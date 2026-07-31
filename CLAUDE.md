# ckm365 — working agreements

Minimal Python MCP server for Microsoft Graph mail + calendar. **Start every
session with `AGENTS.md`** — it chains to everything else (requirements,
board workflow, verification steps, gotchas). Full requirements live in
`tmp/m365-mcp-requirements.md` (git-ignored working doc — read it at session
start; ask seanwy if missing).

## Hard rules

- **Multi-tenant**: never assume one tenant. Named profiles, each with a
  pinned tenant-ID authority — never the `common` authority.
- **Deps**: core is exactly `httpx`, `msal` via uv
  (hash-locked); `mcp` is an optional extra used only by `ckm365 serve`
  (the dev group carries it so source checkouts serve out of the box).
  Any new dependency needs seanwy's explicit sign-off first.
- **KISS, not a line budget**: there is no hard line limit (the old
  ~600–800 phase-1 number is retired — seanwy, 2026-08-01). Simplicity is
  the goal the number was a proxy for, so optimise for it directly: the
  obvious implementation over the clever one, one file per concern, no
  abstraction until a second caller needs it, no configurability nobody
  asked for. Growth is fine when it buys real capability; ceremony is
  not. If a module stops being easy to read end to end, that is the
  signal to stop and propose better abstractions.
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

- `docs/reference-notes.md` — Softeria ms-365-mcp-server study (phase 0;
  the reference clone itself is deleted — re-clone from GitHub if ever
  needed, study only, never vendor)
- Old client being replaced: the first-generation ClearKan `integrations/m365`
  module (private repo)
