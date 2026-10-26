---
type: "issue"
title: "plan_correspondence_migration: the read-only planner for old correspondence folders"
created: "2026-10-26T10:10:00Z"
resource: "oif:ckm/dr4f2n"
kind: "task"
priority: "high"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["mail", "export", "migration", "copilot-card"]
---

Step 1 of mr31re (the brief: `board/issues/doing/correspondence-migration-helper-mr31re.md`,
section "Proposed shape", item 1). A read-tier tool that classifies every
file in ONE correspondence folder and proposes an action per file. Local
only: no Graph call, no write, no recursion. The spec is the test file,
already on main: `tests/test_mail_migrate.py` (22 tests, currently
skipped because the module does not exist). Read it in full first; it is
the contract, and nothing below contradicts it.

## Deliverable

Create `src/ckm365/tools/mail/migrate.py` with

    def plan_correspondence_migration(ctx: Ctx, dir: str) -> dict

`ctx` is unused (local only) but stays first, like every tool. Then register
it: import and `__all__` entry in `src/ckm365/tools/mail/__init__.py`
(alphabetical, with a one-line `migrate.py` entry in that docstring's file
table), and append it to `READ["mail"]` in `src/ckm365/tools/__init__.py`.

Reuse, do not re-implement: `id_key`, `front_matter_id`, `eml_id` and
`_MAX_FRONT_MATTER` from `export.py` (lines 194-230), `confine` from
`disk.py`. Stdlib only. No new dependency.

## Rules the tests encode

- Files considered: `.md`/`.markdown`/`.txt` are records, `.eml` raw,
  `.msg` reported only. Every other suffix (and `.part`) is counted in
  `skipped` by suffix; subdirectories are listed by name in `subfolders`,
  never entered. Items sorted by name.
- Record version from the front matter's top-level keys (lines between
  the first `---` and the next, up to `_MAX_FRONT_MATTER`; `key: value`,
  surrounding quotes stripped): `generated` present → `okf-0.2`;
  else `timestamp` or `exported_by` → `okf-0.1`; else any front matter
  → `hand-written`; no front matter → `none`. `.eml`/`.msg` have
  version `None`.
- Actions: okf-0.2 → `none`. okf-0.1 → `upgrade`. hand-written with an
  id → `none`; without one: `backfill-id` when a `.eml` with the SAME STEM
  carries a Message-ID (the item then reports that id and the eml as its
  `pair`), else `manual` with a reason naming "Message-ID". No front
  matter → `manual`. `.eml` with an id and no record sharing it → `pair`;
  sharing it → `none` with `pair` set both ways; no id → `manual`. `.msg`
  → `manual`, reason says it needs a parser, a new "dependency".
- Pairing a record to an eml is by Message-ID (via `id_key`, brackets
  optional), not by name, except the backfill case above.
- Duplicates: a second file of the SAME KIND with an id already seen, in
  name order, becomes `flag-duplicate` with `duplicate_of` = the first.
  A record and an eml sharing an id are a pair, never duplicates.
- An unreadable file is `manual` with the OSError in its reason, never a
  crash.
- `dir` goes through `confine(Path(dir), "dir")`, then must be a
  directory (ValueError "not a directory" otherwise).
- Return: `{"dir": str(resolved), "items": [...], "counts": {action: n},
  "skipped": {suffix: n}, "subfolders": [names]}`; every item has exactly
  the keys `name, kind, version, internet_message_id, pair, duplicate_of,
  action, reason`. `counts` has only the actions that occur.

## Docstring

It becomes the MCP tool description, so it teaches an agent: what the
plan is for (old folders built before dedupe/OKF v0.2), that it never
writes or calls Graph, what each action means and what the agent does
next (`upgrade`/`pair` will be applied by `migrate_correspondence`, a
later card; `flag-duplicate` is reported and the spare copy is the
caller's `git mv`; `manual` says why per file), and the fence
(CKM365_DOWNLOAD_ROOT). 15-30 lines, in the voice of `export_message`'s.

## Files you may touch

- `src/ckm365/tools/mail/migrate.py` (new)
- `src/ckm365/tools/mail/__init__.py`
- `src/ckm365/tools/__init__.py` (the `READ["mail"]` list only)

Read only those, `tests/test_mail_migrate.py` (all of it),
`export.py` lines 194-250 and `disk.py` lines 30-45. Do not edit the test
file: if a test looks wrong, say so in open_questions and make the rest
pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Before: `189 passed, 16 skipped` (the migrate file skips as one). Expected
after: `211 passed, 15 skipped`. Report the counted result.

## Not in scope

- `migrate_correspondence` (the apply step), any Graph call, any live
  check or `CKM365_LIVE_*` variable, anything under `~/.config/ckm365`.
- Version bump, CHANGELOG, README, docs, board files.
- Commits: leave the working tree changed; the dispatcher commits.

## Relates to

- mr31re (doing): the brief. h59xfz (done): the helpers this imports.
