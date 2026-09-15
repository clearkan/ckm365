"""Offline tests for the compose loop (CKM-42) — no tenant, no network.

seed → revise → attach/remove → verify → discard. What these assert is
exactly what the 2026-08-18 hand-rolled scripts got wrong or nearly wrong:
a revised reply keeps its quoted history AND its signature, the signature
comes from the profile rather than a pasted literal, a draft (and only a
draft) can be thrown away or stripped of a file, and the pre-send check
reports recipients, attachments, the surviving quote and any smart quote
that leaked in. Fixtures are fake ids and *.example addresses throughout.
"""

import base64
import email
import json
import re

import httpx
import pytest

from ckm365.config import ConfigError, Profile, load_profiles
from ckm365.graph import Graph
from ckm365.tools import Ctx, WriteDisabled, mail
from ckm365.tools.mail.common import (BODY_MARK, SIGNATURE_MARK, fence,
                                      fence_open)

MAILBOX = "user@tenant-a.example"
SIGNATURE = ('<p><b>Ops</b></p><p><a href="https://example.invalid">example</a></p>')
QUOTE = ('<div id="divRplyFwdMsg"><hr><b>From:</b> other-user@tenant-b.example'
         "<br><b>Subject:</b> Q1 figures</div><p>the original message</p>")


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return MAILBOX


def _ctx(handler, *, write=True, **profile_kw):
    profiles = {"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1",
        default_mailbox=MAILBOX, **profile_kw)}
    ctx = Ctx(profiles=profiles, write_enabled=write)
    ctx.set_graph("tenant-a", Graph(
        FakeAuth(), transport=httpx.MockTransport(handler)))
    return ctx


def _draft(content, *, is_draft=True, **extra):
    return {"id": "d1", "isDraft": is_draft, "@odata.etag": 'W/"1"',
            "subject": "RE: Q1 figures",
            "body": {"contentType": "html", "content": content}, **extra}


def _seeded(body="", signature=""):
    """What Graph's createReply gives back once we have patched into it."""
    inner = (fence(BODY_MARK, body) if body else "") + (
        fence(SIGNATURE_MARK, signature) if signature else "")
    return f"<html><body>{inner}{QUOTE}</body></html>"


def _recorder(responses):
    """Serve a queue of (predicate → response) and record every request."""
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url),
                     request.content.decode() if request.content else ""))
        for match, response in responses:
            if match(request):
                return response(request) if callable(response) else response
        return httpx.Response(200, json={})

    return handler, seen


# --- signatures (profiles.toml, applied at creation) -----------------------

def test_signature_html_parsed_and_capped(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text('[profiles.a]\ntenant_id = "t"\nclient_id = "c"\n'
                    "signature_html = '''<p>Ops</p>'''\n"
                    '[profiles.b]\ntenant_id = "t"\nclient_id = "c"\n')
    profiles = load_profiles(path)
    assert profiles["a"].signature_html == "<p>Ops</p>"
    assert profiles["b"].signature_html is None  # absent, not empty
    path.write_text('[profiles.a]\ntenant_id = "t"\nclient_id = "c"\n'
                    f'signature_html = "{"x" * 9000}"\n')
    with pytest.raises(ConfigError, match="signature_html"):
        load_profiles(path)


def test_create_reply_draft_seeds_then_fences_body_and_signature():
    """The whole point of seeding: Graph's quoted history must survive our
    PATCH, and our two regions must come back findable."""
    handler, seen = _recorder([
        (lambda r: r.method == "POST",
         httpx.Response(201, json={"id": "d1", "isDraft": True})),
        (lambda r: r.method == "GET",
         httpx.Response(200, json=_draft(f"<html><body>{QUOTE}</body></html>"))),
        (lambda r: r.method == "PATCH",
         lambda r: httpx.Response(200, json=_draft(
             json.loads(r.content)["body"]["content"]))),
    ])
    ctx = _ctx(handler, signature_html=SIGNATURE)
    draft = mail.create_reply_draft(ctx, "m1", "<p>Hello</p>", reply_all=True)
    assert seen[0][1].endswith("/messages/m1/createReplyAll")
    patched = json.loads(seen[2][2])["body"]["content"]
    assert patched == ("<html><body>"
                       + fence(BODY_MARK, "<p>Hello</p>")
                       + fence(SIGNATURE_MARK, SIGNATURE)
                       + f"{QUOTE}</body></html>")
    assert "<!--" not in patched  # CKM-48: Exchange strips in-body comments
    assert draft.body.content == patched


def test_signature_can_be_declined_per_call():
    handler, seen = _recorder([
        (lambda r: r.method == "POST",
         httpx.Response(201, json={"id": "d1", "isDraft": True})),
        (lambda r: r.method == "GET",
         httpx.Response(200, json=_draft("<html><body></body></html>"))),
        (lambda r: r.method == "PATCH", httpx.Response(200, json=_draft(""))),
    ])
    ctx = _ctx(handler, signature_html=SIGNATURE)
    mail.create_reply_draft(ctx, "m1", "<p>Hi</p>", signature=False)
    assert SIGNATURE not in json.loads(seen[2][2])["body"]["content"]


def test_create_draft_fences_body_and_appends_signature():
    handler, seen = _recorder(
        [(lambda r: True, httpx.Response(201, json={"id": "d1",
                                                    "isDraft": True}))])
    ctx = _ctx(handler, signature_html=SIGNATURE)
    mail.create_draft(ctx, to=["other-user@tenant-b.example"], subject="s",
                      body_html="<p>Hi</p>")
    content = json.loads(seen[0][2])["body"]["content"]
    assert content == (fence(BODY_MARK, "<p>Hi</p>")
                       + fence(SIGNATURE_MARK, SIGNATURE))
    assert "<!--" not in content  # CKM-48: Exchange strips in-body comments


def test_caller_html_may_not_forge_the_fence():
    ctx = _ctx(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="compose markers"):
        mail.create_draft(ctx, to=["a@tenant-b.example"], subject="s",
                          body_html=f'<div id="{BODY_MARK}-start"></div>sneaky')
    with pytest.raises(ValueError, match="compose markers"):
        mail.revise_draft(ctx, "d1", f"<div id='{BODY_MARK}-end'></div>")


# --- create_persona_reply (CKM-45) -----------------------------------------

ORIGINAL = {
    "id": "m1", "subject": "Q1 figures",
    "from": {"emailAddress": {"name": "Other", "address": "other-user@tenant-b.example"}},
    "toRecipients": [{"emailAddress": {"address": MAILBOX}},
                     {"emailAddress": {"address": "colleague@tenant-b.example"}}],
    "ccRecipients": [{"emailAddress": {"address": "agent@tenant-a.example"}}],
    "receivedDateTime": "2026-09-01T10:00:00Z",
    "internetMessageId": "<parent@their.host>",
    "internetMessageHeaders": [{"name": "References", "value": "<older@their.host>"}],
    "body": {"contentType": "html", "content": "<p>the original</p>"},
}


def _persona_ctx():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=ORIGINAL)
        return httpx.Response(201, json={"id": "p1", "isDraft": True})
    return _recorder([(lambda r: True, handler)])


def _imported(seen):
    """The RFC-5322 message that actually went to Graph."""
    post = [c for m, _, c in seen if m == "POST"][-1]
    return email.message_from_bytes(base64.b64decode(post))


def test_create_persona_reply_imports_threaded_mime_into_the_persona_drafts():
    """CKM-45: the ONLY route that keeps authorship AND threading. Graph sets
    from= to the signed-in user on a JSON draft, and refuses In-Reply-To on a
    PATCH entirely — but preserves both when the message arrives as MIME."""
    handler, seen = _persona_ctx()
    draft = mail.create_persona_reply(
        _ctx(handler), "m1", as_mailbox="agent@tenant-a.example",
        body_html="<p>our answer</p>")
    assert draft.id == "p1"

    method, url, _ = [row for row in seen if row[0] == "POST"][-1]
    assert url.endswith("/users/agent%40tenant-a.example/"
                        "mailFolders/drafts/messages")

    msg = _imported(seen)
    assert msg["From"] == "agent@tenant-a.example"      # the PERSONA, not us
    assert msg["To"] == "other-user@tenant-b.example"
    assert msg["In-Reply-To"] == "<parent@their.host>"
    assert msg["References"] == "<older@their.host> <parent@their.host>"
    assert msg["Subject"] == "RE: Q1 figures"


def test_create_persona_reply_encodes_base64_never_quoted_printable():
    """QP soft line breaks come back through Exchange mangled, silently
    eating a character mid-word. Invisible in a draft listing."""
    handler, seen = _persona_ctx()
    mail.create_persona_reply(_ctx(handler), "m1",
                              as_mailbox="agent@tenant-a.example",
                              body_html="<p>our answer</p>")
    parts = _imported(seen).walk()
    encodings = {p.get("Content-Transfer-Encoding") for p in parts
                 if p.get("Content-Transfer-Encoding")}
    assert encodings == {"base64"}


def test_create_persona_reply_keeps_the_persona_off_its_own_reply_all():
    handler, seen = _persona_ctx()
    mail.create_persona_reply(_ctx(handler), "m1",
                              as_mailbox="agent@tenant-a.example",
                              body_html="<p>x</p>", reply_all=True)
    msg = _imported(seen)
    assert "agent@tenant-a.example" not in (msg["To"] or "")
    assert "agent@tenant-a.example" not in (msg["Cc"] or "")   # it was on cc
    assert MAILBOX in msg["To"] and "colleague@tenant-b.example" in msg["To"]


def test_create_persona_reply_fences_our_text_and_quotes_the_original():
    handler, seen = _persona_ctx()
    mail.create_persona_reply(_ctx(handler), "m1",
                              as_mailbox="agent@tenant-a.example",
                              body_html="<p>our answer</p>")
    html = [p for p in _imported(seen).walk()
            if p.get_content_type() == "text/html"][0]
    body = html.get_payload(decode=True).decode()
    assert fence(BODY_MARK, "<p>our answer</p>") in body   # revise_draft works
    assert "the original" in body and "divRplyFwdMsg" in body


def test_create_persona_reply_is_write_tier():
    with pytest.raises(WriteDisabled):
        mail.create_persona_reply(
            _ctx(lambda r: httpx.Response(200, json={}), write=False), "m1",
            as_mailbox="agent@tenant-a.example", body_html="<p>x</p>")


# --- revise_draft ----------------------------------------------------------

def test_revise_draft_replaces_only_our_text():
    """The 2026-08-18 failure mode: a second draft that keeps the quoted
    thread and the signature instead of flattening them."""
    handler, seen = _recorder([
        (lambda r: r.method == "GET",
         httpx.Response(200, json=_draft(_seeded("<p>first</p>", SIGNATURE)))),
        (lambda r: r.method == "PATCH",
         lambda r: httpx.Response(200, json=_draft(
             json.loads(r.content)["body"]["content"]))),
    ])
    ctx = _ctx(handler)
    draft = mail.revise_draft(ctx, "d1", "<p>second</p>")
    assert draft.body.content == _seeded("<p>second</p>", SIGNATURE)
    assert "first" not in draft.body.content
    assert QUOTE in draft.body.content and SIGNATURE in draft.body.content
    assert [method for method, _, _ in seen] == ["GET", "PATCH"]  # one round trip


def test_revise_draft_sends_if_match_from_the_etag_it_read():
    etag_seen = {}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=_draft(_seeded("<p>a</p>")))
        etag_seen["if-match"] = request.headers.get("if-match")
        return httpx.Response(200, json=_draft(_seeded("<p>b</p>")))

    mail.revise_draft(_ctx(handler), "d1", "<p>b</p>")
    assert etag_seen["if-match"] == 'W/"1"'


def _unfenced_draft():
    return _recorder([
        (lambda r: r.method == "GET",
         httpx.Response(200, json=_draft(
             f"<html><body><p>typed by hand</p>{QUOTE}</body></html>"))),
        (lambda r: r.method == "PATCH",
         lambda r: httpx.Response(200, json=_draft(
             json.loads(r.content)["body"]["content"]))),
    ])


def test_revise_draft_refuses_an_unfenced_draft_by_default():
    """CKM-48: the silent insert put TWO complete versions of a message in a
    client-facing draft. Refusing is recoverable; a duplicated body is not."""
    handler, seen = _unfenced_draft()
    with pytest.raises(ValueError, match="no ckm365 compose fence"):
        mail.revise_draft(_ctx(handler), "d1", "<p>added</p>")
    assert [method for method, _, _ in seen] == ["GET"]  # nothing was written


def test_revise_draft_inserts_at_the_top_when_asked():
    """A draft written in Outlook has no fence: opt in, and it is inserted
    inside <body> (so the quote below is untouched) and fenced, so the NEXT
    revision replaces."""
    handler, seen = _unfenced_draft()
    draft = mail.revise_draft(_ctx(handler), "d1", "<p>added</p>",
                              insert_if_unfenced=True)
    assert draft.body.content == (
        "<html><body>" + fence(BODY_MARK, "<p>added</p>")
        + f"<p>typed by hand</p>{QUOTE}</body></html>")


def test_compose_loop_survives_a_graph_that_strips_html_comments():
    """THE CKM-48 REGRESSION TEST — and the reason offline mocks missed it.

    Exchange deletes every comment inside <body> when it stores a body
    (measured on both tenants, 2026-09-15: comments and conditional
    comments vanish; an id, a class or a data- attribute on a real element
    survives verbatim). The fence used to BE a comment pair, so it never
    survived being written: revise_draft found nothing to replace and
    prepended instead, silently, on every draft ckm365 had ever composed.

    Every other mock in this file echoes the PATCHed body back unchanged,
    which is precisely why 153 green tests could not see it. This one
    models the store, so a fence that cannot survive real Graph fails here.
    """
    stored = {"content": f"<html><body>{QUOTE}</body></html>"}

    def handler(request):
        if request.method == "POST":
            return httpx.Response(201, json={"id": "d1", "isDraft": True})
        if "/attachments" in str(request.url):
            return httpx.Response(200, json={"value": []})
        if request.method == "PATCH":
            body = json.loads(request.content)["body"]["content"]
            stored["content"] = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        return httpx.Response(200, json=_draft(stored["content"]))

    ctx = _ctx(handler, signature_html=SIGNATURE)
    mail.create_reply_draft(ctx, "m1", "<p>first</p>")
    assert fence_open(BODY_MARK) in stored["content"]  # the fence was kept

    mail.revise_draft(ctx, "d1", "<p>second</p>")
    assert "first" not in stored["content"]        # replaced, NOT prepended
    assert stored["content"].count(fence_open(BODY_MARK)) == 1
    assert QUOTE in stored["content"] and SIGNATURE in stored["content"]
    assert mail.verify_message(ctx, "d1")["boundary"] == "fence"
    assert mail.verify_message(ctx, "d1")["signature"] is True


def test_revise_draft_refuses_non_drafts_and_needs_write():
    with pytest.raises(WriteDisabled):
        mail.revise_draft(_ctx(lambda r: httpx.Response(200, json={}),
                               write=False), "d1", "<p>x</p>")

    def handler(request):
        return httpx.Response(200, json=_draft("<p>sent</p>", is_draft=False))

    with pytest.raises(ValueError, match="non-draft"):
        mail.revise_draft(_ctx(handler), "m1", "<p>x</p>")


# --- discard_draft ---------------------------------------------------------

def test_discard_draft_deletes_only_drafts():
    handler, seen = _recorder([
        (lambda r: r.method == "GET", httpx.Response(200, json=_draft("<p>x</p>"))),
        (lambda r: r.method == "DELETE", httpx.Response(204)),
    ])
    ctx = _ctx(handler)
    assert mail.discard_draft(ctx, "d1") == {"discarded": True,
                                             "message_id": "d1"}
    assert seen[1][0] == "DELETE"
    assert seen[1][1].endswith("/users/user%40tenant-a.example/messages/d1")

    def delivered(request):
        return httpx.Response(200, json=_draft("<p>x</p>", is_draft=False))

    with pytest.raises(ValueError, match="non-draft"):
        mail.discard_draft(_ctx(delivered), "m1")
    with pytest.raises(WriteDisabled):
        mail.discard_draft(_ctx(handler, write=False), "d1")


# --- remove_attachment -----------------------------------------------------

def _attachments(*items):
    return {"value": [{"id": i, "name": n, "size": s, "isInline": inline,
                       "contentType": "text/plain",
                       "@odata.type": "#microsoft.graph.fileAttachment"}
                      for i, n, s, inline in items]}


def test_remove_attachment_deletes_the_named_file_off_a_draft():
    handler, seen = _recorder([
        (lambda r: r.url.path.endswith("/attachments"),
         httpx.Response(200, json=_attachments(("a1", "old.html", 900, False),
                                               ("a2", "logo.png", 40, True)))),
        (lambda r: r.method == "GET", httpx.Response(200, json=_draft("<p>x</p>"))),
        (lambda r: r.method == "DELETE", httpx.Response(204)),
    ])
    ctx = _ctx(handler)
    result = mail.remove_attachment(ctx, "d1", name="old.html")
    assert result == {"removed": True, "message_id": "d1", "attachment_id": "a1",
                      "name": "old.html", "size": 900, "is_inline": False}
    assert seen[-1][0] == "DELETE" and seen[-1][1].endswith("/attachments/a1")


def test_remove_attachment_refuses_ambiguous_names_and_non_drafts():
    handler, _ = _recorder([
        (lambda r: r.url.path.endswith("/attachments"),
         httpx.Response(200, json=_attachments(("a1", "same.pdf", 10, False),
                                               ("a2", "same.pdf", 20, False)))),
        (lambda r: r.method == "GET", httpx.Response(200, json=_draft("<p>x</p>"))),
    ])
    ctx = _ctx(handler)
    with pytest.raises(ValueError, match="share that name"):
        mail.remove_attachment(ctx, "d1", name="same.pdf")
    with pytest.raises(ValueError, match="no attachment with that id"):
        mail.remove_attachment(ctx, "d1", attachment_id="nope")
    with pytest.raises(ValueError, match="attachment_id"):
        mail.remove_attachment(ctx, "d1")

    def delivered(request):
        return httpx.Response(200, json=_draft("<p>x</p>", is_draft=False))

    with pytest.raises(ValueError, match="non-draft"):
        mail.remove_attachment(_ctx(delivered), "m1", name="x")
    with pytest.raises(WriteDisabled):
        mail.remove_attachment(_ctx(handler, write=False), "d1", name="x")


def test_remove_attachment_can_take_off_a_non_file_attachment():
    """Unlike downloading, removal does not need bytes: an itemAttachment
    attached in error must be removable."""
    handler, seen = _recorder([
        (lambda r: r.url.path.endswith("/attachments"),
         httpx.Response(200, json={"value": [
             {"id": "a1", "name": "fwd.eml", "size": 100, "isInline": False,
              "@odata.type": "#microsoft.graph.itemAttachment"}]})),
        (lambda r: r.method == "GET", httpx.Response(200, json=_draft("<p>x</p>"))),
        (lambda r: r.method == "DELETE", httpx.Response(204)),
    ])
    assert mail.remove_attachment(_ctx(handler), "d1",
                                  name="fwd.eml")["removed"] is True


# --- verify_message --------------------------------------------------------

def _verify_ctx(content, *, attachments=(), is_draft=True, **extra):
    def handler(request):
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json=_attachments(*attachments))
        return httpx.Response(200, json=_draft(
            content, is_draft=is_draft,
            toRecipients=[{"emailAddress": {"address": "other-user@tenant-b.example"}}],
            ccRecipients=[{"emailAddress": {"address": "colleague@tenant-a.example"}}],
            **extra))

    return _ctx(handler, write=False)


def test_verify_message_reports_the_assertions_the_scripts_re_derived():
    ctx = _verify_ctx(_seeded("<p>Hi ’there’ — ok</p>", SIGNATURE),
                      attachments=(("a1", "report.pdf", 1200, False),))
    result = mail.verify_message(ctx, "d1")
    assert result["to"] == ["other-user@tenant-b.example"]
    assert result["cc"] == ["colleague@tenant-a.example"]
    assert result["recipients"] == 2
    assert result["attachments"] == [{"attachment_id": "a1",
                                      "name": "report.pdf", "size": 1200,
                                      "kind": "fileAttachment",
                                      "is_inline": False}]
    assert result["quoted_thread"] is True
    assert result["signature"] is True
    assert result["boundary"] == "fence"
    assert result["text"] == "Hi ’there’ — ok"
    assert result["non_ascii"] == [
        {"char": "—", "codepoint": "U+2014", "count": 1},
        {"char": "’", "codepoint": "U+2019", "count": 2}]
    assert result["is_draft"] is True and result["mailbox"] == MAILBOX


def test_verify_message_scans_only_the_text_we_wrote():
    """The quoted thread is someone else's prose — its punctuation is not a
    finding, and neither is the signature's."""
    ctx = _verify_ctx(_seeded("<p>plain ascii</p>",
                              "<p>Ops — example</p>")
                      .replace("the original message",
                               "their “quoted” words"))
    result = mail.verify_message(ctx, "d1")
    assert result["non_ascii"] == []
    assert result["text"] == "plain ascii"


def test_verify_message_lists_attachments_even_when_graph_says_none():
    """hasAttachments is false for a message whose only attachments are
    inline, so the listing is never skipped on the strength of the flag."""
    ctx = _verify_ctx(_seeded("<p>x</p>"), hasAttachments=False,
                      attachments=(("a1", "logo.png", 40, True),))
    result = mail.verify_message(ctx, "d1")
    assert result["attachments"] == [{"attachment_id": "a1",
                                      "name": "logo.png", "size": 40,
                                      "kind": "fileAttachment",
                                      "is_inline": True}]


def test_verify_message_says_when_the_boundary_was_guessed():
    ctx = _verify_ctx(f"<html><body><p>typed by hand</p>{QUOTE}</body></html>")
    result = mail.verify_message(ctx, "d1")
    assert result["boundary"] == "quote"
    assert result["text"] == "typed by hand"
    assert result["quoted_thread"] is True and result["signature"] is False

    bare = mail.verify_message(_verify_ctx("<p>no quote at all</p>"), "d1")
    assert bare["boundary"] == "whole-body"
    assert bare["quoted_thread"] is False


def test_verify_message_sees_a_plain_text_original_s_quote():
    """Graph seeds a reply to a PLAIN-TEXT original with none of the usual
    markers — no divRplyFwdMsg, no <hr>, no blockquote — just
    <div class="PlainText">. Found live 2026-09-15: quoted_thread read False
    on a draft whose quote was perfectly intact, which is a false negative
    on a pre-send check."""
    plain = ('<html><body><div class="PlainText">'
             "From: other-user@tenant-b.example<br>Q1 figures<br>"
             "</div></body></html>")
    result = mail.verify_message(_verify_ctx(plain), "d1")
    assert result["quoted_thread"] is True
    assert result["boundary"] == "quote"


def test_verify_message_caps_the_text_it_returns():
    long_text = "<p>" + ("word " * 2000) + "</p>"
    result = mail.verify_message(_verify_ctx(_seeded(long_text)), "d1")
    assert result["text_truncated"] is True
    assert len(result["text"]) == 4000
    assert result["text_chars"] > 4000


def test_verify_message_is_read_tier():
    """No --write: the compose loop's check must work in a read-only
    session, and on the SENT copy after the draft is gone."""
    ctx = _verify_ctx(_seeded("<p>gone out</p>", SIGNATURE), is_draft=False)
    result = mail.verify_message(ctx, "s1")
    assert result["is_draft"] is False
    assert ctx.write_enabled is False
