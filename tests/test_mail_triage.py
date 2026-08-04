"""Offline tests for the mail triage slice — no tenant, no network.

CKM-33 read state, CKM-34 flags, CKM-35 server-side filtering + transient
retry + group_by_sender, CKM-36 move. Fixtures are fake ids and
*.example addresses throughout.
"""

import json

import httpx
import pytest

from ckm365.config import ConfigError, Profile
from ckm365.graph import Graph, GraphError
from ckm365.tools import Ctx, WriteDisabled, mail


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return "user@tenant-a.example"


def _ctx(handler, *, write=True, **profile_kw):
    profiles = {"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1",
        default_mailbox="user@tenant-a.example", **profile_kw)}
    ctx = Ctx(profiles=profiles, write_enabled=write)
    ctx.set_graph("tenant-a", Graph(
        FakeAuth(), transport=httpx.MockTransport(handler)))
    return ctx


def _batch_recorder(status_for=None, body_for=None):
    """A /$batch handler recording every sub-request payload it is sent."""
    sent = []

    def handler(request):
        payload = json.loads(request.content)
        sent.append(payload["requests"])
        return httpx.Response(200, json={"responses": [
            {"id": r["id"],
             "status": (status_for or {}).get(r["url"].rsplit("/", 1)[-1], 200)
             if not r["url"].endswith("/move")
             else (status_for or {}).get(r["url"].split("/")[-2], 200),
             "body": (body_for or {}).get(r["id"])}
            for r in reversed(payload["requests"])]})  # Graph answers unordered

    return handler, sent


# --- read state (CKM-33) ---------------------------------------------------

def test_mark_read_and_unread_batch_one_patch_per_id():
    handler, sent = _batch_recorder()
    ctx = _ctx(handler)
    res = mail.mark_read(ctx, ["m1", "m2"])
    assert res == {"ok": 2, "failed": []}
    assert [r["method"] for r in sent[0]] == ["PATCH", "PATCH"]
    assert [r["body"] for r in sent[0]] == [{"isRead": True}, {"isRead": True}]
    assert sent[0][0]["url"] == "/users/user%40tenant-a.example/messages/m1"

    mail.mark_unread(ctx, ["m1"])
    assert sent[1][0]["body"] == {"isRead": False}


def test_partial_failure_reports_per_id_and_keeps_going():
    handler, _ = _batch_recorder(
        status_for={"m2": 404},
        body_for={"1": {"error": {"code": "ErrorItemNotFound",
                                  "message": "moved out from under us"}}})
    res = mail.mark_read(_ctx(handler), ["m1", "m2", "m3"])
    assert res["ok"] == 2  # the 404 did not strand the other two
    assert res["failed"] == [{"id": "m2",
                              "error": "404 ErrorItemNotFound moved out "
                                       "from under us"}]


def test_batches_are_chunked_at_graphs_limit_of_20():
    handler, sent = _batch_recorder()
    res = mail.mark_read(_ctx(handler), [f"m{i}" for i in range(45)])
    assert [len(chunk) for chunk in sent] == [20, 20, 5]
    assert res["ok"] == 45


def test_ids_are_validated_deduplicated_and_capped():
    handler, sent = _batch_recorder()
    ctx = _ctx(handler)
    assert mail.mark_read(ctx, ["m1", "m1", " m1 "])["ok"] == 1
    assert len(sent[0]) == 1
    with pytest.raises(ValueError, match="LIST of message ids"):
        mail.mark_read(ctx, "m1")
    with pytest.raises(ValueError, match="empty"):
        mail.mark_read(ctx, [])
    with pytest.raises(ValueError, match="message_id"):
        mail.mark_read(ctx, ["m1", "   "])
    with pytest.raises(ValueError, match="at most 200"):
        mail.mark_read(ctx, [f"m{i}" for i in range(201)])


def test_throttled_sub_requests_are_resent_once(monkeypatch):
    monkeypatch.setattr("ckm365.graph.time.sleep", lambda _: None)
    attempts = []

    def handler(request):
        payload = json.loads(request.content)
        attempts.append([r["url"] for r in payload["requests"]])
        first = len(attempts) == 1
        return httpx.Response(200, json={"responses": [
            {"id": r["id"], "status": 429 if first and r["id"] == "1" else 200}
            for r in payload["requests"]]})

    assert mail.mark_read(_ctx(handler), ["m1", "m2"]) == {"ok": 2, "failed": []}
    assert len(attempts) == 2                     # only the throttled one
    assert attempts[1] == ["/users/user%40tenant-a.example/messages/m2"]


def test_triage_tools_are_write_gated():
    handler, _ = _batch_recorder()
    ro = _ctx(handler, write=False)
    for call in (lambda: mail.mark_read(ro, ["m1"]),
                 lambda: mail.mark_unread(ro, ["m1"]),
                 lambda: mail.flag(ro, ["m1"]),
                 lambda: mail.unflag(ro, ["m1"]),
                 lambda: mail.complete_flag(ro, ["m1"]),
                 lambda: mail.move_message(ro, ["m1"], "archive")):
        with pytest.raises(WriteDisabled):
            call()


# --- flags (CKM-34) --------------------------------------------------------

def test_flag_without_a_date_is_the_default():
    handler, sent = _batch_recorder()
    res = mail.flag(_ctx(handler), ["m1"])
    assert sent[0][0]["body"] == {"flag": {"flagStatus": "flagged"}}
    assert res == {"ok": 1, "failed": [], "timezone": None}


def test_unflag_and_complete_are_different_outcomes():
    handler, sent = _batch_recorder()
    ctx = _ctx(handler)
    mail.unflag(ctx, ["m1"])
    assert sent[0][0]["body"] == {"flag": {"flagStatus": "notFlagged"}}
    mail.complete_flag(ctx, ["m1"])
    completed = sent[1][0]["body"]["flag"]
    assert completed["flagStatus"] == "complete"
    assert completed["completedDateTime"]["timeZone"] == "UTC"


def test_flag_due_gets_a_start_and_reports_the_zone_used():
    handler, sent = _batch_recorder()
    res = mail.flag(_ctx(handler), ["m1"], due="2026-08-10T17:00:00",
                    timezone="Europe/London")
    body = sent[0][0]["body"]["flag"]
    assert body["dueDateTime"] == {"dateTime": "2026-08-10T17:00:00",
                                   "timeZone": "Europe/London"}
    # Graph wants a start alongside a due date — defaulted, not refused.
    assert body["startDateTime"]["timeZone"] == "UTC"
    assert res["timezone"] == "Europe/London"


def test_offset_bearing_dates_normalise_to_utc():
    handler, sent = _batch_recorder()
    res = mail.flag(_ctx(handler), ["m1"], due="2026-08-10T17:00:00+01:00")
    assert sent[0][0]["body"]["flag"]["dueDateTime"] == {
        "dateTime": "2026-08-10T16:00:00", "timeZone": "UTC"}
    assert res["timezone"] == "UTC"


def test_bare_date_never_silently_becomes_utc():
    """A flag due 'today' in the wrong zone is wrong by up to a day, so an
    unresolvable zone is an error rather than a guess (CKM-34)."""
    handler, sent = _batch_recorder()
    with pytest.raises(ValueError, match="carries no timezone"):
        mail.flag(_ctx(handler), ["m1"], due="2026-08-10")
    assert sent == []  # nothing was sent to Graph
    with pytest.raises(ValueError, match="ISO 8601"):
        mail.flag(_ctx(handler), ["m1"], due="next tuesday",
                  timezone="Europe/London")
    with pytest.raises(ValueError, match="invalid timezone"):
        mail.flag(_ctx(handler), ["m1"], due="2026-08-10", timezone="a\nb")


def test_profile_timezone_is_the_default_zone():
    handler, sent = _batch_recorder()
    ctx = _ctx(handler, timezone="Europe/London")
    assert mail.flag(ctx, ["m1"], due="2026-08-10")["timezone"] == "Europe/London"
    assert sent[0][0]["body"]["flag"]["dueDateTime"]["timeZone"] == "Europe/London"


def test_profile_timezone_is_validated_at_load():
    with pytest.raises(ConfigError, match="timezone"):
        Profile(name="p", tenant_id="t", client_id="c", timezone="bad\nzone")


# --- move (CKM-36) ---------------------------------------------------------

def _move_ctx(folders=("Archive", "Projects"), known=("archive",)):
    sent = []

    def handler(request):
        if request.url.path.endswith("/$batch"):
            payload = json.loads(request.content)
            sent.append(payload["requests"])
            return httpx.Response(200, json={"responses": [
                {"id": r["id"], "status": 201,
                 "body": {"id": f"new-{r['id']}"}}
                for r in payload["requests"]]})
        if "/mailFolders/" in request.url.path:
            name = request.url.path.rsplit("/", 1)[-1]
            if name.lower() not in known:
                return httpx.Response(404, json={"error": {
                    "code": "ErrorItemNotFound", "message": "no such folder"}})
            return httpx.Response(200, json={"id": name})
        return httpx.Response(200, json={"value": [
            {"id": f"f{i}", "displayName": n} for i, n in enumerate(folders)]})

    return _ctx(handler), sent


def test_move_returns_the_new_id_mapping():
    ctx, sent = _move_ctx()
    res = mail.move_message(ctx, ["m1", "m2"], "archive")
    assert res["moved"] == {"m1": "new-0", "m2": "new-1"}
    assert res["ok"] == 2 and res["destination"] == "archive"
    assert [r["method"] for r in sent[0]] == ["POST", "POST"]
    assert sent[0][0]["url"].endswith("/messages/m1/move")
    assert sent[0][0]["body"] == {"destinationId": "archive"}


def test_unknown_destination_errors_without_creating_anything():
    ctx, sent = _move_ctx()
    with pytest.raises(ValueError) as err:
        mail.move_message(ctx, ["m1"], "Projcts")
    assert "never creates folders" in str(err.value)
    assert "Archive, Projects" in str(err.value)  # names the real ones
    assert sent == []  # and moved nothing


def test_move_requires_a_destination():
    ctx, _ = _move_ctx()
    with pytest.raises(ValueError, match="destination is required"):
        mail.move_message(ctx, ["m1"], "  ")


# --- server-side filtering (CKM-35) ----------------------------------------

def _url_ctx(items=()):
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={"value": list(items)})

    return _ctx(handler, write=False), urls


def test_predicates_compose_into_one_server_side_filter():
    ctx, urls = _url_ctx()
    mail.list_messages(ctx, unread_only=True, flagged_only=True,
                       since="2026-08-01", from_address="ops@tenant-b.example")
    query = httpx.URL(urls[0]).params["$filter"]
    assert query == ("isRead eq false and flag/flagStatus eq 'flagged' and "
                     "receivedDateTime ge 2026-08-01T00:00:00Z and "
                     "from/emailAddress/address eq 'ops@tenant-b.example'")
    assert "$orderby" not in urls[0]  # a filter drops Graph's ordering


def test_raw_filter_composes_with_predicates_rather_than_competing():
    ctx, urls = _url_ctx()
    mail.list_messages(ctx, unread_only=True, filter="hasAttachments eq true")
    assert httpx.URL(urls[0]).params["$filter"] == \
        "isRead eq false and (hasAttachments eq true)"


def test_from_address_quotes_are_escaped_into_the_odata_literal():
    ctx, urls = _url_ctx()
    mail.list_messages(ctx, from_address="o'brien@tenant-b.example")
    assert httpx.URL(urls[0]).params["$filter"] == \
        "from/emailAddress/address eq 'o''brien@tenant-b.example'"


def test_since_accepts_dates_and_datetimes_and_rejects_junk():
    ctx, urls = _url_ctx()
    mail.list_messages(ctx, since="2026-08-01T09:30:00+02:00")
    assert "2026-08-01T07:30:00Z" in httpx.URL(urls[0]).params["$filter"]
    with pytest.raises(ValueError, match="ISO 8601"):
        mail.list_messages(ctx, since="last tuesday")


def test_search_and_predicates_are_mutually_exclusive():
    ctx, _ = _url_ctx()
    with pytest.raises(ValueError, match="search cannot be combined"):
        mail.list_messages(ctx, search="invoice", unread_only=True)
    with pytest.raises(ValueError, match="search cannot be combined"):
        mail.list_messages(ctx, search="invoice", filter="isRead eq false")


def test_unfiltered_list_still_asks_for_newest_first():
    ctx, urls = _url_ctx()
    mail.list_messages(ctx)
    assert httpx.URL(urls[0]).params["$orderby"] == "receivedDateTime desc"


def test_transient_503_is_retried_past_the_throttling_budget(monkeypatch):
    """The CKM-35 incident: a filtered list 503'd with
    ErrorInternalServerTransientError on a large mailbox and surfaced as a
    hard failure because three sub-second retries fell inside one blip."""
    monkeypatch.setattr("ckm365.graph.time.sleep", lambda _: None)
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) <= 4:
            return httpx.Response(503, json={"error": {
                "code": "ErrorInternalServerTransientError",
                "message": "Cannot query rows in a table"}})
        return httpx.Response(200, json={"value": []})

    ctx, _ = _ctx(handler, write=False), None
    assert mail.list_messages(ctx, unread_only=True) == []
    assert len(attempts) == 5


def test_transient_retries_are_still_bounded(monkeypatch):
    monkeypatch.setattr("ckm365.graph.time.sleep", lambda _: None)
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(503, json={"error": {
            "code": "ErrorInternalServerTransientError", "message": "no"}})

    with pytest.raises(GraphError) as err:
        mail.list_messages(_ctx(handler, write=False), unread_only=True)
    assert err.value.status == 503
    assert len(attempts) == 6  # initial + 5 retries, then it surfaces


# --- group_by_sender (CKM-35) ----------------------------------------------

def _sender_page(*senders):
    return [{"from": {"emailAddress": {"address": a, "name": n}},
             "isRead": read} for a, n, read in senders]


def test_group_by_sender_counts_totals_and_unread_without_message_content():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={"value": _sender_page(
            ("noreply@tenant-b.example", "Robot", False),
            ("noreply@tenant-b.example", "Robot", True),
            ("NoReply@Tenant-B.example", "Robot", False),
            ("colleague@tenant-a.example", "Colleague", True))})

    res = mail.group_by_sender(_ctx(handler, write=False), max_scan=4)
    assert res["senders"] == [
        {"address": "noreply@tenant-b.example", "name": "Robot",
         "total": 3, "unread": 2},
        {"address": "colleague@tenant-a.example", "name": "Colleague",
         "total": 1, "unread": 0}]
    assert res["scanned"] == 4 and res["truncated"] is True
    params = httpx.URL(urls[0]).params
    assert params["$select"] == "from,isRead"  # no subject, preview or body


def test_group_by_sender_reports_an_untruncated_walk_and_pushes_since():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={"value": _sender_page(
            ("ops@tenant-b.example", "Ops", True))})

    res = mail.group_by_sender(_ctx(handler, write=False),
                               folder="archive", since="2026-08-01")
    assert res["truncated"] is False and res["scanned"] == 1
    assert res["folder"] == "archive" and res["since"] == "2026-08-01"
    assert httpx.URL(urls[0]).params["$filter"] == \
        "receivedDateTime ge 2026-08-01T00:00:00Z"


def test_group_by_sender_caps_the_scan():
    ctx, _ = _url_ctx()
    with pytest.raises(ValueError, match="max_scan"):
        mail.group_by_sender(ctx, max_scan=0)
    with pytest.raises(ValueError, match="max_scan"):
        mail.group_by_sender(ctx, max_scan=10001)


def test_group_by_sender_is_read_tier():
    """No require_write: counting is a read, and triage starts here."""
    def handler(request):
        return httpx.Response(200, json={"value": []})

    assert mail.group_by_sender(_ctx(handler, write=False))["senders"] == []
