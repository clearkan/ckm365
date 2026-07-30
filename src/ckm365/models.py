"""Pydantic projections of Graph resources.

Each model owns the $select list used to fetch it, so queries and
projections cannot drift apart. Dates stay ISO strings — agents consume
them as text and Graph emits them zoned already.
"""

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class Recipient(_Base):
    name: str = ""
    address: str = ""

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, v: Any) -> Any:
        return v.get("emailAddress", v) if isinstance(v, dict) else v


class Body(_Base):
    content_type: str = Field("text", alias="contentType")
    content: str = ""


class MessageSummary(_Base):
    SELECT: ClassVar[str] = ("id,subject,from,receivedDateTime,bodyPreview,"
                             "isRead,isDraft,hasAttachments")
    id: str
    subject: str | None = ""
    sender: Recipient | None = Field(None, alias="from")
    received: str | None = Field(None, alias="receivedDateTime")
    preview: str | None = Field("", alias="bodyPreview")
    is_read: bool = Field(False, alias="isRead")
    is_draft: bool = Field(False, alias="isDraft")
    has_attachments: bool = Field(False, alias="hasAttachments")


class Message(MessageSummary):
    SELECT: ClassVar[str] = (MessageSummary.SELECT +
                             ",body,toRecipients,ccRecipients,bccRecipients,"
                             "internetMessageId,webLink")
    body: Body | None = None
    to: list[Recipient] = Field(default_factory=list, alias="toRecipients")
    cc: list[Recipient] = Field(default_factory=list, alias="ccRecipients")
    bcc: list[Recipient] = Field(default_factory=list, alias="bccRecipients")
    internet_message_id: str | None = Field(None, alias="internetMessageId")
    web_link: str | None = Field(None, alias="webLink")


Draft = Message


class Attachment(_Base):
    SELECT: ClassVar[str] = "id,name,contentType,size,isInline"
    id: str
    name: str = ""
    content_type: str | None = Field(None, alias="contentType")
    size: int = 0
    is_inline: bool = Field(False, alias="isInline")


class MailFolder(_Base):
    SELECT: ClassVar[str] = ("id,displayName,totalItemCount,unreadItemCount,"
                             "childFolderCount")
    id: str
    name: str = Field("", alias="displayName")
    total: int = Field(0, alias="totalItemCount")
    unread: int = Field(0, alias="unreadItemCount")
    child_folders: int = Field(0, alias="childFolderCount")


class EventTime(_Base):
    date_time: str = Field("", alias="dateTime")
    time_zone: str = Field("UTC", alias="timeZone")


class EventSummary(_Base):
    SELECT: ClassVar[str] = ("id,subject,start,end,location,organizer,isAllDay,"
                             "isCancelled,isOnlineMeeting,onlineMeeting")
    id: str
    subject: str | None = ""
    start: EventTime | None = None
    end: EventTime | None = None
    location: str = ""
    organizer: Recipient | None = None
    is_all_day: bool = Field(False, alias="isAllDay")
    is_cancelled: bool = Field(False, alias="isCancelled")
    is_online_meeting: bool = Field(False, alias="isOnlineMeeting")
    join_url: str | None = Field(None, alias="onlineMeeting")

    @field_validator("location", mode="before")
    @classmethod
    def _location_name(cls, v: Any) -> Any:
        return v.get("displayName", "") if isinstance(v, dict) else (v or "")

    @field_validator("join_url", mode="before")
    @classmethod
    def _join_url(cls, v: Any) -> Any:
        return v.get("joinUrl") if isinstance(v, dict) else v


class Event(EventSummary):
    SELECT: ClassVar[str] = EventSummary.SELECT + ",attendees,body,webLink"
    attendees: list[Recipient] = Field(default_factory=list)
    body: Body | None = None
    web_link: str | None = Field(None, alias="webLink")
