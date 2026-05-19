from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.constants.interests import normalize_interests


class ProfileResponse(BaseModel):
    id: str
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    interests: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class ProfileMeResponse(ProfileResponse):
    email: str | None = None


class ProfileUpdate(BaseModel):
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    interests: list[str] | None = None

    @field_validator("interests")
    @classmethod
    def validate_interests(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return normalize_interests(value)


class ProfileSearchResponse(BaseModel):
    items: list[ProfileResponse]
    total: int
