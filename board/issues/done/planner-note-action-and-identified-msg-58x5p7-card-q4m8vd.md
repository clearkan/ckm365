---
type: "issue"
title: "Planner: a note action for non-mail files, and .msg with an identified sidecar is current"
created: "2026-11-02T05:30:00Z"
resource: "oif:ckm/q4m8vd"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["mail", "migration", "copilot-card"]
---

Implements 58x5p7 (`board/issues/backlog/migration-planner-thread-records-and-notes-58x5p7.md`).
The spec is `tests/test_mail_migrate_notes.py` (on main, 22 tests,
skipped as a module until the planner returns a `note` action). Read it
in full first; it is the contract.

## Deliverable

All changes in `src/ckm365/tools/mail/migrate.py`:
`plan_correspondence_migration` (lines 55-170) and one line in
`migrate_correspondence` (around line 214).

## Behaviour (the tests encode all of this)

- New planner action `note`: "not a mail record, nothing to migrate".
  The item's `reason` says why. Three sources:
  1. A record (`.md`/`.markdown`/`.txt`) with NO front matter and NO
     same-stem `.eml` or `.msg` in the folder. With a same-stem mail
     file it stays `manual`, and its reason names that file (it owns the
     name a pair would write).
  2. A hand-written front matter (version `hand-written`) whose `type`
     key is present and is not `email` compared case-insensitively
     (values are already unquoted by `_front_matter`). The reason
     includes the type. Records with no `type`, and our own
     `okf-0.1`/`okf-0.2` records, are unaffected.
  3. An `.eml` whose headers carry `X-Unsent` (any non-empty value):
     an unsent draft. It is a note whether or not it has a Message-ID,
     and the reason mentions `X-Unsent`. Read the header the way
     `eml_id` in `export.py` does (headers only, up to the first blank
     line); a small local helper in migrate.py is fine, do not change
     export.py.
- Notes take no part in duplicate detection or eml-to-record pairing:
  skip `note` items in the `first = {}` loop.
- A `.msg` whose same-stem record carries a Message-ID (its own, or one
  proposed by backfill-id) becomes `none` with `pair` = that record's
  name and `reason` None. Its own `internet_message_id` stays None: the
  .msg is still never opened. If that record's `pair` is None, set it
  to the .msg name. Do this after the eml-to-record pairing, so an .eml
  pair wins.
- `migrate_correspondence` omits `note` items from its results exactly
  as it omits `none` (the `if action == "none": continue` line).
- Planner docstring (it is the MCP tool description): add `note` to the
  action list, narrow the `manual` bullet to match, and add one or two
  sentences on thread records: a record covering a thread carries its
  latest message's `internet_message_id` at top level; ids nested under
  other keys (such as a `messages:` list) are not read. The test
  checks for the words "note", "thread" and "top level". Do not parse
  nested YAML.

## Files you may touch

- `src/ckm365/tools/mail/migrate.py` only.

Read only that file, `tests/test_mail_migrate_notes.py` (all),
`tests/test_mail_migrate.py` lines 1-80 (fixtures) and `export.py`
lines 197-232 (`id_key`, `front_matter_id`, `eml_id`). Do not edit any
test file: if a test looks wrong, say so in open_questions and make the
rest pass. No new tool is registered, so the preset counts in
`tests/test_offline.py` do not move.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Before: `229 passed, 16 skipped`. Expected after: `251 passed, 15 skipped`.
Report the counted result.

## Not in scope

- A pair destination when a note owns `<stem>.md` (needs a naming
  decision), recursing into subfolders (xfccc0), opening `.msg`.
- Any live check, `CKM365_LIVE_*`, anything under `~/.config/ckm365`.
- Version bump, CHANGELOG, README, docs, board files. No commits.

## Relates to

- 58x5p7 (backlog): the issue. mr31re (done): the helper's brief.
