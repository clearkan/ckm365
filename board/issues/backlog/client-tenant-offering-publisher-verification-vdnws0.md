---
type: "issue"
title: "Client-tenant offering — publisher verification + one-click consent ask"
created: "2026-08-01T04:02:57Z"
resource: "oif:ckm/vdnws0"
aliases: ["CKM-31"]
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
tags: ["client-tenant", "auth", "interactive", "docs"]
depends_on: ["tr9bzy"]
depends_on_aliases: ["CKM-29"]
---

OPERATIONAL, not architectural — the CKM-29 research concluded ckm365
needs no code change to serve client tenants under the one-admin-click
model. What is missing is the paperwork and the ask.

Work items:
- **Publisher verification** on the multi-tenant app registration:
  needs a Microsoft AI Cloud Partner Program account plus a verified
  custom domain. START THIS EARLY — vetting turnaround is the one
  unbounded unknown in the whole plan, and without it a multi-tenant
  app cannot be user-consented in a client tenant at all.
- A dedicated **multi-tenant, delegated-only, read-only** app
  registration, separate from the existing per-tenant single-tenant
  apps. Requests exactly the scopes the ask covers — nothing
  speculative, since every extra scope makes the ask harder to approve.
- The **consent one-pager** for a client IT department: what the app
  is, that it is delegated-only (sees strictly what the signed-in user
  already sees), that it holds no unattended permissions, that it is
  revocable by deleting the enterprise app, and the exact
  /adminconsent?client_id= URL. Draft exists in git-ignored
  tmp/client-tenant-consent-floor.md.
- Ask the client admin to confirm the Teams "Graph API access to
  transcripts" setting is ON — it is a kill switch that 403s the
  transcript API even after consent is granted.
- Document the client-tenant profile shape in docs/usage-modes.md as a
  fourth mode (device-code against a client tenant using the
  multi-tenant client_id).

For guest-shaped client tenants: do not build. The honest answer is to
request a member account, which converts it to the supported case.
