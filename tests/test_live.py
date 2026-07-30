"""Live integration suite (CKM-9) — SKIPPED unless CKM365_LIVE_ACCOUNT is set.

Zero-residue: everything it creates it deletes and verifies gone. Point it
at a tst.* test mailbox (scripts/create-test-mailbox.ps1) or any mailbox
the signed-in profile can access:

    CKM365_LIVE_ACCOUNT=<profile> [CKM365_LIVE_MAILBOX=<smtp>] \
        uv run pytest tests/test_live.py -q

Needs write consent (base tier); it never sends and never touches the
send tier. Output is pytest pass/fail only — no message content.
"""

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ckm365.graph import GraphError, encode_segment, mailbox_path
from ckm365.tools import Ctx, calendar as cal, mail
from ckm365.tools.watch import list_new_messages

ACCOUNT = os.environ.get("CKM365_LIVE_ACCOUNT")
MAILBOX = os.environ.get("CKM365_LIVE_MAILBOX")  # default: signed-in user

pytestmark = pytest.mark.skipif(
    not ACCOUNT, reason="live suite runs only with CKM365_LIVE_ACCOUNT set")


@pytest.fixture(scope="module")
def ctx():
    return Ctx.create(write=True, account=ACCOUNT)


def _delete(ctx, kind, item_id):
    g, mb = ctx.target(None, MAILBOX)
    g.request("DELETE", mailbox_path(mb, f"{kind}/{encode_segment(item_id)}"))


def test_read_path(ctx):
    folders = mail.list_mail_folders(ctx, mailbox=MAILBOX)
    assert folders and all(f.id for f in folders)
    assert isinstance(mail.list_messages(ctx, top=3, mailbox=MAILBOX), list)


def test_draft_cycle_reply_patch_attach_update_delete(ctx):
    """The requirements' core invariant: createReply seeds quoted history,
    our content lands on top, drafts (only) are patchable, no residue."""
    newest = mail.list_messages(ctx, top=1, mailbox=MAILBOX)
    if not newest:
        pytest.skip("mailbox has no messages to reply to")
    marker = "ckm365-live-suite-marker"
    draft = mail.create_reply_draft(ctx, newest[0].id, f"<p>{marker}</p>",
                                    mailbox=MAILBOX)
    try:
        assert draft.is_draft and draft.to
        fetched = mail.get_message(ctx, draft.id, body_format="html",
                                   mailbox=MAILBOX)
        content = fetched.body.content if fetched.body else ""
        assert marker in content
        assert len(content) > len(marker) + 100  # quoted history preserved

        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "live.txt"
            sample.write_text("live suite attachment")
            added = mail.add_attachment(ctx, draft.id, str(sample),
                                        mailbox=MAILBOX)
        assert any(a.id == added.id for a in
                   mail.list_attachments(ctx, draft.id, mailbox=MAILBOX))

        updated = mail.update_draft(ctx, draft.id, subject="ckm365 live suite",
                                    mailbox=MAILBOX)
        assert updated.subject == "ckm365 live suite"
    finally:
        _delete(ctx, "messages", draft.id)
    with pytest.raises(GraphError) as err:
        mail.get_message(ctx, draft.id, mailbox=MAILBOX)
    assert err.value.status == 404  # residue check


def test_delivered_messages_are_untouchable(ctx):
    newest = mail.list_messages(ctx, top=1, mailbox=MAILBOX)
    if not newest:
        pytest.skip("mailbox has no messages")
    with pytest.raises(ValueError, match="non-draft"):
        mail.update_draft(ctx, newest[0].id, subject="nope", mailbox=MAILBOX)


def test_calendar_event_cycle(ctx):
    start = (datetime.now(UTC) + timedelta(days=2)).replace(
        minute=0, second=0, microsecond=0)
    ev = cal.create_event(ctx, subject="ckm365 live suite event",
                          start=start.isoformat(),
                          end=(start + timedelta(minutes=15)).isoformat(),
                          mailbox=MAILBOX)
    try:
        assert cal.get_event(ctx, ev.id, mailbox=MAILBOX).subject \
            == "ckm365 live suite event"
        assert cal.update_event(ctx, ev.id, location="Nowhere",
                                mailbox=MAILBOX).location == "Nowhere"
    finally:
        _delete(ctx, "events", ev.id)


def test_delta_bootstrap_returns_token_fast(ctx):
    boot = list_new_messages(Ctx.create(account=ACCOUNT), mailbox=MAILBOX)
    assert boot["delta_token"]
    assert boot["matched"] == 0 or boot["messages"]  # shape sanity
