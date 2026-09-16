---
type: "issue"
title: "Phase 1 — mail tools (list/get/folders + draft-only writes)"
created: "2026-07-29T21:47:41Z"
resource: "oif:ckm/1pccze"
aliases: ["CKM-6"]
kind: "feature"
priority: "high"
requested_by: "human:seanwy"
tags: ["phase-1", "mail"]
depends_on: ["8nd03y"]
depends_on_aliases: ["CKM-3"]
---

Read: list_messages (folder, filter, search, top/paging), get_message,
list_mail_folders. Write-gated: create_reply_draft, create_reply_all_draft,
create_forward_draft, update_draft, create_draft.

Mail semantics (non-negotiable):
- Replies/forwards ALWAYS seeded via Graph createReply/createReplyAll/
  createForward, then PATCH new content into the returned draft
- Only ever PATCH drafts (isDraft=true); never modify delivered messages
  (stays clear of Mail-Advanced.ReadWrite enforcement, 31 Dec 2026)
- Forward recipients go in the createForward request body
- Nothing is sent by phase-1 tooling; send_draft separately flagged if built
- Optional `mailbox` param on every tool (/users/{mailbox}/...)
