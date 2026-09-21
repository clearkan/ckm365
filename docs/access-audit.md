# Access audit — who can reach a mailbox, and why ckm365 isn't working

`ckm365 audit` is read-only. It measures mailbox access with whatever
credentials this machine has right now. Each section runs at the widest
scope those credentials allow. When a section can't run, it prints the
exact step that would enable it. It never changes a tenant; any fixes it
suggests are for you to run.

```bash
uv run ckm365 audit [profile]                  # text to the terminal
uv run ckm365 audit [profile] --md             # Markdown to stdout
uv run ckm365 audit [profile] --md audit.md    # Markdown to a file
uv run ckm365 audit [profile] --exchange       # add the Exchange section
uv run ckm365 audit [profile] --user someone@tenant-a.example   # audit an account
uv run ckm365 audit [profile] --exchange --mailbox shared@tenant-a.example
```

`-v`/`--verbose` logs each step to stderr, including every az call and
each Exchange query. The Exchange FullAccess sweep makes one call per
mailbox, so it can take minutes on a large tenant. Verbose output shows
it's still working.

**Audit output names real accounts.** Write `--md` files outside any public
repo; in this repo, `/audit*.md` is git-ignored and `tmp/` is the place.

Exit code 1 means at least one **RISK** finding. The levels are:

| Level | Meaning |
|---|---|
| RISK | Standing access to mailboxes that isn't tied to a person (an app with mail-capable application permissions or Exchange roles), or an account named with `--user` that holds a role which can grant mailbox access. The tenant sweep lists all role holders as INFO, since Global Admins always exist |
| WARN | Something is delegated or shared. It may be intended, so confirm it is |
| FAIL | A check that should work didn't, or a list couldn't be read. An unreadable list is never shown as "none". It's also the "why isn't ckm365 working" signal |
| OK / INFO | Clean, or context |
| SKIP | Section not run, with the steps to enable it |

## What it checks, by scope

| Section | Needs | User scope (anyone) | Tenant scope |
|---|---|---|---|
| **ckm365 profile** | a profile and `ckm365 login` | token valid; live probes of inbox, calendar and calendar sharing | — |
| **Entra / Azure** | `az login` into the tenant | your directory roles, apps you own, your consents, your Azure RBAC | needs Global Admin/Reader, Security Admin/Reader or Privileged Role Admin. Adds: role holders, PIM availability, **every app holding Graph or Exchange application permissions**, tenant-wide consents, and `--user` accounts |
| **Exchange Online** | `pwsh` with the ExchangeOnlineManagement module, plus `--exchange` | FullAccess, SendAs, SendOnBehalf and Calendar/Inbox folder sharing on the target mailbox, as far as the account is permitted | needs Exchange Admin or Global Admin/Reader. Adds: admin role groups, apps holding Exchange roles, and every explicit FullAccess grant in the tenant |

A user with no admin role gets a personal audit: is my ckm365 working,
what have I consented to, who is my calendar shared with. An admin gets
the tenant audit from the same command.

### Why three sources

The answer to "who can read this mailbox" lives in three places. No
single API sees all of them:

- **Entra** decides which *apps* hold permissions and which *people* hold
  admin roles. An app with application permissions such as `Mail.Read`
  reaches every mailbox with nobody signed in, so it's the biggest
  finding the audit can make.
- **Exchange** holds mailbox delegation: FullAccess, SendAs and folder
  permissions. Graph can't see these at all, so a clean Entra audit does
  not mean the mailbox is private.
- **Azure RBAC** (subscription Owner or Contributor) has no path to Exchange
  or Entra. The audit shows it anyway, because "has high Azure
  permissions" is the usual reason someone asks.

Delegated consents, including ckm365's own tenant-wide consent, never
widen reach. A delegated token only gets what its signed-in user can
already reach.

## Enabling each section

**ckm365 profile**: `uv run ckm365 login <profile>`. See `docs/onboarding.md`.

**Entra / Azure**: install the Azure CLI (https://aka.ms/azure-cli), then:

```bash
az login --tenant <tenant-id> --allow-no-subscriptions --use-device-code
```

Use `--allow-no-subscriptions` when you only need Entra; drop it to also
see Azure RBAC per subscription. For the tenant audit, sign in with an
account holding **Global Reader**, which is read-only and enough.

**Exchange Online**: this works on Linux. It needs PowerShell 7 and the
Exchange module. Neither needs root:

```bash
# pwsh: https://aka.ms/powershell (distro package, or the tarball into /opt)
pwsh -c 'Install-Module ExchangeOnlineManagement -Scope CurrentUser'
uv run ckm365 audit --exchange
```

The browser-based sign-in doesn't work on a headless box, so the audit
uses **device code**. It prints a code for
https://microsoft.com/devicelogin. Enter it in any browser, ideally a
private window so the right account signs in. The session ends when the
audit does.

## Troubleshooting ckm365 with the audit

| Finding | Cause | Fix |
|---|---|---|
| `FAIL no valid cached login` | never logged in, the refresh token expired (~90 days unused), or a password reset or revocation | `uv run ckm365 login <profile>` |
| `FAIL mail read (inbox): 403` | scope not consented in this tenant | `uv run ckm365 app consent-status <profile>`, then `scripts/create-app-registration.sh` (admin) |
| `FAIL …: 404` | the account has no mailbox (unlicensed, or a guest) | license the account, or use a member account |
| `FAIL …: 401` | token rejected: wrong tenant, or the app was deleted | check the profile's `tenant_id`/`client_id` against the tenant; `az ad app show --id <client_id>` |
| Shared mailbox: `ErrorAccessDenied` | no Exchange delegation on that mailbox | the audit's Exchange section shows who has FullAccess; an Exchange admin adds it (`ckm365 mailbox grant …` prints the command) |
| `SKIP az has no active login` | az signed out, or signed into another tenant | `az login --tenant <tenant-id> …` |

## Manual equivalents

These are the commands the audit runs, for checking by hand or on a
machine without ckm365.

```bash
OID=$(az ad user show --id <upn> --query id -o tsv)
az rest --url "https://graph.microsoft.com/v1.0/users/$OID/transitiveMemberOf"      # roles and groups
az rest --url "https://graph.microsoft.com/v1.0/users/$OID/ownedObjects"            # owned apps
az role assignment list --assignee $OID --all -o table                             # Azure RBAC
GSP=$(az ad sp show --id 00000003-0000-0000-c000-000000000000 --query id -o tsv)
az rest --url "https://graph.microsoft.com/v1.0/servicePrincipals/$GSP/appRoleAssignedTo"  # apps with Graph app permissions
```

```powershell
Connect-ExchangeOnline -Device
Get-MailboxPermission <mailbox> | ? { $_.User -notlike 'NT AUTHORITY*' }   # FullAccess
Get-RecipientPermission <mailbox>                                          # SendAs
Get-MailboxFolderPermission "<mailbox>:\Calendar"
Get-RoleGroupMember "Organization Management"
Get-ManagementRoleAssignment | ? { $_.RoleAssigneeType -eq 'ServicePrincipal' }
```

## Limits

- **PIM**: in a tenant with Entra ID P2, *eligible* roles don't show as
  active. az's built-in Graph token can't read eligibility, so the audit
  says when PIM is possible and points at the portal.
- **Sign-in and audit logs** aren't read: they need `AuditLog.Read.All`,
  which az's built-in token doesn't carry. Directory audit retention is
  about 30 days without extra licensing.
- **App credentials**: the audit reports which apps hold permissions, not
  whether their secrets are current. An expired secret makes an app
  dormant, not harmless: anyone who can add a credential can revive it.
