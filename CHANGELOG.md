# Changelog

All notable changes to ckm365 are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

## [2.6.0] — 2026-08-19

Closes the compose → send → verify loop (CKM-42, option A of CKM-41).
Five thin tools and one profile key, aimed squarely at the eight
Graph-direct scripts a real outbound cycle needed on 2026-08-18. No new
Graph scope, no consent prompt, no tenant-wide operation.

### Added
- **`revise_draft`** (write tier) — rewrite the text YOU wrote in a draft
  and keep the quoted history and the signature. Draft bodies composed by
  ckm365 are now FENCED with HTML comments
  (`<!--ckm365:body-->` / `<!--ckm365:signature-->`, invisible in every
  mail client), and `revise_draft` replaces what is inside the body fence.
  On an unfenced draft — written in Outlook, or created before this
  version — it inserts at the top of `<body>` and fences that, so the next
  revision replaces properly. Caller HTML containing a marker is refused,
  so the fence cannot be forged from the inside.
- **`signature_html`** on a profile in `profiles.toml` (max 8 KB, TOML
  multi-line literal) — appended below your text by `create_reply_draft`,
  `create_forward_draft` and `create_draft`, in its own fence, so revising
  the text above never disturbs it. `signature=False` skips it for one
  call. Local by design: Outlook's roaming signature would need
  `MailboxSettings.Read`, a scope this app deliberately never requests.
- **`discard_draft`** (write tier) — throw away a draft, refusing anything
  that is not one. Graph moves a deleted message to Deleted Items rather
  than purging it, so it stays recoverable; `move_message`'s refusal to
  delete delivered mail is unchanged. Switching a reply to a reply-all is
  discard + `create_reply_draft(reply_all=True)`, since Graph fixes the
  recipients when it seeds the draft.
- **`remove_attachment`** (write tier) — `add_attachment`'s inverse,
  drafts only, selecting by `attachment_id` or exact `name` with the same
  never-a-silent-first-match rule as `download_attachment`. Any kind can
  be removed (removal needs no bytes, unlike downloading).
- **`verify_message`** (READ tier) — the pre-send check, in one call:
  recipients, attachment names/sizes/kinds/inline flags, whether the
  quoted thread survived, whether the signature is still there, the text
  you wrote as plain text (capped at 4000 chars), and the non-ASCII
  characters in it with counts — the smart-quote check, reported and never
  corrected. `boundary` says whether that text was told apart exactly
  (`fence`) or by falling back to the signature/quote markers. Works on
  the sent copy as well as the draft.

### Changed
- `update_draft`'s docstring now says plainly that `body_html` replaces
  the WHOLE body and points at `revise_draft`; it remains the tool for
  subject and recipients.
- `require_draft` takes the caller's `$select` and headers, so the
  draft guard doubles as the read-before-write instead of costing a
  second GET.
- `_select_attachment` no longer refuses non-file attachments; that rule
  moved to the download path, where it belongs.
- `scripts/draft-cycle-smoke.py` walks the whole loop (seed → verify →
  attach → revise → remove → discard) through the tools, and no longer
  deletes its draft with a raw Graph `DELETE`.
- `docs/graph-direct.md` opens with "check there is not already a tool"
  and a table of the hand-rolled calls that now have one. Part of the
  2026-08-18 friction was DISCOVERABILITY, not missing capability: one
  script archived a message from `/$value` when `export_message` already
  did that job better.

### Verified
- 153 offline tests pass (19 new in `tests/test_mail_compose.py`: fenced
  revision keeps quote and signature, unfenced fallback, forged-marker
  refusal, If-Match on revision, draft-only guards on discard and
  attachment removal, ambiguous-name refusal, and every field
  `verify_message` reports including the inline-attachment case Graph
  reports as `hasAttachments: false`).
- Two live tests added to `tests/test_live.py` (the compose loop end to
  end with a residue check, and the draft-only guards against real Graph)
  — env-gated as always, and NOT yet run.
- NOT yet live-verified: neither those nor
  `scripts/draft-cycle-smoke.py` has been run against a real mailbox.
  Offline mocks have missed real Graph behaviour before — run it before
  relying on the loop.

## [2.5.1] — 2026-08-11

Housekeeping only: no tool, signature, or behaviour changed.

### Changed
- **`tools/mail.py` is now `tools/mail/`**, split at the seams it had
  grown: `common` (paths, Prefer headers, the draft guard, `/$batch`
  fan-out), `disk` (local-disk discipline), `read`, `attachments`,
  `export`, `drafts`, `triage`. The file had passed 1000 lines, which
  CLAUDE.md names as the signal to stop and restructure; no module now
  exceeds ~265. `ckm365.tools.mail` re-exports every tool, so the
  SemVer'd import path and the import-contract test are untouched —
  import from the package, never a submodule.
- The move was mechanical and is checked as such: an AST comparison
  proves all 48 definitions are identical to their pre-split form, modulo
  the shared helpers that dropped a leading underscore (`message_path`,
  `apply_each`, `write_target`, …) now that they cross module lines.

### Fixed
- `create_draft` had no offline test that reached its Graph call — the
  gating test stops at `WriteDisabled` — so a missing import in that path
  was invisible to 133 offline tests and reachable only live. The split
  surfaced it; there is now a test that asserts the POST URL and body.

### Board hygiene
- Scrubbed real tenant profile names from six issues and a client
  engagement plus a person's name from CKM-32: the PUBLIC-repo rule
  forbids them and board history had accumulated them anyway.
- Repaired four issue files written in v1.2.0 that did not parse as YAML
  (an unquoted `details:` carrying a `": "`). All 40 issues now parse and
  every `column` matches its directory.

## [2.5.0] — 2026-08-11

Correspondence that agents can actually search, and the first end-to-end
test of the send tier. 32 tools total.

### Added
- **`export_message`** (CKM-39, read tier): writes one message to a file,
  with **the extension choosing the format** — one source of truth, and
  the caller states intent naturally.
  - `.md` / `.markdown` / `.txt` — a GREPPABLE record, and an **Open
    Knowledge Format v0.1 document** (openknowledgeformat.com): YAML front
    matter carrying OKF's `type`/`title`/`description`/`resource`/`tags`/
    `timestamp`, then mail-specific extension keys (from, to, cc, mailbox,
    message ids, bulk and auto-reply flags), the body as PLAIN TEXT, and
    an attachment manifest carrying each `attachment_id` so
    `download_attachment` can fetch the bytes. Deterministic — re-exporting
    the same message produces the same file, so git shows no diff.
  - `.eml` — the raw MIME exactly as Graph serves it, for an evidence
    archive.
- **Live send-cycle test** (CKM-40), `tests/test_live_send_cycle.py`: the
  send tier end to end — draft + attachment → `send_draft` → poll for
  delivery → `download_attachment` off the DELIVERED copy and compare
  bytes → `create_reply_draft(reply_all=True)` → send → poll for the
  reply. Double-gated (`CKM365_LIVE_ACCOUNT` **and** `CKM365_LIVE_SEND=1`),
  self-addressed only (asserted before anything is sent), zero residue.
  The whole cycle runs in ~20s on both tenants.

### Fixed / documented
- **Three silent Graph subject-filter traps**, all found by the new
  send-cycle test, all returning zero rows — indistinguishable from "there
  is no such mail":
  - `$filter=subject eq '<exact subject>'` never matches, even when the
    subject is byte-identical. Reproduced on a message the test had just
    sent and received, where `startswith` and `contains` matched it in the
    same call sequence.
  - `contains(subject,'…')` returns nothing once the folder is large: it
    matched on a small mailbox and never matched in a 93k-message inbox
    where `startswith` matched immediately.
  - **Even `startswith(subject,'…')` lags delivery.** A reply delivered at
    23:22:09 stayed invisible to it for the remaining five minutes of a
    poll, and the same query found it eleven minutes later. Subject
    predicates read an index that trails the folder; an unfiltered
    newest-first listing sees the message at once. This one cost two
    ten-minute red herrings ("slow tenant") before it was pinned down —
    the cycle now runs in ~20s on the mailbox that appeared to be slow.

  Consequence, now documented in `list_messages`' docstring, `AGENTS.md`
  gotchas and `docs/graph-direct.md`: prefer `startswith` for searching,
  and NEVER poll for just-arrived mail with any subject filter — list
  newest-first and match client-side, or use the delta-based
  `list_new_messages` / `wait_for_message`, which see it immediately.

### Notes
- **`.eml` alone could not do the job, and that is why `.md` exists.**
  Exchange base64-encodes body parts, so a raw `.eml` frequently contains
  none of the words in the message. Measured over 10 real messages across
  both tenants: a distinctive word from each message's own preview was
  found in the `.eml` 7 times out of 10, and in the `.md` record 10 out of
  10 — at 4-7x smaller files (1.8-40 KB vs 8.6-289 KB). A repo of base64
  defeats the point of keeping correspondence beside the work.
- **OKF by default, not behind a flag.** OKF permits extension keys, so
  one format can be both an OKF document and a full mail record — a flag
  would buy two code paths and two things to test for no gain. Where OKF
  has a name for something (`title`, `timestamp`, `resource`), OKF's name
  is used and nothing is written twice. The direction tag is OMITTED when
  Graph has no sender (an unsent draft): calling that "inbound" would be a
  lie in the one field an index groups on.
- **No `.msg`.** Outlook's format is proprietary OLE compound binary, no
  Graph endpoint produces it, it is not greppable, and writing it would
  need a third-party dependency — three strikes against, one of which is
  a hard rule here.
- **Graph does the HTML→text conversion**, via the `Prefer:
  outlook.body-content-type="text"` header `get_message` already uses. No
  local HTML stripping, no new dependency, and the text matches what
  Outlook itself would show.
- **Attachment bytes are never written by an export.** The record names
  them and carries their ids; `download_attachment` fetches them
  deliberately. A `.eml` embeds them because MIME does.
- **Front matter is quoted defensively**: a subject full of colons,
  quotes or newlines cannot break the YAML or inject a second `subject:`
  key — control characters are stripped and scalars are escaped.
- **`tests/test_live.py` keeps its "never sends" invariant** — the send
  cycle lives in its own file behind its own env gate, so the default live
  suite is still safe to run anywhere.
- Out of scope, per the issues: bulk/threaded export, downloading
  attachments as a side effect of an export, and sending to any third
  party from a test.

## [2.4.0] — 2026-08-11

The gap that got hit twice in live engagements (CKM-32): the server could
LIST attachment metadata and ATTACH a local file to a draft, but there was
no way to get an attachment OUT of a message. Both hits were ~3 MB
documents — a counterparty .xlsx for analysis, then a 2.96 MB .docx
meeting transcript in SENT ITEMS that had to land in an engagement repo —
and both were worked around with a throwaway script. 31 tools total.

### Added
- **`download_attachment`** (CKM-32, read tier): saves one attachment of a
  message to a file on the server's disk. The bytes stream from Graph's
  `/attachments/{id}/$value` straight to the file and NEVER pass through
  agent context — the point is to put a document in a repo, not a
  base64 blob in a transcript. Select by `attachment_id` or by exact
  `name`; a shared name is an error listing the candidate ids, never a
  silent first match. `dest_path` may be a file path or an existing
  directory (the attachment names itself, separators stripped).
- **`Graph.download(path, dest)`**: the streaming binary path, with the
  same auth, error and retry policy as every other call. `content()` is
  text-only and would corrupt a .docx — that trap is now closed.
- **`Attachment.kind`**: Graph's `@odata.type` minus the
  `#microsoft.graph.` prefix, so `list_attachments` says which
  attachments are downloadable at all.
- **`docs/graph-direct.md` rewritten** as the escape-hatch guide for
  endpoints with no tool: how to get credentials without minting a token
  (`Ctx.create` → `ctx.target`), recipes for JSON / batch / raw bytes,
  how to read a 403, and a per-resource index into Microsoft's API
  reference plus Graph Explorer. `list_accounts`' description and
  `graph.py` now point at it, so both an MCP-only agent and someone
  reading the code land in the same place.

### Notes
- **No new consent.** `Mail.Read[.Shared]` already covers
  `/messages/{id}/attachments` — a read-tier server can do this today.
- **Read tier, despite writing bytes.** The tier ladder gates what
  happens in the TENANT; this only reads there. The local write is
  confined by `CKM365_DOWNLOAD_ROOT`, falling back to
  `CKM365_ATTACH_ROOT` so an operator who fenced the read side gets the
  write side fenced by the same setting.
- **One code path, not two.** The sketch proposed inline `contentBytes`
  below ~3 MB and `$value` streaming above it. Streaming always is
  simpler, has no threshold to get wrong, and never buffers a file in
  memory; both real-world hits sat exactly on the boundary that a
  threshold would have introduced. Live-verified on 4.9 MB and 11.9 MB
  attachments.
- **Sent items behave identically** — verified on both tenants.
  Attachments hang off the message id, so no folder appears in the URL at
  all; that is now an offline assertion as well as a live test.
- **Attachment `size` is not the file size** (measured, both tenants): it
  counts the MIME-encoded attachment including headers, running +210-230 B
  on synthetic files and up to ~3.8 KB on real mail. Treat it as an upper
  bound; the tool reports what actually landed.
- **`@odata.type` survives `$select`** — it is OData control information,
  not a property, so a five-field listing still says whether each
  attachment is a fileAttachment. That makes refusing an itemAttachment
  (an embedded message) or referenceAttachment (a cloud link, no bytes in
  the mailbox) cheap, with a reason instead of a broken file.
- **Safety defaults**: never overwrites an existing file; a failure
  part-way leaves no residue (bytes land in a `.part` file that is
  renamed only on success); attachment-derived filenames are reduced to a
  bare name (both separator kinds, control characters stripped) before
  the root check; the log line carries ids, counts and byte totals only —
  never the filename, which can name a counterparty and a project.
- Out of scope, per the issue: bulk "download all attachments",
  attachments on calendar events, and any parsing of what was downloaded.

## [2.3.0] — 2026-08-05

Two gaps a downstream consumer hit on the same triage design (CKM-37/38):
message listings could not say who a message was addressed TO, and nothing
could say whether it was bulk or machine-sent. 30 tools total.

### Added
- **`to` and `cc` on every listing row** (CKM-37): `MessageSummary` gains
  them and `list_messages` selects them, which unblocks two things at
  once. In **sentitems** the sender is always the mailbox owner, so the
  recipient IS the correspondent — "who does this user actually email"
  was previously unanswerable from the one folder that knows. And in a
  mailbox **shared by two parties**, the address a message was delivered
  to is the strongest available signal for which party it belongs to;
  the fallback (subject and counterparty-domain heuristics) was weakest
  exactly where being wrong costs most, since different retention and
  disclosure expectations attach to each party.
- **`get_message_headers`** (CKM-38, read tier): a CURATED subset of a
  message's internet headers for many messages at once —
  `List-Unsubscribe`, `List-Id`, `Precedence`, `Auto-Submitted`,
  `X-Auto-Response-Suppress`, `Return-Path` — plus derived `is_bulk` and
  `is_auto_reply` flags. Takes a LIST of ids and batches 20 to a round
  trip, the same convention as the triage tools, but only reads.
  `get_message` carries the same curated projection for a single message.

### Notes
- **No new consent.** `toRecipients`/`ccRecipients`/`internetMessageHeaders`
  are ordinary message properties under `Mail.Read[.Shared]`; a read-tier
  server needs nothing more.
- **Named fields, not a caller-supplied `$select`.** CKM-37 offered both.
  Named fields won: models own their `$select` here, so a caller-driven
  projection would make the return shape dynamic, push Graph's own field
  names into consumer code, and hand an agent a way to request fields
  (bodies, headers) that these tools deliberately keep off list rows. The
  addition is additive on a pinned API; `Message.to`/`.cc` keep their
  names and simply move to the base class.
- **Measured before deciding against an opt-in flag.** Recipients cost
  **+141 bytes/row (+17%)** over 100 real inbox rows on each of two
  tenants (848→988 and 830→970 B/row). That is not enough to justify a
  flag on every call, so `list_messages` has none; if a caller paging
  thousands of rows disagrees, that is a new issue with a number attached.
- **`bcc` stays off listings**: Graph populates it only on the sender's
  own copy, so it would be an empty column on nearly every row.
  `get_message` still returns it.
- **Header values are UNTRUSTED, curated or not.** A forged
  `List-Unsubscribe` proves only that someone wrote one. They are for
  classification and prioritisation — never authorisation or trust. The
  raw values are returned alongside the derived flags precisely so the
  derivation can be audited and overridden. Values are stripped of
  control characters (a header must not inject line breaks into a log or
  a context) and capped at 200 characters with a trailing `…`; live
  sampling showed only `List-Unsubscribe` ever exceeds that (mean ~330,
  max 543 chars).
- Out of scope, per the issues: recipient-based server-side filtering,
  address-book resolution, full header dumps, DKIM/SPF/DMARC results, and
  header-based filtering (Graph does not support it).

### Graph facts learned live (the issue's sketch was wrong)
- **`internetMessageHeaders` IS returned on a collection GET** when
  explicitly `$select`ed — CKM-38 assumed it was not, and that assumption
  was the reason it demanded a per-message design. Verified on both
  tenants: 25/25 rows populated, 47–86 headers each. What makes it
  unsuitable for `list_messages` is therefore **volume, not N+1**: those
  rows cost ~10.6–11 KB each, roughly 11× a summary row. So the tool is
  still deliberate and explicit, but the reason changed, and a caller who
  wants headers for a whole folder now has a cheaper route available if a
  future issue wants it.
- `/$batch` accepts `$select` in sub-request URLs (20 GETs, 20/20 answered).
- A single-message GET returns the same recipient lists as the collection
  GET for the widths seen live (up to 7 recipients) — no truncation
  observed, though `get_message` remains authoritative.
- Adding `internetMessageHeaders` to `get_message`'s `$select` costs
  ~9 KB on the wire per call (2.5 KB → 11.9 KB on a small message);
  curation means only a few hundred bytes reach the caller.

### Verified (live, both delegated tenants)
- `tests/test_live.py` — **9 passed on each profile**, including the new
  recipients/headers check (read-only, no residue).
- Sent Items really answers the correspondent question now: 25/25 rows
  carried `to`, yielding 11 and 58 distinct correspondents from one call.
- Alias routing is resolvable: 25 inbox rows carried 12 and 15 DISTINCT
  delivered-to addresses, and 21/25 and 20/25 rows were addressed to
  something other than the mailbox's primary address.
- Headers beat the subject regex they replace: over 25 real inbox
  messages per tenant, `is_bulk` found 7 and 14, of which a
  representative subject regex missed 7 and 6 — while producing 5 false
  positives of its own on one tenant. `is_auto_reply` found 0 and 7.
- `scripts/live-smoke.py` (both tenants, one with `--triage`) and
  `scripts/draft-cycle-smoke.py` still pass — the latter matters because
  `Draft.SELECT` now includes the header property and is used on PATCH.
- Offline suite: 114 passed (was 101).

## [2.2.0] — 2026-08-05

The mail **triage** slice, filed from a real triage task that hit every one
of these gaps in one sitting (CKM-33/34/35/36). 29 tools total.

### Added
- **Read state, batched** (CKM-33): `mark_read` / `mark_unread` take a
  LIST of message ids and return `{"ok", "failed": [{"id", "error"}]}`.
  Batch is the point, not a convenience — the run that motivated this
  touched 25 messages, which per-message tools would make 25 round trips
  and 25 approval prompts. Read state and folder stay independent: the
  mail does not move.
- **Flags** (CKM-34): `flag` (optional `due`/`start`), `unflag`,
  `complete_flag`. A flag with **no date is the default** — an agent
  should not have to invent one. `complete_flag` is deliberately distinct
  from `unflag`: "done" and "never mind" are different triage outcomes.
- **First-class filter predicates** (CKM-35): `list_messages` gains
  `unread_only`, `flagged_only`, `since`, `from_address`, composed into
  ONE server-side `$filter`. All four push to Graph — none degrades to a
  client-side scan. The raw `filter` escape hatch remains and is now
  ANDed in alongside rather than competing with them.
- **`group_by_sender`** (CKM-35, read tier): sender → `{total, unread}`
  for a folder, projecting `from,isRead` only, so no subject, preview or
  body crosses the caller's context. Establishing "six automated senders
  are ~40% of this inbox" previously cost 1500 messages of context; it is
  now one call. Live: 500 messages → 148 senders in one round of paging.
- **`move_message`** (CKM-36): files messages into a well-known folder or
  a folder id, same convention as `list_messages`' `folder`. Returns the
  `{old_id: new_id}` mapping, because a move mints a new id and the old
  one becomes a dead reference. Refuses to create folders implicitly — an
  unknown destination is an error naming the folders that exist. **Delete
  is deliberately absent**: moving to `deleteditems` is reachable here and
  reversible; permanent deletion is not, and does not belong in an
  agent-callable surface.
- `Graph.batch()` — the `/$batch` primitive behind all six write tools:
  20 sub-requests per round trip, re-ordered back into input order (Graph
  answers unordered), per-item failures reported as data rather than
  raised, and throttled sub-requests re-sent once.
- Optional `timezone` key in `profiles.toml`, and `--triage` on
  `scripts/live-smoke.py` (read-only; prints counts and sender DOMAINS,
  never full addresses).

### Fixed
- **Transient 503s outlived the retry budget** (CKM-35): a filtered
  `list_messages` on a large mailbox answered
  `503 ErrorInternalServerTransientError "Cannot query rows in a table"`
  twice in a row and surfaced as a hard failure, forcing a fallback that
  paged 1200–6000 messages to find ~20 and blew a 120s tool timeout. The
  filtered path was never bypassing retry — the budget was simply too
  short: three retries on a 0.2s base all landed inside one blip. 503/504
  now get 5 retries on a 1s base (~6s expected, ~17s worst), while
  throttling keeps the old budget and its `Retry-After` handling.

### Notes
- **No new consent.** Everything here is `Mail.ReadWrite`, already in the
  delegated read-write scope set — a `--write` server needs nothing more.
  Triage is **write tier, never send tier**: read state, flag and folder
  are metadata, and nothing leaves the tenant.
- **Bare dates are never silently UTC** for flags. Zone resolution is:
  an offset in the value → the `timezone` argument → the profile's
  `timezone`; none of those is an error, not a guess, because "due today"
  in the wrong zone is wrong by up to a day. The zone actually used comes
  back in the result. Reading the mailbox's own zone from Graph would
  need `MailboxSettings.Read`, a scope this app deliberately does not
  request — hence the config key.
- **A filter drops Graph's ordering.** Documented on `list_messages` now:
  `$search` cannot combine with any filter, and any `$filter` returns
  results in Graph's default order, so `top` means "N matches", not "the
  N newest". This surprised the caller mid-task.
- Deliberately **out of scope**, per the issues: marking a whole folder
  read in one call, filter-driven (rather than id-driven) state changes,
  reminders, categories, copy, cross-mailbox moves, folder creation, and
  cross-folder search.

### Verified (live, both delegated tenants)
- `tests/test_live.py` — 8 passed on each profile, including the new
  triage cycle (read state → flags with and without dates → move →
  delete) run against a message the suite creates, so no real mail is
  touched, and the residue 404 check still passes.
- Partial failure proven against Graph: a real id batched with a bogus one
  returns `ok=1` plus one `failed` entry, not a dead batch.
- `scripts/live-smoke.py --triage` on both tenants: `isRead eq false` —
  the exact filter that 503'd — now returns server-side, and
  `group_by_sender` scanned 500 messages into 148 / 106 senders.
- Offline suite: 101 passed (was 73).

## [2.1.1] — 2026-08-01

### Fixed
- **Teams reads 400'd on first live use**: `/me/joinedTeams`,
  `/teams/{id}/channels`, and `/teams/{id}/installedApps` all reject
  `$top` ("Query option 'Top' is not allowed") — only the `/teams`
  collection accepts it. The three calls now send no `$top` and the
  caller's `top` is applied client-side by `pull()`/`paged()`, which
  already caps results and stops paging. `$select`/`$expand` are
  unaffected. Offline mocks accept any query string, so this was
  invisible until the consent tier existed and the reads ran for real —
  a regression test now asserts no `$top` is ever sent, and that the
  client-side cap still truncates.

### Verified (live, delegated profile)
- `list_teams` → 2 teams, `list_channels` → 1 channel,
  `list_installed_apps` → capped at the requested 10 of 63 available
  (proving the client-side cap).
- Negative: the app-only profile — which holds ZERO Graph application
  permissions by design — is refused Teams with 403. Exchange RBAC does
  not cover Teams, so that refusal is the whole app-only story here.

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
