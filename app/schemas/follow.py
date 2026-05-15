from datetime import datetime

from pydantic import BaseModel


class FollowResponse(BaseModel):
    follower_id: str
    followed_id: str
    created_at: datetime


class FollowingListResponse(BaseModel):
    items: list[FollowResponse]
    total: int
