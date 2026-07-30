"""Admin CLI tests (CKM-13) — offline only: no az, no network, no scripts.

Everything goes through server.main() so the argparse wiring is covered too.
An autouse guard makes any attempt to spawn a real process fail the test.
All addresses are placeholders (user@tenant-a.example style)."""

import json

import pytest

from ckm365 import admin
from ckm365.server import main

TENANT_A = "00000000-0000-0000-0000-00000000000a"


@pytest.fixture(autouse=True)
def no_processes(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError(f"tried to spawn a process: {args}")
    monkeypatch.setattr(admin.subprocess, "run", boom)


@pytest.fixture
def profiles_file(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        f'[profiles.tenant-a]\ntenant_id = "{TENANT_A}"\n'
        'client_id = "app-a"\ndefault_mailbox = "ops@tenant-a.example"\n')
    path.chmod(0o600)
    return path


def cli(*argv):
    """Run the CLI; returns the SystemExit code (int, or the error string)."""
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    return exc.value.code


# --- mailbox grant / revoke (always print-only) -----------------------------

def test_grant_prints_fullaccess_and_sendas(capsys):
    assert cli("mailbox", "grant", "ops@tenant-a.example",
               "--user", "user@tenant-a.example") == 0
    out = capsys.readouterr().out
    assert ("Add-MailboxPermission -Identity 'ops@tenant-a.example' "
            "-User 'user@tenant-a.example' -AccessRights FullAccess "
            "-AutoMapping $false") in out
    assert ("Add-RecipientPermission -Identity 'ops@tenant-a.example' "
            "-Trustee 'user@tenant-a.example' -AccessRights SendAs") in out
    assert "Connect-ExchangeOnline" in out  # prereq stated
    assert "you run them" in out  # print-only stance stated


def test_revoke_prints_remove_variants(capsys):
    assert cli("mailbox", "revoke", "ops@tenant-a.example",
               "--user", "user@tenant-a.example") == 0
    out = capsys.readouterr().out
    assert "Remove-MailboxPermission" in out and "FullAccess" in out
    assert "Remove-RecipientPermission" in out and "SendAs" in out
    assert "AutoMapping" not in out


def test_grant_rejects_non_address():
    code = cli("mailbox", "grant", "not-an-address",
               "--user", "user@tenant-a.example")
    assert "does not look like a mail address" in str(code)


def test_grant_requires_user_flag():
    assert cli("mailbox", "grant", "ops@tenant-a.example") == 2  # argparse


# --- mailbox create-test / remove-test --------------------------------------

def test_create_test_with_explicit_domain(capsys):
    assert cli("mailbox", "create-test", "alpha",
               "--domain", "tenant-a.example") == 0
    assert ("New-Mailbox -Shared -Name 'tst.alpha' "
            "-PrimarySmtpAddress 'tst.alpha@tenant-a.example'"
            ) in capsys.readouterr().out


def test_create_test_derives_domain_from_profile(profiles_file, capsys):
    assert cli("--profiles", str(profiles_file),
               "mailbox", "create-test", "alpha") == 0
    assert "'tst.alpha@tenant-a.example'" in capsys.readouterr().out


def test_remove_test(capsys):
    assert cli("mailbox", "remove-test", "alpha",
               "--domain", "tenant-a.example") == 0
    out = capsys.readouterr().out
    assert "Remove-Mailbox -Identity 'tst.alpha@tenant-a.example'" in out


def test_create_test_rejects_bad_suffix():
    code = cli("mailbox", "create-test", "Bad_Suffix!",
               "--domain", "tenant-a.example")
    assert "suffix" in str(code)


def test_create_test_needs_profile_or_domain(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text('[profiles.a]\ntenant_id = "t1"\nclient_id = "c1"\n'
                    '[profiles.b]\ntenant_id = "t2"\nclient_id = "c2"\n')
    code = cli("--profiles", str(path), "mailbox", "create-test", "alpha")
    assert "--profile" in str(code) and "--domain" in str(code)


# --- app register / add-send-scopes (dry-run by default) --------------------

def test_app_register_dry_run(capsys):
    assert cli("app", "register", "--name", "My App") == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "create-app-registration.sh" in out
    assert "az login --tenant" in out  # prerequisite stated
    assert "'My App'" in out  # exact command shown, shell-quoted


def test_app_register_run_aborts_without_yes(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert cli("app", "register", "--run") == 1
    assert "aborted" in capsys.readouterr().out  # and no_processes proves it


def test_app_add_send_scopes_dry_run(capsys):
    assert cli("app", "add-send-scopes") == 0
    out = capsys.readouterr().out
    assert "add-send-scopes.sh" in out and "DRY RUN" in out
    assert "Mail.Send" in out  # says what the deliberate opt-in adds


# --- app consent-status (read-only az) --------------------------------------

def test_consent_status_without_az(profiles_file, monkeypatch, capsys):
    monkeypatch.setattr(admin.shutil, "which", lambda _: None)
    assert cli("--profiles", str(profiles_file), "app", "consent-status") == 1
    assert "az CLI not found" in capsys.readouterr().out


def test_consent_status_base_ok_send_missing(profiles_file, monkeypatch, capsys):
    monkeypatch.setattr(admin.shutil, "which", lambda _: "/usr/bin/az")
    calls = []

    def fake_az(argv):
        calls.append(argv)
        if argv[:2] == ["account", "show"]:
            return 0, TENANT_A
        return 0, " ".join(admin.BASE_SCOPES)

    monkeypatch.setattr(admin, "_az", fake_az)
    assert cli("--profiles", str(profiles_file), "app", "consent-status") == 0
    out = capsys.readouterr().out
    assert "base (read+write): OK" in out
    assert "add-send-scopes" in out  # next step for the missing send tier
    assert calls[1][:4] == ["ad", "app", "permission", "list-grants"]
    assert "app-a" in calls[1]  # queried by the profile's client_id


def test_consent_status_missing_base_scopes(profiles_file, monkeypatch, capsys):
    monkeypatch.setattr(admin.shutil, "which", lambda _: "/usr/bin/az")
    monkeypatch.setattr(admin, "_az", lambda argv: (
        (0, TENANT_A) if argv[:2] == ["account", "show"] else (0, "Mail.Read")))
    assert cli("--profiles", str(profiles_file), "app", "consent-status") == 1
    out = capsys.readouterr().out
    assert "MISSING" in out and "create-app-registration.sh" in out


def test_consent_status_wrong_tenant(profiles_file, monkeypatch, capsys):
    monkeypatch.setattr(admin.shutil, "which", lambda _: "/usr/bin/az")
    monkeypatch.setattr(
        admin, "_az", lambda argv: (0, "11111111-1111-1111-1111-111111111111"))
    assert cli("--profiles", str(profiles_file), "app", "consent-status") == 1
    out = capsys.readouterr().out
    assert "different tenant" in out
    assert f"az login --tenant {TENANT_A}" in out


# --- doctor (fully local) ----------------------------------------------------

class StubAuth:
    def __init__(self, profile, **kwargs):
        self.profile = profile

    def username(self):
        return "user@tenant-a.example"


@pytest.fixture
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    cache_dir = tmp_path / "state" / "ckm365"
    cache_dir.mkdir(parents=True)
    return cache_dir


def _write_cache(cache_dir, name, scopes):
    """Fabricated MSAL cache: scope names only — never token material."""
    cache = cache_dir / f"{name}.msal.json"
    cache.write_text(json.dumps({"RefreshToken": {"k": {"target": scopes}}}))
    cache.chmod(0o600)
    return cache


def test_doctor_all_green(profiles_file, state_home, monkeypatch, capsys):
    monkeypatch.setattr(admin, "Auth", StubAuth)
    _write_cache(state_home, "tenant-a",
                 "Mail.Read Mail.ReadWrite Mail.Send Calendars.ReadWrite")
    assert cli("--profiles", str(profiles_file), "doctor") == 0
    out = capsys.readouterr().out
    assert "signed in as user@tenant-a.example" in out
    assert "read + write + send" in out
    assert "all checks passed" in out


def test_doctor_missing_cache_fails_with_advice(profiles_file, state_home, capsys):
    assert cli("--profiles", str(profiles_file), "doctor") == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "ckm365 login tenant-a" in out


def test_doctor_flags_loose_profiles_perms(profiles_file, state_home,
                                           monkeypatch, capsys):
    monkeypatch.setattr(admin, "Auth", StubAuth)
    _write_cache(state_home, "tenant-a", "Mail.ReadWrite")
    profiles_file.chmod(0o644)
    assert cli("--profiles", str(profiles_file), "doctor") == 1
    assert f"chmod 600 {profiles_file}" in capsys.readouterr().out


def test_doctor_reports_write_tier_from_uri_scopes(profiles_file, state_home,
                                                   monkeypatch, capsys):
    monkeypatch.setattr(admin, "Auth", StubAuth)
    _write_cache(state_home, "tenant-a",
                 "https://graph.microsoft.com/Mail.ReadWrite")  # full-URI form
    assert cli("--profiles", str(profiles_file), "doctor") == 0
    out = capsys.readouterr().out
    assert "read + write" in out and "read + write + send" not in out


def test_doctor_unknown_profile_lists_configured(profiles_file, state_home):
    code = cli("--profiles", str(profiles_file), "doctor", "nope")
    assert "unknown account" in str(code) and "tenant-a" in str(code)
