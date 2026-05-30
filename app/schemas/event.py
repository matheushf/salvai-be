from datetime import datetime
from typing import Literal

from pydantic import BaseModel

EventNotificationReminder = Literal["2d", "1d", "6h", "1h"]


class EventCreate(BaseModel):
    title: str
    date: str
    end_date: str | None = None
    time: str | None = None
    end_time: str | None = None
    location: str | None = None
    image: str | None = None
    source_url: str | None = None
    category: str | None = None
    description: str | None = None
    link: str | None = None
    visible_in_feed: bool = False
    notification_reminder: EventNotificationReminder | None = None


class EventUpdate(BaseModel):
    title: str | None = None
    date: str | None = None
    end_date: str | None = None
    time: str | None = None
    end_time: str | None = None
    location: str | None = None
    image: str | None = None
    source_url: str | None = None
    category: str | None = None
    description: str | None = None
    link: str | None = None
    visible_in_feed: bool | None = None
    notification_reminder: EventNotificationReminder | None = None


class EventResponse(BaseModel):
    id: str
    author_id: str
    title: str
    date: str
    end_date: str | None = None
    time: str | None = None
    end_time: str | None = None
    location: str | None = None
    image: str | None = None
    source_url: str | None = None
    category: str | None = None
    description: str | None = None
    link: str | None = None
    visible_in_feed: bool
    notification_reminder: EventNotificationReminder | None = None
    created_at: datetime


class EventListPage(BaseModel):
    items: list[EventResponse]
    next_cursor: str | None = None
    has_more: bool


class ProfileUpcomingEventsResponse(BaseModel):
    """Upcoming moments shown on a profile (max items enforced server-side)."""

    items: list[EventResponse]
