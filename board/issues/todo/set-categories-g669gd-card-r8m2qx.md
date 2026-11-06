---
type: "issue"
title: "set_categories: add/remove Outlook categories on messages"
created: "2026-11-07T00:00:00Z"
resource: "oif:ckm/r8m2qx"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["mail", "triage", "write-tier", "copilot-card"]
---

Implements g669gd (CKM-51, `board/issues/backlog/set-categories-tool-add-remove-outlook-categories-g669gd.md`).
The spec is `tests/test_mail_categories.py` (on main, skipped until
`mail.set_categories` exists). Read it in full first; its module
docstring is the design.

## Deliverable

1. In `src/ckm365/tools/mail/triage.py`, after `complete_flag`:

       def set_categories(ctx: Ctx, message_ids: list[str], *,
                          add: list[str] | None = None,
                          remove: list[str] | None = None,
                          account: str | None = None,
                          mailbox: str | None = None) -> dict

   Order matters: `ctx.require_write()`, then validate everything BEFORE
   any request: `batch_ids(message_ids)`; `add`/`remove` must be lists
   (a bare string is a ValueError, as in `batch_ids`); each name is
   stripped and must be 1-255 characters; de-duplicate case-insensitively
   (first spelling wins); at least one name overall; a name in both
   lists (case-insensitive) is a ValueError.

   Then:
   - Read: `apply_each(g, mb, ids, "GET", "?$select=categories")`.
   - Merge each read: keep current names whose lower-case is not in
     `remove`, in order; append each `add` name whose lower-case is not
     already present. Equal to current means `unchanged`.
   - Write: one `apply_each(..., "PATCH", body=...)` per distinct merged
     list is wasteful; instead build the batch yourself with
     `g.batch([{"method": "PATCH", "url": message_path(mb, id), "body":
     {"categories": merged}} ...])` and split results the way
     `apply_each` does (`batch_error` from `common.py` for the message).
     If you would rather extend `apply_each` with a per-id body, do not;
     keep the change inside triage.py. Send no batch at all when nothing
     changed.
   - Master categories, only when `add` is non-empty AND at least one
     message ended ok or unchanged: GET `mailbox_path(mb,
     "outlook/masterCategories")` (`$select=displayName`), then POST
     `{"displayName": name, "color": "preset7"}` for each `add` name not
     there (case-insensitive). A `GraphError` on the GET stops the step
     with `master_warning` naming MailboxSettings.ReadWrite (the scope
     ckm365 does not request) and saying the labels were applied without
     a colour. A `GraphError` on a POST adds that name to the warning
     and carries on with the rest. Never raise from this step.

   Result: `outcome("set_categories", mb, ok, failed, unchanged=n,
   categories={id: merged list for ok and unchanged}, master_created=[...],
   master_warning=str | None)`, where `failed` holds read failures then
   write failures. Logging stays counts only: never category names.

   Docstring (the MCP description, ~20 lines, the voice of `flag`):
   metadata not content, pass a list even for one id, case-insensitive
   matching, the read-merge-write and its last-write-wins race, master
   categories and the colour warning, the result shape, up to 200 ids.
2. Register: `tools/mail/__init__.py` (import and `__all__`) and
   `WRITE["mail"]` in `src/ckm365/tools/__init__.py`, after
   `mail.complete_flag`.

## Preset counts

One new write tool: in `tests/test_offline.py::test_tools_for_presets`
the `mail` write and send counts (lines 255-256: 33, 34) and the `all`
write, `all` send and `all`+`teams` counts (lines 283, 284, 287: 38, 39,
42) each go up by one. `mail` read (18) stays. Only those five edits in
that file.

## Files you may touch

- `src/ckm365/tools/mail/triage.py`
- `src/ckm365/tools/mail/__init__.py`, `src/ckm365/tools/__init__.py`
- `tests/test_offline.py`: the five numbers.

Read only those plus `tests/test_mail_categories.py`,
`src/ckm365/tools/mail/common.py` and `src/ckm365/graph.py`. Do not edit
spec or other test files; if a test looks wrong, say so in
open_questions and make the rest pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report the before and after counted results; after: all passing, one
fewer module skipped.

## Not in scope

- Adding MailboxSettings scopes, any consent or tenant change.
- A filter-based selector (callers list first, then pass ids).
- Any live check, `CKM365_LIVE_*`, anything under `~/.config/ckm365`.
- Version bump, CHANGELOG, README, docs, board files. No commits.

## Relates to

- g669gd (CKM-51): the issue.
