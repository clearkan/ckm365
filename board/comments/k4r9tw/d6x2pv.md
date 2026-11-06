---
type: comment
at: "2026-11-07T00:10:00Z"
by: "claude"
event: "started"
---

Decided: a read-tier TOOL, `export_messages`, not a skill. A skill only
reaches Claude; a tool reaches every MCP client, including Codex once
5gkkbh lands. No Graph batching needed.

Selectors: message ids, a conversation id (checked live: the
`conversationId eq` filter on /messages finds a thread across folders,
5 messages in 2 folders on the probe; Graph refuses $orderby with it, so
the tool sorts), or a folder with `since`/`from_address`. Files follow
the name convention proposed in 4qn81m, `YYYYMMDD_<slug>_<token>.md`
with the token from SHA-1 of the Message-ID, so a message gets the same
name everywhere. Reruns are idempotent through the existing Message-ID
dedupe. Codex card h7t3qf, spec `tests/test_mail_bulk.py`.

Not decided here: whether `pair` in the migration helper should fall
back to this conventional name when `<stem>.md` is taken (25 files in
the real folder). That is the open naming question on mr31re, still
seanwy's call.
