---
type: "issue"
title: "Expose recipients on message listings (to/cc), or make $select caller-controllable"
created: "2026-08-05T02:40:00Z"
resource: "oif:ckm/55vnpp"
aliases: ["CKM-37"]
kind: "feature"
priority: "high"
requested_by: "claude"
tags: ["mail", "read-tier", "routing"]
---

claude (2026-08-05): MessageSummary carries sender but no recipient fields,
and the $select projection is fixed inside the server rather than passed by
the caller. Two separate consumers are blocked by the same gap, and the
second one is the more important.

BLOCKED 1 — learning correspondents from Sent Items. "Who does the user
actually email, and how often" is the natural way to seed a contact
registry, and it is unanswerable from a folder where the useful party is
the RECIPIENT. Listing sentitems today returns the user as sender on every
row and nothing else identifying.

BLOCKED 2 — alias-based routing in a SHARED mailbox. Where one mailbox
receives for two distinct parties (an operating entity and a second
jurisdiction; or a personal address that is also used for a trust), the
address the message was delivered TO is the single strongest signal for
which party it belongs to. Sender does not carry it. Without recipients,
that resolution falls back to weaker heuristics on subject and counterparty
domain, precisely in the cases where getting it wrong matters most —
different retention, privacy and disclosure expectations attach to the two
parties sharing the mailbox.

Sketch (read tier — toRecipients/ccRecipients are ordinary message
properties, no new consent):
- Add to_recipients and cc_recipients to MessageSummary. Both are lists;
  Graph caps what it returns on a collection GET, so document the cap
  rather than implying completeness.
- Consider bcc_recipients only for sentitems (it is present on the user's
  own sent copy and absent elsewhere) — or omit it in v1 and say why.
- This is an additive model change on a blessed API. ClearKan pins
  ckm365, so it is additive-safe, but confirm nothing does exhaustive
  field matching on MessageSummary before shipping.
- Alternatively/additionally: let the caller pass a select list to
  list_messages. That is more flexible but pushes Graph field names into
  caller code and makes the return shape dynamic — probably worse for an
  agent-facing API than just adding the two fields. Pick one deliberately
  and record which and why.

Volume note: recipients meaningfully enlarge each row, and callers that
page thousands of messages pay for it on every row whether they use it or
not. If that proves heavy, an opt-in flag on list_messages is the escape
hatch — but do not add the flag pre-emptively without measuring.

Out of scope: recipient-based FILTERING server-side (a separate predicate,
belongs with CKM-35's work if wanted), and any address-book resolution of
recipients to identities.
