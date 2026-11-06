"""Offline spec for `ckm365 doctor --mcp` (ba1m7k item 3, plus kw20z6
gap 1): look at the Claude Code MCP registration, the environment the
server actually runs in.

Two silent failures this catches:
- An app-only (`client_credential`) profile whose credential env vars are
  set in the operator's shell but NOT declared on the registration's
  `env` block: doctor passes in the terminal while `ckm365 serve` has no
  credential. The check is heuristic (the server also inherits whatever
  environment Claude Code was launched with), so the finding is phrased
  "not declared on the registration" and is a WARNING, not a failure.
- A preset that exists but is not on the serve line. Twice an agent
  needed meeting transcripts and found tools/meetings.py only by reading
  the repo. Doctor prints which presets are NOT enabled.

Where registrations live: `~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`),
at the top level `mcpServers.ckm365` and under `projects.<dir>.mcpServers.ckm365`,
plus `./.mcp.json` in the current directory. No registration at all is a
warning: programmatic consumers legitimately have none.

Doctor reads names only. It never prints env VALUES (a secret may sit
there), and never prints the registration's paths or the project
directories it found them under, only "user", "project" or ".mcp.json".

Without `--mcp`, doctor behaves exactly as before.

Skipped as a module until doctor accepts --mcp.
"""

import json

import pytest

from ckm365 import admin
from ckm365.server import main

if not hasattr(admin, "mcp_registrations"):
    pytest.skip("doctor --mcp not built yet (ba1m7k)", allow_module_level=True)

TENANT_A = "00000000-0000-0000-0000-00000000000a"
CERT = "CKM365_APP_A_CLIENT_CERT_PATH"
THUMB = "CKM365_APP_A_CLIENT_CERT_THUMBPRINT"
SECRET = "CKM365_APP_A_CLIENT_SECRET"


@pytest.fixture(autouse=True)
def no_processes(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError(f"tried to spawn a process: {args}")
    monkeypatch.setattr(admin.subprocess, "run", boom)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake HOME and cwd, so the real ~/.claude.json is never read."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    # the app profile's credential is in the SHELL, which is the trap
    monkeypatch.setenv(SECRET, "shell-only-secret-value")
    return h


@pytest.fixture
def profiles_file(tmp_path):
    """One app-only profile only, so the device-code cache checks stay out
    of the way."""
    path = tmp_path / "profiles.toml"
    path.write_text(
        f'[profiles.app-a]\ntenant_id = "{TENANT_A}"\nclient_id = "app-a"\n'
        'auth = "client_credential"\ndefault_mailbox = "ops@tenant-a.example"\n')
    path.chmod(0o600)
    return path


def entry(preset="mail,calendar", env=None, write=True):
    args = ["run", "--directory", "/srv/checkout/ckm365", "ckm365", "serve",
            "--preset", preset] + (["--write"] if write else [])
    return {"type": "stdio", "command": "uv", "args": args, "env": env or {}}


def write_claude(home, servers=None, projects=None):
    data = {"mcpServers": servers or {}}
    if projects:
        data["projects"] = {d: {"mcpServers": s} for d, s in projects.items()}
    (home / ".claude.json").write_text(json.dumps(data))


def doctor(profiles_file, *extra):
    with pytest.raises(SystemExit) as exc:
        main(["--profiles", str(profiles_file), "doctor", *extra])
    return exc.value.code


# --- finding registrations ----------------------------------------------------

def test_finds_user_project_and_dot_mcp_registrations(home):
    write_claude(home, servers={"ckm365": entry(), "other": entry()},
                 projects={"/srv/a": {"ckm365": entry("mail")},
                           "/srv/b": {"unrelated": entry()}})
    (home.parent / "work" / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"ckm365": entry("calendar")}}))
    found = admin.mcp_registrations()
    assert [where for where, _ in found] == ["user", "project", ".mcp.json"]
    assert found[1][1]["args"][-2] == "mail"


def test_claude_config_dir_is_honoured(home, tmp_path, monkeypatch):
    alt = tmp_path / "alt"
    alt.mkdir()
    (alt / ".claude.json").write_text(json.dumps(
        {"mcpServers": {"ckm365": entry()}}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(alt))
    assert [w for w, _ in admin.mcp_registrations()] == ["user"]


def test_unreadable_config_is_no_registration_not_a_crash(home):
    (home / ".claude.json").write_text("{not json")
    assert admin.mcp_registrations() == []


# --- the doctor output ----------------------------------------------------------

def test_credential_not_declared_on_registration_warns(home, profiles_file, capsys):
    write_claude(home, servers={"ckm365": entry()})
    assert doctor(profiles_file, "--mcp") == 0          # a warning, not a failure
    out = capsys.readouterr().out
    assert "warn" in out and "not declared on the registration" in out
    assert SECRET in out                     # names the variable to add
    assert "shell-only-secret-value" not in out


def test_declared_secret_or_cert_pair_is_ok(home, profiles_file, capsys):
    write_claude(home, servers={"ckm365": entry(env={SECRET: "x"})},
                 projects={"/srv/a": {"ckm365": entry(env={CERT: "/k.pem",
                                                           THUMB: "AB"})}})
    assert doctor(profiles_file, "--mcp") == 0
    out = capsys.readouterr().out
    assert "not declared on the registration" not in out
    assert "/k.pem" not in out and "/srv/a" not in out and "/srv/checkout" not in out


def test_half_a_cert_pair_is_not_declared(home, profiles_file, capsys):
    write_claude(home, servers={"ckm365": entry(env={CERT: "/k.pem"})})
    doctor(profiles_file, "--mcp")
    assert "not declared on the registration" in capsys.readouterr().out


def test_presets_not_enabled_are_listed(home, profiles_file, capsys):
    write_claude(home, servers={"ckm365": entry("mail,calendar", env={SECRET: "x"})})
    doctor(profiles_file, "--mcp")
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if "not enabled" in ln)
    assert "meetings" in line and "teams" in line
    assert "mail" not in line.split("not enabled", 1)[1]


def test_all_preset_counts_as_mail_and_calendar(home, profiles_file, capsys):
    write_claude(home, servers={"ckm365": entry("all,meetings", env={SECRET: "x"})})
    doctor(profiles_file, "--mcp")
    line = next(ln for ln in capsys.readouterr().out.splitlines()
                if "not enabled" in ln)
    assert "teams" in line and "meetings" not in line.split("not enabled", 1)[1]


def test_preset_equals_form_and_default_preset(home, profiles_file, capsys):
    e = entry(env={SECRET: "x"})
    e["args"] = [a for a in e["args"] if a not in ("--preset", "mail,calendar")]
    e["args"].append("--preset=mail,meetings")
    write_claude(home, servers={"ckm365": e})
    doctor(profiles_file, "--mcp")
    line = next(ln for ln in capsys.readouterr().out.splitlines()
                if "not enabled" in ln)
    assert "calendar" in line and "meetings" not in line.split("not enabled", 1)[1]


def test_no_registration_is_a_warning(home, profiles_file, capsys):
    assert doctor(profiles_file, "--mcp") == 0
    out = capsys.readouterr().out
    assert "no ckm365 MCP registration" in out and "warn" in out


def test_without_the_flag_doctor_never_reads_claude_json(home, profiles_file,
                                                         capsys, monkeypatch):
    def boom():
        raise AssertionError("read the MCP registration without --mcp")
    monkeypatch.setattr(admin, "mcp_registrations", boom)
    doctor(profiles_file)
    assert "registration" not in capsys.readouterr().out
