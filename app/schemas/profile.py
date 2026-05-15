from datetime import datetime

from pydantic import BaseModel


class ProfileResponse(BaseModel):
    id: str
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    updated_at: datetime | None = None


class ProfileUpdate(BaseModel):
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None


class ProfileSearchResponse(BaseModel):
    items: list[ProfileResponse]
    total: int
