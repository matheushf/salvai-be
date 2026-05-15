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
    created_at: datetime
