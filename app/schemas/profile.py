from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.constants.countries import normalize_country, normalize_location_text
from app.constants.interests import normalize_interests


class ProfileResponse(BaseModel):
    id: str
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    interests: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class ProfileMeResponse(ProfileResponse):
    email: str | None = None
    birth_date: date | None = None


class ProfileUpdate(BaseModel):
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    interests: list[str] | None = None
    birth_date: date | None = None

    @field_validator("country")
    @classmethod
    def validate_country(cls, value: str | None) -> str | None:
        return normalize_country(value)

    @field_validator("state", "city")
    @classmethod
    def validate_location_text(cls, value: str | None) -> str | None:
        return normalize_location_text(value)

    @field_validator("interests")
    @classmethod
    def validate_interests(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return normalize_interests(value)

    @field_validator("birth_date")
    @classmethod
    def validate_birth_date(cls, value: date | None) -> date | None:
        if value is None:
            return None
        today = date.today()
        if value >= today:
            raise ValueError("birth_date must be in the past")
        if value.year < 1900:
            raise ValueError("birth_date must be on or after 1900-01-01")
        return value


class ProfileSearchResponse(BaseModel):
    items: list[ProfileResponse]
    total: int
