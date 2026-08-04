"""Offline tests for recipients on listings (CKM-37) and curated internet
headers (CKM-38) — no tenant, no network.

Fixtures are fake ids and *.example addresses throughout.
"""

import json

import httpx
import pytest

from ckm365.config import Profile
from ckm365.graph import Graph
from ckm365.models import Message, MessageHeaders, MessageSummary
from ckm365.tools import Ctx, mail


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return "user@tenant-a.example"


def _ctx(handler, *, write=False):
    profiles = {"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1",
        default_mailbox="user@tenant-a.example")}
    ctx = Ctx(profiles=profiles, write_enabled=write)
    ctx.set_graph("tenant-a", Graph(
        FakeAuth(), transport=httpx.MockTransport(handler)))
    return ctx


def _to(*addresses):
    return [{"emailAddress": {"address": a}} for a in addresses]


# --- recipients on listings (CKM-37) ---------------------------------------

def test_listing_carries_to_and_cc_from_the_collection_get():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={"value": [{
            "id": "m1", "subject": "s",
            "from": {"emailAddress": {"address": "user@tenant-a.example"}},
            "toRecipients": _to("client@tenant-b.example"),
            "ccRecipients": _to("colleague@tenant-a.example")}]})

    msgs = mail.list_messages(_ctx(handler), folder="sentitems")
    select = httpx.URL(urls[0]).params["$select"]
    assert "toRecipients" in select and "ccRecipients" in select
    # Sent Items: the sender is always the owner, so `to` IS the
    # correspondent — the thing that was unanswerable before (CKM-37).
    assert msgs[0].sender.address == "user@tenant-a.example"
    assert [r.address for r in msgs[0].to] == ["client@tenant-b.example"]
    assert [r.address for r in msgs[0].cc] == ["colleague@tenant-a.example"]


def test_summary_omits_bcc_and_headers_but_the_full_message_keeps_bcc():
    """bcc exists only on the sender's own copy, and the header bag costs
    ~10 KB a row, so neither rides along on every listing row."""
    assert "bccRecipients" not in MessageSummary.SELECT
    assert "internetMessageHeaders" not in MessageSummary.SELECT
    assert not hasattr(MessageSummary(id="m1"), "bcc")
    full = Message.from_graph({
        "id": "m1", "toRecipients": _to("client@tenant-b.example"),
        "bccRecipients": _to("archive@tenant-a.example")})
    assert [r.address for r in full.to] == ["client@tenant-b.example"]
    assert [r.address for r in full.bcc] == ["archive@tenant-a.example"]


def test_missing_recipients_project_to_empty_lists():
    summary = MessageSummary.from_graph({"id": "m1"})
    assert summary.to == [] and summary.cc == []


# --- curated headers (CKM-38) ----------------------------------------------

def _headers(*pairs):
    return {"internetMessageHeaders": [{"name": n, "value": v}
                                       for n, v in pairs]}


def test_only_the_curated_headers_are_projected():
    """Never the raw bag: routing detail and internal hostnames stay out."""
    h = MessageHeaders.from_graph(_headers(
        ("Received", "from mail-relay.internal.example by ..."),
        ("X-Internal-Host", "exch-node-7.internal.example"),
        ("DKIM-Signature", "v=1; a=rsa-sha256; d=tenant-b.example; ..."),
        ("List-Id", "News <news.tenant-b.example>"),
        ("Return-Path", "bounces@mail.tenant-b.example")))
    assert h.list_id == "News <news.tenant-b.example>"
    assert h.return_path == "bounces@mail.tenant-b.example"
    assert "internal.example" not in json.dumps(h.__dict__)


def test_header_names_match_case_insensitively_and_first_wins():
    h = MessageHeaders.from_graph(_headers(
        ("LIST-UNSUBSCRIBE", "<https://tenant-b.example/u/1>"),
        ("list-unsubscribe", "<https://attacker.example/second>")))
    assert h.list_unsubscribe == "<https://tenant-b.example/u/1>"


def test_is_bulk_is_derived_but_the_raw_values_stay_alongside():
    unsub = MessageHeaders.from_graph(
        _headers(("List-Unsubscribe", "<mailto:u@tenant-b.example>")))
    assert unsub.is_bulk and not unsub.is_auto_reply
    assert unsub.list_unsubscribe == "<mailto:u@tenant-b.example>"  # auditable

    assert MessageHeaders.from_graph(_headers(("List-Id", "x"))).is_bulk
    for value in ("bulk", "list", "junk", "Bulk"):
        assert MessageHeaders.from_graph(
            _headers(("Precedence", value))).is_bulk, value
    for value in ("first-class", "normal"):
        assert not MessageHeaders.from_graph(
            _headers(("Precedence", value))).is_bulk, value
    assert not MessageHeaders.from_graph(_headers(
        ("From", "colleague@tenant-a.example"))).is_bulk


def test_is_auto_reply_covers_the_machine_sent_signals():
    for value in ("auto-replied", "auto-generated", "auto-notified",
                  "auto-replied; owner@tenant-b.example"):
        assert MessageHeaders.from_graph(
            _headers(("Auto-Submitted", value))).is_auto_reply, value
    # RFC 3834: "no" is the explicit NOT-auto-submitted value.
    assert not MessageHeaders.from_graph(
        _headers(("Auto-Submitted", "no"))).is_auto_reply
    assert MessageHeaders.from_graph(
        _headers(("X-Auto-Response-Suppress", "OOF"))).is_auto_reply
    assert MessageHeaders.from_graph(_headers()).is_auto_reply is False


def test_values_are_sanitised_and_capped():
    """Header values are attacker-controlled free text: no control
    characters into a log or a context, and no unbounded strings."""
    h = MessageHeaders.from_graph(_headers(
        ("List-Id", "spoof\r\nX-Injected: yes\ttab\x00nul  spaces"),
        ("List-Unsubscribe", "<https://tenant-b.example/" + "a" * 400 + ">")))
    assert h.list_id == "spoof X-Injected: yes tab nul spaces"
    assert not any(ord(c) < 32 for c in h.list_id)
    assert len(h.list_unsubscribe) == 200 and h.list_unsubscribe.endswith("…")


def test_get_message_returns_curated_headers():
    def handler(request):
        return httpx.Response(200, json={
            "id": "m1", "subject": "s",
            "body": {"contentType": "text", "content": "hi"},
            **_headers(("Precedence", "bulk"),
                       ("Received", "from relay.internal.example"))})

    msg = mail.get_message(_ctx(handler), "m1")
    assert msg.headers.is_bulk and msg.headers.precedence == "bulk"
    assert "internetMessageHeaders" in Message.SELECT


def test_get_message_headers_batches_and_returns_plain_dicts():
    sent = []

    def handler(request):
        payload = json.loads(request.content)
        sent.append(payload["requests"])
        return httpx.Response(200, json={"responses": [
            {"id": r["id"], "status": 200,
             "body": _headers(("List-Unsubscribe", "<mailto:u@tenant-b.example>"))}
            for r in reversed(payload["requests"])]})  # Graph answers unordered

    res = mail.get_message_headers(_ctx(handler), [f"m{i}" for i in range(25)])
    assert [len(chunk) for chunk in sent] == [20, 5]  # Graph's /$batch cap
    assert [r["method"] for r in sent[0][:1]] == ["GET"]
    assert sent[0][0]["url"] == ("/users/user%40tenant-a.example/messages/m0"
                                 "?$select=id,internetMessageHeaders")
    assert res["ok"] == 25 and res["failed"] == []
    assert res["headers"]["m7"]["is_bulk"] is True
    # plain dicts, so the MCP/pydantic front doors serialize a dict return
    assert isinstance(res["headers"]["m7"], dict)
    assert "SELECT" not in res["headers"]["m7"]


def test_get_message_headers_reports_per_message_failure():
    def handler(request):
        payload = json.loads(request.content)
        return httpx.Response(200, json={"responses": [
            {"id": r["id"],
             "status": 404 if r["url"].endswith("m2?$select=id,"
                                                "internetMessageHeaders") else 200,
             "body": {"error": {"code": "ErrorItemNotFound", "message": "gone"}}
             if r["url"].endswith("m2?$select=id,internetMessageHeaders")
             else _headers(("Precedence", "list"))}
            for r in payload["requests"]]})

    res = mail.get_message_headers(_ctx(handler), ["m1", "m2", "m3"])
    assert res["ok"] == 2 and list(res["headers"]) == ["m1", "m3"]
    assert res["failed"] == [{"id": "m2", "error": "404 ErrorItemNotFound gone"}]


def test_get_message_headers_is_read_tier_and_validates_ids():
    def handler(request):
        return httpx.Response(200, json={"responses": []})

    ctx = _ctx(handler, write=False)  # no require_write: this only reads
    assert mail.get_message_headers(ctx, ["m1"])["ok"] == 0
    with pytest.raises(ValueError, match="LIST of message ids"):
        mail.get_message_headers(ctx, "m1")
    with pytest.raises(ValueError, match="at most 200"):
        mail.get_message_headers(ctx, [f"m{i}" for i in range(201)])


def test_list_messages_never_asks_for_the_header_bag():
    """CKM-38: the headers are ~10 KB a message. list_messages must not
    carry them, and must not silently fetch them per row either."""
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={"value": [{"id": "m1"}]})

    mail.list_messages(_ctx(handler), top=1)
    assert len(urls) == 1  # one collection GET, not one call per message
    assert "internetMessageHeaders" not in urls[0]
