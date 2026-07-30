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

## Mode 3 — headless / app-only (planned, CKM-5)

Client-credential auth (`auth = "client_credential"` + cert/secret via
`CKM365_<PROFILE>_*` env vars) exists in the code but is not yet used: it
requires Exchange **RBAC for Applications** scoping on the tenant so the
app can only reach an allow-listed set of mailboxes. Tracked as CKM-5; do
not use app-only mode before that scoping is in place.

## Env var reference

| Var | Purpose |
|---|---|
| `CKM365_PROFILES` | Alternate path to profiles.toml |
| `CKM365_ATTACH_ROOT` | Restrict `add_attachment` reads to this directory |
| `CKM365_<PROFILE>_CLIENT_SECRET` | App-only secret (mode 3) |
| `CKM365_<PROFILE>_CLIENT_CERT_PATH` / `_CLIENT_CERT_THUMBPRINT` | App-only certificate (mode 3, preferred) |
