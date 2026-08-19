"""Write-path smoke: createReply -> verify -> attach -> revise -> remove
attachment -> discard.

Creates ONE reply draft to the newest inbox message and walks the whole
compose loop over it (CKM-42): verify_message confirms Graph seeded the
quoted history and our fenced text landed on top, a tiny generated file
goes on and comes off again, revise_draft rewrites the text and the quote
survives, and discard_draft throws the draft away — zero residue, nothing
is ever sent. Prints ids/booleans only, never content.

Usage: uv run python scripts/draft-cycle-smoke.py [profile]
"""

import sys
import tempfile
from pathlib import Path

from ckm365.graph import GraphError
from ckm365.tools import Ctx
from ckm365.tools.mail import (add_attachment, create_reply_draft,
                               discard_draft, get_message, list_attachments,
                               list_messages, remove_attachment, revise_draft,
                               verify_message)

account = sys.argv[1] if len(sys.argv) > 1 else None
MARKER = "ckm365-smoke-marker-7f3a"
REVISED = "ckm365-smoke-revised-7f3a"

ctx = Ctx.create(write=True, account=account)
g, mailbox = ctx.target(account, None)
print(f"profile={ctx.profile(account).name} mailbox={mailbox}")

newest = list_messages(ctx, top=1)
if not newest:
    sys.exit("no inbox messages to reply to")

draft = create_reply_draft(ctx, newest[0].id, f"<p>{MARKER}</p>")
print(f"reply draft created: id={draft.id[:12]}… is_draft={draft.is_draft}")

check = verify_message(ctx, draft.id)
has_marker = MARKER in check["text"]
print(f"marker on top: {has_marker}; quoted history present: "
      f"{check['quoted_thread']}; boundary={check['boundary']}; "
      f"signature: {check['signature']}; recipients={check['recipients']}")

with tempfile.TemporaryDirectory() as tmp:
    sample = Path(tmp) / "ckm365-smoke.txt"
    sample.write_text("ckm365 attachment smoke\n")
    added = add_attachment(ctx, draft.id, str(sample))
listed = list_attachments(ctx, draft.id)
att_ok = any(a.id == added.id and a.name == "ckm365-smoke.txt" for a in listed)
print(f"attachment added and listed: {att_ok} "
      f"(count={len(listed)}, size={added.size})")

revise_draft(ctx, draft.id, f"<p>{REVISED}</p>")
after = verify_message(ctx, draft.id)
revised_ok = (REVISED in after["text"] and MARKER not in after["text"]
              and after["quoted_thread"] and after["boundary"] == "fence")
print(f"revised in place, quote kept: {revised_ok} "
      f"(non_ascii in new text: {len(after['non_ascii'])})")

removed = remove_attachment(ctx, draft.id, attachment_id=added.id)
gone = not any(a.id == added.id for a in list_attachments(ctx, draft.id))
print(f"attachment removed: {removed['removed'] and gone}")

discard_draft(ctx, draft.id)
try:
    get_message(ctx, draft.id)
    sys.exit("cleanup verification failed: draft still exists")
except GraphError as exc:
    if exc.status != 404:
        raise
    print("draft discarded, 404 confirmed — no residue")

ok = (draft.is_draft and has_marker and check["quoted_thread"]
      and check["recipients"] and att_ok and revised_ok and gone)
print("WRITE SMOKE OK" if ok else "WRITE SMOKE FAILED")
sys.exit(0 if ok else 1)
