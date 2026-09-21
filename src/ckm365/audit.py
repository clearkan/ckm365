"""Mailbox access audit (CKM-54): who and what can reach mail, measured with
whatever auth this machine has right now. Read-only everywhere.

Three sections, each run at the widest scope its credentials allow and
otherwise skipped with the steps to enable it:

- ckm365: the profile's own token. Is it signed in, which scopes did it
  actually get, and do live probes (inbox, calendar, calendar sharing)
  succeed? This is the "why is ckm365 not working" section.
- Entra/Azure (az CLI): at user scope, the signed-in user's own roles,
  owned apps, consents and Azure RBAC. With an org role (Global Admin or
  Reader, Security Admin or Reader, Privileged Role Admin), it becomes a
  tenant audit: role holders, PIM availability, every app holding
  application permissions (mail-capable ones flagged), and tenant-wide
  consents. ``--user`` audits named accounts the same way.
- Exchange Online (pwsh with ExchangeOnlineManagement): opt-in via
  ``--exchange`` because it needs an interactive device-code sign-in.
  Checks the target mailbox's delegations. With admin rights, it also
  checks the admin role groups, apps holding Exchange roles, and every
  explicit FullAccess grant in the tenant. Graph cannot see FullAccess
  or SendAs, which is why this section exists at all.

Output is plain text, or Markdown with ``--md`` (stdout or a file). Exit 1
if any RISK finding. Nothing here writes to a tenant; the fixes are printed,
not run.
"""

import argparse
import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .auth import Auth, AuthError, NeedsLogin
from .config import ConfigError, load_profiles, resolve_profile
from .graph import Graph, GraphError

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_APP = "00000003-0000-0000-c000-000000000000"
EXO_APP = "00000002-0000-0ff1-ce00-000000000000"
ORG_ROLES = {"Global Administrator", "Global Reader", "Security Administrator",
             "Security Reader", "Privileged Role Administrator"}
# Directory roles that can grant themselves (or an app) mailbox access.
MAIL_CAPABLE_ROLES = {"Global Administrator", "Exchange Administrator",
                      "Privileged Role Administrator", "Application Administrator",
                      "Cloud Application Administrator"}
# Application permissions that reach mailbox data, or that can mint more.
MAIL_APP_ROLE_PREFIXES = ("Mail.", "MailboxSettings.", "Calendars.", "Contacts.",
                          "full_access_as_app", "Exchange.ManageAsApp",
                          "EWS.", "IMAP.", "POP.", "SMTP.")
ESCALATION_APP_ROLES = {"Application.ReadWrite.All", "AppRoleAssignment.ReadWrite.All",
                        "RoleManagement.ReadWrite.Directory", "Directory.ReadWrite.All"}
MAIL_DELEGATED = ("Mail.", "MailboxSettings.", "Calendars.", "EWS.", "IMAP.",
                  "POP.", "SMTP.", "full_access")


@dataclass
class Section:
    title: str
    scope: str = "skipped"          # "tenant", "user", "profile" or "skipped"
    rows: list[tuple[str, str]] = field(default_factory=list)
    enable: list[str] = field(default_factory=list)   # how to widen/enable

    def add(self, level: str, text: str) -> None:
        self.rows.append((level, text))


def run(args: argparse.Namespace) -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)  # probes, not a log
    sections = [_ckm365(args), _entra(args), _exchange(args)]
    out = render_md(sections) if args.md else render_text(sections)
    if args.md and args.md != "-":
        Path(args.md).write_text(out)
        print(f"audit written to {args.md}")
    else:
        print(out, end="")
    return 1 if any(lvl == "RISK" for s in sections for lvl, _ in s.rows) else 0


def add_parser(sub) -> None:
    p = sub.add_parser(
        "audit", help="read-only mailbox access audit — ckm365 token, Entra "
                      "(az) and Exchange (pwsh), each at the scope you hold",
        description=__doc__.split("\n\n")[0])
    p.add_argument("profile", nargs="?", help="ckm365 profile (optional when "
                   "only one is configured)")
    p.add_argument("--md", nargs="?", const="-", metavar="PATH",
                   help="Markdown output, to PATH or stdout")
    p.add_argument("--user", action="append", default=[], metavar="UPN",
                   help="also audit this account's roles/apps/RBAC (repeatable)")
    p.add_argument("--mailbox", metavar="ADDR",
                   help="mailbox whose delegations to check (default: yours)")
    p.add_argument("--exchange", action="store_true",
                   help="run the Exchange Online section (device-code sign-in)")


# --- rendering ---------------------------------------------------------------

def render_text(sections: list[Section]) -> str:
    lines = []
    for s in sections:
        lines.append(f"== {s.title} [{s.scope}]")
        lines += [f"  {lvl:<4}  {text}" for lvl, text in s.rows]
        lines += [f"  to enable/widen: {e}" for e in s.enable]
        lines.append("")
    lines.append(_summary(sections))
    return "\n".join(lines) + "\n"


def render_md(sections: list[Section]) -> str:
    lines = ["# Mailbox access audit", ""]
    for s in sections:
        lines += [f"## {s.title} ({s.scope})", ""]
        for lvl, text in s.rows:
            head, *tail = text.splitlines()
            lines.append(f"- **{lvl}** {head}")
            lines += [f"  - {t.strip()}" for t in tail]
        if s.enable:
            lines += ["", "To enable or widen this section:", ""]
            lines += [f"- `{e}`" if e.startswith(("az ", "pwsh", "uv ", "ckm365", "Install-"))
                      else f"- {e}" for e in s.enable]
        lines.append("")
    lines.append(f"**{_summary(sections)}**")
    return "\n".join(lines) + "\n"


def _summary(sections: list[Section]) -> str:
    counts = {lvl: sum(1 for s in sections for got, _ in s.rows if got == lvl)
              for lvl in ("RISK", "WARN", "FAIL")}
    return ("summary: " + ", ".join(f"{n} {lvl}" for lvl, n in counts.items())
            + " — scopes: " + ", ".join(f"{s.title}={s.scope}" for s in sections))


# --- section 1: the ckm365 profile's own token --------------------------------

_PROBES = (  # (label, path, params) — each exercises one consented scope.
    # No /me probe: ckm365 never asks for User.Read, so /me is a 403 by design.
    ("mail read (inbox)", "/me/mailFolders/inbox", {"$select": "id"}),
    ("calendar read", "/me/events", {"$top": "1", "$select": "id"}),
)


def _ckm365(args: argparse.Namespace) -> Section:
    s = Section("ckm365 profile")
    try:
        p = resolve_profile(load_profiles(args.profiles), args.profile)
    except ConfigError as exc:
        s.add("SKIP", f"no usable profile: {exc}")
        s.enable.append("create ~/.config/ckm365/profiles.toml — see docs/onboarding.md")
        return s
    s.scope = "profile"
    s.add("INFO", f"profile {p.name!r}, tenant {p.tenant_id}, auth {p.auth}")
    auth = Auth(p)
    try:
        if p.auth == "device_code" and not auth.has_cache():
            raise NeedsLogin(p.name)  # no cache: skip MSAL's network discovery
        auth.token()
    except NeedsLogin:
        s.add("FAIL", "no valid cached login — nothing ckm365 does will work")
        s.enable.append(f"uv run ckm365 login {p.name}")
        return s
    except AuthError as exc:
        s.add("FAIL", str(exc))
        s.enable.append("uv run ckm365 doctor — checks the app-only credential")
        return s
    if p.auth != "device_code":
        s.add("OK", "app-only token acquired; mailbox reach is set by Exchange "
                    "RBAC for Applications (see the Exchange section)")
        return s
    s.add("OK", f"signed in as {auth.username()}")
    graph = Graph(auth)
    try:
        for label, path, params in _PROBES:
            _probe(s, graph, label, path, params)
        try:
            perms = graph.get("/me/calendar/calendarPermissions").get("value", [])
            shared = [f"{(x.get('emailAddress') or {}).get('name', '?')}: {x.get('role')}"
                      for x in perms if x.get("role") not in ("none", "freeBusyRead")]
            s.add("WARN" if shared else "OK",
                  "calendar shared beyond free/busy with: " + "; ".join(shared)
                  if shared else "calendar not shared beyond free/busy")
        except GraphError as exc:
            s.add("INFO", f"calendar sharing not readable ({exc.status} {exc.code})")
    finally:
        graph.close()
    s.add("INFO", "mail FullAccess/SendAs delegation is invisible to Graph — "
                  "see the Exchange section")
    return s


def _probe(s: Section, graph: Graph, label: str, path: str, params: dict) -> None:
    try:
        graph.get(path, params=params)
        s.add("OK", label)
    except GraphError as exc:
        hint = {401: "token rejected — re-run ckm365 login",
                403: "scope not consented — run: ckm365 app consent-status",
                404: "no mailbox for this account (unlicensed?)"}.get(exc.status, "")
        s.add("FAIL", f"{label}: {exc.status} {exc.code}" + (f" — {hint}" if hint else ""))


# --- section 2: Entra ID and Azure via the az CLI -----------------------------

def _az(*argv: str) -> tuple[int, object]:
    """Run a READ-ONLY az command with JSON output; (rc, parsed or stderr)."""
    proc = subprocess.run(["az", *argv, "-o", "json"], capture_output=True,
                          text=True, check=False)
    if proc.returncode:
        return proc.returncode, proc.stderr.strip().splitlines()[-1:] or [""]
    try:
        return 0, json.loads(proc.stdout or "null")
    except ValueError:
        return 1, ["unparseable az output"]


def _err(data: object) -> str:
    """az's last stderr line, as _az returns it on failure."""
    return data[0] if isinstance(data, list) and data else "unknown error"


def _graph_all(url: str) -> list | None:
    """GET a Graph collection through az rest, following nextLink."""
    items: list = []
    while url:
        rc, data = _az("rest", "--url", url)
        if rc or not isinstance(data, dict):
            return None
        items += data.get("value", [])
        url = data.get("@odata.nextLink")
    return items


def _entra(args: argparse.Namespace) -> Section:
    s = Section("Entra ID / Azure (az)")
    if shutil.which("az") is None:
        s.add("SKIP", "az CLI not installed")
        s.enable.append("install the Azure CLI: https://aka.ms/azure-cli")
        return s
    rc, acct = _az("account", "show")
    if rc or not isinstance(acct, dict):
        s.add("SKIP", "az has no active login")
        s.enable.append("az login --tenant <tenant-id> --allow-no-subscriptions")
        return s
    tenant, me_upn = acct.get("tenantId", ""), (acct.get("user") or {}).get("name", "")
    s.add("INFO", f"az signed in as {me_upn} in tenant {tenant}")
    rc, me = _az("rest", "--url", f"{GRAPH}/me?$select=id,userPrincipalName")
    if rc or not isinstance(me, dict):
        s.add("SKIP", f"az login cannot read Microsoft Graph (/me): {_err(me)}")
        s.enable.append("az login --tenant <tenant-id> --allow-no-subscriptions")
        return s
    my_roles = _audit_principal(s, me["id"], me_upn, tenant, self_=True)
    if my_roles is None:
        s.add("FAIL", "could not read your own directory roles, so the scope is "
                      "unknown; tenant checks not attempted")
    org = bool((my_roles or set()) & ORG_ROLES)
    s.scope = "tenant" if org else "user"
    for upn in args.user:
        if not org:
            s.add("SKIP", f"--user {upn}: needs an org-scope role to audit others")
            continue
        rc, u = _az("ad", "user", "show", "--id", upn)
        if rc or not isinstance(u, dict):
            s.add("FAIL", f"--user {upn}: not found")
            continue
        _audit_principal(s, u["id"], upn, tenant, self_=False)
    if org:
        _tenant_sweep(s)
    else:
        s.enable.append("tenant-wide checks need Global Reader (read-only) or "
                        "Global Administrator on the az login")
    return s


def _audit_principal(s: Section, oid: str, upn: str, tenant: str, *,
                     self_: bool) -> set[str] | None:
    """Roles, owned apps, consents and Azure RBAC for one user. Returns the
    role names, or None when they could not be read (reported as FAIL —
    an unreadable list must never print as "none")."""
    who = "you" if self_ else upn
    # Two sources: direct assignments (authoritative, includes roles the
    # legacy view never "activated") and memberOf (catches roles held via a
    # role-assignable group). Either alone has missed real roles.
    direct = _graph_all(f"{GRAPH}/roleManagement/directory/roleAssignments"
                        f"?$filter=principalId eq '{oid}'")
    member_of = _graph_all(f"{GRAPH}/users/{oid}/transitiveMemberOf")
    roles: set[str] | None = None
    if direct is None and member_of is None:
        s.add("FAIL", f"{who}: could not read directory roles")
    else:
        roles = {_role_name({}, a.get("roleDefinitionId", "")) for a in direct or []}
        roles |= {m.get("displayName", "") for m in member_of or []
                  if m.get("@odata.type") == "#microsoft.graph.directoryRole"}
        capable = roles & MAIL_CAPABLE_ROLES
        s.add("RISK" if capable and not self_ else "INFO",
              f"{who}: directory roles: {', '.join(sorted(roles)) or 'none'}"
              + (" — can grant mailbox access" if capable else ""))
    owned = _graph_all(f"{GRAPH}/users/{oid}/ownedObjects")
    if owned is None:
        s.add("FAIL", f"{who}: could not read owned objects")
    apps = [o.get("displayName", "?") for o in owned or []
            if o.get("@odata.type") == "#microsoft.graph.application"]
    if apps:
        s.add("INFO", f"{who}: owns app registration(s): {', '.join(apps)} — "
                      "an owner can add credentials; see app permissions below")
    if self_:
        grants = _graph_all(f"{GRAPH}/users/{oid}/oauth2PermissionGrants")
        if grants is None:
            s.add("FAIL", "you: could not read your consents")
        else:
            mail = [g for g in grants if any(sc.startswith(MAIL_DELEGATED)
                                             for sc in (g.get("scope") or "").split())]
            s.add("INFO", f"you: {len(mail)} personal consent(s) include "
                          "mail/calendar scopes")
    rc, subs = _az("account", "list", "--query", f"[?tenantId=='{tenant}']")
    for sub in subs if rc == 0 and isinstance(subs, list) else []:
        if sub.get("id") == tenant:  # --allow-no-subscriptions placeholder
            continue
        rc, ras = _az("role", "assignment", "list", "--assignee", oid, "--all",
                      "--include-inherited", "--include-groups",
                      "--subscription", sub["id"])
        names = sorted({r.get("roleDefinitionName", "?") for r in ras}) \
            if rc == 0 and isinstance(ras, list) else ["(not readable)"]
        if names:
            s.add("INFO", f"{who}: Azure roles on subscription {sub.get('name')!r}: "
                          f"{', '.join(names)} (Azure RBAC cannot reach Exchange)")
    return roles


def _role_name(names: dict[str, str], role_id: str) -> str:
    """Role display name; hidden built-ins are missing from the list call,
    so fall back to fetching the definition itself."""
    if role_id not in names:
        rc, d = _az("rest", "--url", f"{GRAPH}/roleManagement/directory/"
                                     f"roleDefinitions/{role_id}?$select=displayName")
        names[role_id] = d.get("displayName", role_id) \
            if rc == 0 and isinstance(d, dict) else role_id
    return names[role_id]


def _tenant_sweep(s: Section) -> None:
    rc, skus = _az("rest", "--url", f"{GRAPH}/subscribedSkus")
    plans = {p.get("servicePlanName") for sku in (skus or {}).get("value", [])
             for p in sku.get("servicePlans", [])} if rc == 0 else set()
    s.add("INFO", "PIM available (Entra ID P2) — eligible roles are invisible "
                  "until activated; review them in the portal"
          if "AAD_PREMIUM_P2" in plans else
          "no Entra ID P2: PIM eligibility cannot exist, active roles are the whole story")
    # roleAssignments is authoritative: it includes service principals and
    # roles never "activated" in the legacy /directoryRoles view, and it
    # pages normally (unlike $expand=members, which caps at 20).
    defs = _graph_all(f"{GRAPH}/roleManagement/directory/roleDefinitions"
                      "?$select=id,displayName")
    held = _graph_all(f"{GRAPH}/roleManagement/directory/roleAssignments"
                      "?$expand=principal")
    if defs is None or held is None:
        s.add("FAIL", "could not list directory role assignments")
    names = {d["id"]: d.get("displayName", "?") for d in defs or []}
    by_role: dict[str, list[str]] = {}
    for a in held or []:
        pr = a.get("principal") or {}
        who = pr.get("userPrincipalName") or f"{pr.get('displayName', '?')} (app)"
        by_role.setdefault(_role_name(names, a.get("roleDefinitionId", "")),
                           []).append(who)
    for role, members in sorted(by_role.items()):
        s.add("INFO", f"role {role}: {', '.join(sorted(set(members)))}"
              + (" — can grant mailbox access" if role in MAIL_CAPABLE_ROLES else ""))
    for resource in (GRAPH_APP, EXO_APP):
        _app_permission_holders(s, resource)
    grants = _graph_all(f"{GRAPH}/oauth2PermissionGrants?$filter=consentType eq "
                        "'AllPrincipals'")
    if grants is None:
        s.add("FAIL", "could not list tenant-wide consents")
    for g in grants or []:
        mail = [sc for sc in (g.get("scope") or "").split() if sc.startswith(MAIL_DELEGATED)]
        if mail:
            rc, sp = _az("rest", "--url", f"{GRAPH}/servicePrincipals/{g['clientId']}"
                                          "?$select=displayName")
            name = sp.get("displayName", "?") if rc == 0 and isinstance(sp, dict) else "?"
            s.add("INFO", f"tenant-wide (admin) consent: {name} — delegated "
                          f"{', '.join(mail)} (each user reaches only what they already can)")


def _app_permission_holders(s: Section, resource_app: str) -> None:
    rc, rsp = _az("ad", "sp", "show", "--id", resource_app)
    if rc or not isinstance(rsp, dict):
        return
    role_names = {r["id"]: r.get("value", "?") for r in rsp.get("appRoles", [])}
    held = _graph_all(f"{GRAPH}/servicePrincipals/{rsp['id']}/appRoleAssignedTo")
    if held is None:
        s.add("FAIL", f"could not list application permissions on {rsp.get('displayName')}")
        return
    by_principal: dict[str, list[str]] = {}
    for a in held:
        by_principal.setdefault(a.get("principalDisplayName", "?"), []).append(
            role_names.get(a.get("appRoleId"), "?"))
    if not by_principal:
        s.add("OK", f"no app holds application permissions on {rsp.get('displayName')}")
    for name, perms in sorted(by_principal.items()):
        risky = [p for p in perms if p.startswith(MAIL_APP_ROLE_PREFIXES)
                 or p in ESCALATION_APP_ROLES]
        s.add("RISK" if risky else "INFO",
              f"app {name!r} holds application permissions on "
              f"{rsp.get('displayName')}: {', '.join(sorted(perms))}"
              + (" — unattended reach to every mailbox unless Exchange scopes it"
                 if risky else ""))


# --- section 3: Exchange Online via pwsh --------------------------------------

_EXO_PS = r"""
param($Out, $Mailbox)
$ErrorActionPreference = 'Stop'
Import-Module ExchangeOnlineManagement
Connect-ExchangeOnline -Device -ShowBanner:$false
$res = [ordered]@{ isOrg = $false; errors = @() }
function Try-Get($name, [scriptblock]$sb) {
  try { $res[$name] = @(& $sb) } catch { $res.errors += "${name}: $($_.Exception.Message)" }
}
if (-not $Mailbox) { $Mailbox = (Get-ConnectionInformation)[0].UserPrincipalName }
$res.mailbox = $Mailbox
try { Get-OrganizationConfig | Out-Null; $res.isOrg = $true } catch {}
Try-Get fullAccess { Get-MailboxPermission $Mailbox | ? { $_.User -notlike 'NT AUTHORITY*' -and -not $_.Deny -and $_.User -notlike 'S-1-*' } | % { [string]$_.User } }
Try-Get sendAs { Get-RecipientPermission $Mailbox | ? { $_.Trustee -notlike 'NT AUTHORITY*' } | % { [string]$_.Trustee } }
Try-Get sendOnBehalf { (Get-Mailbox $Mailbox).GrantSendOnBehalfTo | % { [string]$_ } }
foreach ($f in 'Calendar','Inbox') {
  Try-Get "folder$f" { Get-MailboxFolderPermission "${Mailbox}:\$f" | ? { $_.User.DisplayName -notin 'Default','Anonymous' -or ($_.AccessRights -notcontains 'None' -and $_.AccessRights -notcontains 'AvailabilityOnly') } | % { "$($_.User.DisplayName): $($_.AccessRights -join ',')" } }
}
if ($res.isOrg) {
  Try-Get orgMgmt { Get-RoleGroupMember 'Organization Management' | % { [string]$_.Name } }
  Try-Get recipientMgmt { Get-RoleGroupMember 'Recipient Management' | % { [string]$_.Name } }
  Try-Get appRoles { Get-ManagementRoleAssignment | ? { $_.RoleAssigneeType -eq 'ServicePrincipal' } | % { "$($_.RoleAssigneeName): $($_.Role)" } }
  Try-Get fullAccessSweep { Get-Mailbox -ResultSize Unlimited | % { $mb = $_.PrimarySmtpAddress; Get-MailboxPermission $_.Identity -ErrorAction SilentlyContinue | ? { $_.User -notlike 'NT AUTHORITY*' -and $_.User -notlike 'S-1-*' -and -not $_.Deny -and -not $_.IsInherited -and $_.User -notlike '*Discovery Management*' } | % { "$mb <- $($_.User)" } } }
}
Disconnect-ExchangeOnline -Confirm:$false | Out-Null
$res | ConvertTo-Json -Depth 4 | Set-Content -Path $Out -Encoding utf8
"""


def _exchange(args: argparse.Namespace) -> Section:
    s = Section("Exchange Online (pwsh)")
    if shutil.which("pwsh") is None:
        s.add("SKIP", "PowerShell 7 (pwsh) not installed — it runs on Linux too")
        s.enable.append("install pwsh: https://aka.ms/powershell (Linux tarball or package)")
        return s
    rc = subprocess.run(["pwsh", "-NoProfile", "-Command",
                         "if (Get-Module -ListAvailable ExchangeOnlineManagement) "
                         "{ exit 0 } else { exit 1 }"], check=False).returncode
    if rc:
        s.add("SKIP", "ExchangeOnlineManagement module not installed")
        s.enable.append("pwsh -c 'Install-Module ExchangeOnlineManagement -Scope CurrentUser'")
        return s
    if not args.exchange:
        s.add("SKIP", "not requested — needs an interactive device-code sign-in")
        s.enable.append("ckm365 audit --exchange  (prints a code for "
                        "https://microsoft.com/devicelogin)")
        return s
    with tempfile.TemporaryDirectory() as tmp:
        script, out = Path(tmp) / "exo.ps1", Path(tmp) / "exo.json"
        script.write_text(_EXO_PS)
        # stdout/stderr pass through so the device-code prompt reaches the user.
        proc = subprocess.run(["pwsh", "-NoProfile", "-File", str(script),
                               "-Out", str(out), "-Mailbox", args.mailbox or ""],
                              check=False)
        if proc.returncode or not out.exists():
            s.add("FAIL", "Exchange sign-in or query failed (see pwsh output above)")
            return s
        data = json.loads(out.read_text(encoding="utf-8-sig"))
    exchange_findings(s, data)
    return s


def exchange_findings(s: Section, data: dict) -> None:
    """Turn the pwsh JSON into findings (split out for offline tests)."""
    s.scope = "tenant" if data.get("isOrg") else "user"
    mb = data.get("mailbox", "?")
    for key, label in (("fullAccess", "FullAccess"), ("sendAs", "SendAs"),
                       ("sendOnBehalf", "SendOnBehalf")):
        if key not in data:
            continue
        others = [u for u in data[key] or [] if u.lower() != mb.lower()]
        s.add("WARN" if others else "OK",
              f"{mb}: {label} " + (f"held by {', '.join(others)}" if others else "— nobody else"))
    for f in ("Calendar", "Inbox"):
        if f"folder{f}" in data:
            shared = data[f"folder{f}"] or []
            s.add("WARN" if shared else "OK",
                  f"{mb}: {f} folder " + (f"shared: {'; '.join(shared)}" if shared
                                          else "not shared beyond defaults"))
    if data.get("isOrg"):
        s.add("INFO", "Organization Management: "
                      + (", ".join(data.get("orgMgmt") or []) or "empty"))
        s.add("INFO", "Recipient Management: "
                      + (", ".join(data.get("recipientMgmt") or []) or "empty"))
        if "appRoles" not in data:
            s.add("FAIL", "could not list apps holding Exchange roles")
        else:
            app_roles = data["appRoles"] or []
            s.add("RISK" if app_roles else "OK",
                  "apps holding Exchange roles: " + ("; ".join(app_roles) or "none"))
        if "fullAccessSweep" not in data:
            s.add("FAIL", "could not sweep FullAccess grants")
        else:
            sweep = data["fullAccessSweep"] or []
            s.add("INFO", f"explicit FullAccess grants tenant-wide ({len(sweep)}):"
                          + "".join(f"\n        {x}" for x in sweep))
    else:
        s.enable.append("tenant-wide Exchange checks need Exchange Administrator "
                        "or Global Administrator/Reader on the pwsh sign-in")
    for err in data.get("errors") or []:
        s.add("INFO", f"check failed (permission, folder name or transient): {err[:160]}")
