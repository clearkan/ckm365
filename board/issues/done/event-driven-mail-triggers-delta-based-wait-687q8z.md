---
type: "issue"
title: "Event-driven mail triggers — delta-based wait tool + watch CLI (phase 2)"
created: "2026-07-29T22:47:59Z"
resource: "oif:ckm/687q8z"
aliases: ["CKM-10"]
kind: "feature"
priority: "medium"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["phase-2", "agents"]
depends_on: ["gwqa49"]
depends_on_aliases: ["CKM-8"]
---

Let agents react to incoming mail instead of ad-hoc polling. MCP has no
server-initiated agent wake (notifications exist but Claude Code does not
start a turn on them), so phase-2 shapes that work today:

1. wait_for_message tool — long-poll built on Graph delta queries
   (/mailFolders/inbox/messages/delta): tool blocks until new mail or
   timeout, returns summaries + new deltaLink. Works for MCP AND
   pydantic-ai (transport-agnostic function). Mind harness tool timeouts
   (MCP_TOOL_TIMEOUT in Claude Code).
2. list_new_messages(delta_token) — non-blocking incremental variant;
   caller owns cadence (cron/loop).
3. ckm365 watch CLI — exits when new mail matches; run as a Claude Code
   background task so the harness wakes the agent on exit.

seanwy additions (2026-07-30):
- get_watch_command tool (+ MCP server `instructions` at initialize):
  since MCP ships nothing local, the server returns the exact OS-specific
  command line the agent should run for the background-watch pattern
  (server knows its own venv path, entry point, platform, profile).
- Filtered wait lists: watch/wait filters per agent — from_addresses[],
  folder, subject_contains, mailbox — each watcher owns its delta token,
  so several agents (different projects/senders) can wait independently.
  Graph message delta does not support $filter on sender: filter in code.

Later/optional: Graph change-notification webhooks need an HTTPS endpoint
(phase 1 forbids HTTP listeners) or Event Hubs delivery — only if
polling proves insufficient. Keep read-only; no bodies in watch output.
