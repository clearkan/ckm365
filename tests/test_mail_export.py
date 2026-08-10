"""Offline tests for export_message (CKM-39) — no tenant, no network.

The record's whole reason to exist is that it is GREPPABLE and stable, so
that is what these assert: plain-text body on disk, front matter that
survives a hostile subject, attachment ids to fetch the bytes with, and
byte-identical output on re-export.
"""

import httpx
import pytest

from ckm365.config import Profile
from ckm365.graph import Graph
from ckm365.tools import Ctx, mail

MAILBOX = "user@tenant-a.example"
BODY = "Please see the attached Q1 figures. Regards, Alex"
# what Graph's $value serves: a real .eml, whose body parts Exchange
# base64-encodes — the reason the .md format exists at all
RAW_MIME = (b"From: other-user@tenant-b.example\r\nSubject: Q1\r\n"
            b"Content-Transfer-Encoding: base64\r\n\r\n"
            b"UGxlYXNlIHNlZSB0aGUgYXR0YWNoZWQgUTEgZmlndXJlcy4=\r\n")


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return MAILBOX


def _message(subject="Q1 figures", *, attachments=True):
    return {
        "id": "m1", "subject": subject,
        "from": {"emailAddress": {"name": "Alex Doe",
                                  "address": "other-user@tenant-b.example"}},
        "toRecipients": [{"emailAddress": {"name": "Ops",
                                           "address": MAILBOX}}],
        "ccRecipients": [{"emailAddress": {"address": "colleague@tenant-a.example"}}],
        "receivedDateTime": "2026-08-10T09:15:00Z",
        "body": {"contentType": "text", "content": BODY},
        "bodyPreview": BODY[:40],
        "internetMessageId": "<abc123@tenant-b.example>",
        "internetMessageHeaders": [{"name": "List-Id", "value": "<news.example>"}],
        "webLink": "https://outlook.office365.com/mail/deeplink/m1",
        "hasAttachments": attachments, "isRead": True, "isDraft": False,
    }


def _ctx(message=None, attachments=()):
    seen = []
    prefer = []

    def handler(request):
        seen.append(str(request.url))
        if request.headers.get("prefer"):
            prefer.append(request.headers["prefer"])
        if request.url.path.endswith("/$value"):
            return httpx.Response(200, content=RAW_MIME)
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json={"value": list(attachments)})
        return httpx.Response(200, json=message or _message())

    ctx = Ctx(profiles={"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1",
        default_mailbox=MAILBOX)})
    ctx.set_graph("tenant-a", Graph(FakeAuth(),
                                    transport=httpx.MockTransport(handler)))
    return ctx, seen, prefer


def _attachment(att_id="att-1", name="q1.xlsx"):
    return {"@odata.type": "#microsoft.graph.fileAttachment", "id": att_id,
            "name": name, "contentType": "application/vnd.ms-excel",
            "size": 2048, "isInline": False}


def test_markdown_record_is_greppable_and_complete(tmp_path):
    ctx, seen, prefer = _ctx(attachments=[_attachment()])
    dest = tmp_path / "2026-08-10-q1.md"
    res = mail.export_message(ctx, "m1", str(dest))

    text = dest.read_text(encoding="utf-8")
    assert BODY in text                      # the point: plain text on disk
    assert res == {"path": str(dest), "bytes": len(text.encode()),
                   "format": "md", "attachments": 1}
    for line in (
            # OKF v0.1 core (openknowledgeformat.com): the record IS an OKF
            # document, so it drops into an okf/ repo unmodified
            'type: "Email"',
            'title: "Q1 figures"',
            f'description: "{BODY[:40]}"',   # OKF's one-liner: Graph's preview
            'resource: "https://outlook.office365.com/mail/deeplink/m1"',
            # facets an okf/ repo can filter on, all derived
            'tags: ["email", "inbound", "attachments", "bulk"]',
            'timestamp: "2026-08-10T09:15:00Z"',
            # extension keys: the mail specifics OKF has no opinion about
            'from: "Alex Doe <other-user@tenant-b.example>"',
            f'to: "Ops <{MAILBOX}>"',
            'cc: "colleague@tenant-a.example"',
            'internet_message_id: "<abc123@tenant-b.example>"',
            "has_attachments: true",
            "is_bulk: true"):                # derived from the List-Id header
        assert line in text, line
    # the manifest carries what download_attachment needs
    assert "q1.xlsx — 2048 B, fileAttachment, attachment_id `att-1`" in text
    # the body was fetched as TEXT: Graph does the HTML conversion, so
    # no local HTML stripping (and no new dependency) is needed
    assert prefer == ['outlook.body-content-type="text"']
    assert "$value" not in " ".join(seen)     # md never touches raw MIME


def test_record_is_deterministic_so_git_sees_no_diff(tmp_path):
    ctx, _, _prefer = _ctx(attachments=[_attachment()])
    first = tmp_path / "a.md"
    second = tmp_path / "b.md"
    mail.export_message(ctx, "m1", str(first))
    mail.export_message(ctx, "m1", str(second))
    assert first.read_bytes() == second.read_bytes()


def test_hostile_subject_cannot_break_the_front_matter(tmp_path):
    nasty = 'RE: costs: "urgent"\r\n---\ntype: injected'
    ctx, _, _prefer = _ctx(_message(nasty))
    dest = tmp_path / "x.md"
    mail.export_message(ctx, "m1", str(dest))
    front = dest.read_text().split("---")[1]
    assert "injected" not in front            # newlines stripped, quotes escaped
    assert front.count("type:") == 1          # no second key smuggled in


def test_eml_export_is_the_raw_mime(tmp_path):
    ctx, seen, prefer = _ctx()
    dest = tmp_path / "record.eml"
    res = mail.export_message(ctx, "m1", str(dest))
    assert dest.read_bytes() == RAW_MIME
    assert res["format"] == "eml" and res["attachments"] is None
    assert seen[-1].endswith(f"/users/{MAILBOX.replace('@', '%40')}"
                             "/messages/m1/$value")


def test_extension_chooses_the_format_and_is_required(tmp_path):
    ctx, _, _prefer = _ctx()
    with pytest.raises(ValueError, match="dest_path must end in"):
        mail.export_message(ctx, "m1", str(tmp_path / "record.docx"))
    with pytest.raises(ValueError, match="dest_path must end in"):
        mail.export_message(ctx, "m1", str(tmp_path / "record"))
    with pytest.raises(ValueError, match="dest_path must end in"):
        mail.export_message(ctx, "m1", str(tmp_path))     # a bare directory
    (tmp_path / "looks-like.md").mkdir()                  # ...and a directory
    with pytest.raises(ValueError, match="name the file"):  # that ends in .md
        mail.export_message(ctx, "m1", str(tmp_path / "looks-like.md"))
    mail.export_message(ctx, "m1", str(tmp_path / "r.TXT"))  # case-insensitive


def test_disk_rules_match_download_attachment(tmp_path, monkeypatch):
    ctx, _, _prefer = _ctx()
    existing = tmp_path / "taken.md"
    existing.write_text("mine")
    with pytest.raises(ValueError, match="overwrite"):
        mail.export_message(ctx, "m1", str(existing))
    assert existing.read_text() == "mine"

    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CKM365_DOWNLOAD_ROOT", str(root))
    with pytest.raises(ValueError, match="outside the download root"):
        mail.export_message(ctx, "m1", str(tmp_path / "escape.md"))
    mail.export_message(ctx, "m1", str(root / "ok.md"))
    assert not list(root.glob("*.part"))


def test_message_with_no_attachments_skips_the_manifest(tmp_path):
    ctx, seen, prefer = _ctx(_message(attachments=False))
    dest = tmp_path / "plain.md"
    res = mail.export_message(ctx, "m1", str(dest))
    assert res["attachments"] == 0
    assert "## Attachments" not in dest.read_text()
    assert not any(url.endswith("/attachments") for url in seen)


def test_description_falls_back_to_the_body_when_there_is_no_preview(tmp_path):
    """An OKF document with an empty description is a poor citizen of the
    repo it lands in, so the body stands in when bodyPreview is absent."""
    message = _message()
    del message["bodyPreview"]
    ctx, _, _prefer = _ctx(message)
    dest = tmp_path / "p.md"
    mail.export_message(ctx, "m1", str(dest))
    assert f'description: "{BODY}"' in dest.read_text()
