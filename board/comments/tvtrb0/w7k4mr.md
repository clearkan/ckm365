---
type: comment
at: "2026-11-07T01:30:00Z"
by: "claude"
event: "completed"
---

Done. Step 2 merged from Codex card w3c9pg (8 model calls, 181 s). It
stopped on two spec assertions that tested for a literal `$filter` in an
encoded URL; Codex was right, the spec was wrong, fixed on main.

Two changes at merge: the metadata GET goes through `message_path`; and
a 404 on one candidate mailbox now falls through to the next. The second
was found by the read-only dry run over two real folders: with one
tenant's profile, records naming the other tenant's mailbox failed with
ErrorInvalidUser instead of trying the selected mailbox.

Verified on the real folders, read-only, then on temporary copies
(deleted): 92 old records (56 pre-CKM-49 v0.2, 36 v0.1) located with the
right profile and `not-found` with the other, never `failed`; applied to
the copies, all 92 bodies byte-identical, the key changes exactly those
specified, a second run changed nothing, and the planner then calls all
92 current. Offline 342 passed.

The real folders themselves are untouched: applying for real is
seanwy's call, per folder, on a clean tree.
