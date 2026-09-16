---
type: "issue"
title: "Disconnect pydantic from core — dataclass models, pydantic stays first-class"
created: "2026-07-31T09:30:08Z"
resource: "oif:ckm/wxrh02"
aliases: ["CKM-27"]
kind: "improvement"
priority: "high"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["clearkan", "packaging", "api"]
---

seanwy: remove pydantic as a core dependency; treat it as a test of
whether pydantic consumers remain FIRST-CLASS. Design: models.py
becomes stdlib dataclasses with explicit from_graph() projections
(replacing aliases/validators); the SELECT ClassVars stay. pydantic v2
handles stdlib dataclasses natively (TypeAdapter: schema, validation,
serialization), which is exactly what the MCP SDK and pydantic-ai do
under the hood — so both front doors keep working, now against
dataclasses.

Core deps after: httpx + msal only. mcp extra unchanged (brings
pydantic transitively for serve).

Verification bar:
- offline suite green after model_validate -> from_graph migration
- clean venv, no extras: pydantic ABSENT, tool call over MockTransport
  works end to end (the disconnect test)
- first-class test: TypeAdapter(Message) json_schema + dump round-trip
  (what MCP SDK/pydantic-ai rely on)
- MCPServer.add_tool over all presets (schema generation on dataclass
  returns)
- LIVE: full suite on a real tenant + app-only smoke (projection rewrite
  touches every read path)

SemVer: 2.0.0 — the blessed surface said "pydantic models";
model_validate/model_dump disappear from returned objects (attribute
surface unchanged). Notes to ClearKan in tmp/ when done.
