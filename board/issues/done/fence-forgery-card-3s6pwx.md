---
type: "issue"
title: "Compose fence: honour only a fence above the quoted history; always write the body fence"
created: "2026-11-10T00:00:00Z"
resource: "oif:ckm/3s6pwx"
kind: "bug"
priority: "high"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["security", "compose", "copilot-card"]
---

Security fix from the 7 Nov review, approved by seanwy on 10 Nov. The spec
is `tests/test_fence_forgery.py` (skipped until `common.QUOTE_MARKS`
exists). Read it in full first; its module docstring is the design.

## Deliverable

1. `src/ckm365/tools/mail/common.py`: add `QUOTE_MARKS`, the tuple
   verify.py has as `_QUOTE_MARKS` today (lower-case needles, matched
   against the lower-cased body). Change `fenced_region(content, mark)`
   so a fence counts only when its opener AND its closer both come
   before the first quote marker (search the lower-cased content for
   the first of `QUOTE_MARKS`; none found means no limit). Take the
   first opener before that limit, then the first closer after it, and
   return None if that closer is past the limit. Update the comment
   block above the fence helpers in two sentences: the quoted history is
   sender-controlled, so a fence below the quote is not ours.
2. `src/ckm365/tools/mail/drafts.py`: `_composed` always emits the body
   fence (`fence(BODY_MARK, "")` for an empty body); the signature fence
   stays conditional. `_insert_top` therefore always PATCHes. Update the
   create_reply_draft / create_forward_draft docstrings in one line each
   if they say otherwise.
3. `src/ckm365/tools/mail/verify.py`: use `common.QUOTE_MARKS` (delete
   the local tuple, or alias it to the same object). The signature
   detection (`fence_open(SIGNATURE_MARK)` lookups in `_new_region` and
   in the result's `signature` flag) must ignore a signature fence that
   sits at or after the first quote marker, the same rule as (1). One
   small helper in common.py used by both is fine.

## Files you may touch

- `src/ckm365/tools/mail/common.py`, `drafts.py`, `verify.py`.
- Existing tests that pinned "an empty body writes no fence" may be
  updated to expect the empty fence; say which in your report. Do not
  edit `tests/test_fence_forgery.py`. If a spec test looks wrong, say so
  in open_questions and make the rest pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report the before and after counted results; after: all passing, one
fewer module skipped.

## Not in scope

- The other security items (attach and download roots, the exclusion
  override): separate cards for v2.14.0.
- update_draft's missing `unfenced()` check (a low finding, later).
- README, CHANGELOG, version, board files. No commits.
