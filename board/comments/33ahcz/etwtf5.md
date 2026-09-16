---
type: comment
at: "2026-07-30T14:13:08Z"
by: "claude"
event: "moved"
---

Moved to todo — all non-interactive prep is DONE and the issue is ready for the interactive sitting with seanwy (pick ONE tenant, per ckm365 doctor). Prepared: scripts/add-app-permissions.sh (application role-type permissions, preserves delegated scopes, verifies against actual appRoleAssignments, --dry-run mode; bash -n + merge logic tested offline) and docs/app-only-setup.md (RBAC-FIRST ordering, Test-ServicePrincipalAuthorization pre-checks, cert-preferred credential, <name>-app local profile recipe, verification incl. the out-of-scope negative test). OPEN QUESTION for the sitting: Microsoft documents Exchange access as the UNION of Entra app-role grants and RBAC assignments, so RBAC-only (no tenant-wide consent) is proposed as the primary path and the negative test decides whether add-app-permissions.sh is used at all. Remaining work is 100% interactive.
