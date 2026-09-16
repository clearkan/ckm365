---
type: "issue"
title: "send_draft tool behind dedicated --enable-send flag; live cross-tenant test"
created: "2026-07-29T23:40:54Z"
resource: "oif:ckm/ejwm57"
aliases: ["CKM-12"]
kind: "feature"
priority: "high"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["phase-1", "mail", "send"]
depends_on: ["7dn1c2"]
depends_on_aliases: ["CKM-11"]
---

seanwy approved enabling full send capability (2026-07-30).

- send_draft(message_id): POST /messages/{id}/send — refuses non-drafts,
  gated behind BOTH write_enabled AND a new send_enabled flag
  (--enable-send on serve, send=True on agent_tools.register)
- implement AFTER the security review findings are addressed; reviewer
  was asked to spec the gate requirements
- live verification: fresh draft in agent@tenant-b.example -> send to seanwy;
  cross-tenant loop ops@tenant-a.example -> agent@tenant-b.example -> reply back,
  arrivals confirmed from the receiving tenant's profile
- ops@tenant-a.example .Shared access verified readable 2026-07-30
