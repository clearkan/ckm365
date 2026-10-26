---
type: "issue"
title: "migrate_correspondence: apply the plan — upgrade, pair and backfill-id, dry run by default"
created: "2026-10-26T11:00:00Z"
resource: "oif:ckm/cxsznh"
kind: "task"
priority: "high"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["mail", "export", "migration", "copilot-card"]
---

Step 2 of mr31re (brief: `board/issues/doing/correspondence-migration-helper-mr31re.md`,
"Proposed shape" item 2). The planner (`plan_correspondence_migration`,
dr4f2n, on main) says what each file in a correspondence folder needs;
this tool applies it. The spec is `tests/test_mail_migrate_apply.py`
(15 tests, on main, skipped until the function exists). Read it in full
first; it is the contract.

## Deliverable

In `src/ckm365/tools/mail/migrate.py`, add

    def migrate_correspondence(ctx: Ctx, dir: str, *, actions: list[str] | None = None,
                               dry_run: bool = True, account: str | None = None,
                               mailbox: str | None = None) -> dict

Register it like the planner: `tools/mail/__init__.py` (import, `__all__`),
`READ["mail"]` in `tools/__init__.py`, and move the three preset counts in
`tests/test_offline.py::test_tools_for_presets` (lines 254-256: read,
write, send; each includes the read tools) up by one. Those three lines
are the only test edit allowed.

## Behaviour (the tests encode all of this)

- `actions` defaults to all three applicable ones: `upgrade`, `pair`,
  `backfill-id`. Anything else in the list → `ValueError` mentioning
  "actions". Items whose plan action is `none` are NOT in the result;
  `flag-duplicate` and `manual` are listed with outcome `skipped` and the
  planner's reason as detail; a selected-but-not-requested action is
  `skipped` too.
- Locate a message by Message-ID: `GET {mailbox}/messages` with
  `$filter=internetMessageId eq '<id>'` (double any single quote in
  the id), `$select=id`, `$top=2`; first hit wins. Verified live on both
  tenants 2026-10-26: it resolves across folders from the mailbox root.
  Candidate mailboxes, in order, deduplicated: the record's own
  `mailbox:` front-matter value when it has one (you need a small
  top-level front-matter reader returning key→unquoted value; `_record_version`
  can be built on it), then the mailbox from `ctx.target(account, mailbox)`.
  No hit anywhere → outcome `not-found`, detail saying "not found" in
  those mailboxes and that a message delivered minutes ago may not be
  indexed yet (AGENTS.md gotcha on lagging filters) so it should not be
  assumed gone.
- `upgrade` (an OKF v0.1 record, machine-written): re-render the record
  for the located message and write it OVER the old file with
  `write_atomic` (same name; the `.part` rename makes it atomic, and
  write_target's overwrite refusal does not apply because the plan has
  established this is our own old output). To render, extract the
  record-building part of `export_message` in `export.py` (the `.md`
  branch: fetch `Message` with `prefer("text")`, attachments when
  `has_attachments`, `_sent_folder_id`, then `_record(...)`) into a shared
  `record_bytes(g, mailbox, message_id) -> tuple[bytes, Message, int]`
  that `export_message` then calls. No behaviour change there:
  `tests/test_mail_export.py` must stay green untouched.
- `pair` (a lone .eml): the record goes to `<stem>.md` beside it, through
  `write_target` (so an existing file of that name is REFUSED: outcome
  `failed`, detail naming the file) then `write_atomic`. Detail on success
  names the file written.
- `backfill-id` (hand-written record, same-stem .eml with an id): no
  Graph. Insert one line, `internet_message_id: "<id>"`, as the last line
  of the front matter (just before the closing `---`), and write the
  result atomically to the same path. Everything else in the file,
  including the body, stays byte-for-byte: work on the raw text, not a
  re-serialised front matter.
- `dry_run=True` (default) still does the Graph lookups, so a dry run can
  say `not-found`, but writes nothing: outcome `would-apply` with a detail
  that says what would be written and where the message was found
  (truncated id, mailbox).
- Per-item failures (`GraphError`, `OSError`, `ValueError`) become outcome
  `failed` with `detail` carrying the exception; for GraphError include
  its status and code. The loop continues with the next item, and
  `write_atomic` guarantees no `.part` residue.
- Never deletes anything. A second run finds nothing to do.
- Result: `{"dir": str, "dry_run": bool, "results": [{"name", "action",
  "outcome", "detail"}], "counts": {outcome: n}}` (only outcomes that
  occur). Log one line per call with counts only, never file names or ids.

## Docstring

The MCP description. Teach: run the planner first and read it; dry run
is the default and shows what would change; what each outcome means;
that hand-written bodies are never rewritten and nothing is deleted;
that `not-found` can be lag; the fence. Same voice as `export_message`'s,
15-30 lines.

## Files you may touch

- `src/ckm365/tools/mail/migrate.py`
- `src/ckm365/tools/mail/export.py` (only the extraction described; lines 250-365)
- `src/ckm365/tools/mail/__init__.py`, `src/ckm365/tools/__init__.py`
- `tests/test_offline.py`: the three count lines in `test_tools_for_presets`

Read only those plus `tests/test_mail_migrate_apply.py` (all),
`tests/test_mail_migrate.py` lines 1-60 (the fixtures the apply tests
import), `disk.py` (all, 90 lines) and `graph.py` lines 40-75 (GraphError,
mailbox_path). Do not edit the two migrate test files: if a test looks
wrong, say so in open_questions and make the rest pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Before: `211 passed, 16 skipped`. Expected after: `226 passed, 15 skipped`.
Report the counted result.

## Not in scope

- Renaming files to a convention (k4r9tw), Graph lookup by sender and
  time for a sidecar with no .eml (stays `manual`), a CLI subcommand.
- Any live check, `CKM365_LIVE_*`, anything under `~/.config/ckm365`.
- Version bump, CHANGELOG, README, docs, board files. No commits.

## Relates to

- mr31re (doing): the brief. dr4f2n (done): the planner this applies.
