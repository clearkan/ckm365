"""Exporting a message to a file an agent (or a repo) can live with.

The format comes from the destination extension, and the .md record is an
Open Knowledge Format v0.1 document — see export_message.
"""

import logging
from pathlib import Path

from ... import __version__
from ...graph import Graph, GraphError, mailbox_path
from ...models import Attachment, Message
from ..context import Ctx
from .attachments import attachments_of
from .common import message_path, prefer
from .disk import write_atomic, write_target

log = logging.getLogger("ckm365")


# --- export (CKM-39) -------------------------------------------------------
#
# Two formats, chosen by the destination's extension so there is one source
# of truth about what is being written:
#   .eml            raw MIME from Graph, byte-exact, full fidelity
#   .md/.txt        a deterministic record whose body is PLAIN TEXT
# The second exists because raw .eml is not reliably greppable: Exchange
# base64-encodes body parts (measured on real mail — a word from a
# message's own preview was absent from its raw bytes), and a repo full of
# base64 defeats the point of keeping correspondence next to the work.

_EXPORT_TEXT = {".md", ".markdown", ".txt"}
_EXPORT_RAW = {".eml"}


_MAX_DESCRIPTION = 200


def _yaml_value(value) -> str:
    """One YAML value, quoted so a subject full of colons cannot break the
    front matter (and control characters cannot break the file)."""
    if isinstance(value, bool) or value is None:
        return "true" if value is True else "false" if value is False else "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_yaml_value(v) for v in value) + "]"
    if isinstance(value, dict):  # flow style keeps one key per line
        return "{" + ", ".join(f"{k}: {_yaml_value(v)}"
                               for k, v in value.items()) + "}"
    text = "".join(c for c in str(value) if ord(c) >= 32 and ord(c) != 127)
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _who(recipients: list) -> str:
    return ", ".join(f"{r.name} <{r.address}>".strip() if r.name else r.address
                     for r in recipients) or ""


def _yaml_description(message: Message) -> str:
    """OKF's one-line `description`: Graph's own body preview, capped —
    what makes an okf/ index listing readable without opening files.
    Falls back to the body itself, since an OKF document with an empty
    description is a poor citizen of the repo it lands in."""
    text = " ".join((message.preview
                     or (message.body.content if message.body else "")).split())
    return (text[:_MAX_DESCRIPTION - 1] + "…"
            if len(text) > _MAX_DESCRIPTION else text)


def _sent_folder_id(g: Graph, mailbox: str) -> str | None:
    """The mailbox's Sent Items id, or None if it cannot be read.

    Direction is worth one extra GET because the cheap answer is wrong: see
    _tags. A failure here degrades to the old heuristic rather than killing
    an export.
    """
    try:
        return g.get(mailbox_path(mailbox, "mailFolders/sentitems"),
                     params={"$select": "id"}).get("id")
    except GraphError:
        return None


def _tags(message: Message, mailbox: str, sent_folder: str | None) -> list[str]:
    """OKF tags: the facets worth filtering a knowledge repo on.

    Direction is OMITTED rather than guessed when Graph gives no sender —
    an unsent draft has no `from` yet, and calling that "inbound" would be
    a lie in the one field an index would group on.

    WHICH FOLDER IT IS IN WINS over who sent it (CKM-45). Comparing sender
    to mailbox looks obvious and is wrong for Send-As: a message sent AS a
    shared mailbox lands in the HUMAN's Sent Items with the shared mailbox
    as sender, so the sender test tagged the persona's own outbound mail
    `inbound` — and anything filtering an archive on that tag silently got
    the wrong set. Sent Items is authoritative; the sender comparison is
    only the fallback outside it.
    """
    sender = (message.sender.address if message.sender else "").lower()
    in_sent = bool(sent_folder and message.parent_folder_id == sent_folder)
    headers = message.headers
    return ["email"] + [tag for tag, on in (
        ("outbound", in_sent or (bool(sender) and sender == mailbox.lower())),
        ("inbound", not in_sent and bool(sender)
         and sender != mailbox.lower()),
        ("attachments", message.has_attachments),
        ("bulk", bool(headers and headers.is_bulk)),
        ("auto-reply", bool(headers and headers.is_auto_reply))) if on]


def _record(message: Message, attachments: list[Attachment], mailbox: str,
            version: str, sent_folder: str | None = None) -> str:
    """Render the greppable record: front matter, body, attachment manifest.

    The front matter is Open Knowledge Format v0.2 (openknowledgeformat.com):
    OKF is markdown + YAML front matter with a required `type` and
    recommended title/description/resource/tags, and it allows extension
    keys — so the mail-specific fields ride along underneath and the file
    drops into an `okf/` repo unmodified. Where OKF has a name for something
    we would have invented one for, OKF's name wins; nothing is written
    twice.

    WHAT v0.2 CHANGED FOR US, and what it deliberately did not:

    - `timestamp` is gone, replaced by `generated: {by, at}` (v0.2's one
      breaking change that touches this document). `by` follows OKF's actor
      convention, `<producer>/<version>`, which absorbs what used to be the
      `exported_by` extension key — so the upgrade removes a field rather
      than adding one.
    - `at` is the MESSAGE's own time, NOT the moment of export. OKF defines
      it as when the content last meaningfully changed, and this record is a
      pure projection of one immutable message: it cannot change after the
      message arrived. Using export time would be both less true and would
      break the determinism the .md format promises.
    - `sources` is NOT emitted. v0.2 moves citations there, but we never had
      any: the concept IS the email rather than something derived from other
      material, and `resource` already points at it. A `sources` entry would
      restate `resource` and nothing more.
    - `verified` is NOT emitted, which is the honest signal. Its absence
      puts the record in v0.2's "unverified" trust tier, which is exactly
      what a machine export with no human confirmation is.
    - `status`/`stale_after` are NOT emitted: `status` defaults to `stable`,
      and archived mail does not go stale.
    - `okf_version` is NOT emitted. v0.2 declares it in a bundle-root
      index.md, and we write single documents INTO someone else's bundle —
      stamping a version on a leaf file would be claiming authority over a
      bundle we do not own.
    """
    headers = message.headers
    front = {
        # OKF v0.2 core
        "type": "Email",
        "title": message.subject or "(no subject)",
        "description": _yaml_description(message),
        "resource": message.web_link,
        "tags": _tags(message, mailbox, sent_folder),
        "generated": {"by": f"ckm365/{version}", "at": message.received},
        # extension keys: the mail specifics OKF has no opinion about
        "from": _who([message.sender]) if message.sender else "",
        "to": _who(message.to),
        "cc": _who(message.cc),
        "mailbox": mailbox,
        "message_id": message.id,
        "internet_message_id": message.internet_message_id,
        "has_attachments": message.has_attachments,
        "is_bulk": bool(headers and headers.is_bulk),
        "is_auto_reply": bool(headers and headers.is_auto_reply),
    }
    lines = ["---"]
    lines += [f"{k}: {_yaml_value(v)}" for k, v in front.items()]
    lines += ["---", "", f"# {message.subject or '(no subject)'}", "",
              (message.body.content if message.body else "").strip(), ""]
    if attachments:
        lines += ["## Attachments", ""]
        lines += [f"- {a.name or '(unnamed)'} — {a.size} B, {a.kind or 'unknown'}"
                  + (", inline" if a.is_inline else "")
                  + f", attachment_id `{a.id}`" for a in attachments]
        lines += ["",
                  "Fetch the bytes with download_attachment (message_id and "
                  "attachment_id above).", ""]
    return "\n".join(lines)


def export_message(ctx: Ctx, message_id: str, dest_path: str, *,
                   account: str | None = None,
                   mailbox: str | None = None) -> dict:
    """Write one message to a file — the way to keep correspondence in a repo.

    THE FORMAT COMES FROM THE EXTENSION you give dest_path:

    - `.md` / `.markdown` / `.txt` — a GREPPABLE record, and the one to
      reach for by default. It is an Open Knowledge Format v0.2 document
      (openknowledgeformat.com): YAML front matter carrying OKF's
      type/title/description/resource/tags plus `generated` (who produced
      the record and the message's own time), then mail-specific extension
      keys (from, to, cc, mailbox, message ids, bulk and auto-reply
      flags), then the body as PLAIN TEXT, then a manifest of
      the attachments with their attachment_ids. So it drops into an
      `okf/` repo unmodified — `tags` carries the facets worth filtering
      on (email, inbound/outbound, attachments, bulk, auto-reply).
      Deterministic, so re-exporting the same message produces the same
      file and git shows no diff.
      Direction comes from WHICH FOLDER the message is in, falling back to
      `sender == mailbox` outside Sent Items. The folder has to win because
      Send-As breaks the sender test (CKM-45): a message sent as a shared
      mailbox lands in the HUMAN's Sent Items with the shared mailbox as
      sender, and used to come out tagged `inbound`.
    - `.eml` — the raw MIME exactly as Graph serves it: full fidelity
      (every header, HTML part and attachment bytes inline), the right
      choice for an evidence archive. NOT reliably greppable: Exchange
      base64-encodes body parts, so a word in the message may appear
      nowhere in the file. Do not use it as the searchable copy.

    Attachment BYTES are never written by either format — the record names
    them and carries their ids; download_attachment fetches them.

    INLINE IMAGES ARE A BLIND SPOT in the `.md` record (CKM-44). A message
    whose only attachments are inline reports hasAttachments=false, so the
    record lists no manifest and the body keeps bare `[cid:...]` markers —
    it reads as complete while missing the point of the message. This is
    not rare: an annotated slide or a pasted screenshot is often the ENTIRE
    content of a mail. After exporting, call list_attachments (it always
    lists, inline included) and archive those bytes yourself; note that
    inline images routinely share the name "image.png", so download them by
    attachment_id, not by name.

    Read tier, no new consent. Same disk rules as download_attachment: an
    existing file is never overwritten, a failure leaves no residue, and
    CKM365_DOWNLOAD_ROOT (or CKM365_ATTACH_ROOT) confines where the file
    may land. This writes real message content to disk — nothing about
    the message reaches the log, and the body never enters your context
    unless you read the file back.

    Returns {"path", "bytes", "format", "attachments"} — "attachments" is
    how many the record lists, or null for .eml, where they are embedded
    in the MIME itself.
    """
    suffix = Path((dest_path or "").strip()).suffix.lower()
    if suffix not in _EXPORT_TEXT | _EXPORT_RAW:
        raise ValueError(
            f"dest_path must end in {'/'.join(sorted(_EXPORT_TEXT | _EXPORT_RAW))}"
            " — the extension chooses the format (.md for a greppable record, "
            ".eml for raw MIME)")
    g, mb = ctx.target(account, mailbox)
    dest = write_target(dest_path, None)
    count: int | None = None
    if suffix in _EXPORT_RAW:
        written = write_atomic(
            dest, lambda part: g.download(message_path(mb, message_id,
                                                       "/$value"), part))
    else:
        message = Message.from_graph(
            g.get(message_path(mb, message_id),
                  params={"$select": Message.SELECT}, headers=prefer("text")))
        items = attachments_of(g, mb, message_id) if message.has_attachments else []
        record = _record(message, items, mb, __version__,
                         _sent_folder_id(g, mb)).encode("utf-8")
        written = write_atomic(dest, lambda part: part.write_bytes(record))
        count = len(items)
    log.info("tool=export_message mailbox=%r message_id=%r format=%s bytes=%d",
             mb, message_id, suffix.lstrip("."), written)
    return {"path": str(dest), "bytes": written, "format": suffix.lstrip("."),
            "attachments": count}
