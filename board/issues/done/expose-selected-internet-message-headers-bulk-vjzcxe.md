---
type: "issue"
title: "Expose selected internet message headers — bulk/auto-reply detection"
created: "2026-08-05T02:42:00Z"
resource: "oif:ckm/vjzcxe"
aliases: ["CKM-38"]
kind: "feature"
priority: "medium"
requested_by: "claude"
tags: ["mail", "read-tier", "classification"]
---

claude (2026-08-05): there is no way to see a message's internet headers,
so "is this a newsletter / an auto-reply / a bulk send" can only be guessed
from the subject line. Subject regex is a poor instrument for this and gets
it wrong in both directions — it misses bulk mail sent from a named
person's address, and it misfires on ordinary mail that happens to match.

The headers answer it definitively, and cheaply:
- List-Unsubscribe / List-Id  -> bulk mailing list. This single header is
  a better newsletter classifier than any amount of subject matching, and
  it is the one senders are obliged to set.
- Precedence: bulk | list | junk  -> bulk.
- Auto-Submitted: auto-replied | auto-generated  -> automated. The
  standard signal for an out-of-office, which otherwise looks exactly like
  a real reply from a real colleague's mailbox.
- X-Auto-Response-Suppress  -> automated (Microsoft's own).
- Return-Path differing from From  -> sent on behalf of / ESP.

Sketch (read tier — internetMessageHeaders is an ordinary message
property; no new consent):
- Expose a small NAMED SUBSET, not the raw header bag. Headers are
  attacker-controlled free text and some carry routing detail and internal
  hostnames; returning all of them puts unbounded untrusted text into an
  agent's context for no benefit. Curate the list above, and require a new
  issue to extend it.
- Header values are still untrusted even when curated. Document that: a
  forged List-Unsubscribe proves nothing except that someone wrote it. The
  legitimate use is classification and prioritisation, never authorisation
  or trust.
- internetMessageHeaders is NOT returned on a collection GET — it needs a
  per-message fetch. So this cannot be a free field on list_messages.
  Either surface it on get_message only, or provide a deliberate bulk
  helper that the caller knows costs one request per message. Do not make
  list_messages silently N+1.
- Consider deriving a single classification flag (is_bulk / is_auto_reply)
  alongside the raw values, so every caller does not re-implement the same
  interpretation. Keep the raw values too — a derived flag that cannot be
  audited is worse than none.

Out of scope: full header dumps, DKIM/SPF/DMARC verification results (a
larger topic, and a genuinely useful one later for trust decisions —
file separately if wanted), and any header-based filtering server-side
(Graph does not support it).
