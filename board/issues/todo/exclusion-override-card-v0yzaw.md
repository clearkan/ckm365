---
type: "issue"
title: "send_draft exclusion override needs the profile's allow_exclusion_override; log at WARNING"
created: "2026-11-10T00:00:00Z"
resource: "oif:ckm/v0yzaw"
kind: "bug"
priority: "high"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["security", "send", "copilot-card"]
---

Security fix from the 7 Nov review, approved by seanwy on 10 Nov. The
spec is `tests/test_exclusion_override.py` (skipped until `Profile` has
`allow_exclusion_override`). Read it in full first; its module docstring
is the design.

## Deliverable

1. `src/ckm365/config.py`: `allow_exclusion_override: bool = False` on
   `Profile`, validated as a TOML boolean like `allow_send` (ConfigError
   naming the key), and added to `_PROFILE_KEYS`.
2. `src/ckm365/tools/mail/drafts.py` `send_draft`: when there are
   exclude matches and `override_exclusions=True` but the profile does
   not allow it, raise ValueError naming `allow_exclusion_override` and
   listing the excluded addresses; nothing is sent. When it is allowed
   and used, log one WARNING (`tool=send_draft OVERRIDE mailbox=%r
   message_id=%r overridden=%d`) before the send; keep the existing INFO
   line. Update the docstring: the override is the operator's, set in
   profiles.toml.
3. `profiles.example.toml`: document the key next to
   `exclusions_file`, two comment lines.
4. `tests/test_mail_exclusions.py`: `test_send_override_sends_and_says_what_it_overrode`
   now needs the profile key. Give that file's `_ctx` a way to pass it
   and set it in that one test; change nothing else there.

## Files you may touch

- `src/ckm365/config.py`, `src/ckm365/tools/mail/drafts.py`,
  `profiles.example.toml`, `tests/test_mail_exclusions.py` (as above).
  Do not edit `tests/test_exclusion_override.py`.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report the before and after counted results; after: all passing, one
fewer module skipped.

## Not in scope

- Disk roots (card h03k8p). Calendar invites and the exclusion list (a
  low finding, later). CHANGELOG, version, board files. No commits.
