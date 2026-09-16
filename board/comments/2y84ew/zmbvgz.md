---
type: comment
at: "2026-07-30T14:06:00Z"
by: "claude"
event: "moved"
---

Done. Implemented: Ctx._graphs_lock around the graph() miss path; Graph.close(); Ctx.close() + __enter__/__exit__; Auth._lock() now holds a threading.Lock AND documents that flock-on-own-fd also serialises in-process threads (load-bearing, must not be optimised away). Contract documented in context.py, agent_tools.py, README, AGENTS.md. Offline: 3 new tests (20-thread barrier race yields one Graph; close() closes httpx client + idempotent; context-manager form) — 58 passed. Live-verified on a real tenant: ckm365 doctor OK, live-smoke OK, CKM365_LIVE_ACCOUNT=<profile> pytest tests/test_live.py 5 passed.
