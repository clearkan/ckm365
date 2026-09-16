---
type: "issue"
title: "Attachment tools — list_attachments (read) + add_attachment (draft-only write)"
created: "2026-07-29T23:13:29Z"
resource: "oif:ckm/7dn1c2"
aliases: ["CKM-11"]
kind: "feature"
priority: "medium"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["phase-1", "mail"]
depends_on: ["1pccze"]
depends_on_aliases: ["CKM-6"]
---

seanwy: make sure the initial tooling supports adding attachments.

- list_attachments: metadata only (id, name, contentType, size, isInline)
  — never fetches content bytes into agent context
- add_attachment: local file path (server runs on the agent's machine),
  write-gated, refuses non-drafts, 3 MB direct-attach cap with a clear
  error; contentType guessed from filename when not given
- Graph upload sessions for >3 MB deferred to phase 2
