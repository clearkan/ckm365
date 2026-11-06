"""Offline spec for tc3vj9: composed paragraphs carry the mailbox's font.

Observed on a client mailbox: a reply draft built from bare `<p>`
paragraphs renders in the HTML default face (Times) above a quoted
history in Calibri 11pt. Outlook does not cascade a wrapper's style into
paragraphs; when it re-saves a message it puts a styled span inside EVERY
paragraph. So the fix applies the font per paragraph, the way Outlook
does.

Design:
- OPT-IN PER PROFILE. ckm365 cannot read a mailbox's default font (that
  needs MailboxSettings.Read, a scope it never asks for), and mailboxes
  differ (Calibri 11pt on older tenants, Aptos 12pt on newer ones). So
  a profile sets `compose_font` (e.g. "Calibri,sans-serif") and
  optionally `compose_size` (default "11pt"). Without `compose_font`
  every body is byte-identical to before.
- `style_paragraphs(html, font, size)` in tools/mail/common.py: every
  `<p ...>...</p>` whose tag and content mention no `font-family` gets
  its content wrapped in
  `<span style="font-size:<size>;font-family:<font>">`, and a bare `<p>`
  (no attributes) also gets `style="margin:0 0 12pt 0"`, matching
  Outlook's own paragraph spacing. A `<p>` with attributes keeps them
  unchanged. Paragraphs that already name a font, empty paragraphs, and
  everything outside `<p>` are left alone.
- Applied to the CALLER's text in create_reply_draft, create_forward_draft,
  create_draft, revise_draft and create_persona_reply. Never to the
  signature (the operator wrote that HTML deliberately) and never by
  update_draft, which replaces a whole body verbatim.

Rendering still needs a human check in Outlook desktop and OWA; see the
issue's verification steps.

Skipped as a module until common.style_paragraphs exists.
"""

import json

import httpx
import pytest

from ckm365.tools.mail import common

if not hasattr(common, "style_paragraphs"):
    pytest.skip("compose font not built yet (tc3vj9)", allow_module_level=True)

from ckm365.config import ConfigError, Profile, load_profiles  # noqa: E402
from ckm365.tools import mail  # noqa: E402
from ckm365.tools.mail.common import (BODY_MARK, SIGNATURE_MARK,  # noqa: E402
                                      fence, style_paragraphs)
from test_mail_compose import (QUOTE, SIGNATURE, _ctx, _draft,  # noqa: E402
                               _persona_ctx, _imported, _recorder, _seeded)

FONT = "Calibri,sans-serif"
SPAN = '<span style="font-size:11pt;font-family:Calibri,sans-serif">'


def styled(text):
    return f'<p style="margin:0 0 12pt 0">{SPAN}{text}</span></p>'


# --- the transform ---------------------------------------------------------------

def test_bare_paragraphs_get_margin_and_font():
    assert style_paragraphs("<p>Hello</p><p>Second</p>", FONT, "11pt") == (
        styled("Hello") + styled("Second"))


def test_size_and_font_come_from_the_arguments():
    out = style_paragraphs("<p>x</p>", "Aptos,sans-serif", "12pt")
    assert out == ('<p style="margin:0 0 12pt 0"><span style="font-size:12pt;'
                   'font-family:Aptos,sans-serif">x</span></p>')


def test_tag_match_is_case_insensitive_and_spans_lines():
    assert style_paragraphs("<P>a\nb</P>", FONT, "11pt") == (
        f'<P style="margin:0 0 12pt 0">{SPAN}a\nb</span></P>')


def test_paragraph_with_attributes_keeps_them():
    assert style_paragraphs('<p class="x" style="color:red">Hi</p>', FONT, "11pt") == (
        f'<p class="x" style="color:red">{SPAN}Hi</span></p>')


@pytest.mark.parametrize("html", [
    '<p style="font-family:Arial">Hi</p>',
    '<p><span style="font-family: Georgia">Hi</span></p>',
    "<p></p>",
    "<p>  </p>",
    "<pre>code</pre>",
    '<param name="p">',
    "plain text, no paragraph",
    "<div>block</div>",
])
def test_left_alone(html):
    assert style_paragraphs(html, FONT, "11pt") == html


def test_mixed_body_touches_only_unstyled_paragraphs():
    html = ('<p>one</p><ul><li>item</li></ul>'
            '<p style="font-family:Arial">two</p><p>three</p>')
    assert style_paragraphs(html, FONT, "11pt") == (
        styled("one") + "<ul><li>item</li></ul>"
        '<p style="font-family:Arial">two</p>' + styled("three"))


def test_idempotent():
    once = style_paragraphs("<p>a</p><p>b</p>", FONT, "11pt")
    assert style_paragraphs(once, FONT, "11pt") == once


# --- the profile -------------------------------------------------------------------

def _profile(**kw):
    return Profile(name="p", tenant_id="t1", client_id="c1", **kw)


def test_profile_defaults_to_off():
    p = _profile()
    assert p.compose_font is None and p.compose_size == "11pt"


@pytest.mark.parametrize("kw", [
    {"compose_font": ""},
    {"compose_font": 'Calibri"; color:red'},      # would break out of style=""
    {"compose_font": "Calibri<script>"},
    {"compose_font": "x" * 101},
    {"compose_font": 12},
    {"compose_font": FONT, "compose_size": "11"},
    {"compose_font": FONT, "compose_size": "11px;color:red"},
    {"compose_font": FONT, "compose_size": "100pt"},
])
def test_profile_rejects_unsafe_values(kw):
    with pytest.raises(ConfigError):
        _profile(**kw)


def test_profile_accepts_real_font_stacks():
    assert _profile(compose_font="'Segoe UI',Calibri,sans-serif",
                    compose_size="10.5pt").compose_size == "10.5pt"


def test_profiles_toml_keys(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text('[profiles.p]\ntenant_id = "t1"\nclient_id = "c1"\n'
                    'compose_font = "Aptos,sans-serif"\ncompose_size = "12pt"\n')
    p = load_profiles(path)["p"]
    assert (p.compose_font, p.compose_size) == ("Aptos,sans-serif", "12pt")


# --- where it is applied ------------------------------------------------------------

def _reply_handler():
    return _recorder([
        (lambda r: r.method == "POST",
         httpx.Response(201, json={"id": "d1", "isDraft": True})),
        (lambda r: r.method == "GET",
         httpx.Response(200, json=_draft(f"<html><body>{QUOTE}</body></html>"))),
        (lambda r: r.method == "PATCH",
         lambda r: httpx.Response(200, json=_draft(
             json.loads(r.content)["body"]["content"]))),
    ])


def _patched(seen):
    return json.loads([s for s in seen if s[0] == "PATCH"][-1][2])["body"]["content"]


def test_reply_and_forward_style_our_text_not_the_signature():
    for call in (lambda c: mail.create_reply_draft(c, "m1", "<p>Hello</p>"),
                 lambda c: mail.create_forward_draft(
                     c, "m1", to=["other-user@tenant-b.example"],
                     body_html="<p>Hello</p>")):
        handler, seen = _reply_handler()
        call(_ctx(handler, signature_html=SIGNATURE, compose_font=FONT))
        body = _patched(seen)
        assert fence(BODY_MARK, styled("Hello")) in body
        assert fence(SIGNATURE_MARK, SIGNATURE) in body   # untouched
        assert QUOTE in body


def test_without_compose_font_bodies_are_unchanged():
    handler, seen = _reply_handler()
    mail.create_reply_draft(_ctx(handler), "m1", "<p>Hello</p>")
    assert fence(BODY_MARK, "<p>Hello</p>") in _patched(seen)


def test_create_draft_styles_body():
    handler, seen = _recorder(
        [(lambda r: True, httpx.Response(201, json={"id": "d1", "isDraft": True}))])
    mail.create_draft(_ctx(handler, compose_font=FONT),
                      to=["other-user@tenant-b.example"], subject="s",
                      body_html="<p>Hi</p>")
    assert json.loads(seen[0][2])["body"]["content"] == fence(BODY_MARK, styled("Hi"))


def test_revise_draft_styles_the_new_text():
    handler, seen = _recorder([
        (lambda r: r.method == "GET",
         httpx.Response(200, json=_draft(_seeded(styled("first"), SIGNATURE)))),
        (lambda r: r.method == "PATCH",
         lambda r: httpx.Response(200, json=_draft(
             json.loads(r.content)["body"]["content"]))),
    ])
    draft = mail.revise_draft(_ctx(handler, compose_font=FONT), "d1", "<p>second</p>")
    assert draft.body.content == _seeded(styled("second"), SIGNATURE)


def test_persona_reply_styles_the_new_text():
    handler, seen = _persona_ctx()
    mail.create_persona_reply(_ctx(handler, compose_font=FONT), "m1",
                              as_mailbox="agent@tenant-a.example",
                              body_html="<p>our answer</p>")
    html = [p for p in _imported(seen).walk()
            if p.get_content_type() == "text/html"][0]
    assert fence(BODY_MARK, styled("our answer")) in html.get_payload(
        decode=True).decode()


def test_update_draft_replaces_verbatim():
    handler, seen = _recorder([
        (lambda r: r.method == "GET",
         httpx.Response(200, json=_draft("<p>old</p>"))),
        (lambda r: r.method == "PATCH",
         lambda r: httpx.Response(200, json=_draft(
             json.loads(r.content)["body"]["content"]))),
    ])
    mail.update_draft(_ctx(handler, compose_font=FONT), "d1", body_html="<p>new</p>")
    assert _patched(seen) == "<p>new</p>"
