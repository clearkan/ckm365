---
type: comment
resource: oif:ckm/tc3vj9/r5w8hm
at: '2026-11-07T02:30:00+00:00'
by: claude
---

Built (card y4k7gp), OPT-IN per profile: `compose_font` (e.g.
"Calibri,sans-serif") and `compose_size` (default 11pt) in
profiles.toml. Each composed `<p>` without a font gets Outlook's own
span and margin; the signature and update_draft are untouched. Opt-in
because ckm365 cannot read the mailbox font without MailboxSettings.Read
and tenants differ (Calibri 11 vs Aptos 12). Left in backlog until
seanwy checks the rendering in Outlook (the verification steps above).
