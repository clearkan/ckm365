"""Draft writes and the one send.

Replies/forwards are ALWAYS seeded via Graph createReply/createReplyAll/
createForward so Graph assembles the quoted history and threading
headers; our content is then PATCHed into the top of the returned draft
(with If-Match). Delivered messages are never modified here, and only
send_draft sends — behind the send tier.
"""

import logging
import re

from ...graph import Graph, mailbox_path as _path
from ...models import Body, Draft
from ..context import Ctx
from .common import message_path, prefer, require_draft

log = logging.getLogger("ckm365")


_BODY_TAG = re.compile(r"<body[^>]*>", re.IGNORECASE)


def _addrs(addresses: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": a}} for a in addresses]


def _prepended(existing: Body | None, new_html: str) -> dict:
    """Insert new_html at the top of a draft body Graph assembled for us."""
    content = existing.content if existing else ""
    m = _BODY_TAG.search(content)
    i = m.end() if m else 0
    return {"contentType": "html", "content": content[:i] + new_html + content[i:]}


def _etag_header(data: dict) -> dict[str, str] | None:
    """If-Match narrows the isDraft check-then-act window: an intervening
    change 412s instead of patching a message that is no longer a draft."""
    etag = data.get("@odata.etag")
    return {"If-Match": etag} if etag else None


def _insert_top(g: Graph, mb: str, draft_id: str, body_html: str) -> Draft:
    path = message_path(mb, draft_id)
    data = g.get(path, params={"$select": Draft.SELECT}, headers=prefer("html"))
    current = Draft.from_graph(data)
    if not body_html:
        return current
    patched = g.patch(path, json={"body": _prepended(current.body, body_html)},
                      params={"$select": Draft.SELECT},
                      headers=_etag_header(data))
    return Draft.from_graph(patched)


def create_reply_draft(ctx: Ctx, message_id: str, body_html: str = "", *,
                       reply_all: bool = False, account: str | None = None,
                       mailbox: str | None = None) -> Draft:
    """Create a reply (or reply-all) draft seeded by Graph with the quoted
    history and threading headers, inserting body_html at the top. Never sends."""
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    action = "createReplyAll" if reply_all else "createReply"
    created = g.post(message_path(mb, message_id, f"/{action}")) or {}
    return _insert_top(g, mb, created["id"], body_html)


def create_forward_draft(ctx: Ctx, message_id: str, to: list[str],
                         body_html: str = "", *, account: str | None = None,
                         mailbox: str | None = None) -> Draft:
    """Create a forward draft with the quoted original; recipients are set in
    the createForward call itself (never patched later). Never sends."""
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    created = g.post(message_path(mb, message_id, "/createForward"),
                     json={"toRecipients": _addrs(to)}) or {}
    return _insert_top(g, mb, created["id"], body_html)


def update_draft(ctx: Ctx, message_id: str, *, subject: str | None = None,
                 body_html: str | None = None, to: list[str] | None = None,
                 cc: list[str] | None = None, bcc: list[str] | None = None,
                 account: str | None = None,
                 mailbox: str | None = None) -> Draft:
    """Update fields on an existing draft. body_html REPLACES the whole body
    (any quoted history is lost — use create_reply_draft to keep it).
    Refuses to touch non-draft messages."""
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    path = message_path(mb, message_id)
    current = require_draft(g, path, "modify")
    patch: dict = {}
    if subject is not None:
        patch["subject"] = subject
    if body_html is not None:
        patch["body"] = {"contentType": "html", "content": body_html}
    for key, value in (("toRecipients", to), ("ccRecipients", cc),
                       ("bccRecipients", bcc)):
        if value is not None:
            patch[key] = _addrs(value)
    if not patch:
        raise ValueError("nothing to update")
    return Draft.from_graph(
        g.patch(path, json=patch, params={"$select": Draft.SELECT},
                headers=_etag_header(current)))


def create_draft(ctx: Ctx, *, to: list[str], subject: str, body_html: str,
                 cc: list[str] | None = None,
                 bcc: list[str] | None = None, account: str | None = None,
                 mailbox: str | None = None) -> Draft:
    """Create a brand-new draft (not a reply or forward). Never sends."""
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    message: dict = {
        "subject": subject,
        "body": {"contentType": "html", "content": body_html},
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
