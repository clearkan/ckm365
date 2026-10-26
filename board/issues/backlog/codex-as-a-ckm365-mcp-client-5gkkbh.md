---
type: "issue"
title: "Codex as a ckm365 MCP client: let Codex sessions use the mail and calendar tools"
created: "2026-10-26T09:40:00Z"
resource: "oif:ckm/5gkkbh"
kind: "feature"
priority: "medium"
requested_by: "human:seanwy"
tags: ["mcp", "codex", "onboarding", "security"]
---

Today ckm365 serves Claude Code only (one stdio registration per machine,
`ckm365 serve --preset mail,calendar`, write and send tiers on). seanwy
wants Codex sessions to use the same tools eventually, so the design has
to allow for it now rather than be retrofitted. seanwy's words, 26 Oct
2026: "eventually too I want codex to be able to use ckm365 so we need to
plan for that."

This is distinct from Codex DEVELOPING ckm365, which runs today through
omni's copilot card loop in a sandbox with no network and no credentials.

## What is known

- Codex CLI 0.162.1 manages MCP servers with `codex mcp add|list|get|
  remove`, stored in `~/.codex/config.toml` under `[mcp_servers.<name>]`
  (command, args, env). Same stdio shape ckm365 already serves to Claude.
- ckm365's registration is one command line plus env vars for the
  app-only profile's certificate. Nothing in it is Claude-specific; the
  server does not know which client it is talking to.
- Ctx, Graph and Auth are safe for concurrent use and the token cache is
  flock-serialised, so a Codex server process and a Claude server process
  on the same machine sharing one cache is already the supported case.

## Questions to answer before switching it on

1. **Where does Codex run an MCP server process?** If it is a child of
   Codex outside the command sandbox, it has network and can read
   `~/.config/ckm365`, which is what the server needs. If it runs inside
   the sandbox it cannot reach Graph at all. Test with a read-only
   registration and `list_accounts`.
2. **Global config leaks into copilot runs.** `~/.codex/config.toml` is
   read by EVERY `codex exec`, including copilot's development cards. A
   global `[mcp_servers.ckm365]` would hand live mailboxes to a sandboxed
   dev run that is supposed to have neither network nor credentials. The
   registration therefore has to be scoped: a Codex profile, a
   per-project config, or copilot passing an override that empties
   `mcp_servers` for card runs. Decide which and verify with a dry run of
   copilot that the tools are absent.
3. **Tiers.** Start Codex at the read tier (no `--write`), move to
   `--write` once the draft-only invariant is observed, and treat
   `--enable-send` as a separate decision by seanwy. Check how Codex's
   approval policy (`-a`) treats MCP tool calls: if `-a never` also waives
   approval for a send tool, the send tier must stay off for Codex.
4. **Tool descriptions.** MCP schemas come from the docstrings. Codex and
   Claude may weight them differently; check the long docstrings do not
   get truncated or ignored by Codex before relying on the gotchas they
   carry (subject filters, compose fence, dedupe).
5. **Logging and audit.** `ckm365 audit` and the log line format do not
   record the client. If two agents share a mailbox, a `client=` field in
   the serve log line may be worth it. Small.

## Proposed order

1. Read-only registration for Codex, scoped so copilot card runs never see
   it (question 2 settled first). Verify question 1 live.
2. `docs/onboarding.md` gains a Codex section mirroring the Claude one.
3. Write tier, then send, each as its own decision.

## Relates to

- h59xfz and mr31re: the copilot development loop, which must keep its
  no-credentials property when this lands.
- CKM-46 item 3 (ba1m7k): `doctor --mcp` cannot see the Claude
  registration either; extend it to Codex's config when it is built.
