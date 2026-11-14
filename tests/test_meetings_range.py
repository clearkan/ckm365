"""Offline tests for export_meeting_transcripts: every Teams meeting in a
date range to disk in one call, built on export_transcript's writer.

The case that shaped it is the RECURRING meeting. Every occurrence shares
one join URL and one online meeting, so the meeting's transcript list is
the whole series' history. A naive loop over export_transcript would
download all of it for a one-week range. The range tool writes only parts
created inside the range, while part numbers still count over the whole
list, so a part's file name never depends on which range fetched it.
"""

import httpx
import pytest

from ckm365.config import Profile
from ckm365.graph import Graph
from ckm365.tools import READ, Ctx, meetings, tools_for
from ckm365.tools.mail.bulk import file_stem

WEEKLY = "https://teams.example/l/meetup-join/weekly/0"
ONEOFF = "https://teams.example/l/meetup-join/oneoff/0"
NOBODY = "https://teams.example/l/meetup-join/not-invited/0"
LOCKED = "https://teams.example/l/meetup-join/locked-tenant/0"
EXTERNAL = "https://teams.example/l/meetup-join/other-tenant/0"

MEETINGS = {
    WEEKLY: {"id": "MWeekly", "subject": "Weekly sync",
             "startDateTime": "2026-09-07T01:00:00Z"},
    ONEOFF: {"id": "MOneoff", "subject": "Design review",
             "startDateTime": "2026-11-04T03:00:00Z"},
    LOCKED: {"id": "MLocked", "subject": "Locked tenant",
             "startDateTime": "2026-11-05T03:00:00Z"},
    EXTERNAL: {"id": "MExternal", "subject": "Their meeting",
               "startDateTime": "2026-11-06T01:00:00Z"},
}
TRANSCRIPTS = {
    # three weeks of the series, deliberately out of order
    "MWeekly": [{"id": "w3", "createdDateTime": "2026-11-02T01:05:00Z"},
                {"id": "w1", "createdDateTime": "2026-10-19T01:04:00Z"},
                {"id": "w2", "createdDateTime": "2026-10-26T01:03:00Z"}],
    "MOneoff": [{"id": "o1", "createdDateTime": "2026-11-04T03:02:00Z"}],
}
VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v Alex Doe>Hello.</v>\n"


def _event(eid, url, start, cancelled=False, organiser="ops@tenant-a.example"):
    return {"id": eid, "subject": "s", "isOnlineMeeting": bool(url),
            "organizer": {"emailAddress": {"address": organiser}},
            "onlineMeeting": {"joinUrl": url} if url else None,
            "isCancelled": cancelled,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end": {"dateTime": start, "timeZone": "UTC"}}


EVENTS = [
    _event("e1", WEEKLY, "2026-11-02T01:00:00"),
    _event("e2", ONEOFF, "2026-11-04T03:00:00"),
    _event("e3", WEEKLY, "2026-11-09T01:00:00"),     # same series again
    _event("e4", None, "2026-11-04T05:00:00"),       # not an online meeting
    _event("e5", ONEOFF, "2026-11-06T03:00:00", cancelled=True),
    _event("e6", NOBODY, "2026-11-05T01:00:00"),
    _event("e7", LOCKED, "2026-11-05T03:00:00"),
    _event("e8", EXTERNAL, "2026-11-06T01:00:00",
           organiser="colleague@tenant-b.example"),
]


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return "user@tenant-a.example"


def _ctx(events=EVENTS):
    seen = []

    def handler(request):
        seen.append(request)
        path = request.url.path
        if path.endswith("/calendarView"):
            return httpx.Response(200, json={"value": events})
        if path.endswith("/me/onlineMeetings"):
            url = request.url.params["$filter"].split("'", 1)[1][:-1]
            found = MEETINGS.get(url.replace("''", "'"))
            return httpx.Response(200, json={"value": [found] if found else []})
        if path.endswith(("/MLocked/transcripts", "/MExternal/transcripts")):
            return httpx.Response(403, json={"error": {
                "code": "Forbidden",
                "message": "Graph API access to transcripts is disabled"}})
        if path.endswith("/transcripts"):
            mid = path.split("/onlineMeetings/")[1].split("/")[0]
            return httpx.Response(200, json={"value": TRANSCRIPTS.get(mid, [])})
        if path.endswith("/content"):
            return httpx.Response(200, text=VTT,
                                  headers={"content-type": "text/vtt"})
        raise AssertionError(f"unexpected {request.method} {request.url}")

    ctx = Ctx(profiles={"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1",
        default_mailbox="user@tenant-a.example")})
    ctx.set_graph("tenant-a", Graph(FakeAuth(),
                                    transport=httpx.MockTransport(handler)))
    return ctx, seen


WEEK = ("2026-11-02", "2026-11-09")


def _by_meeting(res):
    return {m["meeting_id"] or m["event_id"]: m for m in res["meetings"]}


def test_a_recurring_meeting_yields_only_the_parts_created_in_range(tmp_path):
    ctx, seen = _ctx()
    res = meetings.export_meeting_transcripts(ctx, str(tmp_path), *WEEK)
    weekly = _by_meeting(res)["MWeekly"]
    assert weekly["outcome"] == "exported"
    # w3 is the series' third transcript, so it keeps part number 3
    assert [(r["transcript_id"], r["part"]) for r in weekly["results"]] == [("w3", 3)]
    stem = file_stem("Weekly sync", "2026-09-07T01:00:00Z", "MWeekly")
    assert sorted(p.name for p in tmp_path.glob(f"{stem}*")) == [
        f"{stem}-transcript-part3.md", f"{stem}-transcript-part3.vtt"]
    # only the in-range parts were downloaded
    content = [r.url.path for r in seen if r.url.path.endswith("/content")]
    assert not any("/w1/" in p or "/w2/" in p for p in content)


def test_each_meeting_reports_an_outcome_and_one_failure_stops_nothing(tmp_path):
    ctx, _ = _ctx()
    res = meetings.export_meeting_transcripts(ctx, str(tmp_path), *WEEK)
    by = _by_meeting(res)
    assert by["MOneoff"]["outcome"] == "exported"
    assert by["e6"]["outcome"] == "not-found"
    # a 403 in our own tenant is a real failure (transcript access off)...
    assert by["MLocked"]["outcome"] == "failed"
    assert "403" in by["MLocked"]["error"]
    # ...but on a meeting organised elsewhere it is the expected answer
    assert by["MExternal"]["outcome"] == "other-tenant"
    assert res["counts"] == {"events": 8, "meetings": 5, "written": 2,
                             "already": 0, "no-transcripts": 0,
                             "not-found": 1, "other-tenant": 1, "failed": 1}


def test_shared_join_urls_cancelled_and_offline_events_are_skipped(tmp_path):
    ctx, seen = _ctx()
    res = meetings.export_meeting_transcripts(ctx, str(tmp_path), *WEEK)
    # e3 repeats the weekly URL, e4 has none, e5 is cancelled
    assert [m["event_id"] for m in res["meetings"]] == ["e1", "e2", "e6", "e7", "e8"]
    lookups = [r for r in seen if r.url.path.endswith("/me/onlineMeetings")]
    assert len(lookups) == 5


def test_a_range_with_no_transcripts_says_so(tmp_path):
    ctx, _ = _ctx()
    res = meetings.export_meeting_transcripts(
        ctx, str(tmp_path), "2026-12-01", "2026-12-08")
    assert _by_meeting(res)["MWeekly"]["outcome"] == "no-transcripts"
    assert res["counts"]["written"] == 0
    assert not list(tmp_path.iterdir())


def test_rerun_writes_nothing_and_says_already(tmp_path):
    ctx, _ = _ctx()
    meetings.export_meeting_transcripts(ctx, str(tmp_path), *WEEK)
    before = sorted(p.name for p in tmp_path.iterdir())
    res = meetings.export_meeting_transcripts(ctx, str(tmp_path), *WEEK)
    assert res["counts"]["written"] == 0 and res["counts"]["already"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_files_match_export_transcript_for_the_same_part(tmp_path):
    """One writer: a part fetched by range is byte-identical to the same
    part fetched by join URL."""
    by_range, by_url = tmp_path / "range", tmp_path / "url"
    by_range.mkdir(), by_url.mkdir()
    ctx, _ = _ctx()
    meetings.export_meeting_transcripts(ctx, str(by_range), *WEEK)
    meetings.export_transcript(ctx, str(by_url), ONEOFF)
    for f in by_range.glob("*design-review*"):
        assert f.read_bytes() == (by_url / f.name).read_bytes()


def test_bad_input_fails_before_any_request(tmp_path, monkeypatch):
    ctx, seen = _ctx()
    with pytest.raises(ValueError, match="before end"):
        meetings.export_meeting_transcripts(ctx, str(tmp_path), "2026-11-09",
                                            "2026-11-02")
    with pytest.raises(ValueError, match="ISO 8601"):
        meetings.export_meeting_transcripts(ctx, str(tmp_path), "last week",
                                            "2026-11-09")
    with pytest.raises(ValueError, match="existing directory"):
        meetings.export_meeting_transcripts(ctx, str(tmp_path / "nope"), *WEEK)
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CKM365_DOWNLOAD_ROOT", str(root))
    with pytest.raises(ValueError, match="outside the download root"):
        meetings.export_meeting_transcripts(ctx, str(tmp_path), *WEEK)
    assert seen == []


def test_registered_read_tier_in_the_meetings_preset_only():
    assert meetings.export_meeting_transcripts in READ["meetings"]
    assert meetings.export_meeting_transcripts in tools_for(["meetings"])
    assert meetings.export_meeting_transcripts not in tools_for(
        ["all"], write=True, send=True)
