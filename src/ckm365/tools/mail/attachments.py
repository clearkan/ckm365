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
import re
from pathlib import Path
from urllib.parse import unquote

import httpx

from ...graph import Graph, encode_segment as _seg
from ...models import Attachment
from ..context import Ctx, pull
from .common import message_path, prefer, require_draft  # noqa: F401
from .disk import write_atomic, write_target

log = logging.getLogger("ckm365")


_MAX_DIRECT_ATTACHMENT = 3 * 1024 * 1024  # Graph's cap on a contentBytes POST
_MAX_SESSION_ATTACHMENT = 150 * 1024 * 1024  # Graph's upload-session ceiling
# Graph documents the byte range of each chunk as a multiple of 320 KiB.
# CKM-43's live workaround used a flat 4 MiB, which is NOT one (4 MiB /
# 320 KiB = 12.8) and worked twice anyway — so the rule is not enforced for
# attachment sessions, but there is no reason to rely on that. 12 x 320 KiB
# = 3.75 MiB satisfies the documented rule and sits just under the size
# already proven live.
_UPLOAD_CHUNK = 12 * 320 * 1024
_CHUNK_RETRIES = 4
assert _UPLOAD_CHUNK % (320 * 1024) == 0

_NEXT_RANGE = re.compile(r"^(\d+)")
# Graph answers the last chunk with a Location header, and it is NOT the
# path shape the rest of the API uses: it comes back OData function style,
# .../Attachments('AAMk...='), not .../attachments/AAMk...=. Feeding the
# raw last segment back in yields `400 RequestBroker--ParseUri:
# unterminated string literal`, which does not obviously mean "your id has
# brackets round it". Accept both shapes.
_LOCATION_ID = re.compile(r"""[Aa]ttachments(?:\(['"]?([^'")]+)['"]?\)|/([^/?]+))/?$""")


def _upload_client() -> httpx.Client:
    """The chunk PUTs go to a pre-authenticated URL on another host, so they
    deliberately do not use Graph's client (a bearer on them is wrong). That
    also puts them outside MockTransport, so this is the seam the offline
    tests replace — there is no other way to exercise the chunk loop without
    a network."""
    return httpx.Client(timeout=300.0)


def _upload_in_chunks(g: Graph, path: str, source: Path, size: int) -> str:
    """Stream a file to a draft through Graph's upload session, returning
    the new attachment's id.

    The uploadUrl Graph hands back is PRE-AUTHENTICATED: putting a bearer on
    the chunk PUTs is wrong, so they cannot go through Graph and do not
    inherit its retry policy. They get their own, which is the point of an
    upload session — a 6 MB file on bad wifi will drop a chunk, and Graph
    answers a successful PUT with nextExpectedRanges saying where it
    actually wants the next byte. We resync to that rather than assuming our
    own count is right, and a chunk that keeps failing raises with the byte
    offset instead of leaving a half-uploaded attachment looking fine.

    The file is read one chunk at a time and never base64'd — a 150 MB
    attachment must not become a 200 MB string in memory.
    """
    session = g.post(path + "/attachments/createUploadSession",
                     json={"AttachmentItem": {
                         "attachmentType": "file",
                         "name": source.name,
                         "size": size}})
    url = session["uploadUrl"]
    location, sent = None, 0
    with source.open("rb") as fh, _upload_client() as client:
        while sent < size:
            fh.seek(sent)
            block = fh.read(_UPLOAD_CHUNK)
            last = sent + len(block) - 1
            for attempt in range(_CHUNK_RETRIES + 1):
                try:
                    resp = client.put(url, content=block, headers={
                        "Content-Length": str(len(block)),
                        "Content-Range": f"bytes {sent}-{last}/{size}"})
                except httpx.TransportError:
                    if attempt >= _CHUNK_RETRIES:
                        raise
                    continue
                if resp.status_code in (200, 201, 202):
                    break
                if resp.status_code not in (408, 429, 500, 502, 503, 504) \
                        or attempt >= _CHUNK_RETRIES:
                    raise ValueError(
                        f"upload session failed at bytes {sent}-{last} of "
                        f"{size}: {resp.status_code}")
            location = resp.headers.get("location") or location
            nxt = (resp.json().get("nextExpectedRanges")
                   if resp.status_code == 202 and resp.content else None)
            match = _NEXT_RANGE.match(nxt[0]) if nxt else None
            sent = int(match.group(1)) if match else last + 1
    log.info("tool=add_attachment path=upload_session bytes=%d chunks=%d",
             size, -(-size // _UPLOAD_CHUNK))
    if not location:
        raise ValueError("upload session finished without returning the "
                         "attachment location; check the draft before retrying")
    found = _LOCATION_ID.search(unquote(location.split("?")[0]))
    if not found:
        raise ValueError("upload session returned an unrecognised attachment "
                         "location; the file is attached, so list_attachments "
                         "will show it")
    return found.group(1) or found.group(2)
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
    """Attach a local file to a DRAFT, at any size up to 150 MB.

    Files up to 3 MB go in one request; larger ones stream through a Graph
    upload session, in chunks, straight off the disk. Which one runs is not
    your problem — there is one entry point on purpose, and the only size
    that is an error is one Graph itself cannot take.

    The 150 MB ceiling is GRAPH's, not Outlook's: a mailbox may well accept
    a larger message than this API will build. The file is read by the
    server process on this machine; refuses non-draft messages. If the
    CKM365_ATTACH_ROOT env var is set, only files under that directory can
    be attached, on both paths.
    """
    ctx.require_write()
    source = Path(file_path).expanduser().resolve()
    root = os.environ.get("CKM365_ATTACH_ROOT")
    if root and not source.is_relative_to(Path(root).expanduser().resolve()):
        raise ValueError(f"attachment path is outside CKM365_ATTACH_ROOT "
                         f"({root}); refusing to read it")
    size = source.stat().st_size  # stat, not read: a 150 MB file must not be
    if size > _MAX_SESSION_ATTACHMENT:  # loaded just to be rejected
        raise ValueError(
            f"attachment is {size} bytes; Graph's upload session tops out at "
            f"{_MAX_SESSION_ATTACHMENT} bytes ({_MAX_SESSION_ATTACHMENT // (1024 * 1024)} MB). "
            "That is this API's ceiling, not your mailbox's — send a link "
            "instead, or split the file deliberately rather than by accident.")
    g, mb = ctx.target(account, mailbox)
    path = message_path(mb, message_id)
    require_draft(g, path, "attach to")
    if size > _MAX_DIRECT_ATTACHMENT:
        new_id = _upload_in_chunks(g, path, source, size)
        return Attachment.from_graph(
            g.get(f"{path}/attachments/{_seg(new_id, 'attachment id')}",
                  params={"$select": Attachment.SELECT}))
    payload = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": source.name,
        "contentType": mimetypes.guess_type(source.name)[0]
        or "application/octet-stream",
        "contentBytes": base64.b64encode(source.read_bytes()).decode("ascii"),
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
