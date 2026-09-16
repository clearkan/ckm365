---
type: "issue"
title: "Bug: declared mcp floor (>=1.2) is a major version below what server.py needs"
created: "2026-07-30T14:39:43Z"
resource: "oif:ckm/gmffnf"
aliases: ["CKM-21"]
kind: "bug"
priority: "high"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["clearkan", "packaging"]
---

Reported by the ClearKan agent (tmp/clearkan-followup-asks.md item 0),
verified here: pyproject declares mcp>=1.2 but server.py's _serve() does
`from mcp.server.mcpserver import MCPServer`, a module that only exists
from mcp 2.0. Any install resolving mcp 1.x imports fine (the import is
lazily scoped) and then dies with ImportError the moment `ckm365 serve`
runs. Our lock has 2.0.0, which is why it never bit us.

- Bump floor to mcp>=2.0 and re-lock.
- server.py:1 docstring still says "FastMCP/stdio front door" — the
  fastmcp -> MCPServer migration missed it; fix.
