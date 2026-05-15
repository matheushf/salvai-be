from pydantic import BaseModel

from app.schemas.event import EventResponse
from app.schemas.profile import ProfileResponse


class FeedItem(BaseModel):
    event: EventResponse
    author: ProfileResponse


class FeedPage(BaseModel):
    items: list[FeedItem]
    next_cursor: str | None = None
    has_more: bool
