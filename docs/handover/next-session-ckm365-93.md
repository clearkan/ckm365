# Next session — ckm365-93 — 2026-10-26 (updated after v2.13.0, 2026-11-07)

You are resuming ckm365, the multi-tenant Microsoft Graph MCP server, on the
correspondence-in-a-repo work. Read this first, then `AGENTS.md` (it chains
to CLAUDE.md and everything else; it has a NEW section, "Codex as
co-pilot", which this session added).

This file is committed to the PUBLIC repo on purpose, so it can travel with
the clone. It therefore names no profiles, tenants, hosts or clients. Real
profile names come from `uv run ckm365 doctor` on the machine you are on.

## State — verified at the v2.13.0 release

- Repo: `main` at the commit carrying this file, pushed. Nothing
  uncommitted, nothing unpushed, no stashes, one worktree.
- Released: **v2.13.0**, tagged and pushed: g669gd, kw20z6 (all four
  gaps), ba1m7k item 3, tc3vj9 (built, render check pending), 2tcqc0
  parts 1-2. Seven Codex cards, all merged; an independent review of
  the whole diff found no serious defect (its five cheap fixes are in).
- Offline suite: 493 passed, 18 skipped. Live suite: 17/17 on both
  delegated profiles at the release. The new pieces were also checked
  live one by one (see "Done").

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

## Done this session (v2.13.0, 2026-11-07)

- `set_categories` (g669gd), write tier. NOT exercised live: it writes
  to a real mailbox, so that waits for seanwy's OK.
- Inline images in records (kw20z6 gap 4). Live, read-only: 10 of 10
  cid markers rewritten on three inline-only messages. Measured: the
  plain `contentId` `$select` is a 400; the cast
  `microsoft.graph.fileAttachment/contentId` works.
- `export_transcript` (gap 2). Live: lookup and listing work; content
  routes answer 403 on both device-code profiles (consent tier or the
  Teams kill-switch), so a content pull is still unverified.
- `doctor --mcp` (gap 1, ba1m7k): run for real here, correct.
- `ckm365 refresh` (gap 3): run for real on one profile; the next read
  minted a fresh token silently.
- Compose font (tc3vj9), OPT-IN per profile (`compose_font`), because
  ckm365 cannot read the mailbox font. Needs the Outlook render check.
- `audit` exit codes, `--fail-on`, baseline (2tcqc0 parts 1-2).
- docs/usage-modes.md now records the transcript kill-switch findings.

## Done in earlier sessions

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

The v2.12.0 focus list and the v2.13.0 sweep (kw20z6, tc3vj9, g669gd,
ba1m7k, 2tcqc0 1-2) are DONE. What is left in the backlog is mostly
tenant work or design questions. Pick the next focus with seanwy.

## Next actions — candidates, in the order Claude would take them

1. **Pair destination** when `<stem>.md` is taken: `export_messages`'
   name convention (`YYYYMMDD_<slug>_<token>.md`) is the obvious answer;
   seanwy to confirm before `pair` uses it.
2. **5gkkbh**: Codex as an MCP client, read tier first, never a global
   registration.
3. **nk2jc6**: correlating mail to work items without a subject key; a
   design discussion before any code.
4. **dqgcdk**: one shared serve process instead of one per session
   (efficiency, not urgent).
5. Transcript change notifications (kw20z6's open question), if
   polling for transcripts keeps coming up.

Follow AGENTS.md "working loop" for each, and "Codex as co-pilot" when
handing implementation to Codex.

## Waiting on the user

- **tc3vj9 render check**: set `compose_font` on the affected profile,
  create a reply draft with three bare paragraphs, revise the middle
  one, and compare it with the quoted history in Outlook desktop and OWA.
  The issue stays open until then.
- **set_categories live**: OK to tag one test message and remove it
  again?
- **Transcript content pull**: needs a tenant where
  add-transcript-scopes.sh ran and the kill-switch is on; then
  `ckm365 refresh <profile>` and `export_transcript`.
- **2tcqc0 part 3**: read-only credentials for unattended audits
  (tenant work).

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

- A spec's mock must compare `request.url.path` DECODED and with the
  `/v1.0` prefix (match on a suffix). An exact encoded path cost one
  round this session; Codex reported it correctly.
- Run a throwaway prototype of a pure transform against its spec before
  queuing the card: two spec bugs in one session is the signal.

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
