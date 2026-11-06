---
type: "issue"
title: "ckm365 refresh: drop cached access tokens so new consent applies without re-login"
created: "2026-11-07T00:00:00Z"
resource: "oif:ckm/m9d4wx"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["auth", "dx", "copilot-card"]
---

Implements GAP 3 of kw20z6 (CKM-44,
`board/issues/backlog/surfacing-gaps-export-transcript-the-meetings-kw20z6.md`).
The spec is `tests/test_auth_refresh.py` (on main, skipped until
`Auth.drop_access_tokens` exists). Read it in full first; its module
docstring is the design.

## Deliverable

1. `src/ckm365/auth.py`, on `Auth`, after `logout`:

       def drop_access_tokens(self) -> int

   No cache file: raise `NeedsLogin` naming `ckm365 login <profile>`.
   Otherwise, inside `with self._lock():`, `_reload()`, then remove the
   cache's access tokens and persist through the existing `_persist()`
   (it already writes atomically with 0600). The simplest route is the
   serialized form: `data = json.loads(self._cache.serialize())`, count
   and empty `data["AccessToken"]`, `self._cache.deserialize(json.dumps(data))`;
   check that `_persist()` then actually writes (MSAL's
   `has_state_changed`; set it if deserialize clears it) and that the
   other sections come back byte-for-byte equal in value. Return the
   count. Log one line: profile and count. Docstring: why (a pre-consent
   access token keeps 403ing until it expires; the refresh token mints a
   new one with the new scopes), and that nothing contacts the network.
2. `src/ckm365/server.py`: a `refresh` subcommand beside `login` and
   `logout` (same optional `profile` argument, help "drop cached access
   tokens so newly granted consent applies without a re-login"). On
   success print to stderr `refreshed <profile>: dropped N cached access
   token(s); the next call mints a fresh one`. `NeedsLogin` already
   becomes a `SystemExit` message in that try block; keep it that way.
3. One line in the module docstring of `auth.py` or near `logout`,
   whichever is the natural home, pointing at `refresh`.

## Files you may touch

- `src/ckm365/auth.py`, `src/ckm365/server.py`.

Read only those plus `tests/test_auth_refresh.py` and the existing
login/logout tests (`grep -n logout tests/*.py`). Do not edit any test
file. If a test looks wrong, say so in open_questions and make the rest
pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report the before and after counted results; after: all passing, one
fewer module skipped.

## Not in scope

- Touching any real cache under `~/.local/state`, any live login, any
  tenant or consent change. The spec uses fabricated caches only.
- README, docs, CHANGELOG, version bump, board files. No commits.

## Relates to

- kw20z6 GAP 3.
