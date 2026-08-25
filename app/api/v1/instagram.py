import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from fastapi.security.api_key import APIKeyHeader

from app.core.config import get_settings
from app.schemas.instagram import PostMetadataResponse
from app.services.instagram_scraper import InstagramScraperError, get_post_metadata

router = APIRouter(prefix="/instagram", tags=["instagram"])
logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


def _verify_api_key(key: Annotated[str | None, Security(_api_key_header)]) -> None:
    """
    Optional API-key guard for the Instagram scraper.

    When INSTAGRAM_API_KEY is configured in the environment, this dependency
    rejects requests that omit or mismatch the header.  When the env var is
    empty (the default), any request is accepted — suitable for local dev.
    """
    settings = get_settings()
    expected = settings.instagram_api_key
    if expected and key != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing or invalid X-Api-Key header",
        )


@router.get(
    "/post",
    response_model=PostMetadataResponse,
    dependencies=[Depends(_verify_api_key)],
    summary="Get normalized Instagram post or reel metadata",
    description=(
        "Returns normalized metadata for a single Instagram post or reel. "
        "The response shape matches the frontend enrichment contract. "
        "Accepts either a full Instagram URL (post or reel) or a bare shortcode. "
        "No media files are downloaded. "
        "Requires X-Api-Key header when INSTAGRAM_API_KEY is configured."
    ),
)
@router.get(
    "/post/",
    response_model=PostMetadataResponse,
    dependencies=[Depends(_verify_api_key)],
    include_in_schema=False,
)
def get_post(
    identifier: str = Query(
        ...,
        description="Full Instagram post/reel URL or shortcode (e.g. ABC123 or https://www.instagram.com/p/ABC123/)",
    ),
) -> PostMetadataResponse:
    try:
        result = get_post_metadata(identifier=identifier)
    except InstagramScraperError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    logger.info(
        "Instagram post metadata response identifier=%s payload=%s",
        identifier,
        result.model_dump_json(),
    )
    return result
