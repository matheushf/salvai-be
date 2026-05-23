from app.core.exceptions import UpstreamError
from app.schemas.instagram import PostMetadataResponse
from app.services.scraper_client import fetch_metadata_via_scraper, scraper_is_configured


def enrich_webpage(url: str) -> PostMetadataResponse:
    if not scraper_is_configured():
        raise UpstreamError("Scraper service is not configured")
    return fetch_metadata_via_scraper(url)
