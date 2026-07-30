# App-only (client-credential) setup — per-tenant runbook

Status: **prepared, not yet live-verified** (CKM-5). One step is
genuinely interactive — the section-0 bootstrap, where the operator
creates the automation app and assigns its directory role. Everything
after that is scripted (dry-run by default, explicit apply flags) and can
run unattended, including from CI. All addresses/ids below are
placeholders; real values live in local config only.

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

## 0. One-time per tenant: the EXO automation app (unattended PowerShell)

Everything Exchange-side below (and the CI loop at the end) runs through
Exchange Online PowerShell. Rather than a human pasting cmdlets, a
dedicated **automation app registration** lets scripts connect
app-only with a certificate — `Connect-ExchangeOnline -AppId …
-CertificateFilePath … -Organization …` — from any shell or Jenkins.

**Two different apps — never merge them:**

| App | What it is | Credential |
|---|---|---|
| `ckm365-graph` (existing) | The data-plane app the server runs as; RBAC-scoped to allow-listed mailboxes | cert/secret via `CKM365_<PROFILE>_*` |
| `ckm365-exo-automation` (this section) | Admin-plane: runs EXO cmdlets (mailbox create/remove, scopes, role assignments) | cert (PFX) via `CKM365_EXO_*` |

Bootstrap (interactive — creating it, consenting `Exchange.ManageAsApp`,
and assigning the directory role are Privileged-Role-Admin actions and
stay human; this is the ONE manual step):

```sh
az login --tenant tenant-a.example --allow-no-subscriptions
./scripts/create-exo-automation-app.sh --dry-run   # inspect the plan
./scripts/create-exo-automation-app.sh --yes
```

It creates the app + SP, generates a cert/PFX under
`~/.config/ckm365/certs/`, uploads the public cert, admin-consents
`Exchange.ManageAsApp` (grant-verified), assigns the Entra directory role
(default `--role exchange-admin`; see least-privilege note below), and
prints the `CKM365_EXO_*` env block the scripts consume.

**Least privilege:** `--role recipient-admin` (Exchange Recipient
Administrator) is enough for the CI loop (create/remove `tst.*`
mailboxes, permissions) but NOT for management scopes / role assignments
— those need `--role exchange-admin`. For an ongoing Jenkins credential,
consider two apps: a recipient-admin one the CI holds, and the
exchange-admin one used rarely (RBAC changes) and kept out of CI. The
automation credential is admin-grade either way: PFX + password live in
the credential store, rotate yearly (cert is 365-day).

## 1. Exchange RBAC scoping (scripted)

Prereqs: the tenant's existing ckm365 **Graph** app registration
(`scripts/create-app-registration.sh`), and a target mailbox — a `tst.*`
shared mailbox from `scripts/create-test-mailbox.ps1` is ideal for
verification before scoping the real mailbox in.

```sh
# ids of the GRAPH app (the one being scoped, not the automation app):
APP_ID=<graph-app-client-id>          # from profiles.toml
SP_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv)

pwsh ./scripts/setup-app-rbac.ps1 -AppId $APP_ID -SpObjectId $SP_ID \
  -Mailbox tst.apponly@tenant-a.example \
  -DenyMailbox other-user@tenant-a.example          # dry-run: prints the plan
pwsh ./scripts/setup-app-rbac.ps1 ... -Apply        # execute
```

The script is idempotent and runs, in order: `New-ServicePrincipal`
(registers the Graph app's SP with EXO), `New-ManagementScope` (filter
`PrimarySmtpAddress -eq '<mailbox>'` — only the allow-listed mailbox),
`New-ManagementRoleAssignment` for `Application Mail.ReadWrite` +
`Application Calendars.ReadWrite` bounded by that scope, then proves the
result with `Test-ServicePrincipalAuthorization` for both the in-scope
mailbox (expect `InScope True`) and the `-DenyMailbox` (**must** be
`False` — stop if not). `scripts/teardown-app-rbac.ps1` reverses it
(dry-run by default, refuses non-`ckm365-*` names).

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

## CI / Jenkins: scripted setup → test → teardown

With section 0 done once, the whole cycle is unattended. Agent installs
are in **`docs/toolchain.md`** (uv, az, pwsh + ExchangeOnlineManagement —
incl. the exact tarball recipe); credentials/env:

```sh
# from the Jenkins credential store:
export CKM365_EXO_APP_ID=…            # automation app (section 0)
export CKM365_EXO_ORG=tenant-a.onmicrosoft.com
export CKM365_EXO_PFX_PATH=…          # file credential
export CKM365_EXO_PFX_PASSWORD=…      # secret text
export CKM365_TENANT_A_APP_CLIENT_CERT_PATH=…        # graph app key (section 2)
export CKM365_TENANT_A_APP_CLIENT_CERT_THUMBPRINT=…
```

Pipeline shape (each step is dry-run-by-default; CI passes the
apply/`-Yes` flags explicitly):

```sh
pwsh ./scripts/create-test-mailbox.ps1 -Suffix ci-$BUILD_NUMBER \
  -Domain tenant-a.example -Grantee operator@tenant-a.example -Yes
pwsh ./scripts/setup-app-rbac.ps1 -AppId $APP_ID -SpObjectId $SP_ID \
  -Mailbox tst.ci-$BUILD_NUMBER@tenant-a.example \
  -DenyMailbox other-user@tenant-a.example -Apply
CKM365_LIVE_ACCOUNT=tenant-a-app CKM365_LIVE_MAILBOX=tst.ci-$BUILD_NUMBER@tenant-a.example \
  uv run pytest tests/test_live.py -q
pwsh ./scripts/teardown-app-rbac.ps1 -Apply            # always-run cleanup
pwsh ./scripts/remove-test-mailbox.ps1 -Suffix ci-$BUILD_NUMBER \
  -Domain tenant-a.example -Yes
```

Caveats learned elsewhere in this repo: EXO role assignments and consent
can lag a minute before Graph honors them (first call to a cold mailbox
can also 503 — retry); scope filters are evaluated at call time, so
teardown order (RBAC before mailbox) does not matter for safety, only
tidiness.

## Per-tenant repetition

Everything above is per tenant (scope names, mailbox lists, certs, and
consent all differ). Repeat the whole runbook for each profile that needs
app-only mode; never share certificates between tenants.
