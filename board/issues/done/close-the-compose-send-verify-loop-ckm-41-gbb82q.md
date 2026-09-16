---
type: "issue"
title: "Close the compose -> send -> verify loop (CKM-41 option A)"
created: "2026-08-20T02:25:00Z"
resource: "oif:ckm/gbb82q"
aliases: ["CKM-42"]
kind: "feature"
priority: "high"
requested_by: "human:seanwy"
tags: ["mail", "compose", "write-tier", "ckm-41-option-a"]
parent: "vt2sz3"
---

The build issue for OPTION A of CKM-41, approved by seanwy by phone at
00:04 on 2026-08-20 ("that's approved A" / "let's just get it working on
option A for Alpha for now" / "the rest of them can wait"). B, C and D are
explicitly deferred and nothing here touches them.

## Why

Eight git-ignored `tmp/` scripts dated 2026-08-18 did a real outbound
reply-with-attachment cycle by dropping out of the tool surface and
calling Graph directly. CKM-41 records the evidence. The gaps they had to
work around:

1. Revising a reply body loses the quoted history (`update_draft` REPLACES
   the body; the splice that inserts at the top of `<body>` was private to
   `drafts._insert_top` and only reachable at CREATE time). Re-implemented
   twice, the second time to preserve a signature block as well.
2. No signature concept — a ~700-byte HTML literal copy-pasted into two
   scripts.
3. No `discard_draft` — raw DELETE on the message.
4. No `remove_attachment` — raw DELETE on the attachment.
5. Reply vs reply-all fixed at creation — switching meant deleting the
   draft and re-seeding from `createReplyAll`.
6. Post-send verification hand-rolled three times (recipients, attachment
   names/sizes, quoted thread survived, non-ASCII leakage in the new text).
7. Discoverability: the archive step used raw `/$value` when
   `export_message` already does that job better.

## Scope

Write tier and read tier only. NO new Graph scope, NO consent prompt, NO
tenant-wide operation — that is part of why A was chosen over B and C.

- `revise_draft` (write) — replace the text you wrote, keeping the quoted
  history AND the signature.
- per-profile `signature_html` in `profiles.toml`, applied at draft
  creation by `create_reply_draft` / `create_forward_draft` /
  `create_draft`.
- `discard_draft` (write) — refuses non-drafts; Graph DELETE on a message
  moves it to Deleted Items, so it stays reversible.
- `remove_attachment` (write) — the inverse of `add_attachment`, drafts
  only.
- `verify_message` (read) — the assertions the scripts kept re-deriving.
- docs pass so `export_message` is found before `/$value` is.
