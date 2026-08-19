"""Tool registry: presets are explicit function lists, split read vs write."""

from . import accounts, calendar, mail, meetings, teams, watch
from .context import Ctx, SendDisabled, WriteDisabled, bind

ALWAYS = [accounts.list_accounts]  # registered with every preset

# teams and meetings are read-only by design and each needs its OWN
# consent tier, so neither is ever implied by the mail/calendar scopes:
#   teams    — discovery only (CKM-24 option (c): Bot Framework messaging
#              is not this package's job)
#   meetings — transcript retrieval (CKM-30); additionally gated by a
#              Teams tenant setting, not just Graph consent
READ = {
    "mail": [mail.list_messages, mail.get_message, mail.get_message_headers,
             mail.list_mail_folders,
             mail.list_attachments, mail.download_attachment,
             mail.export_message, mail.group_by_sender, mail.verify_message,
             watch.list_new_messages, watch.wait_for_message,
             watch.get_watch_command],
    "calendar": [calendar.list_events, calendar.get_event],
    "teams": [teams.list_teams, teams.list_channels,
              teams.list_installed_apps],
    "meetings": [meetings.find_meeting_id, meetings.list_meeting_transcripts,
                 meetings.get_meeting_transcript],
}
WRITE = {
    "mail": [mail.create_reply_draft, mail.create_forward_draft,
             mail.update_draft, mail.revise_draft, mail.create_draft,
             mail.discard_draft, mail.add_attachment, mail.remove_attachment,
             # triage: metadata only — read state, flags, filing. Nothing
             # leaves the tenant, so these are write tier, not send tier.
             mail.mark_read, mail.mark_unread, mail.flag, mail.unflag,
             mail.complete_flag, mail.move_message],
    "calendar": [calendar.create_event, calendar.update_event,
                 calendar.respond_event],
    "teams": [],
    "meetings": [],
}
SEND = {
    "mail": [mail.send_draft],
    "calendar": [],
    "teams": [],
    "meetings": [],
}
PRESETS = tuple(READ)
# What "all" expands to. teams and meetings are EXCLUDED deliberately:
# each needs its own consent tier (add-teams-scopes.sh /
# add-transcript-scopes.sh), so folding them in would put tools in every
# session that 403 until someone consents — and preset selection exists to keep per-session tool count
# down. Ask for them by name: --preset mail,calendar,teams,meetings.
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
