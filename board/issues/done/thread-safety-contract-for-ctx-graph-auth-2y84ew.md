---
type: "issue"
title: "Thread-safety contract for Ctx/Graph/Auth (ClearKan item 3)"
created: "2026-07-30T14:02:08Z"
resource: "oif:ckm/2y84ew"
aliases: ["CKM-19"]
kind: "improvement"
priority: "high"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["clearkan", "thread-safety"]
---

ClearKan will call ckm365 from asyncio.to_thread, so concurrent calls hit
one Ctx from multiple threads. Decide + implement + document the contract:
"Ctx/Graph/Auth are safe for concurrent use across threads; call
Ctx.close() on shutdown."

- Ctx.graph(): threading.Lock around the miss path — two threads must
  never construct two Graphs (two httpx.Clients, one orphaned pool) for
  one profile.
- Lifecycle: Graph.close() (closes httpx client), Ctx.close() (closes all
  cached Graphs), Ctx.__enter__/__exit__.
- Auth._lock() docstring: state explicitly that flock on separately
  opened fds ALSO serialises threads within one process, that this is
  load-bearing for the thread-safety contract and must not be "optimised"
  away; add a real threading.Lock alongside (belt and braces).
- Document where consumers will see it: README, agent_tools.py
  docstring, AGENTS.md code map.
- Offline tests: ~20 concurrent ctx.graph() calls yield one Graph;
  close() closes (httpx .is_closed); context-manager form works.

Origin: tmp/clearkan-integration-requirements.md item 3 (the "real ask").
