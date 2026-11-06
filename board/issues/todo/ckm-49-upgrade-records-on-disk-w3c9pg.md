---
type: "issue"
title: "CKM-49 step 2: upgrade pre-CKM-49 records on disk, front matter only"
created: "2026-11-06T06:00:00Z"
resource: "oif:ckm/w3c9pg"
kind: "task"
priority: "high"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["mail", "migration", "okf", "copilot-card"]
---

Second half of tvtrb0 (CKM-49). The record format changed in the
previous card (e8r5wc, merged); records already on disk need bringing up
to date. The spec is `tests/test_mail_migrate_threading.py` (on main,
skipped until the planner proposes `upgrade` for a pre-CKM-49 record).
Read it in full first; its docstring is the design. The fixtures
`v02()` (current shape) and `v02_email()` (old shape) are in
`tests/test_mail_migrate.py`.

THE BODY IS NEVER TOUCHED. Every edit is to lines before the closing
fence, through `_front_matter_lines` (6v3d56 is why; read `_upgrade_bytes`
and its docstring).

## Deliverable, all in `src/ckm365/tools/mail/migrate.py`

1. **`_record_version`**: `generated` and `channel` present: `okf-0.2`;
   `generated` without `channel`: `okf-0.2-email`; otherwise as today.
2. **Planner**: `okf-0.2-email` and `okf-0.1` records are `upgrade` when
   they carry a Message-ID (`id_key(...)` truthy), else `manual` with a
   reason mentioning "Message-ID" (the upgrade now needs Graph).
   The hand-written `type` rule: `type` "message" (case-insensitive)
   counts as mail when `channel` is absent or "email"; any other type
   than email/message, or message with another channel, is a `note`.
   Update the planner docstring's `upgrade` bullet (front matter brought
   to the current shape; thread keys from Graph; body kept).
3. **Apply, `upgrade`**: locate the message by Message-ID exactly as
   `pair` does today, but with candidates: the record's own `mailbox`
   front-matter value first, then `ctx.target(account, mailbox)`'s
   (deduplicated). Not found: outcome `not-found`, as for pair. Found:
   one GET of the message with `$select=conversationId,internetMessageHeaders`
   (no Prefer header, no body); build `MessageHeaders.from_graph` from it
   for `in_reply_to` and `references`. Then rewrite the front matter:
   - a v0.1 record first gets today's `_upgrade_bytes` treatment
     (timestamp -> generated, exported_by dropped); refactor so both
     steps work on one list of lines and the file is written once;
   - `type: ...Email...` line -> `type: "Message"`, and insert
     `channel: "email"` right after it;
   - `resource:` -> `mid_uri(internet_message_id)` (from export.py) and
     remember the old value for `web_link`;
   - insert `conversation_id`, `in_reply_to`, `references` (values
     formatted exactly as export writes them: `export._yaml_value`;
     `""` for None, `[]` for no references) right after the
     `internet_message_id` line;
   - insert `web_link: <old resource>` and then `body_scope: "full"`
     right before `has_attachments`, or before the closing fence when
     there is no `has_attachments` line;
   - the `generated:` line's `by` becomes `ckm365/<__version__>`; `at`
     is kept exactly.
   Keep the file's newline style (CRLF stays CRLF). Detail on success and
   on dry run says what changes and ends with "body kept". Dry run does
   the lookup and the metadata GET, writes nothing.
4. `migrate_correspondence`'s docstring: the `upgrade` sentence now says
   it needs Graph for thread metadata, reads no body, and keeps the body.

## Files you may touch

- `src/ckm365/tools/mail/migrate.py` only.

Read only that file plus the spec, `tests/test_mail_migrate.py` lines
1-110, `tests/test_mail_migrate_apply.py` (its upgrade tests will need
the Graph fake it already has), and in `export.py` `mid_uri` and
`_yaml_value`; in `models.py` `MessageHeaders`. The existing apply
tests in `test_mail_migrate_apply.py` were already relaxed for this
design (upgrade may now call Graph, never for a body) and must stay
green. Do not edit any test file: if a test looks wrong, say so in
open_questions and make the rest pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report before and after counts, and the names of any failing tests with
your reading of why.

## Not in scope

- `pair`, `backfill-id`, notes, export.py, any other module.
- Any live check, `CKM365_LIVE_*`, anything under `~/.config/ckm365`.
- Version bump, CHANGELOG, README, docs, board files. No commits.

## Relates to

- tvtrb0 (CKM-49), e8r5wc (the record card), 6v3d56 (why the body is sacred).
