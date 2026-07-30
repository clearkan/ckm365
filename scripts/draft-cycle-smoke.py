"""Write-path smoke: createReply -> verify marker + quoted history ->
attach file -> verify attachment -> DELETE.

Creates ONE reply draft to the newest inbox message, checks Graph seeded the
quoted history and our HTML landed on top, attaches a tiny generated file
and confirms it lists, then deletes the draft — zero residue. Prints
ids/booleans only, never content.

Usage: uv run python scripts/draft-cycle-smoke.py [profile]
"""

import sys
import tempfile
from pathlib import Path

from ckm365.graph import GraphError, encode_segment, mailbox_path
from ckm365.tools import Ctx
from ckm365.tools.mail import (add_attachment, create_reply_draft,
                               get_message, list_attachments, list_messages)

account = sys.argv[1] if len(sys.argv) > 1 else None
MARKER = "ckm365-smoke-marker-7f3a"

ctx = Ctx.create(write=True, account=account)
g, mailbox = ctx.target(account, None)
print(f"profile={ctx.profile(account).name} mailbox={mailbox}")

newest = list_messages(ctx, top=1, account=account)
if not newest:
    sys.exit("no inbox messages to reply to")

draft = create_reply_draft(ctx, newest[0].id, f"<p>{MARKER}</p>", account=account)
print(f"reply draft created: id={draft.id[:12]}… is_draft={draft.is_draft}")

fetched = get_message(ctx, draft.id, body_format="html", account=account)
content = fetched.body.content if fetched.body else ""
has_marker = MARKER in content
has_history = len(content) > len(MARKER) + 200  # quoted original present
print(f"marker on top: {has_marker}; quoted history present: {has_history} "
      f"(body {len(content)} chars); recipients prefilled: {len(fetched.to) > 0}")

with tempfile.TemporaryDirectory() as tmp:
    sample = Path(tmp) / "ckm365-smoke.txt"
    sample.write_text("ckm365 attachment smoke\n")
    added = add_attachment(ctx, draft.id, str(sample), account=account)
listed = list_attachments(ctx, draft.id, account=account)
att_ok = any(a.id == added.id and a.name == "ckm365-smoke.txt" for a in listed)
print(f"attachment added and listed: {att_ok} "
      f"(count={len(listed)}, size={added.size})")

g.request("DELETE", mailbox_path(mailbox, f"messages/{encode_segment(draft.id)}"))
try:
    get_message(ctx, draft.id, account=account)
    sys.exit("cleanup verification failed: draft still exists")
except GraphError as exc:
    if exc.status != 404:
        raise
    print("draft deleted, 404 confirmed — no residue")

ok = draft.is_draft and has_marker and fetched.to and att_ok
print("WRITE SMOKE OK" if ok else "WRITE SMOKE FAILED")
sys.exit(0 if ok else 1)
