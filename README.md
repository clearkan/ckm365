# ckm365 — M365 Graph MCP Server

Minimal, auditable Python MCP server talking directly to Microsoft Graph for
mail and calendar, across **one or more M365 tenants** via named account
profiles (never assume a single tenant). Replaces third-party MCP servers
and, eventually, the first-generation ClearKan `integrations/m365` module.

## Consumers

1. **Claude Code** via stdio MCP (`ckm365 serve`)
2. **pydantic-ai agents** via direct in-process registration
   (`ckm365.agent_tools.register` — no MCP transport, no HTTP)
3. **Plain Python** via the supported programmatic API (below) — no MCP,
   no agent; this is how ClearKan's intake daemon consumes ckm365

All consumers share one thread-safety contract: **`Ctx`/`Graph`/`Auth` are
safe for concurrent use across threads** — one `Ctx` may serve many threads
(e.g. `asyncio.to_thread` callers). Call `Ctx.close()` on shutdown, or use
`with Ctx.create(...) as ctx:`, to release the httpx connection pools.

## Supported programmatic API

The following surface is supported and covered by SemVer from v1.4.0
onward (renames or signature breaks are a major bump; an import-contract
test in `tests/test_offline.py` fails loudly on drift):

- `ckm365.tools.Ctx` — `create()`, `profile()`, `graph()`, `set_graph()`,
  `target()`, `require_write()`, `require_send()`, `close()`, and the
  context-manager form
- The tool functions in `ckm365.tools.mail`, `.calendar`, `.watch`, and
  `.accounts` — plain typed callables taking `Ctx` as first argument
- The pydantic models they return (`ckm365.models`)
- `ckm365.graph.Graph(transport=...)` for httpx `MockTransport` injection
  in consumer test suites

Everything else (`auth.py` internals, `server.py`, underscore-prefixed
helpers) may change in any release. Worked example:
`docs/usage-modes.md` → "Programmatic use (no MCP, no agent)".

Installing as a dependency: `ckm365 @ git+<repo-url>@vX.Y.Z` pulls only
the core (`httpx`/`msal`/`pydantic`); add the `[mcp]` extra only if you
run `ckm365 serve` from that environment.

## Principles

- **Lowest possible code** — ~750 code lines (docstrings double as MCP tool
  descriptions and are excluded from that count).
- **Three core runtime deps only**: `httpx`, `msal`, `pydantic`. No
  `msgraph-sdk`. `mcp` is an **optional extra** (`ckm365[mcp]`) needed
  only by the `ckm365 serve` front door — programmatic consumers stay
  unpinned from the MCP SDK's majors. Managed with `uv`, hash-locked.
  New deps need explicit sign-off.
- **Tiered capability, deny by default** — see the table below. Sending is
  never part of the default consent set.
- **Draft-only mail writes** — replies/forwards seeded via Graph
  `createReply`/`createReplyAll`/`createForward`, then PATCHed (with
  `If-Match`); never modify delivered messages. `send_draft` only sends
  drafts, and only in the send tier.
- **No secrets in repo** — env vars or key material outside git only; token
  caches are 0600 files under `~/.local/state/ckm365/` with cross-process
  locking. Logs carry ids and counts, never bodies, subjects, or tokens.

## Capability tiers

| Server flags | Tools exposed | Delegated scopes requested |
|---|---|---|
| *(none)* | reads + `list_accounts` | `Mail.Read[.Shared]`, `Calendars.Read[.Shared]` |
| `--write` | + draft/calendar writes, attachments | `*.ReadWrite[.Shared]` |
| `--write --enable-send` | + `send_draft`, attendee-bearing event writes, meeting responses | + `Mail.Send[.Shared]` |

Send consent is a deliberate per-tenant opt-in (`scripts/add-send-scopes.sh`)
on top of the base consent from `scripts/create-app-registration.sh`.

## Setup

```sh
uv sync
cp profiles.example.toml ~/.config/ckm365/profiles.toml   # then edit
uv run ckm365 login <profile>                             # device-code flow
uv run python scripts/live-smoke.py <profile>             # verify
```

Register with Claude Code (pick the tier deliberately; `--scope user` makes
it available in every session):

```sh
claude mcp add --scope user ckm365 -- uv run --directory /path/to/ckm365 \
  ckm365 serve --preset mail,calendar --write --enable-send
```

**See `docs/usage-modes.md`** for the concrete setups: multi-tenant operator
with shared mailboxes, personal single-account use, and the planned
headless/app-only mode. Joining a tenant that already runs ckm365?
**`docs/onboarding.md`** is the five-step quickstart.

## Layout

| Path | Purpose |
|---|---|
| `AGENTS.md` | Entry point for agent sessions: workflow, conventions, gotchas |
| `src/ckm365/` | The server: config, auth, graph client, tools, front doors |
| `docs/` | Usage modes, reference notes, design docs |
| `board/` | Local ClearKan task board (see `.claude/skills/clearkan-lite/`) |
| `scripts/` | Tenant setup (interactive) + live smoke tests |
| `tmp/` | Git-ignored scratch, incl. the requirements doc |

## License

MIT — see `LICENSE`. Version in `VERSION`; history in `CHANGELOG.md`.
The Softeria `ms-365-mcp-server` was studied as a reference (see
`docs/reference-notes.md`) but no code from it is used here.

## Status

Phases 1–2 complete and live-verified on two tenants: 19 tools (mail /
calendar / watch / accounts), three-tier gating, admin CLI, live
integration suite, and — as of v1.4.0 — the thread-safety contract and
the supported programmatic API (SemVer'd; releases are tagged `vX.Y.Z`
for downstream pinning). Security + simplification reviews done. Next:
app-only RBAC mode (CKM-5, prep done, interactive sitting pending),
SharePoint/Teams file sync (CKM-18).
