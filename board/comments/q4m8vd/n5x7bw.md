---
type: comment
at: "2026-11-06T00:30:00Z"
by: "claude"
event: "completed"
---

Squash-merged into v2.11.0 with one change: the planner reads a record's
Message-ID with `front_matter_id` again (shared with export dedupe), and
uses `_front_matter` only for the `type` check.
