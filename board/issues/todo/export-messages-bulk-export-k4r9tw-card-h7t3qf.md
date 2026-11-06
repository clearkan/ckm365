---
type: "issue"
title: "export_messages: bulk export of a thread, folder or id list into a correspondence folder"
created: "2026-11-06T05:00:00Z"
resource: "oif:ckm/h7t3qf"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["mail", "export", "copilot-card"]
---

Implements k4r9tw (CKM-53, `board/issues/doing/bulk-correspondence-export-k4r9tw.md`).
The spec is `tests/test_mail_bulk.py` (on main, skipped until
`mail.export_messages` exists). Read it in full first; its module
docstring is the design, including the file-name convention.

## Deliverable

New module `src/ckm365/tools/mail/bulk.py` (aim for ~150 lines) with:

1. `file_stem(subject: str | None, received: str | None, internet_message_id: str) -> str`,
   public: `YYYYMMDD_<slug>_<token>`. Date: the first 10 characters of
   `received` with dashes removed (`"00000000"` when missing). Slug:
   strip leading reply/forward prefixes repeatedly (case-insensitive
   `re`, `fw`, `fwd`, `aw`, `wg`, `sv`, each followed by `:` and
   whitespace), lower-case, replace every run of characters outside
   `a-z0-9` with `-`, cut to 50 characters, strip `-`; empty becomes
   `no-subject`. Token: `hashlib.sha1(id.strip().strip("<>").encode()).hexdigest()[:8]`.
2. The tool, read tier:

       def export_messages(ctx: Ctx, dest_dir: str, *, message_ids: list[str] | None = None,
                           conversation_id: str | None = None, folder: str | None = None,
                           since: str | None = None, from_address: str | None = None,
                           eml: bool = False, attachments: bool = False,
                           full_body: bool = False, max_messages: int = 200,
                           dry_run: bool = False, account: str | None = None,
                           mailbox: str | None = None) -> dict

   Validate BEFORE any request: exactly one of `message_ids` (non-empty),
   `conversation_id`, `folder`; `since`/`from_address` only with
   `folder`; `1 <= max_messages <= 1000`; `dest_dir` through
   `confine(Path(dest_dir), "dir")` from `disk.py` and it must be an
   existing directory. ValueError otherwise.

   Listing (one `$select` of
   `id,subject,receivedDateTime,internetMessageId,hasAttachments`):
   - `conversation_id`: GET `<mailbox>/messages` with
     `$filter=conversationId eq '<id with ' doubled>'`, NO `$orderby`.
   - `folder`: GET `<mailbox>/mailFolders/<_seg(folder)>/messages` with
     the `$filter` from `read._predicates(since=..., from_address=...)`
     when either is given (import it; do not copy it).
   - `message_ids`: GET each message with that `$select`; an id that
     fails becomes a `failed` result (after the others) and the run goes on.
   Page with `g.paged(..., max_items=max_messages + 1)`. Sort by
   `receivedDateTime` ascending (oldest first), keep the first
   `max_messages`, and set `truncated` when there were more.

   Per message, `name = file_stem(...) + ".md"`:
   - `dry_run`: check `export._already_exported(dest, imid)`; outcome
     `already` (detail names the existing file) or `would-write`.
   - otherwise call `export_message(ctx, id, str(dest / name),
     dedupe_dir=str(dest), full_body=full_body, account=..., mailbox=...)`.
     A result carrying `already_exported` is outcome `already` with the
     existing file's name in `detail`; otherwise `written`. With `eml`,
     also `export_message(..., str(dest / (stem + ".eml")),
     dedupe_dir=None)` unless that file exists. A message with no
     Message-ID still exports (token from the Graph id instead).
   - `attachments` (not on dry run, and only for a written or already
     record): list with `attachments.attachments_of(g, mb, id)`, skip
     `is_inline`, create `dest/<stem>/`, and for each call
     `download_attachment(ctx, id, str(dest / stem), attachment_id=a.id, ...)`
     imported into `bulk` by name (the spec patches `bulk.download_attachment`).
     An existing file there is a skip, not a failure. Count saved files
     in the result's `attachments`.
   - `GraphError`, `OSError` and `ValueError` per message become outcome
     `failed` with the error in `detail`; the run continues.

   Result: `{"dir", "dry_run", "results": [{"message_id",
   "internet_message_id", "name", "outcome", "detail", "attachments"}],
   "counts": {outcome: n}, "truncated": bool}`. Log one line with
   counts only: never subjects, names or addresses.

   Docstring (the MCP description, 20-30 lines, `export_message`'s
   voice): the three selectors, oldest-first order, the name convention
   and why it is stable, idempotence via Message-ID dedupe, eml and
   attachments, dry run, max_messages and truncated, the fence.
3. Register: `tools/mail/__init__.py` (import, `__all__`, a module
   docstring line for bulk.py) and `READ["mail"]` in
   `src/ckm365/tools/__init__.py` after `mail.export_message`.

## Preset counts

One new read tool: in `tests/test_offline.py::test_tools_for_presets`
the `mail` read/write/send counts (lines 253-255: 17, 32, 33) and the `all` write,
`all` send and `all`+`teams` counts (lines 283, 284, 287: 37, 38, 41) each go up by
one. Only those six edits in that file.

## Files you may touch

- `src/ckm365/tools/mail/bulk.py` (new)
- `src/ckm365/tools/mail/__init__.py`, `src/ckm365/tools/__init__.py`
- `tests/test_offline.py`: the six numbers.

Read only those plus `tests/test_mail_bulk.py`,
`src/ckm365/tools/mail/export.py`, `disk.py`, and in `read.py` the
`_predicates` function. Do not edit spec or other test files; if a test
looks wrong, say so in open_questions and make the rest pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report the before and after counted results; after: all passing, one
fewer module skipped.

## Not in scope

- Renaming existing files to the convention, changing `pair` in
  migrate.py, a CLI subcommand.
- Any live check, `CKM365_LIVE_*`, anything under `~/.config/ckm365`.
- Version bump, CHANGELOG, README, docs, board files. No commits.

## Relates to

- k4r9tw (CKM-53): the issue. 4qn81m: where the name token was proposed.
