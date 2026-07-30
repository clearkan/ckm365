"""Offline sanity tests — no tenant, no network (httpx.MockTransport)."""

import inspect

import httpx
import pytest

from ckm365.auth import DELEGATED_RW, DELEGATED_SEND, Auth
from ckm365.config import ConfigError, Profile, load_profiles, resolve_profile
from ckm365.graph import GRAPH_BASE, Graph, GraphError, mailbox_path
from ckm365.models import Event, Message
from ckm365.tools import (Ctx, SendDisabled, WriteDisabled, bind, calendar,
                          mail, tools_for)


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return "user@example.com"


def make_graph(handler):
    return Graph(FakeAuth(), transport=httpx.MockTransport(handler))


# --- config ---------------------------------------------------------------

def test_profile_rejects_common_authority():
    with pytest.raises(ConfigError, match="never"):
        Profile(name="x", tenant_id="common", client_id="c")


def test_app_only_requires_default_mailbox():
    with pytest.raises(ConfigError, match="default_mailbox"):
        Profile(name="x", tenant_id="t", client_id="c", auth="client_credential")


def test_load_and_resolve_profiles(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        '[profiles.tenant-a]\ntenant_id = "t1"\nclient_id = "c1"\n'
        'description = "work tenant"\n'
        '[profiles.tenant-b]\ntenant_id = "t2"\nclient_id = "c2"\n')
    profiles = load_profiles(path)
    assert resolve_profile(profiles, "tenant-b").tenant_id == "t2"
    assert profiles["tenant-a"].description == "work tenant"
    with pytest.raises(ConfigError, match="pass account"):
        resolve_profile(profiles, None)
    with pytest.raises(ConfigError, match="unknown account"):
        resolve_profile(profiles, "nope")


def test_allow_send_key_parsed_defaulted_and_validated(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        '[profiles.capped]\ntenant_id = "t1"\nclient_id = "c1"\n'
        'allow_send = false\n'
        '[profiles.open]\ntenant_id = "t2"\nclient_id = "c2"\n')
    profiles = load_profiles(path)
    assert profiles["capped"].allow_send is False
    assert profiles["open"].allow_send is True  # default
    path.write_text('[profiles.x]\ntenant_id = "t"\nclient_id = "c"\n'
                    'allow_send = "false"\n')  # truthy string must not pass
    with pytest.raises(ConfigError, match="allow_send"):
        load_profiles(path)
    path.write_text('[profiles.x]\ntenant_id = "t"\nclient_id = "c"\n'
                    'alow_send = false\n')
    with pytest.raises(ConfigError, match="unknown key"):
        load_profiles(path)


# --- auth -----------------------------------------------------------------

def test_send_capped_profile_never_requests_send_scopes(tmp_path):
    capped = Profile(name="p", tenant_id="t", client_id="c", allow_send=False)
    scopes = Auth(capped, read_only=False, send=True, cache_dir=tmp_path).scopes
    assert scopes == DELEGATED_RW
    assert not any("Send" in s for s in scopes)
    open_ = Profile(name="q", tenant_id="t", client_id="c")
    assert Auth(open_, read_only=False, send=True,
                cache_dir=tmp_path).scopes == DELEGATED_SEND


# --- graph ----------------------------------------------------------------

def test_paged_follows_next_link():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "page2" in str(request.url):
            return httpx.Response(200, json={"value": [{"n": 3}]})
        return httpx.Response(200, json={
            "value": [{"n": 1}, {"n": 2}],
            "@odata.nextLink": f"{GRAPH_BASE}/page2?$skiptoken=abc"})

    items = list(make_graph(handler).paged("/things", max_items=10))
    assert [i["n"] for i in items] == [1, 2, 3]
    assert "skiptoken" in calls[1]


def test_paged_max_items_stops_early():
    def handler(request):
        return httpx.Response(200, json={
            "value": [{"n": 1}, {"n": 2}], "@odata.nextLink": f"{GRAPH_BASE}/more"})

    assert len(list(make_graph(handler).paged("/things", max_items=2))) == 2


def test_429_retried_with_retry_after():
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"ok": True})

    assert make_graph(handler).post("/x") == {"ok": True}
    assert len(attempts) == 2


def test_5xx_not_retried_on_post():
    def handler(request):
        return httpx.Response(503, json={"error": {"code": "x", "message": "m"}})

    with pytest.raises(GraphError) as err:
        make_graph(handler).post("/x")
    assert err.value.status == 503


def test_mailbox_path_encodes_and_validates():
    assert mailbox_path("ops@x.com", "messages") == "/users/ops%40x.com/messages"
    with pytest.raises(ValueError):
        mailbox_path("a/b", "messages")


def test_paged_refuses_off_graph_next_link():
    def handler(request):
        return httpx.Response(200, json={
            "value": [{"n": 1}],
            "@odata.nextLink": "https://evil.example.com/v1.0/steal-token"})

    with pytest.raises(GraphError, match="unsafe_next_link"):
        list(make_graph(handler).paged("/things", max_items=10))


# --- models ---------------------------------------------------------------

def test_message_model_flattens_graph_shapes():
    msg = Message.model_validate({
        "id": "m1", "subject": "Hi",
        "from": {"emailAddress": {"name": "A", "address": "a@x.com"}},
        "toRecipients": [{"emailAddress": {"address": "b@x.com"}}],
        "body": {"contentType": "html", "content": "<p>hey</p>"},
        "isDraft": True, "@odata.etag": "ignored"})
    assert msg.sender.address == "a@x.com"
    assert msg.to[0].address == "b@x.com"
    assert msg.body.content_type == "html"
    assert msg.is_draft


def test_event_model_flattens_location_and_join_url():
    ev = Event.model_validate({
        "id": "e1", "subject": "standup",
        "start": {"dateTime": "2026-07-30T09:00:00", "timeZone": "UTC"},
        "end": {"dateTime": "2026-07-30T09:15:00", "timeZone": "UTC"},
        "location": {"displayName": "Room 1"},
        "onlineMeeting": {"joinUrl": "https://teams/x"},
        "attendees": [{"emailAddress": {"address": "a@x.com"}, "type": "required"}]})
    assert ev.location == "Room 1"
    assert ev.join_url == "https://teams/x"
    assert ev.attendees[0].address == "a@x.com"


# --- tools / gating / binding ----------------------------------------------

def _ctx(**kw):
    profiles = {"p": Profile(name="p", tenant_id="t", client_id="c")}
    return Ctx(profiles=profiles, **kw)


def test_write_tools_gated():
    with pytest.raises(WriteDisabled):
        mail.create_draft(_ctx(), to=["a@x.com"], subject="s", body="b")


def test_tools_for_presets():
    assert len(tools_for(["mail"])) == 8  # incl. list_accounts (ALWAYS)
    assert len(tools_for(["mail"], write=True)) == 13
    assert len(tools_for(["mail"], write=True, send=True)) == 14
    assert len(tools_for(["all"], write=True)) == 18
    assert len(tools_for(["all"], write=True, send=True)) == 19
    with pytest.raises(ValueError, match="require write"):
        tools_for(["mail"], send=True)
    with pytest.raises(ValueError, match="unknown preset"):
        tools_for(["files"])


def test_send_tier_gated():
    with pytest.raises(WriteDisabled):
        mail.send_draft(_ctx(), "m1")
    with pytest.raises(SendDisabled):
        mail.send_draft(_ctx(write_enabled=True), "m1")
    with pytest.raises(SendDisabled):
        calendar.create_event(_ctx(write_enabled=True), subject="s",
                              start="2026-01-01T00:00:00",
                              end="2026-01-01T01:00:00",
                              attendees=["a@x.com"])
    with pytest.raises(SendDisabled):
        calendar.respond_event(_ctx(write_enabled=True), "e1", "accept")
    with pytest.raises(ValueError, match="response must be"):
        calendar.respond_event(_ctx(write_enabled=True), "e1", "maybe")


def _capped_ctx(**profile_kw):
    profiles = {"p": Profile(name="p", tenant_id="t", client_id="c",
                             allow_send=False, **profile_kw)}
    return Ctx(profiles=profiles, write_enabled=True, send_enabled=True)


def test_profile_send_cap_overrides_server_flags():
    with pytest.raises(SendDisabled, match="allow_send"):
        mail.send_draft(_capped_ctx(), "m1")
    with pytest.raises(SendDisabled, match="allow_send"):
        calendar.create_event(_capped_ctx(), subject="s",
                              start="2026-01-01T00:00:00",
                              end="2026-01-01T01:00:00",
                              attendees=["user@tenant-a.example"])
    with pytest.raises(SendDisabled, match="allow_send"):
        calendar.respond_event(_capped_ctx(), "e1", "accept")


def test_profile_send_cap_covers_attendee_bearing_event_update():
    def handler(request):
        return httpx.Response(200, json={
            "id": "e1", "attendees":
            [{"emailAddress": {"address": "user@tenant-a.example"}}]})

    ctx = _capped_ctx(default_mailbox="me@tenant-a.example")
    ctx._graphs["p"] = make_graph(handler)
    with pytest.raises(SendDisabled, match="allow_send"):
        calendar.update_event(ctx, "e1", subject="s")


def test_account_pin_blocks_cross_profile_and_hides_param():
    profiles = {"a": Profile(name="a", tenant_id="t1", client_id="c1"),
                "b": Profile(name="b", tenant_id="t2", client_id="c2")}
    ctx = Ctx(profiles=profiles, account="a")
    assert ctx.profile(None).name == "a"
    assert ctx.profile("a").name == "a"
    with pytest.raises(ConfigError, match="pinned"):
        ctx.profile("b")
    bound = bind(mail.list_messages, ctx)
    assert "account" not in inspect.signature(bound).parameters
    assert "account" not in bound.__annotations__
    unpinned = bind(mail.list_messages, Ctx(profiles=profiles))
    assert "account" in inspect.signature(unpinned).parameters


def test_add_attachment_gated_and_size_capped(tmp_path):
    small = tmp_path / "a.txt"
    small.write_text("hi")
    with pytest.raises(WriteDisabled):
        mail.add_attachment(_ctx(), "m1", str(small))
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (3 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="3 MB"):
        mail.add_attachment(_ctx(write_enabled=True), "m1", str(big))


def test_add_attachment_respects_attach_root(tmp_path, monkeypatch):
    inside = tmp_path / "root" / "ok.txt"
    inside.parent.mkdir()
    inside.write_text("hi")
    outside = tmp_path / "outside.txt"
    outside.write_text("hi")
    monkeypatch.setenv("CKM365_ATTACH_ROOT", str(tmp_path / "root"))
    with pytest.raises(ValueError, match="ATTACH_ROOT"):
        mail.add_attachment(_ctx(write_enabled=True), "m1", str(outside))


def test_timezone_validated_before_use():
    with pytest.raises(ValueError, match="invalid timezone"):
        calendar.list_events(_ctx(), start="2026-01-01T00:00:00",
                             end="2026-01-02T00:00:00",
                             timezone='UTC", outlook.body-content-type="html')


def test_search_escaped_in_query():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"value": []})

    profiles = {"p": Profile(name="p", tenant_id="t", client_id="c",
                             default_mailbox="me@x.com")}
    ctx = Ctx(profiles=profiles)
    ctx._graphs["p"] = make_graph(handler)
    mail.list_messages(ctx, search='say "hi" \\')
    assert '%22' in captured["url"]  # quotes preserved, escaped, not swapped
    assert "say" in captured["url"]


def test_bind_hides_ctx_from_signature():
    bound = bind(mail.list_messages, _ctx())
    params = inspect.signature(bound).parameters
    assert "ctx" not in params
    assert "folder" in params and "account" in params
    assert bound.__name__ == "list_messages"
    assert "ctx" not in bound.__annotations__
