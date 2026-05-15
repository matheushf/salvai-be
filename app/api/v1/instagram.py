from fastapi import APIRouter, HTTPException, Query

from app.schemas.instagram import PostMetadataResponse
from app.services.instagram_scraper import InstagramScraperError, get_post_metadata

router = APIRouter(prefix="/instagram", tags=["instagram"])


@router.get(
    "/post",
    response_model=PostMetadataResponse,
    summary="Get normalized Instagram post or reel metadata",
    description=(
        "Returns normalized metadata for a single Instagram post or reel. "
        "The response shape matches the frontend enrichment contract. "
        "Accepts either a full Instagram URL (post or reel) or a bare shortcode. "
        "No media files are downloaded."
    ),
)
def get_post(
    identifier: str = Query(
        ...,
        description="Full Instagram post/reel URL or shortcode (e.g. ABC123 or https://www.instagram.com/p/ABC123/)",
    ),
) -> PostMetadataResponse:
    try:
        return get_post_metadata(identifier=identifier)
    except InstagramScraperError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
