"""Offline spec for CKM-49 (tvtrb0): records that know their thread and
store each message's new text once.

Measured live, read-only, on two tenants (2026-11-06), on recent replies:
every one carried In-Reply-To; References held up to 23 ids in 1,850
characters (the 200-character header cap would have cut it to two);
`uniqueBody`, Graph's server-side "new text only", came back as text
under the same Prefer header as `body`, and on a long thread was 14
characters against 54,859 for the full quoted chain. conversationId was
80 characters everywhere.

So, per the issue:
1. Message carries conversation_id and conversation_index (cheap, on
   Message.SELECT) and unique_body (NOT on Message.SELECT: get_message
   would double its payload; export asks for it explicitly).
2. MessageHeaders carries in_reply_to and references. References is
   tokenised by angle-bracket id instead of capped as one string.
3. The record's body is uniqueBody by default, `body_scope: "unique"`;
   `full_body=True`, or a message whose uniqueBody is empty, gives the
   full body and `body_scope: "full"`. The .eml stays the complete chain.
4. `resource` is `mid:<id>` (RFC 2392), a mailbox-independent name for
   the message; webLink moves to a `web_link` extension key.
5. `type: "Message"` plus `channel: "email"`, so chat records can share
   the shape.

Skipped as a module until Message has conversation_id.
"""

from dataclasses import fields

import pytest

from ckm365.models import Message, MessageHeaders

if "conversation_id" not in {f.name for f in fields(Message)}:
    pytest.skip("CKM-49 threading not built yet (tvtrb0)", allow_module_level=True)

from ckm365.tools import mail  # noqa: E402
from test_mail_export import BODY, _ctx, _message  # noqa: E402

UNIQUE = "Thanks, figures received."
CONV = "AAQkAD" + "x" * 74                     # 80 characters, like Graph's
REFS = [f"<r{i}.thread@tenant-b.example>" for i in range(23)]


def threaded(**over):
    m = _message()
    m.update({"conversationId": CONV, "conversationIndex": "AQHZ" + "y" * 28,
              "uniqueBody": {"contentType": "text", "content": UNIQUE},
              "internetMessageHeaders": [
                  {"name": "List-Id", "value": "<news.example>"},
                  {"name": "In-Reply-To", "value": REFS[-1]},
                  {"name": "References", "value": " ".join(REFS)}]})
    m.update(over)
    return m


def front(text):
    """Front matter as an ordered list of (key, raw value) pairs."""
    head = text.partition("\n---\n")[0].splitlines()[1:]
    return [tuple(line.split(": ", 1)) for line in head]


def export(tmp_path, message=None, **kw):
    ctx, seen, prefer = _ctx(message=message or threaded())
    dest = tmp_path / "rec.md"
    mail.export_message(ctx, "m1", str(dest), **kw)
    return dest.read_text(encoding="utf-8"), seen, prefer


# --- models -----------------------------------------------------------------

def test_message_select_has_the_thread_ids_but_not_unique_body():
    assert "conversationId" in Message.SELECT.split(",")
    assert "conversationIndex" in Message.SELECT.split(",")
    assert "uniqueBody" not in Message.SELECT


def test_message_reads_the_thread_fields():
    m = Message.from_graph(threaded())
    assert m.conversation_id == CONV
    assert m.conversation_index.startswith("AQHZ")
    assert m.unique_body.content == UNIQUE
    assert Message.from_graph(_message()).unique_body is None
    assert Message.from_graph(_message()).conversation_id is None


def test_in_reply_to_is_a_curated_header():
    h = MessageHeaders.from_graph(threaded())
    assert h.in_reply_to == REFS[-1]


def test_references_keeps_every_id_past_the_old_cap():
    h = MessageHeaders.from_graph(threaded())
    assert h.references == REFS                       # 23 ids, ~690 characters
    assert MessageHeaders.from_graph(_message()).references == []


def test_references_is_tokenised_and_sanitised():
    raw = "junk <a@x.example>\r\n\t<b@x.example> <c\x00@x.example> <" + "z" * 300 + "@x>"
    h = MessageHeaders.from_graph({"internetMessageHeaders": [
        {"name": "References", "value": raw}]})
    assert h.references == ["<a@x.example>", "<b@x.example>", "<c@x.example>"]


def test_references_keeps_the_newest_hundred():
    ids = [f"<n{i}@x.example>" for i in range(150)]
    h = MessageHeaders.from_graph({"internetMessageHeaders": [
        {"name": "References", "value": " ".join(ids)}]})
    assert h.references == ids[-100:]


# --- the record -------------------------------------------------------------

def test_record_front_matter_keys_and_order(tmp_path):
    text, _, _ = export(tmp_path)
    assert [k for k, _ in front(text)] == [
        "type", "channel", "title", "description", "resource", "tags",
        "generated", "from", "to", "cc", "mailbox", "message_id",
        "internet_message_id", "conversation_id", "in_reply_to", "references",
        "web_link", "body_scope", "has_attachments", "is_bulk", "is_auto_reply"]


def test_record_is_a_message_on_the_email_channel(tmp_path):
    kv = dict(front(export(tmp_path)[0]))
    assert kv["type"] == '"Message"' and kv["channel"] == '"email"'


def test_resource_is_the_mid_uri_and_weblink_moves(tmp_path):
    kv = dict(front(export(tmp_path)[0]))
    assert kv["resource"] == '"mid:abc123@tenant-b.example"'
    assert kv["web_link"] == '"https://outlook.office365.com/mail/deeplink/m1"'


def test_mid_is_percent_encoded():
    from ckm365.tools.mail.export import mid_uri
    assert mid_uri("<a b%c@x.example>") == "mid:a%20b%25c@x.example"
    assert mid_uri("plain@x.example") == "mid:plain@x.example"
    assert mid_uri(None) is None and mid_uri("<>") is None


def test_a_message_without_a_message_id_falls_back_to_web_link(tmp_path):
    kv = dict(front(export(tmp_path, threaded(internetMessageId=None))[0]))
    assert kv["resource"] == '"https://outlook.office365.com/mail/deeplink/m1"'


def test_thread_keys_carry_the_headers(tmp_path):
    kv = dict(front(export(tmp_path)[0]))
    assert kv["conversation_id"] == f'"{CONV}"'
    assert kv["in_reply_to"] == f'"{REFS[-1]}"'
    assert kv["references"] == "[" + ", ".join(f'"{r}"' for r in REFS) + "]"


def test_a_new_thread_has_empty_thread_keys(tmp_path):
    m = threaded(internetMessageHeaders=[], conversationId=None)
    kv = dict(front(export(tmp_path, m)[0]))
    assert kv["in_reply_to"] == '""' and kv["references"] == "[]"
    assert kv["conversation_id"] == '""'


def test_body_is_the_unique_text_by_default(tmp_path):
    text, seen, prefer = export(tmp_path)
    body = text.partition("\n---\n")[2]
    assert UNIQUE in body and BODY not in body
    assert dict(front(text))["body_scope"] == '"unique"'
    assert any("uniqueBody" in u for u in seen)          # asked for explicitly
    assert set(prefer) == {'outlook.body-content-type="text"'}


def test_full_body_is_an_opt_in(tmp_path):
    text, seen, _ = export(tmp_path, full_body=True)
    body = text.partition("\n---\n")[2]
    assert BODY in body and UNIQUE not in body
    assert dict(front(text))["body_scope"] == '"full"'
    assert not any("uniqueBody" in u for u in seen)


@pytest.mark.parametrize("unique", [None, {"contentType": "text", "content": "  \n"}])
def test_an_empty_unique_body_falls_back_to_full(tmp_path, unique):
    text, _, _ = export(tmp_path, threaded(uniqueBody=unique))
    assert BODY in text.partition("\n---\n")[2]
    assert dict(front(text))["body_scope"] == '"full"'


def test_the_record_is_still_deterministic(tmp_path):
    a, _, _ = export(tmp_path)
    (tmp_path / "rec.md").unlink()
    b, _, _ = export(tmp_path)
    assert a == b


def test_eml_export_is_unchanged(tmp_path):
    ctx, seen, _ = _ctx(message=threaded())
    dest = tmp_path / "rec.eml"
    mail.export_message(ctx, "m1", str(dest))
    assert not any("uniqueBody" in u for u in seen)


def test_export_docstring_teaches_body_scope():
    doc = mail.export_message.__doc__
    assert "full_body" in doc and "uniqueBody" in doc and "mid:" in doc
