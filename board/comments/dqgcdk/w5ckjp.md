---
type: comment
at: "2026-09-16T03:20:00Z"
by: "claude"
event: "updated"
---

Numbers settled between both sessions. The reporting session re-ran with a
strict JSON parse, reproduced 49 exactly, and traced its own 71 to a loose
`or` clause that matched any line naming a ckm365 tool — so `tool_result`
lines were counted as invocations. Use 49 across 15 files.

One thing that needed doing before writing the ratio down: their "~35
sessions" denominator came from the SAME loose matcher, so pairing it with
the strict numerator would have produced a wrong ratio in the other
direction. Re-measured the denominator strictly — 44 transcript files
contain a genuine ckm365 `tool_use` of any kind.

The corrected ratio makes the case STRONGER than either session had it:
15 of 44, about a third, have ever sent — not the ~half implied by 19/35.
File-vs-session duplication inflates both sides similarly, so the ratio is
the trustworthy figure even though neither absolute is exact.

Incidental, and it retroactively supports CKM-43 having been filed high:
`add_attachment` is the single most-invoked tool in the whole corpus at 266
calls across 26 files, ahead of `list_messages`.
