"""Offline spec for kw20z6 gap 4 (CKM-44): inline images stop being
invisible in exported records.

The live miss: a message whose whole substance was two inline PNGs
(annotated slides) exported as a record with no manifest and bare
`[cid:...]` markers. Graph reports hasAttachments=false when every
attachment is inline, so nothing said the record was missing its point.

Measured live, read-only (2026-11-07), on three such messages: every one
had hasAttachments=false; listing attachments with
`$select=...,contentId` is a 400, but the cast form
`microsoft.graph.fileAttachment/contentId` works, and its value matched
every `[cid:...]` marker in the text body exactly (10 of 10). One
message had an inline image no marker referenced.

So:
1. Attachment carries `content_id`, selected with the cast form.
2. The record lists attachments when Graph says it has some OR the text
   carries a `[cid:` marker, so inline-only mail gets its manifest.
3. Inline attachments are numbered 1..n in manifest order. A marker
   whose cid matches one becomes `[inline N: <name>]`, and its manifest
   line says `inline N`. A marker matching nothing is left as it is.
4. `has_attachments` and the `attachments` tag are true when the
   manifest is non-empty, whatever Graph's flag said.
5. export_messages(attachments=True) also saves inline attachments, as
   `<stem>/inline<N>-<name>`: inline images routinely share a name
   ("image.png"), so the number keeps them apart and ties each file to
   its marker.

ckm365 does not describe images; it surfaces and names the bytes.

Skipped as a module until Attachment has content_id.
"""

from dataclasses import fields

import pytest

from ckm365.models import Attachment

if "content_id" not in {f.name for f in fields(Attachment)}:
    pytest.skip("inline images not built yet (kw20z6 gap 4)",
                allow_module_level=True)

from ckm365.tools import mail  # noqa: E402
from test_mail_export import _ctx, _message  # noqa: E402

CID1 = "image001.png@01DB0000.11112222"
CID2 = "image002.png@01DB0000.11112222"
TEXT = (f"See the red comments.\n[cid:{CID1}]\nAnd page two:\n[cid:{CID2}]\n"
        "Unknown one: [cid:not-listed@x]\nThanks")


def _inline(att_id, name, cid, kind="fileAttachment"):
    return {"@odata.type": f"#microsoft.graph.{kind}", "id": att_id,
            "name": name, "contentType": "image/png", "size": 5000,
            "isInline": True, "contentId": cid}


def _file(att_id="att-x", name="deck.pdf"):
    return {"@odata.type": "#microsoft.graph.fileAttachment", "id": att_id,
            "name": name, "contentType": "application/pdf", "size": 9000,
            "isInline": False}


def inline_only(text=TEXT):
    m = _message(attachments=False)  # what Graph says for inline-only mail
    m["body"] = {"contentType": "text", "content": text}
    return m


ATTS = [_inline("att-1", "image.png", CID1), _inline("att-2", "image.png", CID2)]


def export(tmp_path, message, attachments=ATTS):
    ctx, seen, _ = _ctx(message=message, attachments=attachments)
    dest = tmp_path / "rec.md"
    res = mail.export_message(ctx, "m1", str(dest), full_body=True)
    return dest.read_text(encoding="utf-8"), res, seen


# --- model ------------------------------------------------------------------

def test_attachment_selects_content_id_with_the_cast():
    assert ("microsoft.graph.fileAttachment/contentId"
            in Attachment.SELECT.split(","))
    assert "contentId" not in Attachment.SELECT.split(",")  # 400 live
    a = Attachment.from_graph(_inline("a", "image.png", CID1))
    assert a.content_id == CID1
    assert Attachment.from_graph(_file()).content_id is None


# --- the record ---------------------------------------------------------------

def test_inline_only_mail_gets_a_manifest(tmp_path):
    text, res, seen = export(tmp_path, inline_only())
    assert any(u.split("?")[0].endswith("/attachments") for u in seen)
    assert res["attachments"] == 2
    assert "## Attachments" in text
    assert "has_attachments: true" in text
    assert '"attachments"' in text.partition("\n---\n")[0]  # the tag


def test_cid_markers_become_numbered_references(tmp_path):
    text, _, _ = export(tmp_path, inline_only())
    body = text.partition("## Attachments")[0]
    assert "[inline 1: image.png]" in body
    assert "[inline 2: image.png]" in body
    assert f"[cid:{CID1}]" not in body and f"[cid:{CID2}]" not in body
    assert "[cid:not-listed@x]" in body          # no match: left alone
    manifest = text.partition("## Attachments")[2]
    assert "inline 1, attachment_id `att-1`" in manifest
    assert "inline 2, attachment_id `att-2`" in manifest


def test_content_id_with_angle_brackets_still_matches(tmp_path):
    atts = [_inline("att-1", "image.png", f"<{CID1}>")]
    text, _, _ = export(tmp_path, inline_only(f"[cid:{CID1}]"), atts)
    assert "[inline 1: image.png]" in text


def test_numbering_counts_inline_attachments_only_in_manifest_order(tmp_path):
    m = inline_only(f"[cid:{CID2}]")
    m["hasAttachments"] = True
    atts = [_file(), _inline("att-2", "chart.png", CID2)]
    text, res, _ = export(tmp_path, m, atts)
    assert res["attachments"] == 2
    assert "[inline 1: chart.png]" in text
    manifest = text.partition("## Attachments")[2]
    assert "- deck.pdf" in manifest and "inline 1" in manifest
    assert manifest.count("inline") == 1          # the pdf is not inline


def test_unreferenced_inline_image_is_still_listed(tmp_path):
    atts = ATTS + [_inline("att-3", "logo.png", "logo@sig")]
    text, res, _ = export(tmp_path, inline_only(), atts)
    assert res["attachments"] == 3
    assert "inline 3, attachment_id `att-3`" in text


def test_plain_mail_still_skips_the_listing_call(tmp_path):
    text, res, seen = export(tmp_path, _message(attachments=False), [])
    assert not any(u.split("?")[0].endswith("/attachments") for u in seen)
    assert res["attachments"] == 0
    assert "has_attachments: false" in text and "## Attachments" not in text


def test_marker_in_unique_body_alone_triggers_the_listing(tmp_path):
    m = _message(attachments=False)
    m["uniqueBody"] = {"contentType": "text", "content": f"[cid:{CID1}]"}
    ctx, seen, _ = _ctx(message=m, attachments=ATTS[:1])
    dest = tmp_path / "rec.md"
    mail.export_message(ctx, "m1", str(dest))
    assert "[inline 1: image.png]" in dest.read_text(encoding="utf-8")


def test_record_is_deterministic(tmp_path):
    first, _, _ = export(tmp_path, inline_only())
    (tmp_path / "rec.md").unlink()
    again, _, _ = export(tmp_path, inline_only())
    assert first == again


def test_docstring_no_longer_calls_inline_images_a_blind_spot():
    assert "BLIND SPOT" not in mail.export_message.__doc__


# --- bulk export saves the inline bytes ---------------------------------------

def test_bulk_saves_inline_images_under_numbered_names(tmp_path, monkeypatch):
    from ckm365.tools.mail import bulk
    from test_mail_bulk import _ctx as bulk_ctx, by_id

    calls = []

    def fake(ctx, message_id, dest_path, *, attachment_id=None, name=None,
             account=None, mailbox=None):
        calls.append((message_id, dest_path, attachment_id))
        return {"path": dest_path, "bytes": 10}

    monkeypatch.setattr(bulk, "download_attachment", fake)
    ctx, _ = bulk_ctx()
    r = mail.export_messages(ctx, str(tmp_path), message_ids=["m1"],
                             attachments=True)
    stem = by_id(r)["m1"]["name"].removesuffix(".md")
    assert calls == [("m1", str(tmp_path / stem), "a1"),
                     ("m1", str(tmp_path / stem / "inline1-logo.png"), "a2")]
    assert by_id(r)["m1"]["attachments"] == 2

    # a re-run keeps what is there: the inline file is not fetched again
    (tmp_path / stem / "q1.xlsx").write_bytes(b"x")
    (tmp_path / stem / "inline1-logo.png").write_bytes(b"x")
    calls.clear()
    mail.export_messages(ctx, str(tmp_path), message_ids=["m1"],
                         attachments=True)
    assert calls == []
