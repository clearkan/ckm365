---
type: comment
at: "2026-07-30T00:19:13Z"
by: "claude"
event: "moved"
---

seanwy pulled the whole item forward (user-scope send made it timely). ALL items implemented: flock around cache reload/persist; nextLink pinned to GRAPH_BASE; timezone Prefer-header validation; registration script refuses to adopt unowned same-named apps; optional CKM365_ATTACH_ROOT; single-account-per-profile enforced (login evicts, token/username refuse); If-Match on draft PATCHes; state-dir chmod when pre-existing; $search escaping; script input validation + 0600 file creation. RT blast-radius documented in docs/usage-modes.md. 20 offline tests green; live smoke green post-change. Moved -> done
