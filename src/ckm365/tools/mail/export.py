"""Exporting a message to a file an agent (or a repo) can live with.

The format comes from the destination extension, and the .md record is an
Open Knowledge Format v0.1 document — see export_message.
"""

import logging
from pathlib import Path

from ... import __version__
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


def _tags(message: Message, mailbox: str) -> list[str]:
    """OKF tags: the facets worth filtering a knowledge repo on.

    Direction is OMITTED rather than guessed when Graph gives no sender —
    an unsent draft has no `from` yet, and calling that "inbound" would be
    a lie in the one field an index would group on.
    """
    sender = (message.sender.address if message.sender else "").lower()
    headers = message.headers
    return ["email"] + [tag for tag, on in (
        ("outbound", bool(sender) and sender == mailbox.lower()),
        ("inbound", bool(sender) and sender != mailbox.lower()),
        ("attachments", message.has_attachments),
        ("bulk", bool(headers and headers.is_bulk)),
        ("auto-reply", bool(headers and headers.is_auto_reply))) if on]


def _record(message: Message, attachments: list[Attachment], mailbox: str,
            version: str) -> str:
    """Render the greppable record: front matter, body, attachment manifest.

    The front matter is Open Knowledge Format v0.1 (openknowledgeformat.com):
    OKF is markdown + YAML front matter with a required `type` and
    recommended title/description/resource/tags/timestamp, and it allows
    extension keys — so the mail-specific fields ride along underneath and
    the file drops into an `okf/` repo unmodified. Where OKF has a name for
    something we would have invented one for (title, timestamp, resource),
    OKF's name wins; nothing is written twice.
    """
    headers = message.headers
    front = {
        # OKF v0.1 core
        "type": "Email",
        "title": message.subject or "(no subject)",
        "description": _yaml_description(message),
        "resource": message.web_link,
        "tags": _tags(message, mailbox),
        "timestamp": message.received,
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
        "exported_by": f"ckm365 {version}",
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
      reach for by default. It is an Open Knowledge Format v0.1 document
      (openknowledgeformat.com): YAML front matter carrying OKF's
      type/title/description/resource/tags/timestamp plus mail-specific
      extension keys (from, to, cc, mailbox, message ids, bulk and
      auto-reply flags), then the body as PLAIN TEXT, then a manifest of
      the attachments with their attachment_ids. So it drops into an
      `okf/` repo unmodified — `tags` carries the facets worth filtering
      on (email, inbound/outbound, attachments, bulk, auto-reply).
      Deterministic, so re-exporting the same message produces the same
      file and git shows no diff.
    - `.eml` — the raw MIME exactly as Graph serves it: full fidelity
      (every header, HTML part and attachment bytes inline), the right
      choice for an evidence archive. NOT reliably greppable: Exchange
      base64-encodes body parts, so a word in the message may appear
      nowhere in the file. Do not use it as the searchable copy.

    Attachment BYTES are never written by either format — the record names
    them and carries their ids; download_attachment fetches them.

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
        record = _record(message, items, mb, __version__).encode("utf-8")
        written = write_atomic(dest, lambda part: part.write_bytes(record))
        count = len(items)
    log.info("tool=export_message mailbox=%r message_id=%r format=%s bytes=%d",
             mb, message_id, suffix.lstrip("."), written)
    return {"path": str(dest), "bytes": written, "format": suffix.lstrip("."),
            "attachments": count}
