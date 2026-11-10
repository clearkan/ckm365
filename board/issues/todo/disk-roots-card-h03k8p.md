---
type: "issue"
title: "Disk roots always on: default root, attach and download confinement, always-deny list"
created: "2026-11-10T00:00:00Z"
resource: "oif:ckm/h03k8p"
aliases: ["CKM-j30wca"]
kind: "bug"
priority: "high"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["security", "disk", "copilot-card"]
---

Security fix from the 7 Nov review, approved by seanwy on 10 Nov
(covers board items CKM-j30wca and CKM-h03k8p). The spec is
`tests/test_disk_roots.py` (skipped until `disk.default_root` exists).
Read it in full first; its module docstring is the design.
`tests/conftest.py` already points both roots at pytest's base temp dir.

## Deliverable

1. `src/ckm365/tools/mail/disk.py`: `default_root()`,
   `download_root()`, `attach_root()` and `confine(path, what,
   root=None)` exactly as the spec's docstring says. Resolve the path
   with `.expanduser().resolve()` (symlinks followed) and compare
   against the resolved root. The always-deny checks: inside
   `config.state_dir()`; equal to `config.profiles_path()` or inside its
   parent directory; any component of the path relative to the root that
   starts with ".". Each refusal is a ValueError whose message says which
   rule refused it (the words "state", "profiles", "hidden" or "outside
   the ... root", plus the env var to set for the outside case). Update
   the module docstring: confinement is always on.
2. `src/ckm365/tools/mail/attachments.py` `add_attachment`: replace the
   inline CKM365_ATTACH_ROOT check with
   `disk.confine(Path(file_path), "attachment", root=disk.attach_root())`.
   The outside-root message must still contain "CKM365_ATTACH_ROOT".
3. Docstrings that say "if CKM365_DOWNLOAD_ROOT ... is set" (attachments,
   export, bulk, meetings, migrate) now say the root defaults to
   `~/.local/share/ckm365` (or `$XDG_DATA_HOME/ckm365`). One line each.
4. `README.md`: in the existing section that documents
   CKM365_ATTACH_ROOT / CKM365_DOWNLOAD_ROOT, state the new default and
   the always-denied paths in at most six lines.

## Files you may touch

- `src/ckm365/tools/mail/disk.py`, `attachments.py`, `export.py`,
  `bulk.py`, `migrate.py`, `src/ckm365/tools/meetings.py` (docstrings
  only outside disk.py and attachments.py), `README.md`.
- Existing tests that relied on "no root means unconfined" may be
  adjusted to set a root; say which in your report. Do not edit
  `tests/test_disk_roots.py` or `tests/conftest.py`. If a spec test
  looks wrong, say so in open_questions and make the rest pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report the before and after counted results; after: all passing, one
fewer module skipped.

## Not in scope

- The exclusion override (card v0yzaw). CHANGELOG, version, board
  files. No commits.
