"""HTTP client for the private salvai-scraper service."""

import logging

import httpx

from app.core.config import get_settings
from app.core.exceptions import UpstreamError
from app.schemas.instagram import PostMetadataResponse
from app.services.instagram_scraper import InstagramScraperError, SessionMode

logger = logging.getLogger(__name__)

_SCRAPER_TIMEOUT_S = 15.0


def scraper_is_configured() -> bool:
    settings = get_settings()
    return bool(settings.scraper_service_url and settings.scraper_api_key)


def _scraper_headers() -> dict[str, str]:
    settings = get_settings()
    assert settings.scraper_api_key
    return {"X-Api-Key": settings.scraper_api_key}


def _raise_instagram_scraper_error(response: httpx.Response) -> None:
    detail = response.text[:200]
    try:
        payload = response.json()
        if isinstance(payload, dict) and "detail" in payload:
            detail = str(payload["detail"])
    except ValueError:
        pass

    status = response.status_code
    if status == 429:
        raise InstagramScraperError(
            f"Instagram rate-limit hit on scraper session. Details: {detail}",
            status_code=429,
        )
    if status == 404:
        raise InstagramScraperError(detail, status_code=404)
    if status == 403:
        raise InstagramScraperError(detail, status_code=403)
    if status == 503:
        raise InstagramScraperError(detail, status_code=503)
    raise InstagramScraperError(
        f"Scraper returned {status}: {detail}", status_code=502
    )


def fetch_instagram_post(identifier: str, session: SessionMode) -> PostMetadataResponse:
    settings = get_settings()
    if not settings.scraper_service_url or not settings.scraper_api_key:
        raise InstagramScraperError("Scraper service is not configured", status_code=503)

    endpoint = f"{settings.scraper_service_url.rstrip('/')}/instagram/post"
    logger.info(
        "Calling salvai-scraper Instagram endpoint: %s (session=%s)",
        endpoint,
        session,
    )
    try:
        response = httpx.post(
            endpoint,
            json={"identifier": identifier, "session": session},
            headers=_scraper_headers(),
            timeout=_SCRAPER_TIMEOUT_S,
        )
    except httpx.TimeoutException as exc:
        raise InstagramScraperError("Scraper request timed out", status_code=502) from exc
    except httpx.RequestError as exc:
        raise InstagramScraperError(f"Scraper request failed: {exc}", status_code=502) from exc

    if response.is_error:
        _raise_instagram_scraper_error(response)

    return PostMetadataResponse.model_validate(response.json())


def fetch_metadata_via_scraper(url: str) -> PostMetadataResponse:
    settings = get_settings()
    if not settings.scraper_service_url or not settings.scraper_api_key:
        raise UpstreamError("Scraper service is not configured")

    endpoint = f"{settings.scraper_service_url.rstrip('/')}/enrich"
    logger.info(
        "Calling salvai-scraper enrich endpoint: %s (url=%s)",
        endpoint,
        url,
    )
    try:
        response = httpx.post(
            endpoint,
            json={"url": url},
            headers=_scraper_headers(),
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
