"""Keep the offline suite hermetic.

Ctx/Auth resolve the MSAL cache directory through state_dir(), which
creates ~/.local/state/ckm365 on first use. Two offline tests reached it
through Ctx.create and wrote there — harmless on a developer box, but a
hard failure in any sandbox whose home directory is read-only (seen
2026-10-26 under Codex's workspace-write sandbox), and a test suite has
no business touching the directory that holds real token caches.

The LIVE suites are the exception by definition: they need the real
caches, so the override steps aside when CKM365_LIVE_ACCOUNT is set.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _disk_roots(tmp_path_factory, monkeypatch):
    """From v2.14.0 every disk tool is confined to a root even when none is
    configured (CKM-j30wca, CKM-h03k8p). Point both roots at pytest's base
    temp dir so tests writing under tmp_path keep working, live runs
    included. Tests about the roots themselves override this."""
    base = str(tmp_path_factory.getbasetemp())
    monkeypatch.setenv("CKM365_DOWNLOAD_ROOT", base)
    monkeypatch.setenv("CKM365_ATTACH_ROOT", base)


@pytest.fixture(autouse=True)
def _state_home(tmp_path_factory, monkeypatch):
    if os.environ.get("CKM365_LIVE_ACCOUNT"):
        return
    monkeypatch.setenv("XDG_STATE_HOME",
                       str(tmp_path_factory.mktemp("state")))
