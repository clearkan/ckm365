"""Mail tools. Reads are plain; writes are draft-only and gated by Ctx.

Replies/forwards are ALWAYS seeded via Graph createReply/createReplyAll/
createForward so Graph assembles the quoted history and threading headers;
we then PATCH our content into the top of the returned draft. Delivered
(non-draft) messages are never modified. Nothing here sends mail.
"""

import base64
import logging
import mimetypes
import os
import re
from pathlib import Path

from ..graph import Graph, encode_segment as _seg, mailbox_path as _path
from ..models import Attachment, Body, Draft, MailFolder, Message, MessageSummary
from .context import Ctx, pull

log = logging.getLogger("ckm365")

_BODY_TAG = re.compile(r"<body[^>]*>", re.IGNORECASE)
_MAX_DIRECT_ATTACHMENT = 3 * 1024 * 1024  # Graph direct-attach limit; bigger
                                          # files need upload sessions (phase 2)


def _prefer(body_format: str) -> dict[str, str]:
    if body_format not in ("text", "html"):
        raise ValueError("body_format must be 'text' or 'html'")
    return {"Prefer": f'outlook.body-content-type="{body_format}"'}


def _addrs(addresses: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": a}} for a in addresses]


def _prepended(existing: Body | None, new_html: str) -> dict:
    """Insert new_html at the top of a draft body Graph assembled for us."""
    content = existing.content if existing else ""
    m = _BODY_TAG.search(content)
    i = m.end() if m else 0
    return {"contentType": "html", "content": content[:i] + new_html + content[i:]}


def _message_path(mailbox: str, message_id: str, suffix: str = "") -> str:
    return _path(mailbox, f"messages/{_seg(message_id, 'message_id')}{suffix}")


def _require_draft(g: Graph, path: str, verb: str,
                   select: str = "id,isDraft") -> dict:
    """The draft-only invariant lives here: fetch and refuse non-drafts."""
    current = g.get(path, params={"$select": select})
    if not current.get("isDraft"):
        raise ValueError(f"refusing to {verb} a non-draft message")
    return current


def _etag_header(data: dict) -> dict[str, str] | None:
    """If-Match narrows the isDraft check-then-act window: an intervening
    change 412s instead of patching a message that is no longer a draft."""
    etag = data.get("@odata.etag")
    return {"If-Match": etag} if etag else None


def list_messages(ctx: Ctx, *, folder: str = "inbox", search: str | None = None,
                  filter: str | None = None, top: int = 25,
                  account: str | None = None,
                  mailbox: str | None = None) -> list[MessageSummary]:
    """List messages in a mail folder, newest first.

    search uses KQL (e.g. 'from:alice subject:invoice'); filter is OData
    (e.g. 'isRead eq false'); they cannot be combined, and filtered results
    come back in Graph's default order. folder takes a well-known name
    (inbox, drafts, sentitems, ...) or a folder id.
    """
    if search and filter:
        raise ValueError("search and filter cannot be combined")
    if not 1 <= top <= 500:
        raise ValueError("top must be between 1 and 500")
    g, mb = ctx.target(account, mailbox)
    params = {"$select": MessageSummary.SELECT, "$top": str(min(top, 100))}
    if search:
        escaped = search.replace("\\", "\\\\").replace('"', '\\"')
        params["$search"] = f'"{escaped}"'
    elif filter:
        params["$filter"] = filter
    else:
        params["$orderby"] = "receivedDateTime desc"
    path = _path(mb, f"mailFolders/{_seg(folder, 'folder')}/messages")
    return pull(g, MessageSummary, path, params=params, top=top)


def get_message(ctx: Ctx, message_id: str, *, body_format: str = "text",
                account: str | None = None,
                mailbox: str | None = None) -> Message:
    """Fetch one message including its body (body_format: 'text' or 'html')."""
    g, mb = ctx.target(account, mailbox)
    data = g.get(_message_path(mb, message_id),
                 params={"$select": Message.SELECT}, headers=_prefer(body_format))
    return Message.model_validate(data)


def list_mail_folders(ctx: Ctx, *, account: str | None = None,
                      mailbox: str | None = None) -> list[MailFolder]:
    """List top-level mail folders with item/unread counts."""
    g, mb = ctx.target(account, mailbox)
    params = {"$select": MailFolder.SELECT, "$top": "100"}
    return pull(g, MailFolder, _path(mb, "mailFolders"), params=params, top=200)


def list_attachments(ctx: Ctx, message_id: str, *, account: str | None = None,
                     mailbox: str | None = None) -> list[Attachment]:
    """List a message's attachment metadata (name, type, size — never content)."""
    g, mb = ctx.target(account, mailbox)
    return pull(g, Attachment, _message_path(mb, message_id, "/attachments"),
                params={"$select": Attachment.SELECT}, top=100)


def add_attachment(ctx: Ctx, message_id: str, file_path: str, *,
                   account: str | None = None,
                   mailbox: str | None = None) -> Attachment:
    """Attach a local file to a DRAFT (max 3 MB). The file is read by the
    server process on this machine; refuses non-draft messages. If the
    CKM365_ATTACH_ROOT env var is set, only files under that directory
    can be attached."""
    ctx.require_write()
    source = Path(file_path).expanduser().resolve()
    root = os.environ.get("CKM365_ATTACH_ROOT")
    if root and not source.is_relative_to(Path(root).expanduser().resolve()):
        raise ValueError(f"attachment path is outside CKM365_ATTACH_ROOT "
                         f"({root}); refusing to read it")
    data = source.read_bytes()
    if len(data) > _MAX_DIRECT_ATTACHMENT:
        raise ValueError("attachment exceeds the 3 MB direct-attach limit "
                         "(upload sessions are not supported yet)")
    g, mb = ctx.target(account, mailbox)
    path = _message_path(mb, message_id)
    _require_draft(g, path, "attach to")
    payload = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": source.name,
        "contentType": mimetypes.guess_type(source.name)[0]
        or "application/octet-stream",
        "contentBytes": base64.b64encode(data).decode("ascii"),
    }
    created = g.post(path + "/attachments", json=payload)
    return Attachment.model_validate(created)


def _insert_top(g: Graph, mb: str, draft_id: str, body_html: str) -> Draft:
    path = _message_path(mb, draft_id)
    data = g.get(path, params={"$select": Draft.SELECT}, headers=_prefer("html"))
    current = Draft.model_validate(data)
    if not body_html:
        return current
    patched = g.patch(path, json={"body": _prepended(current.body, body_html)},
                      params={"$select": Draft.SELECT},
                      headers=_etag_header(data))
    return Draft.model_validate(patched)


def create_reply_draft(ctx: Ctx, message_id: str, body_html: str = "", *,
                       reply_all: bool = False, account: str | None = None,
                       mailbox: str | None = None) -> Draft:
    """Create a reply (or reply-all) draft seeded by Graph with the quoted
    history and threading headers, inserting body_html at the top. Never sends."""
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    action = "createReplyAll" if reply_all else "createReply"
    created = g.post(_message_path(mb, message_id, f"/{action}")) or {}
    return _insert_top(g, mb, created["id"], body_html)


def create_forward_draft(ctx: Ctx, message_id: str, to: list[str],
                         body_html: str = "", *, account: str | None = None,
                         mailbox: str | None = None) -> Draft:
    """Create a forward draft with the quoted original; recipients are set in
    the createForward call itself (never patched later). Never sends."""
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    created = g.post(_message_path(mb, message_id, "/createForward"),
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
    path = _message_path(mb, message_id)
    current = _require_draft(g, path, "modify")
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
    return Draft.model_validate(
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
    return Draft.model_validate(created)


def send_draft(ctx: Ctx, message_id: str, *, account: str | None = None,
               mailbox: str | None = None) -> dict:
    """Send an existing draft. Refuses non-drafts and drafts with no
    recipients. Requires the server to run with --write AND --enable-send;
    the profile needs Mail.Send consent (ckm365 login <profile> --send)
    and must not set allow_send = false."""
    ctx.require_send(account)
    g, mb = ctx.target(account, mailbox)
    path = _message_path(mb, message_id)
    current = _require_draft(g, path, "send",
                             select="id,isDraft,toRecipients,ccRecipients")
    recipients = (len(current.get("toRecipients") or [])
                  + len(current.get("ccRecipients") or []))
    if not recipients:
        raise ValueError("refusing to send: draft has no recipients")
    g.post(path + "/send")
    log.info("tool=send_draft SENT mailbox=%r message_id=%r recipients=%d",
             mb, message_id, recipients)
    return {"sent": True, "message_id": message_id, "recipients": recipients}
