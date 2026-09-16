---
type: "issue"
title: "revise_draft appends instead of replacing on create_reply_draft output"
created: "2026-09-14T14:05:00Z"
resource: "oif:ckm/xenaqk"
aliases: ["CKM-48"]
kind: "bug"
priority: "high"
requested_by: "human:seanwy"
tags: ["mail", "drafts", "write-tier"]
---

seanwy (2026-09-14): hit twice in one session, on drafts created minutes
earlier by create_reply_draft in the same session.

revise_draft's docstring says it replaces the fenced region that
create_reply_draft wrote, and only falls back to inserting at the TOP for a
draft with no fence ("one composed in Outlook, or created before this
version"). Neither applied. Both drafts came straight from
create_reply_draft(reply_all=True) and both times revise_draft PREPENDED the
new text, leaving the previous version intact below it.

The result is a client-facing draft containing two complete versions of the
same message, one superseded. On the second occurrence the stale copy still
said "Attached is v1.2.4" while the new copy above it said v1.2.5 and the
attachment was v1.2.5. That is exactly the kind of thing that gets sent by
accident.

Detection: verify_message reports boundary "quote", not "fence", on these
drafts - so the fence is either not being written by create_reply_draft or
not being found by revise_draft. boundary is the diagnostic; worth checking
which of the two halves is at fault.

Workaround used both times: discard_draft, create_reply_draft again with the
full corrected text, re-attach, re-set cc. Costs the attachment upload and
the cc, and the draft id changes.

Suggested: make revise_draft REFUSE when it cannot find its own fence, rather
than silently falling back to prepend. A loud failure is recoverable; a
duplicated body in a client draft may not be noticed. If the prepend fallback
is kept for genuinely foreign drafts, it should at least be reported in the
return value so a caller can check.
