# Next session — ckm365-93 — 2026-10-26 19:20 Melbourne

You are resuming ckm365, the multi-tenant Microsoft Graph MCP server, on the
correspondence-in-a-repo work. You are probably on a NEW machine. Read this
first, then `AGENTS.md` (it chains to CLAUDE.md and everything else).

This file is committed to the PUBLIC repo on purpose, so it can travel with
the clone. It therefore names no profiles, tenants, hosts or clients. Real
profile names come from `uv run ckm365 doctor` on the machine you are on.

## State — verified 2026-10-26 08:18Z

- Repo: `main` at the commit carrying this file, pushed. Nothing
  uncommitted, nothing unpushed, no stashes, one worktree.
- Released: **v2.9.0**, tagged and pushed (commit 4174549).
- Offline suite: 188 passed, 15 skipped. Live suite: 14/14 on both
  delegated tenant profiles.

## New machine: what does NOT travel with git

Check these before anything else; without them the live checks cannot run.

- Requirements now travel with git as `docs/requirements.md`. The
  original brief in `tmp/` is the owner's private copy and is not needed.
- `~/.config/ckm365/profiles.toml` (mode 600) and the per-profile MSAL token
  caches in ckm365's state dir (see `state_dir()` in `src/ckm365/auth.py`).
  Copy them, or run `uv run ckm365 login <profile>` per profile (device code,
  seanwy completes it).
- The app-only profile needs its cert or secret env vars. Doctor reports
  them missing on the old machine too; that is a known state, not a new fault.
- MCP registration of `ckm365 serve` in Claude Code, if this machine should
  serve the tools. Reconnect with `/mcp` after any tool signature change.
- Then: `uv sync`, `uv run pytest tests/ -q`, `uv run ckm365 doctor`.

## Done this session

- **4qn81m shipped in v2.9.0** (board: done). `export_message` takes
  `dedupe_dir` and `force`: it scans the folder's `.md`/`.markdown`/`.txt`
  front matter and `.eml` headers for the RFC 5322 Message-ID and returns
  `already_exported` instead of writing. Code: `_already_exported` in
  `src/ckm365/tools/mail/export.py`. `confine()` in `tools/mail/disk.py`
  fences the scan with the download root.
- `internet_message_id` moved from `Message` to `MessageSummary`, so
  `list_messages` and delta rows carry it (+~105 B/row, +10-11%, measured).
- Live export test fixed: it asserted the `timestamp:` line v2.8.0 removed.
- Identifiers scrubbed from two backlog issue bodies (xfccc0, dqgcdk).
- Filed **mr31re**: the correspondence migration helper (backlog, high).

## In flight

Nothing running. No background jobs, agents or deploys.

## Focus

"next: migration helper for existing correspondence folders, then CKM-49
threading, subfolders/search cap, bulk export, recipient exclusions."
seanwy asked for a "cleanup" or "migration helper" function agents can use
to migrate existing structures to new ones.

## Next actions — in order

1. **Migration helper (mr31re).** Read
   `board/issues/backlog/correspondence-migration-helper-mr31re.md`; it is the
   brief. Move it to `doing` with `git mv` and add a comment file. Build the
   read-only `plan_correspondence_migration(dir)` first: pure local file
   classification, reusing `_front_matter_id`/`_eml_id`/`_id_key` from
   `export.py` (promote them to non-underscored shared helpers if a second
   module needs them, per AGENTS.md). Then `migrate_correspondence` with
   `dry_run=True` default. First live question to answer: does
   `$filter=internetMessageId eq '<id>'` on `/messages` work and find
   just-arrived mail, or does it lag like subject filters do? Test it on both
   tenants before building on it. Decide tool vs `ckm365 migrate` CLI then.
2. **CKM-49 threading** (`tvtrb0`, high). Add `conversationId`,
   `conversationIndex`, `uniqueBody` to `Message.SELECT`, `in-reply-to`
   and `references` to `_CURATED_HEADERS` in `models.py`, default the
   record body to `uniqueBody` with a `body_scope` key, and `resource:
   mid:<id>`. Every existing record diffs once, which is exactly what the
   migration helper must handle; extend its plan to detect pre-CKM-49 records.
3. **Subfolders and the search cap** (`xfccc0`). `list_mail_folders` is
   top-level only; `list_messages(search=...)` stops near 275 rows silently.
4. **Bulk export** (`k4r9tw`, CKM-53). Now unblocked by dedupe. Includes the
   file-name token deferred from 4qn81m item 3.
5. **Recipient exclusion list** (`cw81fa`). Warn on draft, refuse on send.

Follow AGENTS.md "working loop" for each: board move, tests, identifier
check (also `--rev-range origin/main..HEAD`), live checks on both tenants,
version bump, CHANGELOG, commit, tag, push.

## Also open

- `kw20z6` (CKM-44, high): `export_transcript`. Recurred 16 Oct, done
  by graph-direct script again.
- `tc3vj9` (CKM-47): reply-draft font. Needs seanwy to check in Outlook.
- `g669gd` (CKM-51): `set_categories`. Small, write tier.
- `ba1m7k` (CKM-46 item 3): `doctor --mcp`.
- `2tcqc0` (CKM-55): nightly audit exit codes and baselines.
- `e3b7nr` (CKM-30): in `doing`, blocked on a tenant switch.

## Waiting on the user

- **History rewrite.** Pushed history still holds identifiers: a dev box
  name, a vendor name and both real profile names (commit 31d5b22's issue
  file, the dqgcdk issue, and `board/comments/dqgcdk/s4xcdb.md`, left
  unedited because comments are append-only). Options: leave it, or rewrite
  history and force-push. seanwy's call.
- **Teach the identifier check profile names?** `scripts/check-identifiers.py`
  cannot see real profile names, which is how they slipped through. Option:
  read names from the local profiles.toml at check time, never storing them.

## Gotchas

- OIF comment ids use a Crockford-style alphabet: no `i`, `l`, `o`, `u`.
  `7b9hel.md` failed validation. Generate from
  `0123456789abcdefghjkmnpqrstvwxyz`.
- `check-identifiers.py --rev-range` flags the URL in each commit's
  `Claude-Session:` attribution trailer. That is an accepted false positive;
  30+ pushed commits carry it.
- Board files written by other sessions sometimes lack quotes in front matter
  or carry real names. Re-read before committing them.
- A newer uv bumps `uv.lock`'s `revision` on any version bump. Commit it
  with the bump; no dependency changes rode along in v2.9.0.

## Key references

- Brief: `board/issues/backlog/correspondence-migration-helper-mr31re.md`
- Done: `board/issues/done/dedupe-exports-by-rfc-5322-message-id-4qn81m.md`
- Export code: `src/ckm365/tools/mail/export.py`, `tools/mail/disk.py`
- Tests: `tests/test_mail_export.py` (dedupe section at the end),
  `tests/test_live.py::test_export_message_both_formats`
- Board validate: `uvx --from oifmd oifmd validate board`
