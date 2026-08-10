# AGENTS.md — start here

You are working on ckm365: a minimal multi-tenant Microsoft Graph MCP server
(mail + calendar) in Python. This file is the entry point for any agent
session; everything else worth knowing is one hop from here.

## Read these, in order, at session start

1. `CLAUDE.md` — the hard rules (deps, tiers, draft-only mail, tenant ops
   are interactive, no secrets/bodies in logs). Non-negotiable.
2. `tmp/m365-mcp-requirements.md` — the authoritative requirements. It is
   git-ignored; if missing, ask the owner (seanwy) before proceeding.
3. `board/` — the ClearKan task board. Manage it with the `clearkan-lite`
   skill (`.claude/skills/clearkan-lite/`). The issue file for whatever you
   are asked to work on ("let's do CKM-18") contains the scope, the design
   sketch, dependencies, and history — treat it as the brief.
4. `README.md` + `docs/usage-modes.md` — capability tiers and how the two
   real deployments run. `docs/onboarding.md` for the new-user path.
   `docs/graph-direct.md` — the sanctioned way to call Graph directly for
   endpoints with no tool yet (and where Microsoft's API docs live).
5. `CHANGELOG.md` — what shipped when, including hard-won Graph facts.

## The working loop (what "done" means here)

1. Move the board issue to `doing` (update `updated_at`, append `history`).
2. Implement in the existing style: sync Python, plain typed tool functions
   (Ctx first arg), dataclass models owning their `$select`, docstrings that
   teach agents (they BECOME the MCP tool descriptions). Core deps are
   frozen at httpx/msal (mcp is an optional extra; models are stdlib
   dataclasses, pydantic-compatible via TypeAdapter but never imported) —
   a new dep needs the owner's explicit sign-off first.
3. Offline tests (`uv run pytest tests/ -q`) — httpx.MockTransport, no
   network, must stay green. Add tests for new behavior incl. gating.
4. Live verification — offline mocks have missed real Graph behavior
   before (see gotchas): run the relevant live check yourself:
   - `uv run ckm365 doctor` — config/login/consent health
   - `uv run python scripts/live-smoke.py <profile>` — read path
     (+ `--shared <mbx>` positive / `--deny <mbx>` negative)
   - `uv run python scripts/draft-cycle-smoke.py <profile>` — write path,
     zero residue
   - `CKM365_LIVE_ACCOUNT=<profile> uv run pytest tests/test_live.py -q`
     — the full integration suite (zero residue, never sends)
   Discover real profile names with `uv run ckm365 doctor` or the
   list_accounts tool — they exist only in `~/.config/ckm365/profiles.toml`,
   never in this repo.
5. Board issue → `done` with a history entry stating what was verified.
6. Bump `VERSION` + `pyproject.toml` + `src/ckm365/__init__.py` (SemVer:
   new tools = minor) and add a `CHANGELOG.md` entry.
7. Commit (imperative subject, body says what was verified), tag the
   release (`git tag -a vX.Y.Z -m "..."`), and push commit AND tags to
   `origin main` — downstream consumers (ClearKan) pin to these tags.

## Absolute rules for this PUBLIC repo

- NEVER commit real addresses, tenant names, tenant/client GUIDs, or
  internal project names. Placeholders are `tenant-a.example` /
  `tenant-b.example`, `operator@`, `ops@`, `agent@`, `colleague@`,
  `other-user@`. Real values live in local config and the owner's head.
- Never log or print message bodies, subjects of real mail, or tokens —
  ids, counts, and truncated ids only (see `bind()` in tools/context.py
  and the smoke scripts for the pattern).
- Capability tiers are load-bearing security: read by default, `--write`
  gated, `--write --enable-send` gated twice (flag + per-tenant consent +
  per-profile `allow_send`). Anything that causes mail/invites/responses
  to LEAVE the tenant is send-tier (`ctx.require_send(account)`).
- Anything touching a tenant (app registration, consent, RBAC, mailbox
  creation, Exchange grants) is interactive: propose exact commands or use
  the dry-run admin CLI; the owner runs/approves. Scripts under `scripts/`
  follow this (dry-run default, grant-verified consent).

## Map of the code (src/ckm365/, ~1 file per concern)

`config.py` profiles/TOML → `auth.py` MSAL + locked token caches →
`graph.py` httpx client, retry, paging, errors → `models.py` dataclass
projections → `tools/` (context: Ctx/gating/bind/pull; mail; calendar;
watch: delta triggers; accounts; teams: org-scoped discovery, read-only,
separate consent tier) → front doors `server.py` (CLI: serve/
watch/login/logout + admin.py: mailbox/app/doctor) and `agent_tools.py`
(pydantic-ai). Tests: `tests/test_offline.py` + per-module files;
`tests/test_live.py` is the env-gated live suite.

Ctx/Graph/Auth are safe for concurrent use across threads; call
`Ctx.close()` on shutdown (or use Ctx as a context manager). The flock in
`Auth._lock()` doubles as the in-process serialiser — see its docstring
before touching it.

The SUPPORTED programmatic surface (SemVer'd from v1.4.0, consumed by
ClearKan): `ckm365.tools.Ctx` (create/profile/graph/target/require_*/
close/context-manager), the tool functions in
`ckm365.tools.{mail,calendar,watch,accounts,teams}`, the models they return,
and `Graph(transport=...)` for test injection. Renaming any of these is a
breaking change — `tests/test_offline.py` carries the import contract.

## Gotchas already paid for (do not rediscover)

- Outlook message delta IGNORES `$deltatoken=latest` (directory-only) and
  will enumerate a 92k-message inbox; bootstrap with
  `$filter=receivedDateTime ge <now-60s>` (tools/watch.py).
- `az ad app permission admin-consent` right after a permission update can
  record a stale set and still exit 0 → always verify grants scope-by-scope
  (both consent scripts do).
- Teams meeting provisioning silently no-ops for unlicensed shared-mailbox
  organizers — organize from a licensed account.
- Graph rotates refresh tokens on silent refresh: the cache uses
  reload-before-access + flock; never bypass Auth's helpers.
- `createReply` with a `body` replaces Graph's quoted history — seed first,
  then PATCH the top (`_insert_top`), with If-Match.
- MCP tool schemas come from `bind()`-trimmed signatures; after changing
  tools the running MCP server needs a reconnect (`/mcp`) to show them.
- First Graph hit on a cold mailbox can 503
  (`ErrorInternalServerTransientError`), and a FILTERED list on a large one
  can 503 twice running. The old 3-retry/0.2s-base budget sat inside a
  single blip; since v2.2.0 (CKM-35) 503/504 get 5 retries on a 1s base
  while throttling keeps the old budget. Do not shrink it back.
- Graph `/$batch` takes at most 20 sub-requests, answers them OUT OF ORDER
  (match on the request `id`), needs `Content-Type: application/json` on
  every sub-request carrying a body, and reports per-item failures as
  sub-`status` inside an overall 200 — `Graph.batch()` handles all four.
- `internetMessageHeaders` IS returned on a message COLLECTION GET when
  explicitly `$select`ed (CKM-38 assumed it was not — verified otherwise on
  both tenants, 47-86 headers per row). It is kept off `list_messages`
  anyway on VOLUME grounds: ~10.6-11 KB per row, ~11x a summary row.
  `get_message_headers` fetches it deliberately, 20 messages per `/$batch`,
  and curates before returning. `/$batch` sub-request URLs accept `$select`.
- Attachment `@odata.type` (`kind` on the model) rides along on a listing
  even when `$select` names five other fields — it is OData control
  information, not a property, so it cannot be selected and cannot be
  suppressed. That is what makes refusing item/referenceAttachment cheap.
- Attachment `size` is NOT the file size: it counts the MIME-encoded
  attachment including headers, measured +210-230 B on synthetic files and
  up to ~3.8 KB on real mail (both tenants). Use it as an upper bound;
  `download_attachment` reports what actually landed.
- `Graph.content()` decodes to `str` (built for VTT transcripts) and will
  corrupt any binary. `Graph.download()` is the streaming byte path — it
  writes to a file and never buffers the body.
- Teams endpoints REJECT `$top` (400 "Query option 'Top' is not
  allowed"): `/me/joinedTeams`, `/teams/{id}/channels`,
  `/teams/{id}/installedApps` all refuse it — only the `/teams`
  collection accepts it. tools/teams.py sends no `$top` and caps
  client-side via `pull()`; `$select`/`$expand` are fine. Offline mocks
  accept anything, so this only showed up live (it did, on first run).

## Current state (2026-08-11)

Version 2.4.0. Phases 1-2 done and live-verified on both tenants: 31 tools
(mail/calendar/watch/accounts/teams/meetings), three-tier gating, admin CLI,
multi-user onboarding, event-driven wake pattern. v2.4.0 added read-tier
`download_attachment` (CKM-32 — attachment bytes stream from Graph's
`$value` straight to disk via the new `Graph.download()`, never through
agent context; confined by `CKM365_DOWNLOAD_ROOT`) and rewrote
`docs/graph-direct.md` as the escape-hatch guide for endpoints with no
tool. v2.3.0 put `to`/`cc` on
every `MessageSummary` (CKM-37 — sent-items correspondents, and which party
a message belongs to in a shared mailbox; measured cost +17% per row, so no
opt-in flag) and added read-tier `get_message_headers` (CKM-38 — a curated,
sanitised, length-capped subset of internet headers with derived
`is_bulk`/`is_auto_reply`; header values stay UNTRUSTED and are for
classification, never authorisation). v2.2.0 added the mail
triage slice (CKM-33/34/35/36): batched `mark_read`/`mark_unread`/`flag`/
`unflag`/`complete_flag`/`move_message` over Graph `/$batch`, first-class
`unread_only`/`flagged_only`/`since`/`from_address` predicates plus
`group_by_sender`, and a longer transient-5xx retry budget. v1.4.0 added the thread-safety
contract and the SemVer'd programmatic API (ClearKan pins these tags);
v1.5.0 the mcp>=2.0 floor fix, Ctx.set_graph, py.typed; v1.6.0 the
app-only mode live-verified (CKM-5: RBAC-only scoping, scripted
Jenkins-ready EXO automation — see docs/app-only-setup.md +
docs/toolchain.md); v1.7.0 made mcp an optional extra (the dev
group still carries mcp so source checkouts serve out of the box); v2.0.0
disconnected pydantic entirely — models are stdlib dataclasses
(pydantic-compatible via TypeAdapter, test-pinned), core deps are exactly
httpx/msal; v2.1.0 added the teams discovery preset (CKM-25 — the option
(c) slice: read-only, org-scoped, SEPARATE consent tier). Teams bot
messaging stays out of this repo by decision (CKM-24). Board: CKM-18
(SharePoint/Teams-site file sync), CKM-28 (Teams persona options) and
CKM-31 (client-tenant onboarding) are open in backlog; CKM-30 (meeting
transcripts) is code-complete in doing, blocked on a tenant switch. Security +
simplification reviews completed; decisions on deliberately-kept
complexity are recorded in the CKM-14 board history.
