"""Calendar tools over /calendarView and /events. Writes gated by Ctx."""

import re

from ..graph import encode_segment as _seg, mailbox_path as _path
from ..models import Event, EventSummary
from .context import Ctx

_TZ_RE = re.compile(r"[A-Za-z0-9_+/ -]{1,64}")


def _tz_header(timezone: str | None) -> dict[str, str] | None:
    if timezone is None:
        return None
    if not _TZ_RE.fullmatch(timezone):  # keep it out of the Prefer header
        raise ValueError("invalid timezone name")
    return {"Prefer": f'outlook.timezone="{timezone}"'}


def _when(value: str, timezone: str) -> dict[str, str]:
    return {"dateTime": value, "timeZone": timezone}


def _attendees(addresses: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": a}, "type": "required"} for a in addresses]


def list_events(ctx: Ctx, *, start: str, end: str, timezone: str | None = None,
                top: int = 50, account: str | None = None,
                mailbox: str | None = None) -> list[EventSummary]:
    """List calendar events between start and end (ISO 8601 datetimes, e.g.
    '2026-07-30T00:00:00'). Recurring events are expanded into instances.
    timezone (IANA name) controls the returned times' zone."""
    if not 1 <= top <= 500:
        raise ValueError("top must be between 1 and 500")
    headers = _tz_header(timezone)
    g, mb = ctx.target(account, mailbox)
    params = {"startDateTime": start, "endDateTime": end,
              "$select": EventSummary.SELECT, "$orderby": "start/dateTime",
              "$top": str(min(top, 100))}
    return [EventSummary.model_validate(e)
            for e in g.paged(_path(mb, "calendarView"), params=params,
                             max_items=top, headers=headers)]


def get_event(ctx: Ctx, event_id: str, *, timezone: str | None = None,
              account: str | None = None, mailbox: str | None = None) -> Event:
    """Fetch one calendar event including attendees and body."""
    headers = _tz_header(timezone)
    g, mb = ctx.target(account, mailbox)
    data = g.get(_path(mb, f"events/{_seg(event_id, 'event_id')}"),
                 params={"$select": Event.SELECT}, headers=headers)
    return Event.model_validate(data)


def create_event(ctx: Ctx, *, subject: str, start: str, end: str,
                 timezone: str = "UTC", attendees: list[str] | None = None,
                 body_html: str | None = None, location: str | None = None,
                 online_meeting: bool = False, account: str | None = None,
                 mailbox: str | None = None) -> Event:
    """Create a calendar event. start/end are ISO 8601 datetimes interpreted
    in `timezone`. Attendees (email addresses) receive invitations the moment
    Graph saves the event, so attendee-bearing creates are send-tier and
    additionally require --enable-send. online_meeting=True asks Graph to
    provision a Teams meeting (join link in join_url; the organizer mailbox
    must be Teams-enabled)."""
    ctx.require_write()
    if attendees:
        ctx.require_send()  # invitations are outbound mail (security review)
    g, mb = ctx.target(account, mailbox)
    payload: dict = {"subject": subject, "start": _when(start, timezone),
                     "end": _when(end, timezone)}
    if attendees:
        payload["attendees"] = _attendees(attendees)
    if body_html is not None:
        payload["body"] = {"contentType": "html", "content": body_html}
    if location:
        payload["location"] = {"displayName": location}
    if online_meeting:
        payload["isOnlineMeeting"] = True
        payload["onlineMeetingProvider"] = "teamsForBusiness"
    created = g.post(_path(mb, "events"), json=payload)
    return Event.model_validate(created)


_RESPONSES = {"accept": "accept", "tentative": "tentativelyAccept",
              "decline": "decline"}


def respond_event(ctx: Ctx, event_id: str, response: str, *,
                  comment: str | None = None, send_response: bool = True,
                  account: str | None = None,
                  mailbox: str | None = None) -> dict:
    """Respond to a meeting invitation: response is 'accept', 'tentative',
    or 'decline'. send_response=True notifies the organizer (requires
    --enable-send); send_response=False only updates this calendar."""
    if response not in _RESPONSES:
        raise ValueError(f"response must be one of {sorted(_RESPONSES)}")
    ctx.require_write()
    if send_response:
        ctx.require_send()  # the response is outbound mail to the organizer
    g, mb = ctx.target(account, mailbox)
    payload: dict = {"sendResponse": send_response}
    if comment:
        payload["comment"] = comment
    g.post(_path(mb, f"events/{_seg(event_id, 'event_id')}/{_RESPONSES[response]}"),
           json=payload)
    return {"responded": response, "event_id": event_id,
            "response_sent": send_response}


def update_event(ctx: Ctx, event_id: str, *, subject: str | None = None,
                 start: str | None = None, end: str | None = None,
                 timezone: str = "UTC", location: str | None = None,
                 body_html: str | None = None, account: str | None = None,
                 mailbox: str | None = None) -> Event:
    """Update fields on an existing event (organizer copy). Updating an
    event that has attendees re-notifies them, so that case is send-tier
    and additionally requires --enable-send."""
    ctx.require_write()
    g, mb = ctx.target(account, mailbox)
    path = _path(mb, f"events/{_seg(event_id, 'event_id')}")
    if g.get(path, params={"$select": "id,attendees"}).get("attendees"):
        ctx.require_send()  # updates re-notify attendees (security review)
    patch: dict = {}
    if subject is not None:
        patch["subject"] = subject
    if start is not None:
        patch["start"] = _when(start, timezone)
    if end is not None:
        patch["end"] = _when(end, timezone)
    if location is not None:
        patch["location"] = {"displayName": location}
    if body_html is not None:
        patch["body"] = {"contentType": "html", "content": body_html}
    if not patch:
        raise ValueError("nothing to update")
    updated = g.patch(path, json=patch)
    return Event.model_validate(updated)
