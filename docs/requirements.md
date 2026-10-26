# Requirements

The authoritative requirements for ckm365. Where this document and
`CLAUDE.md` disagree, `CLAUDE.md` wins and this file is the one to fix.

This is the public, generic version of the owner's original working brief
(2026-07-30), brought up to date with the decisions made since. Real
tenants, addresses and mailbox names live only in local config. The
placeholders here follow AGENTS.md: `tenant-a.example`, `operator@`, `ops@`.

## Purpose

A minimal, auditable Python MCP server that talks directly to Microsoft
Graph for mail and calendar, with Teams and files as later additive
modules. It replaces dependence on third-party M365 MCP servers. Softeria's
`ms-365-mcp-server` (MIT) was a reference for study only: nothing is
vendored from it (`docs/reference-notes.md`).

Consumers, in order:

1. **Claude Code** over stdio MCP (`ckm365 serve`).
2. **pydantic-ai agents** through in-process tool registration
   (`agent_tools.py`): plain typed Python functions, no transport.
3. **Other harnesses and programs**, through the SemVer'd programmatic
   surface (`ckm365.tools`), which ClearKan consumes. Tool functions stay
   transport-agnostic so this keeps working.

## Guiding principles

- **Simplicity, not a line budget.** The original 600-800 line target is
  retired (2026-08-01). Prefer the obvious implementation, one file per
  concern, no abstraction until a second caller needs it. A module that is
  no longer easy to read end to end is the signal to propose better
  abstractions.
- **Smallest dependency surface.** Core runtime deps are exactly `httpx`
  and `msal`, hash-locked with `uv`. `mcp` is an optional extra used only
  by `ckm365 serve`. Never `msgraph-sdk`: Graph is clean REST. Any new
  dependency needs the owner's explicit sign-off.
- **Tool functions are the core artifact.** Plain typed functions taking a
  `Ctx` and returning stdlib dataclass models. The front doors (`server.py`,
  `agent_tools.py`) hold nothing Graph-specific. Docstrings become the MCP
  tool descriptions, so they are written to teach agents.
- **Read-only by default**, with capability tiers that are load-bearing
  security (see Security).

## Tenancy and auth

- **Multi-tenant is mandatory.** Named profiles in
  `~/.config/ckm365/profiles.toml`, each with a PINNED tenant-ID authority.
  Never the `common` authority: refresh tokens issued via `common` are
  rejected on first refresh and sessions die after about an hour.
- **Two auth modes:**
  1. **Delegated (device code)** for interactive use. Scopes cover mail and
     calendar read/write plus the `.Shared` variants, which reach shared
     mailboxes (e.g. `ops@tenant-a.example`) the signed-in user has
     FullAccess to. Send scopes only for profiles that need the send tier.
  2. **App-only (client credential)** for headless servers. Application
     permissions scoped down with **RBAC for Applications in Exchange
     Online**, never the legacy Application Access Policy. Certificate
     credential preferred over a secret. See `docs/app-only-setup.md`.
- **A dedicated app registration** for this server, never shared with
  another connector, so scopes and secrets stay isolated.
- **Token caches** are per profile, file-based with mode 600 and a
  cross-process lock (`auth.py`).
- **Mailbox targeting:** every mail and calendar tool takes an optional
  `mailbox`. It defaults to the signed-in user in delegated mode and is
  required in app-only mode. Graph path shape: `/users/{mailbox}/...`.
- **Client tenants** where the operator is a guest or non-admin member
  cannot use the admin-consent path; see the publisher-verification issue
  on the board.

## Mail semantics

- **Never compose replies or forwards from scratch.** Seed with Graph
  `createReply`, `createReplyAll` or `createForward` so the server builds
  the quoted history, inline images and threading headers, then PATCH our
  text into the top of the returned draft.
- **Only ever PATCH drafts** (`isDraft = true`) for content. This keeps the
  server inside plain `Mail.ReadWrite` and clear of the `Mail-Advanced`
  enforcement on non-draft subject, body and recipient changes. Metadata
  changes on delivered mail (read state, flags, moves, categories) are a
  different class and are write-tier.
- **Forward recipients** go in the `createForward` body, never onto a
  delivered message.
- **Sending** exists only as `send_draft` and related send-tier tools,
  behind the double gate described below.

## Tool surface

The live surface is in the README and the docstrings. The shape:

- **Presets** limit tools per session: `mail`, `calendar`, `all`, plus
  separately consented ones such as `teams` and `meetings`, which `all`
  deliberately excludes.
- **Phase 1** (done): mail and calendar read, draft-only writes.
- **Phase 2** (done): Teams discovery, read-only, on its own consent tier.
  Meeting transcripts are in progress.
- **Phase 3**: files (OneDrive/SharePoint). Backlog. It must be a purely
  additive module over `graph.py`.

## Test mailboxes

- **Shared mailboxes** (no licence cost) with a consistent naming prefix
  kept in local config, created and torn down by script, never by hand.
- Mailbox creation is Exchange Online PowerShell (`New-Mailbox -Shared`);
  Entra-side work uses `az` or Graph.
- Test mailboxes sit inside the app-only RBAC management scope.
- The live suites (`tests/test_live.py`, `tests/test_live_send_cycle.py`)
  are env-gated, leave zero residue, and only the send-cycle test sends,
  self-addressed. See AGENTS.md for how to run them.

## Security

- **No secrets in the repo**: env vars or local files with restrictive
  permissions only. `.env.example` documents the variables.
- **No real identifiers in the repo**, including infrastructure names and
  commit messages. `scripts/check-identifiers.py` enforces what it can.
- **Capability tiers:** read by default; `--write` for drafts and metadata;
  `--write --enable-send` for anything that leaves the tenant, which also
  needs per-tenant send consent and per-profile `allow_send`.
- **Logging:** tool name, mailbox and ids only. Never bodies, subjects of
  real mail, or tokens.
- **stdio only.** No HTTP listener until there is a concrete need.
- **Local disk:** tools that write mail content to disk are fenced by
  `CKM365_DOWNLOAD_ROOT`, never overwrite, and leave no partial files.

## Working style

- Anything touching a tenant (app registration, consent, RBAC, mailbox
  creation, Exchange grants) is interactive. Propose the exact commands;
  the owner runs or approves them.
- Propose module layout and helper signatures before building a new area.
- Where ClearKan already has a reusable pattern, flag it for lifting rather
  than rewriting.
- The working loop and verification steps are in AGENTS.md.
