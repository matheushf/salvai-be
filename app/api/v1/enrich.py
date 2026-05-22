from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.instagram import PostMetadataResponse
from app.services.enrich_dispatcher import enrich_url
from app.services.ssrf_validator import validate_url_safety

router = APIRouter(prefix="/enrich", tags=["enrich"])


@router.get(
    "",
    response_model=PostMetadataResponse,
    summary="Enrich a URL with metadata",
    description=(
        "Returns normalized metadata for a supported URL (Instagram, TikTok, "
        "or generic web page). The response shape matches the frontend "
        "enrichment contract."
    ),
)
@router.get(
    "/",
    response_model=PostMetadataResponse,
    summary="Enrich a URL with metadata",
    description=(
        "Returns normalized metadata for a supported URL (Instagram, TikTok, "
        "or generic web page). The response shape matches the frontend "
        "enrichment contract."
    ),
)
def get_enrich(
    url: str = Query(
        ...,
        description="Full URL to enrich (e.g. https://www.tiktok.com/@user/video/123)",
    ),
) -> PostMetadataResponse:
    decoded = unquote(url)

    try:
        validate_url_safety(decoded)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return enrich_url(decoded)
