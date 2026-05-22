import httpx

from app.core.exceptions import UpstreamError
from app.schemas.instagram import PostMetadataResponse

_OEMBED_URL = "https://www.tiktok.com/oembed"

_TIKTOK_DOMAINS = {
    "tiktok.com",
    "www.tiktok.com",
    "m.tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
}


def is_tiktok_url(url: str) -> bool:
    from urllib.parse import urlparse

    host = urlparse(url).hostname
    return host is not None and host.lower() in _TIKTOK_DOMAINS


def enrich_tiktok(url: str) -> PostMetadataResponse:
    try:
        response = httpx.get(
            _OEMBED_URL,
            params={"url": url},
            timeout=5.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException:
        raise UpstreamError("TikTok oEmbed request timed out")
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(
            f"TikTok oEmbed returned {exc.response.status_code}"
        )
    except httpx.RequestError as exc:
        raise UpstreamError(f"TikTok oEmbed request failed: {exc}")

    return PostMetadataResponse(
        platform="tiktok",
        kind="video",
        description=data.get("title") or None,
        thumbnailUrl=data.get("thumbnail_url") or None,
        authorHandle=data.get("author_name") or None,
        publishedAt=None,
    )
