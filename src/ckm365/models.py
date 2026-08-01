"""Dataclass projections of Graph resources (stdlib only — no pydantic).

Each model owns the $select list used to fetch it, so queries and
projections cannot drift apart, and builds itself from the raw Graph
shape via from_graph() (unknown keys are simply never read). Dates stay
ISO strings — agents consume them as text and Graph emits them zoned
already.

Deliberately dependency-free: pydantic v2 treats stdlib dataclasses as
first-class (TypeAdapter gives schema/validation/serialization), which is
what the MCP SDK and pydantic-ai do with tool return types — so those
front doors lose nothing while programmatic consumers gain a
pydantic-free core. An offline test pins that contract.
"""

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class Recipient:
    name: str = ""
    address: str = ""

    @classmethod
    def from_graph(cls, v: Any) -> "Recipient":
        v = v.get("emailAddress", v) if isinstance(v, dict) else {}
        return cls(name=v.get("name") or "", address=v.get("address") or "")


@dataclass
class Body:
    content_type: str = "text"
    content: str = ""

    @classmethod
    def from_graph(cls, v: dict[str, Any]) -> "Body":
        return cls(content_type=v.get("contentType") or "text",
                   content=v.get("content") or "")


def _recipients(items: Any) -> list[Recipient]:
    return [Recipient.from_graph(r) for r in items or []]


@dataclass
class MessageSummary:
    SELECT: ClassVar[str] = ("id,subject,from,receivedDateTime,bodyPreview,"
                             "isRead,isDraft,hasAttachments")
    id: str
    subject: str | None = ""
    sender: Recipient | None = None
    received: str | None = None
    preview: str | None = ""
    is_read: bool = False
    is_draft: bool = False
    has_attachments: bool = False

    @classmethod
    def _kw(cls, d: dict[str, Any]) -> dict[str, Any]:
        return dict(
            id=d["id"], subject=d.get("subject", ""),
            sender=Recipient.from_graph(d["from"]) if d.get("from") else None,
            received=d.get("receivedDateTime"),
            preview=d.get("bodyPreview", ""),
            is_read=bool(d.get("isRead")),
            is_draft=bool(d.get("isDraft")),
            has_attachments=bool(d.get("hasAttachments")))

    @classmethod
    def from_graph(cls, d: dict[str, Any]):
        return cls(**cls._kw(d))


@dataclass
class Message(MessageSummary):
    SELECT: ClassVar[str] = (MessageSummary.SELECT +
                             ",body,toRecipients,ccRecipients,bccRecipients,"
                             "internetMessageId,webLink")
    body: Body | None = None
    to: list[Recipient] = field(default_factory=list)
    cc: list[Recipient] = field(default_factory=list)
    bcc: list[Recipient] = field(default_factory=list)
    internet_message_id: str | None = None
    web_link: str | None = None

    @classmethod
    def _kw(cls, d: dict[str, Any]) -> dict[str, Any]:
        return super()._kw(d) | dict(
            body=Body.from_graph(d["body"]) if d.get("body") else None,
            to=_recipients(d.get("toRecipients")),
            cc=_recipients(d.get("ccRecipients")),
            bcc=_recipients(d.get("bccRecipients")),
            internet_message_id=d.get("internetMessageId"),
            web_link=d.get("webLink"))


Draft = Message


@dataclass
class Attachment:
    SELECT: ClassVar[str] = "id,name,contentType,size,isInline"
    id: str
    name: str = ""
    content_type: str | None = None
    size: int = 0
    is_inline: bool = False

    @classmethod
    def from_graph(cls, d: dict[str, Any]) -> "Attachment":
        return cls(id=d["id"], name=d.get("name") or "",
                   content_type=d.get("contentType"),
                   size=int(d.get("size") or 0),
                   is_inline=bool(d.get("isInline")))


@dataclass
class MailFolder:
    SELECT: ClassVar[str] = ("id,displayName,totalItemCount,unreadItemCount,"
                             "childFolderCount")
    id: str
    name: str = ""
    total: int = 0
    unread: int = 0
    child_folders: int = 0

    @classmethod
    def from_graph(cls, d: dict[str, Any]) -> "MailFolder":
        return cls(id=d["id"], name=d.get("displayName") or "",
                   total=int(d.get("totalItemCount") or 0),
                   unread=int(d.get("unreadItemCount") or 0),
                   child_folders=int(d.get("childFolderCount") or 0))


@dataclass
class EventTime:
    date_time: str = ""
    time_zone: str = "UTC"

    @classmethod
    def from_graph(cls, v: dict[str, Any]) -> "EventTime":
        return cls(date_time=v.get("dateTime") or "",
                   time_zone=v.get("timeZone") or "UTC")


@dataclass
class EventSummary:
    SELECT: ClassVar[str] = ("id,subject,start,end,location,organizer,isAllDay,"
                             "isCancelled,isOnlineMeeting,onlineMeeting")
    id: str
    subject: str | None = ""
    start: EventTime | None = None
    end: EventTime | None = None
    location: str = ""
    organizer: Recipient | None = None
    is_all_day: bool = False
    is_cancelled: bool = False
    is_online_meeting: bool = False
    join_url: str | None = None

    @classmethod
    def _kw(cls, d: dict[str, Any]) -> dict[str, Any]:
        loc = d.get("location")
        meeting = d.get("onlineMeeting")
        return dict(
            id=d["id"], subject=d.get("subject", ""),
            start=EventTime.from_graph(d["start"]) if d.get("start") else None,
            end=EventTime.from_graph(d["end"]) if d.get("end") else None,
            location=loc.get("displayName", "") if isinstance(loc, dict)
                     else (loc or ""),
            organizer=Recipient.from_graph(d["organizer"])
                      if d.get("organizer") else None,
            is_all_day=bool(d.get("isAllDay")),
            is_cancelled=bool(d.get("isCancelled")),
            is_online_meeting=bool(d.get("isOnlineMeeting")),
            join_url=meeting.get("joinUrl") if isinstance(meeting, dict)
                     else meeting)

    @classmethod
    def from_graph(cls, d: dict[str, Any]):
        return cls(**cls._kw(d))


@dataclass
class Team:
    SELECT: ClassVar[str] = "id,displayName,description,isArchived,webUrl"
    id: str
    name: str = ""
    description: str | None = ""
    is_archived: bool = False
    web_url: str | None = None

    @classmethod
    def from_graph(cls, d: dict[str, Any]) -> "Team":
        return cls(id=d["id"], name=d.get("displayName") or "",
                   description=d.get("description") or "",
                   is_archived=bool(d.get("isArchived")),
                   web_url=d.get("webUrl"))


@dataclass
class Channel:
    SELECT: ClassVar[str] = ("id,displayName,description,email,webUrl,"
                             "membershipType")
    id: str
    name: str = ""
    description: str | None = ""
    email: str | None = None
    web_url: str | None = None
    membership_type: str = ""

    @classmethod
    def from_graph(cls, d: dict[str, Any]) -> "Channel":
        return cls(id=d["id"], name=d.get("displayName") or "",
                   description=d.get("description") or "",
                   email=d.get("email") or None,
                   web_url=d.get("webUrl"),
                   membership_type=d.get("membershipType") or "")


@dataclass
class Transcript:
    """Metadata for one meeting transcript. Deliberately no SELECT: the
    objects are tiny, and Teams endpoints have already been caught
    rejecting query options that offline mocks accept happily (see the
    $top gotcha in AGENTS.md) — so we ask for nothing and project what
    arrives. The transcript TEXT is fetched separately by content()."""
    id: str
    created: str | None = None
    meeting_id: str | None = None
    meeting_organizer_id: str | None = None

    @classmethod
    def from_graph(cls, d: dict[str, Any]) -> "Transcript":
        return cls(id=d["id"], created=d.get("createdDateTime"),
                   meeting_id=d.get("meetingId"),
                   meeting_organizer_id=d.get("meetingOrganizerId"))


@dataclass
class InstalledApp:
    """A Teams app installed in a team; the definition arrives via $expand."""
    id: str
    name: str = ""
    version: str | None = None
    teams_app_id: str | None = None

    @classmethod
    def from_graph(cls, d: dict[str, Any]) -> "InstalledApp":
        definition = d.get("teamsAppDefinition") or {}
        return cls(id=d["id"], name=definition.get("displayName") or "",
                   version=definition.get("version"),
                   teams_app_id=definition.get("teamsAppId"))


@dataclass
class Event(EventSummary):
    SELECT: ClassVar[str] = EventSummary.SELECT + ",attendees,body,webLink"
    attendees: list[Recipient] = field(default_factory=list)
    body: Body | None = None
    web_link: str | None = None

    @classmethod
    def _kw(cls, d: dict[str, Any]) -> dict[str, Any]:
        return super()._kw(d) | dict(
            attendees=_recipients(d.get("attendees")),
            body=Body.from_graph(d["body"]) if d.get("body") else None,
            web_link=d.get("webLink"))
