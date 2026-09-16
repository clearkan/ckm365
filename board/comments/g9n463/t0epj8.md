---
type: comment
at: "2026-08-05T12:30:00Z"
by: "claude"
event: "completed"
---

Done in v2.2.0. unread_only/flagged_only/since/from_address compose into ONE server-side $filter, with the raw filter ANDed in alongside rather than competing. group_by_sender added (read tier, $select=from,isRead only). The search/filter exclusivity and the loss of newest-first ordering under any filter are now spelled out in the docstring. Two corrections to the issue's own sketch, recorded rather than silently worked around: (1) filtered list calls were NOT bypassing the retry plumbing — GET already retried 503 — the budget was simply too short, three retries on a 0.2s base landing inside one blip, so the fix is 5 retries on a 1s base for 503/504 while throttling keeps its old budget and Retry-After handling; (2) "say so in the return value where a predicate cannot be pushed server-side" turned out to have no case to report — all four predicates push to Graph, nothing degrades to a scan, and list_messages keeps returning list[MessageSummary] rather than taking a breaking return-shape change to carry a field that would always be empty. Live: isRead eq false (the filter that 503'd) returns server-side on both tenants, and group_by_sender walked 500 messages into 148/106 senders in one call. Cross-folder search and metadata caching stayed out.
