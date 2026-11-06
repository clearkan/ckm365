# Next session — ckm365-93 — 2026-10-26 (updated after v2.12.0, 2026-11-07)

You are resuming ckm365, the multi-tenant Microsoft Graph MCP server, on the
correspondence-in-a-repo work. Read this first, then `AGENTS.md` (it chains
to CLAUDE.md and everything else; it has a NEW section, "Codex as
co-pilot", which this session added).

This file is committed to the PUBLIC repo on purpose, so it can travel with
the clone. It therefore names no profiles, tenants, hosts or clients. Real
profile names come from `uv run ckm365 doctor` on the machine you are on.

## State — verified at the v2.12.0 release

- Repo: `main` at the commit carrying this file, pushed. Nothing
  uncommitted, nothing unpushed, no stashes, one worktree.
- Released: **v2.12.0**, tagged and pushed (xfccc0, cw81fa, CKM-49,
  k4r9tw; five Codex cards).
- Offline suite: 372 passed, 18 skipped. Live suite: 17/17 on both
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
- **v2.10.1, a data-loss fix** (6v3d56, done): `upgrade` re-exported from
  Graph and replaced the whole file, deleting what a person had written
  below the mail. A second Claude session found it testing 2.10.0 on a
  real folder in a throwaway worktree (6 of 18 records affected, nothing
  lost for real). `upgrade` is now front-matter-only, no Graph call. The
  spec on cxsznh asked for the re-export, so the error was in the brief.
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

## Focus

The focus list ("migration helper, then CKM-49 threading,
subfolders/search cap, bulk export, recipient exclusions") is DONE as of
v2.12.0 (2026-11-07), all through Codex cards with Claude specs and
reviews. Pick the next focus with seanwy.

## Next actions — candidates, in the order Claude would take them

1. **kw20z6** (high): surfacing gaps, including inline images lost by
   export (CKM-44: `hasAttachments` is false for inline-only mail).
2. **tc3vj9**: reply body_html renders in the wrong font unless every
   paragraph carries a style. A compose bug users see.
3. **g669gd**: `set_categories`, a small write-tier triage tool; a good
   Codex card.
4. **Pair destination** when `<stem>.md` is taken: `export_messages`'
   name convention (`YYYYMMDD_<slug>_<token>.md`) is the obvious answer;
   seanwy to confirm before `pair` uses it.
5. **5gkkbh**: Codex as an MCP client, read tier first, never a global
   registration.

Follow AGENTS.md "working loop" for each, and "Codex as co-pilot" when
handing implementation to Codex.

## Waiting on the user

- **Apply the migration for real** on a project folder (v2.12.0 also
  upgrades pre-CKM-49 records: checked on copies of two real folders,
  92 records, every body byte-identical): pick one, run
  `migrate_correspondence` with `dry_run=false` on a clean git tree, review
  the diff. The session that found 6v3d56 has a throwaway worktree for
  this; it was asked to re-run on v2.10.1 and confirm the six annotated
  records keep their sections. Its report lands as a comment on 6v3d56.
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

- Codex's ChatGPT login does not always survive a reboot or a CLI
  upgrade. A tick that ends in 14 s with zero tokens and a "no valid
  report" comment is a 401: check `codex login status`; seanwy runs
  `codex login --device-auth`. Resume with a `review:` comment (uses one
  of the two rounds). The warmed uv cache under /tmp also goes with a
  reboot.
- A record's body is a person's document once exported. No migration step
  may regenerate it; `upgrade` and `backfill-id` edit lines BEFORE the
  closing fence only (`_front_matter_lines` in migrate.py). The planner
  cannot tell an annotated record from a clean one, so any future
  "re-export" action must diff bodies first and fall back to manual.
- An offline test proving a rewrite "keeps the body" must build the
  fixture WITH extra content below the body. The 2.10.0 fixtures had
  bodies the re-export reproduced, so the suite was green on a bug the
  first real folder showed.
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

- Brief: `board/issues/done/correspondence-migration-helper-mr31re.md`;
  the bug and its fix: `board/issues/done/migrate-upgrade-deletes-hand-written-sections-6v3d56.md`
- Code: `src/ckm365/tools/mail/migrate.py`, `export.py` (`record_bytes`)
- Tests: `tests/test_mail_migrate.py`, `tests/test_mail_migrate_apply.py`
- Codex loop: AGENTS.md "Codex as co-pilot"; `../omni/skills/copilot/`
- Board validate: `uvx --from oifmd oifmd validate board`
