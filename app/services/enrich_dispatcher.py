from urllib.parse import urlparse

from app.schemas.instagram import PostMetadataResponse
from app.services.enrich_cache import get_cached_enrich, set_cached_enrich
from app.services.instagram_scraper import (
    InstagramScraperError,
    get_post_metadata,
)
from app.services.tiktok_service import enrich_tiktok, is_tiktok_url

_IG_DOMAINS = {"instagram.com", "www.instagram.com", "m.instagram.com"}


def _enrich_url_uncached(url: str) -> PostMetadataResponse:
    host = urlparse(url).hostname
    if host is None:
        raise ValueError(f"Cannot parse host from URL: {url}")

    host_lower = host.lower()

    if host_lower in _IG_DOMAINS:
        try:
            return get_post_metadata(identifier=url)
        except InstagramScraperError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=exc.status_code, detail=exc.message)

    if is_tiktok_url(url):
        return enrich_tiktok(url)

    from app.services.webpage_service import enrich_webpage

    return enrich_webpage(url)


def enrich_url(url: str) -> PostMetadataResponse:
    cached = get_cached_enrich(url)
    if cached is not None:
        return cached

    result = _enrich_url_uncached(url)
    set_cached_enrich(url, result)
    return result
