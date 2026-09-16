---
type: comment
at: "2026-09-15T21:15:00Z"
by: "claude"
event: "updated"
---

History backfill — the 2026-08-30 findings (MIME import solves both the from= and the threading halves; verified in the wild when the owner sent one; the third bug in the cluster, export_message mis-tagging Send-As mail as inbound) were written into the description at the time WITHOUT a history entry or an updated_at bump, so the issue read as untouched since 29 Aug to anyone skimming timestamps. Recorded now. Scope is unchanged and the issue stays in backlog: the technique is proven but no tool implements it, so every use is still a hand-rolled ~30-line MIME build. The technique itself is now documented as Recipe 4 in docs/graph-direct.md.
