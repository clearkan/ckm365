---
type: "issue"
title: "Front doors — server.py (FastMCP/stdio) + agent_tools.py (pydantic-ai) + presets"
created: "2026-07-29T21:47:41Z"
resource: "oif:ckm/gwqa49"
aliases: ["CKM-8"]
kind: "feature"
priority: "medium"
requested_by: "human:seanwy"
tags: ["phase-1", "mcp"]
depends_on: ["1pccze", "7ycsnb"]
depends_on_aliases: ["CKM-6", "CKM-7"]
---

Two thin front doors over the same plain typed tool functions (Pydantic
return models). Nothing Graph-specific in the front doors. Preset groups
mail / calendar / all to limit per-session tool count. Read-only default;
write tools only with explicit opt-in flag at server start. stdio only —
no HTTP listener in phase 1. Log tool name + mailbox + message id, never
bodies or tokens.
