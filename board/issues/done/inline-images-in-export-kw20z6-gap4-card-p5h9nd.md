---
type: "issue"
title: "Inline images in exported records: manifest, numbered cid references, bulk bytes"
created: "2026-11-07T00:00:00Z"
resource: "oif:ckm/p5h9nd"
kind: "task"
priority: "high"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["mail", "export", "copilot-card"]
---

Implements GAP 4 of kw20z6 (CKM-44,
`board/issues/backlog/surfacing-gaps-export-transcript-the-meetings-kw20z6.md`).
The spec is `tests/test_mail_inline.py` (on main, skipped until
`Attachment` has `content_id`). Read it in full first; its module
docstring is the design and carries the live measurements.

## Deliverable

1. `src/ckm365/models.py`, `Attachment`: add `content_id: str | None = None`
   (after `is_inline`, before `kind`), read from `contentId`, and add
   `microsoft.graph.fileAttachment/contentId` to `SELECT`. The plain
   `contentId` is a 400 live; the cast form is the measured one. Extend
   the class docstring by one or two sentences saying so.
2. `src/ckm365/tools/mail/export.py`:
   - `record_bytes`: list attachments when `message.has_attachments` OR
     `"[cid:"` appears in the text of `message.body` or
     `message.unique_body`. Plain mail keeps skipping the call.
   - `_record`: number the inline attachments 1..n in manifest order
     (non-inline ones are not counted). In the body that is written,
     replace each `[cid:<x>]` whose `<x>` equals an inline
     attachment's `content_id` (compare both with surrounding `<>`
     stripped) with `[inline N: <name or '(unnamed)'>]`; leave others
     as they are. One `re.sub` with a callback is enough. In the
     manifest, an inline line ends `, inline N, attachment_id `...``
     instead of `, inline, attachment_id ...`.
   - `has_attachments` in the front matter, and the `attachments` tag
     from `_tags`, are true when Graph says so OR the manifest is
     non-empty. Pass what `_tags` needs; keep key order unchanged.
   - `export_message` docstring: replace the "INLINE IMAGES ARE A BLIND
     SPOT" paragraph with a short one on what happens now (manifest,
     `[inline N: name]` markers, bulk saves the bytes, download by
     attachment_id because names repeat). Keep the rest.
3. `src/ckm365/tools/mail/bulk.py`, the `attachments` loop: stop
   skipping inline attachments. A non-inline one keeps today's path (the
   directory, its own name). Inline number N (counted as in `_record`,
   in `attachments_of` order) goes to the full path
   `<stem>/inline<N>-<safe_name(name)>`. In both cases an existing file
   is a skip. Update the `export_messages` docstring line about
   attachments.

## Files you may touch

- `src/ckm365/models.py`, `src/ckm365/tools/mail/export.py`,
  `src/ckm365/tools/mail/bulk.py`.

Read only those plus `tests/test_mail_inline.py`, `tests/test_mail_export.py`,
`tests/test_mail_bulk.py`, `src/ckm365/tools/mail/attachments.py` and
`disk.py`. Do not edit any test file; if a test looks wrong, say so in
open_questions and make the rest pass. Existing export and migrate tests
must still pass unchanged.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report the before and after counted results; after: all passing, one
fewer module skipped.

## Not in scope

- Describing or transcribing images; HTML bodies; changing
  `download_attachment` or `list_attachments` beyond the new field.
- Any live check, `CKM365_LIVE_*`, anything under `~/.config/ckm365`.
- Version bump, CHANGELOG, README, docs, board files. No commits.

## Relates to

- kw20z6 (CKM-44) gap 4. h7t3qf: the bulk export this extends.
