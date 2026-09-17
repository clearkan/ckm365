---
type: "issue"
title: "Correlate mail to work items without relying on a ticket key in the subject"
created: "2026-09-17T08:20:00Z"
resource: "oif:ckm/nk2jc6"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
tags: ["mail", "search", "oif"]
depends_on: []
---

Raised from a client engagement, where mail is correlated to Jira work by
putting the key in the subject - `... [ABC-123]`. It works, and searching
that key does find the thread. But the practice has three weaknesses, and a
fourth arrives with OIF.

## Why the subject line is load-bearing today

It is the ONLY field that survives the round trip. Custom headers
(`X-Ticket-Id`) are stripped or dropped by gateways between Exchange, Gmail and
Notes. `References`/`In-Reply-To` survive WITHIN a thread but break the moment
somebody starts a fresh mail about the same work item - which is exactly when
the correlation is most wanted. So the subject is not a bad choice; it is the
only durable one.

Its weaknesses:

1. **A renamed subject loses it.** "Fwd: FW: your question" and the key is gone.
2. **It is at the END**, so `RE:` chains truncate it first in preview panes and
   on mobile.
3. **It carries no STREAM.** One key tells you the item but not which
   conversation it belongs to, which starts to matter as soon as a project runs
   more than one workstream.

## The fourth weakness, which is this repo's own direction

**ckm365 has already moved its board to OIF (CKM-50) and keeps the old keys in
`aliases`.** So this repo is living the migration: `oif:ckm/vdnws0` is the
identity, `CKM-31` is history. If the projects that mail each other do the
same, then a subject-line convention built on `ABC-123` shaped keys is
matching on the thing being retired, and the OIF id - short, opaque, no project
prefix - is a WORSE substring to grep for, because six lowercase characters
collide with ordinary words.

## The ask: filter at the ckm365 level, optionally

Rather than every caller reimplementing "find the mail for this work item",
consider a server-side correlation filter:

- **An opt-in filter parameter** on `list_messages` (`src/ckm365/tools/mail/read.py:75`
  already takes `search`) that takes a work-item identity and applies the
  matching rules, rather than making the caller build a query string.
- **Several match sources, in priority order**, so no single one is load-bearing:
  a body footer line (`ticket: oif:ckm/vdnws0`), the subject key, the
  `References` chain, and any alias. A hit on any is a hit.
- **Alias-aware**, because that is exactly what OIF migration produces: a thread
  may carry `CKM-31` from before the move and `vdnws0` after it, and both must
  resolve to the same item.
- **Able to say what did NOT match**, if requested - the "filter stuff that
  doesn't match" half of the ask. Useful for noticing a thread that should have
  been correlated and was not.

## Why this belongs here rather than in each caller

Every project that adopts the convention otherwise reimplements the same
fragile substring search, and each gets the alias handling subtly wrong. The
rules are small, they are about MAIL rather than about any one tracker, and
this is the only component that sees both.

## Not decided here

Whether the footer line should be machine-generated on send (ckm365 is
draft-only for mail, so a send-side convention has to be somebody's policy, not
its default), and what the canonical footer spelling is. Both want the owner.
