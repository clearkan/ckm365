# Usage modes

ckm365 is one codebase with three capability tiers and per-user, per-tenant
profiles. This doc describes the concrete setups we actually run. Nothing
here is hard-coded — every address below is an example from our tenants.

## The model in one paragraph

Each **profile** in `~/.config/ckm365/profiles.toml` pins one (tenant, app
registration) pair — never the `common` authority. All auth is **delegated**:
the server acts as whoever completed `ckm365 login <profile>`, and Exchange
enforces that identity's rights on every call. Capability is **tiered** at
server start (read → `--write` → `--write --enable-send`), scopes are
requested per tier, and send consent is a separate per-tenant opt-in. Every
tool takes `account` (profile name; hidden when the server is pinned with
`--account`) and `mailbox` (defaults to the signed-in user). `list_accounts`
shows agents what is configured, with the `description` field from the TOML.

## Mode 1 — multi-tenant operator with shared mailboxes (how seanwy runs it)

Two tenants, four mailboxes, full tier:

```toml
[profiles.tenant-a]
tenant_id = "<tenant-a tenant guid>"
client_id = "<ckm365-graph app id in tenant-a>"
auth = "device_code"
description = "Tenant A work tenant (shared mailbox: ops@tenant-a.example)"

[profiles.tenant-b]
tenant_id = "<tenant-b tenant guid>"
client_id = "<ckm365-graph app id in tenant-b>"
auth = "device_code"
description = "Tenant B tenant (agent persona shared mailbox: agent@tenant-b.example)"
```

Setup, per tenant (interactive, once):

1. `az login --tenant <tenant> --allow-no-subscriptions`
2. `./scripts/create-app-registration.sh --yes` — dedicated public-client
   app, base scopes, grant-verified admin consent, profile appended.
3. `./scripts/add-send-scopes.sh --yes` — **only if** this tenant should
   ever send. Deliberate opt-in; verified against actual grants.
4. `uv run ckm365 login <profile>` — device code as yourself.
5. `uv run python scripts/live-smoke.py <profile> --shared <shared-mailbox>
   --deny <someone-else's-mailbox>` — positive AND negative verification.

MCP registration (user scope = every Claude Code session):

```sh
claude mcp add --scope user ckm365 -- uv run --directory <repo> \
  ckm365 serve --preset mail,calendar --write --enable-send
```

Shared mailboxes need no extra config: pass `mailbox="ops@tenant-a.example"` on
any tool. Reading requires Exchange **FullAccess** for your account on that
mailbox; `send_draft` from it additionally requires **SendAs** (grant:
`Add-MailboxPermission` / `Add-RecipientPermission` in Exchange Online
PowerShell). Cross-tenant flows are just two calls with different `account`
values — each uses its own profile's token; nothing is shared between
tenants.

Operator cautions for the full tier:
- Send-capable tools in every session means trusting every agent/session
  with outbound mail. Downgrade globally by dropping `--enable-send` (or
  `--write`) from the user-scope registration, and add a local-scope
  registration with more capability only where needed (same server name at
  local scope shadows user scope in that project).
- `--account <profile>` pins a server to one tenant and removes the
  `account` parameter from tool schemas entirely — use it for agents that
  should never touch the other tenant.
- Set `CKM365_ATTACH_ROOT=<dir>` to confine which local files
  `add_attachment` may read.

## Mode 2 — personal, single account (e.g. colleague@tenant-b.example)

Goal: use the tools for **your own mailbox only**. No admin steps needed —
the app registration is already admin-consented tenant-wide. Self-contained
step-by-step version with troubleshooting: **`docs/onboarding.md`**.

1. Get the code and `uv sync`.
2. Create `~/.config/ckm365/profiles.toml` with ONE profile — same
   `tenant_id`/`client_id` as the tenant's existing registration (ask the
   operator, or copy from them; these ids are not secrets):

   ```toml
   [profiles.tenant-b]
   tenant_id = "<tenant-b tenant guid>"
   client_id = "<ckm365-graph app id in tenant-b>"
   auth = "device_code"
   description = "My personal tenant-b mailbox"
   ```

3. `uv run ckm365 login tenant-b` — sign in **as yourself**.
4. Register read-only first; add `--write` when drafts are wanted:

   ```sh
   claude mcp add --scope user ckm365 -- uv run --directory <repo> \
     ckm365 serve --preset mail,calendar
   ```

What the platform enforces, regardless of local flags: every Graph call
carries *your* identity. You cannot read anyone else's mailbox, and you
cannot send as anyone else — including the operator — unless an Exchange
admin explicitly grants FullAccess/SendAs on a specific mailbox. Omitting
`--enable-send` (and skipping nothing else) keeps your setup send-free;
your token cache never holds send-consented refresh tokens acquired by you
unless you log in after the send tier is exercised for your account. To
make send-free permanent per profile, set `allow_send = false` in
profiles.toml: the send tier then refuses regardless of server flags, and
that profile never requests the `Mail.Send` scopes.

One rule: one human per OS account. Caches live under your home directory
(0700/0600, flock-protected); don't share a login session between people.

## Mode 3 — headless / app-only (live-verified, CKM-5)

Client-credential auth (`auth = "client_credential"` + cert via
`CKM365_<PROFILE>_*` env vars), with Exchange **RBAC for Applications**
scoping so the app can only reach an allow-listed set of mailboxes — no
tenant-wide Graph application permissions at all (verified: the role
assignments alone authorize, and out-of-scope mailboxes get 403). The
full per-tenant recipe — automation-app bootstrap, scripted RBAC,
certificate credential, verification incl. the mandatory out-of-scope
negative test, and the CI/Jenkins loop — is **`docs/app-only-setup.md`**.
Never enable an app-only profile before its scope exists.

## The `teams` preset — read-only discovery, separate consent

Turns names into the team/channel ids other systems otherwise hard-code
(`list_teams` → `list_channels` / `list_installed_apps`). Deliberately
narrow, per the CKM-24 decision: ckm365 is a Graph client, so Teams *bot
messaging* — Bot Framework endpoints, inbound activity validation, replay
protection — is not here and is not planned.

```sh
./scripts/add-teams-scopes.sh --dry-run   # then --yes; per tenant
uv run ckm365 login <profile>             # re-login to pick up the scopes
uv run python scripts/live-smoke.py <profile> --teams
claude mcp add --scope user ckm365 -- uv run --directory <repo> \
  ckm365 serve --preset mail,calendar,teams
```

Three things to know:

- **Its own consent tier.** Delegated `Team.ReadBasic.All`,
  `Channel.ReadBasic.All`, `TeamsAppInstallation.ReadForTeam` — added by
  a separate script that merges into the app's existing permissions.
  Mail/calendar tiers never imply Teams reach, and `teams` has no write
  or send tier.
- **Org-scoped, not mailbox-scoped.** These tools take no `mailbox`
  parameter; they read the tenant's Teams graph, not a person's mail.
- **Delegated is the safe mode.** A delegated token sees only the
  signed-in user's joined teams (`/me/joinedTeams`). App-only has no
  "me", so it lists every team in the tenant (`/teams`) — and Exchange
  RBAC-for-Applications does NOT constrain Teams, so there is no
  mailbox-style scope to fall back on. If a headless caller needs Teams,
  scope it per team with Teams resource-specific consent (RSC).

## The `meetings` preset — transcript retrieval (read-only)

Meeting CONTENT after the fact, over plain Graph REST: no bot joins the
call, no audio is captured. Live media would need the .NET media library
on a Windows VM in Azure — deliberately out of scope (CKM-28). The old
per-minute transcript meter was removed on 2025-08-25, so this costs
nothing.

Flow: a calendar event's `join_url` → `find_meeting_id` →
`list_meeting_transcripts` → `get_meeting_transcript` (VTT by default,
`text/plain` available).

**TWO admin gates, and the second one surprises people:**

1. `scripts/add-transcript-scopes.sh` grants delegated
   `OnlineMeetings.Read` + `OnlineMeetingTranscript.Read.All`. The
   `.Read.All` is admin-consent-required *by definition* — no tenant
   setting ever opens it to user consent.
2. Teams has a separate tenant kill-switch. Even with consent granted,
   the API returns `403 "Graph API access to transcripts is disabled for
   this tenant"` until an admin turns on **Teams admin center → Meetings
   → Meeting settings → Transcript API access → Microsoft Graph access**
   (or `Set-CsTeamsMeetingConfiguration -EnableGraphTranscriptAccess $true
   -Identity Global`). It defaults to OFF and has been **enforced since
   2026-07-29**. `EnableAttributedTranscripts` additionally controls
   whether speaker names appear; also off by default.

What you can read: transcripts of meetings the signed-in user organised
**or is on the calendar invite for** — attending counts, not just
organising. Someone must have started transcription during the meeting.

```sh
./scripts/add-transcript-scopes.sh --dry-run    # then --yes; per tenant
uv run python scripts/live-smoke.py <profile> --transcripts
claude mcp add --scope user ckm365 -- uv run --directory <repo> \
  ckm365 serve --preset mail,calendar,meetings
```

Transcript text is meeting content — as sensitive as mail bodies. It is
returned to the caller but never logged, and the smoke script prints
character counts only.

## Programmatic use (no MCP, no agent)

For daemons and plain scripts (ClearKan's intake poller is the canonical
consumer): import the supported surface directly — see README
"Supported programmatic API" for exactly what is SemVer'd.

```python
from ckm365.tools import Ctx
from ckm365.tools.watch import list_new_messages

# account= pins the Ctx to one profile (isolation, not just a default);
# the context-manager form closes the httpx pools on exit.
with Ctx.create(account="tenant-a", write=False) as ctx:
    res = list_new_messages(ctx, mailbox="ops@tenant-a.example")
    token = res["delta_token"]        # bootstrap poll: carry this forward
    while polling:
        res = list_new_messages(ctx, token, mailbox="ops@tenant-a.example")
        token = res["delta_token"]
        for msg in res["messages"]:   # MessageSummary models
            handle(msg.id)
```

Notes:

- `list_new_messages` returns a **dict** `{"messages": [MessageSummary],
  "delta_token": str, "matched": int}` — not a tuple. `matched` can
  exceed `len(messages)` when capped by `top=`.
- Every tool function takes `Ctx` first, then plain typed arguments; they
  return dataclass models (or dicts of them) and raise
  `WriteDisabled`/`SendDisabled`/`GraphError`/`NeedsLogin` — the same
  gating as the MCP server, enforced in the functions themselves.
- One `Ctx` is safe across threads; async callers wrap calls in
  `await asyncio.to_thread(...)` (ckm365 is deliberately sync — MSAL has
  no async API, so an async facade would still block under the hood).
- Consumer tests inject `httpx.MockTransport` via `Graph(transport=...)`
  and install it with the supported seam:
  `ctx.set_graph("tenant-a", Graph(auth, transport=mock))` — never reach
  into private attributes.

## Env var reference

| Var | Purpose |
|---|---|
| `CKM365_PROFILES` | Alternate path to profiles.toml |
| `CKM365_ATTACH_ROOT` | Restrict `add_attachment` reads to this directory |
| `CKM365_<PROFILE>_CLIENT_SECRET` | App-only secret (mode 3) |
| `CKM365_<PROFILE>_CLIENT_CERT_PATH` / `_CLIENT_CERT_THUMBPRINT` | App-only certificate (mode 3, preferred) |
