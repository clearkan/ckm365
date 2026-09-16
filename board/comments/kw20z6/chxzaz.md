---
type: comment
at: "2026-08-30T12:25:00Z"
by: "claude"
event: "updated"
---

Added GAP 4 from a second live hit — a message whose whole substance was two inline PNGs. has_attachments was false, so the exported OKF record looked complete while carrying only bare cid: markers. The images had to be found via list_attachments, downloaded by attachment_id (both were named image.png), read, and transcribed into the record by hand. Raising priority: this silently loses content from an archive, which is worse than the transcript gaps in this same item.
