"""Teams discovery over Graph: teams, channels, installed apps (read-only).

Scope of this module (CKM-24 decision, option (c)): ckm365 stays a Graph
client. Teams *bot messaging* — Bot Framework endpoints, inbound activity
validation, replay protection — is a different service with a different
token audience and issuer, and deliberately lives elsewhere. What is
genuinely Graph-shaped is discovery: turning names into the team/channel
ids that other systems otherwise hard-code in config.

Two things differ from every other tool module here:

- These resources are ORG-scoped, not mailbox-scoped, so they take no
  `mailbox` and use ctx.graph() rather than ctx.target().
- The listing endpoint depends on the auth mode: delegated tokens use
  /me/joinedTeams (only teams the signed-in user belongs to — least
  privilege, and usually what a human means); app-only tokens have no
  "me" and use /teams (every team in the tenant).

Graph fact paid for live (2026-08-01): the Teams endpoints reject
`$top` with 400 "Query option 'Top' is not allowed" — /me/joinedTeams,
/teams/{id}/channels, and /teams/{id}/installedApps all refuse it (only
the app-only /teams collection accepts it). So none of these calls send
`$top`; the caller's `top` is applied client-side by pull()/paged(),
which caps the result and stops following pages. `$select` and `$expand`
ARE supported everywhere they are used here.

Consent is a SEPARATE least-privilege tier (scripts/add-teams-scopes.sh),
never folded into the mailbox scopes: a mail --write flag must never
imply the ability to enumerate Teams. Note the app-only asymmetry —
Exchange RBAC-for-Applications scoping does NOT apply to Teams, so an
app-only Team.ReadBasic.All grant reads every team in the tenant. Prefer
delegated for Teams discovery; if app-only is required, scope it with
Teams resource-specific consent (RSC) per team.
"""

from ..graph import encode_segment as _seg
from ..models import Channel, InstalledApp, Team
from .context import Ctx, pull


def list_teams(ctx: Ctx, *, top: int = 50,
               account: str | None = None) -> list[Team]:
    """List Microsoft Teams as ids you can pass to the other teams tools.

    Delegated profiles see only the teams the signed-in user has joined;
    app-only profiles see every team in the tenant. Returns id, name,
    description, archived flag, and web URL — no messages, no members.
    """
    if not 1 <= top <= 500:
        raise ValueError("top must be between 1 and 500")
    g = ctx.graph(account)
    path = "/teams" if ctx.profile(account).auth == "client_credential" \
        else "/me/joinedTeams"
    return pull(g, Team, path, top=top, params={"$select": Team.SELECT})


def list_channels(ctx: Ctx, team_id: str, *, top: int = 50,
                  account: str | None = None) -> list[Channel]:
    """List the channels of one team (get team_id from list_teams).

    Returns each channel's id, name, description, membership type
    (standard/private/shared), and — where the channel has one — the
    address mail can be sent to. Channel ids are what posting systems
    need configured; this is how you look them up instead of hard-coding.
    """
    if not 1 <= top <= 500:
        raise ValueError("top must be between 1 and 500")
    g = ctx.graph(account)
    return pull(g, Channel, f"/teams/{_seg(team_id, 'team_id')}/channels",
                top=top, params={"$select": Channel.SELECT})


def list_installed_apps(ctx: Ctx, team_id: str, *, top: int = 50,
                        account: str | None = None) -> list[InstalledApp]:
    """List the Teams apps installed in one team.

    Use this to check whether a bot/app is provisioned in a team before
    relying on it. Returns the installation id plus the app's display
    name, version, and catalog id.
    """
    if not 1 <= top <= 500:
        raise ValueError("top must be between 1 and 500")
    g = ctx.graph(account)
    return pull(g, InstalledApp,
                f"/teams/{_seg(team_id, 'team_id')}/installedApps", top=top,
                params={"$expand": "teamsAppDefinition"})
