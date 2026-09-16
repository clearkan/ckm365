---
type: "issue"
title: "Surfacing gaps — export_transcript, the meetings preset, and inline images lost by export_message"
created: "2026-08-29T01:35:00Z"
resource: "oif:ckm/kw20z6"
aliases: ["CKM-44"]
kind: "feature"
priority: "high"
requested_by: "human:seanwy"
tags: ["teams", "meetings", "graph", "dx", "mail", "attachments"]
depends_on: ["e3b7nr"]
depends_on_aliases: ["CKM-30"]
---

Filed per docs/graph-direct.md rule 5, from the first END-TO-END live
transcript pull (CKM-30 run of 2026-08-29, second tenant): the meeting
resolved, the transcript downloaded, and every step worked — but none of
it was reachable through the MCP server the session actually had, so the
whole flow ran as a tmp/ scratch script. Three gaps, one finding to
encode, one open question.

GAP 1 — the meetings preset was not on the session's serve line. The
agent had mail/calendar tools but tools/meetings.py was invisible; it
found the module only by reading the repo. Either add meetings to the
recommended serve preset alongside mail,calendar once a tenant is
consented, or surface "module exists, preset not enabled" in doctor so
the gap is diagnosable from the tool side.

GAP 2 — export_transcript. The scratch script is the tool shape:
event join_url -> find_meeting_id -> newest transcript -> content to a
FILE on disk (VTT or text), content never through agent context, an OKF
.md variant like export_message's, CKM365_DOWNLOAD_ROOT confinement,
never overwrite. One tool call replaces the whole script.

GAP 3 — a consent-refresh helper. After add-transcript-scopes.sh, a
still-valid pre-consent ACCESS token keeps 403ing (CORRECTION to the
2026-08-01 "no re-login needed" finding — that held only because the AT
happened to be expired). The fix that avoids interactive re-login is
surgical: drop only the AccessToken section of the profile's MSAL cache
and let the refresh token mint the new scopes. Candidate: a
`ckm365 refresh <profile>` subcommand or doctor --fix, instead of
hand-editing JSON next to the credential cache.

FINDING to encode in docs/usage-modes.md: the Teams kill-switch
(EnableGraphTranscriptAccess) can be flipped fully headless —
MicrosoftTeams pwsh module + Connect-MicrosoftTeams -AccessTokens with
two az-minted tokens (Graph + resource
48ac35b8-9aa8-4d74-927d-1f4a14a0b239) — and PROPAGATION IS ~45-50 MIN:
the API kept returning the kill-switch 403 for 9 five-minute retries
after the setting read back true. Poll with backoff; do not treat the
first post-flip 403 as failure.

ANSWERED from CKM-30's open list: attribution. A transcript RECORDED
while EnableAttributedTranscripts was false came back fully attributed
(<v Name> tags, 3 speakers) once the flag was true at retrieval time —
the flag gates API return, not capture. ALSO VERIFIED: transcript
created ~4 min after meeting start (auto-transcription), retrieved
intact at 61 KB / 261 cues.

OPEN: change-notification subscriptions for transcript availability
(CKM-30's original shape) would replace the polling loop entirely.

GAP 4 (added 2026-08-30, second live hit) — INLINE IMAGES ARE INVISIBLE.
A message arrived whose entire substance was two inline PNGs: slides
returned with the counterparty's comments in red. Three things went
wrong at once:
  (a) has_attachments is FALSE when every image is inline, so nothing
      signals that the message has content beyond its text;
  (b) export_message's OKF record therefore lists no attachments and
      leaves bare "[cid:...]" markers in the body — the record reads as
      complete while missing the point of the message;
  (c) list_attachments DOES return them (is_inline: true) and
      download_attachment fetches them fine — so the data is reachable,
      it just is not surfaced.
Both images were also named "image.png", so name-based download is
ambiguous and attachment_id is mandatory.
FIX SHAPE: export_message should (1) always emit an attachment manifest
including inline parts, (2) rewrite each cid: marker into a reference to
the manifest entry, and (3) when a --with-attachments flag is passed,
write the bytes into a sibling folder with deduplicated names. Callers
can then run their own transcription over the images — the archiving
side just has to stop hiding them.
NOTE for whoever builds it: ckm365 cannot transcribe images and should
not try. The consuming repo now has an image-sidecar script
that takes an agent-supplied transcription; ckm365's job ends at
surfacing the bytes and naming them.
