---
type: "issue"
title: "Calendar invites — respond_event tool + Teams meeting provisioning"
created: "2026-07-30T00:56:30Z"
resource: "oif:ckm/zvn7xb"
aliases: ["CKM-17"]
kind: "feature"
priority: "high"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["phase-1", "calendar", "teams"]
depends_on: ["ejwm57"]
depends_on_aliases: ["CKM-12"]
---

seanwy: keen to see how setting up calendar invites works, and accepting;
test between the two shared mailboxes; how to attach a Teams invite?

Added:
- respond_event(event_id, response=accept|tentative|decline, comment,
  send_response) — send_response=True notifies the organizer and is
  send-tier; False only updates the local calendar (write-tier)
- create_event(online_meeting=True) — sets isOnlineMeeting +
  onlineMeetingProvider=teamsForBusiness; Graph provisions the Teams
  join link (surfaced as join_url)

Live results (cross-tenant, shared mailboxes):
- ops@tenant-a.example invited agent@tenant-b.example: invitation
  delivered cross-tenant, event auto-appeared tentative in the invitee
  calendar, respond_event accept with comment worked, organizer copy
  shows response=accepted. Full lifecycle green.
- Teams provisioning: silently SKIPPED when the organizer is an
  unlicensed shared mailbox (no error, no join link). Licensed-user
  probe: join link provisioned correctly. Conclusion: organize Teams
  meetings from a licensed account (inviting the shared mailbox), or
  license the shared mailbox.
