---
type: comment
at: "2026-08-05T12:30:00Z"
by: "claude"
event: "completed"
---

Done in v2.2.0. mark_read/mark_unread land as write-tier tools taking a LIST of ids and returning {ok, failed:[{id,error}]}. $batch WAS used rather than N sequential PATCHes (Graph.batch: 20 sub-requests per round trip, sub-responses re-keyed because Graph answers out of order, per-item failures returned as data, throttled sub-requests re-sent once) — so 25 messages cost 2 calls. Duplicate ids collapse, so ok counts distinct messages; 200 ids max per call. No new consent: Mail.ReadWrite was already in DELEGATED_RW, confirmed against a live tenant. Live-verified on two delegated profiles incl. the partial-failure case (a real id batched with a bogus one gives ok=1 plus one failed entry). Out-of-scope items respected: no whole-folder mark, no filter-driven state change.
