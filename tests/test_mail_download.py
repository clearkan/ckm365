"""Offline tests for download_attachment (CKM-32) — no tenant, no network.

Covers what the tool promises: resolution by id or exact name, refusal of
the two kinds that have no file bytes, containment under the download
root, no clobbering, no residue on failure, and that the bytes come off
$value as a stream rather than inline contentBytes.
"""

import httpx
import pytest

from ckm365.config import Profile
from ckm365.graph import Graph
from ckm365.tools import Ctx, mail

MAILBOX = "user@tenant-a.example"
DOCX = b"PK\x03\x04\x14\x00\x06\x00\xff\xfe binary, not utf-8 \x00\x01\x02"


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return MAILBOX


def _attachment(att_id, name, *, kind="fileAttachment", size=1024, inline=False):
    return {"@odata.type": f"#microsoft.graph.{kind}", "id": att_id,
            "name": name, "contentType": "application/octet-stream",
            "size": size, "isInline": inline}


def _ctx(items, *, content=DOCX, value_status=200):
    """A mailbox whose messages carry `items`; $value serves `content`."""
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path.endswith("/$value"):
            if value_status != 200:
                return httpx.Response(value_status,
                                      json={"error": {"code": "ErrorBoom",
                                                      "message": "no"}})
            return httpx.Response(200, content=content)
        return httpx.Response(200, json={"value": items})

    ctx = Ctx(profiles={"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1",
        default_mailbox=MAILBOX)})
    ctx.set_graph("tenant-a", Graph(FakeAuth(),
                                    transport=httpx.MockTransport(handler)))
    return ctx, seen


def test_downloads_by_id_streaming_from_value(tmp_path):
    ctx, seen = _ctx([_attachment("att-1", "report.docx", size=1402)])
    dest = tmp_path / "report.docx"
    res = mail.download_attachment(ctx, "m1", str(dest), attachment_id="att-1")

    assert dest.read_bytes() == DOCX          # binary survives byte-for-byte
    assert res["bytes"] == len(DOCX)          # actual bytes, not Graph's size
    assert res["path"] == str(dest)
    assert res["name"] == "report.docx" and res["attachment_id"] == "att-1"
    assert seen[-1].endswith(
        f"/users/{MAILBOX.replace('@', '%40')}/messages/m1"
        "/attachments/att-1/$value")
    # the metadata listing must not pull contentBytes down with it
    assert "contentBytes" not in seen[0]
    assert not list(tmp_path.glob("*.part"))


def test_read_tier_needs_no_write_flag(tmp_path):
    """It reads the mailbox and writes to LOCAL disk: no --write anywhere."""
    ctx, _ = _ctx([_attachment("att-1", "a.pdf")])
    assert ctx.write_enabled is False
    mail.download_attachment(ctx, "m1", str(tmp_path / "a.pdf"),
                             attachment_id="att-1")


def test_folder_is_irrelevant_sent_items_uses_the_same_path(tmp_path):
    """CKM-32's second live hit was a sent-items attachment: attachments
    hang off the message id, so there is no folder in the URL at all."""
    ctx, seen = _ctx([_attachment("att-1", "transcript.docx")])
    mail.download_attachment(ctx, "sent-msg-id", str(tmp_path / "t.docx"),
                             attachment_id="att-1")
    assert all("mailFolders" not in url for url in seen)


def test_resolves_by_exact_name_and_reports_ambiguity(tmp_path):
    items = [_attachment("att-1", "notes.txt", size=10),
             _attachment("att-2", "notes.txt", size=20),
             _attachment("att-3", "other.txt")]
    ctx, _ = _ctx(items)
    mail.download_attachment(ctx, "m1", str(tmp_path / "other.txt"),
                             name="other.txt")
    assert (tmp_path / "other.txt").read_bytes() == DOCX

    with pytest.raises(ValueError, match="share that name") as err:
        mail.download_attachment(ctx, "m1", str(tmp_path / "x"), name="notes.txt")
    assert "att-1" in str(err.value) and "att-2" in str(err.value)
    with pytest.raises(ValueError, match="exact name"):
        mail.download_attachment(ctx, "m1", str(tmp_path / "x"), name="Notes.txt")
    with pytest.raises(ValueError, match="no attachment with that id"):
        mail.download_attachment(ctx, "m1", str(tmp_path / "x"),
                                 attachment_id="nope")
    with pytest.raises(ValueError, match="attachment_id"):
        mail.download_attachment(ctx, "m1", str(tmp_path / "x"))


@pytest.mark.parametrize("kind", ["itemAttachment", "referenceAttachment"])
def test_refuses_kinds_with_no_file_bytes(tmp_path, kind):
    ctx, _ = _ctx([_attachment("att-1", "thing", kind=kind)])
    with pytest.raises(ValueError, match=kind):
        mail.download_attachment(ctx, "m1", str(tmp_path / "thing"),
                                 attachment_id="att-1")
    assert not list(tmp_path.iterdir())


def test_directory_destination_uses_a_sanitised_attachment_name(tmp_path):
    ctx, _ = _ctx([_attachment("att-1", "../../etc/passwd"),
                   _attachment("att-2", "C:\\Users\\x\\Q1 report.xlsx")])
    res = mail.download_attachment(ctx, "m1", str(tmp_path),
                                   attachment_id="att-1")
    assert res["path"] == str(tmp_path / "passwd")   # never escapes tmp_path
    res = mail.download_attachment(ctx, "m1", str(tmp_path),
                                   attachment_id="att-2")
    assert res["path"] == str(tmp_path / "Q1 report.xlsx")


def test_download_root_confines_writes(tmp_path, monkeypatch):
    ctx, _ = _ctx([_attachment("att-1", "a.txt")])
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CKM365_DOWNLOAD_ROOT", str(root))
    with pytest.raises(ValueError, match="outside the download root"):
        mail.download_attachment(ctx, "m1", str(tmp_path / "escape.txt"),
                                 attachment_id="att-1")
    mail.download_attachment(ctx, "m1", str(root / "ok.txt"),
                             attachment_id="att-1")

    # ATTACH_ROOT is the fallback: fencing the read side fences this too
    monkeypatch.delenv("CKM365_DOWNLOAD_ROOT")
    monkeypatch.setenv("CKM365_ATTACH_ROOT", str(root))
    with pytest.raises(ValueError, match="outside the download root"):
        mail.download_attachment(ctx, "m1", str(tmp_path / "escape.txt"),
                                 attachment_id="att-1")


def test_never_overwrites_and_requires_an_existing_directory(tmp_path):
    ctx, _ = _ctx([_attachment("att-1", "a.txt")])
    existing = tmp_path / "a.txt"
    existing.write_bytes(b"mine")
    with pytest.raises(ValueError, match="overwrite"):
        mail.download_attachment(ctx, "m1", str(existing), attachment_id="att-1")
    assert existing.read_bytes() == b"mine"
    with pytest.raises(ValueError, match="does not exist"):
        mail.download_attachment(ctx, "m1", str(tmp_path / "no" / "a.txt"),
                                 attachment_id="att-1")
    with pytest.raises(ValueError, match="dest_path is required"):
        mail.download_attachment(ctx, "m1", "  ", attachment_id="att-1")


def test_failed_download_leaves_no_partial_file(tmp_path):
    ctx, _ = _ctx([_attachment("att-1", "a.txt")], value_status=404)
    with pytest.raises(Exception):
        mail.download_attachment(ctx, "m1", str(tmp_path / "a.txt"),
                                 attachment_id="att-1")
    assert not list(tmp_path.iterdir())


def test_graph_download_retries_transient_5xx_then_writes_once(tmp_path):
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503, json={"error": {
                "code": "ErrorInternalServerTransientError", "message": "cold"}})
        return httpx.Response(200, content=DOCX)

    graph = Graph(FakeAuth(), transport=httpx.MockTransport(handler))
    dest = tmp_path / "out.bin"
    written = graph.download("/whatever/$value", dest)
    assert written == len(DOCX) and dest.read_bytes() == DOCX
    assert len(attempts) == 3
