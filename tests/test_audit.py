"""Access audit tests (CKM-54) — offline only: no az, no pwsh, no network.

The section runners are exercised with az/pwsh reported missing, and the
finding logic through its pure helpers. Placeholder identities only."""

import pytest

from ckm365 import audit
from ckm365.server import main

TENANT_A = "00000000-0000-0000-0000-00000000000a"


@pytest.fixture(autouse=True)
def no_processes(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError(f"tried to spawn a process: {args}")
    monkeypatch.setattr(audit.subprocess, "run", boom)


@pytest.fixture
def profiles_file(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(f'[profiles.tenant-a]\ntenant_id = "{TENANT_A}"\n'
                    'client_id = "app-a"\n')
    path.chmod(0o600)
    return path


def cli(*argv):
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    return exc.value.code


def test_no_tools_no_login_skips_with_enable_steps(profiles_file, tmp_path,
                                                   monkeypatch, capsys):
    monkeypatch.setattr(audit.shutil, "which", lambda _: None)
    monkeypatch.setattr("ckm365.auth.state_dir", lambda: tmp_path)
    assert cli("--profiles", str(profiles_file), "audit", "-v") == 0
    captured = capsys.readouterr()
    out = captured.out
    assert "audit: section: Exchange Online (pwsh)" in captured.err
    assert "FAIL  no valid cached login" in out
    assert "to enable/widen: uv run ckm365 login tenant-a" in out
    assert "SKIP  az CLI not installed" in out
    assert "SKIP  PowerShell 7 (pwsh) not installed" in out
    assert "Entra ID / Azure (az)=skipped" in out


def test_markdown_to_file(profiles_file, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(audit.shutil, "which", lambda _: None)
    monkeypatch.setattr("ckm365.auth.state_dir", lambda: tmp_path)
    dest = tmp_path / "audit.md"
    assert cli("--profiles", str(profiles_file), "audit", "--md", str(dest)) == 0
    md = dest.read_text()
    assert md.startswith("# Mailbox access audit")
    assert "## Exchange Online (pwsh) (skipped)" in md
    assert "- `uv run ckm365 login tenant-a`" in md


def test_exchange_findings_tenant_scope():
    s = audit.Section("x")
    audit.exchange_findings(s, {
        "isOrg": True, "mailbox": "me@tenant-a.example",
        "fullAccess": ["me@tenant-a.example", "other@tenant-a.example"],
        "sendAs": [], "folderCalendar": [], "orgMgmt": ["TenantAdmins"],
        "recipientMgmt": [], "appRoles": ["some-app: ApplicationImpersonation"],
        "fullAccessSweep": ["shared@tenant-a.example <- other@tenant-a.example"]})
    assert s.scope == "tenant"
    assert ("WARN", "me@tenant-a.example: FullAccess held by other@tenant-a.example") in s.rows
    assert ("OK", "me@tenant-a.example: SendAs — nobody else") in s.rows
    assert any(lvl == "RISK" and "apps holding Exchange roles" in t for lvl, t in s.rows)
    assert audit.render_text([s]).count("RISK") >= 1


def test_exchange_findings_user_scope_adds_enable_hint():
    s = audit.Section("x")
    audit.exchange_findings(s, {"isOrg": False, "mailbox": "me@tenant-a.example",
                                "errors": ["fullAccess: not permitted"]})
    assert s.scope == "user"
    assert any("Exchange Administrator" in e for e in s.enable)
    assert ("INFO", "check failed (permission, folder name or transient): "
            "fullAccess: not permitted") in s.rows


def test_app_permission_classification(monkeypatch):
    graph_sp = {"id": "sp-graph", "displayName": "Microsoft Graph",
                "appRoles": [{"id": "r1", "value": "Mail.Read"},
                             {"id": "r2", "value": "User.Read.All"}]}
    monkeypatch.setattr(audit, "_az", lambda *a: (0, graph_sp))
    monkeypatch.setattr(audit, "_graph_all", lambda url: [
        {"principalDisplayName": "mailer", "appRoleId": "r1"},
        {"principalDisplayName": "directory-sync", "appRoleId": "r2"}])
    s = audit.Section("x")
    audit._app_permission_holders(s, audit.GRAPH_APP)
    levels = {t.split("'")[1]: lvl for lvl, t in s.rows}
    assert levels == {"directory-sync": "INFO", "mailer": "RISK"}


def test_unreadable_lists_are_fail_not_none(monkeypatch):
    """A failed read must never print as 'none' — the false-clean an audit
    tool must not have — and must not silently downgrade the scope."""
    monkeypatch.setattr(audit, "_graph_all", lambda url: None)
    monkeypatch.setattr(audit, "_az", lambda *a: (1, ["forbidden"]))
    s = audit.Section("x")
    assert audit._audit_principal(s, "oid", "u@tenant-a.example", TENANT_A,
                                  self_=False) is None
    texts = [t for lvl, t in s.rows if lvl == "FAIL"]
    assert any("could not read directory roles" in t for t in texts)
    assert not any("none" in t for _, t in s.rows)


def test_markdown_multiline_row_nests():
    s = audit.Section("x")
    s.add("INFO", "grants (2):\n        a <- b\n        c <- d")
    md = audit.render_md([s])
    assert "- **INFO** grants (2):\n  - a <- b\n  - c <- d" in md
