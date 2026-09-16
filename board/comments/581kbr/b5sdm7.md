---
type: comment
at: "2026-08-05T12:30:00Z"
by: "claude"
event: "completed"
---

Done in v2.2.0. move_message takes the same id list + partial-failure shape as CKM-33 and returns the {old_id: new_id} mapping, since a move mints a new id. The destination is resolved ONCE up front against /mailFolders/{dest} (which accepts well-known names and ids alike, so no hardcoded name list is needed): an unknown one raises before anything moves, naming the well-known options and the mailbox's actual top-level folders. No implicit folder creation, no delete tool. Live-verified on two tenants including the unknown-destination refusal and a real Drafts -> Archive move whose new id was then fetched and deleted. Copy, cross-mailbox moves and folder creation stayed out.
