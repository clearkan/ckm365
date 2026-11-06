---
type: "issue"
title: "Recipient exclusion list: warn on drafts, refuse on send, check_recipients"
created: "2026-11-06T03:00:00Z"
resource: "oif:ckm/v6n4tj"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["mail", "compose", "send", "safety", "copilot-card"]
---

Implements cw81fa (`board/issues/doing/recipient-exclusion-list-warn-on-draft-refuse-on-send-cw81fa.md`).
The spec is `tests/test_mail_exclusions.py` (on main, skipped until
`mail.check_recipients` exists). Read it in full first; its module
docstring is the design, including the file format. Decisions already
made, do not revisit: TOML via stdlib `tomllib` (no YAML, no new
dependency); the per-call file only on `check_recipients`; a configured
file that is missing or invalid raises ValueError (message contains
"exclusion") BEFORE any Graph request.

## Deliverable

1. **New module `src/ckm365/tools/mail/exclusions.py`** (keep it under
   ~120 lines):
   - `load(path: str) -> list[dict]`: `~` expanded, `tomllib`. Top level
     may hold only `entries`, a list of tables. Each entry: `address`
     (required, non-empty str); `action` in {"exclude", "warn"}, default
     "exclude"; optional str `type`, `scope`, `source`, `notes`; optional
     `since`/`until` ISO dates (`date.fromisoformat`). Unknown keys,
     wrong types, a missing file or bad TOML: `ValueError` naming the
     file and saying "exclusion list". An empty file is zero entries.
   - `check(entries, recipients: list[tuple[str, str]], subject: str | None)
     -> list[RecipientWarning]`: `recipients` are (address, field) pairs,
     field in {"to", "cc", "bcc", ""}. Normalise an address with
     `email.utils.parseaddr` then `.strip().lower()`; match entries by
     equal normalised address. Skip an entry whose `until` is before
     today; one whose `scope` is set matches only when `subject` contains
     it case-insensitively (no subject: no match). One warning per
     (recipient, matching entry), in recipient order. The warning's
     `address` is the recipient as normalised.
   - `for_profile(ctx, account) -> list[dict] | None`: the profile's
     `exclusions_file` loaded, or None when unset.
   - `draft_warnings(entries, draft) -> list[RecipientWarning]` from the
     draft's `to`, `cc`, `bcc` and `subject`.
2. **Models** (`src/ckm365/models.py`):
   - `RecipientWarning` dataclass: `address: str`, `field: str = ""`,
     `action: str = "exclude"`, `type: str = ""`, `source: str = ""`.
   - `Draft` stops being an alias: `class Draft(Message)` adding
     `recipient_warnings: list[RecipientWarning] = field(default_factory=list)`.
     `Message.from_graph` already builds `cls(...)`, so
     `Draft.from_graph` returns a Draft. `Message` itself gains nothing.
3. **Config** (`src/ckm365/config.py`): `exclusions_file: str | None = None`
   on `Profile` with a one-line comment, and in `_PROFILE_KEYS`.
4. **Draft tools** (`src/ckm365/tools/mail/drafts.py`): in
   `create_draft`, `create_reply_draft`, `create_forward_draft`,
   `update_draft` and `create_persona_reply`, load the profile's list
   FIRST (before any Graph call), then set `draft.recipient_warnings`
   on the Draft about to be returned. `revise_draft` does not change
   recipients: leave it. Recipients are never removed or altered.
5. **send_draft**: new keyword `override_exclusions: bool = False`.
   Load the list first; widen the guard's select to
   `id,isDraft,subject,toRecipients,ccRecipients,bccRecipients`; any
   `exclude` match and no override: `ValueError` saying the send is
   refused because of the exclusion list and naming each excluded
   address. Count bcc in `recipients` too. The result gains
   `recipient_warnings` (all matches, `[]` when none or no list). Log
   only counts, never addresses.
6. **check_recipients** (read tier), in `exclusions.py`:

       def check_recipients(ctx: Ctx, addresses: list[str], *, subject: str | None = None,
                            exclusions_file: str | None = None,
                            account: str | None = None) -> list[RecipientWarning]

   The per-call file replaces the profile's. No Graph call. Docstring:
   what it is for (test a list before building a draft), the file format
   in five lines, that draft tools warn and send refuses.
7. **Docstrings**: one sentence each on the five draft tools ("the result
   carries recipient_warnings when the profile has an exclusion list")
   and on `send_draft` (refusal and the override). Keep them short.
8. **Register**: export `check_recipients` from `tools/mail/__init__.py`
   (import, `__all__`, a module-docstring line for exclusions.py) and add
   it to `READ["mail"]` in `src/ckm365/tools/__init__.py` after
   `mail.verify_message`. `profiles.example.toml`: one commented-out
   `# exclusions_file = "~/path/to/exclusions.toml"` line in the first
   profile block.

## Preset counts

One new read tool: in `tests/test_offline.py::test_tools_for_presets`,
these six numbers each go up by one: 16, 31, 32 (lines 254-256, `mail`)
and 36, 37, 40 (lines 283, 284, 287). Only those six edits in that file.

## Files you may touch

- `src/ckm365/tools/mail/exclusions.py` (new), `src/ckm365/tools/mail/drafts.py`
- `src/ckm365/models.py`, `src/ckm365/config.py`
- `src/ckm365/tools/mail/__init__.py`, `src/ckm365/tools/__init__.py`
- `profiles.example.toml` (one comment line)
- `tests/test_offline.py`: the six numbers above.

Read only those plus `tests/test_mail_exclusions.py` and
`tests/test_mail_compose.py` lines 1-80. Do not edit any spec or other
test file: if a test looks wrong, say so in open_questions and make the
rest pass. Every existing compose and send test must stay green.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Before: `277 passed, 16 skipped`. Expected after: all passing, `15
skipped`, about 32 more passed. Report the counted result.

## Not in scope

- Suggesting entries from inbound REMOVE replies or bounces (a later step).
- Domain-wide entries, writing the list, any per-call file on draft tools.
- Any live check, `CKM365_LIVE_*`, anything under `~/.config/ckm365`.
- Version bump, CHANGELOG, README, docs, board files. No commits.

## Relates to

- cw81fa (doing): the issue.
