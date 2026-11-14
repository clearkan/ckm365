"""Meeting transcript retrieval over Graph — read-only, no bot, no media.

The deliberate non-goal (CKM-28/CKM-30): this does NOT join meetings or
capture audio. Real-time media requires the .NET media library, a Windows
Server VM in Azure with a public IP per instance, and a platform still in
developer preview — none of which belongs in a Python Graph client.
Transcript retrieval gets most of the same value over plain REST, and the
old per-minute transcript meter was removed on 2025-08-25.

Two tenant gates, both admin-only, both worth knowing before debugging a
403:

- `OnlineMeetingTranscript.Read.All` is admin-consent-required BY
  DEFINITION — no tenant setting opens it to user consent
  (scripts/add-transcript-scopes.sh grants it where we are admin).
- Separately, Teams has a tenant kill-switch: "Transcript API access →
  Microsoft Graph access". It defaults to OFF and has been ENFORCED since
  2026-07-29, so a correctly-consented app still gets
  403 "Graph API access to transcripts is disabled for this tenant"
  until an admin turns it on. That is a Teams admin setting, not a Graph
  permission — see docs/usage-modes.md.

Scope of what you can read: transcripts of meetings the signed-in user
organised OR is on the calendar invite for, IN THE USER'S OWN TENANT. A
meeting organised in another tenant resolves from its join URL but its
transcript list answers 403 (measured 2026-11-08: 3 of 3 external-
organiser meetings, against 14 of 14 same-tenant ones that worked); only
the organiser's tenant serves it. Someone must have actually
started transcription, and transcripts land at or after the meeting ends
— this is meeting CONTENT after the fact, never a live feed.

Transcript text is sensitive in exactly the way mail bodies are: it is
returned to the caller but never logged, and the smoke scripts print
lengths and ids only.
"""

import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from .. import __version__
from ..graph import Graph, GraphError, encode_segment as _seg
from ..models import Transcript
from .calendar import list_events
from .context import Ctx, pull
from .mail.bulk import file_stem
from .mail.disk import confine, write_atomic, write_target
from .mail.export import _yaml_value

log = logging.getLogger("ckm365")

# Graph's own formats for transcript content; VTT carries timings and
# (when the tenant enables attribution) speaker names.
_FORMATS = ("text/vtt", "text/plain")


def _meeting_path(meeting_id: str) -> str:
    return f"/me/onlineMeetings/{_seg(meeting_id, 'meeting_id')}"


def _find_meeting(g: Graph, join_url: str) -> dict | None:
    # $filter on JoinWebUrl is the documented lookup; the URL is passed as
    # an OData string literal, so single quotes must be doubled.
    quoted = join_url.replace("'", "''")
    found = g.get("/me/onlineMeetings",
                  params={"$filter": f"JoinWebUrl eq '{quoted}'"})
    values = found.get("value") or []
    return values[0] if values else None


def find_meeting_id(ctx: Ctx, join_url: str, *,
                    account: str | None = None) -> str | None:
    """Resolve a Teams join URL to the online-meeting id the transcript
    tools need. Get the join URL from list_events/get_event (an event's
    join_url field). Returns None when the meeting cannot be resolved —
    typically because the signed-in user was not on its invite.
    """
    if not (join_url or "").strip():
        raise ValueError("join_url is required")
    meeting = _find_meeting(ctx.graph(account), join_url)
    return meeting.get("id") if meeting else None


def list_meeting_transcripts(ctx: Ctx, meeting_id: str, *, top: int = 20,
                             account: str | None = None) -> list[Transcript]:
    """List the transcripts available for one online meeting.

    meeting_id comes from find_meeting_id (via a calendar event's join
    URL). Returns transcript ids and creation times — not the text; pass
    an id to get_meeting_transcript for that. An empty list means nobody
    started transcription, which is common.
    """
    if not 1 <= top <= 100:
        raise ValueError("top must be between 1 and 100")
    g = ctx.graph(account)
    return pull(g, Transcript,
                f"{_meeting_path(meeting_id)}/transcripts",
                params={}, top=top)


def get_meeting_transcript(ctx: Ctx, meeting_id: str, transcript_id: str, *,
                           text_format: str = "text/vtt",
                           account: str | None = None) -> dict:
    """Fetch the text of one meeting transcript.

    text_format is 'text/vtt' (default — timings, plus speaker names when
    the tenant enables attribution) or 'text/plain'. Returns
    {"meeting_id", "transcript_id", "format", "content"}. The content is
    the verbatim meeting record: treat it as sensitive, and never echo it
    into logs or issue trackers wholesale.
    """
    if text_format not in _FORMATS:
        raise ValueError(f"text_format must be one of {_FORMATS}")
    g = ctx.graph(account)
    path = (f"{_meeting_path(meeting_id)}"
            f"/transcripts/{_seg(transcript_id, 'transcript_id')}/content")
    return {
        "meeting_id": meeting_id,
        "transcript_id": transcript_id,
        "format": text_format,
        "content": g.content(path, params={"$format": text_format}),
    }


def vtt_turns(vtt: str) -> list[tuple[str, str, str]]:
    """Project VTT cues into speaker turns, keeping each turn's first start."""
    turns: list[tuple[str, str, str]] = []
    for block in re.split(r"\n\s*\n", vtt.replace("\r\n", "\n").strip()):
        lines = block.splitlines()
        if not lines or re.match(r"NOTE(?:\s|$)", lines[0]):
            continue
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None or timing + 1 == len(lines):
            continue
        start = lines[timing].split()[0].split(".")[0]
        if start.count(":") == 1:
            start = "00:" + start
        text = " ".join(line.strip() for line in lines[timing + 1:])
        voice = re.search(r"<v(?:\.[^\s>]*)?\s+([^>]+)>", text)
        speaker = voice.group(1).strip() if voice else ""
        text = re.sub(r"<v(?:\.[^\s>]*)?\s+[^>]+>|</v>", "", text).strip()
        if speaker and turns and turns[-1][0] == speaker:  # unattributed cues keep their own timings
            turns[-1] = (speaker, turns[-1][1], turns[-1][2] + " " + text)
        else:
            turns.append((speaker, start, text))
    return turns


def _transcript_record(vtt: str, meeting: dict, transcript: Transcript,
                       part: int, parts: int) -> bytes:
    raw = vtt.encode("utf-8")
    title = meeting.get("subject") or "(no subject)"
    turns = vtt_turns(vtt)
    speakers = list(dict.fromkeys(speaker for speaker, _, _ in turns if speaker))
    front = {
        "type": "Transcript",
        "channel": "teams-meeting",
        "title": title,
        "description": f"Teams meeting transcript, part {part} of {parts}",
        "tags": ["transcript", "teams"],
        "generated": {"by": f"ckm365/{__version__}", "at": transcript.created},
        "meeting_id": meeting["id"],
        "transcript_id": transcript.id,
        "part": part,
        "parts": parts,
        "transcript_created_utc": transcript.created,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
        "speakers": speakers,
    }
    lines = ["---", *(f"{k}: {_yaml_value(v)}" for k, v in front.items()),
             "---", "", f"# {title}"]
    for speaker, start, text in turns:
        lines += ["", f"**{speaker or '(unattributed)'}** [{start}]", text]
    return ("\n".join(lines) + "\n").encode("utf-8")


def export_transcript(ctx: Ctx, dest_dir: str, join_url: str, *,
                      account: str | None = None) -> dict:
    """Save every transcript of a Teams meeting in one call.

    Give the join URL from a calendar event and an existing directory;
    this replaces the lookup/list/download/scratch-script flow. ALL parts
    are exported in creation order: stopping and restarting transcription
    makes separate parts, and taking only the newest loses earlier speech.

    Each part becomes a verbatim UTF-8 .vtt and an Open Knowledge Format
    .md record with speaker turns, timings and provenance (ids, creation
    time, VTT hash and size). Names are a meeting date, subject slug and
    stable id token followed by -transcript-part<N>.vtt or .md.
    Returns filenames and outcomes, never transcript content.

    Reruns leave existing files alone; a complete pair is `already` and
    is not downloaded. A missing file is filled in and new parts are
    `written`. Read tier; the tenant gates and invite requirements in
    this module's docstring still apply.

    Same disk rules as export_message: dest_dir must exist, writes are
    atomic, and CKM365_DOWNLOAD_ROOT (or CKM365_ATTACH_ROOT) confines them.
    The root defaults to ~/.local/share/ckm365 (or $XDG_DATA_HOME/ckm365).
    Content goes straight to disk and never enters your context unless
    you read it back. Logs contain only the meeting id and counts.
    """
    if not (join_url or "").strip():
        raise ValueError("join_url is required")
    dest = _dest(dest_dir)
    g = ctx.graph(account)
    meeting = _find_meeting(g, join_url)
    if not meeting:
        raise ValueError("no online meeting found for that join_url: the "
                         "signed-in user must be its organiser or on its invite")
    meeting_id = meeting["id"]
    parts, results = _export_parts(g, dest, meeting)
    written = sum(result["outcome"] == "written" for result in results)
    log.info("tool=export_transcript meeting_id=%r parts=%d written=%d already=%d",
             meeting_id, parts, written, parts - written)
    return {"dir": str(dest), "meeting_id": meeting_id,
            "parts": parts, "results": results}


def _dest(dest_dir: str) -> Path:
    dest = confine(Path(dest_dir), "dest_dir")
    if not dest.is_dir():
        raise ValueError("dest_dir must be an existing directory")
    return dest


def _export_parts(g: Graph, dest: Path, meeting: dict,
                  window: tuple[datetime, datetime] | None = None
                  ) -> tuple[int, list[dict]]:
    """Write a meeting's transcript parts; return (part count, results).

    Parts are numbered over ALL the meeting's transcripts, so a part keeps
    its number and file name whether or not a window selects it. window
    (UTC, end exclusive) limits which parts are written and reported.
    """
    meeting_id = meeting["id"]
    transcripts = pull(g, Transcript, f"{_meeting_path(meeting_id)}/transcripts",
                       params={}, top=100)
    transcripts.sort(key=lambda transcript: transcript.created or "")
    parts = len(transcripts)
    stem = file_stem(meeting.get("subject"), meeting.get("startDateTime"), meeting_id)
    results = []
    for part, transcript in enumerate(transcripts, 1):
        if window and not (window[0] <= _utc(transcript.created or "")
                           < window[1]):
            continue
        vtt_path = dest / f"{stem}-transcript-part{part}.vtt"
        md_path = dest / f"{stem}-transcript-part{part}.md"
        outcome = "already"
        if not (vtt_path.exists() and md_path.exists()):
            path = (f"{_meeting_path(meeting_id)}/transcripts/"
                    f"{_seg(transcript.id, 'transcript_id')}/content")
            vtt = g.content(path, params={"$format": "text/vtt"})
            for target in (vtt_path, md_path):
                if target.exists():
                    continue
                target = write_target(str(target), None)
                data = (vtt.encode("utf-8") if target.suffix == ".vtt" else
                        _transcript_record(vtt, meeting, transcript, part, parts))
                write_atomic(target, lambda pending: pending.write_bytes(data))
            outcome = "written"
        results.append({"part": part, "transcript_id": transcript.id,
                        "created": transcript.created, "vtt": vtt_path.name,
                        "md": md_path.name, "outcome": outcome})
    return parts, results


def _utc(value: str) -> datetime:
    """An ISO date or datetime as aware UTC; no offset is read as UTC,
    which is also how Graph's calendarView reads it."""
    try:
        dt = datetime.fromisoformat((value or "").strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"not an ISO 8601 date or datetime: {value!r}") from exc
    return (dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt).astimezone(UTC)


def export_meeting_transcripts(ctx: Ctx, dest_dir: str, start: str, end: str, *,
                               account: str | None = None) -> dict:
    """Save the transcripts of every Teams meeting in a date range.

    The one call for "get me this week's transcripts": it reads the
    signed-in user's calendar between start and end (ISO 8601; no offset
    means UTC), takes each online meeting's join URL, and writes its
    transcripts exactly as export_transcript does — the same .vtt and .md
    pair per part, the same names, the same skip-what-is-there reruns.

    ONLY TRANSCRIPTS CREATED IN THE RANGE are written. This matters for
    recurring meetings: every occurrence shares one join URL and one
    online meeting, so the meeting's transcript list holds the whole
    series' history. Part numbers count over that whole list, so a part
    keeps the same file name whichever range fetched it.

    One meeting failing never stops the rest. Each meeting reports an
    outcome: `exported` (with its files), `no-transcripts` in the range
    (common: nobody started transcription, or it is still processing,
    since transcripts land at or after the meeting ends), `not-found` (the
    join URL did not resolve: the user must be the organiser or on the
    invite), `other-tenant` (a 403 on a meeting whose organiser's domain
    differs from the mailbox's: only the organiser's tenant serves its
    transcript, so fetch it from an account there), or `failed` with the
    Graph error, e.g. a 403 from this tenant when its admin has not
    enabled transcript access (see this module's docstring). Cancelled
    events and events with no join URL are skipped.

    Read tier, meetings preset. Same disk rules as export_transcript:
    dest_dir must exist and sits under CKM365_DOWNLOAD_ROOT when set.
    Returns file names and outcomes, never transcript text or subjects.
    """
    dest = _dest(dest_dir)
    window = (_utc(start), _utc(end))
    if window[0] >= window[1]:
        raise ValueError("start must be before end")
    g, mailbox = ctx.target(account, None)
    home = mailbox.rpartition("@")[2].lower()
    events = list_events(ctx, start=start, end=end, top=500, account=account)
    seen, meetings = set(), []
    for event in events:
        url = event.join_url
        if event.is_cancelled or not url or url in seen:
            continue
        seen.add(url)
        entry = {"event_id": event.id, "meeting_id": None, "outcome": "exported",
                 "results": []}
        meetings.append(entry)
        try:
            meeting = _find_meeting(g, url)
            if not meeting:
                entry["outcome"] = "not-found"
                continue
            entry["meeting_id"] = meeting["id"]
            _, entry["results"] = _export_parts(g, dest, meeting, window)
            if not entry["results"]:
                entry["outcome"] = "no-transcripts"
        except GraphError as exc:
            organiser = (event.organizer.address if event.organizer else "")
            external = organiser.rpartition("@")[2].lower() not in ("", home)
            entry.update(outcome="other-tenant" if exc.status == 403 and external
                         else "failed", error=str(exc))
        except (OSError, ValueError) as exc:
            entry.update(outcome="failed", error=str(exc))
    results = [r for entry in meetings for r in entry["results"]]
    counts = {"events": len(events), "meetings": len(meetings),
              "written": sum(r["outcome"] == "written" for r in results),
              "already": sum(r["outcome"] == "already" for r in results)}
    for outcome in ("no-transcripts", "not-found", "other-tenant", "failed"):
        counts[outcome] = sum(e["outcome"] == outcome for e in meetings)
    log.info("tool=export_meeting_transcripts counts=%s", counts)
    return {"dir": str(dest), "start": start, "end": end,
            "counts": counts, "meetings": meetings}
