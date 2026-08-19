"""Draft writes and the one send.

Replies/forwards are ALWAYS seeded via Graph createReply/createReplyAll/
createForward so Graph assembles the quoted history and threading
headers; our content is then PATCHed into the top of the returned draft
(with If-Match). Delivered messages are never modified here, and only
send_draft sends — behind the send tier.

What we PATCH in is FENCED (common.BODY_MARK / SIGNATURE_MARK) so the
text we wrote can be found again: revise_draft rewrites what is inside
the body fence and leaves the signature and the quoted history exactly
where Graph put them. The profile's signature_html rides along at
creation, so it stops being a literal pasted into a script (CKM-42).
"""

import logging
import re

from ...graph import Graph, mailbox_path as _path
from ...models import Draft
from ..context import Ctx
from .common import (BODY_MARK, SIGNATURE_MARK, fence, fenced_region,
                     message_path, prefer, require_draft, unfenced)

log = logging.getLogger("ckm365")


_BODY_TAG = re.compile(r"<body[^>]*>", re.IGNORECASE)


def _addrs(addresses: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": a}} for a in addresses]


def _prepend(content: str, new_html: str) -> str:
    """Insert new_html at the top of a draft body Graph assembled for us —
    inside <body> when there is one, so the quoted history that follows is
    untouched."""
    m = _BODY_TAG.search(content or "")
    i = m.end() if m else 0
    return content[:i] + new_html + content[i:]


def _body(content: str) -> dict:
    return {"contentType": "html", "content": content}


def _composed(body_html: str, signature_html: str | None) -> str:
    """Our half of a draft body: the text, then the signature, each fenced.

    Fencing the signature separately is what lets revise_draft replace the
    text above it without the caller re-supplying it (the 2026-08-18
    scripts had to splice it back by hand, twice).
    """
    return (fence(BODY_MARK, unfenced(body_html, "body_html"))
            if body_html else "") + (
        fence(SIGNATURE_MARK, signature_html) if signature_html else "")


def _signature(ctx: Ctx, account: str | None, wanted: bool) -> str | None:
    """The profile's signature_html, unless this call opted out of it."""
    return ctx.profile(account).signature_html if wanted else None


def _etag_header(data: dict) -> dict[str, str] | None:
    """If-Match narrows the isDraft check-then-act window: an intervening
    change 412s instead of patching a message that is no longer a draft."""
    etag = data.get("@odata.etag")
    return {"If-Match": etag} if etag else None


def _insert_top(g: Graph, mb: str, draft_id: str, body_html: str,
                signature_html: str | None = None) -> Draft:
    path = message_path(mb, draft_id)
    data = g.get(path, params={"$select": Draft.SELECT}, headers=prefer("html"))
    current = Draft.from_graph(data)
    composed = _composed(body_html, signature_html)
    if not composed:
        return current
    content = _prepend(current.body.content if current.body else "", composed)
    patched = g.patch(path, json={"body": _body(content)},
                      params={"$select": Draft.SELECT},
                      headers=_etag_header(data))
    return Draft.from_graph(patched)


def create_reply_draft(ctx: Ctx, message_id: str, body_html: str = "", *,
                       reply_all: bool = False, signature: bool = True,
                       account: str | None = None,
                       mailbox: str | None = None) -> Draft:
    """Create a reply (or reply-all) draft seeded by Graph with the quoted
    history and threading headers, inserting body_html at the top. Never sends.

    reply_all is decided HERE and cannot be changed later — Graph fixes the
    recipients when it seeds the draft. To switch, discard_draft this one
    and create another (that is what the choice costs; the alternative,
    patching recipients onto a reply, silently loses the ones Graph
    derived).

    The profile's signature_html (profiles.toml) is appended below your
    text unless signature=False. Both regions are FENCED, so revise_draft
    can rewrite your text later without disturbing the signature or the
    quoted history.

    Returns the Draft; keep its id for update_draft / revise_draft /
    add_attachment / verify_message / send_draft.
    """
    ctx.require_write()
    signature_html = _signature(ctx, account, signature)
    g, mb = ctx.target(account, mailbox)
    action = "createReplyAll" if reply_all else "createReply"
    created = g.post(message_path(mb, message_id, f"/{action}")) or {}
    return _insert_top(g, mb, created["id"], body_html, signature_html)


def create_forward_draft(ctx: Ctx, message_id: str, to: list[str],
                         body_html: str = "", *, signature: bool = True,
                         account: str | None = None,
                         mailbox: str | None = None) -> Draft:
    """Create a forward draft with the quoted original; recipients are set in
    the createForward call itself (never patched later). Never sends.

    The profile's signature_html is appended below your text unless
    signature=False, and both regions are fenced for revise_draft.
    """
    ctx.require_write()
    signature_html = _signature(ctx, account, signature)
    g, mb = ctx.target(account, mailbox)
    created = g.post(message_path(mb, message_id, "/createForward"),
                     json={"toRecipients": _addrs(to)}) or {}
    return _insert_top(g, mb, created["id"], body_html, signature_html)


def update_draft(ctx: Ctx, message_id: str, *, subject: str | None = None,
                 body_html: str | None = None, to: list[str] | None = None,
                 cc: list[str] | None = None, bcc: list[str] | None = None,
                 account: str | None = None,
                 mailbox: str | None = None) -> Draft:
    """Update SUBJECT and RECIPIENTS on an existing draft (and, bluntly, the
    body). Refuses to touch non-draft messages.

    body_html here REPLACES the whole body — on a reply that throws away
    the quoted history Graph assembled and the signature with it. To
    rewrite what you wrote and keep both, use revise_draft. This tool
    stays the right one for subject/to/cc/bcc, and for deliberately
    flattening a body to exactly what you pass.
    """
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    path = message_path(mb, message_id)
    current = require_draft(g, path, "modify")
    patch: dict = {}
    if subject is not None:
        patch["subject"] = subject
    if body_html is not None:
        patch["body"] = _body(body_html)
    for key, value in (("toRecipients", to), ("ccRecipients", cc),
                       ("bccRecipients", bcc)):
        if value is not None:
            patch[key] = _addrs(value)
    if not patch:
        raise ValueError("nothing to update")
    return Draft.from_graph(
        g.patch(path, json=patch, params={"$select": Draft.SELECT},
                headers=_etag_header(current)))


def revise_draft(ctx: Ctx, message_id: str, body_html: str, *,
                 account: str | None = None,
                 mailbox: str | None = None) -> Draft:
    """Rewrite the text YOU wrote in a draft, keeping the quoted history and
    the signature exactly as they are. This is the tool for a second draft.

    update_draft(body_html=...) REPLACES the entire body, which on a reply
    throws away the quoted thread Graph assembled and any signature with
    it. This one replaces only the fenced region that create_reply_draft /
    create_forward_draft / create_draft wrote, so revising a reply four
    times costs four calls and loses nothing.

    Send the WHOLE new text each time — body_html is the region's new
    contents, not an addition to it. Subject and recipients are not touched
    here; that is update_draft's job. Refuses non-draft messages.

    On a draft with no fence — one composed in Outlook, or created before
    this version — the text is inserted at the TOP of the body instead and
    fenced there, so nothing below it is disturbed and the NEXT revision
    replaces it properly. That first call therefore adds rather than
    replaces: check the result (or verify_message) before assuming
    otherwise.
    """
    ctx.require_write()
    new_html = unfenced(body_html, "body_html")
    g, mb = ctx.target(account, mailbox)
    path = message_path(mb, message_id)
    data = require_draft(g, path, "revise", select=Draft.SELECT,
                         headers=prefer("html"))
    current = Draft.from_graph(data)
    content = current.body.content if current.body else ""
    region = fenced_region(content, BODY_MARK)
    if region:
        start, end = region
        merged = content[:start] + new_html + content[end:]
    else:
        merged = _prepend(content, fence(BODY_MARK, new_html))
    patched = g.patch(path, json={"body": _body(merged)},
                      params={"$select": Draft.SELECT},
                      headers=_etag_header(data))
    log.info("tool=revise_draft mailbox=%r message_id=%r fenced=%s bytes=%d",
             mb, message_id, bool(region), len(merged))
    return Draft.from_graph(patched)


def discard_draft(ctx: Ctx, message_id: str, *, account: str | None = None,
                  mailbox: str | None = None) -> dict:
    """Throw away a DRAFT you no longer want — the inverse of create_*_draft.

    Refuses anything that is not a draft, so this can never touch delivered
    mail (that is move_message's territory, and it does not delete either).
    Graph moves a deleted message to Deleted Items rather than purging it,
    so a discard is recoverable from the mailbox — but the draft's id dies
    with the move, and any attachment ids on it with it.

    Use it when a draft is wrong beyond revising: the common case is
    switching a reply to a reply-all, which Graph fixes at creation
    (discard, then create_reply_draft(reply_all=True)).

    Returns {"discarded": true, "message_id"}.
    """
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    path = message_path(mb, message_id)
    require_draft(g, path, "discard")
    g.request("DELETE", path)
    log.info("tool=discard_draft mailbox=%r message_id=%r", mb, message_id)
    return {"discarded": True, "message_id": message_id}


def create_draft(ctx: Ctx, *, to: list[str], subject: str, body_html: str,
                 cc: list[str] | None = None, bcc: list[str] | None = None,
                 signature: bool = True, account: str | None = None,
                 mailbox: str | None = None) -> Draft:
    """Create a brand-new draft (not a reply or forward). Never sends.

    The profile's signature_html is appended below body_html unless
    signature=False, and both regions are fenced so revise_draft can
    rewrite the text without touching the signature. For a REPLY use
    create_reply_draft — only Graph can assemble the quoted history and
    the threading headers that keep it in the thread.
    """
    ctx.require_write()
    signature_html = _signature(ctx, account, signature)
    g, mb = ctx.target(account, mailbox)
    message: dict = {
        "subject": subject,
        "body": _body(_composed(body_html, signature_html)),
        "toRecipients": _addrs(to),
    }
    if cc:
        message["ccRecipients"] = _addrs(cc)
    if bcc:
        message["bccRecipients"] = _addrs(bcc)
    created = g.post(_path(mb, "messages"), json=message)
    return Draft.from_graph(created)


def send_draft(ctx: Ctx, message_id: str, *, account: str | None = None,
               mailbox: str | None = None) -> dict:
    """Send an existing draft. Refuses non-drafts and drafts with no
    recipients. Requires the server to run with --write AND --enable-send;
    the profile needs Mail.Send consent (ckm365 login <profile> --send)
    and must not set allow_send = false."""
    ctx.require_send(account)
    g, mb = ctx.target(account, mailbox)
    path = message_path(mb, message_id)
    current = require_draft(g, path, "send",
                            select="id,isDraft,toRecipients,ccRecipients")
    recipients = (len(current.get("toRecipients") or [])
                  + len(current.get("ccRecipients") or []))
    if not recipients:
        raise ValueError("refusing to send: draft has no recipients")
    g.post(path + "/send")
    log.info("tool=send_draft SENT mailbox=%r message_id=%r recipients=%d",
             mb, message_id, recipients)
    return {"sent": True, "message_id": message_id, "recipients": recipients}
