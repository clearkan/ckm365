# Calling Graph directly when a tool is missing (the escape hatch)

ckm365 deliberately ships ~30 hand-written tools, not 324 generated ones —
so you will sometimes need a Graph endpoint the server does not expose.
This page is the sanctioned way to do that: reuse the server's own auth and
retry plumbing, keep the tier discipline, and leave a board item behind so
the gap gets a real tool. It exists because the pattern has been needed
twice in live engagements (CKM-32's history), each time reinvented as a
throwaway script.

**The 30-second version:** `Ctx.create(account=...)` → `ctx.target(...)`
gives you an authenticated `Graph` and the mailbox path; `g.get()` for
JSON, `g.paged()` for collections, `g.batch()` for fan-out, `g.download()`
for bytes. Find the endpoint in Microsoft's API reference (table at the
bottom), try it in Graph Explorer first, then file the gap.

## The rules (same as everywhere else in this repo)

1. **Read tier by default.** `Ctx.create()` with no flags — or a bare
   `Auth(profile)` — requests `DELEGATED_RO` (or the app-only scopes on
   client-credential profiles) and silently reuses the cached login the
   server already holds. Pass `write=True`/`read_only=False` only when the
   gap is genuinely a write, and clear it with the owner first. **Never
   send mail this way** — draft-only is a hard rule; the send tier stays
   inside the server.
2. **No secrets or bodies in logs/output.** Print ids, counts and byte
   totals — never subjects, filenames of real mail, body text, or tokens.
3. **Bytes go to disk, not into agent context.** If you are fetching
   content for analysis, write a file and read it with file tools.
4. **v1.0, not beta.** Stick to `https://graph.microsoft.com/v1.0`; the
   `Graph` wrapper pins it. If an endpoint exists only in beta, that is a
   design conversation, not a script.
5. **File the gap.** A direct call is a workaround, not a capability. Add
   or update a `board/` backlog item (see CKM-32 for the template) so the
   tool gets built — note what you called and any Graph behaviour that
   surprised you.
6. Throwaway scripts live in `tmp/` (git-ignored) and die with the task.

## Getting credentials: there is nothing to configure

You do not mint tokens, read `profiles.toml`, or touch client secrets. The
server already holds a locked MSAL cache per profile; the classes below
reuse it and refresh silently.

- **Which profiles exist?** `uv run ckm365 doctor` (also proves each one is
  signed in and what consent it has), or the `list_accounts` tool. Profile
  names live only in `~/.config/ckm365/profiles.toml` — never in this repo.
- **Not signed in?** `uv run ckm365 login <profile>` once, interactively
  (device code). A script cannot do this for you: `auth.token()` raises
  `NeedsLogin` rather than prompting.
- **App-only profiles** (`auth = "client_credential"`) need
  `CKM365_<PROFILE>_CLIENT_SECRET` or the cert env vars in the
  environment; they have no `/me` — always address mailboxes explicitly.

## Recipe 1 — start from Ctx (the shortest correct path)

`Ctx` is what the tools themselves use: it resolves the profile, builds
the `Graph`, and works out which mailbox you meant (explicit argument →
profile default → signed-in user). It also owns the tier gates, so a
direct call inherits the same discipline as a tool.

```python
# tmp/scratch_query.py — run with: uv run python tmp/scratch_query.py
from ckm365.tools import Ctx

with Ctx.create(account="tenant-a") as ctx:        # read tier, cached login
    g, mailbox = ctx.target(None, None)            # (Graph, "user@tenant-a.example")
    me = g.get("/me")                              # any v1.0 path
```

`ctx.target(account, mailbox)` is the one call worth remembering: it
returns the pair every mail/calendar path needs, and raises `NeedsLogin`
with an actionable message when the profile has no mailbox.

Use plain `Auth` + `Graph` instead when you want no profile/mailbox
resolution at all:

```python
from ckm365.auth import Auth
from ckm365.config import load_profiles, resolve_profile
from ckm365.graph import Graph, mailbox_path

auth = Auth(resolve_profile(load_profiles(), "tenant-a"))   # read-only scopes
g = Graph(auth)
try:
    path = mailbox_path("ops@tenant-a.example", "/messages")  # encodes safely
    ...
finally:
    g.close()
```

## Recipe 2 — JSON endpoints (use the `Graph` wrapper, it is free)

`Graph` gives you the base URL, bearer injection, 429/5xx retry with
`Retry-After`, `$batch`, and safe paging. Do not hand-roll httpx for JSON.

```python
me = g.get("/me")                                  # single GET
folder = g.get(mailbox_path(mailbox, "mailFolders/inbox"),
               params={"$select": "id,displayName,totalItemCount"})

# paged listing — follows @odata.nextLink, hard-capped by max_items
for msg in g.paged(mailbox_path(mailbox, "mailFolders/inbox/messages"),
                   params={"$select": "id,receivedDateTime", "$top": "50"},
                   max_items=200):
    ...

# fan-out reads: 20 sub-requests per round trip, answered OUT OF ORDER
# (the wrapper re-keys them back into input order for you)
answers = g.batch([{"method": "GET",
                    "url": mailbox_path(mailbox, f"messages/{i}")}
                   for i in ids])
```

Notes that save time:
- `$select` everything explicitly — Graph's defaults are bloated and differ
  by resource. The dataclasses in `models.py` show the fields each tool
  considers canonical.
- `$filter` + `$orderby` combinations are rejected surprisingly often;
  filtered results come back in Graph's own order (`list_messages`'s
  docstring explains the consequence).
- `search` (KQL) cannot be combined with `$filter` at all.
- Teams endpoints reject `$top` outright (see AGENTS.md gotchas).
- A failing sub-request inside `$batch` is DATA (a per-item `status`), not
  an exception — check every item.

## Recipe 3 — raw bytes (`$value` and `/content` endpoints)

**Do not use `Graph.content()` for binaries** — it decodes to `str` and was
built for VTT transcripts; it will corrupt a .docx/.pdf/.zip. Use
`Graph.download()`, which streams to a file with the same auth and retry
policy and never holds the body in memory:

```python
from pathlib import Path

n = g.download(mailbox_path(mailbox, f"messages/{msg_id}/$value"),   # MIME
               Path("tmp/message.eml"))
print(f"wrote {n} bytes")      # counts only — never the filename of real mail
```

The same shape covers contact photos (`/photo/$value`) and drive items
(`/content`). For **mail attachments there is now a tool** —
`download_attachment` (CKM-32) — which also resolves the attachment by id
or name, refuses the kinds that have no bytes, confines writes to
`CKM365_DOWNLOAD_ROOT`, and never overwrites. Prefer it; reach for
`g.download()` only for endpoints no tool covers.

`fileAttachment` is the only attachment kind with bytes behind `$value`;
`itemAttachment` (an embedded message) and `referenceAttachment` (a cloud
link) will not give you a usable file — check `kind` from
`list_attachments` (Graph's `@odata.type`) first.

## Scopes: what the cached token can and cannot do

The silent token carries whatever the profile's tier granted — see
`DELEGATED_RO` / `DELEGATED_RW` / `DELEGATED_SEND` / `APP_ONLY_SCOPES` in
`auth.py`. A direct call cannot exceed those scopes: if Graph answers
`403 ErrorAccessDenied`, the endpoint needs a permission this app has never
consented to (e.g. `Files.Read.All`, `Sites.Read.All`, `MailboxSettings.Read`)
— that is a consent-tier decision for the owner (compare CKM-18), never
something to solve by widening scopes in a scratch script.

Reading `403` correctly saves an hour: **scope** problems are the app's
consent (fix: a consent script + owner approval), **`ErrorAccessDenied` on
one mailbox** is usually an Exchange delegation/RBAC problem (fix: mailbox
permissions), and a **tenant kill-switch** can 403 a correctly-consented
call outright (Teams transcripts do exactly this — see `tools/meetings.py`).

## Where the Microsoft documentation actually is

Every Graph resource page follows the same shape — HTTP request, permissions
table (delegated vs application), optional query parameters, and a worked
example — so finding the right page is most of the work:

| What you need | Where |
|---|---|
| API index (start here; drill into Mail / Calendar / Teams) | learn.microsoft.com/graph/api/overview |
| **Graph Explorer** — try the exact URL with your own account first | developer.microsoft.com/graph/graph-explorer |
| Message resource + its methods | learn.microsoft.com/graph/api/resources/message |
| List messages / Get message | learn.microsoft.com/graph/api/user-list-messages · .../api/message-get |
| Attachments (incl. the `$value` download) | learn.microsoft.com/graph/api/resources/attachment · .../api/attachment-get |
| Mail folders, move, reply/forward drafts | learn.microsoft.com/graph/api/resources/mailfolder · .../api/message-move · .../api/message-createreply |
| Events / calendar | learn.microsoft.com/graph/api/resources/event · .../api/user-list-events |
| Delta (change tracking) | learn.microsoft.com/graph/delta-query-overview · .../api/message-delta |
| Query parameters (`$select`, `$filter`, `$top`) and paging | learn.microsoft.com/graph/query-parameters · .../graph/paging |
| Permissions ↔ endpoint mapping (the authority for "which scope") | learn.microsoft.com/graph/permissions-reference |
| Batching | learn.microsoft.com/graph/json-batching |
| Throttling / 429 (the wrapper already honours `Retry-After`) | learn.microsoft.com/graph/throttling |
| Error codes | learn.microsoft.com/graph/errors |
| OpenAPI description of the whole API (the spec itself) | github.com/microsoftgraph/msgraph-metadata (`openapi/v1.0/openapi.yaml`; CSDL `$metadata` too) |
| Changelog (endpoints do move) | developer.microsoft.com/graph/changelog |

Two habits worth keeping: test the exact URL in **Graph Explorer** first (it
shows the required scopes inline and fails fast), and when a call misbehaves,
check `reference-notes.md` here — several hard-won Graph behaviours (filter
ordering, KQL exclusivity, shared-mailbox 403 semantics) are already written
down, as are the ones in AGENTS.md's gotchas list.
