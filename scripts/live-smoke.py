"""Read-only live smoke test against a real mailbox.

Prints counts and truncated ids ONLY — never subjects, bodies, addresses of
correspondents, or tokens — so its output is safe to feed back into an
agent session.

Usage: uv run python scripts/live-smoke.py [profile] [--deny MAILBOX]
                                                     [--shared MAILBOX]
                                                     [--teams]

--deny MAILBOX runs a negative test: listing that mailbox's messages MUST
fail with a Graph 4xx (proves tenant permissions do not leak across users).
--shared MAILBOX runs a positive test: the shared mailbox MUST be readable
via the profile's .Shared delegated scopes (counts printed, nothing else).
--teams exercises the Teams discovery reads (CKM-25): teams, then the
first team's channels and installed apps. Needs the separate Teams
consent tier (scripts/add-teams-scopes.sh); without it Graph returns 403,
which this reports as a skip rather than a failure.
--transcripts walks recent calendar events with a Teams join URL,
resolves each to an online meeting, and reports how many have a
transcript (CKM-30). Needs add-transcript-scopes.sh AND the Teams admin
setting 'Transcript API access -> Microsoft Graph access'. Prints ids and
character counts only — never transcript text.
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta

from ckm365.graph import GraphError
from ckm365.tools import Ctx
from ckm365.tools.calendar import list_events
from ckm365.tools.mail import list_mail_folders, list_messages
from ckm365.tools.meetings import (find_meeting_id,
                                   get_meeting_transcript,
                                   list_meeting_transcripts)
from ckm365.tools.teams import list_channels, list_installed_apps, list_teams

parser = argparse.ArgumentParser()
parser.add_argument("profile", nargs="?", default=None)
parser.add_argument("--deny", metavar="MAILBOX", default=None)
parser.add_argument("--shared", metavar="MAILBOX", default=None)
parser.add_argument("--teams", action="store_true")
parser.add_argument("--transcripts", action="store_true")
parser.add_argument("--days", type=int, default=60,
                    help="how far back --transcripts looks")
args = parser.parse_args()
account = args.profile

ctx = Ctx.create(write=False, account=account)
profile = ctx.profile(account)
_, mailbox = ctx.target(account, None)
print(f"profile={profile.name} mailbox={mailbox}")

folders = list_mail_folders(ctx)
print(f"mail folders: {len(folders)}")

messages = list_messages(ctx, top=5)
print(f"inbox messages fetched: {len(messages)}")
print(f"  ids: {[m.id[:12] + '…' for m in messages]}")

now = datetime.now(UTC)
events = list_events(ctx, start=now.isoformat(),
                     end=(now + timedelta(days=7)).isoformat())
print(f"calendar events next 7 days: {len(events)}")

if args.shared:
    try:
        shared = list_messages(ctx, top=3, mailbox=args.shared)
        print(f"shared-test {args.shared}: readable, "
              f"{len(shared)} message(s) fetched")
    except GraphError as exc:
        sys.exit(f"SHARED-TEST FAILED: {args.shared} not readable "
                 f"(HTTP {exc.status} {exc.code}) — likely missing FullAccess "
                 "for the signed-in user; grant via Exchange Online: "
                 f"Add-MailboxPermission {args.shared} -User <upn> "
                 "-AccessRights FullAccess -AutoMapping $false")

if args.teams:
    try:
        found = list_teams(ctx, top=10)
        print(f"teams visible: {len(found)}")
        if found:
            team = found[0]
            print(f"  first team id: {team.id[:12]}… archived={team.is_archived}")
            channels = list_channels(ctx, team.id, top=10)
            print(f"  channels in it: {len(channels)} "
                  f"(types: {sorted({c.membership_type for c in channels})})")
            apps = list_installed_apps(ctx, team.id, top=10)
            print(f"  installed apps: {len(apps)}")
    except GraphError as exc:
        if exc.status in (401, 403):
            print(f"teams-test SKIPPED: no Teams consent yet (HTTP "
                  f"{exc.status} {exc.code}) — run scripts/add-teams-scopes.sh "
                  "then re-login")
        else:
            sys.exit(f"teams-test FAILED: {exc}")

if args.transcripts:
    now = datetime.now(UTC)
    evs = list_events(ctx, start=(now - timedelta(days=args.days)).isoformat(),
                      end=(now + timedelta(days=1)).isoformat(), top=200)
    online = [e for e in evs if e.join_url]
    print(f"events last {args.days}d: {len(evs)} (online: {len(online)})")
    checked = found = 0
    try:
        for ev in online[:25]:
            mid = find_meeting_id(ctx, ev.join_url)
            if not mid:
                continue
            checked += 1
            trs = list_meeting_transcripts(ctx, mid)
            if trs:
                found += 1
                # ids and sizes only — transcript text is meeting content
                body = get_meeting_transcript(ctx, mid, trs[0].id)
                print(f"  meeting {mid[:16]}…: {len(trs)} transcript(s), "
                      f"first {len(body['content'])} chars {body['format']}")
                break
        print(f"transcripts: probed {checked} resolvable meeting(s), "
              f"{found} with a transcript")
    except GraphError as exc:
        if exc.status in (401, 403):
            print(f"transcripts-test SKIPPED: {exc.status} — {str(exc)[:90]}")
            print("  (needs scripts/add-transcript-scopes.sh AND the Teams admin "
                  "setting 'Transcript API access -> Microsoft Graph access')")
        else:
            sys.exit(f"transcripts-test FAILED: {exc}")

if args.deny:
    try:
        list_messages(ctx, top=1, mailbox=args.deny)
    except GraphError as exc:
        if 400 <= exc.status < 500:
            print(f"deny-test {args.deny}: correctly refused "
                  f"(HTTP {exc.status} {exc.code})")
        else:
            sys.exit(f"deny-test {args.deny}: unexpected error {exc}")
    else:
        sys.exit(f"DENY-TEST FAILED: {args.deny} was accessible — "
                 "check tenant permissions before proceeding")

print("SMOKE OK")
