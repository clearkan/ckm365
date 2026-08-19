"""Mail tools. Reads are plain; writes are draft-only and gated by Ctx.

`ckm365.tools.mail` is the SemVer'd import path (ClearKan pins it), so
every tool is re-exported here and the split below is an implementation
detail — import from this package, never from its submodules.

    common.py       paths, Prefer headers, the draft guard, the compose
                    fence, /$batch fan-out
    disk.py         writing mail content to LOCAL disk, safely
    read.py         listings, one message, curated headers, folders, counts
    attachments.py  list metadata, stream bytes out, put a file in, take one off
    export.py       one message to a file (OKF .md record, or raw .eml)
    drafts.py       reply/forward/update/revise/create/discard, and the one send
    verify.py       what a composed message actually says, before it goes
    triage.py       read state, flags, filing — batched metadata writes

Two invariants hold across all of it:

Replies/forwards are ALWAYS seeded via Graph createReply/createReplyAll/
createForward so Graph assembles the quoted history and threading headers;
we then PATCH our content into the top of the returned draft. Delivered
(non-draft) messages are never modified. Only send_draft sends, behind the
send tier.

TRIAGE TOOLS (CKM-33/34/35/36) are the one exception to "never modify
delivered messages": read state, flags, and folder are message METADATA,
not content — changing them is what a mail client does, and none of it
alters the message itself or sends anything. They are write-tier
(Mail.ReadWrite, already in the delegated read-write scope set) and they
are BATCHED: a triage pass touches tens of messages at once, so every one
of them takes a LIST of ids, reports per-id outcomes, and never lets one
404 strand the rest of the batch.
"""

from .attachments import (add_attachment, download_attachment,
                          list_attachments, remove_attachment)
from .drafts import (create_draft, create_forward_draft, create_reply_draft,
                     discard_draft, revise_draft, send_draft, update_draft)
from .export import export_message
from .read import (get_message, get_message_headers, group_by_sender,
                   list_mail_folders, list_messages)
from .triage import (complete_flag, flag, mark_read, mark_unread, move_message,
                     unflag)
from .verify import verify_message

__all__ = [
    "add_attachment", "complete_flag", "create_draft", "create_forward_draft",
    "create_reply_draft", "discard_draft", "download_attachment",
    "export_message", "flag", "get_message", "get_message_headers",
    "group_by_sender", "list_attachments", "list_mail_folders",
    "list_messages", "mark_read", "mark_unread", "move_message",
    "remove_attachment", "revise_draft", "send_draft", "unflag",
    "update_draft", "verify_message",
]
