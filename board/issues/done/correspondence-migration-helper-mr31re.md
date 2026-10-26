---
type: "issue"
title: "Correspondence migration helper — bring existing folders up to the current record structure"
created: "2026-10-26T08:18:41Z"
resource: "oif:ckm/mr31re"
kind: "feature"
priority: "high"
requested_by: "human:seanwy"
tags: ["mail", "export", "migration", "idempotency"]
---

Project repos already hold correspondence folders built before the current
tools existed. One measured on 26 Oct 2026 had 349 sidecars, of which 292
carry `internet_message_id`. The rest predate the OKF export or were written
by hand from `.msg` files. Records also span OKF v0.1 (`timestamp`,
`exported_by`) and v0.2 (`generated`), file names are hand-written slugs, and
some messages exist only as `.eml` with no `.md` record. Each new structure
change (v2.9.0 dedupe; CKM-49 threading, `uniqueBody` and `mid:` resource;
the file-name token deferred from 4qn81m) widens that gap, and every agent
that meets an old folder improvises its own cleanup.

Requested: a helper agents call to move an existing folder onto the current
structure, safely and repeatably. seanwy's words: a "cleanup" or "migration
helper" function agents can use to migrate from existing structures to new
structures.

## Proposed shape

Two steps, plan then apply, so an agent (and the human) sees the change
before anything moves.

1. **`plan_correspondence_migration(dir)`**, read tier, local only, no Graph.
   Classifies every file and returns a plan, never writes:
   - record version: OKF v0.2 current, v0.1, hand-written front matter, none
   - Message-ID present or missing; for `.eml`, read from the header
   - duplicates: two or more files with one Message-ID (reuse the v2.9.0 scan
     in `tools/mail/export.py`)
   - `.eml` with no `.md` record beside it, and `.md` records whose paired
     `.eml` is missing (report only)
   - `.msg` files: classify and report. Parsing them needs a new dependency,
     which needs sign-off, so the first cut does not open them.
   - for each file, the proposed action: none, upgrade, backfill-id, pair,
     flag-duplicate, manual.
2. **`migrate_correspondence(dir, actions=None, dry_run=True)`**. Applies the
   plan or a subset of it:
   - **upgrade**: re-export the message through `export_message`, located by
     Message-ID with `$filter=internetMessageId eq '<id>'` across the
     caller's mailboxes, so a record exported from someone else's copy still
     resolves. Verify live that this filter works and is not lag-prone like
     the subject filters (AGENTS.md gotchas).
   - **backfill-id**: add `internet_message_id` to a hand-written sidecar's
     front matter from its paired `.eml`, or by Graph lookup on sender plus
     sent time when there is no `.eml`. Ambiguous lookups become `manual`,
     never a guess.
   - **flag-duplicate**: report, never delete. Moving the spare copy is the
     caller's `git mv` to make.
   - **rename** to the convention, only once the file-name token convention
     exists (k4r9tw), and only on request.

## Rules

- Never delete. Never overwrite a hand-written body: hand-written sidecars
  get front-matter additions only, because their prose is human work.
- Writes go through `tools/mail/disk.py`'s rules: download root fence,
  atomic write, no residue.
- Idempotent: running it twice changes nothing the second time.
- Says what it could not do, per file. A silent skip is the failure mode
  this exists to remove.
- Tool versus CLI versus skill: decide when picked up. A tool if agents call
  it mid-task, a `ckm365 migrate` subcommand if humans run it over a repo.
  Possibly both over one module.

## Relates to

- 4qn81m (v2.9.0): the Message-ID scan this reuses.
- CKM-49 (tvtrb0): its record changes are the next migration target, so the
  helper should land first or alongside.
- CKM-53 (k4r9tw): bulk export writes new folders; this repairs old ones.
