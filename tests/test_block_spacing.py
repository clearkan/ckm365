"""Offline spec: our paragraphs keep their spacing under Outlook's seeded
stylesheet (reported live, 2026-11-18).

A reply Graph seeds carries Outlook's head stylesheet,
`<style>P {margin-top:0;margin-bottom:0;}</style>`, and our text lands in
that same document, so plain <p> (pandoc, or an LLM) ran together with no
blank line between paragraphs. verify_message saw nothing, because its
text check strips formatting.

- `common.block_margins(html)` gives p, ul, ol, table, blockquote and
  h1-h6 an inline `margin:0 0 12pt 0` unless the element already sets a
  margin; an existing style keeps its declarations after ours.
- Applied to caller text on every compose path (drafts._styled), whatever
  the profile. Never to the signature or the quoted history.
- verify_message's `layout_warnings` flags a body whose stylesheet zeroes
  p margins while our fenced text has a <p> without one (drafts made
  before this fix, or written elsewhere).
- The confinement refusal says how to fix it.
"""

import json

import httpx
import pytest

from ckm365.tools import mail
from ckm365.tools.mail import disk
from ckm365.tools.mail.common import (BODY_MARK, SIGNATURE_MARK, block_margins,
                                      fence, unspaced_blocks)
from test_mail_compose import QUOTE, SIGNATURE, _ctx, _draft, _recorder, _verify_ctx

SP = "margin:0 0 12pt 0"
OUTLOOK_HEAD = ('<html><head><meta http-equiv="Content-Type" content="text/html; '
                'charset=utf-8"><style type="text/css" style="display:none;"> '
                'P {margin-top:0;margin-bottom:0;} </style></head><body dir="ltr">')


@pytest.mark.parametrize("given, want", [
    ("<p>a</p><p>b</p>", f'<p style="{SP}">a</p><p style="{SP}">b</p>'),
    ('<p class="x">a</p>', f'<p class="x" style="{SP}">a</p>'),
    ('<p style="color:red">a</p>', f'<p style="{SP};color:red">a</p>'),
    ("<p style='margin:0'>a</p>", "<p style='margin:0'>a</p>"),       # caller's own margin
    ('<p style="margin-bottom:4pt">a</p>', '<p style="margin-bottom:4pt">a</p>'),
    ("<ul><li>x</li></ul><ol><li>y</li></ol>",
     f'<ul style="{SP}"><li>x</li></ul><ol style="{SP}"><li>y</li></ol>'),
    ("<table border=1><tr><td>c</td></tr></table>",
     f'<table border=1 style="{SP}"><tr><td>c</td></tr></table>'),
    ("<H2>T</H2><blockquote>q</blockquote>",
     f'<H2 style="{SP}">T</H2><blockquote style="{SP}">q</blockquote>'),
    ("<pre>x</pre><param><span>s</span>", "<pre>x</pre><param><span>s</span>"),
    ("", ""),
])
def test_block_margins(given, want):
    assert block_margins(given) == want


def test_block_margins_is_idempotent():
    once = block_margins("<p>a</p><ul><li>b</li></ul>")
    assert block_margins(once) == once


def test_unspaced_blocks_needs_the_zeroing_rule():
    assert unspaced_blocks(OUTLOOK_HEAD, "<p>a</p><p style='margin:0 0 1em'>b</p>") == 1
    assert unspaced_blocks("<html><body>", "<p>a</p>") == 0
    assert unspaced_blocks("<style>.MsoP {margin:0}</style>", "<p>a</p>") == 0


def _outlook_reply_handler():
    seeded = f"{OUTLOOK_HEAD}{QUOTE}</body></html>"
    return _recorder([
        (lambda r: r.method == "POST", httpx.Response(201, json={"id": "d1", "isDraft": True})),
        (lambda r: r.method == "GET", httpx.Response(200, json=_draft(seeded))),
        (lambda r: r.method == "PATCH",
         lambda r: httpx.Response(200, json=_draft(json.loads(r.content)["body"]["content"]))),
    ])


def test_reply_spaces_our_text_not_the_signature_or_quote():
    handler, seen = _outlook_reply_handler()
    mail.create_reply_draft(_ctx(handler, signature_html=SIGNATURE), "m1",
                            "<p>One</p><ul><li>a</li></ul><p>Two</p>")
    body = json.loads([s for s in seen if s[0] == "PATCH"][-1][2])["body"]["content"]
    assert fence(BODY_MARK, f'<p style="{SP}">One</p><ul style="{SP}"><li>a</li></ul>'
                            f'<p style="{SP}">Two</p>') in body
    assert fence(SIGNATURE_MARK, SIGNATURE) in body and QUOTE in body
    assert body.startswith(OUTLOOK_HEAD)
    ours = body[body.index(BODY_MARK + "-start"):body.index(BODY_MARK + "-end")]
    assert unspaced_blocks(body, ours) == 0


def test_verify_message_warns_on_a_squashed_draft():
    old = f"{OUTLOOK_HEAD}{fence(BODY_MARK, '<p>a</p><p>b</p>')}{QUOTE}</body></html>"
    warnings = mail.verify_message(_verify_ctx(old), "d1")["layout_warnings"]
    assert len(warnings) == 1 and warnings[0].startswith("2 paragraph(s)")
    fixed = f"{OUTLOOK_HEAD}{fence(BODY_MARK, block_margins('<p>a</p>'))}{QUOTE}</body></html>"
    assert mail.verify_message(_verify_ctx(fixed), "d1")["layout_warnings"] == []


def test_confinement_refusal_says_how_to_fix_it(monkeypatch, tmp_path):
    monkeypatch.setenv("CKM365_ATTACH_ROOT", str(tmp_path / "root"))
    (tmp_path / "root").mkdir()
    with pytest.raises(ValueError, match="copy the file under it first, or set "
                                         "CKM365_ATTACH_ROOT"):
        disk.confine(tmp_path / "x.txt", "attachment", disk.attach_root())
