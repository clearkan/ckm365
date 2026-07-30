"""Offline tests for the delta-based watch tools — no tenant, no network."""

from pathlib import Path

import httpx
import pytest

from ckm365 import server
from ckm365.config import Profile
from ckm365.graph import GRAPH_BASE, Graph, GraphError
from ckm365.models import MessageSummary
from ckm365.tools import Ctx, watch


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return "user@tenant-a.example"


def _ctx(handler):
    profiles = {"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1",
        default_mailbox="user@tenant-a.example")}
    ctx = Ctx(profiles=profiles)
    ctx._graphs["tenant-a"] = Graph(
        FakeAuth(), transport=httpx.MockTransport(handler))
    return ctx


def _delta_link(token):
    return (f"{GRAPH_BASE}/users/user%40tenant-a.example/mailFolders"
            f"('inbox')/messages/delta?$deltatoken={token}")


def _msg(i, sender="alice@tenant-b.example", subject="hello"):
    return {"id": f"msg-{i}", "subject": subject,
            "from": {"emailAddress": {"address": sender}},
            "receivedDateTime": "2026-07-30T00:00:00Z"}


# --- list_new_messages ------------------------------------------------------

def test_bootstrap_windows_initial_sync_by_received_time():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={
            "value": [], "@odata.deltaLink": _delta_link("tok1")})

    res = watch.list_new_messages(_ctx(handler))
    assert len(urls) == 1
    assert "messages/delta" in urls[0]
    # Outlook delta ignores $deltatoken=latest (live-tested) — the bootstrap
    # must window by receivedDateTime instead of enumerating the folder.
    assert "receivedDateTime+ge+" in urls[0] or "receivedDateTime%20ge%20" in urls[0]
    assert "deltatoken" not in urls[0]
    assert res == {"messages": [], "delta_token": "tok1", "matched": 0}


def test_drain_caps_runaway_paging():
    def handler(request):
        return httpx.Response(200, json={
            "value": [], "@odata.nextLink":
                f"{GRAPH_BASE}/users/u/mailFolders('inbox')/messages/delta"
                "?$skiptoken=forever"})

    with pytest.raises(GraphError, match="delta_pages_exceeded"):
        watch.list_new_messages(_ctx(handler))


def test_token_round_trip_and_delta_paging():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        if "skiptoken=page2" in urls[-1]:
            return httpx.Response(200, json={
                "value": [_msg(2)], "@odata.deltaLink": _delta_link("tok2")})
        return httpx.Response(200, json={
            "value": [_msg(1)],
            "@odata.nextLink": f"{GRAPH_BASE}/users/user%40tenant-a.example"
                               "/mailFolders('inbox')/messages/delta"
                               "?$skiptoken=page2"})

    res = watch.list_new_messages(_ctx(handler), "tok1")
    assert "deltatoken=tok1" in urls[0]
    assert "select" not in urls[0].lower()  # the token encodes the $select
    assert [m.id for m in res["messages"]] == ["msg-1", "msg-2"]
    assert res["delta_token"] == "tok2"
    assert res["matched"] == 2


def test_client_side_from_and_subject_filtering():
    def handler(request):
        assert "filter" not in str(request.url).lower()  # delta forbids it
        return httpx.Response(200, json={
            "value": [
                _msg(1, sender="Boss@Tenant-B.example", subject="Deploy done"),
                _msg(2, sender="noise@tenant-b.example", subject="Deploy done"),
                _msg(3, sender="boss@tenant-b.example", subject="lunch?"),
            ],
            "@odata.deltaLink": _delta_link("tok2")})

    res = watch.list_new_messages(
        _ctx(handler), "tok1", from_addresses=["boss@tenant-b.example"],
        subject_contains="deploy")
    assert [m.id for m in res["messages"]] == ["msg-1"]
    assert res["matched"] == 1


def test_removed_entries_skipped():
    def handler(request):
        return httpx.Response(200, json={
            "value": [{"id": "gone-1", "@removed": {"reason": "deleted"}},
                      _msg(1)],
            "@odata.deltaLink": _delta_link("tok2")})

    res = watch.list_new_messages(_ctx(handler), "tok1")
    assert [m.id for m in res["messages"]] == ["msg-1"]
    assert res["matched"] == 1


def test_delta_refuses_off_graph_next_link():
    def handler(request):
        return httpx.Response(200, json={
            "value": [], "@odata.nextLink": "https://evil.example.com/delta"})

    with pytest.raises(GraphError, match="unsafe_next_link"):
        watch.list_new_messages(_ctx(handler), "tok1")


# --- wait_for_message -------------------------------------------------------

def test_wait_for_message_returns_on_first_match():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        if len(urls) < 3:
            return httpx.Response(200, json={
                "value": [],
                "@odata.deltaLink": _delta_link(f"tok{len(urls)}")})
        return httpx.Response(200, json={
            "value": [_msg(9)], "@odata.deltaLink": _delta_link("tok3")})

    res = watch.wait_for_message(_ctx(handler), timeout_s=60, poll_s=0)
    assert len(urls) == 3  # returned the moment a message matched
    assert "receivedDateTime" in urls[0]  # bootstrap window, no token yet
    assert "deltatoken=tok1" in urls[1]
    assert res["timed_out"] is False
    assert res["matched"] == 1
    assert res["delta_token"] == "tok3"


def test_wait_for_message_sets_timed_out_on_expiry():
    def handler(request):
        return httpx.Response(200, json={
            "value": [], "@odata.deltaLink": _delta_link("tok1")})

    res = watch.wait_for_message(_ctx(handler), timeout_s=0, poll_s=0)
    assert res["timed_out"] is True
    assert res["matched"] == 0
    assert res["delta_token"] == "tok1"  # caller can resume without a gap


# --- get_watch_command ------------------------------------------------------

def test_get_watch_command_bakes_filters_and_repo_path():
    res = watch.get_watch_command(
        _ctx(lambda request: httpx.Response(500)),  # no Graph calls expected
        from_addresses=["boss@tenant-b.example", "ops@tenant-a.example"],
        subject_contains="deploy done", timeout_s=1800,
        mailbox="shared@tenant-a.example")
    cmd = res["command"]
    repo_root = Path(watch.__file__).resolve().parents[3]
    assert cmd.startswith(f"uv run --directory {repo_root} ckm365 watch")
    assert "--account tenant-a" in cmd
    assert "--folder inbox" in cmd
    assert "--timeout 1800" in cmd
    assert "--mailbox shared@tenant-a.example" in cmd
    assert "--from boss@tenant-b.example" in cmd
    assert "--from ops@tenant-a.example" in cmd
    assert "--contains 'deploy done'" in cmd  # shell-quoted
    assert "background" in res["notes"]
    assert "exits 0" in res["notes"].lower()


# --- ckm365 watch CLI -------------------------------------------------------

def _fake_result(matched, timed_out):
    msgs = [MessageSummary.model_validate(_msg(1))] if matched else []
    return {"messages": msgs, "delta_token": "tok9",
            "matched": matched, "timed_out": timed_out}


def test_watch_cli_exit_codes(monkeypatch, tmp_path, capsys):
    profiles = tmp_path / "profiles.toml"
    profiles.write_text(
        '[profiles.tenant-a]\ntenant_id = "t1"\nclient_id = "c1"\n')
    argv = ["--profiles", str(profiles), "watch", "--account", "tenant-a",
            "--timeout", "5", "--poll", "0"]

    monkeypatch.setattr("ckm365.tools.watch.wait_for_message",
                        lambda ctx, **kw: _fake_result(1, False))
    with pytest.raises(SystemExit) as on_match:
        server.main(argv)
    assert on_match.value.code == 0
    out = capsys.readouterr().out
    assert "matched=1" in out and "msg-1" in out
    assert "hello" not in out  # ids and counts only — never subjects

    monkeypatch.setattr("ckm365.tools.watch.wait_for_message",
                        lambda ctx, **kw: _fake_result(0, True))
    with pytest.raises(SystemExit) as on_timeout:
        server.main(argv)
    assert on_timeout.value.code == 3

    def boom(ctx, **kw):
        raise GraphError(500, "internalServerError", "upstream sad")

    monkeypatch.setattr("ckm365.tools.watch.wait_for_message", boom)
    with pytest.raises(SystemExit) as on_error:
        server.main(argv)
    assert on_error.value.code == 1
