---
type: comment
at: "2026-10-16T03:45:00Z"
by: "claude"
event: "commented"
---

Recurrence, 2026-10-16: GAP 1 and GAP 2 are still live. A session whose server runs `--preset mail,calendar` needed a meeting transcript (operator's own organised meeting, same tenant as the 2026-10-02 pull). It found `tools/meetings.py` only by reading the repo again. It then ran the graph-direct escape hatch as a scratch script: `Ctx.create(write=False)`, then `find_meeting_id(join_url)`, then `list_meeting_transcripts`, then `get_meeting_transcript(text/vtt)`, with the content written to disk and ids and character counts printed. It worked first time: 1 transcript, 114,482 chars, 712 cues, attributed. No consent or kill-switch problem this time.

Two requirements to add to the `export_transcript` shape in GAP 2:

1. **Fetch ALL transcripts on the meeting, not just the newest.** The 2026-10-02 meeting had two, because transcription was stopped and restarted (about 9 minutes untranscribed). "Newest only" would have silently dropped the first 32 minutes. Name them `part1..n` in creation order and report the count.
2. **Emit the OKF `.md` alongside the `.vtt`**: speaker plus `[hh:mm:ss]` per turn, consecutive same-speaker cues joined, and a provenance block with `transcript_created_utc`, sha256 and size. Both live pulls had to hand-roll exactly this converter. Downstream sidecar tools only accept Teams `.docx` downloads, so the VTT route needs its own `.md` record.

Also for GAP 1: `doctor` saying "meetings module present, preset not enabled" would have saved the repo spelunking on both occasions.
