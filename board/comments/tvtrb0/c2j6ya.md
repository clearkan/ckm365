---
type: comment
at: "2026-11-06T04:30:00Z"
by: "claude"
event: "commented"
---

Measured live, read-only, on recent replies in both tenants: every one
carried In-Reply-To; References held up to 23 ids in 1,850 characters,
so the 200-character header cap would keep two; `uniqueBody` comes back
as text under the same Prefer header as `body`, 14 characters against
54,859 for the full chain on one long thread; conversationId is 80
characters.

Spec for items 1-4 is `tests/test_mail_threading.py` (skipped until
built). Two decisions: `uniqueBody` is fetched by export only, not on
`Message.SELECT`, so `get_message` does not double its payload; and
References is tokenised by id (last 100 kept, any id over 250 characters
dropped) instead of capped as a string. The upgrade of existing records
is a second card after this one lands.
