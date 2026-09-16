---
type: "issue"
title: "Live send-cycle test — send with attachment, receive, download, reply-all"
created: "2026-08-11T10:25:00Z"
resource: "oif:ckm/c7x3wr"
aliases: ["CKM-40"]
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
tags: ["testing", "live", "send-tier"]
depends_on: ["28mbps"]
depends_on_aliases: ["CKM-32"]
---

seanwy (2026-08-11): does the test cycle cover sending an email with an
attachment, receiving that email, downloading the attachment from it, and
replying-all to it — if the relevant credentials are available?

It did not. tests/test_live.py is documented as "never sends" and stops at
the draft boundary, so every send-tier path (send_draft, delivery, the
received copy, reply-all on real delivered mail) was verified only by hand.
CKM-32 closed the download gap, which makes the full loop testable for the
first time.

Design — a SEPARATE file, tests/test_live_send_cycle.py, so test_live.py
keeps its "never sends" invariant:
- Double gate: CKM365_LIVE_ACCOUNT (as usual) AND CKM365_LIVE_SEND=1. The
  second is explicit opt-in, because this one really does deliver mail.
  Skips, never fails, when either is absent — matching how the live suite
  behaves without credentials.
- SELF-SEND ONLY. The single recipient is the target mailbox itself,
  asserted before send_draft is called. Nothing can leave the tenant even
  if the test is misconfigured.
- The cycle: create_draft -> add_attachment (binary payload) -> send_draft
  -> poll the inbox for the marker subject -> assert the received copy has
  the attachment -> download_attachment and compare bytes byte-for-byte ->
  create_reply_draft(reply_all=True) on the RECEIVED message -> send_draft
  -> poll for the reply -> assert it threads and carries the reply marker.
- Unique marker subject per run (uuid4 hex) so polling, assertions and
  cleanup can never touch real mail.
- Zero residue, the same standard as test_live.py: everything the run
  creates — both received copies AND both Sent Items copies — is deleted
  in a finally block that runs even on timeout, and the run ends by
  asserting nothing carrying the marker survives in either folder.
- Delivery is polled with a timeout (self-delivery is normally seconds); a
  timeout FAILS rather than skips, since a stuck send is a real signal.

Out of scope: sending to any third party, calendar invites (send tier is
already covered there by the gating tests), and running this in CI —
it is a deliberate, local, opt-in check.
