"""Attachments: list metadata, get the bytes out, put a file in, take one
back off.

download_attachment (read tier) streams Graph's $value straight to disk
so the bytes never enter an agent's context; add_attachment (write tier)
is the inverse and refuses non-drafts, as does remove_attachment. Only a
fileAttachment has bytes — itemAttachment and referenceAttachment are
refused with the reason by the download path (removal does not care what
kind it is taking off).
"""

import base64
import logging
import mimetypes
import os
from pathlib import Path

from ...graph import Graph, encode_segment as _seg
from ...models import Attachment
from ..context import Ctx, pull
from .common import message_path, prefer, require_draft  # noqa: F401
from .disk import write_atomic, write_target

log = logging.getLogger("ckm365")


_MAX_DIRECT_ATTACHMENT = 3 * 1024 * 1024  # Graph direct-attach limit; bigger
                                          # files need upload sessions (phase 2)
def attachments_of(g: Graph, mb: str, message_id: str) -> list[Attachment]:
    return pull(g, Attachment, message_path(mb, message_id, "/attachments"),
                params={"$select": Attachment.SELECT}, top=100)


def list_attachments(ctx: Ctx, message_id: str, *, account: str | None = None,
                     mailbox: str | None = None) -> list[Attachment]:
    """List a message's attachment metadata (name, type, size — never content).

    `kind` says what each one actually is: fileAttachment (a real file —
    the only kind download_attachment can save), itemAttachment (an
    embedded message or event) or referenceAttachment (a link to cloud
    storage, no bytes in the mailbox). `size` counts the MIME-encoded
    attachment including its headers, so it slightly EXCEEDS the file
    itself (a few hundred bytes to a few KB) — an upper bound, not the
    file size.
    """
    g, mb = ctx.target(account, mailbox)
    return attachments_of(g, mb, message_id)


def _select_attachment(items: list[Attachment], attachment_id: str | None,
                       name: str | None) -> Attachment:
    """Pick exactly one attachment, or raise saying why none was picked.

    Shared by download_attachment and remove_attachment: an ambiguous name
    is an error listing the discriminators, never a silent first match.
    The fileAttachment-only rule belongs to the download path alone
    (_require_bytes), since removing an itemAttachment is perfectly sane.
    """
    if attachment_id:
        matches = [a for a in items if a.id == attachment_id]
        if not matches:
            raise ValueError(
                f"no attachment with that id on this message ({len(items)} "
                "attachment(s) present) — ids change when a message moves, "
                "so re-read them with list_attachments")
    else:
        matches = [a for a in items if a.name == name]
        if not matches:
            raise ValueError(
                f"no attachment with that exact name ({len(items)} "
                "attachment(s) present) — names must match exactly; "
                "list_attachments shows them")
        if len(matches) > 1:
            # Never a silent first-match: hand back the discriminators
            # (ids, sizes) rather than the name they all share.
            candidates = ", ".join(f"{a.id[:24]}… ({a.size} B)" for a in matches)
            raise ValueError(
                f"{len(matches)} attachments on this message share that name — "
                f"pass attachment_id instead: {candidates}")
    return matches[0]


def _require_bytes(found: Attachment) -> Attachment:
    """Only a fileAttachment has bytes on disk to save."""
    if found.kind and found.kind != "fileAttachment":
        raise ValueError(
            f"this attachment is a {found.kind}, which has no file bytes to "
            "save: an itemAttachment is a message or event embedded in the "
            "mail (read it with get_message), and a referenceAttachment is a "
            "link to cloud storage (the file lives in OneDrive/SharePoint, "
            "not in the mailbox). Only fileAttachment can be downloaded.")
    return found


def download_attachment(ctx: Ctx, message_id: str, dest_path: str, *,
                        attachment_id: str | None = None,
                        name: str | None = None, account: str | None = None,
                        mailbox: str | None = None) -> dict:
    """Save one attachment of a message to a file on the server's disk.

    THE BYTES NEVER ENTER YOUR CONTEXT — they stream from Graph straight
    to disk, so this works for a 30 MB PDF as well as a 3 KB one. Read the
    result with ordinary file tools afterwards (that is the point: a .docx
    or .xlsx has to land in a repo or a working directory to be useful).

    Choose the attachment with attachment_id (from list_attachments —
    always unambiguous) or with `name`, which must match EXACTLY. Two
    attachments sharing a name is an error listing their ids, never a
    silent first match. Only a fileAttachment has bytes; an itemAttachment
    (embedded message) or referenceAttachment (a cloud link) is refused
    with the reason rather than written as a broken file.

    dest_path is either a full file path, or an EXISTING DIRECTORY, in
    which case the attachment's own name is used (path separators
    stripped). An existing file is never overwritten — pick another path.
    The download is atomic: a failure part-way leaves nothing behind.
    If CKM365_DOWNLOAD_ROOT (or, failing that, CKM365_ATTACH_ROOT) is set,
    only paths under that directory can be written.

    Read tier — this reads the mailbox and needs no --write; the write it
    does is to LOCAL disk, which is what the roots above are for. Any
    folder works, sentitems included: attachments hang off the message id,
    not the folder. Inline attachments (signature images) download the
    same way; list_attachments' is_inline flags them.

    Returns {"path", "bytes", "name", "content_type", "attachment_id"}.
    "bytes" is what was actually written, always slightly less than the
    `size` list_attachments reports (that one includes MIME headers).
    """
    if not (attachment_id or name):
        raise ValueError("pass attachment_id (from list_attachments) or name")
    g, mb = ctx.target(account, mailbox)
    found = _require_bytes(_select_attachment(
        attachments_of(g, mb, message_id), attachment_id, name))
    dest = write_target(dest_path, found.name)
    written = write_atomic(dest, lambda part: g.download(message_path(
        mb, message_id,
        f"/attachments/{_seg(found.id, 'attachment_id')}/$value"), part))
    # ids, counts and byte totals only — an attachment's NAME can carry the
    # counterparty and project it came from, so it stays out of the log.
    log.info("tool=download_attachment mailbox=%r message_id=%r "
             "attachment_id=%r bytes=%d", mb, message_id, found.id[:24], written)
    return {"path": str(dest), "bytes": written, "name": found.name,
            "content_type": found.content_type, "attachment_id": found.id}


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
    path = message_path(mb, message_id)
    require_draft(g, path, "attach to")
    payload = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": source.name,
        "contentType": mimetypes.guess_type(source.name)[0]
        or "application/octet-stream",
        "contentBytes": base64.b64encode(data).decode("ascii"),
    }
    created = g.post(path + "/attachments", json=payload)
    return Attachment.from_graph(created)


def remove_attachment(ctx: Ctx, message_id: str, *,
                      attachment_id: str | None = None,
                      name: str | None = None, account: str | None = None,
                      mailbox: str | None = None) -> dict:
    """Take an attachment back off a DRAFT — the inverse of add_attachment.

    Drafts only, so this can never strip a file off delivered mail. Choose
    the attachment with attachment_id (from list_attachments — always
    unambiguous) or with `name`, which must match EXACTLY; two attachments
    sharing a name is an error listing their ids, never a silent first
    match. Removal is permanent for that copy: nothing else holds the
    bytes, so download_attachment it first if it might be wanted.

    Any kind can be removed (file, item or reference) — unlike downloading,
    which needs real bytes. Watch the INLINE ones: list_attachments' is_inline
    flags the images a signature or a pasted screenshot references by cid,
    and removing one leaves a broken image in the body rather than freeing
    space. Removing a normal file attachment is the ordinary case — swapping
    a stale revision for a new one is remove_attachment then add_attachment.

    Returns {"removed": true, "message_id", "attachment_id", "name",
    "size", "is_inline"}.
    """
    ctx.require_write()
    if not (attachment_id or name):
        raise ValueError("pass attachment_id (from list_attachments) or name")
    g, mb = ctx.target(account, mailbox)
    path = message_path(mb, message_id)
    require_draft(g, path, "remove an attachment from")
    found = _select_attachment(attachments_of(g, mb, message_id),
                               attachment_id, name)
    g.request("DELETE",
              path + f"/attachments/{_seg(found.id, 'attachment_id')}")
    # ids and sizes only — an attachment NAME can carry the counterparty
    # and the project it came from, so it stays out of the log.
    log.info("tool=remove_attachment mailbox=%r message_id=%r "
             "attachment_id=%r size=%d", mb, message_id, found.id[:24],
             found.size)
    return {"removed": True, "message_id": message_id,
            "attachment_id": found.id, "name": found.name,
            "size": found.size, "is_inline": found.is_inline}
