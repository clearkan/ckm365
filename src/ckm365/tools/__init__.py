"""Tool registry: presets are explicit function lists, split read vs write."""

from . import accounts, calendar, mail
from .context import Ctx, SendDisabled, WriteDisabled, bind

ALWAYS = [accounts.list_accounts]  # registered with every preset

READ = {
    "mail": [mail.list_messages, mail.get_message, mail.list_mail_folders,
             mail.list_attachments],
    "calendar": [calendar.list_events, calendar.get_event],
}
WRITE = {
    "mail": [mail.create_reply_draft, mail.create_forward_draft,
             mail.update_draft, mail.create_draft, mail.add_attachment],
    "calendar": [calendar.create_event, calendar.update_event,
                 calendar.respond_event],
}
SEND = {
    "mail": [mail.send_draft],
    "calendar": [],
}
PRESETS = tuple(READ)

__all__ = ["Ctx", "PRESETS", "READ", "SEND", "WRITE", "SendDisabled",
           "WriteDisabled", "bind", "tools_for"]


def tools_for(presets, *, write: bool = False, send: bool = False) -> list:
    if send and not write:
        raise ValueError("send tools require write mode as well")
    names = list(presets)
    if "all" in names:
        names = list(PRESETS)
    unknown = set(names) - set(PRESETS)
    if unknown:
        raise ValueError(
            f"unknown preset(s) {sorted(unknown)}; "
            f"available: {', '.join(PRESETS)}, all")
    out: list = [*ALWAYS]
    for name in dict.fromkeys(names):
        out += READ[name] + (WRITE[name] if write else []) \
            + (SEND[name] if send else [])
    return out
