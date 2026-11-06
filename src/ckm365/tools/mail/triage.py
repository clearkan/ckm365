"""Triage: read state, flags, filing — message METADATA, never content.

The one exception to "never modify delivered messages": read state, flags
and folder are what a mail client changes, none of it alters the message
or sends anything. Write tier, and BATCHED — a triage pass touches tens
of messages, so each tool takes a LIST of ids and reports per-id
outcomes.
"""

import logging
import re
from datetime import UTC, datetime

from ...graph import (Graph, GraphError, encode_segment as _seg,
                      mailbox_path as _path)
from ...models import MailFolder
from ..context import Ctx, pull
from .common import apply_each, batch_error, batch_ids, message_path, outcome

log = logging.getLogger("ckm365")


_TZ_RE = re.compile(r"[A-Za-z0-9_+/ -]{1,64}")


# --- triage: read state, flags, filing (CKM-33/34/36) ----------------------
#
# One convention for all six tools (and for the read-tier
# get_message_headers above, which borrows the machinery without the
# write gate): take a LIST of message ids, run them
# through Graph's /$batch endpoint (20 sub-requests per round trip, so 25
# messages cost 2 calls instead of 25), and return
# {"ok": <distinct messages changed>, "failed": [{"id", "error"}, ...]}.
# A per-message failure is reported and the batch continues — one message
# moved out from under the caller must never strand the other 24.


def _set_read(ctx: Ctx, tool: str, message_ids: list[str], is_read: bool,
              account: str | None, mailbox: str | None) -> dict:
    ctx.require_write()
    ids = batch_ids(message_ids)
    g, mb = ctx.target(account, mailbox)
    ok, failed = apply_each(g, mb, ids, "PATCH", body={"isRead": is_read})
    return outcome(tool, mb, ok, failed)


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


def _flag_when(value: str, zone: str | None,
               name: str) -> tuple[dict[str, str], str]:
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
    ids = batch_ids(message_ids)
    zone = timezone or ctx.profile(account).timezone
    payload: dict = {"flagStatus": "flagged"}
    used: str | None = None
    if start:
        payload["startDateTime"], used = _flag_when(start, zone, "start")
    if due:
        payload["dueDateTime"], used = _flag_when(due, zone, "due")
        payload.setdefault("startDateTime", _now_utc())
    g, mb = ctx.target(account, mailbox)
    ok, failed = apply_each(g, mb, ids, "PATCH", body={"flag": payload})
    return outcome("flag", mb, ok, failed, timezone=used)


def unflag(ctx: Ctx, message_ids: list[str], *, account: str | None = None,
           mailbox: str | None = None) -> dict:
    """Clear the follow-up flag on messages ("never mind"), in one batch.

    Sets flagStatus back to notFlagged and drops any dates. For "I finished
    this" use complete_flag instead — it keeps the message in the completed
    queue rather than erasing that it was ever flagged. Same batching and
    {"ok", "failed"} shape as mark_read.
    """
    ctx.require_write()
    ids = batch_ids(message_ids)
    g, mb = ctx.target(account, mailbox)
    ok, failed = apply_each(g, mb, ids, "PATCH",
                            body={"flag": {"flagStatus": "notFlagged"}})
    return outcome("unflag", mb, ok, failed)


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
    ids = batch_ids(message_ids)
    g, mb = ctx.target(account, mailbox)
    ok, failed = apply_each(g, mb, ids, "PATCH", body={"flag": {
        "flagStatus": "complete", "completedDateTime": _now_utc()}})
    return outcome("complete_flag", mb, ok, failed)


def set_categories(ctx: Ctx, message_ids: list[str], *,
                   add: list[str] | None = None,
                   remove: list[str] | None = None,
                   account: str | None = None,
                   mailbox: str | None = None) -> dict:
    """Add or remove Outlook categories on messages. Pass a LIST even for
    one id. Categories are message METADATA, like flags, never content;
    this is write tier and sends nothing.

    Select messages first, then pass up to 200 ids. Names are stripped,
    must be 1-255 characters, and match case-insensitively. Duplicates
    keep the first spelling; a name cannot be both added and removed.
    Existing names keep their spelling and order; new names go on the end.

    Graph replaces the whole category list, so this reads, merges, then
    PATCHes only changed messages, 20 at a time via /$batch. Last write
    wins: an Outlook edit between the read and write can be overwritten.

    Added names missing from the mailbox's master categories are created
    with a default colour. This needs MailboxSettings.ReadWrite, which
    ckm365 does not request; refusal returns master_warning, while the
    message labels remain applied without a colour.

    Returns {"ok": changed count, "unchanged": count, "failed":
    [{"id", "error"}], "categories": {id: merged names}, "master_created":
    [names], "master_warning": text or null}. Categories includes changed
    and unchanged successes only. Failures are per message.
    """
    ctx.require_write()
    ids = batch_ids(message_ids)

    def names(values: list[str] | None, argument: str) -> list[str]:
        if values is None:
            return []
        if not isinstance(values, list):
            raise ValueError(f"{argument} must be a LIST of category names")
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 255:
                raise ValueError(
                    f"{argument} names must be strings of 1-255 characters")
            name = value.strip()
            if name.lower() not in seen:
                result.append(name)
                seen.add(name.lower())
        return result

    additions = names(add, "add")
    removals = {name.lower() for name in names(remove, "remove")}
    if not additions and not removals:
        raise ValueError("at least one category name is required")
    if any(name.lower() in removals for name in additions):
        raise ValueError("a category cannot be both added and removed")

    g, mb = ctx.target(account, mailbox)
    read, failed = apply_each(g, mb, ids, "GET", "?$select=categories")
    categories: dict[str, list[str]] = {}
    pending: list[tuple[str, list[str]]] = []
    unchanged = 0
    for message_id, body in read:
        current = body.get("categories") or []
        merged = [name for name in current if name.lower() not in removals]
        present = {name.lower() for name in merged}
        for name in additions:
            if name.lower() not in present:
                merged.append(name)
                present.add(name.lower())
        if merged == current:
            unchanged += 1
            categories[message_id] = merged
        else:
            pending.append((message_id, merged))

    ok: list[tuple[str, dict]] = []
    if pending:
        results = g.batch([
            {"method": "PATCH", "url": message_path(mb, message_id),
             "body": {"categories": merged}}
            for message_id, merged in pending])
        for (message_id, merged), result in zip(pending, results):
            if 200 <= result["status"] < 300:
                ok.append((message_id, result["body"] or {}))
                categories[message_id] = merged
            else:
                failed.append({"id": message_id, "error": batch_error(result)})

    master_created: list[str] = []
    master_warning: str | None = None
    if additions and (ok or unchanged):
        path = _path(mb, "outlook/masterCategories")
        warning = ("Master categories need MailboxSettings.ReadWrite, which "
                   "ckm365 does not request; labels were applied without "
                   "a colour")
        try:
            master = g.get(path, params={"$select": "displayName"})
        except GraphError:
            master_warning = warning + "."
        else:
            existing = {item["displayName"].lower()
                        for item in master.get("value", [])}
            refused: list[str] = []
            for name in additions:
                if name.lower() in existing:
                    continue
                try:
                    g.post(path, json={"displayName": name, "color": "preset7"})
                except GraphError:
                    refused.append(name)
                else:
                    master_created.append(name)
            if refused:
                master_warning = warning + " for: " + ", ".join(refused) + "."

    return outcome("set_categories", mb, ok, failed, unchanged=unchanged,
                   categories=categories, master_created=master_created,
                   master_warning=master_warning)


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
    ids = batch_ids(message_ids)
    g, mb = ctx.target(account, mailbox)
    dest = _resolve_destination(g, mb, destination)
    ok, failed = apply_each(g, mb, ids, "POST", "/move",
                            {"destinationId": dest})
    return outcome("move_message", mb, ok, failed, destination=dest,
                   moved={old: body.get("id") or "" for old, body in ok})
