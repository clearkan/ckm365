#!/usr/bin/env python3
"""
capture.py - Join a Microsoft Teams meeting via the web client and capture
the live caption stream to disk.

Part of the teams-transcript Claude Code skill.

Outputs (in --out-dir):
    raw.jsonl        - one JSON object per finalized caption line
    transcript.md    - human-readable running transcript
    capture.log      - status/progress log (tail this to monitor)

Typical invocation (Claude Code runs this in the background):
    xvfb-run -a python capture.py "<meeting-url>" --out-dir meetings/2026-08-14-acme
    # or, on a machine with a desktop session:
    python capture.py "<meeting-url>" --out-dir meetings/2026-08-14-acme

Dependencies are NOT installed by this script or the skill. Check them with:
    uv run --with playwright python capture.py --check
which reports each missing piece (Playwright package, Chromium build,
display or xvfb, signed-in profile) and exits non-zero.

First run opens a login flow; sign in to Teams once and the persistent
profile at ~/.teams-capture-profile keeps you signed in afterwards.
If you cannot sign in headlessly, run once interactively (or via RDP)
to seed the profile, then background runs will reuse it.
"""

import argparse
import datetime
import json
import pathlib
import sys
import time

import os
import shutil
import signal

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:  # reported by --check / main(), not a traceback
    sync_playwright = None
    PWTimeout = TimeoutError

# ---------------------------------------------------------------------------
# Selectors - Teams web client moves these around occasionally.
# Update here when capture stops finding elements (check capture.log).
# ---------------------------------------------------------------------------

SELECTORS = {
    "continue_on_browser": 'button[data-tid="joinOnWeb"]',
    "prejoin_name_input": 'input[data-tid="prejoin-display-name-input"]',
    "mic_toggle": 'div[data-tid="toggle-mute"]',
    "camera_toggle": 'div[data-tid="toggle-video"]',
    "join_button": 'button[data-tid="prejoin-join-button"]',
    "more_button": 'button[id="callingButtons-showMoreBtn"]',
    "language_speech_menu": 'div[id="LanguageSpeechMenuControl-id"]',
    "captions_menuitem": 'div[id="closed-captions-button"]',
    "caption_containers": [
        '[data-tid="closed-captions-renderer"]',
        '[data-tid="closed-caption-v2-window-wrapper"]',
    ],
    "caption_author": '[data-tid="author"]',
    "caption_text": '[data-tid="closed-caption-text"]',
    "hangup_button": 'button[data-tid="hangup-main-btn"]',
    # Meeting chat - UNVERIFIED against the live client; fix here if the
    # consent notice logs "could not post".
    "chat_button": 'button[id="chat-button"]',
    "chat_compose": 'div[data-tid="ckeditor"]',
    "chat_messages": '[data-tid="chat-pane-message"]',
}

OPT_OUT_PHRASE = "no notes"
NOTICE = ("Note-taking assistant here, joined on {who}'s account. "
          "This meeting may be transcribed and processed with AI. "
          "If you do not consent, reply \"{phrase}\" in this chat and it "
          "will leave and discard what it captured.")
NOTICE_MARK = "processed with AI"   # tells our own notice apart from an opt-out

PROFILE_DIR = pathlib.Path.home() / ".teams-capture-profile"
POLL_INTERVAL_SECS = 2.0
FINALIZE_MS = 4000  # caption unchanged for this long -> treat as final

OBSERVER_JS = """
(sel) => {
    if (window.__captionObserverInstalled) return true;
    window.__capturedCaptions = [];
    window.__pending = new Map();

    const snapshotEntry = (el, sel) => {
        const authorEl = el.querySelector(sel.caption_author);
        const textEl = el.querySelector(sel.caption_text) || el;
        return {
            author: authorEl ? authorEl.innerText.trim() : "",
            text: textEl.innerText.trim(),
        };
    };

    const scan = () => {
        const containers = [];
        for (const c of sel.caption_containers) {
            document.querySelectorAll(c).forEach(x => containers.push(x));
        }
        const now = Date.now();
        for (const container of containers) {
            const chunks = container.querySelectorAll(sel.caption_text);
            chunks.forEach(textEl => {
                const chunkRoot = textEl.closest("div") || textEl;
                const entry = snapshotEntry(chunkRoot.parentElement || chunkRoot, sel);
                if (!entry.text) return;
                const key = chunkRoot;
                const prev = window.__pending.get(key);
                if (!prev || prev.text !== entry.text) {
                    window.__pending.set(key, {...entry, lastChange: now});
                }
            });
        }
        for (const [el, val] of window.__pending) {
            const detached = !document.contains(el);
            if (detached || (now - val.lastChange) > sel.finalize_ms) {
                const caps = window.__capturedCaptions;
                const last = caps[caps.length - 1];
                if (!last || !(last.author === val.author &&
                               (last.text === val.text || last.text.endsWith(val.text)))) {
                    caps.push({
                        ts: new Date().toISOString(),
                        author: val.author,
                        text: val.text,
                    });
                }
                window.__pending.delete(el);
            }
        }
    };

    setInterval(scan, 1000);
    window.__captionObserverInstalled = true;
    return true;
}
"""

DRAIN_JS = """
() => {
    const out = window.__capturedCaptions || [];
    window.__capturedCaptions = [];
    return out;
}
"""


class Logger:
    def __init__(self, log_path):
        self.f = open(log_path, "a", encoding="utf-8")

    def log(self, msg):
        line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        self.f.write(line + "\n")
        self.f.flush()


def click_if_present(page, selector, logger, timeout_ms=5000, desc=""):
    try:
        page.wait_for_selector(selector, timeout=timeout_ms)
        page.click(selector)
        logger.log(f"Clicked: {desc or selector}")
        return True
    except PWTimeout:
        logger.log(f"Not found (skipping): {desc or selector}")
        return False


def join_meeting(page, meeting_url, display_name, logger):
    logger.log("STATUS: opening meeting link")
    page.goto(meeting_url, wait_until="domcontentloaded")

    click_if_present(page, SELECTORS["continue_on_browser"], logger,
                     timeout_ms=15000, desc="Continue on this browser")

    page.wait_for_selector(SELECTORS["join_button"], timeout=60000)
    try:
        name_input = page.query_selector(SELECTORS["prejoin_name_input"])
        if name_input and display_name:
            name_input.fill(display_name)
            logger.log(f"Set display name: {display_name}")
    except Exception:
        pass

    click_if_present(page, SELECTORS["mic_toggle"], logger, timeout_ms=3000, desc="Mute mic")
    click_if_present(page, SELECTORS["camera_toggle"], logger, timeout_ms=3000, desc="Camera off")

    page.click(SELECTORS["join_button"])
    logger.log("STATUS: join requested, waiting for admission (lobby may apply)")

    page.wait_for_selector(SELECTORS["more_button"], timeout=600000)
    logger.log("STATUS: admitted to meeting")


def enable_captions(page, logger):
    logger.log("Enabling live captions...")
    try:
        page.click(SELECTORS["more_button"])
        page.wait_for_selector(SELECTORS["language_speech_menu"], timeout=5000)
        page.click(SELECTORS["language_speech_menu"])
        page.wait_for_selector(SELECTORS["captions_menuitem"], timeout=5000)
        page.click(SELECTORS["captions_menuitem"])
        logger.log("STATUS: captions enabled")
        return True
    except PWTimeout:
        logger.log("WARNING: could not enable captions via menu; "
                   "capture continues and will pick up captions if enabled another way")
        return False


def post_notice(page, notice, logger):
    """Announce the capture in the meeting chat. Returns the chat message
    count at posting time (opt-outs are looked for after it), or None when
    the notice could not be posted."""
    try:
        page.click(SELECTORS["chat_button"], timeout=10000)
        page.wait_for_selector(SELECTORS["chat_compose"], timeout=10000)
        page.click(SELECTORS["chat_compose"])
        page.keyboard.type(notice)
        page.keyboard.press("Enter")
        time.sleep(2)
        msgs = page.query_selector_all(SELECTORS["chat_messages"])
        if not any(NOTICE_MARK in (m.inner_text() or "") for m in msgs):
            logger.log("WARNING: notice typed but not seen in chat - "
                       "opt-out monitoring inactive; announce the note-taker verbally")
            return None
        logger.log("STATUS: consent notice posted in meeting chat")
        return len(msgs) - 1
    except Exception:
        logger.log("WARNING: could not post consent notice in chat - "
                   "announce the note-taker verbally")
        return None


def opted_out(page, seen, phrase, notice):
    """True if any chat message after index `seen` contains the phrase,
    ignoring a quoted copy of our own notice (a Teams Reply quotes it)."""
    for el in page.query_selector_all(SELECTORS["chat_messages"])[seen + 1:]:
        text = (el.inner_text() or "").lower().replace(notice.lower(), "")
        if phrase in text:
            return True
    return False


def leave_and_discard(page, out_dir, logger):
    try:
        page.click(SELECTORS["chat_compose"])
        page.keyboard.type("Understood - leaving now; nothing captured is kept.")
        page.keyboard.press("Enter")
        time.sleep(1)
    except Exception:  # best effort; leaving matters more
        pass
    click_if_present(page, SELECTORS["hangup_button"], logger, desc="Leave")
    for name in ("raw.jsonl", "transcript.md"):
        (out_dir / name).unlink(missing_ok=True)
    logger.log("STATUS: consent refused in chat - left meeting, capture discarded")


def capture_loop(page, out_dir, logger, notice_at, phrase, notice):
    page.evaluate(OBSERVER_JS, {
        "caption_containers": SELECTORS["caption_containers"],
        "caption_author": SELECTORS["caption_author"],
        "caption_text": SELECTORS["caption_text"],
        "finalize_ms": FINALIZE_MS,
    })
    raw_path = out_dir / "raw.jsonl"
    md_path = out_dir / "transcript.md"
    logger.log(f"STATUS: capturing to {md_path}")

    with open(raw_path, "a", encoding="utf-8") as raw_f, \
         open(md_path, "a", encoding="utf-8") as md_f:
        md_f.write(f"\n# Teams meeting transcript - "
                   f"{datetime.datetime.now().isoformat(timespec='seconds')}\n\n")
        md_f.flush()
        refused = False
        try:
            while True:
                time.sleep(POLL_INTERVAL_SECS)
                try:
                    if notice_at is not None and opted_out(page, notice_at, phrase, notice):
                        refused = True
                        break
                    if page.query_selector(SELECTORS["hangup_button"]) is None:
                        logger.log("STATUS: meeting ended")
                        write_entries(page.evaluate(DRAIN_JS), raw_f, md_f, logger)
                        break
                    write_entries(page.evaluate(DRAIN_JS), raw_f, md_f, logger)
                except KeyboardInterrupt:
                    raise
                except Exception as e:  # detached node, navigation at meeting end
                    logger.log(f"WARNING: {type(e).__name__} during poll - continuing")
                    if page.is_closed():
                        logger.log("STATUS: meeting ended")
                        break
        except KeyboardInterrupt:
            logger.log("Interrupted - flushing remaining captions")
            try:
                write_entries(page.evaluate(DRAIN_JS), raw_f, md_f, logger)
            except Exception:
                pass
    if refused:
        leave_and_discard(page, out_dir, logger)
        return
    logger.log("STATUS: capture complete")


def write_entries(entries, raw_f, md_f, logger):
    for e in entries:
        raw_f.write(json.dumps(e, ensure_ascii=True) + "\n")
        ts = e.get("ts", "")[11:19]
        author = e.get("author") or "Unknown"
        text = e.get("text", "")
        md_f.write(f"**[{ts}] {author}:** {text}\n\n")
        logger.log(f"CAPTION {ts} ({len(text)} chars)")  # no content in the log
    raw_f.flush()
    md_f.flush()


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def check_deps(verbose):
    """True when capture can run. Installs nothing: a missing piece is
    reported with the command that would fix it, for the user to approve."""
    problems = []
    if sync_playwright is None:
        problems.append("Playwright package not importable - run via "
                        "`uv run --with playwright` (needs network on first use)")
    else:
        try:
            with sync_playwright() as pw:
                exe = pw.chromium.executable_path
            if not pathlib.Path(exe).exists():
                problems.append(f"Chromium build missing ({exe}) - "
                                "`uv run --with playwright playwright install chromium`")
        except Exception as e:
            problems.append(f"Playwright cannot locate Chromium ({type(e).__name__}) - "
                            "`uv run --with playwright playwright install chromium`")
    if not os.environ.get("DISPLAY") and not shutil.which("xvfb-run"):
        problems.append("No DISPLAY and no xvfb-run - install xvfb (needs sudo)")
    if not PROFILE_DIR.exists():
        problems.append(f"No signed-in profile at {PROFILE_DIR} - first run must be "
                        "on a desktop session (no xvfb-run) to sign in once "
                        "(anonymous join may still work if the lobby allows it)")
    if verbose:
        for p in problems:
            print(f"MISSING: {p}")
        print("OK: all dependencies present" if not problems else
              f"{len(problems)} problem(s)")
    # A missing profile alone does not block (anonymous join).
    return all(p.startswith("No signed-in profile") for p in problems)


def main():
    ap = argparse.ArgumentParser(description="Capture live captions from a Teams meeting")
    ap.add_argument("meeting_url", nargs="?", help="Teams meeting join link")
    ap.add_argument("--out-dir", default=None,
                    help="Output directory (default: meetings/YYYY-MM-DD-HHMM)")
    ap.add_argument("--name", default="Notes",
                    help="Display name if joining anonymously")
    ap.add_argument("--who", default="the organiser's invitee",
                    help="Whose account this is, for the chat consent notice")
    ap.add_argument("--opt-out-phrase", default=OPT_OUT_PHRASE,
                    help="Chat phrase that makes the capture leave and discard")
    ap.add_argument("--check", action="store_true",
                    help="Report missing dependencies and exit (no meeting joined)")
    args = ap.parse_args()

    if args.check:
        return 0 if check_deps(verbose=True) else 1
    if not args.meeting_url:
        ap.error("meeting_url is required unless --check")
    if not check_deps(verbose=False):
        print("Dependencies missing - run with --check for details", file=sys.stderr)
        return 1

    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    out_dir = pathlib.Path(args.out_dir or f"meetings/{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = Logger(out_dir / "capture.log")
    # Own pid, not the xvfb-run wrapper's, so `kill` reaches this process;
    # SIGTERM takes the same flush path as Ctrl-C.
    (out_dir / "capture.pid").write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, _raise_interrupt)

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,  # run under xvfb-run on headless boxes
            args=[
                "--use-fake-ui-for-media-stream",
                "--disable-blink-features=AutomationControlled",
            ],
            permissions=["microphone", "camera"],
            viewport={"width": 1600, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        phrase = args.opt_out_phrase.lower()
        notice = NOTICE.format(who=args.who, phrase=phrase)
        try:
            join_meeting(page, args.meeting_url, args.name, logger)
            notice_at = post_notice(page, notice, logger)
            enable_captions(page, logger)
            capture_loop(page, out_dir, logger, notice_at, phrase, notice)
        except KeyboardInterrupt:  # stopped in the lobby/setup: nothing captured yet
            logger.log("STATUS: stopped before capture")
        finally:
            logger.log("Closing browser")
            context.close()
            (out_dir / "capture.pid").unlink(missing_ok=True)

    logger.log(f"Done. Output in {out_dir}")


if __name__ == "__main__":
    sys.exit(main())
