---
type: "issue"
title: "doctor --mcp: check the MCP registration's env and presets"
created: "2026-11-07T00:00:00Z"
resource: "oif:ckm/f8j3zt"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["admin", "dx", "copilot-card"]
---

Implements ba1m7k item 3 (`board/issues/backlog/*ba1m7k.md`) and GAP 1
of kw20z6 (CKM-44). The spec is `tests/test_doctor_mcp.py` (on main,
skipped until `admin.mcp_registrations` exists). Read it in full first;
its module docstring is the design.

## Deliverable

In `src/ckm365/admin.py`:

1. `mcp_registrations() -> list[tuple[str, dict]]`, public: every
   `ckm365` entry, labelled `"user"` (top-level `mcpServers` of
   `.claude.json`), `"project"` (each `projects.*.mcpServers`, in file
   order) or `".mcp.json"` (`Path.cwd() / ".mcp.json"`), in that order.
   `.claude.json` is in `$CLAUDE_CONFIG_DIR` when set, else
   `Path.home()`. A missing or unreadable file (OSError, ValueError
   from json) contributes nothing; an entry that is not a dict is
   skipped.
2. `doctor --mcp` (a `store_true` on the doctor parser; extend its help
   in one phrase). After the existing per-profile checks and before the
   summary line, when the flag is set:
   - no registration: one WARN line containing
     `no ckm365 MCP registration` and saying this is fine for
     programmatic use.
   - for each registration: a header `doctor: MCP registration (<label>)`,
     then for each `client_credential` profile among the checked ones,
     ok when the entry's `env` keys include `_env("CLIENT_SECRET")` or
     both `_env("CLIENT_CERT_PATH")` and `_env("CLIENT_CERT_THUMBPRINT")`
     (use `Profile._env`); otherwise WARN `credential for <profile> not
     declared on the registration` with advice naming the variables to
     add with `claude mcp add -e`. Then presets: read `--preset X` or
     `--preset=X` from `args` (absent means `all`), expand `all` to
     `ALL_PRESETS` from `ckm365.tools`, and if any of `PRESETS` is
     missing print one note line `presets not enabled: a, b` with the
     advice that meetings and teams need their consent scripts first.
   - Add a third state to `check`'s printer: WARN lines print `warn`
     and do not count as failures. Keep `ok`/`FAIL` as they are.
   - Print names only: never env values, never the registration's
     paths, args or project directories.
3. Without `--mcp`, doctor must not call `mcp_registrations` and its
   output is unchanged.

## Files you may touch

- `src/ckm365/admin.py` only. Do not touch existing tests, including
  `tests/test_admin.py`, which must still pass.

Read only that, `tests/test_doctor_mcp.py`, `tests/test_admin.py`
(doctor section), `src/ckm365/config.py` (`Profile._env`,
`client_credential`) and `src/ckm365/tools/__init__.py` (`PRESETS`,
`ALL_PRESETS`). If a test looks wrong, say so in open_questions and make
the rest pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report the before and after counted results; after: all passing, one
fewer module skipped.

## Not in scope

- Editing `.claude.json` or any registration; it is read only.
- Checking the env Claude Code itself was launched with.
- ba1m7k's other items, GAP 3 (token refresh), README/docs/CHANGELOG,
  version bump, board files. No commits. Never read the real
  `~/.claude.json`; the spec fakes HOME.

## Relates to

- ba1m7k item 3; kw20z6 GAP 1.
