# Next session — ckm365-93 — 2026-10-26 (updated 23:00 Melbourne)

You are resuming ckm365, the multi-tenant Microsoft Graph MCP server, on the
correspondence-in-a-repo work. Read this first, then `AGENTS.md` (it chains
to CLAUDE.md and everything else; it has a NEW section, "Codex as
co-pilot", which this session added).

This file is committed to the PUBLIC repo on purpose, so it can travel with
the clone. It therefore names no profiles, tenants, hosts or clients. Real
profile names come from `uv run ckm365 doctor` on the machine you are on.

## State — verified at the v2.10.0 release

- Repo: `main` at the commit carrying this file, pushed. Nothing
  uncommitted, nothing unpushed, no stashes, one worktree.
- Released: **v2.10.0**, tagged and pushed.
- Offline suite: 226 passed, 15 skipped. Live suite: 14/14 on both
  delegated tenant profiles. live-smoke OK on both.

## New machine: what does NOT travel with git

- `~/.config/ckm365/profiles.toml` (mode 600) and the per-profile MSAL
  token caches in the state dir (`state_dir()` in `src/ckm365/auth.py`).
  Copy them, or `uv run ckm365 login <profile>` per profile.
- The app-only profile needs its cert or secret env vars; doctor reports
  them missing here too, a known state.
- MCP registration of `ckm365 serve` in Claude Code. Reconnect with `/mcp`
  after any tool signature change (two tools were added this release).
- For the Codex loop: `codex` CLI logged in, omni checked out beside this
  repo, and the warmed uv cache under /tmp (recreate after a reboot; the
  AGENTS.md section says how).
- Then: `uv sync`, `uv run pytest tests/ -q`, `uv run ckm365 doctor`.

## Done this session

- **mr31re shipped in v2.10.0** (board: done): `plan_correspondence_migration`
  and `migrate_correspondence` in `src/ckm365/tools/mail/migrate.py`, read
  tier. The planner was run read-only over four real folders; the apply
  step was dry-run over two. NOT applied for real anywhere yet.
- **Codex as co-pilot is live** for this repo: three cards merged
  (h59xfz, dr4f2n, cxsznh). Claude wrote test-first specs on main and the
  cards; Codex implemented in a sandboxed worktree. Costs 3-10 model
  calls per card. The blockers found and fixed are in AGENTS.md.
- The offline suite is hermetic (`tests/conftest.py`); it steps aside for
  live runs.
- Filed **5gkkbh**: Codex as a ckm365 MCP CLIENT (seanwy wants this
  eventually). Unstarted; its questions are on the issue.
- Live fact: `$filter=internetMessageId eq '<id>'` on `/messages` works on
  both tenants, across folders. Under-five-minute arrival unmeasured.

## Focus (unchanged)

"next: migration helper, then CKM-49 threading, subfolders/search cap,
bulk export, recipient exclusions." Migration helper is done; the rest
in that order.

## Next actions — in order

1. **CKM-49 threading** (`tvtrb0`, high). `conversationId`,
   `conversationIndex`, `uniqueBody` on `Message.SELECT`; `in-reply-to`,
   `references` in `_CURATED_HEADERS`; record body defaults to
   `uniqueBody` with a `body_scope` key; `resource: mid:<id>`. Every
   record diffs once: extend the planner's version detection so a
   pre-CKM-49 v0.2 record becomes an `upgrade`, and the apply step
   handles it. Good Codex cards: the model/select change, the record
   change, the planner extension — each test-first.
2. **Subfolders and the search cap** (`xfccc0`).
3. **Bulk export** (`k4r9tw`, CKM-53), with the file-name token.
4. **Recipient exclusion list** (`cw81fa`).
5. Small follow-ups from the real-folder runs (in mr31re's last comment):
   a `note` kind for front-matter-less files, a pair destination when
   `<stem>.md` is taken, `nk2jc6` (correlate mail to work items).

Follow AGENTS.md "working loop" for each, and "Codex as co-pilot" when
handing implementation to Codex.

## Waiting on the user

- **Apply the migration for real** on a project folder: pick one, run
  `migrate_correspondence` with `dry_run=false` on a clean git tree, review
  the diff. Not done because it rewrites files in private repos.
- **History rewrite.** Pushed history holds identifiers: the earlier
  list (a dev box name, a vendor name, both profile names in commit
  31d5b22's issue file, the dqgcdk issue and a comment), plus this
  session's own: a home-directory path in a Codex report comment
  (commit 5542e3a, redacted in the next commit). Options unchanged:
  leave it, or rewrite and force-push. seanwy's call.
- **Teach the identifier check profile names?** Unchanged proposal.
- **5gkkbh**: when to start Codex-as-client, and whether its first
  registration is read-only (recommended).

## Gotchas (new ones first)

- Codex report comments land on the board verbatim and can quote absolute
  paths. `check-identifiers.py` BEFORE the commit that carries them, in a
  chain that cannot proceed on failure (this session pushed one with `;`).
- `test_tools_for_presets` pins every preset count; a new read tool moves
  SIX numbers (mail and all, each at three tiers). List that file on any
  card that registers a tool, or expect Codex to stop and ask.
- `test_live.py`'s export test slices the front matter of the NEWEST
  inbox message; it used `split("---")`, which a Jenkins notification
  whose description contains a dash run broke (one failure, same message,
  three runs). Fixed to partition on the closing fence. Any test reading
  a record should slice on `"\n---\n"`, never on bare dashes.
- OIF comment ids use a Crockford-style alphabet: no `i`, `l`, `o`, `u`.
- `check-identifiers.py --rev-range` flags the attribution trailer's
  URLs; accepted false positive.
- A newer uv bumps `uv.lock`'s `revision` on a version bump; commit it.

## Key references

- Brief: `board/issues/done/correspondence-migration-helper-mr31re.md`
- Code: `src/ckm365/tools/mail/migrate.py`, `export.py` (`record_bytes`)
- Tests: `tests/test_mail_migrate.py`, `tests/test_mail_migrate_apply.py`
- Codex loop: AGENTS.md "Codex as co-pilot"; `../omni/skills/copilot/`
- Board validate: `uvx --from oifmd oifmd validate board`
