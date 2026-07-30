# Reference notes — Softeria `ms-365-mcp-server`

Phase 0 study (CKM-2). The reference clone (`tmp/softeria-ref/`) was
deleted once phases 1–2 completed; these notes are the surviving record —
re-clone from GitHub if ever needed. MIT-licensed, **reference only** —
nothing vendored, no dependency.

## Shape of the thing

Node/TypeScript. The tool surface is **generated from an OpenAPI-derived
`endpoints.json`** (324 endpoint entries), each carrying `pathPattern`,
`method`, `toolName`, `scopes`, `presets[]`, and an `llmTip` string that
compensates for the generic parameter schemas. Roughly 25k lines including
generated client types. This is the opposite of our approach (a dozen
hand-written typed tools), but the endpoint selection and the llmTips encode
hard-won Graph behaviour worth keeping.

## Graph call shapes

Base URL `https://graph.microsoft.com/{v1.0|beta}{path}`, bearer injected per
request. Everything is direct REST — they don't use Microsoft's SDK either.

**Mail** (preset `mail`, 43 endpoints; the ones we care about):

| Purpose | Endpoint |
|---|---|
| List/search messages | `GET /me/messages`, `GET /me/mailFolders/{id}/messages` |
| Get one | `GET /me/messages/{id}` |
| Folders | `GET /me/mailFolders` (+ childFolders) |
| Seed reply drafts | `POST /me/messages/{id}/createReply` / `createReplyAll` / `createForward` |
| Edit draft | `PATCH /me/messages/{id}` |
| New draft | `POST /me/messages` |
| Send a draft | `POST /me/messages/{id}/send` |

Their `createReply` llmTip records the trap that matters for our PATCH-into-
draft flow: **supplying `message.body` in the createReply call (or a PATCH)
replaces the whole draft body — the quoted history Graph assembled is gone.**
Passing both `comment` and `message.body` returns 400. Signatures are an
Outlook-client feature, not available via Graph. Consequence for us: seed with
`createReply` (optionally passing `comment` for the trivial case), and for the
rich case GET the draft's assembled HTML body, prepend our content, PATCH the
combined body back.

**Calendar** (preset `calendar`): the list primitive is
`GET /me/calendarView?startDateTime=...&endDateTime=...` — it expands
recurring events into instances within the range (plain `/me/events` returns
only `seriesMaster` for recurrences). Plus `GET|POST /me/events`,
`GET|PATCH|DELETE /me/events/{id}`, accept/decline/cancel actions.

All paths are `/me/...`; shared-mailbox access is a separate tool family. We
instead take `mailbox` on every tool and route `/users/{mailbox}/...`
(delegated `.Shared` scopes or app-only), which is simpler and matches the
old ClearKan client.

**Query/body handling:**
- `$search` uses KQL and the whole expression **must be wrapped in double
  quotes** (`$search="from:x subject:y"`); `$filter`/`$orderby` are OData and
  cannot combine with `$search`.
- They push `$select` discipline hard (via llmTips) to cut response size —
  we get the same effect for free by projecting into Pydantic models with a
  fixed `$select`.
- `Prefer: outlook.body-content-type="text"` on GETs by default — Graph
  returns text-converted bodies instead of HTML soup. Keep, with per-call
  override (we need HTML when preparing draft PATCHes).
- `Prefer: outlook.timezone="..."` for calendar views so start/end come back
  in the requested zone. Keep as an optional param.
- `$top` clamped server-side; page size via `Prefer: odata.maxpagesize` for
  some resources.

## Pagination

Opt-in per call (`fetchAllPages`), then: follow `@odata.nextLink` (absolute
URL — they strip the `/v1.0|/beta` prefix and re-issue through the same
client), concat `value` arrays, cap by max-pages/max-items env knobs, keep the
final page's `@odata.deltaLink` if present, only merge when page one is
actually a collection. Sensible; our version is a ~20-line generator
`paged()` with a `max_items` argument.

## Throttling / retry (`lib/graph-resilience.ts`) — the best module in the repo

- **429**: honour `Retry-After` (integer seconds or HTTP-date, capped 60 s);
  retryable on **every** method including POST/PATCH because Graph throttles
  *before* executing, so the side effect has not landed.
- **503/504/network/timeout**: retry **idempotent methods only**
  (GET/HEAD/PUT/DELETE) — a POST/PATCH may already have executed server-side
  and would duplicate the side effect. Surface immediately for those.
- Other 4xx/5xx: deterministic, never retried.
- Exponential backoff with full jitter (base 200 ms, cap 5 s, 3 retries),
  request timeout via AbortController (100 s default).
- Plus a process-wide circuit breaker (5 consecutive failures → open 30 s →
  half-open probe). Reasonable for their multi-user HTTP deployment;
  **overkill for our single-user stdio server — skip it.**

The 429-vs-5xx retry-safety split is the part to replicate exactly.

## Auth & token caching

MSAL `PublicClientApplication`, device-code and interactive-browser flows.
Authority is `{host}/{tenantId || 'common'}` — **defaults to `common`**, and
their own code contains the admission this is broken: `consumersAuthorityHint()`
detects the June-2026 `invalid_grant`-on-refresh failure for accounts logged
in via `/common` and tells the user to pin an authority and re-login. Exactly
the failure our requirements doc pins tenant IDs to avoid.

Token cache (`token-cache-storage.ts` + MSAL `ICachePlugin`):
- Serialized MSAL cache stored in **keytar (OS keychain) with file fallback**;
  file writes are atomic (temp + rename), `0600`, dir `0700`; both copies
  wrapped in an envelope carrying `savedAt` so load picks the newest.
- The `ICachePlugin` reloads the persisted cache **before every MSAL cache
  access** and persists after any change. Reason (their issue #545):
  Microsoft **rotates refresh tokens on silent refresh**, so a second process
  holding a stale cache dies with `invalid_grant`. With several Claude Code
  sessions each spawning our stdio server, we will hit this — replicate the
  reload-before-access/persist-after-change pattern with
  `msal.SerializableTokenCache`.
- Multi-account: all accounts live in one MSAL cache; a persisted
  "selected account" picks the default; an `account` parameter is injected
  into tool schemas **only when more than one account exists**; with multiple
  accounts and no selection they refuse rather than fall back to the first.
  Good pattern for our multi-tenant profiles (theirs is multi-account within
  one authority; ours must be one authority *per* profile since we pin
  tenants).

## Preset / read-only system

Presets are **exact tool-name allowlists**: each endpoint entry declares
`presets: ["mail", ...]`; `--preset mail,calendar` compiles the union into a
filter. They moved away from name-regex matching because it over-matched —
with our explicit per-module tool lists that failure mode doesn't exist.
`--read-only` filters out non-GET tools (with a `readOnly: true` escape hatch
for read-flavoured POSTs like `getSchedule`) **and also shrinks the scopes
requested at login** to the Read-only variants. Worth copying: read-only mode
should affect both the tool list and the requested scopes.

## Over-complications to avoid

- 324 generated tools + a scope-hierarchy inference engine (~400 lines
  collapsing `Mail.ReadWrite` ⊃ `Mail.Read` etc.) — our scope sets are small
  static lists per preset × auth-mode.
- Raw Graph JSON straight into MCP responses (with `@odata.*` stripped and an
  optional TOON encoding to claw back tokens) — typed Pydantic projections
  make both problems disappear.
- Seven env vars just for resilience tuning, circuit breaker, Key Vault
  secrets provider, OBO/HTTP/OAuth modes, ETag plumbing — all serve their
  hosted multi-tenant product, none serve a local stdio server.
- `common` authority default (see above — their own hint apologises for it).

## Worth stealing from ClearKan `integrations/m365`

- `_encoded_graph_path_segment()` — path-segment validation/quoting for
  mailbox + message ids (drop-in for `graph.py`).
- Audit-log shape: tool/outcome/mailbox/counts + subject *hash*, never bodies
  or tokens.
- `M365GraphError(status, graph_error_code)` mapping keyed off Graph's
  `error.code` JSON.
- Anti-pattern to fix: it builds a fresh `httpx.AsyncClient()` per request —
  we hold one client for the process.
