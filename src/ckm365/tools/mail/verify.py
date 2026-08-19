"""Checking a composed message before — and after — it goes.

Read tier. verify_message returns the handful of assertions the
2026-08-18 scripts re-derived three times each (recipients, attachment
names and sizes, did the quoted thread survive, did a smart quote leak
into the text we wrote), so the compose loop has one place to look
instead of a fresh hand-rolled HTML splice per check.
"""

import html as htmllib
import logging
import re

from ...models import Message
from ..context import Ctx
from .attachments import attachments_of
from .common import BODY_MARK, SIGNATURE_MARK, fenced_region, message_path, prefer

log = logging.getLogger("ckm365")


# internetMessageHeaders is deliberately NOT selected: ~11 KB a message
# (CKM-38) and nothing here classifies senders. get_message_headers is the
# tool that wants them.
_SELECT = ("id,subject,isDraft,hasAttachments,toRecipients,ccRecipients,"
           "bccRecipients,body,internetMessageId,receivedDateTime")

# What a mail client leaves behind where the quoted history begins. Outlook
# and Graph's createReply produce the first two; the rest cover mail that
# came back through another client.
_QUOTE_MARKS = ("divrplyfwdmsg", 'id="appendonsend"', "gmail_quote",
                "-----original message-----", "<blockquote")
_SIGNATURE_MARKS = ("_mailautosig",)  # Outlook's own signature wrapper

_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"</p\s*>|<br\s*/?>|</div\s*>|</tr\s*>", re.IGNORECASE)
_BLANK = re.compile(r"\n{3,}")
_MAX_TEXT = 4000       # the text we wrote, not the thread it hangs off
_MAX_NON_ASCII = 20
_MAX_TAG = 500         # longest opening tag a cut may back up over


def to_text(html: str) -> str:
    """An HTML fragment as readable plain text — good enough to eyeball and
    to scan for stray characters, and nothing more.

    Deliberately not a parser: block ends become newlines, tags go, entities
    unescape, and &nbsp; becomes a plain space (Outlook's own markup is full
    of them, and reporting every one as "non-ASCII" would bury the smart
    quote that actually matters).
    """
    text = htmllib.unescape(_TAG.sub("", _BREAK.sub("\n", html or "")))
    text = text.replace("\xa0", " ").replace("\u200b", "")
    return _BLANK.sub("\n\n", "\n".join(
        line.rstrip() for line in text.splitlines())).strip()


def _first_of(haystack: str, needles: tuple[str, ...]) -> int:
    found = [i for i in (haystack.find(n) for n in needles) if i >= 0]
    return min(found) if found else -1


def _new_region(content: str) -> tuple[str, str]:
    """(the HTML we wrote, how that boundary was decided).

    The fence create_reply_draft/revise_draft leave behind is exact. Failing
    that — a draft composed in Outlook, or one predating the fence — fall
    back to cutting at the signature or at the quoted history, and SAY which,
    because a guessed boundary is worth less than a known one.
    """
    region = fenced_region(content, BODY_MARK)
    if region:
        return content[region[0]:region[1]], "fence"
    lowered = content.lower()
    cuts = {"signature": _first_of(lowered, _SIGNATURE_MARKS),
            "quote": _first_of(lowered, _QUOTE_MARKS)}
    sig_fence = content.find(f"<!--{SIGNATURE_MARK}-->")
    if sig_fence >= 0:
        cuts["signature"] = sig_fence
    at = min((i for i in cuts.values() if i >= 0), default=-1)
    if at < 0:
        return content, "whole-body"
    how = next(k for k, v in cuts.items() if v == at)
    return content[:_tag_start(content, at)], how


def _tag_start(content: str, at: int) -> int:
    """Back up from a marker to the '<' of the tag carrying it, so the cut
    lands between elements — an id= match sits INSIDE its own opening tag
    ('<div id="divRplyFwdMsg">'), and slicing there leaves half a tag in the
    text."""
    if content[at] == "<":
        return at
    opened = content.rfind("<", 0, at)
    return opened if 0 <= at - opened <= _MAX_TAG else at


def _non_ascii(text: str) -> list[dict]:
    """Every non-ASCII character in the text WE wrote, with a count.

    This is the smart-quote check: an em dash or a curly apostrophe pasted
    from a document is invisible in a draft and mangled by some recipients'
    clients. Reported, never corrected — an intended é must not be an error.
    """
    counts: dict[str, int] = {}
    for char in text:
        if ord(char) > 127:
            counts[char] = counts.get(char, 0) + 1
    return [{"char": c, "codepoint": f"U+{ord(c):04X}", "count": n}
            for c, n in sorted(counts.items())][:_MAX_NON_ASCII]


def verify_message(ctx: Ctx, message_id: str, *, account: str | None = None,
                   mailbox: str | None = None) -> dict:
    """Check a draft before it goes — or the sent copy after it went.

    One call for the things worth asserting about a composed message, all
    of which were hand-derived at every call site before this existed:

    - `to` / `cc` / `bcc` — the addresses, so a reply-all's recipients can
      be eyeballed against who was on the original.
    - `attachments` — attachment_id, name, size, kind and is_inline for
      every one, so a stale file can go straight to remove_attachment.
      ALWAYS listed, because Graph reports `has_attachments` false for a
      message whose only attachments are inline images.
    - `quoted_thread` — is the quoted history still there? (The usual way
      to lose it is update_draft(body_html=...); revise_draft is the tool
      that keeps it.)
    - `signature` — is the profile signature block still in place?
    - `non_ascii` — the characters above ASCII in the text YOU wrote, with
      counts: the smart-quote check, reported and never corrected.
    - `text` — that same text as plain text, capped at 4000 chars, so what
      is about to go out can be read without the thread beneath it.

    `boundary` says HOW the text was told apart from the signature and the
    quoted history: "fence" is exact (ckm365 composed it), while
    "signature", "quote" and "whole-body" are fallbacks for a draft written
    elsewhere — treat `text` and `non_ascii` as approximate when it is not
    "fence".

    Read tier, no --write, no new consent: it only reads the mailbox. Works
    on any folder — verify the draft, send it, then verify the sentitems
    copy by its new id (a send gives the message a different id; find it
    with list_messages(folder="sentitems")).

    Returns {"message_id", "mailbox", "subject", "is_draft", "to", "cc",
    "bcc", "recipients", "attachments", "quoted_thread", "signature",
    "boundary", "text", "text_chars", "text_truncated", "non_ascii",
    "internet_message_id", "received"}.
    """
    g, mb = ctx.target(account, mailbox)
    message = Message.from_graph(
        g.get(message_path(mb, message_id), params={"$select": _SELECT},
              headers=prefer("html")))
    content = message.body.content if message.body else ""
    written, boundary = _new_region(content)
    text = to_text(written)
    lowered = content.lower()
    items = attachments_of(g, mb, message_id)
    result = {
        "message_id": message.id, "mailbox": mb, "subject": message.subject,
        "is_draft": message.is_draft,
        "to": [r.address for r in message.to],
        "cc": [r.address for r in message.cc],
        "bcc": [r.address for r in message.bcc],
        "recipients": len(message.to) + len(message.cc) + len(message.bcc),
        "attachments": [{"attachment_id": a.id, "name": a.name,
                         "size": a.size, "kind": a.kind,
                         "is_inline": a.is_inline} for a in items],
        "quoted_thread": _first_of(lowered, _QUOTE_MARKS) >= 0,
        "signature": (f"<!--{SIGNATURE_MARK}-->" in content
                      or _first_of(lowered, _SIGNATURE_MARKS) >= 0),
        "boundary": boundary,
        "text": text[:_MAX_TEXT - 1] + "…" if len(text) > _MAX_TEXT else text,
        "text_chars": len(text), "text_truncated": len(text) > _MAX_TEXT,
        "non_ascii": _non_ascii(text),
        "internet_message_id": message.internet_message_id,
        "received": message.received,
    }
    # counts only: the subject, the addresses and the text stay out of the log
    log.info("tool=verify_message mailbox=%r message_id=%r draft=%s "
             "recipients=%d attachments=%d quoted=%s non_ascii=%d",
             mb, message_id, message.is_draft, result["recipients"],
             len(items), result["quoted_thread"], len(result["non_ascii"]))
    return result
