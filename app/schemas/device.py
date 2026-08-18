from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PushPlatform = Literal["ios", "android"]


class PushTokenUpsert(BaseModel):
    expo_push_token: str = Field(min_length=8, max_length=512)
    platform: PushPlatform
    timezone: str | None = Field(default=None, max_length=64)


class PushTokenResponse(BaseModel):
    id: str
    user_id: str
    expo_push_token: str
    platform: PushPlatform
    created_at: datetime
    last_seen_at: datetime
