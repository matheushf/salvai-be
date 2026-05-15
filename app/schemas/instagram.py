from pydantic import BaseModel


class PostMetadataResponse(BaseModel):
    platform: str
    kind: str
    description: str | None
    thumbnailUrl: str | None
    authorHandle: str | None
    publishedAt: str | None
