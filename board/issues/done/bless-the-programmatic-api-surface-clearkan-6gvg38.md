---
type: "issue"
title: "Bless the programmatic API surface (ClearKan item 4)"
created: "2026-07-30T14:02:08Z"
resource: "oif:ckm/6gvg38"
aliases: ["CKM-20"]
kind: "task"
priority: "medium"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["clearkan", "docs", "api"]
depends_on: ["2y84ew"]
depends_on_aliases: ["CKM-19"]
---

ClearKan's intake daemon wants neither MCP nor an LLM agent — it calls
the tool functions directly. Declare that surface supported (option (a)
from their doc — no facade):

- README + AGENTS.md: supported programmatic surface is
  ckm365.tools.Ctx (create/target/profile/require_*/close), the tool
  functions in ckm365.tools.{mail,calendar,watch,accounts}, the models
  they return, and Graph(transport=...) for test injection. SemVer
  applies from the next tag.
- docs/usage-modes.md: "Programmatic use (no MCP, no agent)" section
  with a CORRECT example — list_new_messages returns a dict
  {"messages", "delta_token", "matched"}, NOT a tuple (their sample was
  wrong; bless the API as it is). Show Ctx pinning via account= and
  `with Ctx.create(...) as ctx:`.
- Trivial offline test importing the blessed names — an import contract
  that fails loudly on rename.

Origin: tmp/clearkan-integration-requirements.md item 4.
