---
type: "issue"
title: "audit CI mode: severity exit codes, --fail-on, baseline of accepted findings"
created: "2026-11-07T00:00:00Z"
resource: "oif:ckm/k8p3vh"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["audit", "copilot-card"]
---

Implements parts 1 and 2 of 2tcqc0 (`board/issues/backlog/*2tcqc0.md`).
The spec is `tests/test_audit_ci.py` (on main, skipped until
`audit.exit_code` exists). Read it in full first; its module docstring is
the design.

## Deliverable

All in `src/ckm365/audit.py`:

1. `exit_code(sections, fail_on: str = "risk") -> int`: rank OK, INFO
   and SKIP 0, WARN 1, FAIL 2, RISK 3, over rows that are not
   baselined; return the highest rank if it is at or above
   `fail_on`'s rank, else 0. `run()` returns this instead of today's
   RISK-only 1.
2. `load_baseline(path) -> set[tuple[str, str]]`: (level, text) per
   non-blank, non-`#` line, split on the first run of two or more
   spaces. An unreadable file or a malformed line raises ValueError
   whose message contains "baseline" and the path.
3. `apply_baseline(sections, accepted) -> None`: mark each WARN or RISK
   row whose (level, first line of text) is in `accepted`. Keep the
   marking simple and explicit (for example a set of baselined row
   indexes on `Section`); never baseline FAIL.
4. `write_baseline(path, sections) -> None`: a `#` header line (what
   the file is, that it names real accounts so it stays out of public
   repos), then `LEVEL  first-line` for every WARN and RISK row,
   sorted, de-duplicated. Write with mode 0600.
5. Rendering: a baselined row shows `(baselined)` after its first line
   in both `render_text` and `render_md`. `_summary` counts only
   non-baselined RISK/WARN/FAIL and adds `N baselined` when N > 0.
6. CLI (`add_parser`): `--fail-on {warn,fail,risk}` (default risk),
   `--baseline FILE`, `--write-baseline FILE`. In `run()`, load the
   baseline before running any section (so a bad path fails fast), then
   after the sections apply it, write the new baseline when asked, and
   render. A ValueError from the baseline becomes
   `SystemExit(f"ckm365: {exc}")`. Update the module docstring's exit
   code sentence and the help texts.

## Files you may touch

- `src/ckm365/audit.py` only. `tests/test_audit.py` must still pass
  unchanged.

Read only that, `tests/test_audit_ci.py` and `tests/test_audit.py`. Do
not edit any test file. If a test looks wrong, say so in open_questions
and make the rest pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report the before and after counted results; after: all passing, one
fewer module skipped.

## Not in scope

- Part 3 (unattended credentials): tenant work, interactive.
- Running az, pwsh or any live audit.
- docs/access-audit.md, README, CHANGELOG, version, board files. No
  commits.

## Relates to

- 2tcqc0 parts 1-2; CKM-54 (the audit).
