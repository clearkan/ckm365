---
type: comment
at: "2026-07-31T03:15:19Z"
by: "claude"
event: "moved"
---

Done. mcp moved to [project.optional-dependencies] mcp (>=2.0 floor preserved); core deps httpx/msal/PYDANTIC — pydantic was always a direct dep (models.py) but undeclared, riding in via mcp; the clean-venv acceptance test caught the break and it is now declared (flagged to seanwy). serve exits 1 with an install-hint message when mcp is absent (offline test added). dev group mirrors the extra so uv sync / live Claude Code registrations serve unchanged (verified import in dev env). VERIFIED: wheel metadata (Requires-Dist httpx/msal/pydantic; mcp;extra==mcp); clean venv WITHOUT extra -> ckm365.tools/models import OK, mcp absent, ckm365 serve exit 1 with actionable message; same venv WITH [mcp] extra -> mcp.server.mcpserver imports. Offline suite 61 passed. Docs: README principles + install note, CLAUDE.md deps rule, onboarding step 1.
