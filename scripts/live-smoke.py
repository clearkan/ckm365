"""Read-only live smoke test against a real mailbox.

Prints counts and truncated ids ONLY — never subjects, bodies, addresses of
correspondents, or tokens — so its output is safe to feed back into an
agent session.

Usage: uv run python scripts/live-smoke.py [profile] [--deny MAILBOX]
                                                     [--shared MAILBOX]

--deny MAILBOX runs a negative test: listing that mailbox's messages MUST
fail with a Graph 4xx (proves tenant permissions do not leak across users).
--shared MAILBOX runs a positive test: the shared mailbox MUST be readable
via the profile's .Shared delegated scopes (counts printed, nothing else).
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta

from ckm365.graph import GraphError
from ckm365.tools import Ctx
from ckm365.tools.calendar import list_events
from ckm365.tools.mail import list_mail_folders, list_messages

parser = argparse.ArgumentParser()
parser.add_argument("profile", nargs="?", default=None)
parser.add_argument("--deny", metavar="MAILBOX", default=None)
parser.add_argument("--shared", metavar="MAILBOX", default=None)
args = parser.parse_args()
account = args.profile

ctx = Ctx.create(write=False, account=account)
profile = ctx.profile(account)
_, mailbox = ctx.target(account, None)
print(f"profile={profile.name} mailbox={mailbox}")

folders = list_mail_folders(ctx, account=account)
print(f"mail folders: {len(folders)}")

messages = list_messages(ctx, top=5, account=account)
print(f"inbox messages fetched: {len(messages)}")
print(f"  ids: {[m.id[:12] + '…' for m in messages]}")

now = datetime.now(UTC)
events = list_events(ctx, start=now.isoformat(),
                     end=(now + timedelta(days=7)).isoformat(), account=account)
print(f"calendar events next 7 days: {len(events)}")

if args.shared:
    try:
        shared = list_messages(ctx, top=3, account=account, mailbox=args.shared)
        print(f"shared-test {args.shared}: readable, "
              f"{len(shared)} message(s) fetched")
    except GraphError as exc:
        sys.exit(f"SHARED-TEST FAILED: {args.shared} not readable "
                 f"(HTTP {exc.status} {exc.code}) — likely missing FullAccess "
                 "for the signed-in user; grant via Exchange Online: "
                 f"Add-MailboxPermission {args.shared} -User <upn> "
                 "-AccessRights FullAccess -AutoMapping $false")

if args.deny:
    try:
        list_messages(ctx, top=1, account=account, mailbox=args.deny)
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
