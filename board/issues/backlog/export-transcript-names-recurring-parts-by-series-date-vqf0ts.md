---
type: "issue"
title: "export_transcript names every part of a recurring meeting by the series start date"
created: "2026-11-12T00:00:00Z"
resource: "oif:ckm/vqf0ts"
kind: "bug"
priority: "low"
requested_by: "agent:claude"
tags: ["meetings", "export"]
---

Found in live use on 12 Nov 2026 (gap report from another session, which
called `meetings.export_transcript` directly because the user's server
did not enable the `meetings` preset; see graph-direct.md rule 5).

For a RECURRING Teams meeting, Graph's onlineMeeting is the whole series,
so its transcripts are every occurrence's. `export_transcript` builds one
stem from `meeting["startDateTime"]` (the series start) and numbers parts
across the series. A 12 Nov transcript of a series that began on 17 Sep
was saved as `20260917_<slug>_<token>-transcript-part3.*`, and its .md
record says "part 3 of 3".

## Proposed fix (needs a spec test before it goes to Codex)

- Date each transcript from its own `createdDateTime`, not the series
  start, and number parts within that date: the 12 Nov file becomes
  `<12 Nov date>_<slug>_<token>-transcript-part1.*`, "part 1 of 1".
- Keep the UTC date, as every other exporter does (`file_stem`), and
  say so in the docstring: a morning meeting in Melbourne lands on the
  previous UTC day.
- CHANGELOG note: files already exported under the old names are not
  renamed; a rerun writes the new names alongside them.

Open question for later: a long series re-checks every occurrence on
each run. A `since` date filter may be worth adding, but not in this fix.
