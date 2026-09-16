---
type: comment
at: "2026-09-17T00:50:00Z"
by: "claude"
event: "updated"
---

Correction, prompted by seanwy pointing out that sessions create AND delete
events in his own calendar. He was right.

The original body said "No delete_event — the single biggest gap". That
conflated the MCP tool list with what ckm365 can do. The transcripts show five
direct Graph DELETEs on /events/ across four sessions, through the escape hatch
rather than a tool. And the recommended setup is a script, which uses that
escape hatch anyway, so the missing TOOL does not affect it.

The same error ran through the rest of the list: an invisible marker via
singleValueExtendedProperties, showAs/sensitivity, and calendar delta are all
reachable through the Graph wrapper under Calendars.ReadWrite. Unlike delete,
those three have not been exercised live here, and the body now says so.

Net change to the answer: two-way sync moves from "not supported" to
"reachable but harder, and not worth it unless needed". The one-way busy-block
mirror remains the recommendation. The consent wall in client tenants is
unaffected — that is a permission problem, and no escape hatch gets around it.
