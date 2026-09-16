---
type: "issue"
title: "Public Ctx.set_graph() seam for consumer test injection"
created: "2026-07-30T14:39:43Z"
resource: "oif:ckm/a27cdb"
aliases: ["CKM-22"]
kind: "improvement"
priority: "medium"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["clearkan", "api"]
---

ClearKan follow-up ask A: docs/usage-modes.md pointed consumers at
ctx._graphs for injecting Graph(transport=MockTransport(...)) — a
private field outside the SemVer promise, yet the pattern their whole
offline suite depends on.

- Add Ctx.set_graph(account, graph): validates the profile name, swaps
  under _graphs_lock, closes any replaced instance.
- Bless it: README supported list, import-contract test, and a
  functional offline test (inject mock, call a tool through it).
- Update the docs/usage-modes.md snippet to use it.
