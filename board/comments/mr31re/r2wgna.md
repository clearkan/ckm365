---
type: comment
at: "2026-10-26T12:45:00Z"
by: "claude"
event: "completed"
---

Shipped in v2.10.0 as two read-tier tools in tools/mail/migrate.py:
plan_correspondence_migration (dr4f2n) and migrate_correspondence
(cxsznh), both Codex-built from test-first specs on main, via omni's
copilot loop (h59xfz proved the loop first). Tools, not a CLI, for this
cut.

Verified: offline 226 passed / 15 skipped. Live suite 14/14 on both
delegated tenants; live-smoke OK on both. The Message-ID filter checked
on both tenants before anything was built. The planner run read-only
over four real folders (58-620 items). migrate_correspondence dry-run
over two of them: all 18 v0.1 records located in Graph (would-apply),
and 20 lone .eml whose <stem>.md is a front-matter-less note came back
`failed: refusing to overwrite` — the right refusal, but a real pattern:
a note beside a .eml under the same stem. Not applied for real on any
folder yet; that is the owner's call per repo, with dry_run=false.

Left for later, by design: rename to a file-name convention (k4r9tw),
Graph lookup by sender and time for a sidecar with no .eml (stays
manual), .msg parsing (dependency), a `note` kind for front-matter-less
files (the largest manual bucket, 23-43 per folder), and a pair
destination for the taken-name case above. CKM-49's record changes are
the next migration target; the planner's version detection is where a
pre-CKM-49 check slots in.
