"""Offline spec for `ckm365 refresh` (kw20z6 gap 3, CKM-44): make newly
granted consent take effect without an interactive re-login.

Found on a live transcript pull: after add-transcript-scopes.sh granted
new scopes, a still-valid ACCESS token minted before the consent kept
403ing until it expired (up to ~an hour). The fix that worked, applied by
hand-editing JSON next to the credential cache: drop only the
AccessToken section of the profile's MSAL cache. The refresh token, the
account and the id token stay, so the next call mints a fresh access
token carrying the new scopes, silently.

- `Auth.drop_access_tokens() -> int`: under the same lock as every other
  cache write, remove every cached access token, keep everything else,
  write back atomically with mode 0600. Returns how many were dropped.
  Works for app-only profiles too (a fresh app token carries newly
  granted app roles).
- CLI `ckm365 refresh [profile]`: runs it and prints the count. Never
  contacts Graph or Entra. A profile with no cache file is an error
  telling the user to log in.
- Never prints or logs token material.

Skipped as a module until Auth.drop_access_tokens exists.
"""

import json
import stat

import pytest

from ckm365.auth import Auth

if not hasattr(Auth, "drop_access_tokens"):
    pytest.skip("refresh not built yet (kw20z6 gap 3)", allow_module_level=True)

from ckm365.config import Profile  # noqa: E402
from ckm365.server import main  # noqa: E402

TENANT_A = "00000000-0000-0000-0000-00000000000a"


def _cache(n_access=2):
    """A fabricated MSAL cache: placeholder strings, never real tokens."""
    at = {f"uid.utid-login.example-accesstoken-c1-t{i}-scope{i}": {
        "credential_type": "AccessToken", "secret": f"fake-at-{i}",
        "home_account_id": "uid.utid", "environment": "login.example",
        "client_id": "c1", "realm": "t1", "target": f"scope{i}",
        "cached_at": "1", "expires_on": "9999999999"} for i in range(n_access)}
    return {
        "AccessToken": at,
        "RefreshToken": {"uid.utid-login.example-refreshtoken-c1--": {
            "credential_type": "RefreshToken", "secret": "fake-rt",
            "home_account_id": "uid.utid", "environment": "login.example",
            "client_id": "c1", "target": "Mail.ReadWrite"}},
        "IdToken": {"uid.utid-login.example-idtoken-c1-t1-": {
            "credential_type": "IdToken", "secret": "fake-id",
            "home_account_id": "uid.utid", "environment": "login.example",
            "client_id": "c1", "realm": "t1"}},
        "Account": {"uid.utid-login.example-t1": {
            "home_account_id": "uid.utid", "environment": "login.example",
            "realm": "t1", "local_account_id": "uid",
            "username": "user@tenant-a.example", "authority_type": "MSSTS"}},
        "AppMetadata": {"appmetadata-login.example-c1": {
            "client_id": "c1", "environment": "login.example"}},
    }


def _profile(name="tenant-a", **kw):
    return Profile(name=name, tenant_id=TENANT_A, client_id="c1", **kw)


@pytest.fixture
def cache_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir(mode=0o700)
    return d


def _write(cache_dir, data, name="tenant-a"):
    path = cache_dir / f"{name}.msal.json"
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return path


def test_drops_only_access_tokens(cache_dir):
    path = _write(cache_dir, _cache(2))
    assert Auth(_profile(), cache_dir=cache_dir).drop_access_tokens() == 2
    after = json.loads(path.read_text())
    before = _cache(2)
    assert not after.get("AccessToken")
    for section in ("RefreshToken", "IdToken", "Account", "AppMetadata"):
        assert after[section] == before[section]


def test_file_stays_private(cache_dir):
    path = _write(cache_dir, _cache(1))
    Auth(_profile(), cache_dir=cache_dir).drop_access_tokens()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not [p for p in cache_dir.iterdir() if p.name.endswith(".tmp")]


def test_nothing_to_drop_is_zero(cache_dir):
    _write(cache_dir, _cache(0))
    assert Auth(_profile(), cache_dir=cache_dir).drop_access_tokens() == 0


def test_no_cache_is_an_error_naming_login(cache_dir):
    from ckm365.auth import NeedsLogin
    with pytest.raises(NeedsLogin, match="login"):
        Auth(_profile(), cache_dir=cache_dir).drop_access_tokens()


def test_app_only_profile_works_too(cache_dir):
    p = _profile("app-a", auth="client_credential",
                 default_mailbox="ops@tenant-a.example")
    _write(cache_dir, _cache(3), name="app-a")
    assert Auth(p, cache_dir=cache_dir).drop_access_tokens() == 3


def test_takes_the_cache_lock(cache_dir, monkeypatch):
    _write(cache_dir, _cache(1))
    auth = Auth(_profile(), cache_dir=cache_dir)
    entered = []
    original = auth._lock

    def spy():
        entered.append(True)
        return original()

    monkeypatch.setattr(auth, "_lock", spy)
    auth.drop_access_tokens()
    assert entered


# --- the CLI ---------------------------------------------------------------------

def _run(argv):
    """main() returns normally for login/logout-style commands and raises
    SystemExit for errors; give back an exit code either way."""
    try:
        main(argv)
    except SystemExit as exc:
        return exc.code
    return 0


@pytest.fixture
def profiles_file(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(f'[profiles.tenant-a]\ntenant_id = "{TENANT_A}"\n'
                    'client_id = "c1"\n')
    path.chmod(0o600)
    return path


def test_cli_refresh_prints_the_count_and_no_secrets(profiles_file, tmp_path,
                                                     monkeypatch, capsys):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    d = tmp_path / "xdg" / "ckm365"
    d.mkdir(parents=True, mode=0o700)
    _write(d, _cache(2))
    assert _run(["--profiles", str(profiles_file), "refresh", "tenant-a"]) in (0, None)
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "2" in out and "tenant-a" in out
    assert "fake-" not in out


def test_cli_refresh_without_cache_fails(profiles_file, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    code = _run(["--profiles", str(profiles_file), "refresh"])
    assert code not in (0, None)
    assert "login" in str(code)
