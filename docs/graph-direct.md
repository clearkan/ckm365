# Calling Graph directly when a tool is missing (the escape hatch)

ckm365 deliberately ships a dozen hand-written tools, not 324 generated ones
— so you will sometimes need a Graph endpoint the server does not expose.
This page is the sanctioned way to do that: reuse the server's own auth and
retry plumbing, keep the tier discipline, and leave a board item behind so
the gap gets a real tool. It exists because the pattern has been needed
twice in live engagements (CKM-32's history), each time reinvented as a
throwaway script.

## The rules (same as everywhere else in this repo)

1. **Read tier by default.** Construct `Auth(profile)` — that requests
   `DELEGATED_RO` (or the app-only scopes on client-credential profiles) and
   can silently reuse the cached login the server already holds. Pass
   `read_only=False` only when the gap is genuinely a write, and clear it
   with the owner first. **Never send mail this way** — draft-only is a hard
   rule; the send tier stays inside the server.
2. **No secrets or bodies in logs/output.** Print ids, counts and byte
   totals — never subjects, filenames of real mail, body text, or tokens.
3. **Bytes go to disk, not into agent context.** If you are fetching content
   for analysis, write a file and read it with file tools.
4. **v1.0, not beta.** Stick to `https://graph.microsoft.com/v1.0`; the
   `Graph` wrapper pins it. If an endpoint exists only in beta, that is a
   design conversation, not a script.
5. **File the gap.** A direct call is a workaround, not a capability. Add or
   update a `board/` backlog item (see CKM-32 for the template) so the tool
   gets built — note what you called and any Graph behaviour that surprised
   you.
6. Throwaway scripts live in `tmp/` (git-ignored) and die with the task.

## Recipe 1 — JSON endpoints (use the `Graph` wrapper, it is free)

`Graph` gives you the base URL, bearer injection, 429/5xx retry with
`Retry-After`, `$batch`, and safe paging. Do not hand-roll httpx for JSON.

```python
# tmp/scratch_query.py — run with: uv run python tmp/scratch_query.py
from ckm365.config import load_profiles, resolve_profile
from ckm365.auth import Auth
from ckm365.graph import Graph, mailbox_path

profile = resolve_profile(load_profiles(), "intixa")   # profile name, see `ckm365 doctor`
auth = Auth(profile)                                   # read-only scopes, cached login
g = Graph(auth)
try:
    # single GET — any v1.0 path, params become the query string
    me = g.get("/me")

    # paged listing — follows @odata.nextLink, hard-capped page count
    for msg in g.paged("/me/mailFolders/inbox/messages",
                       params={"$select": "id,receivedDateTime",
                               "$top": "50"}, limit=200):
        ...

    # another mailbox (shared-mailbox rules apply, same as the server):
    path = mailbox_path("ops@intixa.com", "/messages")  # encodes safely
finally:
    g.close()
```

Notes that save time:
- `$select` everything explicitly — Graph's defaults are bloated and differ
  by resource. The dataclasses in `models.py` show the fields each tool
  considers canonical.
- `$filter` + `$orderby` combinations are rejected surprisingly often;
  filtered results come back in Graph's own order (`list_messages`'s
  docstring explains the consequence).
- `search` (KQL) cannot be combined with `$filter` at all.
- `g.batch([...])` for fan-out reads: 20 requests per round trip.

## Recipe 2 — raw bytes (`$value` endpoints): token + httpx

**Do not use `Graph.content()` for binaries** — it returns `.text` and was
built for VTT transcripts; it will corrupt a .docx/.pdf/.zip. Until a
`download_attachment` tool exists (CKM-32), fetch bytes with the token and
plain httpx:

```python
# tmp/scratch_download.py — the CKM-32 case: an attachment out of a message
import httpx
from ckm365.config import load_profiles, resolve_profile
from ckm365.auth import Auth

auth = Auth(resolve_profile(load_profiles(), "intixa"))
tok = auth.token()          # silent from the MSAL cache; raises NeedsLogin
                            # if there is no cached login — run the server
                            # or `ckm365 login <profile>` once, interactively

MSG = "AAMk..."             # from list_messages (any folder, incl. sentitems)
ATT = "AAMk...AAABEgAQ..."  # from list_attachments

url = (f"https://graph.microsoft.com/v1.0/me/messages/{MSG}"
       f"/attachments/{ATT}/$value")
with httpx.stream("GET", url,
                  headers={"Authorization": f"Bearer {tok}"},
                  timeout=60.0) as r:
    r.raise_for_status()
    n = 0
    with open("tmp/attachment.bin", "wb") as f:
        for chunk in r.iter_bytes():
            f.write(chunk); n += len(chunk)
print(f"wrote {n} bytes")   # counts only — never the filename of real mail
```

The same shape covers other `$value`/content endpoints: message MIME
(`/messages/{id}/$value`), contact photos, drive items (`/content`). Stream
anything that could exceed a few MB.

`fileAttachment` is the only kind with bytes behind `$value`;
`itemAttachment` (an embedded message) and `referenceAttachment` (a cloud
link) will not give you a usable file this way — check `@odata.type` in the
`list_attachments`/Graph metadata first.

## Scopes: what the cached token can and cannot do

The silent token carries whatever the profile's tier granted — see
`DELEGATED_RO` / `DELEGATED_RW` / `DELEGATED_SEND` / `APP_ONLY_SCOPES` in
`auth.py`. A direct call cannot exceed those scopes: if Graph answers
`403 ErrorAccessDenied`, the endpoint needs a permission this app has never
consented to (e.g. `Files.Read.All`, `Sites.Read.All`, `MailboxSettings.Read`)
— that is a consent-tier decision for the owner (compare CKM-18), never
something to solve by widening scopes in a scratch script.

## Where the Microsoft documentation actually is

| What you need | Where |
|---|---|
| Endpoint reference (v1.0, per resource) | learn.microsoft.com/graph/api/overview — drill into "Mail", "Calendar", etc.; each page gives the HTTP shape, permissions table, and example responses |
| Message / attachment resources | learn.microsoft.com/graph/api/resources/message and .../resources/attachment (the `$value` download is on "Get attachment") |
| Query parameters (`$select`, `$filter`, `$top`, paging) | learn.microsoft.com/graph/query-parameters and .../graph/paging |
| Permissions ↔ endpoint mapping | learn.microsoft.com/graph/permissions-reference — the authority for "which scope does this call need" |
| Batch | learn.microsoft.com/graph/json-batching |
| Throttling / 429 behaviour | learn.microsoft.com/graph/throttling (the wrapper already honours `Retry-After`) |
| **Graph Explorer** — try a call with your own account before scripting it | developer.microsoft.com/graph/graph-explorer |
| OpenAPI description of the whole API (the spec itself) | github.com/microsoftgraph/msgraph-metadata (`openapi/v1.0/openapi.yaml`; the CSDL `$metadata` lives there too) |
| Changelog (endpoints do move) | developer.microsoft.com/graph/changelog |

Two habits worth keeping: test the exact URL in **Graph Explorer** first (it
shows the required scopes inline and fails fast), and when a call misbehaves,
check `reference-notes.md` here — several hard-won Graph behaviours (filter
ordering, KQL exclusivity, shared-mailbox 403 semantics) are already written
down.
