"""Reading mail: listings, one message, headers, folders, sender counts.

Every predicate here pushes into ONE server-side $filter — none degrades
into a client-side scan (CKM-35: classifying 6000 messages locally to
find 20 blew a tool timeout).
"""

import logging
from dataclasses import asdict
from datetime import UTC, datetime

from ...graph import encode_segment as _seg, mailbox_path as _path
from ...models import (MailFolder, MessageHeaders, Message, MessageSummary)
from ..context import Ctx, pull
from .common import apply_each, message_path, outcome, prefer, batch_ids

log = logging.getLogger("ckm365")


_MAX_SCAN = 10000     # ceiling on a group_by_sender folder walk
# Graph takes IANA ("Europe/London") or Windows ("GMT Standard Time") zone
# names; this only keeps junk out of the request body (cf. calendar._TZ_RE).
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

    Three Graph behaviours worth knowing before you plan a query:
    - search (KQL, e.g. 'from:alice subject:invoice') CANNOT be combined
      with any filter or predicate — pick one.
    - MATCHING A SUBJECT: prefer filter="startswith(subject,'...')", and
      distrust the alternatives — they fail SILENTLY, returning zero rows,
      which reads exactly like "no such mail". `subject eq '...'` never
      matches even a byte-identical subject, and `contains(subject,'...')`
      works on a small folder but returns nothing on a large one (proved
      on a 93k-message inbox where startswith matched at once).
    - DO NOT USE ANY SUBJECT FILTER TO FIND MAIL THAT JUST ARRIVED. Those
      predicates read an index that lags delivery — a message delivered at
      23:22:09 was invisible to startswith for another five minutes, then
      found by the same query later. For "has it landed yet", list
      newest-first with NO filter (or `since`, which is indexed with the
      folder view) and match client-side, or use list_new_messages /
      wait_for_message, which are built on delta and see it immediately.
    - ANY filter drops the newest-first ordering: Graph returns filtered
      results in its own default order and rejects most $orderby
      combinations, so `top` then means "N matches", not "the N newest".
      Narrow with `since` if recency matters.

    folder takes a well-known name (inbox, archive, drafts, sentitems, ...)
    or a folder id from list_mail_folders. Transient Graph 503s
    (ErrorInternalServerTransientError, common on large mailboxes) are
    retried inside the client — a filter that works on the second attempt
    never surfaces here as a failure.

    Each row carries `to` and `cc` alongside `sender`, which answers two
    questions sender alone cannot:
    - in sentitems the sender is always the mailbox owner, so `to` is the
      correspondent — this is how you learn who someone actually emails;
    - in a mailbox shared by two parties, the address a message was
      DELIVERED to is the strongest signal for which party it belongs to.
      Treat it as a signal, not proof: a message can arrive via a
      distribution list or bcc with the alias nowhere in `to`.
    bcc is deliberately absent (it exists only on the sender's own copy —
    get_message returns it), as are the internet headers, which cost ~10 KB
    per message; get_message_headers fetches those deliberately.
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
    """Fetch one message including its body (body_format: 'text' or 'html').

    Also carries `bcc` (populated only on the sender's own copy) and
    `headers` — the curated internet headers described on
    get_message_headers, which is the tool to use for MANY messages.
    """
    g, mb = ctx.target(account, mailbox)
    data = g.get(message_path(mb, message_id),
                 params={"$select": Message.SELECT}, headers=prefer(body_format))
    return Message.from_graph(data)


def get_message_headers(ctx: Ctx, message_ids: list[str], *,
                        account: str | None = None,
                        mailbox: str | None = None) -> dict:
    """Curated internet headers for messages: is this bulk, or automated?

    Answers definitively what a subject regex only guesses, and it guesses
    wrong both ways — missing bulk mail sent from a named person's address,
    misfiring on ordinary mail. Per message you get the raw values of
    List-Unsubscribe, List-Id, Precedence, Auto-Submitted,
    X-Auto-Response-Suppress and Return-Path, plus two DERIVED flags:
      is_bulk       — List-Unsubscribe or List-Id present, or Precedence
                      bulk/list/junk. Bulk senders are obliged to set these.
      is_auto_reply — Auto-Submitted says auto-replied (an out-of-office,
                      which otherwise looks exactly like a real reply) or
                      auto-generated, or X-Auto-Response-Suppress is set.
    The raw values stay alongside the flags so you can audit or override
    the derivation rather than trusting it blindly.

    THESE VALUES ARE UNTRUSTED. Anyone can write any header: a forged
    List-Unsubscribe proves only that someone wrote one. Use them to
    classify and prioritise — never to authorise, authenticate, or decide
    that a message is trustworthy. Values are stripped of control
    characters and capped at 200 characters (a trailing '…' marks a cut).

    COSTS ONE GRAPH FETCH PER MESSAGE, batched 20 to a round trip: the
    full header bag is ~50 headers and ~10 KB per message on the wire,
    which is why list_messages does not carry it. Curation happens here,
    so only the fields above cross into your context. Pass a list even for
    one id; up to 200 ids per call.

    Returns {"ok": how many messages answered, "headers": {message_id:
    {...}}, "failed": [{"id", "error"}]} — a per-message failure never
    aborts the batch.
    """
    ids = batch_ids(message_ids)
    g, mb = ctx.target(account, mailbox)
    ok, failed = apply_each(g, mb, ids, "GET",
                            f"?$select={MessageHeaders.SELECT}")
    return outcome("get_message_headers", mb, ok, failed,
                   headers={message_id: asdict(MessageHeaders.from_graph(body))
                             for message_id, body in ok})


def list_mail_folders(ctx: Ctx, *, account: str | None = None,
                      mailbox: str | None = None) -> list[MailFolder]:
    """List top-level mail folders with item/unread counts."""
    g, mb = ctx.target(account, mailbox)
    params = {"$select": MailFolder.SELECT, "$top": "100"}
    return pull(g, MailFolder, _path(mb, "mailFolders"), params=params, top=200)
