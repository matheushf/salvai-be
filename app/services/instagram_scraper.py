import logging
import re
from typing import Literal

import app.core.instagram_patch  # noqa: F401 — monkey-patch for Instagram API changes
import instaloader
from instaloader import (
    ConnectionException,
    InstaloaderException,
    LoginRequiredException,
    Post,
    PrivateProfileNotFollowedException,
    QueryReturnedForbiddenException,
    QueryReturnedNotFoundException,
    TooManyRequestsException,
)

from app.core.config import get_settings
from app.schemas.instagram import PostMetadataResponse

logger = logging.getLogger(__name__)

_SHORTCODE_RE = re.compile(r"instagram\.com/(?:p|reel)/([A-Za-z0-9_-]+)")

SessionMode = Literal["anonymous", "authenticated"]
FetchSource = Literal["be", "scraper"]

ATTEMPTS: list[tuple[FetchSource, SessionMode]] = [
    ("be", "anonymous"),
    ("be", "authenticated"),
    ("scraper", "anonymous"),
    ("scraper", "authenticated"),
]


class InstagramScraperError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def shortcode_from_identifier(identifier: str) -> str:
    """Return a shortcode given a full Instagram URL or a bare shortcode."""
    match = _SHORTCODE_RE.search(identifier)
    if match:
        return match.group(1)
    return identifier.strip("/")


def _map_kind(typename: str, is_video: bool) -> str:
    if typename == "GraphSidecar":
        return "carousel"
    if typename == "GraphVideo" or is_video:
        return "video"
    if typename == "GraphImage":
        return "image"
    return "unknown"


def _make_instaloader() -> instaloader.Instaloader:
    """Return a bare Instaloader instance with scraping disabled."""
    return instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )


def _session_for_mode(mode: SessionMode) -> instaloader.Instaloader | None:
    """Return an Instaloader for the given mode, or None if unavailable."""
    if mode == "anonymous":
        return _make_instaloader()

    settings = get_settings()
    username = settings.instagram_username
    session_file = settings.instagram_session_file
    if not username or not session_file:
        return None

    loader = _make_instaloader()
    try:
        loader.load_session_from_file(username, session_file)
    except FileNotFoundError:
        return None
    return loader


def _build_sessions() -> list[tuple[str, instaloader.Instaloader]]:
    """Return available Instaloader sessions: anonymous first, then authenticated."""
    sessions: list[tuple[str, instaloader.Instaloader]] = []

    anonymous = _session_for_mode("anonymous")
    if anonymous is not None:
        sessions.append(("anonymous", anonymous))

    authenticated = _session_for_mode("authenticated")
    if authenticated is not None:
        sessions.append(("authenticated", authenticated))

    return sessions


_RATE_LIMIT_EXCEPTIONS = (TooManyRequestsException, QueryReturnedForbiddenException)


def _is_rate_limit(exc: InstaloaderException) -> bool:
    return isinstance(exc, _RATE_LIMIT_EXCEPTIONS)


def _post_to_response(post: Post) -> PostMetadataResponse:
    return PostMetadataResponse(
        platform="instagram",
        kind=_map_kind(post.typename, post.is_video),
        description=post.caption or None,
        thumbnailUrl=post.url or None,
        authorHandle=post.owner_username or None,
        publishedAt=post.date_utc.isoformat() if post.date_utc else None,
    )


def _fetch_local(shortcode: str, loader: instaloader.Instaloader, label: str) -> PostMetadataResponse:
    try:
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
    except QueryReturnedNotFoundException:
        raise InstagramScraperError(
            f"Post with shortcode '{shortcode}' does not exist.", status_code=404
        ) from None
    except (LoginRequiredException, PrivateProfileNotFollowedException):
        raise InstagramScraperError(
            "This post is from a private account or requires login.", status_code=403
        ) from None
    except InstaloaderException as exc:
        if _is_rate_limit(exc):
            raise InstagramScraperError(
                f"Instagram rate-limit hit on {label} session. Details: {exc}",
                status_code=429,
            ) from exc
        if isinstance(exc, ConnectionException):
            raise InstagramScraperError(
                f"Connection error while fetching post: {exc}", status_code=502
            ) from exc
        raise InstagramScraperError(
            f"Unexpected scraper error: {exc}", status_code=502
        ) from exc

    return _post_to_response(post)


def get_post_metadata(identifier: str) -> PostMetadataResponse:
    shortcode = shortcode_from_identifier(identifier)
    last_error: InstagramScraperError | None = None

    for source, mode in ATTEMPTS:
        layer = f"{source}:{mode}"

        if source == "be":
            loader = _session_for_mode(mode)
            if loader is None:
                continue
            try:
                result = _fetch_local(shortcode, loader, layer)
                logger.info("Instagram post fetched via %s", layer)
                return result
            except InstagramScraperError as exc:
                if exc.status_code == 429:
                    last_error = exc
                    continue
                raise
            continue

        from app.services.scraper_client import fetch_instagram_post, scraper_is_configured

        if not scraper_is_configured():
            continue

        try:
            result = fetch_instagram_post(identifier=identifier, session=mode)
            logger.info("Instagram post fetched via %s", layer)
            return result
        except InstagramScraperError as exc:
            if exc.status_code in (429, 503):
                if exc.status_code == 429:
                    last_error = exc
                continue
            raise

    if last_error is not None:
        raise last_error

    raise InstagramScraperError(
        "All Instagram fetch layers are unavailable or exhausted.", status_code=429
    )
