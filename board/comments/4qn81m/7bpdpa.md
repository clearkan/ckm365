---
type: comment
at: "2026-10-26T07:01:20Z"
by: "claude"
event: "completed"
---

Shipped in v2.9.0. Items 1, 2 and 4 done; item 3 left for k4r9tw (CKM-53),
the first tool that will name files itself.

- export_message gains dedupe_dir + force. The scan keys on the Message-ID
  (angle brackets optional), reads .md/.markdown/.txt front matter and .eml
  headers up to the blank line, does not recurse, and runs before the
  overwrite check. dedupe_dir is fenced by CKM365_DOWNLOAD_ROOT.
- internet_message_id moved from Message to MessageSummary, so list_messages
  and delta rows carry it. Measured +~105 bytes/row (+10-11%) on both tenants.

Verified: offline suite green (11 new tests). Live suite 14/14 on both
tenants, with a new round trip: a draft exported to .md, then re-exported as
.md and .eml into the same folder; both returned already_exported and wrote
nothing. live-smoke.py and a delta bootstrap OK on both. The live export
test had been failing since v2.8.0 on a stale timestamp assertion; fixed.
