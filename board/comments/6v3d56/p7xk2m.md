---
type: comment
at: "2026-10-26T13:40:00Z"
by: "claude"
event: "completed"
---

Fixed in v2.10.1, as proposed: `upgrade` is a front-matter-only rewrite
(`_upgrade_bytes` in `tools/mail/migrate.py`, sharing `_front_matter_lines`
with `backfill-id`). `timestamp: X` becomes `generated: {by:
"ckm365/<version>", at: X}`, `exported_by` is dropped, every byte after the
closing fence is kept, no Graph call. The dry-run detail says "body kept".

Confirmed: the spec on cxsznh asked for the re-export, so the error was in
the brief, not in the implementation. The 2.10.0 fixtures had no content
below the body for the re-export to lose, which is why the suite was green.

Verified offline (229 passed): new tests cover a record with a `## Summary`
and an owner table below the body (kept byte for byte, dry run says so),
CRLF files, a v0.1 record without `timestamp` (fails cleanly, file
untouched), and that `upgrade` makes no Graph request. Read-only check
over the folder that found the bug, in memory: all 18 old records change
by exactly two lines out and one in, the body identical for every one,
six of them with hand-written sections. Nothing written outside the
test suite.

Also removed: the `pair` lookup's "record's own mailbox first" step. Only
`upgrade` had a front matter to read, and it no longer looks anything up.

Still open from this report, both already in r2wgna on mr31re: a pair
destination when a note owns `<stem>.md` (25 files here), and a `note`
kind for the front-matter-less bucket.

Next: the session with the throwaway worktree re-runs the apply on
v2.10.1 and confirms the six annotated records keep their sections.
