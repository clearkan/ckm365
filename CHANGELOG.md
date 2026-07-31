# Changelog

All notable changes to ckm365 are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

## [2.1.0] — 2026-08-01

### Added
- **`teams` preset — read-only Teams discovery** (CKM-25, the option-(c)
  slice from the CKM-24 decision): `list_teams`, `list_channels`,
  `list_installed_apps`, plus `Team`/`Channel`/`InstalledApp` models.
  Turns names into the team/channel ids that downstream systems
  otherwise hard-code in env vars. 22 tools total.
- `scripts/add-teams-scopes.sh` — the separate, deliberate consent tier
  (delegated `Team.ReadBasic.All`, `Channel.ReadBasic.All`,
  `TeamsAppInstallation.ReadForTeam`), dry-run by default, **merging**
  into the app's existing permissions rather than replacing them, with
  the usual grant-verified consent loop.
- `scripts/live-smoke.py --teams` — exercises the three reads and
  reports a missing consent tier as a skip, not a failure.

### Notes
- **Teams consent is never implied by mail/calendar.** The preset has no
  write or send tier, and its scopes live outside the read → `--write` →
  `--enable-send` ladder. `--preset all` also **excludes** teams by
  design (it now means mail+calendar): a preset needing its own consent
  must be named explicitly, so existing sessions gain no tools that would
  403 and no extra schema in their token budget.
- **Auth-mode asymmetry, by design:** delegated tokens list only the
  signed-in user's teams (`/me/joinedTeams`); app-only has no "me" and
  lists every team in the tenant (`/teams`). Exchange
  RBAC-for-Applications does NOT constrain Teams, so there is no
  mailbox-style scope to fall back on — prefer delegated, or use Teams
  resource-specific consent (RSC) per team.
- Bot Framework messaging remains out of scope permanently under the
  CKM-24 decision.
- **Live verification is PENDING the consent step** (tenant-touching, so
  the owner runs it): offline tests and the pre-consent 403 path are
  verified; the post-consent reads are not yet.

## [2.0.0] — 2026-07-31

**Breaking:** pydantic is disconnected from the core (CKM-27). Models in
`ckm365.models` are now **stdlib dataclasses** built via
`Model.from_graph(dict)` — the attribute surface (field names, types,
defaults, nesting) is unchanged, but pydantic-specific methods
(`model_validate`, `model_dump`, …) no longer exist on returned objects.
Core runtime deps are now exactly `httpx` + `msal`.

The disconnect doubled as a first-class-support test, and pydantic
consumers pass it: pydantic v2 treats stdlib dataclasses natively
(`TypeAdapter` schema/validation/serialization — exactly what the MCP SDK
and pydantic-ai do with tool return types). Two new offline tests pin
that contract: a `TypeAdapter(Message)` schema + dump/validate round-trip,
and `MCPServer.add_tool` over all 19 tools with dataclass returns.

Verified: offline suite 63 passed; clean-venv install with NO pydantic
and NO mcp runs a full tool call over `MockTransport` (projection,
`set_graph`, `close`); live suite 5/5 on the delegated profile and
app-only smoke incl. the 403 deny probe — every read path re-verified
against real Graph through the new projections.

## [1.7.0] — 2026-07-31

### Changed
- **`mcp` is now an optional extra, not a core dependency** (CKM-26,
  ClearKan blocker): core installs pull only `httpx`/`msal`/`pydantic`;
  `ckm365[mcp]` adds the MCP SDK (still `>=2.0`) for `ckm365 serve`,
  which now exits with an actionable install hint when the SDK is
  missing. Rationale: the v1.5.0 floor fix was correct but propagated an
  mcp-2.0 pin to pure programmatic consumers — ClearKan's own MCP server
  needs mcp 1.x (`mcp.server.fastmcp` was removed in 2.0), making the
  two uninstallable together while the dep was hard. The dev group
  mirrors the extra so source checkouts (`uv sync` + the live Claude
  Code registrations) serve unchanged.

### Fixed
- **`pydantic` declared as the direct dependency it always was** —
  `models.py` imports it and the blessed API returns pydantic models,
  but it was riding in transitively via `mcp` and a no-extra install
  broke. Caught by the clean-venv acceptance test for this release.

## [1.6.0] — 2026-07-30

App-only mode is real: CKM-5 closed, live-verified end to end on one
tenant with a fully scripted (Jenkins-ready) tenant-automation path.

### Added
- **EXO automation tooling**: `scripts/create-exo-automation-app.sh`
  (one-time bootstrap of a dedicated cert-auth automation app —
  `Exchange.ManageAsApp`, grant-verified consent, Entra directory role
  with a least-privilege `--role recipient-admin` option),
  `scripts/exo-common.ps1` (`Connect-Ckm365Exo`: unattended from
  `CKM365_EXO_*` env, interactive fallback), and idempotent
  dry-run-by-default `scripts/setup-app-rbac.ps1` /
  `teardown-app-rbac.ps1` (RBAC-for-Applications scoping with mandatory
  positive + negative `Test-ServicePrincipalAuthorization` probes). The
  test-mailbox scripts auto-connect through the same helper.
- `docs/toolchain.md` — install requirements for dev box + CI agent
  (incl. the pwsh tarball recipe and why there is no direct REST
  alternative to EXO PowerShell for Exchange admin ops).
- App-only example profile in `profiles.example.toml`.

### Verified (the release's real content)
- **RBAC-only authorization works**: an app-only token with ZERO Graph
  application permissions read the scoped mailbox; an out-of-scope
  mailbox was refused with 403 `ErrorAccessDenied` — the negative test,
  at the Graph layer. No tenant-wide grant exists to argue about in
  enterprise review; `add-app-permissions.sh` stays unused, in reserve.
- Full live suite 5/5 app-only; delta bootstrap + `wait_for_message`
  app-only caught a real cross-profile delivery via token round-trip —
  no behavioral difference vs delegated mode (ClearKan asks 5.1/5.2).
- `Test-ServicePrincipalAuthorization`: `InScope True` (scoped mailbox) /
  `False` (operator mailbox) before any token was minted.

## [1.5.0] — 2026-07-30

ClearKan follow-up release (their v1.4.0 verification report, items 0/A/B),
plus repo cleanup. The Teams migration survey they sent is deliberately
NOT built — it is a design decision first (CKM-24, options a/b/c, owner's
call); nothing lands until that is settled.

### Fixed
- **`mcp` floor was wrong by a major version** (CKM-21): pyproject said
  `mcp>=1.2` but `ckm365 serve` imports `mcp.server.mcpserver`, which only
  exists from mcp 2.0 — installs resolving mcp 1.x imported fine and died
  at serve time. Floor is now `mcp>=2.0` (re-locked); the stale "FastMCP"
  docstring in server.py corrected. Programmatic-API consumers were never
  affected (the mcp import is lazily scoped inside `_serve`).

### Added
- **`Ctx.set_graph(account, graph)`** (CKM-22): the supported seam for
  injecting `Graph(transport=httpx.MockTransport(...))` in consumer
  tests — validates the profile name, swaps under the graphs lock, closes
  any replaced instance. Blessed (README + import-contract test);
  `docs/usage-modes.md` no longer points consumers at the private
  `_graphs` dict.
- **`py.typed`** (CKM-23): PEP 561 marker shipped and verified present in
  the built wheel — consumer type checkers now see the annotations.

### Removed
- Stale phase-0 artifacts: `docs/module-layout-proposal.md` (layout long
  since implemented) and the `tmp/softeria-ref/` reference clone
  (`docs/reference-notes.md` is the surviving record). References updated
  in CLAUDE.md/README.

## [1.4.0] — 2026-07-30

ClearKan-adoption release (their integration requirements, items 3–5).
No async mode, no `mark_message_read`, and no domain-layer features were
added — deliberate decisions, recorded in the board history and
`tmp/clearkan-integration-reply.md`.

### Added
- **Thread-safety contract** (CKM-19), now documented and SemVer'd:
  Ctx/Graph/Auth are safe for concurrent use across threads. `Ctx.graph()`
  takes a lock around the miss path (two racing threads can no longer
  build two Graphs and orphan an httpx pool); `Graph.close()`,
  `Ctx.close()`, and the Ctx context-manager form provide clean shutdown;
  `Auth._lock()` adds an in-process `threading.Lock` and documents that
  flock-on-own-fd also serialises threads (load-bearing — do not
  "optimise" away). Offline: 20-thread race, close, and context-manager
  tests. Live-verified on one tenant (doctor, smoke, full live suite).
- **Blessed programmatic API** (CKM-20): `ckm365.tools.Ctx`, the tool
  functions in `ckm365.tools.{mail,calendar,watch,accounts}`, the models
  they return, and `Graph(transport=...)` are the supported non-MCP,
  non-agent surface, covered by SemVer from this tag. Documented in
  README + `docs/usage-modes.md` ("Programmatic use", with the correct
  `list_new_messages` dict return shape); guarded by an import-contract
  test. Live-verified: documented pattern (bootstrap poll, delta token
  round-trip, context-manager close) ran against a real tenant.
- **App-only prep** (CKM-5, not yet live-verified — the tenant work is
  interactive): `scripts/add-app-permissions.sh` (application role-type
  permissions, preserves existing delegated scopes, grant-verified
  against actual appRoleAssignments, `--dry-run`) and
  `docs/app-only-setup.md` (per-tenant runbook: RBAC-for-Applications
  scoping FIRST, certificate credential preferred, out-of-scope negative
  test mandatory). Records the union caveat: an Entra app-role consent is
  NOT narrowed by an Exchange management scope, so RBAC-only is the
  proposed primary path.

## [1.3.0] — 2026-07-30

### Added
- Live integration suite `tests/test_live.py` (CKM-9): env-gated
  (`CKM365_LIVE_ACCOUNT`), zero-residue — read path, the full
  createReply → PATCH-top → attach → update → delete cycle with a 404
  residue check, non-draft refusal, calendar cycle, delta bootstrap.
  Verified against both tenants. Companion
  `scripts/create-test-mailbox.ps1` / `remove-test-mailbox.ps1` provision
  `tst.*` shared mailboxes (remove refuses non-`tst.*` addresses).
- `AGENTS.md` — the session entry point for agents: reading order,
  working loop, public-repo rules, code map, and the Graph gotchas
  already paid for.

### Changed
- Simplification pass (CKM-14): shared `pull()` list-fetch helper;
  `create_draft` takes `body_html` like its siblings; `add_attachment`
  derives name/MIME from the file; model field-shape consistency.
  Deliberately kept (recorded on the board): literal tool signatures,
  the per-call `account` parameter, app-only auth code, explicit patch
  builders.

## [1.2.0] — 2026-07-30

Three features built by parallel review-hardened subagent worktrees,
merged and live-verified.

### Added
- **Event-driven mail triggers**: `list_new_messages` / `wait_for_message`
  read tools built on Graph delta queries (bootstrap windows the initial
  sync with `$filter=receivedDateTime ge now-60s` — Outlook delta ignores
  `$deltatoken=latest`, live-tested; token URLs rebuilt server-side so
  they can never redirect the bearer; runaway paging capped), client-side
  sender/subject filters, `get_watch_command`, and a `ckm365 watch` CLI
  that exits 0 on matching mail (run it as a harness background task to
  wake an agent) or 3 on timeout. Wake pattern live-verified end to end.
- **Admin CLI**: `ckm365 mailbox grant|revoke|create-test|remove-test`
  (prints the exact Exchange Online PowerShell, always print-only),
  `ckm365 app register|add-send-scopes|consent-status` (dry-run by
  default; `--run` double-confirms), and `ckm365 doctor` (local health
  checks: profiles, cache perms, logins, likely consent tier).
- **Per-profile send cap**: `allow_send = false` in profiles.toml blocks
  the send tier for that profile regardless of server flags AND keeps
  send scopes out of its token requests. New `docs/onboarding.md`
  quickstart for additional users joining in personal capacity.

## [1.1.0] — 2026-07-30

### Added
- `respond_event` — accept / tentatively accept / decline meeting
  invitations; notifying the organizer (`send_response=True`, the default)
  is send-tier, calendar-only updates are write-tier.
- `create_event(online_meeting=True)` provisions a Teams meeting via Graph
  (`join_url` on the returned event). Note: silently unavailable when the
  organizer mailbox has no Teams license (e.g. unlicensed shared
  mailboxes) — organize from a licensed account instead.

## [1.0.0] — 2026-07-30

Initial public release. Multi-tenant Microsoft Graph mail + calendar MCP
server, live-verified on two tenants (delegated device-code auth, shared
mailboxes, cross-tenant send).

### Added
- Named account profiles (`~/.config/ckm365/profiles.toml`), one per
  (tenant, app registration), tenant authority always pinned — the
  `common`/`organizations`/`consumers` aliases are rejected.
- Capability tiers: read-only by default; `--write` for draft-only mail
  writes, attachments, and calendar writes; `--write --enable-send` for
  `send_draft` and attendee-bearing event writes. Send scopes are consented
  per tenant as a deliberate opt-in (`scripts/add-send-scopes.sh`).
- 15 tools: mail (list/get/folders/attachments; reply/forward/new drafts,
  draft update, draft-only attach, gated send), calendar (calendarView
  list, get, gated create/update), and `list_accounts` (profile discovery
  with descriptions).
- Two front doors over the same typed functions: `ckm365 serve` (MCP/stdio)
  and `ckm365.agent_tools.register` (pydantic-ai, in-process).
- MSAL auth with per-profile serialized token cache: 0600 files, atomic
  writes, cross-process file locking, reload-before-access (survives
  refresh-token rotation across concurrent sessions), one identity per
  profile enforced.
- Graph client with tiered retry (429 any method honouring Retry-After;
  503/504 idempotent methods only), `@odata.nextLink` paging pinned to the
  Graph host, and typed error mapping.
- Interactive tenant setup scripts (app registration with grant-verified
  admin consent and ownership checks; send-scope opt-in) plus read-only
  and zero-residue write live-smoke scripts.
- Docs: usage modes (multi-tenant operator, personal single-account,
  planned app-only), Softeria reference study, module layout proposal.

### Security
- Draft-only invariant end to end: replies/forwards seeded via Graph
  `createReply`/`createReplyAll`/`createForward`; only `isDraft` messages
  are ever PATCHed or sent (with `If-Match`); delivered messages are never
  modified.
- Independent security + simplification reviews completed pre-release; all
  findings addressed or tracked on the in-repo board (`board/`). Hardening
  includes account-pin isolation (pinned servers drop the `account`
  parameter), `$search` escaping, timezone header validation, optional
  `CKM365_ATTACH_ROOT` attachment-path constraint, and audit logging of
  ids/counts only — never bodies, subjects, or tokens.
