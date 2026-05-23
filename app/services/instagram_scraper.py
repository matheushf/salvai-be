import re

import instaloader
from instaloader import (
    ConnectionException,
    InstaloaderException,
    LoginRequiredException,
    PrivateProfileNotFollowedException,
    QueryReturnedForbiddenException,
    QueryReturnedNotFoundException,
    TooManyRequestsException,
)

from app.core.config import get_settings
from app.schemas.instagram import PostMetadataResponse

_SHORTCODE_RE = re.compile(r"instagram\.com/(?:p|reel)/([A-Za-z0-9_-]+)")


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


def _build_sessions() -> list[tuple[str, instaloader.Instaloader]]:
    """Return available Instaloader sessions: authenticated first (if configured),
    then anonymous. Callers try each in order, falling back on rate-limit errors."""
    sessions: list[tuple[str, instaloader.Instaloader]] = []

    settings = get_settings()
    username = settings.instagram_username
    session_file = settings.instagram_session_file

    if username and session_file:
        L = _make_instaloader()
        try:
            L.load_session_from_file(username, session_file)
            sessions.append(("authenticated", L))
        except FileNotFoundError:
            pass

    sessions.append(("anonymous", _make_instaloader()))
    return sessions


_RATE_LIMIT_EXCEPTIONS = (TooManyRequestsException, QueryReturnedForbiddenException)


def _is_rate_limit(exc: InstaloaderException) -> bool:
    return isinstance(exc, _RATE_LIMIT_EXCEPTIONS)


def get_post_metadata(identifier: str) -> PostMetadataResponse:
    shortcode = shortcode_from_identifier(identifier)
    sessions = _build_sessions()
    last_error: InstagramScraperError | None = None

    for label, L in sessions:
        try:
            post = instaloader.Post.from_shortcode(L.context, shortcode)
        except QueryReturnedNotFoundException:
            raise InstagramScraperError(
                f"Post with shortcode '{shortcode}' does not exist.", status_code=404
            )
        except (LoginRequiredException, PrivateProfileNotFollowedException):
            raise InstagramScraperError(
                "This post is from a private account or requires login.", status_code=403
            )
        except InstaloaderException as exc:
            if _is_rate_limit(exc):
                last_error = InstagramScraperError(
                    f"Instagram rate-limit hit on {label} session. "
                    f"Details: {exc}",
                    status_code=429,
                )
                continue
            if isinstance(exc, ConnectionException):
                raise InstagramScraperError(
                    f"Connection error while fetching post: {exc}", status_code=502
                )
            raise InstagramScraperError(
                f"Unexpected scraper error: {exc}", status_code=502
            )

        return PostMetadataResponse(
            platform="instagram",
            kind=_map_kind(post.typename, post.is_video),
            description=post.caption or None,
            thumbnailUrl=post.url or None,
            authorHandle=post.owner_username or None,
            publishedAt=post.date_utc.isoformat() if post.date_utc else None,
        )

    assert last_error is not None
    raise last_error
