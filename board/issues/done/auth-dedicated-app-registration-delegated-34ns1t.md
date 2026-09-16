---
type: "issue"
title: "Auth — dedicated app registration + delegated device code flow (interactive)"
created: "2026-07-29T21:47:41Z"
resource: "oif:ckm/34ns1t"
aliases: ["CKM-4"]
kind: "task"
priority: "high"
assignees: ["claude", "seanwy"]
requested_by: "human:seanwy"
tags: ["auth", "interactive"]
depends_on: ["8nd03y"]
depends_on_aliases: ["CKM-3"]
---

INTERACTIVE with seanwy — propose exact commands, seanwy runs/approves.
MULTI-TENANT: repeat per tenant profile (e.g. tenant-a.example AND tenant-b.example) —
one dedicated app registration per tenant, one profile entry each.

- New dedicated app registration (do NOT reuse Claude M365 connector app)
- Pin each profile's tenant ID in its MSAL authority URL — NEVER
  `common` (refresh tokens via common die after ~1h as of mid-2026)
- Delegated scopes: Mail.ReadWrite, Mail.ReadWrite.Shared,
  Calendars.ReadWrite, Calendars.ReadWrite.Shared, offline_access
- Confirm full-access on ops@tenant-a.example first
  (Get-MailboxPermission ops@tenant-a.example)
- Token cache: OS credential store, file fallback with 0600 perms
