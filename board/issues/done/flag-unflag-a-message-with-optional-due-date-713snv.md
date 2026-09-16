---
type: "issue"
title: "flag / unflag a message, with optional due date — and list what is flagged"
created: "2026-08-05T00:12:00Z"
resource: "oif:ckm/713snv"
aliases: ["CKM-34"]
kind: "feature"
priority: "high"
requested_by: "human:seanwy"
tags: ["mail", "write-tier", "triage"]
depends_on: ["g9n463"]
depends_on_aliases: ["CKM-35"]
---

seanwy (2026-08-05): flagging is the second half of a triage pass. The
working pattern is: clear the unread pile first, then work the flagged
queue. The server currently supports neither half of that.

Graph models this as a single `flag` property on the message:
  flag: {flagStatus: notFlagged|flagged|complete,
         startDateTime, dueDateTime, completedDateTime}

Sketch (write tier, same scope as CKM-33):
- flag(message_ids, due: str | None = None, start: str | None = None)
  A flag with NO date is the common case and must be the default — an
  agent should not have to invent a date to mark something for later.
  When due is given, set dueDateTime (and startDateTime, which Graph
  expects alongside it; default start to now if only due is supplied,
  rather than failing).
- unflag(message_ids) -> flagStatus notFlagged
- complete_flag(message_ids) -> flagStatus complete + completedDateTime.
  Distinct from unflag: "done" and "never mind" are different outcomes
  and a triage log wants to tell them apart.
- Batch and partial-failure semantics identical to CKM-33. Do not invent
  a second convention.
- Dates are timezone-bearing. Graph wants {dateTime, timeZone}; accept a
  plain ISO string from the caller and normalise, but do NOT silently
  assume UTC for a bare date — a flag due "today" in the wrong zone is
  wrong by up to a day. Default to the profile/mailbox timezone and say
  which was used in the return value.

Listing flagged mail is the other half and is covered by CKM-35's
filtering work rather than duplicated here — flagged is just another
server-side predicate. This issue owns SETTING the flag; CKM-35 owns
FINDING flagged mail reliably.

Out of scope v1: reminders (a separate Graph concept from flags),
categories/colour, and flagging calendar items.
