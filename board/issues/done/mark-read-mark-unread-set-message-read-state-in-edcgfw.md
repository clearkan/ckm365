---
type: "issue"
title: "mark_read / mark_unread — set message read state, in batch"
created: "2026-08-05T00:10:00Z"
resource: "oif:ckm/edcgfw"
aliases: ["CKM-33"]
kind: "feature"
priority: "high"
requested_by: "claude"
tags: ["mail", "write-tier", "triage"]
---

claude (2026-08-05): the server can READ isRead (it is already selected in
list_messages output) but cannot SET it. Hit in real use during a mailbox
triage task whose whole first half was "mark this class of notification
read". Neither the MCP surface nor the `ckm365` CLI exposes it, so the
workaround was a throwaway script importing ckm365.auth + ckm365.config to
mint a read-write token and PATCH /messages/{id} directly — the same
pattern CKM-32 records for attachments, and the same conclusion: the auth
plumbing is already right there, only the tool is missing.

Sketch (write tier — needs Mail.ReadWrite, which the delegated RW scope
set already requests; no new consent beyond read_only=False):
- mark_read(message_ids: list[str]) -> {ok: int, failed: [{id, error}]}
- mark_unread(message_ids: list[str]) -> same shape
- BATCH IS THE POINT, not a convenience. The triage run that motivated
  this touched 25 messages in one pass; a per-message tool is 25 round
  trips and 25 approval prompts in a headless agent. Accept a list even
  for one id.
- Partial failure must not abort the batch. Report per-id outcome and
  keep going — a single 404 on a message moved out from under the caller
  should not strand the other 24.
- Consider Graph's $batch endpoint (20 requests per batch) rather than N
  sequential PATCHes. If sequential is kept for v1, say so explicitly in
  the docstring so the next person does not assume it was considered.
- Return counts, never subjects or addresses. Logging stays
  ids/counts/truncated-ids (repo rule).

Why not "just use move to a Read folder": read state and folder are
independent, and the caller wanted the mail to stay exactly where it was.

Out of scope v1: marking an entire folder read in one call (Graph has no
single operation for it; it is a paged enumerate + batch, which belongs on
top of this once this exists), and any read-state change driven by a
filter rather than an explicit id list — the caller should select first,
then act, so the selection is auditable.
