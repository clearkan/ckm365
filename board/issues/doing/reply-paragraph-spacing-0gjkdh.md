---
type: "issue"
title: "Reply paragraphs run together: Outlook's seeded stylesheet zeroes our <p> margins"
created: "2026-11-18T00:00:00Z"
resource: "oif:ckm/0gjkdh"
kind: "bug"
priority: "high"
requested_by: "human:seanwy"
tags: ["compose", "rendering", "outlook"]
---

Reported by a working session for seanwy, who says it happens often:
reply drafts from create_reply_draft / revise_draft with plain pandoc
HTML (`<p>`, `<ul>`, `<ol>`, no inline styles) render in Outlook with
no blank line between paragraphs. verify_message reported nothing.

## Cause

The reply Graph seeds carries Outlook's head stylesheet,
`<style>P {margin-top:0;margin-bottom:0;}</style>`. ckm365 inserts our
text inside that same document, so the rule zeroes our paragraphs too.
The quoted history is unaffected because Outlook styles its own
paragraphs inline. Before this card, ckm365 added an inline margin only
when the profile set `compose_font` (tc3vj9), and only to bare `<p>`.

## Fix (v2.16.0)

- `common.block_margins`: p, ul, ol, table, blockquote and h1-h6 in
  caller text get `margin:0 0 12pt 0` inline unless they set a margin.
  Applied on every compose path (`drafts._styled`), whatever the
  profile. Signature and quoted history are untouched.
- verify_message gains `layout_warnings`: the stylesheet zeroes p
  margins and our fenced text has a `<p>` without one (older drafts, or
  ones written elsewhere). revise_draft with the same body fixes them.
- The disk-root refusal now says how to fix it ("copy the file under it
  first, or set CKM365_ATTACH_ROOT on the server's registration").

## Verification

- Offline: `tests/test_block_spacing.py` (15 tests); suite 568 passed,
  18 skipped.
- Still to do: a human look at one reply in Outlook desktop and OWA
  after the server restarts on the new code.
