---
type: comment
at: "2026-07-30T04:03:33Z"
by: "claude"
event: "moved"
---

create/remove-test-mailbox.ps1 written (tst.*-only guard on remove; first interactive run pending when a dedicated test mailbox is wanted). tests/test_live.py: env-gated zero-residue integration suite (read path, full draft cycle w/ attachment+update+delete+404 check, non-draft refusal, calendar cycle, delta bootstrap) — verified live against BOTH tenants (5/5 each). Dependency on CKM-5 dropped: delegated auth suffices. Moved backlog -> done
