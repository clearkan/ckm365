# Toolchain requirements — dev box and CI agent

Everything a machine needs to develop ckm365 or run its tenant-automation
scripts. **Keep this current**: any script that grows a new dependency
updates this file in the same commit.

| Tool | Needed for | Install |
|---|---|---|
| Python ≥3.11 + `uv` | the package, offline + live tests | distro python; uv standalone installer |
| `az` CLI | Entra-side scripts (app registrations, consent, directory roles) | `sudo dnf install azure-cli` (or MS docs) |
| PowerShell ≥7.4 (`pwsh`) | all Exchange-side scripts (`exo-common.ps1` consumers: mailboxes, RBAC) | official tarball → `/opt` (below) |
| `ExchangeOnlineManagement` ≥3.x | same | `pwsh -c 'Install-Module ExchangeOnlineManagement -Scope CurrentUser -Force'` |
| `openssl` | cert generation for both app credentials | any distro |

## pwsh install (the recipe we use)

The self-contained tarball avoids two traps: `dotnet tool install
--global powershell` requires a full **.NET SDK** (a runtime is not
enough — fails with "No .NET SDKs were found"), and Microsoft's RHEL RPM
repo is hit-and-miss on Fedora.

```sh
V=7.6.4   # or latest from github.com/PowerShell/PowerShell/releases
curl -sL -o /tmp/pwsh.tar.gz \
  "https://github.com/PowerShell/PowerShell/releases/download/v${V}/powershell-${V}-linux-x64.tar.gz"
sudo mkdir -p /opt/microsoft/powershell/7
sudo tar zxf /tmp/pwsh.tar.gz -C /opt/microsoft/powershell/7
sudo chmod +x /opt/microsoft/powershell/7/pwsh
sudo ln -sf /opt/microsoft/powershell/7/pwsh /usr/local/bin/pwsh
pwsh --version
pwsh -c 'Install-Module ExchangeOnlineManagement -Scope CurrentUser -Force'
```

## CI agent (Jenkins)

Same list. Credentials the agent holds (never in the repo):

- `CKM365_EXO_APP_ID` / `CKM365_EXO_ORG` (plain env), `CKM365_EXO_PFX_PATH`
  (file credential), `CKM365_EXO_PFX_PASSWORD` (secret text) — the EXO
  automation app from `scripts/create-exo-automation-app.sh`
- `CKM365_<PROFILE>_CLIENT_CERT_PATH` + `_CLIENT_CERT_THUMBPRINT` — the
  Graph app's app-only credential
- `CKM365_LIVE_ACCOUNT` / `CKM365_LIVE_MAILBOX` — live-suite targeting

Pipeline recipe: `docs/app-only-setup.md` → "CI / Jenkins".

## Why PowerShell at all — is there no direct REST API?

Asked and answered deliberately: the Entra-side operations already ARE
direct API calls (`az` / `az rest` → Microsoft Graph). But the
Exchange-side operations — shared-mailbox create/remove, management
scopes, RBAC-for-Applications role assignments,
`Test-ServicePrincipalAuthorization` — have **no public Graph API**. The
v3 `ExchangeOnlineManagement` module is itself a REST client (no WinRM),
but the AdminApi endpoint it calls is undocumented and unsupported for
direct use; scripting the supported module from `pwsh` IS Microsoft's
sanctioned automation path for Exchange admin. Revisit if Graph ever
grows admin endpoints for these.
