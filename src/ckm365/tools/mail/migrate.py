"""Plan and apply local correspondence migrations without altering mail."""

import json
import logging
from collections import Counter
from pathlib import Path

from ... import __version__
from ...graph import GraphError, mailbox_path
from ..context import Ctx
from .disk import confine, write_atomic, write_target
from .export import (_MAX_FRONT_MATTER, eml_id, front_matter_id, id_key,
                     record_bytes)

log = logging.getLogger("ckm365")


def _front_matter(path: Path) -> dict[str, str] | None:
    """Read bounded top-level scalar keys, without a YAML dependency."""
    values = {}
    with path.open(encoding="utf-8", errors="replace") as f:
        if f.readline().strip() != "---":
            return None
        for _, line in zip(range(_MAX_FRONT_MATTER), f):
            if line.strip() == "---":
                return values
            if line[:1].isspace():
                continue
            key, separator, value = line.partition(":")
            if separator:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] == '"':
                    try:
                        value = json.loads(value)
                    except ValueError:
                        value = value[1:-1]
                elif len(value) >= 2 and value[0] == value[-1] == "'":
                    value = value[1:-1].replace("''", "'")
                values[key.strip()] = value
    return None


def _record_version(path: Path) -> str:
    """Recognise bounded front matter by its top-level keys only."""
    keys = _front_matter(path)
    if keys is None:
        return "none"
    if "generated" in keys:
        return "okf-0.2"
    if keys.keys() & {"timestamp", "exported_by"}:
        return "okf-0.1"
    return "hand-written"


def plan_correspondence_migration(ctx: Ctx, dir: str) -> dict:
    """Plan the cleanup of ONE old correspondence folder, without changing it.

    Use this on folders built before export dedupe and OKF v0.2: it reads
    local records and raw mail, never writes, never calls Graph, and never
    recurses into subfolders. CKM365_DOWNLOAD_ROOT fences the directory
    (falling back to CKM365_ATTACH_ROOT, like export_message).

    Each item proposes an action:
    - none: keep this current record, identified sidecar, or paired .eml.
    - upgrade: rewrite an OKF v0.1 record's front matter to v0.2; the
      body, and anything a person wrote below it, is kept.
    - backfill-id: copy the Message-ID from the same-stem .eml into a
      hand-written record; the plan reports the proposed id and pair.
    - pair: create a record for a raw .eml that has no matching record.
    - flag-duplicate: another file of the same kind already has this id;
      review duplicate_of and git mv the spare copy yourself.
    - manual: inspect the per-file reason (missing id, unreadable file,
      unrecognised record, or .msg requiring a parser dependency).

    Review this plan before acting. A later migrate_correspondence tool
    will apply upgrade/pair; this planner applies nothing. Pairing uses
    Message-ID, with optional angle brackets, except same-stem backfill.
    Items and duplicate winners follow filename order. The result includes
    action counts, skipped suffix counts, and subfolder names for a later
    separate pass; .msg files are reported without opening them.
    """
    folder = confine(Path(dir), "dir")
    if not folder.is_dir():
        raise ValueError(f"{folder} is not a directory")

    items = []
    skipped = Counter()
    subfolders = []
    raw_by_stem = {}
    backfills = []
    for path in sorted(folder.iterdir()):
        if path.is_dir():
            subfolders.append(path.name)
            continue
        suffix = path.suffix.lower()
        if suffix in {".md", ".markdown", ".txt"}:
            kind = "record"
        elif suffix in {".eml", ".msg"}:
            kind = suffix[1:]
        else:
            skipped[suffix] += 1
            continue
        item = dict(name=path.name, kind=kind, version=None,
                    internet_message_id=None, pair=None, duplicate_of=None,
                    action="manual", reason=None)
        items.append(item)
        try:
            if kind == "msg":
                item["reason"] = ".msg needs a parser and a new dependency"
            elif kind == "eml":
                item["internet_message_id"] = eml_id(path)
                if id_key(item["internet_message_id"]):
                    item["action"] = "pair"
                    raw_by_stem.setdefault(path.stem, item)
                else:
                    item["reason"] = "No Message-ID in the raw mail"
            else:
                item["version"] = _record_version(path)
                item["internet_message_id"] = front_matter_id(path)
                if item["version"] == "okf-0.2":
                    item["action"] = "none"
                elif item["version"] == "okf-0.1":
                    item["action"] = "upgrade"
                elif item["version"] == "hand-written":
                    if id_key(item["internet_message_id"]):
                        item["action"] = "none"
                    else:
                        item["reason"] = "No Message-ID or same-stem .eml with one"
                        backfills.append(item)
                else:
                    item["reason"] = "No front matter; inspect the record manually"
        except OSError as exc:
            item.update(action="manual", reason=str(exc),
                        internet_message_id=None)

    # Backfill before deduplication so proposed ids participate in the plan.
    for item in backfills:
        raw = raw_by_stem.get(Path(item["name"]).stem)
        if raw is not None:
            item.update(action="backfill-id", reason=None,
                        internet_message_id=raw["internet_message_id"],
                        pair=raw["name"])

    first = {}
    for item in items:
        key = id_key(item["internet_message_id"])
        if not key:
            continue
        identity = (item["kind"], key)
        if identity in first:
            item.update(action="flag-duplicate",
                        duplicate_of=first[identity]["name"],
                        reason="Same Message-ID as an earlier file of this kind")
        else:
            first[identity] = item

    for (kind, key), item in first.items():
        if kind != "eml":
            continue
        record = first.get(("record", key))
        if record is not None:
            item.update(action="none", pair=record["name"], reason=None)
            if record["pair"] is None:
                record["pair"] = item["name"]

    return {"dir": str(folder), "items": items,
            "counts": dict(Counter(item["action"] for item in items)),
            "skipped": dict(skipped), "subfolders": subfolders}


def _front_matter_lines(path: Path) -> tuple[list[bytes], int, bytes]:
    """The file's lines, the index of the closing fence, and its newline.
    Every rewrite below edits lines before the fence and keeps the rest."""
    lines = path.read_bytes().splitlines(keepends=True)
    if lines and lines[0].strip() == b"---":
        for i in range(1, min(len(lines), _MAX_FRONT_MATTER + 1)):
            if lines[i].strip() == b"---":
                newline = b"\r\n" if lines[0].endswith(b"\r\n") else b"\n"
                return lines, i, newline
    raise ValueError("No closed front matter to rewrite")


def _backfill_bytes(path: Path, internet_message_id: str) -> bytes:
    """Insert one key into raw front matter, preserving every existing byte."""
    lines, fence, newline = _front_matter_lines(path)
    field = "internet_message_id: " + json.dumps(
        internet_message_id, ensure_ascii=False)
    lines.insert(fence, field.encode("utf-8") + newline)
    return b"".join(lines)


def _upgrade_bytes(path: Path) -> bytes:
    """OKF v0.1 to v0.2 in the front matter ONLY: `timestamp: X` becomes
    `generated: {by: "ckm365/<version>", at: X}` and `exported_by` goes
    (CHANGELOG 2.8.0 is exactly that delta). Nothing after the closing
    fence is touched: a person may have written below the mail (6v3d56),
    and re-exporting from Graph would have thrown that away."""
    lines, fence, newline = _front_matter_lines(path)
    head, stamped = [], False
    for line in lines[:fence]:
        key, _, value = line.partition(b":")
        if key.strip() == b"timestamp":
            head.append(b"generated: {by: "
                        + json.dumps(f"ckm365/{__version__}").encode()
                        + b", at: " + value.strip() + b"}" + newline)
            stamped = True
        elif key.strip() != b"exported_by":
            head.append(line)
    if not stamped:
        raise ValueError("No timestamp in the front matter to upgrade")
    return b"".join(head + lines[fence:])


def migrate_correspondence(ctx: Ctx, dir: str, *, actions: list[str] | None = None,
                           dry_run: bool = True, account: str | None = None,
                           mailbox: str | None = None) -> dict:
    """Apply a correspondence migration plan to ONE local folder.

    Run plan_correspondence_migration first and READ its per-file actions.
    Dry run is the default: it looks up messages but writes nothing, so
    review what would change before calling again with dry_run=false.
    actions defaults to upgrade, pair and backfill-id; pass a subset to
    limit this pass. No mail in Graph is ever changed.

    upgrade rewrites only the front matter of our old OKF v0.1 record, in
    place and without Graph; the body, including anything a person added
    below the mail, is kept byte for byte. pair writes a .md record beside
    a lone .eml and refuses an existing destination file. backfill-id
    inserts the paired .eml's Message-ID into a hand-written record's
    front matter, without Graph. No body is EVER rewritten, nothing is
    deleted, and writes are atomic.

    Outcomes: would-apply describes a dry-run write; applied means written;
    skipped carries the planner's reason for manual/duplicate items, or
    says the action was not requested. Current items (none) are omitted.
    not-found means no Message-ID hit for a lone .eml in the selected
    mailbox. A message delivered minutes ago may not be indexed
    yet: a missing hit must not be assumed to mean the message is gone.
    failed carries a per-file error; other items still proceed.

    Read tier, no new consent. CKM365_DOWNLOAD_ROOT fences the directory
    and destinations, falling back to CKM365_ATTACH_ROOT. The result gives
    per-file details and outcome counts; only counts reach the log.
    """
    applicable = {"upgrade", "pair", "backfill-id"}
    requested = applicable if actions is None else set(actions)
    if requested - applicable:
        raise ValueError("actions must contain only upgrade, pair, backfill-id")
    plan = plan_correspondence_migration(ctx, dir)
    folder = Path(plan["dir"])
    results = []
    for item in plan["items"]:
        action = item["action"]
        if action == "none":
            continue
        result = dict(name=item["name"], action=action,
                      outcome="skipped", detail=item["reason"] or "")
        results.append(result)
        if action not in applicable:
            continue
        if action not in requested:
            result["detail"] = "Action not requested in actions"
            continue
        try:
            path = confine(folder / item["name"], "source")
            imid = item["internet_message_id"]
            if action == "upgrade":
                data = _upgrade_bytes(path)
                detail = (f"Rewrite {path.name} front matter (timestamp to "
                          "generated, exported_by dropped); body kept")
                dest = path
            elif action == "backfill-id":
                data = _backfill_bytes(path, imid)
                detail = f"Insert internet_message_id into {path.name} front matter"
                dest = path
            else:
                g, mb = ctx.target(account, mailbox)
                escaped = imid.replace("'", "''")
                hits = g.get(mailbox_path(mb, "messages"), params={
                    "$filter": f"internetMessageId eq '{escaped}'",
                    "$select": "id", "$top": 2}).get("value", [])
                if not hits:
                    result.update(outcome="not-found", detail=(
                        f"Message-ID not found in mailbox {mb}. A message "
                        "delivered minutes ago may not be indexed yet; do not "
                        "assume it is gone."))
                    continue
                message_id = hits[0]["id"]
                dest = write_target(str(path.with_suffix(".md")), None)
                detail = (f"Write {dest.name}; found message "
                          f"{message_id[:12]}... in mailbox {mb}")
                if not dry_run:
                    data, _, _ = record_bytes(g, mb, message_id)
            if dry_run:
                result.update(outcome="would-apply", detail=f"Would {detail}")
            else:
                write_atomic(dest, lambda part: part.write_bytes(data))
                result.update(outcome="applied", detail=detail)
        except (GraphError, OSError, ValueError) as exc:
            result.update(outcome="failed", detail=str(exc))
    counts = dict(Counter(result["outcome"] for result in results))
    log.info("tool=migrate_correspondence counts=%s", counts)
    return {"dir": str(folder), "dry_run": dry_run,
            "results": results, "counts": counts}
