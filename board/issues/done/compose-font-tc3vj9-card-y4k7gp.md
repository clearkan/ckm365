---
type: "issue"
title: "Compose font: style each composed paragraph from the profile's compose_font"
created: "2026-11-07T00:00:00Z"
resource: "oif:ckm/y4k7gp"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["mail", "compose", "copilot-card"]
---

Implements tc3vj9 (`board/issues/backlog/*tc3vj9.md`). The spec is
`tests/test_compose_font.py` (on main, skipped until
`common.style_paragraphs` exists). Read it in full first; its module
docstring is the design. Note the one deliberate change from the issue:
the font is OPT-IN per profile, not on by default.

## Deliverable

1. `src/ckm365/config.py`, `Profile`: `compose_font: str | None = None`
   and `compose_size: str = "11pt"`, after `signature_html`, each with a
   short comment in the style of its neighbours (why opt-in: ckm365
   cannot read the mailbox font without MailboxSettings.Read, and
   mailboxes differ). Validate in `__post_init__`: `compose_font`, when
   not None, must be a str matching `[A-Za-z0-9 ,'-]{1,100}`;
   `compose_size` must match `\d{1,2}(\.\d{1,2})?pt`. ConfigError
   otherwise, naming the profile. Add both keys to `_PROFILE_KEYS`.
2. `src/ckm365/tools/mail/common.py`: `style_paragraphs(html: str, font: str,
   size: str) -> str`, one compiled regex for `<p(\s[^>]*)?>(.*?)</p>`
   (case-insensitive, DOTALL) and a callback. Leave the match alone when
   the content is blank or the tag or content mentions `font-family`
   (case-insensitive). Otherwise wrap the content in
   `<span style="font-size:{size};font-family:{font}">...</span>`, and
   if the tag had no attributes give it `style="margin:0 0 12pt 0"`.
   Keep the tag's own spelling (`<P>` stays `<P>`). Docstring: why per
   paragraph (Outlook does not cascade a wrapper's style).
3. `src/ckm365/tools/mail/drafts.py`: one small helper,
   `_styled(ctx, account, html)`, returning `style_paragraphs(html,
   p.compose_font, p.compose_size)` when the profile has a
   `compose_font`, else `html` unchanged. Apply it to the caller's
   `body_html` (after `unfenced`) in create_reply_draft,
   create_forward_draft, create_draft, revise_draft and
   create_persona_reply. Not to `signature_html`, not in update_draft.
   Add one sentence to each of those five docstrings' existing text, or
   to the module docstring if that reads better, saying the profile's
   compose_font, when set, is applied per paragraph.

## Files you may touch

- `src/ckm365/config.py`, `src/ckm365/tools/mail/common.py`,
  `src/ckm365/tools/mail/drafts.py`.

Read only those plus `tests/test_compose_font.py` and
`tests/test_mail_compose.py`. Do not edit any test file; existing tests
must pass unchanged. If a test looks wrong, say so in open_questions and
make the rest pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Report the before and after counted results; after: all passing, one
fewer module skipped.

## Not in scope

- `<li>`, `<div>` or bare-text bodies; reading the mailbox font from
  Graph; changing any real profile.
- Any live check, `CKM365_LIVE_*`, anything under `~/.config/ckm365`.
- README, docs, CHANGELOG, version bump, board files. No commits.

## Relates to

- tc3vj9: the issue. Rendering is verified by a human in Outlook after
  merge (the issue's verification steps).
