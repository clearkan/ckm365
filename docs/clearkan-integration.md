# ClearKan integration — decision log

ClearKan is ckm365's main downstream consumer. It uses ckm365 as a pure
**programmatic** client (`ckm365.tools.Ctx` + tool functions, called from
`asyncio.to_thread`) behind its own mail-intake port. It never goes through
the MCP server. This page records what the two projects agreed, in order,
and where things stand now. The asks and replies were exchanged as working
docs, relayed through the owner. This is the durable summary of them.

**Standing division of labour.** ckm365 is Graph transport. ClearKan owns
the domain layer: sender policy, the processed-message ledger,
message-to-issue mapping, board commands and anything Bot Framework.
ckm365 builds nothing domain-shaped for ClearKan.

---

## Log

### 2026-07-30 — adoption requirements → v1.4.0

ClearKan sent six adoption items. ckm365 answered them all in v1.4.0.

| # | Ask | Outcome |
|---|---|---|
| 1 | Tags to pin | Every release gets an annotated tag, pushed. This is a standing release step (AGENTS.md step 7). Pin v1.4.0 or later. |
| 2 | No async mode | Agreed. ckm365 stays sync (MSAL has no async API). ClearKan calls it from `asyncio.to_thread`. |
| 3 | Thread safety | CKM-19. `Ctx`, `Graph` and `Auth` are safe across threads. `Ctx.graph()` check-then-set is locked. `Graph.close()`/`Ctx.close()` and a context-manager form were added. The flock in `Auth._lock()` is documented as load-bearing, with an in-process lock alongside it. |
| 4 | A blessed API | CKM-20. `Ctx`, the tool functions, the models, the exceptions and `Graph(transport=...)` are SemVer'd from v1.4.0, and an import-contract test guards them. Correction to ClearKan's sample: `list_new_messages` returns a dict `{messages, delta_token, matched}`, not a tuple. The shape was kept as it was. |
| 5 | App-only mode | CKM-5. The runbook (`docs/app-only-setup.md`) was done in this release. Live verification waited on an interactive tenant sitting (see v1.6.0). |
| 6 | No read-state or delivered-message mutation | Agreed for ClearKan. Its delta token plus its own ledger does the job. |

Caveat raised back to ClearKan: Exchange access is the **union** of Entra
app-role grants and Exchange RBAC assignments. A tenant-wide
`Mail.ReadWrite` consent is therefore not narrowed by a management scope,
and the runbook proposes RBAC-only authorisation.

### 2026-07-30 — v1.4.0 follow-ups → v1.5.0

ClearKan verified v1.4.0 from a clean install and filed three gaps:

- **mcp floor was wrong** (CKM-21). `mcp>=1.2` was declared, but
  `server.py` needs `mcp.server.mcpserver`, which exists only in 2.0+.
  Fixed to `mcp>=2.0` and re-locked.
- **Test injection used a private attribute** (CKM-22). Added the public
  seam `Ctx.set_graph(profile, Graph(auth, transport=mock))`. It validates
  the profile, swaps under the `graph()` lock and closes what it replaces.
  `_graphs` is private again.
- **No `py.typed`** (CKM-23). Added, and confirmed inside the built wheel.

ClearKan's "not asks", which ckm365 agreed to leave alone:

- `MessageSummary` stays narrow. ClearKan does a delta poll plus N
  `get_message` calls, and N is small.
- `Ctx.close()` is for shutdown only.
- No optional-extra split for mcp. This was reversed two releases later.

The same batch included a Teams migration survey. ckm365 filed it as a
decision gate (CKM-24) and did not start work on it.

### 2026-07-30 — app-only verified → v1.6.0

Asks 5.1 and 5.2 were verified live on one tenant, using a certificate
credential and a single scoped mailbox:

- Doctor passed, the read path passed, and the full live suite passed
  app-only.
- `list_new_messages` bootstrap → `wait_for_message` resume worked
  app-only, with no behavioural difference from delegated mode.
- Negative test: `Test-ServicePrincipalAuthorization` showed in-scope for
  the scoped mailbox and out-of-scope elsewhere. With a real token, the
  out-of-scope mailbox returned **403 `ErrorAccessDenied`**.
- **RBAC-only.** The app holds zero Graph application permissions. The
  scoped Exchange role assignments are the entire grant. There is no
  tenant-wide permission to narrow.

**Teams decision: option (c).** ckm365 stays Graph-only. Bot Framework
messaging, inbound webhook auth and replay protection stay in ClearKan
permanently. Only Graph-shaped Teams reads may land in ckm365, as a
separate least-privilege consent tier that no mail flag implies (CKM-25).

### 2026-07-31 — the mcp blocker → v1.7.0

The v1.5.0 floor fix was correct, but it propagated. With `mcp` as a hard
dependency, every consumer was forced onto mcp 2.x. ClearKan's own board
MCP server needs `mcp.server.fastmcp`, which 2.0 removed. Pip resolved it
without complaint and the board server broke at runtime. ClearKan's
workaround was `pip install --no-deps`.

Fix (CKM-26): **`mcp` became an optional extra.** Core installs no longer
pull it. `ckm365[mcp]` adds `mcp>=2.0` for `ckm365 serve`, which exits with
an install hint when the SDK is absent. The dev dependency group mirrors
the extra, so source checkouts still serve. ClearKan pins `mcp<2` on its
side and migrates its board server on its own schedule.

The clean-venv acceptance test found that `pydantic` had only ever arrived
through `mcp`. v1.7.0 declared it as a core dependency to stop the break.

### 2026-07-31 — pydantic disconnected → v2.0.0

This was the owner's call. Instead of carrying pydantic, the models became
**stdlib dataclasses**, built with `Model.from_graph(dict)` (CKM-27). The
core dependencies are exactly `httpx` and `msal`.

- The attribute surface, tool signatures, return shapes and exceptions are
  unchanged.
- Gone from returned objects: `model_validate`, `model_dump`, `model_copy`.
  Use `dataclasses.asdict`/`replace` instead.
- pydantic consumers remain first-class. `pydantic.TypeAdapter(Model)`
  schema, dump and validate round-trips are test-pinned, and so is
  `MCPServer.add_tool` over the dataclass-returning tools.
- The ClearKan migration was expected to be a no-op, because it only reads
  attributes.

### 2026-08-01 — Teams option-(c) slice → v2.1.0 / v2.1.1

The `teams` preset (CKM-25) adds `list_teams`, `list_channels` and
`list_installed_apps`, all read-only. They turn names into the ids that
ClearKan otherwise sets by hand in env vars. The preset has its own consent
script (`scripts/add-teams-scopes.sh`) and stays separate from the mail
scopes. v2.1.1 fixed live 400s: three of the Teams endpoints reject `$top`,
so the limit is now applied client-side.

### Later releases that touch ClearKan's surface

These were not ClearKan asks. They are listed because a re-pin crosses
them.

- **v2.2.0**: `mark_read`/`mark_unread` and flags (write tier), plus
  triage filters, all built for interactive triage. They exist on their
  own merits. ClearKan did not ask for them, and item 6 still holds for
  its intake.
- **v2.3.0**: `MessageSummary` gains `to`/`cc`. It still has no `webLink`
  or `internetMessageId`.
- **v2.7.0**: **behaviour change on the SemVer'd surface.** `revise_draft`
  now raises `ValueError` on a draft with no compose fence, where it used
  to silently duplicate the body. `insert_if_unfenced=True` restores the
  old insert.
- **v2.8.0**: `export_message` records move to OKF v0.2. A re-export diffs
  once, on `timestamp`/`exported_by` → `generated`.

---

## Current state (checked 2026-09-21)

- ckm365 is at **v2.8.0**. Core dependencies are `httpx` and `msal`, with
  `mcp>=2.0` as the optional `[mcp]` extra (`pyproject.toml`).
- ClearKan's current `pyproject.toml` pins its optional `m365` extra to **v2.0.0**, as a git
  tag. The pin comment lists what it relies on from v1.4.0, v1.5.0, v1.7.0
  and v2.0.0. It imports ckm365 lazily, so a missing extra degrades to
  "intake offline".
- Tags `v1.0.0`–`v2.8.0` are on the remote, **except `v2.6.0`**. That
  release was committed but never tagged.

## Open items

- **Missing `v2.6.0` tag.** Tag the release commit or record it as skipped.
  Consumers pin to tags, so the tag list should be complete.
- **ClearKan re-pin.** ClearKan is eight minor releases behind. The
  changelog lists no incompatible change to the read and watch tools that
  its intake uses. Before it adopts `revise_draft` or `export_message`,
  it should read the 2.7.0 and 2.8.0 notes above.
- **`MessageSummary` width.** Deferred until real poll volumes make the
  N × `get_message` pattern hurt.
- **Teams env-var fallback.** Retiring ClearKan's first-generation M365
  client left three env-var-name constants behind in a stub, which
  ClearKan's Teams code still imports. Resolving that is ClearKan's job
  under option (c). Its status was not verified from this repo.
