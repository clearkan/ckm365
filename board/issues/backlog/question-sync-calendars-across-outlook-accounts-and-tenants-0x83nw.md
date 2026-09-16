---
type: issue
title: "Question: sync calendars across Outlook accounts and tenants with personal access"
created: "2026-09-17T00:30:00Z"
resource: "oif:ckm/0x83nw"
kind: "task"
priority: "low"
requested_by: "human:seanwy"
tags: ["calendar", "sync", "multi-tenant", "client-tenant", "research", "question"]
---

A question relayed from a prospective user: could ckm365 keep several Outlook
calendars in sync across DIFFERENT accounts in DIFFERENT tenants, using only
their own personal (delegated) access, with a few basic rules — for example
"mirror every event from calendar A into calendar B as a private Busy block"?
What is the most basic setup, and do they need Claude Code at all, or would a
scheduled or routine feature in Claude or ChatGPT do it? Guidance: simple is
sweet.

This issue records the answer. It is a question, not a build request.

## Short answer so far

**Within tenants where the user can get calendar consent, yes — today, with
no code change and no LLM.** A one-way busy-block mirror is the simple case
and needs only the existing tools. Two-way sync is also reachable, through
the Graph escape hatch rather than the tool list, but is materially harder
to get right (echo prevention, conflict handling) and not worth it unless
genuinely needed. And the premise "as long as they use their personal access
model" breaks down in exactly the case that motivates the question: a CLIENT
tenant.

## The blocker is consent, not code (verified, CKM-29)

Our own consent-floor research (CKM-29, 2026-08) found that Microsoft's managed
default consent policy — the default for new tenants, and force-migrated onto
legacy tenants from 2025-07-16 — **excludes `Mail.*` and `Calendars.*` from
user consent entirely.** On top of that, users cannot consent to a multi-tenant
app from an unverified publisher beyond basic sign-in.

Consequences, and they are not specific to ckm365:

- In a client tenant where the user is an ordinary MEMBER, no third-party app
  gets `Calendars.ReadWrite` on personal consent. It needs one admin click
  (CKM-31 is the paperwork for that: publisher verification plus the ask).
- In a client tenant where the user is a GUEST, there is no calendar to sync —
  guests have no mailbox there. The honest answer is to request a member
  account (CKM-31).
- The same wall applies to any THIRD-PARTY app asking for calendar scopes:
  Claude's and ChatGPT's Microsoft connectors and third-party sync services
  included. Microsoft's own first-party apps are the exception, because they
  are pre-consented. Whether that holds for each named product is being
  verified in the research below rather than assumed.

## What ckm365 can do today (verified from code)

Works for a ONE-WAY busy-block mirror:

- `list_events(start, end)` reads a calendar VIEW, so recurring series come
  back as individual instances — no recurrence expansion to write.
- `isCancelled` is selected, so cancellations are visible when reading.
- `create_event` with NO attendees is write tier only and sends nothing.
  Worth stating because it is load-bearing: with attendees, `create_event`
  escalates to the SEND tier (tools/calendar.py:68) because invitations go
  out the moment Graph saves the event. A mirrored hold must never carry
  attendees.
- Multi-tenant named profiles with delegated login are the core design, so
  reading from one profile and writing to another is the ordinary case.
- A plain Python script can do all of this through the supported programmatic
  API — no MCP server, no Claude session, no LLM.

Beyond the tools, the capability is broader than the tool list suggests. A
sync is a SCRIPT, and a script gets the whole Graph surface the token allows
through the supported escape hatch (`ctx.graph()` plus `Graph.request`,
docs/graph-direct.md). `Calendars.ReadWrite` covers all of the following:

- **Delete events: works today, proven.** There is no `delete_event` TOOL,
  but sessions have deleted events with a direct Graph `DELETE` on
  `/events/{id}` five times across four transcripts. So a mirror CAN be
  removed when its source is deleted or cancelled.
- **An invisible marker: reachable, not live-tested here.** Graph's
  `singleValueExtendedProperties` can be set on create and filtered on read
  through the same wrapper. That is what makes idempotency ("find the copy I
  made last time") reliable, and what makes TWO-WAY sync possible at all —
  A->B->A echo is prevented by skipping anything carrying your own marker.
- **`showAs` / `sensitivity`: reachable, not live-tested here.** Set them in
  the create payload to make a mirror a private Busy block, and read them to
  honour rules like "skip events marked free or private".
- **Calendar delta: reachable, not live-tested here.** `calendarView/delta`
  is a plain GET. Polling a date window is simpler and fine at this scale.

What is genuinely missing is only the MCP TOOL surface for these — no
`delete_event`, no marker or `showAs` parameters on `create_event`. That
matters only if the sync is driven by an LLM calling tools rather than by a
script. docs/graph-direct.md rule 5 applies: a direct call is a workaround,
not a capability, so if the LLM-driven route is ever wanted, those are the
tool gaps to file.

## Confidentiality, before anyone builds it

Copying event DETAILS out of a client tenant into another tenant can breach
client confidentiality even when it is technically allowed. Busy-block mode
(generic subject, no body, no attendees, no location) is the only mode worth
recommending across a tenant boundary.

## External landscape

Being researched now: current Claude features (Claude Code scheduled routines,
Cowork scheduled tasks, the Microsoft 365 connector), current ChatGPT features
(scheduled Tasks, agent mode, connectors, custom MCP), and non-AI baselines
(Power Automate, native Outlook options, third-party sync services), each
checked against the consent wall above. Findings and a recommendation will be
added as a comment and folded into this body.
