---
type: comment
at: "2026-10-26T09:05:00Z"
by: "claude"
event: "started"
---

Picked up. First live question answered on both delegated tenants before
any code: `GET /users/{mbx}/messages?$filter=internetMessageId eq '<id>'`
works. It found the three newest inbox messages (the youngest 50 minutes
old) and the two newest Sent Items messages by their own id, one hit each,
so it resolves across folders from the mailbox root. An id that cannot
exist returns zero rows and no error. Not measured: a message under five
minutes old, which would need a send; subject filters lagged in that
window (AGENTS.md), so an upgrade that finds nothing should say "not found
yet" rather than "gone". Single quotes in an id are doubled in the filter.

Shape decided: a new `tools/mail/migrate.py` beside export.py, plan first.
Implementation split: Claude designs and writes the failing tests, Codex
implements via omni's copilot card loop (offline gate only; nothing live
runs under Codex). The `_id_key`/`_front_matter_id`/`_eml_id` helpers are
promoted to shared names first, as the first (proving) card.
