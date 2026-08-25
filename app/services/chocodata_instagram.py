"""ChocoData Instagram post client (httpx). Used when INSTAGRAM_CHOCODATA_ENABLED."""

from __future__ import annotations

import html
import logging
import re
import time
from html.parser import HTMLParser
from typing import Mapping

import httpx

from app.core.config import get_settings
from app.schemas.instagram import PostMetadataResponse
from app.services.instagram_scraper import InstagramScraperError, shortcode_from_identifier

logger = logging.getLogger(__name__)

_CHOCODATA_POST_URL = "https://api.chocodata.com/api/v1/instagram/post"
_TIMEOUT_SECONDS = 20.0
_MAX_ATTEMPTS = 2
_RETRYABLE_STATUS = {408, 429, 500, 502, 503}
_RETRYABLE_ERROR_CODES = {
    "upstream_timeout",
    "rate_limited",
    "internal_error",
    "extraction_failed",
    "capacity",
    "target_unreachable",
}
_POST_PATH_RE = re.compile(r"instagram\.com/(p|reel|tv)/([A-Za-z0-9_-]+)", re.IGNORECASE)
_HTML_HINT_RE = re.compile(
    r"<(div|span|p|br|h[1-6]|li|ul|ol|a|strong|em|b|i)\b|&nbsp;|&amp;|&lt;",
    re.IGNORECASE,
)
_BLOCK_TAGS = frozenset({"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def to_plain_text(value: object) -> str | None:
    """Turn ChocoData caption/title HTML into instaloader-like plain text."""
    raw = _as_str(value)
    if raw is None:
        return None
    text = html.unescape(raw)
    if _HTML_HINT_RE.search(text):
        parser = _HTMLTextExtractor()
        try:
            parser.feed(text)
            parser.close()
        except Exception:
            logger.warning("Failed to parse ChocoData HTML caption; using unescape only")
        else:
            text = parser.text()
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip() or None


def _description_from_payload(payload: Mapping[str, object]) -> str | None:
    caption = to_plain_text(payload.get("caption"))
    title = to_plain_text(payload.get("title"))
    if caption and title and title.casefold() not in caption.casefold():
        return f"{title}\n\n{caption}"
    return caption or title


def canonical_instagram_post_url(identifier: str) -> str:
    """Return a query-free permalink for ChocoData's `url` param."""
    match = _POST_PATH_RE.search(identifier)
    if match:
        kind, code = match.group(1).lower(), match.group(2)
        return f"https://www.instagram.com/{kind}/{code}/"
    shortcode = shortcode_from_identifier(identifier)
    return f"https://www.instagram.com/p/{shortcode}/"


def _unwrap_payload(payload: Mapping[str, object]) -> Mapping[str, object]:
    if payload.get("caption") or payload.get("title") or payload.get("author"):
        return payload
    for key in ("data", "post", "result"):
        inner = payload.get(key)
        if isinstance(inner, dict):
            return inner
    return payload


def _map_kind(payload: Mapping[str, object]) -> str:
    media_type = (_as_str(payload.get("media_type")) or "").lower()
    product_type = (_as_str(payload.get("product_type")) or "").lower()
    is_video = payload.get("is_video") is True

    if media_type == "carousel":
        return "carousel"
    if (
        media_type in {"video", "clips", "reel", "reels"}
        or product_type in {"clips", "reel", "reels", "igtv"}
        or is_video
    ):
        return "video"
    if media_type in {"image", "photo"}:
        return "image"
    if media_type == "post":
        return "post"
    return "unknown"


def _thumbnail_url(payload: Mapping[str, object]) -> str | None:
    thumbnail = _as_str(payload.get("thumbnail"))
    if thumbnail:
        return thumbnail
    images = payload.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, str):
            return _as_str(first)
        if isinstance(first, dict):
            return _as_str(first.get("url"))
    return None


def map_chocodata_post(payload: Mapping[str, object]) -> PostMetadataResponse:
    payload = _unwrap_payload(payload)
    caption = _description_from_payload(payload)
    data_source = _as_str(payload.get("data_source"))
    if data_source:
        logger.info("ChocoData Instagram post data_source=%s", data_source)
    return PostMetadataResponse(
        platform="instagram",
        kind=_map_kind(payload),
        description=caption,
        thumbnailUrl=_thumbnail_url(payload),
        authorHandle=_as_str(payload.get("author")) or _as_str(payload.get("author_name")),
        publishedAt=_as_str(payload.get("taken_at")),
    )


def _error_body(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        body = response.json()
    except ValueError:
        return None, None
    if not isinstance(body, dict):
        return None, None
    error = body.get("error")
    request_id = body.get("request_id")
    return (
        error if isinstance(error, str) else None,
        request_id if isinstance(request_id, str) else None,
    )


def _retry_delay_seconds(response: httpx.Response) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 10.0)
        except ValueError:
            pass
    return 2.0


def fetch_instagram_post(
    identifier: str,
    api_key: str,
    country: str | None = None,
) -> PostMetadataResponse:
    shortcode = shortcode_from_identifier(identifier)
    post_url = canonical_instagram_post_url(identifier)
    country_code = (country if country is not None else get_settings().choco_data_country)
    country = country_code.strip().lower()
    last_error: InstagramScraperError | None = None

    params: dict[str, str] = {
        "api_key": api_key,
        "shortcode": shortcode,
        "url": post_url,
    }
    if len(country) == 2:
        params["country"] = country

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = httpx.get(
                _CHOCODATA_POST_URL,
                params=params,
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as exc:
            last_error = InstagramScraperError(
                "ChocoData request timed out", status_code=502
            )
            if attempt < _MAX_ATTEMPTS:
                time.sleep(2)
                continue
            raise last_error from exc
        except httpx.RequestError as exc:
            raise InstagramScraperError(
                f"ChocoData request failed: {exc}", status_code=502
            ) from exc

        error_code, request_id = _error_body(response)
        if request_id or not response.is_success:
            logger.warning(
                "ChocoData Instagram post status=%s error=%s request_id=%s attempt=%s",
                response.status_code,
                error_code,
                request_id,
                attempt,
            )

        if response.is_success:
            try:
                payload = response.json()
            except ValueError as exc:
                raise InstagramScraperError(
                    "ChocoData returned invalid JSON", status_code=502
                ) from exc
            if not isinstance(payload, dict):
                raise InstagramScraperError(
                    "ChocoData returned an unexpected payload", status_code=502
                )
            return map_chocodata_post(payload)

        if response.status_code == 404 or error_code == "item_not_found":
            raise InstagramScraperError(
                f"Post with shortcode '{shortcode}' does not exist.",
                status_code=404,
            )

        if response.status_code in {400, 401, 402}:
            raise InstagramScraperError(
                f"ChocoData returned {response.status_code}: {error_code or 'error'}",
                status_code=502,
            )

        last_error = InstagramScraperError(
            f"ChocoData returned {response.status_code}: {error_code or 'error'}",
            status_code=429 if response.status_code == 429 else 502,
        )
        retryable = (
            response.status_code in _RETRYABLE_STATUS
            or error_code in _RETRYABLE_ERROR_CODES
        )
        if retryable and attempt < _MAX_ATTEMPTS:
            time.sleep(_retry_delay_seconds(response))
            continue
        raise last_error

    raise last_error or InstagramScraperError(
        "ChocoData request failed", status_code=502
    )
