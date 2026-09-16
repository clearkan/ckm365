---
type: "issue"
title: "Reliable server-side filtering (unread / flagged / since) + transient retry"
created: "2026-08-05T00:14:00Z"
resource: "oif:ckm/g9n463"
aliases: ["CKM-35"]
kind: "feature"
priority: "high"
requested_by: "claude"
tags: ["mail", "read-tier", "performance"]
---

claude (2026-08-05): list_messages already takes an OData `filter`, but in
real use on a high-volume mailbox it failed and there was no good fallback.
This is the issue that made a triage task slow and fragile.

What actually happened:
- `filter="isRead eq false"` returned HTTP 503
  "ErrorInternalServerTransientError ... Cannot query rows in a table"
  on a large mailbox. Twice in a row, so not a one-off blip.
- With no working server-side filter, the fallback was to page unfiltered
  and classify client-side. That meant pulling 1200-6000 messages to find
  ~20 interesting ones. One 6000-message pass exceeded a 120s tool
  timeout and had to be backgrounded.
- Cost is not just latency: every one of those messages crosses the
  agent's context boundary if the caller is not careful.

Required:
- RETRY TRANSIENTS. 503 ErrorInternalServerTransientError and 429 are
  retryable with backoff; the Graph client already has retry plumbing for
  throttling — filtered list calls must use it. A filter that works on
  the second attempt should never surface as a failure at all.
- First-class predicates instead of hand-written OData, because the
  hand-written form is where the fragility lives:
    unread_only: bool
    flagged_only: bool
    since: ISO date/datetime  (receivedDateTime ge ...)
    from_address: str
  These compose into one $filter server-side. Keep the raw `filter`
  escape hatch for anything not covered.
- DOCUMENT the search/filter exclusivity that already exists (they cannot
  be combined, and filtered results come back in Graph's default order,
  not the requested $orderby). This surprised the caller mid-task.
- Where a predicate genuinely cannot be pushed server-side, say so in the
  return value rather than silently degrading to a full scan. A caller
  that knows it is scanning can bound it; one that does not will hang.

Nice to have, sharply useful for triage: group_by_sender(folder, since)
returning sender -> {total, unread} counts without returning message
bodies. The motivating analysis — "which senders actually generate this
volume" — needed exactly this and had to be done by scanning everything.
Six automated senders accounted for ~40% of inbox volume; that fact took
1500 messages through context to establish and should have been one call.

Out of scope v1: cross-folder search (its own issue), and any caching of
message metadata between calls.
