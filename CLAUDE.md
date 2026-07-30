# ckm365 — working agreements

Minimal Python MCP server for Microsoft Graph mail + calendar. **Start every
session with `AGENTS.md`** — it chains to everything else (requirements,
board workflow, verification steps, gotchas). Full requirements live in
`tmp/m365-mcp-requirements.md` (git-ignored working doc — read it at session
start; ask seanwy if missing).

## Hard rules

- **Multi-tenant**: never assume one tenant. Named profiles, each with a
  pinned tenant-ID authority — never the `common` authority.
- **Deps**: exactly `mcp`, `msal`, `httpx` via uv (hash-locked). Any new
  dependency needs seanwy's explicit sign-off first.
- **Line budget**: ~600–800 lines for phase 1. If a file outgrows its budget,
  stop and propose better abstractions.
- **Mail writes are draft-only**: seed replies/forwards with Graph
  `createReply`/`createReplyAll`/`createForward`, then PATCH the returned
  draft. Never PATCH a non-draft. No sending in phase 1.
- **Read-only by default**: write tools exist only behind an explicit flag.
- **Anything touching a tenant** (app registrations, consent, RBAC, mailbox
  creation) is interactive — propose exact commands, seanwy runs/approves.
- **No secrets in repo**; never log message bodies or tokens.

## Task board

`board/` is a ClearKan board — manage it with the `clearkan-lite` skill
(`.claude/skills/clearkan-lite/`). Keep issue moves/history current.

## Reference

- `docs/reference-notes.md` — Softeria ms-365-mcp-server study (phase 0)
- `docs/module-layout-proposal.md` — module layout awaiting approval
- `tmp/softeria-ref/` — reference clone (MIT; study only, never vendor)
- Old client being replaced: the first-generation ClearKan `integrations/m365`
  module (private repo)
