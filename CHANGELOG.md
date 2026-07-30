# Changelog

All notable changes to ckm365 are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

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
