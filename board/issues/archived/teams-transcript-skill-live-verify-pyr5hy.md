---
type: "issue"
title: "teams-transcript skill — live-verify the caption-capture path"
created: "2026-09-21T00:00:00Z"
resource: "oif:ckm/pyr5hy"
aliases: ["CKM-52"]
kind: "feature"
priority: "medium"
requested_by: "human:seanwy"
tags: ["meetings", "teams", "skill", "client-tenant"]
---

Project skill at `.claude/skills/teams-transcript/`, imported from a
standalone `.skill` bundle built outside this repo. It joins a Teams
meeting through a Playwright-driven web client, captures the live captions
under `meetings/` (git-ignored here because the repo is public), then
writes notes. It complements the Graph transcript tools (e3b7nr, CKM-30).
It needs no tenant transcript switch and no admin, which makes it the path
for client tenants.

Dependencies stay outside ckm365. Playwright runs through
`uv run --with playwright` (ephemeral, like oifmd), plus a Chromium build and
xvfb on headless boxes. `capture.py --check` reports each missing piece
and installs nothing (seanwy, 2026-09-21: if deps are missing or can't be
fetched, say so).

Consent (seanwy, 2026-09-21): once admitted, it posts in the meeting chat
that it has joined on the user's account and that the meeting may be
processed with AI. A reply containing the opt-out phrase (default
"no notes") makes it acknowledge, leave, and delete the captured captions.

To verify live:
- [ ] `--check` clean on a box, with the Chromium build installed on the user's OK
- [ ] signed-in profile seeded by one run on a desktop session (no xvfb-run)
- [ ] join, admission, captions enabled, CAPTION lines flowing
- [ ] chat selectors (UNVERIFIED): notice posts; opt-out leaves and discards
- [ ] SIGTERM via `capture.pid` flushes and exits cleanly
- [ ] meeting-ended detection, then notes generated
