---
type: "issue"
title: "Make mcp an optional extra — core deps become httpx+msal (ClearKan blocker)"
created: "2026-07-31T03:12:41Z"
resource: "oif:ckm/23qy6k"
aliases: ["CKM-26"]
kind: "improvement"
priority: "high"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["clearkan", "packaging"]
---

ClearKan blocker (tmp/clearkan-mcp-dependency-blocker.md +
tmp/clearkan-mcp-optional-followup.md, approved by seanwy): the v1.5.0
mcp>=2.0 floor fix was correct but mcp is a HARD dep, so the floor
propagates to pure programmatic consumers. ClearKan's own board MCP
server needs mcp 1.x (mcp.server.fastmcp was removed in 2.0), so
clearkan[m365] is uninstallable while ckm365 hard-requires mcp>=2.0.
The MCP ecosystem is three unaligned moving parts right now (spec
2026-07-28, mcp SDK 2.0, standalone fastmcp 3.x) — the constraint would
keep recurring.

- pyproject: dependencies = httpx+msal; [project.optional-dependencies]
  mcp = ["mcp>=2.0"]. Keep mcp in the dev group so `uv run ckm365
  serve` from a source checkout (the live Claude Code registrations!)
  still works with a plain `uv sync`.
- server.py _serve: catch ImportError on the lazy import, exit with an
  actionable "install ckm365[mcp]" message.
- Offline test for that error path; wheel metadata verified
  (Requires-Dist ... extra == 'mcp').
- Docs: README principles, CLAUDE.md deps rule, onboarding.
