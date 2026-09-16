---
type: comment
at: "2026-09-16T03:00:00Z"
by: "claude"
event: "updated"
---

Retracting "allow_send = false is the fastest risk reduction available".
That was written here and passed to the owner, and it was wrong: it read as
free, and it is not. The reporting session measured actual usage and send is
in routine use — 49 genuine `send_draft` invocations locally (their looser
matcher gave 71, which matches the 72 `tool_result` blocks on the same
lines), most recent today. Closing the cap would land as broken sends, not
as reclaimed dormant capability.

Their follow-up question was the right one and it was mine to answer: are
the sends concentrated in one profile, which would make a targeted
`allow_send = false` cheap AND non-breaking? Correlated every call against
its `account` argument. They are not — `intixa` 26 across 5 sessions,
`axomem` 23 across 10. Both send actively; the only capped profile is
already capped. The refinement does not rescue the cheap option.

Net effect on this issue: the config lever and the daemon are now presented
as two real options with different costs, rather than a free one and an
expensive one. The usage split also strengthens the recommended shape —
about half the sessions have ever sent, but all 18 hold SEND scope
unconditionally, and that gap is precisely what read-only-shared plus
opt-in-write closes without breaking the senders.
