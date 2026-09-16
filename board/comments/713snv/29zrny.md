---
type: comment
at: "2026-08-05T12:30:00Z"
by: "claude"
event: "completed"
---

Done in v2.2.0. flag/unflag/complete_flag share CKM-33's batching and partial-failure convention exactly. A dateless flag is the default. Zone resolution: an offset in the value (normalised to UTC) -> the timezone argument -> a new optional timezone key on the profile; none of those raises rather than guessing, and the zone used is reported back. Design note worth recording: the issue said "default to the profile/mailbox timezone", and the MAILBOX half is not reachable — /mailboxSettings needs MailboxSettings.Read, a scope this app deliberately does not request, so probing it would cost a round trip and 403 in every current deployment. Profile config only, documented in profiles.example.toml. Supplying only due defaults start to now (Graph wants both) rather than failing, as specified. Live-verified on two tenants; flagStatus read back as flagged/complete/notFlagged. Reminders, categories and calendar flags stayed out.
