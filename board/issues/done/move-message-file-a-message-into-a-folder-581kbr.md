---
type: "issue"
title: "move_message — file a message into a folder"
created: "2026-08-05T00:16:00Z"
resource: "oif:ckm/581kbr"
aliases: ["CKM-36"]
kind: "feature"
priority: "medium"
requested_by: "claude"
tags: ["mail", "write-tier", "triage"]
depends_on: ["edcgfw"]
depends_on_aliases: ["CKM-33"]
---

claude (2026-08-05): triage needs somewhere to PUT things. Today the
server can read mail and (with CKM-33/34) change its read and flag state,
but cannot file it. That leaves "processed" and "unprocessed" mail sitting
in the same folder, distinguishable only by a read bit that the human's
own mail client will also change.

Sketch (write tier, same scope as CKM-33/34):
- move_message(message_ids, destination: str) where destination is a
  well-known name (archive, deleteditems, ...) or a folder id, mirroring
  list_messages' existing folder argument so callers learn one convention.
- Batch + partial failure, same shape as CKM-33.
- Graph's move returns a NEW message id in the destination folder. Return
  the id mapping {old_id: new_id}; a caller holding the old id after a
  move is holding a dead reference, and silently discarding that mapping
  would produce confusing 404s later.
- Refuse to create folders implicitly. An unknown destination is an error
  listing the available folders, not a new folder appearing in someone's
  mailbox as a side effect.

DELIBERATELY NOT INCLUDED: delete. Moving to Deleted Items is reachable
via this tool and is reversible; permanent deletion is not, and does not
belong in an agent-callable surface.

Out of scope v1: copy (as opposed to move), moving between mailboxes, and
creating folders.
