---
type: "issue"
title: "Promote the Message-ID helpers in export.py to shared names"
created: "2026-10-26T09:20:00Z"
resource: "oif:ckm/h59xfz"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["mail", "export", "copilot-card"]
---

A second module (the correspondence migration helper, mr31re) needs the
three Message-ID helpers that `export_message`'s dedupe scan uses. The
repo's rule for `tools/mail/` (AGENTS.md, section "Map of the code") is
that a helper shared inside the package drops its leading underscore;
anything still underscored is private to its module.

## Scope: one rename, one test

In `src/ckm365/tools/mail/export.py` (365 lines), lines 194-247 hold the
dedupe helpers. Rename three module-level functions and every use of them
inside that file:

| now | becomes |
|---|---|
| `_id_key` | `id_key` |
| `_front_matter_id` | `front_matter_id` |
| `_eml_id` | `eml_id` |

`_already_exported` and `_MAX_FRONT_MATTER` STAY private (unchanged).
Change nothing else in the file: no docstring edits beyond the names, no
behaviour change.

Add this test at the END of `tests/test_mail_export.py` (371 lines), run
it RED first, then make it pass:

```python
# --- shared helpers (mr31re) ------------------------------------------------

def test_message_id_helpers_are_shared_names(tmp_path):
    """The migration helper imports these; the names are public inside
    the package (AGENTS.md: shared helpers in tools/mail drop the
    underscore)."""
    from ckm365.tools.mail.export import eml_id, front_matter_id, id_key
    assert id_key(" <a@b.example> ") == "a@b.example"
    record = tmp_path / "r.md"
    record.write_text('---\ninternet_message_id: "<a@b.example>"\n---\nbody\n')
    assert front_matter_id(record) == "<a@b.example>"
    raw = tmp_path / "r.eml"
    raw.write_bytes(b"Message-ID: <a@b.example>\r\nSubject: x\r\n\r\nbody\r\n")
    assert eml_id(raw) == "<a@b.example>"
```

## Files you may touch

- `src/ckm365/tools/mail/export.py`
- `tests/test_mail_export.py`

Read only those two, and only the regions named: export.py lines 194-247,
and the last 20 lines of the test file to see where the new test goes.
Nothing in `src/` or `tests/` outside export.py references the old names
(checked with rg before the card was written), so no other file changes.

## Gate

The offline suite, with no network (the sandbox has none; the uv cache
already holds every wheel):

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Expected: `189 passed, 15 skipped`. It was `188 passed, 15 skipped`
before this card. Report the counted result. If `uv run --offline` cannot
create the worktree's `.venv` inside the sandbox, do not work around it:
put the exact error in `not_run` and stop.

## Relates to

- mr31re (doing): the migration helper this unblocks.

## Not in scope

- Any live check, any `CKM365_LIVE_*` variable, anything that touches
  `~/.config/ckm365`. Never run those.
- Version bump, CHANGELOG, docs, board files.
- The migration helper itself (mr31re), which Claude is designing.
- Commits: leave the working tree changed; the dispatcher commits.
