---
type: comment
at: "2026-11-06T05:30:00Z"
by: "claude"
event: "completed"
---

Merged from Codex card v6n4tj (7 model calls, 150 s). Everything in the
proposal except the three deliberate changes noted when it started (TOML,
per-call file on check_recipients only, fail closed on a bad list).
Not built: suggesting entries from inbound REMOVE replies and bounces,
which the issue marked as a later step.

Changed at merge: a bad list's error now says why; the send log keeps
mailbox and message id and counts overridden addresses.

Verified offline only (307 passed): 30 new tests over the file format,
matching, scope, expiry, all five draft tools, and send refusal and
override. Not exercised live: nothing was sent. A first real use should
be a draft to a listed address, to see the warning, before relying on
the send refusal.
