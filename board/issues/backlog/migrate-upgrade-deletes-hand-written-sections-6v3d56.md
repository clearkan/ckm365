---
type: "issue"
title: "migrate_correspondence upgrade deletes hand-written sections from OKF v0.1 records"
created: "2026-10-26T10:05:29Z"
resource: "oif:ckm/6v3d56"
kind: "bug"
priority: "high"
requested_by: "human:seanwy"
tags: ["mail", "migration", "data-loss"]
---

Found testing v2.10.0 against a real client correspondence folder, on a
throwaway branch in a git worktree, 2026-10-26. Nothing was lost for real:
the branch is unmerged and git holds every original.

## What happened

`migrate_correspondence(dry_run=False)` with the default actions:

| Outcome | Count |
|---|---|
| pair applied | 22 |
| pair failed: a note already uses `<stem>.md` | 25 |
| upgrade applied, clean | 12 |
| upgrade applied, human-written sections deleted | 6 |
| manual, skipped | 60 |

A second run changed nothing, and no partial files were left.

The 12 clean upgrades changed exactly three lines each: `timestamp` became
`generated`, and `exported_by` was dropped. The other 6 were records a
person had annotated after export: summaries, "what to remember" lists,
owner and action tables below the mail body. The upgrade re-exports the
message from Graph and replaces the whole file, so 34 such sections went.

This contradicts the brief (mr31re: "never overwrite a hand-written body")
and the tool's own docstring ("Hand-written bodies are NEVER rewritten").
The planner calls these records `upgrade` because it classifies by
front-matter keys only; a v0.1 record that a human has extended looks
identical to an untouched one. The dry run could not show the problem
either: it reports "Would Write <name>" with no hint the body differs.

## Fix, proposed

Make `upgrade` a FRONT-MATTER-ONLY rewrite, like `backfill-id` already is:
replace `timestamp: X` with `generated: {by: "ckm365/<version>", at: X}`,
drop `exported_by`, and keep every byte after the closing `---`. That is
exactly the v0.1 to v0.2 delta for this document (CHANGELOG 2.8.0), needs
no Graph call, and cannot lose content. The 12 clean cases would come out
byte-identical to what the re-export wrote.

If a re-export is still wanted for some reason, it must first compare the
existing body with a fresh one and fall back to `manual` ("record has hand
edits") on any difference.

Regression test: a v0.1 record with an extra `## Summary` section below
the body must keep it after upgrade, and the dry run must say the body is
kept.

## Also seen, already known (r2wgna)

- 25 lone `.eml` cannot be paired because a front-matter-less note owns
  `<stem>.md`. Needs a pair destination for the taken-name case.
- 43 front-matter-less notes are the largest manual bucket.
- 13 subfolders hold 23 more items (19 current, 4 manual); not entered.

Relates to mr31re (the helper), cxsznh (the apply step).
