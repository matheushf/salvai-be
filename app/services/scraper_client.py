"""HTTP client for the private salvai-scraper service."""

import httpx

from app.core.config import get_settings
from app.core.exceptions import UpstreamError
from app.schemas.instagram import PostMetadataResponse

_SCRAPER_TIMEOUT_S = 15.0


def scraper_is_configured() -> bool:
    settings = get_settings()
    return bool(settings.scraper_service_url and settings.scraper_api_key)


def fetch_metadata_via_scraper(url: str) -> PostMetadataResponse:
    settings = get_settings()
    if not settings.scraper_service_url or not settings.scraper_api_key:
        raise UpstreamError("Scraper service is not configured")

    endpoint = f"{settings.scraper_service_url.rstrip('/')}/enrich"
    try:
        response = httpx.post(
            endpoint,
            json={"url": url},
            headers={"X-Api-Key": settings.scraper_api_key},
            timeout=_SCRAPER_TIMEOUT_S,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException as exc:
        raise UpstreamError("Scraper request timed out") from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200] if exc.response is not None else str(exc)
        raise UpstreamError(
            f"Scraper returned {exc.response.status_code}: {detail}"
        ) from exc
    except httpx.RequestError as exc:
        raise UpstreamError(f"Scraper request failed: {exc}") from exc

    return PostMetadataResponse.model_validate(data)
