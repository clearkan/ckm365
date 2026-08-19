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
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ckm365.graph import GraphError, encode_segment, mailbox_path
from ckm365.models import MessageHeaders
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


def test_download_attachment_round_trip(ctx):
    """CKM-32 against real Graph: the bytes off /$value must be exactly
    what went in — binary, not text — and Graph's reported `size` counts
    the MIME-encoded form, so it over-reports what lands on disk. Zero
    residue: the draft is deleted and the files live in a temp dir."""
    payload = bytes(range(256)) * 8  # deliberately not valid utf-8
    _, mb = ctx.target(None, MAILBOX)
    draft = mail.create_draft(ctx, to=[mb], subject="ckm365 live download",
                              body_html="<p>ckm365 live suite</p>",
                              mailbox=MAILBOX)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "ckm365-live-download.bin"
            sample.write_bytes(payload)
            added = mail.add_attachment(ctx, draft.id, str(sample),
                                        mailbox=MAILBOX)
            assert added.kind == "fileAttachment"  # rides along with $select

            out = Path(tmp) / "out.bin"
            res = mail.download_attachment(ctx, draft.id, str(out),
                                           attachment_id=added.id,
                                           mailbox=MAILBOX)
            assert out.read_bytes() == payload
            assert res["bytes"] == len(payload) <= added.size

            # by exact name, into a DIRECTORY: the attachment names itself
            into = Path(tmp) / "into"
            into.mkdir()
            by_name = mail.download_attachment(ctx, draft.id, str(into),
                                               name=sample.name,
                                               mailbox=MAILBOX)
            assert Path(by_name["path"]) == into / sample.name
            assert Path(by_name["path"]).read_bytes() == payload
            with pytest.raises(ValueError, match="overwrite"):
                mail.download_attachment(ctx, draft.id, str(out),
                                         attachment_id=added.id,
                                         mailbox=MAILBOX)
    finally:
        _delete(ctx, "messages", draft.id)


def test_download_attachment_from_sent_items(ctx):
    """The second live hit was a .docx in SENT ITEMS: attachments hang off
    the message id, so the folder must make no difference. Read-only, into
    a temp dir; nothing about the file is asserted beyond its size."""
    sent = mail.list_messages(ctx, folder="sentitems", top=10,
                              filter="hasAttachments eq true", mailbox=MAILBOX)
    for message in sent:
        files = [a for a in mail.list_attachments(ctx, message.id,
                                                  mailbox=MAILBOX)
                 if a.kind == "fileAttachment"]
        if not files:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            res = mail.download_attachment(ctx, message.id, tmp,
                                           attachment_id=files[0].id,
                                           mailbox=MAILBOX)
            written = Path(res["path"])
            assert written.stat().st_size == res["bytes"] > 0
            assert res["bytes"] <= files[0].size  # MIME-encoded size is bigger
        return
    pytest.skip("sent items has no message carrying a file attachment")


def test_export_message_both_formats(ctx):
    """CKM-39 against real Graph, on a message this test creates (so the
    assertions can look at content without touching real mail). The claim
    being tested is the one that motivated the format: the .md record is
    GREPPABLE, where the raw .eml is not guaranteed to be."""
    _, mb = ctx.target(None, MAILBOX)
    token = "ckm365-export-marker-zqx"
    draft = mail.create_draft(ctx, to=[mb], subject="ckm365 live export",
                              body_html=f"<p>{token}</p><p>second line</p>",
                              mailbox=MAILBOX)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "record.md"
            res = mail.export_message(ctx, draft.id, str(record),
                                      mailbox=MAILBOX)
            text = record.read_text(encoding="utf-8")
            assert token in text                     # plain text, greppable
            assert "<p>" not in text                 # Graph converted the HTML
            assert res["format"] == "md" and res["attachments"] == 0
            # OKF v0.1 front matter, from REAL Graph fields
            assert 'type: "Email"' in text
            assert 'title: "ckm365 live export"' in text
            assert f'description: "{token}' in text  # Graph's own preview
            assert "timestamp: " in text and "resource: " in text
            # an unsent draft has no `from`, so no direction is claimed
            assert 'tags: ["email"]' in text

            # a REAL message does carry one, and it must agree with who
            # sent it (nothing else about the message is asserted on)
            newest = mail.list_messages(ctx, top=1, mailbox=MAILBOX)
            if newest:
                real = Path(tmp) / "real.md"
                mail.export_message(ctx, newest[0].id, str(real),
                                    mailbox=MAILBOX)
                sender = (newest[0].sender.address
                          if newest[0].sender else "").lower()
                expected = "outbound" if sender == mb.lower() else "inbound"
                assert f'"{expected}"' in real.read_text().split("---")[1]

            raw = Path(tmp) / "record.eml"
            res = mail.export_message(ctx, draft.id, str(raw), mailbox=MAILBOX)
            head = raw.read_bytes()[:2000].lower()
            assert b"mime-version" in head or b"content-type" in head
            assert res["format"] == "eml" and res["attachments"] is None
    finally:
        _delete(ctx, "messages", draft.id)


def test_compose_loop_revise_verify_remove_discard(ctx):
    """CKM-42 against real Graph: the fence must survive Graph's PATCH
    round trip, a revision must replace our text while the quoted history
    and the signature stay put, and discard_draft must leave no residue."""
    newest = mail.list_messages(ctx, top=1, mailbox=MAILBOX)
    if not newest:
        pytest.skip("mailbox has no messages to reply to")
    first, second = "ckm365-live-first-draft", "ckm365-live-second-draft"
    signature = bool(ctx.profile(ACCOUNT).signature_html)
    draft = mail.create_reply_draft(ctx, newest[0].id, f"<p>{first}</p>",
                                    mailbox=MAILBOX)
    discarded = False
    try:
        before = mail.verify_message(ctx, draft.id, mailbox=MAILBOX)
        assert before["boundary"] == "fence"  # our comments survived Graph
        assert first in before["text"] and before["quoted_thread"]
        assert before["recipients"] >= 1 and before["is_draft"]
        assert before["signature"] is signature

        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "live-compose.txt"
            sample.write_text("live compose loop")
            added = mail.add_attachment(ctx, draft.id, str(sample),
                                        mailbox=MAILBOX)

        mail.revise_draft(ctx, draft.id, f"<p>{second}</p>", mailbox=MAILBOX)
        after = mail.verify_message(ctx, draft.id, mailbox=MAILBOX)
        assert second in after["text"] and first not in after["text"]
        assert after["quoted_thread"] and after["boundary"] == "fence"
        assert after["signature"] is signature
        assert any(a["attachment_id"] == added.id
                   for a in after["attachments"])

        assert mail.remove_attachment(ctx, draft.id, attachment_id=added.id,
                                      mailbox=MAILBOX)["removed"]
        assert not any(a.id == added.id for a in
                       mail.list_attachments(ctx, draft.id, mailbox=MAILBOX))
        assert mail.discard_draft(ctx, draft.id,
                                  mailbox=MAILBOX)["discarded"]
        discarded = True
    finally:
        if not discarded:
            _delete(ctx, "messages", draft.id)
    with pytest.raises(GraphError) as err:
        mail.get_message(ctx, draft.id, mailbox=MAILBOX)
    assert err.value.status == 404  # residue check


def test_compose_loop_guards_refuse_delivered_mail(ctx):
    """discard_draft and remove_attachment must be as draft-only as
    update_draft — the offline mocks assert it, this proves Graph agrees."""
    newest = mail.list_messages(ctx, top=1, mailbox=MAILBOX)
    if not newest:
        pytest.skip("mailbox has no messages")
    for call in (lambda: mail.discard_draft(ctx, newest[0].id, mailbox=MAILBOX),
                 lambda: mail.revise_draft(ctx, newest[0].id, "<p>x</p>",
                                           mailbox=MAILBOX),
                 lambda: mail.remove_attachment(ctx, newest[0].id, name="x",
                                                mailbox=MAILBOX)):
        with pytest.raises(ValueError, match="non-draft"):
            call()


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


def test_server_side_predicates_are_accepted_by_graph(ctx):
    """CKM-35: every predicate must push into ONE $filter that Graph
    accepts. Offline mocks accept any query string, so this is the only
    place the OData is really checked — and the transient 503 that
    motivated the issue only ever appeared on a real mailbox."""
    unread = mail.list_messages(ctx, unread_only=True, top=5, mailbox=MAILBOX)
    assert all(not m.is_read for m in unread)
    assert isinstance(
        mail.list_messages(ctx, flagged_only=True, top=5, mailbox=MAILBOX), list)
    since = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = mail.list_messages(ctx, since=since, top=5, mailbox=MAILBOX)
    assert all(m.received >= since for m in recent if m.received)
    # all four at once, plus the raw escape hatch ANDed alongside
    mail.list_messages(ctx, unread_only=True, since=since,
                       from_address="nobody@tenant-b.example",
                       filter="hasAttachments eq true", top=5, mailbox=MAILBOX)
    with pytest.raises(ValueError, match="search cannot be combined"):
        mail.list_messages(ctx, search="x", unread_only=True, mailbox=MAILBOX)


def test_group_by_sender_aggregates_without_pulling_messages(ctx):
    res = mail.group_by_sender(ctx, max_scan=200, mailbox=MAILBOX)
    assert res["scanned"] <= 200
    assert res["truncated"] is (res["scanned"] == 200)
    assert sum(s["total"] for s in res["senders"]) == res["scanned"]
    assert all(s["unread"] <= s["total"] for s in res["senders"])
    totals = [s["total"] for s in res["senders"]]
    assert totals == sorted(totals, reverse=True)  # busiest sender first


def test_recipients_ride_along_and_headers_are_curated(ctx):
    """CKM-37/38 against real Graph. Offline mocks return whatever the
    handler is given, so only a live call proves Graph honours to/cc on a
    COLLECTION GET and that the header bag curates down to the named
    subset. Read-only, and no message content is asserted on."""
    sent = mail.list_messages(ctx, folder="sentitems", top=10, mailbox=MAILBOX)
    if sent:
        # In Sent Items the sender is always the owner: `to` is the only
        # thing identifying the correspondent (CKM-37's first blocker).
        assert any(m.to for m in sent)
        assert all(r.address for m in sent for r in m.to)
    newest = mail.list_messages(ctx, top=5, mailbox=MAILBOX)
    if not newest:
        pytest.skip("mailbox has no messages")

    res = mail.get_message_headers(ctx, [m.id for m in newest], mailbox=MAILBOX)
    assert res["ok"] == len(newest) and res["failed"] == []
    curated = {f.name for f in fields(MessageHeaders)}
    for headers in res["headers"].values():
        assert set(headers) == curated  # never the raw bag Graph returned
        assert all(len(v) <= 200 for v in headers.values()
                   if isinstance(v, str))
    # get_message carries the same projection, from the same real headers
    one = mail.get_message(ctx, newest[0].id, mailbox=MAILBOX)
    assert one.headers is None or isinstance(one.headers.is_bulk, bool)


def test_triage_cycle_read_state_flags_and_move(ctx):
    """CKM-33/34/36 end to end against Graph, on a message this test
    creates — real mail is never touched. Zero residue: the draft is
    deleted at its post-move id and verified gone."""
    _, mb = ctx.target(None, MAILBOX)
    draft = mail.create_draft(ctx, to=[mb], subject="ckm365 live triage",
                              body_html="<p>ckm365 live suite</p>",
                              mailbox=MAILBOX)
    current = draft.id
    try:
        assert mail.mark_read(ctx, [current], mailbox=MAILBOX) == \
            {"ok": 1, "failed": []}
        assert mail.get_message(ctx, current, mailbox=MAILBOX).is_read
        assert mail.mark_unread(ctx, [current], mailbox=MAILBOX)["ok"] == 1
        assert not mail.get_message(ctx, current, mailbox=MAILBOX).is_read

        # a bad id alongside a good one must not strand the good one
        partial = mail.mark_read(ctx, [current, "not-a-real-message-id"],
                                 mailbox=MAILBOX)
        assert partial["ok"] == 1 and len(partial["failed"]) == 1
        assert partial["failed"][0]["id"] == "not-a-real-message-id"

        assert mail.flag(ctx, [current], mailbox=MAILBOX)["timezone"] is None
        assert _flag_status(ctx, current) == "flagged"
        dated = mail.flag(ctx, [current], due="2026-12-24T17:00:00",
                          timezone="Europe/London", mailbox=MAILBOX)
        assert dated["ok"] == 1 and dated["timezone"] == "Europe/London"
        assert mail.complete_flag(ctx, [current], mailbox=MAILBOX)["ok"] == 1
        assert _flag_status(ctx, current) == "complete"
        assert mail.unflag(ctx, [current], mailbox=MAILBOX)["ok"] == 1
        assert _flag_status(ctx, current) == "notFlagged"

        with pytest.raises(ValueError, match="never creates folders"):
            mail.move_message(ctx, [current], "ckm365-no-such-folder",
                              mailbox=MAILBOX)
        moved = mail.move_message(ctx, [current], "archive", mailbox=MAILBOX)
        assert moved["ok"] == 1 and moved["failed"] == []
        # a move mints a NEW id — the old one is a dead reference
        current = moved["moved"][draft.id]
        assert current and current != draft.id
        assert mail.get_message(ctx, current, mailbox=MAILBOX).id == current
    finally:
        _delete(ctx, "messages", current)
    with pytest.raises(GraphError) as err:
        mail.get_message(ctx, current, mailbox=MAILBOX)
    assert err.value.status == 404  # residue check


def _flag_status(ctx, message_id: str) -> str:
    g, mb = ctx.target(None, MAILBOX)
    data = g.get(mailbox_path(mb, f"messages/{encode_segment(message_id)}"),
                 params={"$select": "flag"})
    return (data.get("flag") or {}).get("flagStatus", "")
