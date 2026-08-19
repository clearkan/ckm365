"""Offline tests for the compose loop (CKM-42) — no tenant, no network.

seed → revise → attach/remove → verify → discard. What these assert is
exactly what the 2026-08-18 hand-rolled scripts got wrong or nearly wrong:
a revised reply keeps its quoted history AND its signature, the signature
comes from the profile rather than a pasted literal, a draft (and only a
draft) can be thrown away or stripped of a file, and the pre-send check
reports recipients, attachments, the surviving quote and any smart quote
that leaked in. Fixtures are fake ids and *.example addresses throughout.
"""

import json

import httpx
import pytest

from ckm365.config import ConfigError, Profile, load_profiles
from ckm365.graph import Graph
from ckm365.tools import Ctx, WriteDisabled, mail
from ckm365.tools.mail.common import BODY_MARK, SIGNATURE_MARK, fence

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
                       f"<!--{BODY_MARK}--><p>Hello</p><!--/{BODY_MARK}-->"
                       f"<!--{SIGNATURE_MARK}-->{SIGNATURE}"
                       f"<!--/{SIGNATURE_MARK}-->{QUOTE}</body></html>")
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
    assert content == (f"<!--{BODY_MARK}--><p>Hi</p><!--/{BODY_MARK}-->"
                       f"<!--{SIGNATURE_MARK}-->{SIGNATURE}"
                       f"<!--/{SIGNATURE_MARK}-->")


def test_caller_html_may_not_forge_the_fence():
    ctx = _ctx(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="compose markers"):
        mail.create_draft(ctx, to=["a@tenant-b.example"], subject="s",
                          body_html=f"<!--{BODY_MARK}-->sneaky")
    with pytest.raises(ValueError, match="compose markers"):
        mail.revise_draft(ctx, "d1", f"<!--/{BODY_MARK}-->")


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


def test_revise_draft_on_an_unfenced_draft_inserts_at_the_top():
    """A draft written in Outlook has no fence: insert inside <body> (so the
    quote below is untouched) and fence it, so the NEXT revision replaces."""
    handler, seen = _recorder([
        (lambda r: r.method == "GET",
         httpx.Response(200, json=_draft(
             f"<html><body><p>typed by hand</p>{QUOTE}</body></html>"))),
        (lambda r: r.method == "PATCH",
         lambda r: httpx.Response(200, json=_draft(
             json.loads(r.content)["body"]["content"]))),
    ])
    draft = mail.revise_draft(_ctx(handler), "d1", "<p>added</p>")
    assert draft.body.content == (
        f"<html><body><!--{BODY_MARK}--><p>added</p><!--/{BODY_MARK}-->"
        f"<p>typed by hand</p>{QUOTE}</body></html>")


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
