"""Bulk correspondence export to a local folder, oldest first."""

import hashlib
import logging
import re
from collections import Counter
from pathlib import Path

from ...graph import GraphError, encode_segment as _seg, mailbox_path
from ..context import Ctx
from .attachments import attachments_of, download_attachment
from .common import message_path
from .disk import confine, safe_name
from .export import _already_exported, export_message
from .read import _predicates

log = logging.getLogger("ckm365")
_SELECT = "id,subject,receivedDateTime,internetMessageId,hasAttachments"


def file_stem(subject: str | None, received: str | None,
              internet_message_id: str) -> str:
    """A stable date, subject slug and mailbox-independent Message-ID token."""
    subject = re.sub(r"^(?:(?:re|fw|fwd|aw|wg|sv):\s*)+", "",
                     (subject or "").strip(), flags=re.IGNORECASE)
    slug = re.sub(r"[^a-z0-9]+", "-", subject.lower())[:50].strip("-")
    date = received[:10].replace("-", "") if received else "00000000"
    token = hashlib.sha1(internet_message_id.strip().strip("<>").encode()).hexdigest()[:8]
    return f"{date}_{slug or 'no-subject'}_{token}"


def export_messages(ctx: Ctx, dest_dir: str, *, message_ids: list[str] | None = None,
                    conversation_id: str | None = None, folder: str | None = None,
                    since: str | None = None, from_address: str | None = None,
                    eml: bool = False, attachments: bool = False,
                    full_body: bool = False, max_messages: int = 200,
                    dry_run: bool = False, account: str | None = None,
                    mailbox: str | None = None) -> dict:
    """Write a thread, folder or list of messages into a correspondence folder.

    Give EXACTLY ONE selector: message_ids (a non-empty list),
    conversation_id (the whole thread, across folders), or folder.
    With folder, since and from_address narrow the listing using the
    same predicates as list_messages. They cannot accompany other selectors.
    Messages are exported OLDEST FIRST. When a selector finds more than
    max_messages, which ones make the cut follows Graph's listing order,
    so narrow a big folder with since rather than relying on the cut.

    Each searchable .md record is named YYYYMMDD_<slug>_<token>.md:
    the received date, a lower-case subject with reply/forward prefixes
    removed (at most 50 characters), and 8 hex characters of SHA-1 of
    the Message-ID without angle brackets. This stays stable across runs
    and mailboxes. Missing dates use 00000000, empty subjects no-subject;
    a message without a Message-ID uses its Graph id for the token.
    Message-ID dedupe scans dest_dir: a message already filed under ANY
    name is reported already, with the existing filename, and kept intact.

    eml=true also saves the raw MIME alongside the record. attachments=true
    saves attachment bytes into <stem>/, with inline images named
    inline<N>-<safe_name> to match the record's numbering; existing files stay.
    full_body=true chooses the full body instead of Graph's uniqueBody.
    dry_run=true lists, names and dedupes but writes NOTHING.
    max_messages defaults to 200 (1–1000); truncated says more were found.
    Per-message failures are reported and the remaining messages continue.

    Read tier, no new consent. dest_dir must already exist. The same disk
    fence as export_message applies: CKM365_DOWNLOAD_ROOT (falling back to
    CKM365_ATTACH_ROOT) confines the directory and every write beneath it.
    The root defaults to ~/.local/share/ckm365 (or $XDG_DATA_HOME/ckm365).
    This writes real mail to disk; logs carry counts only, never content.
    """
    if (sum(x is not None for x in (message_ids, conversation_id, folder)) != 1
            or not (message_ids or conversation_id or folder)):
        raise ValueError("give exactly one non-empty message_ids, conversation_id or folder")
    if folder is None and (since is not None or from_address is not None):
        raise ValueError("since and from_address require folder")
    if not 1 <= max_messages <= 1000:
        raise ValueError("max_messages must be between 1 and 1000")
    dest = confine(Path(dest_dir), "dir")
    if not dest.is_dir():
        raise ValueError("dest_dir must be an existing directory")
    params = {"$select": _SELECT}
    if conversation_id is not None:
        params["$filter"] = "conversationId eq '" + conversation_id.replace("'", "''") + "'"
    elif folder is not None:
        predicate = _predicates(since=since, from_address=from_address)
        if predicate:
            params["$filter"] = predicate
    g, mb = ctx.target(account, mailbox)
    failures = []
    if message_ids is not None:
        rows = []
        for mid in message_ids:
            try:
                rows.append(g.get(message_path(mb, mid), params=params))
            except (GraphError, OSError, ValueError) as exc:
                failures.append({"message_id": mid, "internet_message_id": None,
                                 "name": None, "outcome": "failed",
                                 "detail": str(exc), "attachments": 0})
    else:
        suffix = (f"mailFolders/{_seg(folder, 'folder')}/messages"
                  if folder is not None else "messages")
        rows = list(g.paged(mailbox_path(mb, suffix), params={**params, "$top": "100"},
                            max_items=max_messages + 1))
    truncated = len(rows) > max_messages
    rows.sort(key=lambda row: row.get("receivedDateTime") or "")
    results = []
    for row in rows[:max_messages]:
        mid, imid = row["id"], row.get("internetMessageId")
        stem = file_stem(row.get("subject"), row.get("receivedDateTime"), imid or mid)
        result = {"message_id": mid, "internet_message_id": imid,
                  "name": stem + ".md", "outcome": "would-write",
                  "detail": "", "attachments": 0}
        try:
            if dry_run:
                hit = _already_exported(dest, imid) if imid else None
                if hit:
                    result.update(outcome="already", detail=hit.name)
            else:
                exported = export_message(ctx, mid, str(dest / result["name"]),
                                          dedupe_dir=str(dest), full_body=full_body,
                                          account=account, mailbox=mailbox)
                hit = exported.get("already_exported")
                result.update(outcome="already" if hit else "written",
                              detail=Path(hit).name if hit else "")
                # an `already` message is filed under another name: a
                # fresh .eml here would be a second copy of it
                if eml and not hit and not (dest / (stem + ".eml")).exists():
                    export_message(ctx, mid, str(dest / (stem + ".eml")),
                                   dedupe_dir=None, account=account, mailbox=mailbox)
                if attachments:
                    inline_count = 0
                    for attachment in attachments_of(g, mb, mid):
                        directory = confine(dest / stem, "attachment directory")
                        directory.mkdir(exist_ok=True)
                        name = safe_name(attachment.name)
                        if attachment.is_inline:
                            inline_count += 1
                            name = f"inline{inline_count}-{name}"
                        target = directory / name
                        # an embedded message or cloud link has no bytes to
                        # save; the record's manifest still lists it
                        if (attachment.kind not in ("", "fileAttachment")
                                or target.exists()):
                            continue
                        download_attachment(ctx, mid,
                                            str(target if attachment.is_inline
                                                else directory),
                                            attachment_id=attachment.id,
                                            account=account, mailbox=mailbox)
                        result["attachments"] += 1
        except (GraphError, OSError, ValueError) as exc:
            result.update(outcome="failed", detail=str(exc))
        results.append(result)
    results.extend(failures)
    counts = dict(Counter(result["outcome"] for result in results))
    log.info("tool=export_messages counts=%s", counts)
    return {"dir": str(dest), "dry_run": dry_run, "results": results,
            "counts": counts, "truncated": truncated}
