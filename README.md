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
- The tool functions in `ckm365.tools.mail`, `.calendar`, `.watch`,
  `.accounts`, and `.teams` — plain typed callables taking `Ctx` first
- The models they return (`ckm365.models` — stdlib dataclasses;
  pydantic v2 treats them as first-class via `TypeAdapter`, which is
  what the MCP SDK and pydantic-ai do, and a test pins that contract)
- `ckm365.graph.Graph(transport=...)` for httpx `MockTransport` injection
  in consumer test suites

Everything else (`auth.py` internals, `server.py`, underscore-prefixed
helpers) may change in any release. Worked example:
`docs/usage-modes.md` → "Programmatic use (no MCP, no agent)".
For a Graph endpoint the tools don't cover yet, **`docs/graph-direct.md`**
is the sanctioned escape hatch — reuse the server's auth/retry plumbing,
keep the tier rules, file the gap on the board.

Installing as a dependency: `ckm365 @ git+<repo-url>@vX.Y.Z` pulls only
the core (`httpx`/`msal` — nothing else, not even pydantic); add the
`[mcp]` extra only if you run `ckm365 serve` from that environment.

## Principles

- **KISS** — the obvious implementation over the clever one, one file per
  concern, no abstraction before a second caller needs it. Currently
  no single module exceeds ~400 lines; when `tools/mail.py` passed 1000 it
  was split into a package (`common`/`disk`/`read`/`attachments`/`export`/
  `drafts`/`triage`) that still re-exports one import path. There is no
  hard line limit — readability is the constraint that matters.
- **Two core runtime deps only**: `httpx`, `msal`. No
  `msgraph-sdk`. `mcp` is an **optional extra** (`ckm365[mcp]`) needed
  only by the `ckm365 serve` front door — programmatic consumers stay
  unpinned from the MCP SDK's majors. Managed with `uv`, hash-locked.
  New deps need explicit sign-off.
- **Tiered capability, deny by default** — see the table below. Sending is
  never part of the default consent set.
- **Draft-only mail writes** — replies/forwards seeded via Graph
  `createReply`/`createReplyAll`/`createForward`, then PATCHed (with
  `If-Match`) into a FENCED region, so `revise_draft` can rewrite what you
  wrote without disturbing the quoted history or the signature; never
  modify delivered message CONTENT. `send_draft` only
  sends drafts, and only in the send tier. The triage tools are the one
  thing that touches delivered mail, and only its metadata (read state,
  flag, folder) — write tier, never send tier, since nothing leaves the
  tenant.
- **No secrets in repo** — env vars or key material outside git only; token
  caches are 0600 files under `~/.local/state/ckm365/` with cross-process
  locking. Logs carry ids and counts, never bodies, subjects, or tokens.

## Capability tiers

| Server flags | Tools exposed | Delegated scopes requested |
|---|---|---|
| *(none)* | reads + `list_accounts` + `download_attachment` + `export_message` + `verify_message` | `Mail.Read[.Shared]`, `Calendars.Read[.Shared]` |
| `--write` | + draft/calendar writes, attachments, triage (read state, flags, move) | `*.ReadWrite[.Shared]` |
| `--write --enable-send` | + `send_draft`, attendee-bearing event writes, meeting responses | + `Mail.Send[.Shared]` |

Send consent is a deliberate per-tenant opt-in (`scripts/add-send-scopes.sh`)
on top of the base consent from `scripts/create-app-registration.sh`.

`download_attachment` and `export_message` sit in the read tier because
they only READ the mailbox — but they write bytes to the server's local
disk, which is what `CKM365_DOWNLOAD_ROOT` (falling back to
`CKM365_ATTACH_ROOT`) is for: set it and both are confined to that
directory.

The `teams` preset (read-only discovery: `list_teams`, `list_channels`,
`list_installed_apps`) sits **outside** that ladder on its own consent
tier (`scripts/add-teams-scopes.sh`) — a mail `--write` flag never implies
the ability to enumerate Teams, and the preset has no write tier at all.
It is also excluded from `--preset all` on purpose: name it explicitly
(`--preset mail,calendar,teams`) so it never appears in a session that
has not consented to it.

## Correspondence in a repo

`export_message` writes one message to a file, and the extension picks the
format: **`.md`** for a greppable record or **`.eml`** for byte-exact MIME.

The `.md` record is an **[Open Knowledge Format](https://openknowledgeformat.com/)
v0.1 document** — YAML front matter with OKF's
`type`/`title`/`description`/`resource`/`tags`/`timestamp`, mail-specific
extension keys beneath it (from, to, cc, mailbox, message ids, bulk and
auto-reply flags), the body as plain text, then an attachment manifest
carrying the ids `download_attachment` needs. It drops into an `okf/` repo
unmodified, and `tags` carries the facets worth filtering on (`email`,
`inbound`/`outbound`, `attachments`, `bulk`, `auto-reply`). Re-exporting a
message is byte-identical, so git shows no diff.

Prefer `.md` for anything agents will search —
Exchange base64-encodes body parts, so a raw `.eml` often contains none of
the words in the message (measured: greppable 7/10 for `.eml` vs 10/10 for
`.md`, at 4–7× the size). `.msg` is not offered: no Graph endpoint
produces it, it is binary, and writing it would need a third-party
dependency.

## The compose loop

Composing a reply is `create_reply_draft` → `revise_draft` →
`add_attachment` / `remove_attachment` → `verify_message` → `send_draft`,
with `discard_draft` for "start again".

What each one exists to stop you hand-rolling:

- **`revise_draft`** replaces only the text you wrote. `update_draft`'s
  `body_html` replaces the WHOLE body, which on a reply throws away the
  quoted history Graph assembled; the tools fence their own region with
  HTML comments (`<!--ckm365:body-->`, invisible in every mail client) and
  `revise_draft` rewrites what is inside it. On a draft written elsewhere
  it inserts at the top of the body and fences that, so the next revision
  replaces properly.
- **`signature_html`** on the profile (`profiles.toml`) is appended below
  your text at draft creation — `signature=False` skips it for one call —
  and sits in its own fence, so revising the text above never disturbs it.
  It is local by design: Outlook's roaming signature would need
  `MailboxSettings.Read`, a scope this app deliberately never requests.
- **`discard_draft`** throws away a draft (and only a draft — Graph moves
  it to Deleted Items, so it is recoverable). Switching a reply to a
  reply-all is discard + `create_reply_draft(reply_all=True)`: Graph fixes
  the recipients when it seeds the draft.
- **`remove_attachment`** is `add_attachment`'s inverse, drafts only.
- **`verify_message`** is read tier and answers the pre-send questions in
  one call: recipients, attachment names/sizes/kinds, did the quoted
  thread survive, is the signature still there, and which non-ASCII
  characters are in the text you wrote (the smart-quote check — reported,
  never corrected). Run it on the draft, then on the sent copy.

## Setup

```sh
uv sync
mkdir -p -m 700 ~/.config/ckm365                          # holds profiles + certs/
cp profiles.example.toml ~/.config/ckm365/profiles.toml   # then edit
uv run ckm365 login <profile>                             # device-code flow
uv run ckm365 doctor                                      # config/login/consent
uv run python scripts/live-smoke.py <profile>             # verify the READ path
uv run python scripts/draft-cycle-smoke.py <profile>      # verify the WRITE path
```

Register with Claude Code (pick the tier deliberately; `--scope user` makes
it available in every session):

```sh
claude mcp add --scope user ckm365 -- uv run --directory /path/to/ckm365 \
  ckm365 serve --preset mail,calendar --write --enable-send
```

App-only (`client_credential`) profiles need their credential in the
**server's own** environment. Exporting it from your shell rc reaches the
server only if Claude Code was itself started from a shell that sourced
that rc, so pass it explicitly instead — only a path and a thumbprint land
in `.claude.json`, never key material:

```sh
claude mcp add --scope user ckm365 \
  -e CKM365_TENANT_A_APP_CLIENT_CERT_PATH=$HOME/.config/ckm365/certs/tenant-a-app.key.pem \
  -e CKM365_TENANT_A_APP_CLIENT_CERT_THUMBPRINT=<sha1-thumbprint> \
  -- uv run --directory /path/to/ckm365 \
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

Phases 1–2 complete and live-verified on two tenants: 32 tools (mail /
calendar / watch / accounts / teams / meetings), three-tier gating, admin
CLI, live integration suite, the thread-safety contract and supported
programmatic API (SemVer'd; releases are tagged `vX.Y.Z` for downstream
pinning), and app-only mode with Exchange RBAC-only scoping (v1.6.0, incl.
the out-of-scope 403 negative test). v2.0.0 slims the core to two deps with
dataclass models; v2.1.0 adds read-only Teams discovery; v2.2.0 adds the
mail triage slice — batched read-state/flag/move tools and reliable
server-side filtering; v2.3.0 puts `to`/`cc` on every listing row and adds
curated internet headers for bulk/auto-reply detection; v2.4.0 adds
read-tier `download_attachment` (attachment bytes streamed to disk, never
into agent context); v2.5.0 adds `export_message` (a message as a
greppable `.md` record or raw `.eml`) and an opt-in live send-cycle test
covering the send tier end to end; v2.6.0 closes the compose loop
(`revise_draft`, `discard_draft`, `remove_attachment`, read-tier
`verify_message`, and per-profile HTML signatures) — offline-verified;
its live draft-cycle run is still outstanding. Security + simplification
reviews done. Next: SharePoint/Teams file sync (CKM-18).
