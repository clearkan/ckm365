---
type: comment
at: "2026-11-07T02:30:00Z"
by: "claude"
event: "completed"
---

Shipped in v2.12.0 from Codex card h7t3qf (7 model calls, 116 s):
`export_messages`, read tier. Changed at merge: listings page 100 rows
at a time; an `already` message gets no second `.eml`; the docstring
says a truncated folder listing is cut in Graph's order.

Verified: offline 372 passed (30 bulk tests); live on one real thread
into a temporary directory (deleted): dry run 4 would-write, first run 4
written with 4 `.eml`, names matching the convention, oldest first, a
rerun 4 already.
