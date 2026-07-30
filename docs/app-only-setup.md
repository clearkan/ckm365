# App-only (client-credential) setup — per-tenant runbook

Status: **prepared, not yet live-verified** (CKM-5). Every step that
touches a tenant is interactive — the operator runs/approves; nothing here
runs unattended. All addresses/ids below are placeholders; real values
live in local config only.

App-only mode is for headless daemons (no human to complete a device-code
flow) — e.g. ClearKan's intake poller. The security story is **Exchange
RBAC for Applications**: the app can only reach mailboxes inside an
explicit management scope, and that claim is proven by a negative test,
not assumed.

## Ordering rule (non-negotiable)

**The management scope exists before any app-only credential is
verified.** An application permission without a scope can read every
mailbox in the tenant — there is no "briefly, for testing". Steps below
are in required order; do 1–3 in one sitting.

## 1. Exchange RBAC scoping (Exchange Online PowerShell, run by the admin)

Prereqs: the tenant's existing ckm365 app registration
(`scripts/create-app-registration.sh`), and a target mailbox — a `tst.*`
shared mailbox from `scripts/create-test-mailbox.ps1` is ideal for
verification before scoping the real mailbox in.

```powershell
Connect-ExchangeOnline -UserPrincipalName admin@tenant-a.example

# The app's Entra service principal OBJECT id (not the app/client id):
#   az ad sp show --id <app-client-id> --query id -o tsv
New-ServicePrincipal -AppId <app-client-id> -ObjectId <sp-object-id> `
  -DisplayName "ckm365 app-only"

# Management scope covering ONLY the allow-listed mailbox(es):
New-ManagementScope -Name "ckm365-app-scope" `
  -RecipientRestrictionFilter "PrimarySmtpAddress -eq 'tst.apponly@tenant-a.example'"
# (multi-mailbox alternative: -RecipientRestrictionFilter
#  "PrimarySmtpAddress -like 'tst.*@tenant-a.example'")

# Scoped role assignments — mail and calendar, read-write:
New-ManagementRoleAssignment -App <sp-object-id> `
  -Role "Application Mail.ReadWrite" -CustomResourceScope "ckm365-app-scope"
New-ManagementRoleAssignment -App <sp-object-id> `
  -Role "Application Calendars.ReadWrite" -CustomResourceScope "ckm365-app-scope"

# Prove the scope BEFORE any token exists — expect InScope True/False:
Test-ServicePrincipalAuthorization -Identity <sp-object-id> `
  -Resource tst.apponly@tenant-a.example | Format-Table
Test-ServicePrincipalAuthorization -Identity <sp-object-id> `
  -Resource other-user@tenant-a.example | Format-Table   # must be out of scope
```

## 2. Certificate credential (preferred over client secret)

Key material stays OUTSIDE the repo — `~/.config/ckm365/certs/` shown
here; anywhere non-repo with 600 perms works.

```sh
mkdir -p ~/.config/ckm365/certs && chmod 700 ~/.config/ckm365/certs
openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
  -keyout ~/.config/ckm365/certs/tenant-a-app.key.pem \
  -out    ~/.config/ckm365/certs/tenant-a-app.cert.pem \
  -subj   "/CN=ckm365-app-only"
chmod 600 ~/.config/ckm365/certs/tenant-a-app.key.pem

# Upload the PUBLIC cert to the app registration (--append keeps existing):
az ad app credential reset --id <app-client-id> \
  --cert "@$HOME/.config/ckm365/certs/tenant-a-app.cert.pem" --append

# SHA-1 thumbprint (hex, no colons) — MSAL needs it alongside the key:
openssl x509 -in ~/.config/ckm365/certs/tenant-a-app.cert.pem \
  -fingerprint -sha1 -noout | sed 's/^.*=//; s/://g'
```

## 3. Graph application permissions — a decision, then maybe a script

Two ways an app-only token gets mailbox access; **the difference is the
security story**:

- **RBAC-only (preferred):** grant nothing in Entra. Access comes solely
  from the step-1 role assignments, so it is scoped by construction. The
  app requests `https://graph.microsoft.com/.default`; the token carries
  no Graph roles and Exchange authorizes per RBAC.
- **App-role consent:** `scripts/add-app-permissions.sh` declares
  application permissions `Mail.ReadWrite` + `Calendars.ReadWrite`
  (role-type), admin-consents, and verifies against actual app-role
  assignments. **Caution:** Microsoft documents Exchange access as the
  UNION of Entra app-role grants and RBAC assignments — a tenant-wide
  app-role consent is NOT narrowed by the management scope. Only use this
  path if the RBAC-only path proves insufficient, and treat the step-5
  negative test as the arbiter: if the out-of-scope mailbox is readable,
  revoke the app-role consent and fall back to RBAC-only.

Start with RBAC-only. `./scripts/add-app-permissions.sh --dry-run` shows
the app-role plan without touching the tenant.

## 4. Local profile (never the repo)

Append to `~/.config/ckm365/profiles.toml` — a separate `<name>-app`
profile beside the delegated one, same tenant + app registration:

```toml
[profiles.tenant-a-app]
tenant_id = "<tenant-a tenant guid>"
client_id = "<ckm365-graph app id in tenant-a>"
auth = "client_credential"
default_mailbox = "tst.apponly@tenant-a.example"  # the scoped mailbox
allow_send = false                                # cap the send tier
description = "App-only, RBAC-scoped to tst.apponly"
```

Credentials via env (profile name uppercased, `-` → `_`):

```sh
export CKM365_TENANT_A_APP_CLIENT_CERT_PATH=~/.config/ckm365/certs/tenant-a-app.key.pem
export CKM365_TENANT_A_APP_CLIENT_CERT_THUMBPRINT=<sha1-hex-no-colons>
```

(`CKM365_<PROFILE>_CLIENT_SECRET` is the fallback if a tenant forbids
certs; prefer the cert.)

## 5. Verification (only after steps 1–4, in this order)

```sh
uv run ckm365 doctor                       # profile loads, credential mints
uv run python scripts/live-smoke.py tenant-a-app \
  --deny other-user@tenant-a.example       # read path + NEGATIVE
CKM365_LIVE_ACCOUNT=tenant-a-app uv run pytest tests/test_live.py -q
```

Then the delta/watch tools specifically (ClearKan's poller depends on
them, and they are the likeliest to differ without a signed-in user):
`list_new_messages` bootstrap + token round-trip and `wait_for_message`
against the scoped mailbox, app-only. Record any behavioral difference
from delegated mode in CHANGELOG/board history.

**The negative test is the whole story:** a mailbox OUTSIDE the
management scope must come back 403/404 (`ErrorAccessDenied` /
`ErrorItemNotFound`). If it does not, stop — revisit step 3 before the
credential is used anywhere.

## Per-tenant repetition

Everything above is per tenant (scope names, mailbox lists, certs, and
consent all differ). Repeat the whole runbook for each profile that needs
app-only mode; never share certificates between tenants.
