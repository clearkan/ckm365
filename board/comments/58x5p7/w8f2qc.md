---
type: comment
at: "2026-11-06T00:30:00Z"
by: "claude"
event: "completed"
---

Shipped in v2.11.0 through Codex card q4m8vd (round 1 lost to a Codex
login that had not survived a reboot; round 2 delivered: 7 model calls,
86 s, `migrate.py` only, spec shown failing before).

All four rules from this issue are in: `note` for a record with no front
matter and no same-stem mail file, for front matter typed other than
Email, and for an `X-Unsent` `.eml`; a `.msg` is `none` when its
same-stem record carries an id. Notes are left out of duplicate
detection, pairing and the apply step's results. The thread-record
answer is the documented convention (latest message's id at top level),
in the planner's description and the README.

One change at merge: Codex read a record's id with the planner's own
front-matter parser; it is back on `front_matter_id`, the helper export
dedupe uses, so the two never disagree about a record's id.

Verified: offline 251 passed, 15 skipped. Not re-run on a real folder;
the session holding the folder that motivated this can run the planner
there and compare its `manual` count with the 33 in this issue.
