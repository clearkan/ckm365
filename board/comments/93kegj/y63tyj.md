---
type: comment
at: "2026-07-31T14:43:39Z"
by: "claude"
event: "updated"
---

Code COMPLETE and released as 2.1.0; live verification is the only thing outstanding and it is gated on an interactive consent step. Built: tools/teams.py (list_teams / list_channels / list_installed_apps — read-only, org-scoped so no mailbox param, 22 code lines) + Team/Channel/InstalledApp models; teams preset with empty WRITE/SEND tiers; scripts/add-teams-scopes.sh (delegated Team.ReadBasic.All, Channel.ReadBasic.All, TeamsAppInstallation.ReadForTeam; dry-run default; MERGES into existing requiredResourceAccess so mail scopes survive; grant-verified consent loop); live-smoke --teams. DESIGN CALL: "all" preset now means mail+calendar and EXCLUDES teams — a preset with its own consent tier must be named explicitly, so no existing session gains tools that would 403 or pay their schema cost. VERIFIED: offline 67 passed (auth-mode endpoint switch delegated /me/joinedTeams vs app-only /teams, projection, id encoding as a single segment, no mailbox param, preset counts); consent script dry-run resolved all three scope ids against real Graph; live-smoke --teams on the operator tenant correctly reports the pre-consent 403 as a SKIP with mail path still green. PENDING (seanwy, tenant-touching): run ./scripts/add-teams-scopes.sh --yes on a tenant, re-login, then live-smoke --teams to verify the post-consent reads — especially that $select is honoured on /me/joinedTeams, which offline mocks cannot prove. Issue stays in doing until that runs.
