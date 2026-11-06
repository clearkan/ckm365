---
type: comment
at: "2026-11-06T06:30:00Z"
by: "claude"
event: "commented"
---

Step 1 merged (Codex card e8r5wc, 7 model calls, 114 s, spec shown
failing before). All four items of this issue are in the record now.

Verified: offline 327 passed; the live export test passes on both
delegated tenants with the new assertions; one real reply exported both
ways (to a temporary directory, deleted): unique body 467 characters
against 4,069 full, one reference, In-Reply-To present, `mid:` resource,
80-character conversation id.

Step 2 queued as card w3c9pg: the planner and apply step bring records
already on disk up to date, front matter only, with thread metadata from
Graph (no body read). Spec `tests/test_mail_migrate_threading.py`.
