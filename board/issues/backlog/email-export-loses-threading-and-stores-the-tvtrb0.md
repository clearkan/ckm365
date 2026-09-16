---
type: "issue"
title: "Email export loses threading and stores the whole quoted chain every time"
created: "2026-09-16T09:30:00Z"
resource: "oif:ckm/tvtrb0"
aliases: ["CKM-49"]
kind: "bug"
priority: "high"
requested_by: "human:seanwy"
tags: ["email", "export", "okf", "correspondence"]
---

A design study on holding correspondence in a repository
(two client correspondence corpora) examined what `export_message` writes
and found four concrete gaps. None is speculative; each was read out of the
code.

**1. Threading headers are never captured.** `Message.SELECT` (models.py:162)
fetches `internetMessageId` only, and `_CURATED_HEADERS` (models.py:46) does
not include `in-reply-to` or `references`. `conversationId` appears nowhere in
the codebase. So an exported record cannot be placed in its thread, and the
corpora invent `supersedes:` pointers by hand to compensate — reconstructing
badly what RFC 5322 already carries.

Add to `Message.SELECT`: `conversationId`, `conversationIndex`, `uniqueBody`.
Add to `_CURATED_HEADERS`: `in-reply-to`, `references`. Sanitise `References`
by angle-bracket token rather than the 200-character cap, because a long
thread legitimately exceeds it.

**2. The body is the full quoted chain.** Export uses `prefer("text")`, so
every message carries everything before it. In a ten-message thread the first
message's text is stored ten times. Graph already returns `uniqueBody`, which
is the new text alone, computed server-side with no heuristic quote-stripping.
Default to `uniqueBody`, with a `body_scope` key recording which was used and
an opt-in for the full body. Keep the `.eml` authoritative for the complete
chain.

**3. `resource` should be `mid:<internetMessageId>`.** RFC 2392 defines the
`mid:` URI, which identifies a message independently of any mailbox. Today
`webLink` is used, which is per-mailbox and therefore means something
different to each recipient. A `mid:` resource lets a record in one repository
cite a message held in another, and survives the file being renamed. Move
`webLink` to a `web_link` extension key rather than dropping it.

**4. `type: Email` should become `type: Message` plus `channel: email`.**
Teams, Slack and WhatsApp records share the same shape, and a single type with
a channel key lets one consumer handle all of them. Splitting by type forces
every reader to enumerate channels it has never heard of.

The export stays deterministic under all four changes, which is the property
worth protecting.

Related, already known: CKM-45 (direction derived from sender == mailbox, wrong
for Send-As) and CKM-44 (inline images invisible because hasAttachments is
false).
