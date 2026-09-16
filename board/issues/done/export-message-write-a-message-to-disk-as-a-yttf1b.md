---
type: "issue"
title: "export_message — write a message to disk as a greppable repo record"
created: "2026-08-11T10:20:00Z"
resource: "oif:ckm/yttf1b"
aliases: ["CKM-39"]
kind: "feature"
priority: "high"
requested_by: "human:seanwy"
tags: ["mail", "export", "read-tier"]
depends_on: ["28mbps"]
depends_on_aliases: ["CKM-32"]
---

seanwy (2026-08-11): correspondence needs to land in the engagement repos
agents work in, and be GREPPABLE there — the current practice of keeping a
hand-written sidecar .md "extract" of each message alongside the real
artifact is duplicated effort and drifts from the source.

Asked: can we export as .eml or .msg, whichever manages better in git?

Findings that decide the design (measured on a live inbox, 3 messages):
- .msg is out: Outlook's proprietary OLE compound format, binary, not
  greppable, no Graph endpoint produces it, and any writer would be a new
  third-party dependency (needs sign-off, and would still not be greppable).
- .eml IS available for free — GET /messages/{id}/$value returns the raw
  MIME and Graph.download() (CKM-32) already streams it safely.
- BUT raw .eml is NOT reliably greppable: Exchange base64-encodes body
  parts. Sampled 3 real messages — 7bit/7bit, base64+quoted-printable,
  and base64+base64. On the third, a distinctive word from the message's
  own preview did NOT appear in the raw bytes. So .eml alone cannot
  replace the sidecar; that is exactly the failure mode to avoid.

Design (read tier, no new consent — the body is an ordinary message
property under Mail.Read[.Shared]):
- export_message(message_id, dest_path) -> written path + byte count.
  FORMAT IS INFERRED FROM THE EXTENSION, so there is one source of truth
  and the caller states intent naturally:
    .md / .markdown / .txt -> the greppable record (default shape)
    .eml                   -> raw MIME, byte-exact, full fidelity
- The greppable record is deterministic and diff-friendly: YAML front
  matter (subject, from, to, cc, date, Graph id, internet message id,
  mailbox, has_attachments, is_bulk/is_auto_reply, web link), then the
  PLAIN-TEXT body, then an attachment manifest listing name, size, kind
  and attachment_id so download_attachment can fetch the bytes.
- Take the text body from Graph, not from a local HTML converter: the
  Prefer: outlook.body-content-type="text" header (already used by
  get_message) makes Graph do the conversion server-side, so no HTML
  stripping code and no new dependency.
- Same disk discipline as download_attachment: confined by
  CKM365_DOWNLOAD_ROOT (falling back to CKM365_ATTACH_ROOT), never
  overwrites, no residue on failure. Share one helper between the two.
- Logging stays ids/counts only — an export writes real message content
  to disk, so the subject and body must never reach a log line.

Out of scope v1: bulk/threaded export, downloading attachments as a side
effect (the manifest carries the ids — call download_attachment), .msg,
and any HTML-to-markdown rendering beyond what Graph's text conversion
gives.
