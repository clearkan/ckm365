---
type: "issue"
title: "Auth — app-only client credential + Exchange RBAC for Applications (interactive)"
created: "2026-07-29T21:47:41Z"
resource: "oif:ckm/33ahcz"
aliases: ["CKM-5"]
kind: "task"
priority: "high"
requested_by: "human:seanwy"
tags: ["auth", "interactive"]
depends_on: ["34ns1t"]
depends_on_aliases: ["CKM-4"]
---

INTERACTIVE with seanwy — walk through cmdlets, no unattended tenant changes.
MULTI-TENANT: RBAC scoping is per tenant; repeat for each profile that
needs app-only mode (mailbox lists differ per tenant).

- Application permissions Mail.ReadWrite + Calendars.ReadWrite, scoped via
  RBAC for Applications in Exchange Online (NOT legacy Application Access
  Policy): management scope covering the operator's, ops@, tst.* mailboxes;
  assign via New-ManagementRoleAssignment
- Certificate credential preferred over client secret

ClearKan asks folded in (tmp/clearkan-integration-requirements.md item 5;
their headless intake daemon DEPENDS on this issue — device-code auth is
impossible in their containers):
- 5.1 Live-verify the app-only code path end to end on one tenant
  (doctor, live-smoke, CKM365_LIVE_ACCOUNT=<profile>-app pytest
  tests/test_live.py).
- 5.2 Specifically confirm the delta/watch tools (list_new_messages /
  wait_for_message) work app-only — delta bootstrap + token round-trip
  with application permissions; report any behavioral difference.
- 5.3 Exchange RBAC scoping runbook (docs/app-only-setup.md,
  placeholders only, cert-preferred) — their enterprise-review artifact.

SAFETY ORDER (non-negotiable, from our requirements doc + review): the
Exchange RBAC management scope MUST exist before any app-only credential
verification — an unscoped application permission can read EVERY mailbox
in the tenant, even "briefly for testing". Scope first (or same
interactive sitting), then verify. Also verify the NEGATIVE: app-only
profile must get 403/404 on a mailbox outside the management scope.
