"""Offline spec for CKM-j30wca and CKM-h03k8p (v2.14.0): every tool that
touches local disk is confined to a root, ALWAYS.

Until v2.13.0 the roots were opt-in. With CKM365_ATTACH_ROOT unset (the
default), add_attachment read any file the server could read, so a
prompt-injected agent could attach the MSAL token cache, profiles.toml or
~/.ssh to a draft (and, with send enabled, mail it out). With
CKM365_DOWNLOAD_ROOT unset, download_attachment, the exporters and the
migration tools wrote wherever the agent pointed: a sender's attachment
saved as a login autostart file, or as a repo's agent settings file.
Approved by seanwy on 10 Nov 2026, default root included.

Design:
- `disk.default_root()`: `$XDG_DATA_HOME/ckm365`, or
  `~/.local/share/ckm365` without XDG_DATA_HOME. Created on first use
  with mode 0700.
- `disk.download_root()`: CKM365_DOWNLOAD_ROOT, else CKM365_ATTACH_ROOT
  (the existing fallback), else default_root().
- `disk.attach_root()`: CKM365_ATTACH_ROOT, else default_root().
  CKM365_DOWNLOAD_ROOT never widens what may be READ.
- `disk.confine(path, what, root=None)` resolves the path (following
  symlinks) and refuses it unless it is inside `root` (download_root()
  when None). It also ALWAYS refuses, whatever the root:
  - a path inside ckm365's own state directory (`config.state_dir()`,
    the token caches) or the profiles file (`config.profiles_path()`) or
    the directory holding it;
  - a path with any component starting with "." BELOW the root (dotfiles
    and dot-directories: .ssh, .config, .claude, .env, .git ...). The
    root itself may sit under a dot-directory, as the default does.
  Refusals are ValueError. The outside-root message names the governing
  env var and the root in use, e.g. "... outside the download root
  (<root>); set CKM365_DOWNLOAD_ROOT to change it", and keeps the
  existing phrases "outside the download root" and "CKM365_ATTACH_ROOT"
  that current tests match.
- add_attachment confines its source with `root=attach_root()` before
  touching Graph. Every writer that calls confine today keeps calling it
  and is therefore confined by default.

The suite's conftest points both roots at pytest's base temp dir, so
tests writing to tmp_path keep working; tests here override that.

Skipped as a module until disk.default_root exists.
"""

import os
import stat

import httpx
import pytest

from ckm365.tools.mail import disk

if not hasattr(disk, "default_root"):
    pytest.skip("disk roots not built yet (CKM-j30wca, CKM-h03k8p)",
                allow_module_level=True)

from ckm365 import config  # noqa: E402
from ckm365.config import Profile  # noqa: E402
from ckm365.graph import Graph  # noqa: E402
from ckm365.tools import Ctx, mail  # noqa: E402


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return "user@tenant-a.example"


def _no_graph_ctx():
    """Any Graph request fails the test: a refusal must come first."""
    def handler(request):
        raise AssertionError(f"Graph was called: {request.method} {request.url}")

    ctx = Ctx(profiles={"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1",
        default_mailbox="user@tenant-a.example")}, write_enabled=True)
    ctx.set_graph("tenant-a", Graph(FakeAuth(),
                                    transport=httpx.MockTransport(handler)))
    return ctx


@pytest.fixture
def no_roots(tmp_path, monkeypatch):
    """Neither env var set; XDG_DATA_HOME in tmp. Returns the default root."""
    monkeypatch.delenv("CKM365_DOWNLOAD_ROOT", raising=False)
    monkeypatch.delenv("CKM365_ATTACH_ROOT", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path / "data" / "ckm365"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home used as BOTH roots, with ckm365's state and config in
    it, so only the always-deny rules stand between a path and a read."""
    h = tmp_path / "home"
    (h / ".ssh").mkdir(parents=True)
    (h / ".ssh" / "id_ed25519").write_text("fake key")
    (h / "docs").mkdir()
    (h / "docs" / "report.txt").write_text("ok")
    (h / "docs" / ".env").write_text("SECRET=fake")
    cfg = h / "cfg" / "ckm365"
    cfg.mkdir(parents=True)
    (cfg / "profiles.toml").write_text("")
    monkeypatch.setenv("CKM365_PROFILES", str(cfg / "profiles.toml"))
    monkeypatch.setenv("XDG_STATE_HOME", str(h / "state"))
    cache = config.state_dir() / "tenant-a.msal.json"
    cache.write_text("{}")
    monkeypatch.setenv("CKM365_ATTACH_ROOT", str(h))
    monkeypatch.setenv("CKM365_DOWNLOAD_ROOT", str(h))
    return h


# --- the default root ----------------------------------------------------------

def test_default_root_follows_xdg_data_home_and_is_private(no_roots):
    root = disk.default_root()
    assert root == no_roots.resolve() or root == no_roots
    assert root.is_dir()
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_default_root_without_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert disk.default_root() == tmp_path / ".local" / "share" / "ckm365"


def test_both_roots_default_to_it(no_roots):
    assert disk.download_root() == disk.default_root()
    assert disk.attach_root() == disk.default_root()


def test_env_precedence(no_roots, tmp_path, monkeypatch):
    monkeypatch.setenv("CKM365_ATTACH_ROOT", str(tmp_path / "a"))
    assert disk.download_root() == tmp_path / "a"      # the existing fallback
    assert disk.attach_root() == tmp_path / "a"
    monkeypatch.setenv("CKM365_DOWNLOAD_ROOT", str(tmp_path / "d"))
    assert disk.download_root() == tmp_path / "d"
    assert disk.attach_root() == tmp_path / "a"        # downloads never widen reads


# --- confinement is no longer opt-in -------------------------------------------

def test_writes_outside_the_default_root_are_refused(no_roots, tmp_path):
    with pytest.raises(ValueError, match="outside the download root") as e:
        disk.confine(tmp_path / "elsewhere" / "x.pdf", "destination")
    assert "CKM365_DOWNLOAD_ROOT" in str(e.value)
    assert str(disk.default_root()) in str(e.value)


def test_writes_inside_the_default_root_are_fine(no_roots):
    target = disk.default_root() / "exports" / "x.pdf"
    assert disk.confine(target, "destination") == target.resolve()


def test_add_attachment_without_a_root_refuses_files_outside_the_default(
        no_roots, tmp_path):
    outside = tmp_path / "anything.txt"
    outside.write_text("hi")
    with pytest.raises(ValueError, match="CKM365_ATTACH_ROOT"):
        mail.add_attachment(_no_graph_ctx(), "m1", str(outside))


def test_add_attachment_inside_the_default_root_reaches_graph(no_roots):
    inside = disk.default_root() / "ok.txt"
    inside.write_text("hi")
    with pytest.raises(AssertionError, match="Graph was called"):
        mail.add_attachment(_no_graph_ctx(), "m1", str(inside))


def test_download_attachment_without_a_root_is_refused(no_roots, tmp_path):
    with pytest.raises(ValueError, match="outside the download root"):
        disk.write_target(str(tmp_path / "x.pdf"), None)


# --- always denied, whatever the root --------------------------------------------

def test_token_cache_can_never_be_attached(home):
    cache = config.state_dir() / "tenant-a.msal.json"
    with pytest.raises(ValueError, match="state"):
        mail.add_attachment(_no_graph_ctx(), "m1", str(cache))


def test_profiles_file_and_its_directory_are_denied(home):
    with pytest.raises(ValueError, match="profiles"):
        disk.confine(home / "cfg" / "ckm365" / "profiles.toml", "attachment",
                     root=disk.attach_root())
    with pytest.raises(ValueError, match="profiles"):
        disk.confine(home / "cfg" / "ckm365" / "notes.txt", "destination")


@pytest.mark.parametrize("rel", [".ssh/id_ed25519", "docs/.env",
                                 ".claude/settings.json", ".config/autostart/x"])
def test_hidden_paths_below_the_root_are_denied(home, rel):
    with pytest.raises(ValueError, match="hidden"):
        disk.confine(home / rel, "destination")


def test_ordinary_paths_below_the_root_are_allowed(home):
    path = home / "docs" / "report.txt"
    assert disk.confine(path, "attachment", root=disk.attach_root()) == path.resolve()


def test_root_may_itself_live_under_a_dot_directory(no_roots):
    # the default does: ~/.local/share/ckm365
    target = disk.default_root() / "a.txt"
    assert disk.confine(target, "destination") == target.resolve()


def test_symlink_out_of_the_root_is_refused(home, tmp_path):
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("x")
    link = home / "docs" / "innocent.txt"
    os.symlink(secret, link)
    with pytest.raises(ValueError, match="outside"):
        disk.confine(link, "attachment", root=disk.attach_root())


def test_symlink_to_a_hidden_file_is_refused(home):
    link = home / "docs" / "key.txt"
    os.symlink(home / ".ssh" / "id_ed25519", link)
    with pytest.raises(ValueError, match="hidden"):
        mail.add_attachment(_no_graph_ctx(), "m1", str(link))
