---
type: issue
title: "Shared-instance mode: duplicate serve processes cost ~1.4 GB PSS"
created: "2026-09-16T02:10:00Z"
resource: "oif:ckm/dqgcdk"
kind: "improvement"
priority: "low"
requested_by: "claude"
tags: ["serve", "mcp", "memory", "architecture", "needs-signoff"]
---

Reported by another agent session and independently reproduced here with
the same method, on the same host. Every Claude session spawns its own
`uv run --directory ... ckm365 serve --preset mail,calendar --write
--enable-send`, which forks a python child. All instances run identical
config against the same mailbox.

MEASURED (PSS, not RSS, so no double-counting):

    ckm365 python  : 20 proc   1231 MB PSS   1715 MB RSS   (62 MB PSS each)
    uv run wrapper : 18 proc    163 MB PSS    637 MB RSS   ( 9 MB PSS each)
    TOTAL          : 38 proc   1394 MB PSS   2353 MB RSS

The cost is the real servers at 62 MB PSS each. The reporter initially read
the `uv run` wrappers as ~650 MB of overhead from RSS and corrected it
before reporting: they share nearly all their pages, so dropping `uv run`
for a direct venv python buys 163 MB at best and is NOT the lever. Do not
act on the RSS figure.

NOT URGENT. Nothing is under pressure — 25.4 GB available of 38.9 GB, swap
untouched. This is an efficiency finding, not an incident.

## What the code already answers

**Token refresh is ALREADY shared, which inverts the concern raised.** The
worry was that N servers are N independent failure domains and that one
shared refresh is a new single point of failure with a thundering herd on
expiry. The cache is per PROFILE, not per process — `state_dir()/
{profile}.msal.json` (auth.py:59) — and `Auth._lock()` (auth.py:76) is an
explicit CROSS-PROCESS flock whose docstring says it "guards two servers
refreshing the same rotated refresh token", with reload-before-access.

So there are not N failure domains today. There is one shared rotated
refresh token with N processes contending on one flock, and the thundering
herd is what we have NOW. Consolidation removes contention rather than
introducing a shared point of failure; the shared point already exists.

**Per-session state is not a blocker.** The watch tools are stateless
server-side: `list_new_messages(ctx, delta_token)` takes the cursor as a
parameter and returns the next one — "the caller owns the cadence and
carries the delta_token between calls" (tools/watch.py). `wait_for_message`
is a blocking loop over that and holds nothing beyond its own frame. `Ctx`'s
only mutable state is `_graphs`, a per-profile Graph cache behind a lock,
which is exactly what you would want shared.

**But `wait_for_message` BLOCKS, and that is the real design problem nobody
raised.** It holds a tool call open for up to `timeout_s`. One daemon
serving N clients needs genuine concurrency or one waiting client blocks
every other client's calls. That is a bigger change than the transport.

**Option "does one serve already take N clients" is a non-starter.** `serve`
is stdio only (`mcp.run()`, server.py:120) and stdio is one client per
process by construction — stdin/stdout is a pipe pair to a single parent.

## Why this needs sign-off, not just a design

1. `tmp/m365-mcp-requirements.md` line 74: "The server binds to stdio only
   in phase 1 — no HTTP listener until there's a concrete need." An HTTP/SSE
   daemon contradicts a stated requirement. This finding may well BE the
   concrete need, but that is seanwy's call to make.
2. Capability tiers are load-bearing security here. Tier is process-wide,
   set once from the CLI flags, and the token SCOPES differ per tier
   (`DELEGATED_RO` / `RW` / `SEND` in auth.py). Every session currently runs
   `--write --enable-send`. A shared daemon widens the blast radius: any
   connected client could send mail as the owner. The reporter's own
   suggestion — a shared READ-ONLY instance plus a separate opt-in write
   instance — is the right shape and fits the existing tier discipline,
   because a read-only daemon would hold a genuinely weaker token rather
   than merely a policy flag.

## Shape if it is ever approved

Read-only shared daemon first, write and send left per-session. That
captures most of the memory (most sessions never write) while making the
blast radius strictly smaller than today, not larger. Concurrency for
`wait_for_message` has to be solved before any of it. Re-measure with PSS
afterwards; the reporter offered to.
