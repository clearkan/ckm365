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
organised OR is on the calendar invite for. Someone must have actually
started transcription, and transcripts land at or after the meeting ends
— this is meeting CONTENT after the fact, never a live feed.

Transcript text is sensitive in exactly the way mail bodies are: it is
returned to the caller but never logged, and the smoke scripts print
lengths and ids only.
"""

from ..graph import encode_segment as _seg
from ..models import Transcript
from .context import Ctx, pull

# Graph's own formats for transcript content; VTT carries timings and
# (when the tenant enables attribution) speaker names.
_FORMATS = ("text/vtt", "text/plain")


def _meeting_path(meeting_id: str) -> str:
    return f"/me/onlineMeetings/{_seg(meeting_id, 'meeting_id')}"


def find_meeting_id(ctx: Ctx, join_url: str, *,
                    account: str | None = None) -> str | None:
    """Resolve a Teams join URL to the online-meeting id the transcript
    tools need. Get the join URL from list_events/get_event (an event's
    join_url field). Returns None when the meeting cannot be resolved —
    typically because the signed-in user was not on its invite.
    """
    if not (join_url or "").strip():
        raise ValueError("join_url is required")
    g = ctx.graph(account)
    # $filter on JoinWebUrl is the documented lookup; the URL is passed as
    # an OData string literal, so single quotes must be doubled.
    quoted = join_url.replace("'", "''")
    found = g.get("/me/onlineMeetings",
                  params={"$filter": f"JoinWebUrl eq '{quoted}'"})
    values = found.get("value") or []
    return values[0].get("id") if values else None


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
