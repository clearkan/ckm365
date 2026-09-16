---
type: "issue"
title: "Simplification review — deferred medium/low findings (Fable 5 review 2026-07-30)"
created: "2026-07-29T23:40:54Z"
resource: "oif:ckm/dsjs0g"
aliases: ["CKM-14"]
kind: "improvement"
priority: "low"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["quality", "review"]
---

HIGH findings (dead Ctx.cache_dir plumbing; replyTo in Message.SELECT but
unmodeled) are being fixed immediately. Deferred items, owner input where
noted:

MEDIUM
- @tool decorator collapsing account/mailbox params + ctx.target() +
  require_write() across all 13 tools (~25 net lines, the largest win) —
  trades away literal signatures; decide next trim pass
- App-only client-credential support (~30 lines in config/auth) shipped
  ahead of CKM-5 and unexercised — either stub until CKM-5 or accept
- Per-call account param: reviewer proposes dropping (Ctx pinning covers
  smokes) — RECOMMEND KEEP: cross-tenant calls in one MCP session are a
  demonstrated flow (tenant-a+tenant-b in the same Claude Code session)
- _list()/_fetch() helper for the 4x paged+model_validate+$select pattern

LOW
- Drop redundant account= kwargs in smoke scripts (pinning covers it)
- Patch-dict if-chains in update_draft/update_event -> comprehensions
- _require_draft() helper to unify the two isDraft guards (invariant in
  one place — do together with send_draft which needs the same check)
- create_draft body+html flag vs body_html convention of siblings
- add_attachment name/content_type override params likely speculative
- Model field-shape consistency (is_read nullable vs sibling flags)

Context: actual code ~742 lines vs 1,018 raw (docstrings are load-bearing
MCP descriptions); ~50 lines of growth is board-sanctioned CKM-11 scope.
Reviewer verdict: mandate honored; propose restating budget as code lines.
