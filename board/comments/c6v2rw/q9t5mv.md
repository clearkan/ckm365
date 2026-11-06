---
type: comment
resource: oif:ckm/c6v2rw/q9t5mv
at: '2026-11-07T01:30:00+00:00'
by: claude
---

Merged: 418 passed. One tweak: the no-meeting error now says what failed
("no online meeting found for that join_url: ...").

Live, read-only, NOT fully verified: on both device-code profiles the
meeting lookup worked (one meeting resolved, 0 transcripts, nothing
written), but every other recent meeting answered 403 on the transcript
routes. That is the consent tier or the Teams kill-switch, both tenant
settings, so it was left alone. A content pull still needs a run on a
tenant where add-transcript-scopes.sh was applied.
