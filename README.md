# ckm365 — M365 Graph MCP Server

Minimal, auditable Python MCP server talking directly to Microsoft Graph for
mail and calendar, across **one or more M365 tenants** via named account
profiles (never assume a single tenant). Replaces third-party MCP servers
and, eventually, the first-generation ClearKan `integrations/m365` module.

## Consumers

1. **Claude Code** via stdio MCP (`ckm365 serve`)
2. **pydantic-ai agents** via direct in-process registration
   (`ckm365.agent_tools.register` — no MCP transport, no HTTP)
3. Other harnesses later — tool functions stay transport-agnostic

## Principles

- **Lowest possible code** — ~750 code lines (docstrings double as MCP tool
  descriptions and are excluded from that count).
- **Three runtime deps only**: `mcp`, `msal`, `httpx`. No `msgraph-sdk`.
  Managed with `uv`, hash-locked. New deps need explicit sign-off.
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
| `tmp/` | Git-ignored scratch, incl. requirements doc and reference clone |

## License

MIT — see `LICENSE`. Version in `VERSION`; history in `CHANGELOG.md`.
The Softeria `ms-365-mcp-server` was studied as a reference (see
`docs/reference-notes.md`) but no code from it is used here.

## Status

Phase 1 complete and live-verified on two tenants: read, draft-cycle,
attachments, and the gated send tier (incl. cross-tenant + shared
mailboxes). Security + simplification reviews done; deferred findings
tracked on the board (CKM-14/15). Next: admin CLI (CKM-13), test-mailbox
pytest suite (CKM-9), event-driven watch tools (CKM-10), app-only RBAC
mode (CKM-5).
