---
type: issue
resource: oif:ckm/cw81fa
title: Recipient exclusion list - warn on draft, refuse on send
description: Check To/Cc/Bcc against a per-profile list of opted-out or dead addresses, warn on every draft tool and refuse send_draft unless overridden.
kind: feature
priority: medium
requested_by: human:seanwy
tags: [mail, compose, send, safety]
created: 2026-10-01T00:26:33Z
---

Requested by seanwy from live client work. Distribution emails (meeting notes,
agendas, action follow-ups) take their recipients from a calendar invite or a
reply-all, and both lag behind reality. Someone who replied "REMOVE", or whose
address now bounces, stays on the invite until the organiser changes it, which
may be weeks. The calling agent is supposed to check a list kept in the
project repo, but nothing in the tool stops a missed check. Sending to someone
who has opted out is the outcome to prevent.

## Proposed shape

- **A list file per profile**: `exclusions_file = "<path>"` in profiles.toml,
  plus an optional per-call `exclusions_file` argument so a project repo can keep
  its own. YAML with `entries: [{address, action: exclude|warn, type, scope,
  since, until, source, notes}]`. Match addresses case-insensitively, and ignore
  entries whose `until` has passed.
- **Draft tools warn and still create the draft.** That covers create_draft,
  create_reply_draft (especially reply_all, which pulls in recipients the
  caller never named), create_forward_draft and update_draft. Add
  `recipient_warnings: [{address, field, action, type, source}]` to the
  result. Leave the recipients on the draft: removing someone silently is
  worse than flagging them.
- **send_draft refuses** when any `action: exclude` address is on the draft,
  unless `override_exclusions=True`. `warn` entries never block a send.
- **A read tool, check_recipients(addresses)**, so an agent can test a list
  before it builds a draft.
- **Scope** (optional): an entry may name the series it applies to. A cheap
  first cut is a subject substring, e.g. "Co-ordination Meeting". Entries with
  no scope apply to everything.

## Notes for the implementer

- The list belongs to the caller's project or profile. Ship no data with the
  tool.
- A later step could suggest entries from inbound mail: replies whose subject
  starts "REMOVE", and NDRs with `Auto-Submitted` set and a failed recipient.
  Suggest only, never add on its own; the human decides.
- The read tier only reads the file. Writing the list is the caller's job.
