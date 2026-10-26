---
type: "issue"
title: "Dedupe exports by RFC 5322 Message-ID: skip or flag a message already on disk"
created: "2026-10-26T05:58:28Z"
resource: "oif:ckm/4qn81m"
kind: "improvement"
priority: "medium"
requested_by: "human:seanwy"
tags: ["mail", "export", "idempotency"]
---

Agents filing mail into a project's `correspondence/` folder cannot tell whether a
message has already been fetched. The Graph `id` is no use for that: it differs per
mailbox (the same message has one id in the sender's Sent Items and another in the
cc'd agent mailbox) and changes when the message is moved. File names are
hand-written slugs, so two sessions file the same message under two names.

The stable key is the RFC 5322 `Message-ID` header, which Graph exposes as
`internetMessageId`. It is the same in every copy of the message in every mailbox,
and `export_message` already writes it into the `.md` front matter as
`internet_message_id`. Measured in a client project repo on 26 Oct 2026: 292 of 349
sidecars carry it (the rest predate the OKF export or came from `.msg` files), and
`grep -l '<the id>' correspondence/*.md` finds a filed message in one call. No
duplicates found, but only because the sessions happened to coordinate.

Proposal, in order of value:

1. `export_message` takes an optional `dedupe_dir`. Before writing it scans that
   directory's `.md` front matter for the message's `internet_message_id`; on a hit
   it returns `{"already_exported": "<path>"}` and writes nothing, unless
   `force=true`. Cheap: one grep over the folder.
2. The `.eml` export does not need a sidecar to be found: the `Message-ID:` header is
   in the MIME, so the scan can cover `.eml` files too.
3. Optionally put a short stable token in the suggested file name, e.g. the first
   8 hex characters of SHA-1(Message-ID), as `YYYYMMDD_<slug>_<token>.md`, so a
   listing alone shows duplicates. Not instead of the slug: humans read the slug.
4. `list_messages` rows could carry `internet_message_id` too, so an agent can
   decide what to fetch before fetching; today it costs a `get_message` per row.

Relates to the bulk export proposal (k4r9tw / CKM-53): "skips what is already there"
needs exactly this key to be idempotent across mailboxes and sessions.

Source: seanwy, client project session, 26 Oct 2026, asking whether M365 has an id that
makes sense for file naming or the sidecar so a session knows a message is already
fetched.
