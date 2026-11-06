---
type: "issue"
title: "CKM-49 records: thread ids, References, uniqueBody, mid: resource, type Message"
created: "2026-11-06T04:00:00Z"
resource: "oif:ckm/e8r5wc"
kind: "task"
priority: "high"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["mail", "export", "okf", "copilot-card"]
---

Implements items 1-4 of tvtrb0 (CKM-49,
`board/issues/doing/email-export-loses-threading-and-stores-the-tvtrb0.md`).
The spec is `tests/test_mail_threading.py` (on main, skipped until
`Message` has `conversation_id`). Read it in full first; its module
docstring carries the live measurements. The migration of existing
records is a separate, later card: do not touch `migrate.py`.

## Deliverable

1. **`src/ckm365/models.py`**
   - `Message` gains `conversation_id: str | None = None`,
     `conversation_index: str | None = None`, `unique_body: Body | None = None`
     (appended after `parent_folder_id`), filled in `Message._kw` from
     `conversationId`, `conversationIndex`, `uniqueBody` (`Body.from_graph`
     when present). Add `conversationId,conversationIndex` to
     `Message.SELECT`; NOT `uniqueBody`.
   - `MessageHeaders` gains `in_reply_to: str | None = None` (a normal
     curated header: add `"in-reply-to": "in_reply_to"` to
     `_CURATED_HEADERS`) and `references: list[str]` (default empty).
     References is NOT in `_CURATED_HEADERS`; parse it separately in
     `from_graph` (first occurrence wins): drop control characters,
     find tokens with `<[^<>\s]*>` after that, drop any token longer
     than 250 characters, keep the LAST 100. A two-line comment says
     why (a long thread legitimately exceeds the 200 cap; measured 23
     ids / 1,850 characters).
2. **`src/ckm365/tools/mail/export.py`**
   - `mid_uri(internet_message_id: str | None) -> str | None`, public:
     strip whitespace and the angle brackets; empty -> None; else
     `"mid:" + quote(value, safe="@!$&'()*+,;=:~._-")` (RFC 2392).
   - `record_bytes(g, mailbox, message_id, *, full_body: bool = False)`:
     unless `full_body`, add `,uniqueBody` to the `$select` of the one
     message GET (same `prefer("text")`).
   - `_record(...)` gains the scope decision and new keys. Front matter
     in EXACTLY this order: type `"Message"`, channel `"email"`, title,
     description, resource (`mid_uri(...)`, or `web_link` when that is
     None), tags, generated, from, to, cc, mailbox, message_id,
     internet_message_id, conversation_id (`""` when None),
     in_reply_to (`""` when None), references (list, `[]` when none),
     web_link, body_scope, has_attachments, is_bulk, is_auto_reply.
     Body: `unique_body.content` when not `full_body` and it is
     non-blank, with `body_scope: "unique"`; otherwise the full body,
     `"full"`.
   - `export_message` gains `full_body: bool = False` (after `force`),
     passed to `record_bytes`; ignored for `.eml`. Update its docstring
     (keep the voice): what body_scope means, that uniqueBody is Graph's
     own new-text-only rendering, that the `.eml` is the complete chain,
     that `resource` is the `mid:` URI and `web_link` is per mailbox.
     The OKF note in `_record`'s docstring about `type`/`resource`
     changes accordingly; keep the rest.
3. **Existing tests that encode the old record** (only these edits):
   - `tests/test_mail_export.py` line 95: `'type: "Email"'` becomes
     `'type: "Message"'`; line 98: the resource line becomes
     `'resource: "mid:abc123@tenant-b.example"'`, and add the line
     `'web_link: "https://outlook.office365.com/mail/deeplink/m1"'` to
     the same tuple.
   - Nothing else in that file. If another existing test breaks, stop
     and say so in open_questions.

## Files you may touch

- `src/ckm365/models.py`, `src/ckm365/tools/mail/export.py`
- `tests/test_mail_export.py`: the edits above only.

Read only those plus `tests/test_mail_threading.py`. `migrate.py` calls
`record_bytes(g, mb, message_id)` positionally; that call must keep
working unchanged. No new tool, so no preset counts move.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report the before and after counted results; after: everything
passing, one fewer module skipped, about 21 more passed.

## Not in scope

- The planner/apply upgrade of existing records (next card), `type`
  rules in `migrate.py`, `MessageSummary`, `get_message`'s behaviour.
- Any live check, `CKM365_LIVE_*`, anything under `~/.config/ckm365`.
- Version bump, CHANGELOG, README, docs, board files. No commits.

## Relates to

- tvtrb0 (CKM-49): the issue. k4r9tw (bulk export) groups by conversation.
