"""Tool registry: presets are explicit function lists, split read vs write."""

from . import accounts, calendar, mail, teams, watch
from .context import Ctx, SendDisabled, WriteDisabled, bind

ALWAYS = [accounts.list_accounts]  # registered with every preset

# The teams preset is read-only by design (CKM-24 option (c): discovery
# only — Bot Framework messaging is not this package's job) and needs its
# own consent tier, so it is never implied by the mail/calendar scopes.
READ = {
    "mail": [mail.list_messages, mail.get_message, mail.list_mail_folders,
             mail.list_attachments, watch.list_new_messages,
             watch.wait_for_message, watch.get_watch_command],
    "calendar": [calendar.list_events, calendar.get_event],
    "teams": [teams.list_teams, teams.list_channels,
              teams.list_installed_apps],
}
WRITE = {
    "mail": [mail.create_reply_draft, mail.create_forward_draft,
             mail.update_draft, mail.create_draft, mail.add_attachment],
    "calendar": [calendar.create_event, calendar.update_event,
                 calendar.respond_event],
    "teams": [],
}
SEND = {
    "mail": [mail.send_draft],
    "calendar": [],
    "teams": [],
}
PRESETS = tuple(READ)
# What "all" expands to. teams is EXCLUDED deliberately: it needs its own
# consent tier (scripts/add-teams-scopes.sh), so folding it into the
# default would put tools in every session that 403 until someone
# consents — and preset selection exists to keep per-session tool count
# down. Ask for it by name: --preset mail,calendar,teams.
ALL_PRESETS = ("mail", "calendar")

__all__ = ["ALL_PRESETS", "Ctx", "PRESETS", "READ", "SEND", "WRITE",
           "SendDisabled", "WriteDisabled", "bind", "tools_for"]


def tools_for(presets, *, write: bool = False, send: bool = False) -> list:
    if send and not write:
        raise ValueError("send tools require write mode as well")
    names = list(presets)
    if "all" in names:
        names = [n for n in names if n != "all"] + list(ALL_PRESETS)
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
