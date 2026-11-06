"""Offline spec for export_transcript (kw20z6 gap 2, CKM-44): a Teams
meeting's transcripts to disk in one call, the content never passing
through the agent's context.

Two live pulls hand-rolled this as a scratch script: join URL ->
find_meeting_id -> list transcripts -> VTT content -> a file, then a
hand-written VTT-to-markdown converter. What they learned is the design:

- Fetch EVERY transcript on the meeting, not the newest. One real
  meeting had two because transcription was stopped and restarted;
  "newest only" would have dropped its first 32 minutes. Parts are
  numbered 1..n in creation order and the result reports the count.
- Each part is written twice, side by side: the verbatim `.vtt` and an
  OKF `.md` record. The record has one paragraph per speaker turn,
  `**Name** [hh:mm:ss]` then the text, consecutive cues from the same
  speaker joined, and front matter carrying provenance:
  `transcript_created_utc`, the `.vtt`'s `sha256` and `size`. Downstream
  tools take Teams `.docx` downloads, so the VTT route needs its own
  `.md`.
- Names follow export_messages: `<file_stem(subject, start, meeting
  id)>-transcript-part<N>.vtt|.md`, so they sort by meeting date and are
  stable across runs.
- Read tier, `meetings` preset. Same disk rules as the other exporters:
  `dest_dir` must exist and sits under CKM365_DOWNLOAD_ROOT when set; an
  existing file is never overwritten, it is reported `already`, so a
  rerun after a new part appears writes only the new part.
- Never logs transcript text, speaker names or the subject.

Skipped as a module until meetings.export_transcript exists.
"""

import hashlib

import httpx
import pytest

from ckm365.tools import meetings

if not hasattr(meetings, "export_transcript"):
    pytest.skip("export_transcript not built yet (kw20z6 gap 2)",
                allow_module_level=True)

from ckm365.config import Profile  # noqa: E402
from ckm365.graph import Graph  # noqa: E402
from ckm365.tools import Ctx, READ, tools_for  # noqa: E402
from ckm365.tools.mail.bulk import file_stem  # noqa: E402

JOIN = "https://teams.example/l/meetup-join/19%3ameeting_x%40thread.v2/0"
MEETING = {"id": "MSoMeeting1", "subject": "Re: Q1 review",
           "startDateTime": "2026-10-02T09:00:00Z", "joinWebUrl": JOIN}

VTT_A = """WEBVTT

1a2b/10-0
00:00:03.120 --> 00:00:05.400
<v Alex Doe>Hello everyone.</v>

1a2b/11-0
00:00:05.900 --> 00:00:08.000
<v Alex Doe>Shall we start?</v>

1a2b/12-0
00:01:02.000 --> 00:01:04.500
<v Sam Roe>Yes, go ahead.</v>

1a2b/13-0
01:02:03.250 --> 01:02:05.000
Unattributed line.
"""

VTT_B = """WEBVTT

00:00:01.000 --> 00:00:02.000
<v Sam Roe>Back again.</v>
"""


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return "user@tenant-a.example"


def _ctx(*, meetings_found=(MEETING,), transcripts=None, contents=None):
    """transcripts: Graph rows, deliberately NOT in creation order."""
    transcripts = transcripts if transcripts is not None else [
        {"id": "trB", "createdDateTime": "2026-10-02T09:45:00Z"},
        {"id": "trA", "createdDateTime": "2026-10-02T09:04:00Z"}]
    contents = contents or {"trA": VTT_A, "trB": VTT_B}
    seen = []

    def handler(request):
        seen.append(request)
        path = request.url.path
        if path.endswith("/me/onlineMeetings"):
            return httpx.Response(200, json={"value": list(meetings_found)})
        if path.endswith("/transcripts"):
            return httpx.Response(200, json={"value": transcripts})
        if path.endswith("/content"):
            tid = path.split("/transcripts/")[1].split("/")[0]
            assert request.url.params.get("$format") == "text/vtt"
            return httpx.Response(200, text=contents[tid],
                                  headers={"content-type": "text/vtt"})
        raise AssertionError(f"unexpected {request.method} {request.url}")

    ctx = Ctx(profiles={"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1",
        default_mailbox="user@tenant-a.example")})
    ctx.set_graph("tenant-a", Graph(FakeAuth(),
                                    transport=httpx.MockTransport(handler)))
    return ctx, seen


STEM = file_stem(MEETING["subject"], MEETING["startDateTime"], MEETING["id"])


def front(text):
    head = text.partition("\n---\n")[0].splitlines()[1:]
    return dict(line.split(": ", 1) for line in head)


# --- the happy path -----------------------------------------------------------

def test_every_part_is_written_in_creation_order(tmp_path):
    ctx, _ = _ctx()
    res = meetings.export_transcript(ctx, str(tmp_path), JOIN)
    assert res["meeting_id"] == "MSoMeeting1"
    assert res["parts"] == 2
    assert [p["transcript_id"] for p in res["results"]] == ["trA", "trB"]
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [f"{STEM}-transcript-part1.md", f"{STEM}-transcript-part1.vtt",
                     f"{STEM}-transcript-part2.md", f"{STEM}-transcript-part2.vtt"]
    assert STEM.startswith("20261002_q1-review_")
    assert all(p["outcome"] == "written" for p in res["results"])


def test_vtt_is_verbatim(tmp_path):
    ctx, _ = _ctx()
    meetings.export_transcript(ctx, str(tmp_path), JOIN)
    assert (tmp_path / f"{STEM}-transcript-part1.vtt").read_text(
        encoding="utf-8") == VTT_A


def test_markdown_joins_turns_and_carries_provenance(tmp_path):
    ctx, _ = _ctx()
    meetings.export_transcript(ctx, str(tmp_path), JOIN)
    text = (tmp_path / f"{STEM}-transcript-part1.md").read_text(encoding="utf-8")
    fm = front(text)
    raw = VTT_A.encode("utf-8")
    assert fm["type"] == '"Transcript"'
    assert fm["channel"] == '"teams-meeting"'
    assert fm["title"] == '"Re: Q1 review"'
    assert fm["meeting_id"] == '"MSoMeeting1"'
    assert fm["transcript_id"] == '"trA"'
    assert fm["part"] == "1" and fm["parts"] == "2"
    assert fm["transcript_created_utc"] == '"2026-10-02T09:04:00Z"'
    assert fm["sha256"] == f'"{hashlib.sha256(raw).hexdigest()}"'
    assert fm["size"] == str(len(raw))
    assert fm["speakers"] == '["Alex Doe", "Sam Roe"]'

    body = text.partition("\n---\n")[2]
    assert "**Alex Doe** [00:00:03]\nHello everyone. Shall we start?" in body
    assert "**Sam Roe** [00:01:02]\nYes, go ahead." in body
    assert "**(unattributed)** [01:02:03]\nUnattributed line." in body
    assert "<v " not in body and "-->" not in body
    assert body.index("Alex Doe") < body.index("Sam Roe") < body.index("Unattributed")


def test_rerun_writes_nothing_new_and_says_already(tmp_path):
    ctx, _ = _ctx()
    meetings.export_transcript(ctx, str(tmp_path), JOIN)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    res = meetings.export_transcript(ctx, str(tmp_path), JOIN)
    assert [p["outcome"] for p in res["results"]] == ["already", "already"]
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_a_new_part_is_the_only_thing_written_on_rerun(tmp_path):
    ctx, _ = _ctx(transcripts=[{"id": "trA",
                                "createdDateTime": "2026-10-02T09:04:00Z"}])
    meetings.export_transcript(ctx, str(tmp_path), JOIN)
    ctx, seen = _ctx()
    res = meetings.export_transcript(ctx, str(tmp_path), JOIN)
    assert [p["outcome"] for p in res["results"]] == ["already", "written"]
    # an `already` part is not downloaded again
    assert [r.url.path.split("/transcripts/")[1].split("/")[0]
            for r in seen if r.url.path.endswith("/content")] == ["trB"]


# --- the edges ----------------------------------------------------------------

def test_no_transcripts_is_an_empty_result_not_an_error(tmp_path):
    ctx, _ = _ctx(transcripts=[])
    res = meetings.export_transcript(ctx, str(tmp_path), JOIN)
    assert res["parts"] == 0 and res["results"] == []
    assert list(tmp_path.iterdir()) == []


def test_unresolvable_meeting_is_an_error_naming_the_cause(tmp_path):
    ctx, _ = _ctx(meetings_found=())
    with pytest.raises(ValueError, match="invite"):
        meetings.export_transcript(ctx, str(tmp_path), JOIN)


@pytest.mark.parametrize("join_url", ["", "   "])
def test_join_url_required_before_any_request(tmp_path, join_url):
    ctx, seen = _ctx()
    with pytest.raises(ValueError, match="join_url"):
        meetings.export_transcript(ctx, str(tmp_path), join_url)
    assert seen == []


def test_dest_dir_must_exist_and_respect_the_root(tmp_path, monkeypatch):
    ctx, seen = _ctx()
    with pytest.raises(ValueError):
        meetings.export_transcript(ctx, str(tmp_path / "missing"), JOIN)
    monkeypatch.setenv("CKM365_DOWNLOAD_ROOT", str(tmp_path / "root"))
    (tmp_path / "root").mkdir()
    (tmp_path / "elsewhere").mkdir()
    with pytest.raises(ValueError, match="outside the download root"):
        meetings.export_transcript(ctx, str(tmp_path / "elsewhere"), JOIN)
    assert seen == []


def test_meeting_without_subject_still_gets_a_stable_name(tmp_path):
    bare = {"id": "MSoMeeting2", "startDateTime": "2026-10-03T10:00:00Z"}
    ctx, _ = _ctx(meetings_found=(bare,))
    meetings.export_transcript(ctx, str(tmp_path), JOIN)
    assert (tmp_path / (file_stem(None, bare["startDateTime"], bare["id"])
                        + "-transcript-part1.vtt")).exists()


def test_vtt_without_voice_tags_or_cue_ids_still_converts():
    md = meetings.vtt_turns("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhi\n\n"
                            "00:00:02.500 --> 00:00:03.000\nthere\n")
    # unattributed cues are not merged: with no speaker, the timing is the
    # only structure left (Fable review, 2026-11-07)
    assert md == [("", "00:00:01", "hi"), ("", "00:00:02", "there")]


def test_voice_tags_with_classes():
    assert meetings.vtt_turns("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
                              "<v.loud Bob>shout</v>\n") == [("Bob", "00:00:01", "shout")]


def test_vtt_turns_split_on_speaker_change():
    turns = meetings.vtt_turns(VTT_A)
    assert turns == [("Alex Doe", "00:00:03", "Hello everyone. Shall we start?"),
                     ("Sam Roe", "00:01:02", "Yes, go ahead."),
                     ("", "01:02:03", "Unattributed line.")]


# --- registration ---------------------------------------------------------------

def test_registered_read_tier_in_the_meetings_preset_only():
    assert meetings.export_transcript in READ["meetings"]
    assert meetings.export_transcript in tools_for(["meetings"])
    assert meetings.export_transcript not in tools_for(
        ["all"], write=True, send=True)
