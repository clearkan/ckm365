"""Mail tools. Reads are plain; writes are draft-only and gated by Ctx.

Replies/forwards are ALWAYS seeded via Graph createReply/createReplyAll/
createForward so Graph assembles the quoted history and threading headers;
we then PATCH our content into the top of the returned draft. Delivered
(non-draft) messages are never modified. Nothing here sends mail.

TRIAGE TOOLS (CKM-33/34/35/36) are the one exception to "never modify
delivered messages": read state, flags, and folder are message METADATA,
not content — changing them is what a mail client does, and none of it
alters the message itself or sends anything. They are write-tier
(Mail.ReadWrite, already in the delegated read-write scope set) and they
are BATCHED: a triage pass touches tens of messages at once, so every one
of them takes a LIST of ids, reports per-id outcomes, and never lets one
404 strand the rest of the batch.
"""

import base64
import logging
import mimetypes
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from ..graph import Graph, GraphError, encode_segment as _seg, mailbox_path as _path
from ..models import Attachment, Body, Draft, MailFolder, Message, MessageSummary
from .context import Ctx, pull

log = logging.getLogger("ckm365")

_BODY_TAG = re.compile(r"<body[^>]*>", re.IGNORECASE)
_MAX_DIRECT_ATTACHMENT = 3 * 1024 * 1024  # Graph direct-attach limit; bigger
                                          # files need upload sessions (phase 2)
_MAX_BATCH_IDS = 200  # one triage call = at most 10 Graph batches
_MAX_SCAN = 10000     # ceiling on a group_by_sender folder walk
# Graph takes IANA ("Europe/London") or Windows ("GMT Standard Time") zone
# names; this only keeps junk out of the request body (cf. calendar._TZ_RE).
_TZ_RE = re.compile(r"[A-Za-z0-9_+/ -]{1,64}")


def _prefer(body_format: str) -> dict[str, str]:
    if body_format not in ("text", "html"):
        raise ValueError("body_format must be 'text' or 'html'")
    return {"Prefer": f'outlook.body-content-type="{body_format}"'}


def _addrs(addresses: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": a}} for a in addresses]


def _prepended(existing: Body | None, new_html: str) -> dict:
    """Insert new_html at the top of a draft body Graph assembled for us."""
    content = existing.content if existing else ""
    m = _BODY_TAG.search(content)
    i = m.end() if m else 0
    return {"contentType": "html", "content": content[:i] + new_html + content[i:]}


def _message_path(mailbox: str, message_id: str, suffix: str = "") -> str:
    return _path(mailbox, f"messages/{_seg(message_id, 'message_id')}{suffix}")


def _require_draft(g: Graph, path: str, verb: str,
                   select: str = "id,isDraft") -> dict:
    """The draft-only invariant lives here: fetch and refuse non-drafts."""
    current = g.get(path, params={"$select": select})
    if not current.get("isDraft"):
        raise ValueError(f"refusing to {verb} a non-draft message")
    return current


def _etag_header(data: dict) -> dict[str, str] | None:
    """If-Match narrows the isDraft check-then-act window: an intervening
    change 412s instead of patching a message that is no longer a draft."""
    etag = data.get("@odata.etag")
    return {"If-Match": etag} if etag else None


def _odata_str(value: str, name: str) -> str:
    """One OData string literal's contents: single quotes are doubled."""
    v = (value or "").strip()
    if not v or any(ord(c) < 32 or ord(c) == 127 for c in v):
        raise ValueError(f"invalid {name}: {v[:60]!r}")
    return v.replace("'", "''")


def _odata_datetime(value: str, name: str) -> str:
    """ISO date or datetime → the zoned literal Graph compares against.

    A value with no offset is read as UTC (documented on every caller): for
    a receivedDateTime floor that is at most a few hours of slack, unlike a
    flag due date where the same guess is wrong by up to a day.
    """
    try:
        dt = datetime.fromisoformat((value or "").strip())
    except ValueError as exc:
        raise ValueError(
            f"{name} must be an ISO 8601 date or datetime "
            f"(e.g. '2026-08-01' or '2026-08-01T09:00:00Z'), got {value!r}"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _predicates(*, unread_only: bool = False, flagged_only: bool = False,
                since: str | None = None, from_address: str | None = None,
                filter: str | None = None) -> str | None:
    """Compose the first-class predicates into ONE server-side $filter.

    Every one of these pushes to Graph — none degrades into a client-side
    scan, which is the whole point (CKM-35: classifying 6000 messages
    locally to find 20 blew a tool timeout). A raw `filter` is ANDed in
    parentheses so the escape hatch composes instead of competing.
    """
    clauses = []
    if unread_only:
        clauses.append("isRead eq false")
    if flagged_only:
        clauses.append("flag/flagStatus eq 'flagged'")
    if since:
        clauses.append(f"receivedDateTime ge {_odata_datetime(since, 'since')}")
    if from_address:
        clauses.append("from/emailAddress/address eq "
                       f"'{_odata_str(from_address, 'from_address')}'")
    if filter:
        clauses.append(f"({filter})")
    return " and ".join(clauses) or None


def list_messages(ctx: Ctx, *, folder: str = "inbox", search: str | None = None,
                  filter: str | None = None, unread_only: bool = False,
                  flagged_only: bool = False, since: str | None = None,
                  from_address: str | None = None, top: int = 25,
                  account: str | None = None,
                  mailbox: str | None = None) -> list[MessageSummary]:
    """List messages in a mail folder, newest first.

    PREFER THE NAMED PREDICATES over a hand-written filter: unread_only,
    flagged_only, since (ISO date/datetime — bare values are read as UTC),
    and from_address all become ONE server-side $filter, ANDed together, so
    Graph does the selecting and only matches cross into your context.
    `filter` stays as the OData escape hatch for anything not covered and
    is ANDed in alongside them.

    Two Graph behaviours worth knowing before you plan a query:
    - search (KQL, e.g. 'from:alice subject:invoice') CANNOT be combined
      with any filter or predicate — pick one.
    - ANY filter drops the newest-first ordering: Graph returns filtered
      results in its own default order and rejects most $orderby
      combinations, so `top` then means "N matches", not "the N newest".
      Narrow with `since` if recency matters.

    folder takes a well-known name (inbox, archive, drafts, sentitems, ...)
    or a folder id from list_mail_folders. Transient Graph 503s
    (ErrorInternalServerTransientError, common on large mailboxes) are
    retried inside the client — a filter that works on the second attempt
    never surfaces here as a failure.
    """
    predicates = _predicates(unread_only=unread_only, flagged_only=flagged_only,
                             since=since, from_address=from_address,
                             filter=filter)
    if search and predicates:
        raise ValueError("search cannot be combined with filter, unread_only, "
                         "flagged_only, since or from_address")
    if not 1 <= top <= 500:
        raise ValueError("top must be between 1 and 500")
    g, mb = ctx.target(account, mailbox)
    params = {"$select": MessageSummary.SELECT, "$top": str(min(top, 100))}
    if search:
        escaped = search.replace("\\", "\\\\").replace('"', '\\"')
        params["$search"] = f'"{escaped}"'
    elif predicates:
        params["$filter"] = predicates
    else:
        params["$orderby"] = "receivedDateTime desc"
    path = _path(mb, f"mailFolders/{_seg(folder, 'folder')}/messages")
    return pull(g, MessageSummary, path, params=params, top=top)


def group_by_sender(ctx: Ctx, *, folder: str = "inbox", since: str | None = None,
                    max_scan: int = 2000, account: str | None = None,
                    mailbox: str | None = None) -> dict:
    """Count messages per sender in a folder — who actually generates the volume.

    Answers "which senders fill this mailbox" in ONE call, without any
    message crossing into your context: the scan projects sender and read
    state only — no subjects, previews or bodies — and returns counts.
    (Establishing that six automated senders were ~40% of an inbox
    previously cost 1500 messages of context; this is that call.)

    Returns {"senders": [{"address", "name", "total", "unread"}, ...]
    sorted by total descending, "scanned": how many messages were walked,
    "truncated": whether max_scan cut the walk short, "folder", "since"}.
    A truncated result is still useful but is NOT the whole folder — raise
    max_scan or narrow `since` before drawing conclusions from it.

    since is an ISO date/datetime (bare values are read as UTC) and filters
    server-side. Note that filtering drops Graph's newest-first ordering, so
    a TRUNCATED scan is an arbitrary slice of the matches, not the newest N.
    """
    if not 1 <= max_scan <= _MAX_SCAN:
        raise ValueError(f"max_scan must be between 1 and {_MAX_SCAN}")
    g, mb = ctx.target(account, mailbox)
    params = {"$select": "from,isRead", "$top": "100"}
    predicates = _predicates(since=since)
    if predicates:
        params["$filter"] = predicates
    else:
        params["$orderby"] = "receivedDateTime desc"
    path = _path(mb, f"mailFolders/{_seg(folder, 'folder')}/messages")
    counts: dict[str, dict] = {}
    scanned = 0
    for item in g.paged(path, params=params, max_items=max_scan):
        scanned += 1
        who = (item.get("from") or {}).get("emailAddress") or {}
        address = (who.get("address") or "").lower() or "(unknown sender)"
        entry = counts.setdefault(address, {"address": address,
                                            "name": who.get("name") or "",
                                            "total": 0, "unread": 0})
        entry["total"] += 1
        entry["unread"] += 0 if item.get("isRead") else 1
    log.info("tool=group_by_sender mailbox=%r folder=%r scanned=%d senders=%d",
             mb, folder, scanned, len(counts))
    return {"senders": sorted(counts.values(),
                              key=lambda e: (-e["total"], e["address"])),
            "scanned": scanned, "truncated": scanned >= max_scan,
            "folder": folder, "since": since}


def get_message(ctx: Ctx, message_id: str, *, body_format: str = "text",
                account: str | None = None,
                mailbox: str | None = None) -> Message:
    """Fetch one message including its body (body_format: 'text' or 'html')."""
    g, mb = ctx.target(account, mailbox)
    data = g.get(_message_path(mb, message_id),
                 params={"$select": Message.SELECT}, headers=_prefer(body_format))
    return Message.from_graph(data)


def list_mail_folders(ctx: Ctx, *, account: str | None = None,
                      mailbox: str | None = None) -> list[MailFolder]:
    """List top-level mail folders with item/unread counts."""
    g, mb = ctx.target(account, mailbox)
    params = {"$select": MailFolder.SELECT, "$top": "100"}
    return pull(g, MailFolder, _path(mb, "mailFolders"), params=params, top=200)


def list_attachments(ctx: Ctx, message_id: str, *, account: str | None = None,
                     mailbox: str | None = None) -> list[Attachment]:
    """List a message's attachment metadata (name, type, size — never content)."""
    g, mb = ctx.target(account, mailbox)
    return pull(g, Attachment, _message_path(mb, message_id, "/attachments"),
                params={"$select": Attachment.SELECT}, top=100)


def add_attachment(ctx: Ctx, message_id: str, file_path: str, *,
                   account: str | None = None,
                   mailbox: str | None = None) -> Attachment:
    """Attach a local file to a DRAFT (max 3 MB). The file is read by the
    server process on this machine; refuses non-draft messages. If the
    CKM365_ATTACH_ROOT env var is set, only files under that directory
    can be attached."""
    ctx.require_write()
    source = Path(file_path).expanduser().resolve()
    root = os.environ.get("CKM365_ATTACH_ROOT")
    if root and not source.is_relative_to(Path(root).expanduser().resolve()):
        raise ValueError(f"attachment path is outside CKM365_ATTACH_ROOT "
                         f"({root}); refusing to read it")
    data = source.read_bytes()
    if len(data) > _MAX_DIRECT_ATTACHMENT:
        raise ValueError("attachment exceeds the 3 MB direct-attach limit "
                         "(upload sessions are not supported yet)")
    g, mb = ctx.target(account, mailbox)
    path = _message_path(mb, message_id)
    _require_draft(g, path, "attach to")
    payload = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": source.name,
        "contentType": mimetypes.guess_type(source.name)[0]
        or "application/octet-stream",
        "contentBytes": base64.b64encode(data).decode("ascii"),
    }
    created = g.post(path + "/attachments", json=payload)
    return Attachment.from_graph(created)


def _insert_top(g: Graph, mb: str, draft_id: str, body_html: str) -> Draft:
    path = _message_path(mb, draft_id)
    data = g.get(path, params={"$select": Draft.SELECT}, headers=_prefer("html"))
    current = Draft.from_graph(data)
    if not body_html:
        return current
    patched = g.patch(path, json={"body": _prepended(current.body, body_html)},
                      params={"$select": Draft.SELECT},
                      headers=_etag_header(data))
    return Draft.from_graph(patched)


def create_reply_draft(ctx: Ctx, message_id: str, body_html: str = "", *,
                       reply_all: bool = False, account: str | None = None,
                       mailbox: str | None = None) -> Draft:
    """Create a reply (or reply-all) draft seeded by Graph with the quoted
    history and threading headers, inserting body_html at the top. Never sends."""
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    action = "createReplyAll" if reply_all else "createReply"
    created = g.post(_message_path(mb, message_id, f"/{action}")) or {}
    return _insert_top(g, mb, created["id"], body_html)


def create_forward_draft(ctx: Ctx, message_id: str, to: list[str],
                         body_html: str = "", *, account: str | None = None,
                         mailbox: str | None = None) -> Draft:
    """Create a forward draft with the quoted original; recipients are set in
    the createForward call itself (never patched later). Never sends."""
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    created = g.post(_message_path(mb, message_id, "/createForward"),
                     json={"toRecipients": _addrs(to)}) or {}
    return _insert_top(g, mb, created["id"], body_html)


def update_draft(ctx: Ctx, message_id: str, *, subject: str | None = None,
                 body_html: str | None = None, to: list[str] | None = None,
                 cc: list[str] | None = None, bcc: list[str] | None = None,
                 account: str | None = None,
                 mailbox: str | None = None) -> Draft:
    """Update fields on an existing draft. body_html REPLACES the whole body
    (any quoted history is lost — use create_reply_draft to keep it).
    Refuses to touch non-draft messages."""
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    path = _message_path(mb, message_id)
    current = _require_draft(g, path, "modify")
    patch: dict = {}
    if subject is not None:
        patch["subject"] = subject
    if body_html is not None:
        patch["body"] = {"contentType": "html", "content": body_html}
    for key, value in (("toRecipients", to), ("ccRecipients", cc),
                       ("bccRecipients", bcc)):
        if value is not None:
            patch[key] = _addrs(value)
    if not patch:
        raise ValueError("nothing to update")
    return Draft.from_graph(
        g.patch(path, json=patch, params={"$select": Draft.SELECT},
                headers=_etag_header(current)))


def create_draft(ctx: Ctx, *, to: list[str], subject: str, body_html: str,
                 cc: list[str] | None = None,
                 bcc: list[str] | None = None, account: str | None = None,
                 mailbox: str | None = None) -> Draft:
    """Create a brand-new draft (not a reply or forward). Never sends."""
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    message: dict = {
        "subject": subject,
        "body": {"contentType": "html", "content": body_html},
        "toRecipients": _addrs(to),
    }
    if cc:
        message["ccRecipients"] = _addrs(cc)
    if bcc:
        message["bccRecipients"] = _addrs(bcc)
    created = g.post(_path(mb, "messages"), json=message)
    return Draft.from_graph(created)


def send_draft(ctx: Ctx, message_id: str, *, account: str | None = None,
               mailbox: str | None = None) -> dict:
    """Send an existing draft. Refuses non-drafts and drafts with no
    recipients. Requires the server to run with --write AND --enable-send;
    the profile needs Mail.Send consent (ckm365 login <profile> --send)
    and must not set allow_send = false."""
    ctx.require_send(account)
    g, mb = ctx.target(account, mailbox)
    path = _message_path(mb, message_id)
    current = _require_draft(g, path, "send",
                             select="id,isDraft,toRecipients,ccRecipients")
    recipients = (len(current.get("toRecipients") or [])
                  + len(current.get("ccRecipients") or []))
    if not recipients:
        raise ValueError("refusing to send: draft has no recipients")
    g.post(path + "/send")
    log.info("tool=send_draft SENT mailbox=%r message_id=%r recipients=%d",
             mb, message_id, recipients)
    return {"sent": True, "message_id": message_id, "recipients": recipients}


# --- triage: read state, flags, filing (CKM-33/34/36) ----------------------
#
# One convention for all six tools: take a LIST of message ids, run them
# through Graph's /$batch endpoint (20 sub-requests per round trip, so 25
# messages cost 2 calls instead of 25), and return
# {"ok": <distinct messages changed>, "failed": [{"id", "error"}, ...]}.
# A per-message failure is reported and the batch continues — one message
# moved out from under the caller must never strand the other 24.


def _batch_ids(message_ids: list[str]) -> list[str]:
    """Validate and de-duplicate the id list every triage tool takes.

    Duplicates collapse (patching one message twice in a batch is
    pointless), so "ok" counts DISTINCT messages and may be lower than the
    number of ids passed in.
    """
    if isinstance(message_ids, str):  # a bare id is the obvious LLM mistake,
        raise ValueError(            # and would otherwise batch its letters
            "message_ids must be a LIST of message ids, not a single string")
    ids = list(dict.fromkeys((m or "").strip() for m in message_ids or []))
    if not ids:
        raise ValueError("message_ids is empty")
    if len(ids) > _MAX_BATCH_IDS:
        raise ValueError(f"at most {_MAX_BATCH_IDS} message ids per call, got "
                         f"{len(ids)} — split it into several calls")
    for message_id in ids:
        _seg(message_id, "message_id")  # reject junk before any Graph call
    return ids


def _batch_error(result: dict) -> str:
    err = (result.get("body") or {}).get("error") or {}
    detail = f"{err.get('code') or ''} {err.get('message') or ''}".strip()
    return f"{result['status']} {detail}".strip()[:200]


def _apply_each(g: Graph, mb: str, ids: list[str], method: str,
                suffix: str = "", body: dict | None = None
                ) -> tuple[list[tuple[str, dict]], list[dict]]:
    """Run one Graph call per message id through /$batch; split the outcome
    into (succeeded [(id, response body)], failed [{"id", "error"}])."""
    results = g.batch([{"method": method, "url": _message_path(mb, i, suffix),
                        **({"body": body} if body is not None else {})}
                       for i in ids])
    ok: list[tuple[str, dict]] = []
    failed: list[dict] = []
    for message_id, result in zip(ids, results):
        if 200 <= result["status"] < 300:
            ok.append((message_id, result["body"] or {}))
        else:
            failed.append({"id": message_id, "error": _batch_error(result)})
    return ok, failed


def _outcome(tool: str, mb: str, ok: list, failed: list, **extra) -> dict:
    log.info("tool=%s mailbox=%r ok=%d failed=%d", tool, mb, len(ok), len(failed))
    return {"ok": len(ok), "failed": failed, **extra}


def _set_read(ctx: Ctx, tool: str, message_ids: list[str], is_read: bool,
              account: str | None, mailbox: str | None) -> dict:
    ctx.require_write()
    ids = _batch_ids(message_ids)
    g, mb = ctx.target(account, mailbox)
    ok, failed = _apply_each(g, mb, ids, "PATCH", body={"isRead": is_read})
    return _outcome(tool, mb, ok, failed)


def mark_read(ctx: Ctx, message_ids: list[str], *, account: str | None = None,
              mailbox: str | None = None) -> dict:
    """Mark messages as READ, in one batch. Pass a list even for one id.

    Read state is independent of folder: the mail stays exactly where it
    is. Select the messages first (list_messages with unread_only=True,
    since, from_address ...) and pass their ids here, so the selection is
    explicit and auditable — no tool changes read state from a filter.

    Returns {"ok": how many messages changed, "failed": [{"id", "error"}]}.
    Failures are per message and never abort the batch. Up to 200 ids per
    call, sent 20 at a time via Graph's /$batch endpoint.
    """
    return _set_read(ctx, "mark_read", message_ids, True, account, mailbox)


def mark_unread(ctx: Ctx, message_ids: list[str], *, account: str | None = None,
                mailbox: str | None = None) -> dict:
    """Mark messages as UNREAD, in one batch (the inverse of mark_read).

    Same shape and batching as mark_read: a list of ids, /$batch under the
    hood, {"ok", "failed": [{"id", "error"}]} back, partial failure
    tolerated.
    """
    return _set_read(ctx, "mark_unread", message_ids, False, account, mailbox)


def _now_utc() -> dict[str, str]:
    return {"dateTime": datetime.now(UTC).replace(
        tzinfo=None, microsecond=0).isoformat(), "timeZone": "UTC"}


def _flag_when(value: str, zone: str | None, name: str) -> tuple[dict[str, str], str]:
    """Caller ISO string → Graph's {dateTime, timeZone}, plus the zone used.

    An explicit offset ('...Z' or '+01:00') wins and normalises to UTC. A
    bare date or naive datetime NEVER silently becomes UTC — "due today" in
    the wrong zone is wrong by up to a day — so an unresolvable zone is an
    error that says how to supply one.
    """
    try:
        when = datetime.fromisoformat((value or "").strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO 8601 date or datetime "
                         f"(e.g. '2026-08-10' or '2026-08-10T17:00:00+01:00'), "
                         f"got {value!r}") from exc
    if when.tzinfo is not None:
        return {"dateTime": when.astimezone(UTC).replace(tzinfo=None)
                .isoformat(timespec="seconds"), "timeZone": "UTC"}, "UTC"
    if not zone:
        raise ValueError(
            f"{name}={value!r} carries no timezone, and a flag date in the "
            "wrong zone is wrong by up to a day — so it is never guessed. "
            "Either pass an offset ('2026-08-10T17:00:00+01:00'), or pass "
            "timezone='Europe/London', or set timezone on the profile in "
            "profiles.toml.")
    if not _TZ_RE.fullmatch(zone):
        raise ValueError(f"invalid timezone name: {zone[:60]!r}")
    return {"dateTime": when.isoformat(timespec="seconds"), "timeZone": zone}, zone


def flag(ctx: Ctx, message_ids: list[str], *, due: str | None = None,
         start: str | None = None, timezone: str | None = None,
         account: str | None = None, mailbox: str | None = None) -> dict:
    """Flag messages for follow-up, in one batch. A flag with NO date is the
    common case and the default — never invent a date to mark something.

    due/start are ISO 8601 dates or datetimes. Graph wants a start
    alongside a due date, so supplying only `due` sets start to now rather
    than failing. Timezone resolution, in order: an offset in the value
    itself ('2026-08-10T17:00:00+01:00', normalised to UTC) → the
    `timezone` argument (IANA like 'Europe/London', or the Windows name
    Graph also accepts) → the profile's `timezone` in profiles.toml. A bare
    date with none of those is an ERROR, not a UTC guess. The zone actually
    used comes back in the result.

    Returns {"ok", "failed": [{"id", "error"}], "timezone": zone or null}.
    Find flagged mail again with list_messages(flagged_only=True). Use
    complete_flag for "done" and unflag for "never mind" — they are
    different outcomes and a triage log wants to tell them apart.
    """
    ctx.require_write()
    ids = _batch_ids(message_ids)
    zone = timezone or ctx.profile(account).timezone
    payload: dict = {"flagStatus": "flagged"}
    used: str | None = None
    if start:
        payload["startDateTime"], used = _flag_when(start, zone, "start")
    if due:
        payload["dueDateTime"], used = _flag_when(due, zone, "due")
        payload.setdefault("startDateTime", _now_utc())
    g, mb = ctx.target(account, mailbox)
    ok, failed = _apply_each(g, mb, ids, "PATCH", body={"flag": payload})
    return _outcome("flag", mb, ok, failed, timezone=used)


def unflag(ctx: Ctx, message_ids: list[str], *, account: str | None = None,
           mailbox: str | None = None) -> dict:
    """Clear the follow-up flag on messages ("never mind"), in one batch.

    Sets flagStatus back to notFlagged and drops any dates. For "I finished
    this" use complete_flag instead — it keeps the message in the completed
    queue rather than erasing that it was ever flagged. Same batching and
    {"ok", "failed"} shape as mark_read.
    """
    ctx.require_write()
    ids = _batch_ids(message_ids)
    g, mb = ctx.target(account, mailbox)
    ok, failed = _apply_each(g, mb, ids, "PATCH",
                             body={"flag": {"flagStatus": "notFlagged"}})
    return _outcome("unflag", mb, ok, failed)


def complete_flag(ctx: Ctx, message_ids: list[str], *,
                  account: str | None = None,
                  mailbox: str | None = None) -> dict:
    """Mark flagged messages as DONE, in one batch: flagStatus complete plus
    a completion timestamp (now, UTC).

    Distinct from unflag: "done" and "never mind" are different triage
    outcomes. Completed messages drop out of list_messages(flagged_only=True),
    which matches only the still-outstanding queue. Same batching and
    {"ok", "failed"} shape as mark_read.
    """
    ctx.require_write()
    ids = _batch_ids(message_ids)
    g, mb = ctx.target(account, mailbox)
    ok, failed = _apply_each(g, mb, ids, "PATCH", body={"flag": {
        "flagStatus": "complete", "completedDateTime": _now_utc()}})
    return _outcome("complete_flag", mb, ok, failed)


def _resolve_destination(g: Graph, mb: str, destination: str) -> str:
    """Check the destination folder EXISTS before moving anything.

    Graph's move never creates folders, and an unresolvable destination
    would otherwise fail once per message with an opaque id error. One
    lookup up front turns that into a single actionable message naming the
    folders that do exist.
    """
    dest = (destination or "").strip()
    if not dest:
        raise ValueError("destination is required")
    try:
        g.get(_path(mb, f"mailFolders/{_seg(dest, 'destination')}"),
              params={"$select": "id"})
    except GraphError as exc:
        if not 400 <= exc.status < 500:
            raise
        known = ", ".join(f.name for f in pull(
            g, MailFolder, _path(mb, "mailFolders"),
            params={"$select": MailFolder.SELECT, "$top": "100"}, top=100))
        raise ValueError(
            f"unknown destination {dest!r} — move_message never creates "
            "folders. Use a well-known name (archive, deleteditems, inbox, "
            "junkemail, drafts, sentitems) or a folder id from "
            f"list_mail_folders. Top-level folders here: {known[:400]}") from exc
    return dest


def move_message(ctx: Ctx, message_ids: list[str], destination: str, *,
                 account: str | None = None, mailbox: str | None = None) -> dict:
    """File messages into another folder, in one batch.

    destination is a well-known name (archive, deleteditems, inbox,
    junkemail, drafts, sentitems, ...) or a folder id from
    list_mail_folders — the same convention as list_messages' folder
    argument. An unknown destination is an ERROR listing the folders that
    exist: this tool never creates a folder as a side effect.

    A move gives the message a NEW id in the destination folder, so the old
    id becomes a dead reference. The result carries the mapping:
    {"ok", "failed": [{"id", "error"}], "moved": {old_id: new_id},
    "destination"}. Use the new ids for anything afterwards.

    Deletion is deliberately NOT offered. Moving to "deleteditems" is
    reachable here and is reversible; permanent deletion is not, and does
    not belong in an agent-callable surface.
    """
    ctx.require_write()
    ids = _batch_ids(message_ids)
    g, mb = ctx.target(account, mailbox)
    dest = _resolve_destination(g, mb, destination)
    ok, failed = _apply_each(g, mb, ids, "POST", "/move",
                             {"destinationId": dest})
    return _outcome("move_message", mb, ok, failed, destination=dest,
                    moved={old: body.get("id") or "" for old, body in ok})
