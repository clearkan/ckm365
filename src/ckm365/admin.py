"""Admin CLI (CKM-13): tenant setup and diagnosis, dry-run by default.

Division of labour, per the working agreement ("propose commands, seanwy
runs/approves"):

- Exchange Online has no az equivalent, so every ``mailbox`` subcommand
  prints the exact PowerShell (with a one-line why per command) and NEVER
  executes it — review, then paste into a Connect-ExchangeOnline session.
- ``app register`` / ``app add-send-scopes`` wrap the tenant-touching shell
  scripts in ``scripts/``: a step summary by default, executed only with
  ``--run`` plus an explicit y/N confirmation (the script then shows the
  signed-in tenant and asks once more — two gates for tenant writes).
- ``app consent-status`` runs read-only az queries only; ``doctor`` is
  fully local. Neither needs ``--run``.

Addresses in help text are placeholders (user@tenant-a.example style).
"""

import argparse
import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from .auth import DELEGATED_RO, DELEGATED_RW, DELEGATED_SEND, Auth, AuthError
from .config import (ConfigError, load_profiles, profiles_path,
                     resolve_profile, state_dir)

COMMANDS = ("mailbox", "app", "doctor")
# Declared per-tenant consent sets — mirrors scripts/ (base + opt-in send).
BASE_SCOPES = sorted({*DELEGATED_RO, *DELEGATED_RW, "offline_access"})
SEND_SCOPES = sorted(set(DELEGATED_SEND) - set(DELEGATED_RW))
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_ADDR_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SUFFIX_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
_DOMAIN_RE = re.compile(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")
_GUID_RE = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def add_parsers(sub) -> None:
    """Wire the admin command family into server.py's subparsers."""
    mbox = sub.add_parser(
        "mailbox",
        help="print Exchange Online PowerShell for mailbox admin (print-only)",
        description="Prints the exact Exchange Online PowerShell for shared/"
                    "test mailbox administration, with a one-line explanation "
                    "per command. ckm365 NEVER executes these — review them, "
                    "then paste into a Connect-ExchangeOnline session.")
    ms = mbox.add_subparsers(dest="action", required=True)
    for act, verb in (("grant", "grant"), ("revoke", "remove")):
        p = ms.add_parser(
            act, help=f"print the commands to {verb} FullAccess (open/read) "
                      "+ SendAs (send as) on a shared mailbox for --user")
        p.add_argument("shared_mailbox", metavar="shared-mailbox",
                       help="shared mailbox address, e.g. ops@tenant-a.example")
        p.add_argument("--user", required=True, metavar="UPN",
                       help="the user affected, e.g. user@tenant-a.example")
    for act, what in (("create-test", "New-Mailbox -Shared"),
                      ("remove-test", "Remove-Mailbox")):
        p = ms.add_parser(
            act, help=f"print {what} for the disposable test mailbox "
                      "tst.<suffix>@<domain> (test-suite fixture, CKM-9)")
        p.add_argument("suffix",
                       help="short suffix, e.g. 'alpha' -> tst.alpha@<domain>")
        p.add_argument("--domain", help="mail domain; default: derived from "
                       "the profile's default mailbox or signed-in login")
        p.add_argument("--profile", help="profile to derive --domain from "
                       "(optional when only one is configured)")

    app = sub.add_parser(
        "app", help="app registration + consent (dry-run by default)",
        description="Front end for the tenant-touching scripts in scripts/, "
                    "plus read-only consent checks. Nothing executes without "
                    "--run and a y/N confirmation.")
    asub = app.add_subparsers(dest="action", required=True)
    reg = asub.add_parser(
        "register", help="create/reuse the app registration in the signed-in "
                         "az tenant (wraps create-app-registration.sh)")
    reg.add_argument("--name",
                     help="app display name (script default: ckm365-graph)")
    snd = asub.add_parser(
        "add-send-scopes", help="add Mail.Send consent — deliberate per-"
                                "tenant opt-in (wraps add-send-scopes.sh)")
    for p in (reg, snd):
        p.add_argument("--profile", help="profile name passed to the script "
                       "(script default: derived from your az login domain)")
        p.add_argument("--run", action="store_true",
                       help="execute the script (asks y/N); default: dry-run")
    cst = asub.add_parser(
        "consent-status", help="compare granted vs declared scopes — "
                               "read-only az queries, no --run needed")
    cst.add_argument("profile", nargs="?",
                     help="profile name (optional when only one is configured)")

    doc = sub.add_parser(
        "doctor",
        help="local health checks: profiles, caches, logins, consent tier",
        description="Check the local setup only — profiles file, token cache "
                    "presence and permissions, signed-in accounts, and which "
                    "capability tier the cached consent likely supports. "
                    "Never touches a tenant; exits non-zero on any failure.")
    doc.add_argument("profile", nargs="?",
                     help="check one profile (default: all configured)")


def run(args: argparse.Namespace) -> int:
    """Dispatch a parsed admin command; returns the process exit code."""
    if args.command == "mailbox":
        return _mailbox(args)
    if args.command == "app":
        return _app(args)
    return _doctor(args)


# --- mailbox: Exchange Online PowerShell, ALWAYS print-only -----------------

def _pq(s: str) -> str:
    """Single-quote for PowerShell (inputs are validated; belt and braces)."""
    return "'" + s.replace("'", "''") + "'"


def _addr(value: str, what: str) -> str:
    if not _ADDR_RE.fullmatch(value):
        raise SystemExit(f"ckm365: {what} {value!r} does not look like a mail "
                         "address — expected e.g. user@tenant-a.example")
    return value


def _permission_cmds(mb: str, user: str, *, revoke: bool) -> list[tuple[str, str]]:
    """(why, command) pairs: FullAccess for reading, SendAs for sending."""
    act = "Remove" if revoke else "Add"
    fa_why = ("removes the user's FullAccess — they can no longer open/read "
              "the mailbox" if revoke else
              "FullAccess lets the user open/read the mailbox (ckm365 reads "
              "and drafts); -AutoMapping $false stops Outlook auto-attaching it")
    sa_why = ("removes the user's SendAs — they can no longer send as the "
              "mailbox" if revoke else
              "SendAs lets the user send mail as the mailbox (ckm365 send_draft)")
    return [
        (fa_why, f"{act}-MailboxPermission -Identity {_pq(mb)} -User "
                 f"{_pq(user)} -AccessRights FullAccess"
                 + ("" if revoke else " -AutoMapping $false")),
        (sa_why, f"{act}-RecipientPermission -Identity {_pq(mb)} -Trustee "
                 f"{_pq(user)} -AccessRights SendAs"),
    ]


def _test_mailbox_cmds(suffix: str, domain: str, *, remove: bool) -> list[tuple[str, str]]:
    address = f"tst.{suffix}@{domain}"
    if remove:
        return [("permanently deletes the test mailbox and its contents "
                 "(PowerShell asks to confirm)",
                 f"Remove-Mailbox -Identity {_pq(address)}")]
    return [("creates a license-free shared test mailbox — the tst. prefix "
             "marks it disposable (CKM-9)",
             f"New-Mailbox -Shared -Name {_pq('tst.' + suffix)} "
             f"-PrimarySmtpAddress {_pq(address)}")]


def _derive_domain(args: argparse.Namespace) -> str:
    """Mail domain from a profile: default_mailbox first, else the cached
    signed-in login — and if neither exists, say exactly what to pass."""
    try:
        profiles = load_profiles(args.profiles)
    except ConfigError as exc:
        raise SystemExit(f"ckm365: cannot derive the mail domain ({exc}) — "
                         "pass --domain, e.g. --domain tenant-a.example") from exc
    if args.profile is None and len(profiles) > 1:
        raise SystemExit("ckm365: several profiles configured "
                         f"({', '.join(sorted(profiles))}) — pass --profile "
                         "<name> or --domain <mail-domain>")
    p = resolve_profile(profiles, args.profile)
    source = p.default_mailbox or Auth(p).username()
    if not source or "@" not in source:
        raise SystemExit(f"ckm365: profile {p.name!r} has no default_mailbox "
                         "and no cached login to derive a domain from — pass "
                         f"--domain, or run: uv run ckm365 login {p.name}")
    return source.rsplit("@", 1)[1]


def _mailbox(args: argparse.Namespace) -> int:
    if args.action in ("grant", "revoke"):
        pairs = _permission_cmds(_addr(args.shared_mailbox, "shared-mailbox"),
                                 _addr(args.user, "--user"),
                                 revoke=args.action == "revoke")
    else:
        if not _SUFFIX_RE.fullmatch(args.suffix):
            raise SystemExit(f"ckm365: suffix {args.suffix!r} must be short "
                             "lowercase [a-z0-9-], e.g. 'alpha'")
        domain = args.domain or _derive_domain(args)
        if not _DOMAIN_RE.fullmatch(domain):
            raise SystemExit(f"ckm365: {domain!r} does not look like a mail "
                             "domain — expected e.g. tenant-a.example")
        pairs = _test_mailbox_cmds(args.suffix, domain,
                                   remove=args.action == "remove-test")
    print("# Exchange Online PowerShell — ckm365 prints these, you run them."
          "\n# prereq: Connect-ExchangeOnline -UserPrincipalName <admin-upn>")
    for why, cmd in pairs:
        print(f"\n# {why}")
        print(cmd)
    return 0


# --- app: wrap the tenant-touching scripts; read-only consent check ---------

_REGISTER_STEPS = (
    "create (or safely reuse) the public-client app registration",
    "declare the delegated Graph read+write scopes (send NOT included)",
    "grant tenant-wide admin consent, verified against the actual grants",
    "append a matching profile to your profiles.toml (never clobbers one)",
)
_SEND_STEPS = (
    "find the app via the client_id in profiles.toml (never by display name)",
    "re-declare the delegated scopes adding Mail.Send + Mail.Send.Shared",
    "re-grant admin consent, verified to include the send scopes",
)


def _confirm(prompt: str) -> bool:
    """Explicit y/N gate; EOF (non-interactive stdin) counts as no."""
    try:
        return input(f"{prompt} [y/N] ").strip().lower().startswith("y")
    except EOFError:
        return False


def _script(name: str, extra: list[str], steps: tuple[str, ...], *,
            run: bool) -> int:
    """Print-or-run front end for a scripts/ shell script. Never reimplements
    its logic: dry-run summarizes; --run executes the script itself, which
    shows the signed-in tenant and asks once more before touching it."""
    script = _SCRIPTS / name
    if not script.is_file():
        raise SystemExit(f"ckm365: {script} not found — the app subcommands "
                         "need a source checkout of ckm365")
    argv = ["bash", str(script), *extra]
    shown = " ".join(shlex.quote(a) for a in argv)
    print(f"scripts/{name} — TENANT-TOUCHING. It will:")
    for i, step in enumerate(steps, 1):
        print(f"  {i}. {step}")
    print("prereq: az login --tenant <tenant-domain> --allow-no-subscriptions"
          f"\ncommand: {shown}")
    if not run:
        print("DRY RUN — nothing was executed. Add --run to execute "
              "(you will be asked to confirm).")
        return 0
    if not _confirm("Execute this script against the signed-in az tenant?"):
        print("aborted — nothing was executed.")
        return 1
    return subprocess.run(argv, check=False).returncode


def _az(argv: list[str]) -> tuple[int, str]:
    """Run a READ-ONLY az query; returns (exit code, stdout). Write verbs
    never go through here — those live in the scripts, behind --run."""
    proc = subprocess.run(["az", *argv], capture_output=True, text=True,
                          check=False)
    return proc.returncode, proc.stdout.strip()


def _consent_status(args: argparse.Namespace) -> int:
    """Read-only: compare the tenant's actual delegated grants against the
    declared base and send scope sets."""
    p = resolve_profile(load_profiles(args.profiles), args.profile)
    login = f"az login --tenant {p.tenant_id} --allow-no-subscriptions"
    if shutil.which("az") is None:
        print("az CLI not found — install it (https://aka.ms/azure-cli), or "
              "check the app's granted permissions in the Entra portal.")
        return 1
    rc, tenant = _az(["account", "show", "--query", "tenantId", "-o", "tsv"])
    if rc:
        print(f"az has no active login — run: {login}")
        return 1
    if _GUID_RE.fullmatch(p.tenant_id) and tenant.lower() != p.tenant_id.lower():
        print(f"az is signed into a different tenant than profile {p.name!r} "
              f"— run: {login}")
        return 1
    rc, tsv = _az(["ad", "app", "permission", "list-grants", "--id",
                   p.client_id, "--query", "[].scope", "-o", "tsv"])
    if rc:
        print(f"grant query failed for profile {p.name!r} — the app may not "
              "exist in this tenant yet; run "
              f"./scripts/create-app-registration.sh (prereq: {login})")
        return 1
    granted = set(tsv.split())
    missing_base = [s for s in BASE_SCOPES if s not in granted]
    missing_send = [s for s in SEND_SCOPES if s not in granted]
    print(f"profile {p.name!r}: delegated Graph grants vs the declared sets")
    if p.auth != "device_code":
        print("  note: app-only profiles rely on app role assignments, which "
              "this delegated-grant check does not cover")
    if missing_base:
        print(f"  base (read+write): MISSING {', '.join(missing_base)} — run "
              "./scripts/create-app-registration.sh "
              "(or: ckm365 app register --run)")
    else:
        print(f"  base (read+write): OK — all {len(BASE_SCOPES)} scopes granted")
    if missing_send:
        print("  send: not granted — deliberate per-tenant opt-in via "
              "./scripts/add-send-scopes.sh (or: ckm365 app add-send-scopes "
              "--run)")
    else:
        print("  send: OK — usable with: ckm365 serve --write --enable-send")
    return 1 if missing_base else 0


def _app(args: argparse.Namespace) -> int:
    if args.action == "consent-status":
        return _consent_status(args)
    extra: list[str] = []
    if getattr(args, "name", None):
        extra += ["--name", args.name]
    if args.profile:
        extra += ["--profile", args.profile]
    script = ("create-app-registration.sh" if args.action == "register"
              else "add-send-scopes.sh")
    steps = _REGISTER_STEPS if args.action == "register" else _SEND_STEPS
    return _script(script, extra, steps, run=args.run)


# --- doctor: local-only health checks ---------------------------------------

def _cache_tier(cache_path: Path) -> str | None:
    """Which capability tier the cached consent likely supports. Reads only
    the scope lists ('target') from the MSAL cache — never token material."""
    try:
        data = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        return None
    blob = " ".join(str(entry.get("target", ""))
                    for section in ("RefreshToken", "AccessToken")
                    for entry in (data.get(section) or {}).values())
    for tier, marker in (("read + write + send", "Mail.Send"),
                         ("read + write", "Mail.ReadWrite"),
                         ("read only", "Mail.Read")):
        if marker in blob:
            return tier
    return None


def _doctor(args: argparse.Namespace) -> int:
    """Local checks with a next step per failure; 1 if anything failed."""
    failed = 0

    def check(ok: bool, label: str, advice: str = "") -> bool:
        nonlocal failed
        failed += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {label}"
              + (f" — {advice}" if advice and not ok else ""))
        return ok

    path = args.profiles or profiles_path()
    print(f"doctor: profiles file {path}")
    try:
        profiles = load_profiles(args.profiles)
    except ConfigError as exc:
        check(False, "profiles file loads", str(exc))
        return 1
    targets = ([resolve_profile(profiles, args.profile)] if args.profile
               else list(profiles.values()))
    check(True, f"loads ({len(profiles)} profile(s): "
                f"{', '.join(sorted(profiles))})")
    mode = path.stat().st_mode & 0o777
    check(not mode & 0o077, f"file permissions {mode:03o}",
          f"it holds tenant/app ids — run: chmod 600 {path}")
    for p in targets:
        print(f"doctor: profile {p.name!r} ({p.auth})")
        if p.auth == "client_credential":
            try:
                p.client_credential()
                check(True, "app-only credential material present")
            except ConfigError as exc:
                check(False, "app-only credential material", str(exc))
            continue
        cache = state_dir() / f"{p.name}.msal.json"
        if not check(cache.exists(), "token cache present",
                     f"no login yet — run: uv run ckm365 login {p.name}"):
            continue
        cmode = cache.stat().st_mode & 0o777
        check(not cmode & 0o077, f"cache permissions {cmode:03o}",
              f"run: chmod 600 {cache}")
        try:
            user = Auth(p).username()
        except AuthError as exc:  # e.g. multiple cached accounts
            check(False, "one signed-in account", str(exc))
            continue
        if not check(bool(user),
                     f"signed in as {user}" if user else "signed-in account",
                     f"cache has no account — run: uv run ckm365 login {p.name}"):
            continue
        tier = _cache_tier(cache)
        check(tier is not None,
              f"cached consent likely supports: {tier or 'unknown'}",
              f"no scopes readable — run: uv run ckm365 login {p.name}")
    print("doctor: all checks passed" if not failed
          else f"doctor: {failed} check(s) FAILED")
    return 1 if failed else 0
