# Module layout proposal — for approval before tool implementation

Phase 0 deliverable (CKM-3). Nothing below `tools/` gets written until this
is signed off.

## New requirement folded in: multi-tenant

We may talk to more than one M365 tenant (e.g. operator@tenant-b.example **and**
operator@tenant-a.example). Since authorities are tenant-pinned (never `common`),
multi-tenant means **named account profiles**, each with its own pinned
authority, client id, auth mode, and token cache entry. Every tool takes an
optional `account` parameter (profile name); single-profile setups never need
to pass it. `mailbox` stays a separate parameter — it selects the mailbox
*within* the profile's tenant (shared mailboxes via `.Shared` delegated
scopes, or any in-scope mailbox in app-only mode).

## Module tree (line budgets total ≈ 750)

```
src/ckm365/
├── __init__.py
├── config.py        ~90   # profiles (TOML + env overlay), write-flag, cache paths
├── auth.py         ~130   # MSAL wrapper per profile; device-code & client-credential
├── graph.py        ~150   # one httpx.Client; retry/backoff; pagination; error mapping
├── models.py       ~120   # Pydantic response models (fixed $select projections)
├── tools/
│   ├── __init__.py  ~30   # PRESETS registry: {"mail": [...], "calendar": [...]}
│   ├── mail.py     ~160   # 3 read + 5 write-gated tools
│   └── calendar.py  ~90   # 2 read + 2 write-gated tools
├── server.py        ~60   # FastMCP/stdio front door (only place that imports mcp)
└── agent_tools.py   ~30   # pydantic-ai front door (plain function registration)
```

`server.py` and `agent_tools.py` contain zero Graph knowledge — they iterate
the same registry and wrap the same functions.

## config.py

```python
@dataclass(frozen=True)
class Profile:
    name: str                      # "tenant-a", "tenant-b"
    tenant_id: str                 # GUID — pinned; 'common'/'organizations' rejected
    client_id: str
    auth: Literal["device_code", "client_credential"]
    default_mailbox: str | None    # required when auth="client_credential"
    # client secret/cert always via env/keychain, never in this file

def load_profiles(path: Path | None = None) -> dict[str, Profile]
    # ~/.config/ckm365/profiles.toml by default; CKM365_PROFILES overrides path.
    # tomllib is stdlib — no new dependency.

def resolve_profile(profiles: dict[str, Profile], name: str | None) -> Profile
    # None + exactly one profile -> that profile
    # None + several -> raise with the list (mirror Softeria: never guess)
```

## auth.py

```python
class Auth:
    """One MSAL app per profile, created lazily, cached for process lifetime."""
    def __init__(self, profile: Profile, cache_dir: Path | None = None) -> None
    def token(self) -> str
        # silent from cache -> refresh -> raise NeedsLogin (delegated)
        # acquire_token_for_client (app-only)
    def login(self) -> str          # device-code bootstrap, prints code; returns UPN
    def logout(self) -> None

class NeedsLogin(Exception): ...    # message tells the user: ckm365 login <profile>
```

- Authority: `https://login.microsoftonline.com/{tenant_id}` — constructor
  rejects `common`/`organizations`/`consumers`.
- Delegated scopes (static): `Mail.ReadWrite Mail.ReadWrite.Shared
  Calendars.ReadWrite Calendars.ReadWrite.Shared offline_access`; read-only
  server start requests the `.Read` variants instead (Softeria pattern:
  read-only shrinks scopes, not just the tool list).
- Cache: `msal.SerializableTokenCache`, one file per profile
  (`~/.local/state/ckm365/{profile}.msal.json`, dir 0700, file 0600, atomic
  temp+rename), **reload-before-access / persist-after-change** wrapped
  around every acquire — required because Graph rotates refresh tokens and
  several Claude Code sessions will run this server concurrently.
- `ckm365 login <profile>` / `logout` as console entry points.

## graph.py

```python
class GraphError(Exception):
    status: int; code: str; message: str; request_id: str | None
    # code = Graph JSON error.code (e.g. ErrorItemNotFound, Forbidden)

class Graph:
    """One httpx.Client for the process; all methods sync."""
    def __init__(self, auth: Auth, *, timeout: float = 30.0) -> None

    def request(self, method: str, path: str, *,
                params: Mapping[str, str] | None = None,
                json: Any | None = None,
                headers: Mapping[str, str] | None = None) -> dict[str, Any] | None
        # - injects bearer + Prefer headers
        # - retry: 429 on any method honouring Retry-After (int|http-date, cap 60s);
        #   503/504/transport errors on idempotent methods only; 3 attempts,
        #   expo backoff w/ full jitter (0.2s base, 5s cap)
        # - non-2xx -> GraphError from Graph's error JSON
    def get(self, path, **kw) -> dict          # thin aliases
    def post(self, path, **kw) -> dict | None
    def patch(self, path, **kw) -> dict

    def paged(self, path: str, *,
              params: Mapping[str, str] | None = None,
              max_items: int = 100,
              headers: Mapping[str, str] | None = None) -> Iterator[dict]
        # follows @odata.nextLink (re-issues absolute URL), yields items,
        # stops at max_items

def mailbox_path(mailbox: str, suffix: str) -> str
    # "/users/{quoted}/{suffix}" with ClearKan's path-segment validation lifted
```

Body/HTML handling: reads default `Prefer: outlook.body-content-type="text"`;
`get_message(..., body_format="html")` overrides (needed when preparing draft
PATCHes). Calendar reads accept optional `timezone` → `Prefer: outlook.timezone`.

## models.py (Pydantic v2, comes with `mcp`'s dependency tree — not a new dep)

`MessageSummary` (id, subject, from, received, preview, has_attachments,
is_read, folder ref) · `Message` (+ body, to/cc, headers subset, weblink) ·
`Draft` (id, subject, to/cc/bcc, body, is_draft=True enforced) · `MailFolder` ·
`EventSummary` · `Event` · `Page[T]` (items + next hint). Each model owns its
`$select` list so queries and projections can't drift apart.

## tools/ — the core artifact

Every tool: plain typed sync function, first arg a `Ctx` bundle
(`Ctx = profiles + per-profile Graph instances + write_enabled flag`),
then keyword params. `account: str | None = None`, `mailbox: str | None = None`
on all of them (mailbox default: profile.default_mailbox, else the signed-in
user via `/me` semantics on `/users/{upn}`).

```python
# mail.py — read
def list_messages(ctx, *, folder="inbox", search=None, filter=None,
                  top=25, account=None, mailbox=None) -> list[MessageSummary]
def get_message(ctx, message_id, *, body_format="text",
                account=None, mailbox=None) -> Message
def list_mail_folders(ctx, *, account=None, mailbox=None) -> list[MailFolder]

# mail.py — write-gated (draft-only; never touches non-drafts)
def create_reply_draft(ctx, message_id, body_html, *, reply_all=False, ...) -> Draft
    # POST createReply|createReplyAll -> GET draft (html) -> prepend -> PATCH
def create_forward_draft(ctx, message_id, to, body_html=None, ...) -> Draft
    # recipients go in the createForward request body (requirements rule)
def update_draft(ctx, message_id, *, subject=None, body_html=None,
                 to=None, cc=None, bcc=None, ...) -> Draft
    # refuses unless isDraft=true on the target (fetch-then-patch)
def create_draft(ctx, *, to, subject, body, html=False, cc=None, bcc=None, ...) -> Draft
# no send tool in phase 1

# calendar.py
def list_events(ctx, *, start, end, timezone=None, top=50, ...) -> list[EventSummary]
    # /calendarView — expands recurrences (deliberate choice over /events)
def get_event(ctx, event_id, *, ...) -> Event
def create_event(ctx, *, subject, start, end, timezone=None, attendees=None,
                 body=None, location=None, ...) -> Event      # write-gated
def update_event(ctx, event_id, *, ...) -> Event               # write-gated
```

Write gating: one check in the shared `Ctx` (`ctx.require_write()`), set only
by an explicit `--write` flag at server start / registration call. Logging:
tool name, profile, mailbox, message/event id — never bodies, subjects, or
tokens (subject-hash trick from ClearKan if we ever need correlation).

## Front doors

```python
# server.py
#   ckm365 serve --preset mail,calendar [--write] [--account NAME]
# FastMCP stdio; registers PRESETS[p] for requested presets; write tools only
# added when --write. --account restricts to one profile and drops the
# account param from schemas (Softeria's only-inject-when-multi pattern).

# agent_tools.py
def register(agent: "pydantic_ai.Agent", *, presets=("mail",),
             write=False, account: str | None = None) -> None
```

## Decisions needing your sign-off

1. **Sync, not async.** msal is sync; FastMCP and pydantic-ai both accept sync
   tools (threadpool). Async buys nothing for a stdio server and costs
   ~10–15% of the line budget in ceremony. (Old ClearKan client is async —
   this is a deliberate departure.)
2. **Profiles in TOML** (`~/.config/ckm365/profiles.toml`, stdlib `tomllib`),
   secrets stay in env/keychain. Alternative is pure env vars
   (`CKM365_<PROFILE>_TENANT_ID=...`), workable but ugly with 2+ tenants.
3. **Token cache = file-only in phase 1** (0600, XDG state dir). True OS
   keychain needs the `keyring` package — a 4th runtime dep, so per the
   rules it needs your explicit sign-off; propose deferring it, the pattern
   drops in behind `auth.py` without structural change.
4. **Tenant IDs**: profiles.toml wants the GUID per tenant. I'll need those
   from you (or `az account show` per tenant) during auth setup — CKM-4/5
   are updated to be per-profile, run interactively per tenant.
