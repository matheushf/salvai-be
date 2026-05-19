from datetime import datetime

from pydantic import BaseModel


class EventCreate(BaseModel):
    title: str
    date: str
    end_date: str | None = None
    location: str | None = None
    image: str | None = None
    source_url: str | None = None
    category: str | None = None
    description: str | None = None
    link: str | None = None
    visible_in_feed: bool = False


class EventUpdate(BaseModel):
    title: str | None = None
    date: str | None = None
    end_date: str | None = None
    location: str | None = None
    image: str | None = None
    source_url: str | None = None
    category: str | None = None
    description: str | None = None
    link: str | None = None
    visible_in_feed: bool | None = None


class EventResponse(BaseModel):
    id: str
    author_id: str
    title: str
    date: str
    end_date: str | None = None
    location: str | None = None
    image: str | None = None
    source_url: str | None = None
    category: str | None = None
    description: str | None = None
    link: str | None = None
    visible_in_feed: bool
    created_at: datetime


class EventListPage(BaseModel):
    items: list[EventResponse]
    next_cursor: str | None = None
    has_more: bool


class ProfileUpcomingEventsResponse(BaseModel):
    """Upcoming moments shown on a profile (max items enforced server-side)."""

    items: list[EventResponse]
