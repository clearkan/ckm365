---
type: comment
at: "2026-07-31T09:33:13Z"
by: "claude"
event: "moved"
---

DONE, released as 2.0.0 (breaking: pydantic methods gone from returned models; attribute surface unchanged). models.py rewritten as stdlib dataclasses with explicit from_graph() projections (SELECT ClassVars kept; same flattening semantics incl. from/emailAddress, location displayName, onlineMeeting joinUrl); all model_validate call sites migrated. Core deps now exactly httpx+msal. FIRST-CLASS TEST PASSED: TypeAdapter(Message) schema + dump/validate round-trip works (what MCP SDK/pydantic-ai rely on), and MCPServer.add_tool accepted all 19 dataclass-returning tools — pydantic consumers lose nothing. VERIFIED: offline 63 passed; clean venv with NO pydantic + NO mcp ran a full MockTransport tool call (projection/set_graph/close); LIVE suite 5/5 delegated + app-only smoke with 403 deny probe — every read path re-verified against real Graph. Docs/CHANGELOG/notes to ClearKan (tmp/clearkan-pydantic-disconnect-notes.md) updated.
