---
name: teams-transcript
description: Join a Microsoft Teams meeting as a participant and capture the live caption stream, then turn it into structured meeting notes in the current (private, client) repo. Use whenever the user pastes a Teams meeting join link, asks to capture/record/transcribe a Teams meeting, asks to "join this meeting and take notes", or asks to turn a finished capture in meetings/ into notes. Also use for "is the capture still running", "stop the capture", or "write up the meeting notes".
---

# Teams Transcript Capture

Captures live captions from a Teams meeting the user is invited to, using a
Playwright-driven Teams web client session under the user's own identity.
No third-party notetaker bot, no external cloud - output lands in the repo
you are currently working in.

Where ckm365's Graph transcript tools work (`get_meeting_transcript`, which
needs the tenant's Graph transcript access switch ON), prefer them. The
official transcript is better than live captions. This skill is for
meetings where they can't work: client tenants without admin, or
transcription not running.

## Layout and conventions

All output goes into the current repo under `meetings/`:

```
meetings/
  2026-08-14-1030-<slug>/
    capture.log      - progress log (tail to monitor)
    capture.pid      - pid of the running capture (removed on exit)
    raw.jsonl        - finalized caption lines as JSON
    transcript.md    - raw running transcript
    notes.md         - structured notes (generated after the meeting)
```

Derive `<slug>` from context (client or meeting topic) or ask. If the user
gives a client/topic name, use it; keep it short and kebab-case.

## Workflow 1: Start a capture

Trigger: user provides a Teams meeting URL (contains `teams.microsoft.com`
or `teams.live.com`).

1. **Check dependencies.** Never install anything from this skill:
   ```bash
   uv run --with playwright python <skill_dir>/scripts/capture.py --check
   ```
   Every `MISSING:` line names the fix command. On a non-zero exit, stop and
   tell the user which dependency is missing and the command that would fix
   it, then wait for their go-ahead. If `uv` cannot fetch Playwright
   (offline, or a blocked index), say that and stop. The user needs network
   or a pre-seeded cache; guessing at a workaround doesn't help.

2. **Check login state.** A missing `~/.teams-capture-profile` is reported
   by `--check` but does not block: anonymous join still works if the
   organiser's lobby allows it. To join as the user, the first run needs a
   desktop or RDP session (run without `xvfb-run`) to sign in once. Later runs reuse the
   profile.

3. **Launch the capture in the background** so the session stays responsive:
   ```bash
   OUT="meetings/$(date +%Y-%m-%d-%H%M)-<slug>"
   nohup xvfb-run -a uv run --with playwright python \
       <skill_dir>/scripts/capture.py "<meeting-url>" --out-dir "$OUT" \
       --who "<user's name>" \
       > /dev/null 2>&1 &
   ```
   The script writes its own PID to `$OUT/capture.pid`. On a machine with a
   live desktop session (DISPLAY set), drop `xvfb-run -a`.

4. **Confirm it is running** after ~15 seconds:
   ```bash
   tail -n 5 "$OUT/capture.log"
   ```
   Look for `STATUS: admitted to meeting` (may take a while if in lobby) and
   `STATUS: captions enabled`. Report status to the user and stop there -
   do not poll continuously. Tell the user to ask for notes when the
   meeting is done.

5. **Consent notice.** Pass `--who "<user's name>"` at launch; the name
   comes from the session, never from this file. Once admitted, the script
   posts in the meeting chat that it has joined on the user's account and
   that the meeting may be processed with AI. Anyone can reply
   `no notes` (change it with `--opt-out-phrase`) to make it post an
   acknowledgement, leave, and delete `raw.jsonl` and `transcript.md`.
   Report these log lines to the user:
   - `STATUS: consent notice posted in meeting chat`: done.
   - `WARNING: could not post consent notice` or `notice typed but not
     seen in chat`: tell the user to announce
     the note-taker themselves. Opt-out via chat won't work then.
   - `STATUS: consent refused in chat`: tell the user someone refused and
     nothing was kept. Do not rejoin that meeting.

## Workflow 2: Monitor or stop

- Status: `tail -n 20 <out-dir>/capture.log` - CAPTION lines (timestamp
  and length only, no content) mean it is flowing; `STATUS: meeting ended` / `STATUS: capture complete` mean done.
- Stop early: `kill $(cat <out-dir>/capture.pid)`. SIGTERM flushes the
  remaining captions before exit.

## Workflow 3: Generate notes

Trigger: meeting has ended (capture.log shows complete), or the user asks
for notes on a capture directory.

1. Read `transcript.md` (fall back to `raw.jsonl` if needed).
2. Write `notes.md` in the same directory with this structure:

   ```markdown
   # Meeting notes - <topic> - <date>

   ## Attendees
   (speakers observed in the transcript; note that caption speaker names
   may be missing for anonymous joins - mark unknowns)

   ## Summary
   (3-8 bullet points of what was discussed)

   ## Decisions
   (explicit decisions made; "none recorded" if none)

   ## Actions
   (who / what / when, as a markdown table; flag items owned by the user)

   ## Open questions / follow-ups

   ## Notable quotes or details
   (only if genuinely useful - numbers, commitments, technical specifics)
   ```

3. Caption text is lossy: fix obvious speech-to-text errors silently when
   the correction is unambiguous, but never invent content. If a passage is
   garbled, say so in the notes rather than guessing.
4. Offer to commit: `git add meetings/<dir> && git commit` with a message
   like `meeting: <topic> <date> - transcript and notes`. Ask before
   committing if the repo has uncommitted unrelated changes. **Never commit
   meeting output to a public repo**: it's other people's words. Check the
   remote's visibility first. If it's public or you're unsure, add
   `meetings/` to `.gitignore` and leave the output uncommitted.

## Troubleshooting

- **Stuck at "join requested"**: still in lobby, or selectors changed. If
  capture.log shows repeated "Not found (skipping)" for join controls, the
  Teams web client DOM has changed - update the SELECTORS dict at the top
  of `scripts/capture.py` (all selectors are centralized there). Inspect
  by running it on a desktop session without `xvfb-run`, so the browser
  window is visible.
- **No CAPTION lines after admission**: captions may not be enabled -
  the script tries to enable them, but if the menu selectors drifted, the
  user can enable captions manually in their own client; the capture
  session needs them on in ITS window, so fix selectors if this recurs.
- **Login loop headlessly**: seed `~/.teams-capture-profile` with one
  interactive login (RDP into the box and run without `xvfb-run`).
- **Anonymous join blocked**: organizer's lobby policy; user must be
  signed in (see above) or admitted manually by the organizer.
