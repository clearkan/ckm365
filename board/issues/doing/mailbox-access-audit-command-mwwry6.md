---
type: "issue"
title: "ckm365 audit — read-only mailbox access audit and troubleshooting"
created: "2026-09-22T00:00:00Z"
resource: "oif:ckm/mwwry6"
aliases: ["CKM-54"]
kind: "feature"
priority: "high"
requested_by: "human:seanwy"
tags: ["security", "admin", "cli", "troubleshooting"]
---

Came out of an access review. A user with high Azure permissions had started
using ckm365, and the question was whether they could reach another user's
mailbox. Answering it by hand took three sources: Entra through az, Exchange
Online through pwsh, and the ckm365 token itself. The manual review also
found a forgotten app holding tenant-wide Mail.Read and Mail.Send
application permissions (its secret had expired). The owner deleted it.

Ask (seanwy, 2026-09-22): save these checks in the repo as a tool for
auditing mailbox access and for troubleshooting why ckm365 isn't working.
Output goes to the CLI, with an optional --md. It should detect what auth
it has and audit at that scope: tenant-wide for an admin with az and
Exchange, just their own view for a regular user. For each section it
can't run, it should say how to enable it.

Built: `ckm365 audit` (src/ckm365/audit.py), docs/access-audit.md, and
offline tests (tests/test_audit.py).

- [x] ckm365 section: live-verified (it caught a bad /me probe, now removed)
- [x] Entra section at tenant scope, with --user: live-verified
- [ ] Exchange section via --exchange: live run with a sign-in. The
      expired-code failure path is verified. The same cmdlets passed in the
      manual review run.
- [x] Fable 5 pre-commit review: false-clean on failed reads, the 20-member
      $expand cap, and Markdown nesting all fixed. The switch to
      roleAssignments surfaced a role that the legacy directoryRoles view had missed.
- [ ] user-scope run by a non-admin account
