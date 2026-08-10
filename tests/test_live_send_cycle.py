"""The full send tier, end to end (CKM-40) — THE ONLY TEST THAT SENDS MAIL.

Separate from test_live.py precisely so that file keeps its "never sends"
invariant. Double-gated, and skipped unless BOTH are set:

    CKM365_LIVE_ACCOUNT=<profile> CKM365_LIVE_SEND=1 \
        uv run pytest tests/test_live_send_cycle.py -q

Needs send consent (`ckm365 login <profile> --send`) and a profile that
does not set allow_send = false.

SELF-SEND ONLY: the one recipient is the target mailbox itself, asserted
before anything is sent, so no mail can reach a third party even if the
environment is misconfigured. Zero residue — every message the run
creates, in the inbox AND in Sent Items, is deleted in a finally block
and the run ends by asserting nothing carrying its marker survives.
"""

import os
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from ckm365.graph import encode_segment, mailbox_path
from ckm365.tools import Ctx, mail

ACCOUNT = os.environ.get("CKM365_LIVE_ACCOUNT")
MAILBOX = os.environ.get("CKM365_LIVE_MAILBOX")  # default: signed-in user
SEND = os.environ.get("CKM365_LIVE_SEND") == "1"

pytestmark = pytest.mark.skipif(
    not (ACCOUNT and SEND),
    reason="send cycle runs only with CKM365_LIVE_ACCOUNT and CKM365_LIVE_SEND=1")

# Generous on purpose. Observed self-delivery is ~10s per hop on both
# tenants; the minutes-long waits seen while building this were the
# subject-filter index lag described in _find, not delivery. An opt-in
# manual check can afford to wait, and a timeout then means something.
DELIVERY_TIMEOUT_S = 600.0
POLL_S = 5.0
PAYLOAD = bytes(range(256)) * 16  # binary, deliberately not valid utf-8


@pytest.fixture(scope="module")
def ctx():
    with Ctx.create(write=True, send=True, account=ACCOUNT) as c:
        yield c


def _find(ctx, folder: str, prefix: str) -> list:
    """Every message near the top of one folder whose subject starts with
    `prefix` — NEWEST-FIRST LISTING, matched client-side, deliberately.

    Subject $filters cannot be used to detect mail that has just arrived.
    Three separate failures were caught here against real mailboxes, all
    of them SILENT (zero rows, indistinguishable from "no such mail"):
      - `subject eq '<exact>'` never matches, even byte-identically;
      - `contains(subject,…)` matches on a small mailbox and returns
        nothing in a 93k-message inbox;
      - even `startswith(subject,…)` LAGS DELIVERY: a reply delivered at
        23:22:09 stayed invisible to it for the remaining 5 minutes of the
        poll, and was found by the same predicate 11 minutes later.
    An unfiltered listing is served from the folder view rather than a
    lagging index, so a delivered message is at the top immediately. (For
    production polling, the delta tools in watch.py exist for this.)
    """
    return [m for m in mail.list_messages(ctx, folder=folder, top=50,
                                          mailbox=MAILBOX)
            if (m.subject or "").startswith(prefix)]


def _await_delivery(ctx, folder: str, prefix: str, what: str):
    """Poll one folder until a message with this subject prefix appears."""
    deadline = time.monotonic() + DELIVERY_TIMEOUT_S
    while time.monotonic() < deadline:
        found = _find(ctx, folder, prefix)
        if found:
            return found[0]
        time.sleep(POLL_S)
    raise AssertionError(
        f"{what} never arrived in {folder} within {DELIVERY_TIMEOUT_S:g}s "
        "— a stuck send is a real failure, not a flake")


def _purge(ctx, prefixes: list[str]) -> int:
    """Delete every message under these subject prefixes, in both folders."""
    g, mb = ctx.target(None, MAILBOX)
    removed = 0
    for prefix in prefixes:
        for folder in ("inbox", "sentitems"):
            for message in _find(ctx, folder, prefix):
                g.request("DELETE", mailbox_path(
                    mb, f"messages/{encode_segment(message.id)}"))
                removed += 1
    return removed


def test_send_receive_download_and_reply_all_cycle(ctx):
    """draft + attachment -> send -> receive -> download -> reply-all -> receive.

    Every step here was previously verified only by hand: the live suite
    stopped at the draft boundary, and until CKM-32 there was no way to
    get the attachment back out of the delivered copy to prove it made
    the round trip intact.
    """
    _, mailbox = ctx.target(None, MAILBOX)
    marker = f"ckm365 send cycle {uuid.uuid4().hex[:8]}"
    prefixes = [marker]  # the reply's own subject joins this once Graph picks it
    try:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ckm365-cycle.bin"
            source.write_bytes(PAYLOAD)

            draft = mail.create_draft(ctx, to=[mailbox], subject=marker,
                                      body_html="<p>ckm365 live send cycle</p>",
                                      mailbox=MAILBOX)
            # the safety property this whole file rests on
            assert [r.address.lower() for r in draft.to] == [mailbox.lower()]
            mail.add_attachment(ctx, draft.id, str(source), mailbox=MAILBOX)

            sent = mail.send_draft(ctx, draft.id, mailbox=MAILBOX)
            assert sent == {"sent": True, "message_id": draft.id,
                            "recipients": 1}

            received = _await_delivery(ctx, "inbox", marker,
                                       "the sent message")
            assert received.has_attachments
            assert received.id != draft.id  # the delivered copy is its own message

            files = [a for a in mail.list_attachments(ctx, received.id,
                                                      mailbox=MAILBOX)
                     if a.kind == "fileAttachment"]
            assert len(files) == 1 and files[0].name == source.name
            out = Path(tmp) / "roundtrip.bin"
            got = mail.download_attachment(ctx, received.id, str(out),
                                           attachment_id=files[0].id,
                                           mailbox=MAILBOX)
            assert out.read_bytes() == PAYLOAD      # survived the whole loop
            assert got["bytes"] == len(PAYLOAD)

            # reply-all on the DELIVERED message: Graph seeds the quoted
            # history and threading headers, we patch our text on top
            reply = mail.create_reply_draft(ctx, received.id,
                                            "<p>ckm365 cycle reply</p>",
                                            reply_all=True, mailbox=MAILBOX)
            assert reply.is_draft and reply.to
            assert [r.address.lower() for r in reply.to] == [mailbox.lower()]
            # Graph picks the reply prefix (RE:/Re:) — poll for the
            # subject it actually chose, never one we guessed
            assert marker in (reply.subject or "") and reply.subject != marker
            prefixes.append(reply.subject)
            assert mail.send_draft(ctx, reply.id, mailbox=MAILBOX)["sent"]

            back = _await_delivery(ctx, "inbox", reply.subject, "the reply")
            full = mail.get_message(ctx, back.id, mailbox=MAILBOX)
            body = full.body.content if full.body else ""
            assert "ckm365 cycle reply" in body
            assert marker in body or "ckm365 live send cycle" in body  # quoted
    finally:
        removed = _purge(ctx, prefixes)
    # At least the two delivered copies; four when the mailbox also keeps
    # Sent Items copies (a per-mailbox setting, so not something to assert).
    assert removed >= 2, f"expected to clean up 2+ messages, removed {removed}"
    for prefix in prefixes:
        assert not _find(ctx, "inbox", prefix)
        assert not _find(ctx, "sentitems", prefix)
