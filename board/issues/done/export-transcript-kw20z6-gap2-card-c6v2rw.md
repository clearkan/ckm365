---
type: "issue"
title: "export_transcript: every transcript part of a Teams meeting to .vtt + OKF .md"
created: "2026-11-07T00:00:00Z"
resource: "oif:ckm/c6v2rw"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["meetings", "export", "copilot-card"]
---

Implements GAP 2 of kw20z6 (CKM-44,
`board/issues/backlog/surfacing-gaps-export-transcript-the-meetings-kw20z6.md`,
including its 2026-10-16 comment). The spec is
`tests/test_meetings_export.py` (on main, skipped until
`meetings.export_transcript` exists). Read it in full first; its module
docstring is the design.

## Deliverable

In `src/ckm365/tools/meetings.py`:

1. `vtt_turns(vtt: str) -> list[tuple[str, str, str]]`, public:
   (speaker, `hh:mm:ss` start, text) per turn. A cue is a timing line
   containing `-->` followed by text lines up to a blank line; anything
   else (the WEBVTT header, cue ids, NOTE blocks) is skipped. Speaker from
   `<v Name>...</v>` (strip the tags; `""` when absent). Start is the
   timing's first field cut to `hh:mm:ss` (pad `mm:ss.fff` forms to
   `00:mm:ss`). Consecutive cues from the same speaker join with one
   space; the turn keeps the first cue's start.
2. The tool, read tier:

       def export_transcript(ctx: Ctx, dest_dir: str, join_url: str, *,
                             account: str | None = None) -> dict

   Before any request: `join_url` non-blank (ValueError naming it);
   `dest_dir` through `confine(Path(dest_dir), "dest_dir")` from
   `tools/mail/disk.py` and it must be an existing directory.
   Then look the meeting up yourself with the same `/me/onlineMeetings`
   `$filter` as `find_meeting_id` (factor the shared lookup into a
   private helper returning the whole meeting dict, and have
   `find_meeting_id` use it; its tests must still pass). No match is a
   ValueError saying the signed-in user must be the organiser or on the
   invite. List transcripts with `pull(...)` as
   `list_meeting_transcripts` does (top 100), sort by `created`
   ascending. Stem: `file_stem(meeting.get("subject"),
   meeting.get("startDateTime"), meeting["id"])` from
   `tools/mail/bulk.py`, then `-transcript-part<N>`.
   Per part: if both `.vtt` and `.md` exist, outcome `already` with no
   download. Otherwise fetch the VTT (`g.content(..., params={"$format":
   "text/vtt"})`), and write whichever of the two files is missing with
   `write_target` + `write_atomic` (the `.vtt` verbatim, UTF-8; the
   `.md` rendered from it). Outcome `written`.
   The `.md`: front matter in this key order, values through
   `_yaml_value` from `tools/mail/export.py` (import it): type
   `"Transcript"`, channel `"teams-meeting"`, title (subject or
   `"(no subject)"`), description (`"Teams meeting transcript, part N
   of M"`), tags `["transcript", "teams"]`, generated `{by:
   "ckm365/<version>", at: <transcript created>}`, meeting_id,
   transcript_id, part, parts, transcript_created_utc, sha256 and size
   (of the UTF-8 `.vtt` bytes), speakers (distinct, first-appearance
   order, without `""`). Body: `# <title>`, then per turn a blank line,
   `**<speaker or (unattributed)>** [hh:mm:ss]`, and the text on the
   next line.

   Result: `{"dir", "meeting_id", "parts": M, "results":
   [{"part", "transcript_id", "created", "vtt", "md", "outcome"}]}`
   with file names (not full paths) in vtt/md. Log one line: meeting id,
   parts, counts. Never text, names or subject.

   Docstring (~20 lines, the voice of `export_message`): one call
   replaces the scratch-script flow, all parts in creation order and
   why, the two files and the name convention, idempotent reruns,
   disk rules, the tenant gates from the module docstring (pointer, not
   a copy), content never enters context.
3. Register in `READ["meetings"]` in `src/ckm365/tools/__init__.py`,
   after `get_meeting_transcript`.

## Preset counts

`tests/test_offline.py::test_meetings_preset_is_read_only_and_opt_in`:
the two `== 4` become `== 5` and the comment `4 tools + list_accounts`.
Check `test_tools_for_presets` for any count that includes meetings;
change only counts the new tool moves.

## Files you may touch

- `src/ckm365/tools/meetings.py`, `src/ckm365/tools/__init__.py`
- `tests/test_offline.py`: the counts above.

Read only those plus `tests/test_meetings_export.py`,
`src/ckm365/tools/mail/bulk.py` (for `file_stem`), `export.py` (for
`_yaml_value`), `disk.py`, `src/ckm365/graph.py` and the `Transcript`
model. Do not edit spec or other test files; if a test looks wrong, say
so in open_questions and make the rest pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report the before and after counted results; after: all passing, one
fewer module skipped.

## Not in scope

- GAP 1 (doctor hint), GAP 3 (refresh), change notifications.
- Any live check, `CKM365_LIVE_*`, anything under `~/.config/ckm365`.
- Version bump, CHANGELOG, README, docs, board files. No commits.

## Relates to

- kw20z6 (CKM-44) gap 2. h7t3qf: `file_stem` and the naming convention.
