"""Local, read-only planning for old correspondence folders."""

from collections import Counter
from pathlib import Path

from ..context import Ctx
from .disk import confine
from .export import _MAX_FRONT_MATTER, eml_id, front_matter_id, id_key


def _record_version(path: Path) -> str:
    """Recognise bounded front matter by its top-level keys only."""
    keys = set()
    with path.open(encoding="utf-8", errors="replace") as f:
        if f.readline().strip() != "---":
            return "none"
        for _, line in zip(range(_MAX_FRONT_MATTER), f):
            if line.strip() == "---":
                break
            if line[:1].isspace():
                continue
            key, separator, _ = line.partition(":")
            if separator:
                keys.add(key.strip())
        else:
            return "none"
    if "generated" in keys:
        return "okf-0.2"
    if keys & {"timestamp", "exported_by"}:
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
    - upgrade: convert an OKF v0.1 record to v0.2.
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
