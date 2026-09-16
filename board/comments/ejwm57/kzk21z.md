---
type: comment
at: "2026-07-29T23:51:44Z"
by: "claude"
event: "moved"
---

Implemented per security-review spec (send tier: scopes, registry, require_send, destructive_hint; consent via add-send-scopes.sh on both tenants, no re-login needed). Live-verified 3/3: agent->seanwy with attachment, ops@tenant-a->agent cross-tenant, agent threaded reply->ops; every arrival confirmed from the receiving profile. SendAs rights were already in place on both shared mailboxes. Moved -> done
