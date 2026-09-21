---
type: comment
at: "2026-09-21T00:00:00Z"
by: "claude"
event: "note"
---

The marker-query findings from the 2026-09-16 probes are now written up in
`docs/graph-behaviour-notes.md` (calendar findings 4 to 6). calendarView with
`$expand` alone silently drops the property. Filtering on the property id
alone gets a 400. The constant-flag workaround is still unprobed.
