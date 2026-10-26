"""Keep the offline suite hermetic.

Ctx/Auth resolve the MSAL cache directory through state_dir(), which
creates ~/.local/state/ckm365 on first use. Two offline tests reached it
through Ctx.create and wrote there — harmless on a developer box, but a
hard failure in any sandbox whose home directory is read-only (seen
2026-10-26 under Codex's workspace-write sandbox), and a test suite has
no business touching the directory that holds real token caches.
"""

import pytest


@pytest.fixture(autouse=True)
def _state_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME",
                       str(tmp_path_factory.mktemp("state")))
