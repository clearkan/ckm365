---
type: "issue"
title: "Nightly access audit — severity exit codes, baselines, scoped read-only credentials"
created: "2026-09-22T00:00:00Z"
resource: "oif:ckm/2tcqc0"
aliases: ["CKM-55"]
kind: "feature"
priority: "medium"
requested_by: "human:seanwy"
tags: ["security", "admin", "cli", "automation", "interactive"]
depends_on: ["mwwry6"]
depends_on_aliases: ["CKM-54"]
---

Follow-on to `ckm365 audit` (CKM-54). Make it runnable unattended, e.g.
nightly in CI, so that an adverse change fails the job.

**1. Exit codes by severity.** Today the audit exits 1 on RISK only.
Proposed: 0 clean, 1 WARN, 2 FAIL (the audit could not see something), 3
RISK, with the highest level winning, plus `--fail-on {warn,fail,risk}`
so CI picks the threshold. FAIL must stay distinct: an audit that could not
read is not a clean audit.

**2. Baseline, so a nightly run flags CHANGES rather than known state.**
The tenant sweep legitimately reports delegations that are intended (for
example the shared-mailbox FullAccess grants). Proposed:
`--baseline FILE` holds the accepted findings. A new app holding
application permissions, a new role holder, or a new FullAccess grant goes
to WARN or RISK. Anything baselined is reported but doesn't raise the exit
code. The baseline file names real accounts, so it lives outside this
public repo, like any audit output.

**3. Scoped read-only credentials for unattended runs.** Today every section
uses a human's interactive sign-in. Nightly needs:
- **Entra**: an app-only identity with Graph `Directory.Read.All` and
  `RoleManagement.Read.Directory` (application permissions, read-only).
  The audit would flag this app itself as INFO (not mail-capable).
  Needs an az- or Graph-direct path using the cert credential rather than
  `az login`.
- **Exchange**: a cert-auth app with `Exchange.ManageAsApp` plus the
  **Global Reader** or **View-Only Organization Management** role, never
  Exchange Admin. This follows the pattern of
  `scripts/create-exo-automation-app.sh`, but with a read-only role and its
  own app (never reuse the admin-grade automation app).
- The credentials are themselves standing access. Scope them to read-only
  roles, keep the cert in the CI credential store, and have the audit
  report the audit apps by name so a change to their permissions is
  visible.

Tenant-touching setup (app registrations, consent, role assignment) is
interactive: propose exact commands, seanwy runs.

**4. Also open from CKM-54:** a user-scope run by a non-admin account,
to confirm the personal-audit path end to end.
