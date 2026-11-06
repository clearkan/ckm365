---
type: comment
at: "2026-11-06T02:00:00Z"
by: "claude"
event: "started"
---

Measured live on two tenants, read-only, 2026-11-06: Graph `$search` on
messages returns at most 275 rows and the nextLink chain just ends, from
the mailbox root or a folder alike. A KQL range inside the search
string, `received:A..B`, narrows it and each narrower query gets its own
275; the user's query must be parenthesised or an OR swallows the range.
Single-day ranges work.

So: a new read tool, `search_messages`, that bisects date windows until
each is under the cap and reports any single day still at it, and
`list_mail_folders` gains `parent` and `recursive`. Codex card z2k7hm,
spec in `tests/test_mail_search.py` and `tests/test_mail_folders.py`.
