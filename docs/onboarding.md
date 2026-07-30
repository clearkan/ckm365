# Onboarding — new user in an existing tenant

Quickstart for someone joining a tenant where ckm365 is already set up
(personal capacity, **your own mailbox only** — Mode 2 in
`docs/usage-modes.md`). No admin steps: the tenant's app registration is
already admin-consented tenant-wide, so any user in the tenant can log in
with the same ids. Every address below is a placeholder — substitute your
own.

## Prerequisites

- An M365 account in the tenant (e.g. `user@tenant-a.example`).
- The tenant's `tenant_id` and ckm365 `client_id` — ask the operator or
  copy them from their profiles.toml; **these ids are not secrets**.
- `uv` installed (Python 3.11+ is resolved by `uv sync`).
- One human per OS account: token caches live under your home directory
  and are keyed to it — never share a login session between people.

## The five steps

1. **Get the code and sync deps** (exactly `mcp`, `msal`, `httpx`,
   hash-locked):

   ```sh
   git clone <repo-url> ckm365 && cd ckm365
   uv sync
   ```

2. **Create `~/.config/ckm365/profiles.toml`** with a single profile,
   using the tenant's *existing* app registration:

   ```toml
   [profiles.tenant-a]
   tenant_id = "<tenant-a tenant guid>"
   client_id = "<ckm365-graph app id in tenant-a>"
   auth = "device_code"
   description = "My personal tenant-a mailbox"
   ```

3. **Log in as yourself** (device-code flow — open the printed URL, enter
   the code, sign in as `user@tenant-a.example`):

   ```sh
   uv run ckm365 login tenant-a
   ```

4. **Verify** with the read-only live smoke (prints counts and truncated
   ids only — safe output):

   ```sh
   uv run python scripts/live-smoke.py tenant-a
   ```

5. **Register with Claude Code**, read-only first (add `--write` later if
   you want drafts; the send tier is a deliberate extra opt-in):

   ```sh
   claude mcp add --scope user ckm365 -- uv run --directory /path/to/ckm365 \
     ckm365 serve --preset mail,calendar
   ```

## What the platform enforces, regardless of flags

All auth is **delegated**: every Graph call carries *your* identity, and
Exchange checks your rights on every request. Whatever server flags you
(or anyone else) run with:

- You cannot read another user's mailbox — not the operator's, not a
  shared one — unless an Exchange admin grants your account **FullAccess**
  on that specific mailbox.
- You cannot send as anyone else without an explicit **SendAs** grant.
- Nothing in ckm365 configuration can widen this; flags and profiles only
  *narrow* what the tools expose.

## Cautious setups: `allow_send = false`

If you never want this machine to send mail — even if the server is later
started with `--write --enable-send` — cap the profile itself:

```toml
[profiles.tenant-a]
tenant_id = "<tenant-a tenant guid>"
client_id = "<ckm365-graph app id in tenant-a>"
auth = "device_code"
allow_send = false
```

A capped profile refuses every send-tier operation (`send_draft`,
attendee-bearing event writes, meeting responses) with a profile-level
error, and its logins/token refreshes never request the `Mail.Send`
scopes, so the token cache never holds send-consented tokens.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `AADSTS65001` (consent) at login | The app registration is not admin-consented in this tenant, or you have the wrong `client_id` | Confirm the ids with the operator; the operator re-runs `scripts/create-app-registration.sh` to verify/grant consent |
| `NeedsLogin: profile 'tenant-a' needs a login` | No (or expired) cached login for the profile | `uv run ckm365 login tenant-a` |
| `multiple cached accounts for profile 'tenant-a'` | Two identities ended up in one profile cache (e.g. someone else signed in on your OS account) | `uv run ckm365 logout tenant-a && uv run ckm365 login tenant-a` |
