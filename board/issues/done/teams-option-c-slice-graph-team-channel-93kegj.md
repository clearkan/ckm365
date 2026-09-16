---
type: "issue"
title: "Teams option-(c) slice — Graph team/channel discovery + app-installation state"
created: "2026-07-30T14:52:38Z"
resource: "oif:ckm/93kegj"
aliases: ["CKM-25"]
kind: "feature"
priority: "low"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["teams", "graph", "interactive"]
depends_on: ["vqf1fg"]
depends_on_aliases: ["CKM-24"]
---

Implementation of the CKM-24 decision (option (c)): the only Teams
functionality that moves into ckm365 is the genuinely Graph-shaped
subset. Bot Framework messaging/webhooks stay downstream, permanently
under this option.

Scope (read-only, new `teams` preset):
- Team discovery (`/teams` or `/me/joinedTeams` per auth mode) and
  channel discovery (`/teams/{id}/channels`) — replaces the downstream
  consumer hand-configuring team/channel/conversation IDs via env vars.
- Teams app installation state (same caveat).

HARD REQUIREMENT carried from the downstream survey: this is a separate
reviewed consent slice with least-privilege READ scopes (candidates:
Team.ReadBasic.All, Channel.ReadBasic.All, TeamsAppInstallation
read scopes — verify exact names at implementation). It must be kept
OUT of the Mail.*/mailbox authorization: a mail --write flag must never
imply Teams reach, and the consent script must be a separate deliberate
opt-in like add-send-scopes.sh. Consent = tenant-touching = interactive
with seanwy.

Not urgent (downstream said no deadline); pure additive module over
graph.py, no structural change expected. Line budget applies.
