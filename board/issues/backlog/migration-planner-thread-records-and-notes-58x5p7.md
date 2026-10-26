---
type: "issue"
title: "Migration planner: read thread records' message ids, and stop calling non-mail notes manual"
created: "2026-10-26T13:20:26Z"
resource: "oif:ckm/58x5p7"
kind: "improvement"
priority: "medium"
requested_by: "human:seanwy"
tags: ["mail", "migration"]
---

From a full manual review of one real correspondence folder after the
v2.10.1 migration, 2026-10-27. The folder is now reconciled: 625 items
current, nothing to pair, no duplicates. Two planner gaps account for most
of the manual work it took.

**1. Thread records hide their ids.** A hand-extended record covering a
thread listed each message under a nested `messages:` list, with the
`internet_message_id` of the latest one inside the list item. The planner
reads top-level scalar keys only, so the record looked id-less, its
same-stem `.eml` stayed lone, and `pair` then failed with "refusing to
overwrite". The fix in the folder was a top-level `internet_message_id`
for the record's `.eml`. Either document that convention (a thread record
carries its latest message's id at top level) or have the planner read ids
from `messages:` entries too. Documenting it is simpler.

**2. Notes that are not one email stay `manual` forever.** 33 items remain
manual after review, all correctly:

| Kind | Count |
|---|---|
| `.msg` (never opened; its sidecar now carries the id) | 9 |
| guides, READMEs, digests, meeting and topic notes, drafts | 16 |
| text conversions of attachments in subfolders | 4 |
| WhatsApp records, a document register (front matter, no id) | 3 |
| unsent draft `.eml` (`X-Unsent`, no Message-ID by nature) | 1 |

So a rerun reports the same 33 forever, and the next agent re-reviews them.
Options: a `note` kind for records without front matter and with no
same-stem mail file; treat a front matter whose `type` is not `Email` as
not a migration concern; skip `X-Unsent` `.eml`; let a `.msg` count as
`none` when its same-stem sidecar carries an id. Each is a few lines.

**Also confirmed in the review:** `export_message`'s `dedupe_dir` caught
two real duplicates. Two summary notes described emails already filed
under other names, and the export returned `already_exported` instead of
writing a second copy.

Relates to mr31re, r2wgna (the earlier "note kind" remark), 6v3d56.
