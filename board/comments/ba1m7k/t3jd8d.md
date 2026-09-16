---
type: comment
at: "2026-08-30T04:55:16Z"
by: "claude"
event: "updated"
---

Item 4 RETRACTED as originally worded: scripts/draft-cycle-smoke.py already provides the write-path smoke (CKM-42, 2026-08-19) and is more thorough than the replacement proposed. Reframed to the real, narrower defect — the write smoke was absent from README Setup and onboarding.md. Items 1, 2, 4, 5 fixed in the docs commit; offline suite green (153 passed, 15 skipped). Item 3 (doctor --mcp) left open and is now the ticket's remaining scope; priority high -> medium since the docs now warn where they previously misled.
