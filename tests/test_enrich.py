"""Tests for URL enrichment endpoint and services."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import UpstreamError
from app.main import app
from app.schemas.instagram import PostMetadataResponse
from app.services.instagram_scraper import (
    InstagramScraperError,
    _build_sessions,
    get_post_metadata,
    shortcode_from_identifier,
)
from app.services.ssrf_validator import validate_url_safety
from app.services.tiktok_service import enrich_tiktok, is_tiktok_url


# ── SSRF validator ────────────────────────────────────────────────

def test_allows_public_https_url() -> None:
    # We skip DNS resolution here — public URLs succeed at the scheme/hostname checks.
    # A real DNS-resolved public IP passes the private-range check.
    validate_url_safety("https://www.tiktok.com/@user/video/123")


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError, match="scheme must be http or https"):
        validate_url_safety("ftp://example.com/file")


def test_rejects_no_hostname() -> None:
    with pytest.raises(ValueError, match="URL has no hostname"):
        validate_url_safety("https:///path")


def test_rejects_localhost() -> None:
    with pytest.raises(ValueError, match="blocked"):
        validate_url_safety("https://localhost:8000/admin")


def test_rejects_metadata_endpoint() -> None:
    with pytest.raises(ValueError, match="blocked"):
        validate_url_safety("http://metadata.google.internal/")


# ── TikTok service ────────────────────────────────────────────────

_OEMBED_RESPONSE = {
    "title": "Check out this event! #salvai",
    "author_name": "eventcreator",
    "thumbnail_url": "https://p16-sign.tiktokcdn.com/thumb.jpg",
    "html": "<iframe>...</iframe>",
}


def _mock_httpx_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def test_tiktok_enrich_returns_mapped_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(*args, **kwargs):
        return _mock_httpx_response(_OEMBED_RESPONSE)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = enrich_tiktok("https://www.tiktok.com/@user/video/123")

    assert isinstance(result, PostMetadataResponse)
    assert result.platform == "tiktok"
    assert result.kind == "video"
    assert result.description == "Check out this event! #salvai"
    assert result.authorHandle == "eventcreator"
    assert result.thumbnailUrl == "https://p16-sign.tiktokcdn.com/thumb.jpg"
    assert result.publishedAt is None


def test_tiktok_enrich_handles_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(*args, **kwargs):
        return _mock_httpx_response({})

    monkeypatch.setattr(httpx, "get", fake_get)

    result = enrich_tiktok("https://www.tiktok.com/@user/video/123")
    assert result.description is None
    assert result.thumbnailUrl is None
    assert result.authorHandle is None


def test_tiktok_enrich_raises_upstream_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(*args, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(UpstreamError, match="timed out"):
        enrich_tiktok("https://www.tiktok.com/@user/video/123")


def test_tiktok_enrich_raises_upstream_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 404
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "not found", request=MagicMock(), response=resp
    )

    def fake_get(*args, **kwargs):
        return resp

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(UpstreamError, match="404"):
        enrich_tiktok("https://www.tiktok.com/@user/video/123")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.tiktok.com/@user/video/123", True),
        ("https://vm.tiktok.com/abc123/", True),
        ("https://m.tiktok.com/@user/video/123", True),
        ("https://vt.tiktok.com/abc123/", True),
        ("https://www.instagram.com/p/abc123/", False),
        ("https://example.com", False),
    ],
)
def test_is_tiktok_url(url: str, expected: bool) -> None:
    assert is_tiktok_url(url) == expected


# ── Webpage service (scraper proxy) ───────────────────────────────

_SAMPLE_METADATA = PostMetadataResponse(
    platform="unknown",
    kind="post",
    description="Awesome Event 2026\n\nJoin us for the best event of the year",
    thumbnailUrl="https://example.com/hero.jpg",
    authorHandle="Sympla",
    publishedAt=None,
)


def test_webpage_enrich_delegates_to_scraper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.webpage_service.scraper_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.webpage_service.fetch_metadata_via_scraper",
        lambda url: _SAMPLE_METADATA,
    )

    from app.services.webpage_service import enrich_webpage

    result = enrich_webpage("https://example.com/event")

    assert result.platform == "unknown"
    assert result.kind == "post"
    assert result.thumbnailUrl == "https://example.com/hero.jpg"
    assert result.authorHandle == "Sympla"
    assert result.description is not None
    assert "Awesome Event 2026" in result.description


def test_webpage_enrich_raises_when_scraper_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.webpage_service.scraper_is_configured",
        lambda: False,
    )

    from app.services.webpage_service import enrich_webpage

    with pytest.raises(UpstreamError, match="not configured"):
        enrich_webpage("https://example.com")


def test_webpage_enrich_raises_upstream_when_scraper_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.webpage_service.scraper_is_configured",
        lambda: True,
    )

    def raise_scraper_error(url: str) -> PostMetadataResponse:
        raise UpstreamError("Scraper returned 502")

    monkeypatch.setattr(
        "app.services.webpage_service.fetch_metadata_via_scraper",
        raise_scraper_error,
    )

    from app.services.webpage_service import enrich_webpage

    with pytest.raises(UpstreamError, match="502"):
        enrich_webpage("https://example.com/event")


# ── Instagram scraper ──────────────────────────────────────────────

def test_shortcode_extracts_from_url() -> None:
    assert shortcode_from_identifier("https://www.instagram.com/p/ABC123/") == "ABC123"
    assert shortcode_from_identifier("https://www.instagram.com/reel/XYZ789/") == "XYZ789"
    assert shortcode_from_identifier("bare_shortcode") == "bare_shortcode"


def test_build_sessions_anonymous_only_when_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no credentials are configured, _build_sessions returns only anonymous."""
    monkeypatch.setattr(
        "app.services.instagram_scraper.get_settings",
        lambda: MagicMock(instagram_username="", instagram_session_file=""),
    )
    sessions = _build_sessions()
    assert len(sessions) == 1
    assert sessions[0][0] == "anonymous"


def test_build_sessions_includes_authenticated_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When credentials are set, _build_sessions returns [authenticated, anonymous]."""
    fake_instaloader = MagicMock()
    fake_instaloader.load_session_from_file.return_value = None

    monkeypatch.setattr(
        "app.services.instagram_scraper.get_settings",
        lambda: MagicMock(instagram_username="testuser", instagram_session_file="/tmp/session"),
    )
    monkeypatch.setattr(
        "app.services.instagram_scraper.instaloader.Instaloader", lambda **kw: fake_instaloader
    )

    sessions = _build_sessions()
    assert len(sessions) == 2
    assert sessions[0][0] == "authenticated"
    assert sessions[1][0] == "anonymous"


def test_build_sessions_skips_authenticated_when_session_file_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When session file doesn't exist, _build_sessions returns only anonymous."""
    fake_instaloader = MagicMock()
    fake_instaloader.load_session_from_file.side_effect = FileNotFoundError

    monkeypatch.setattr(
        "app.services.instagram_scraper.get_settings",
        lambda: MagicMock(instagram_username="testuser", instagram_session_file="/nonexistent"),
    )
    monkeypatch.setattr(
        "app.services.instagram_scraper.instaloader.Instaloader", lambda **kw: fake_instaloader
    )

    sessions = _build_sessions()
    assert len(sessions) == 1
    assert sessions[0][0] == "anonymous"


def test_get_post_metadata_falls_back_to_anonymous_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When authenticated session is rate-limited, fall back to anonymous."""
    from instaloader import QueryReturnedForbiddenException

    fake_post = MagicMock()
    fake_post.typename = "GraphImage"
    fake_post.is_video = False
    fake_post.caption = "A caption"
    fake_post.url = "https://example.com/img.jpg"
    fake_post.owner_username = "author"
    fake_post.date_utc.isoformat.return_value = "2026-05-22T12:00:00"

    call_count = 0

    def fake_from_shortcode(context, shortcode):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise QueryReturnedForbiddenException("403 Forbidden")
        return fake_post

    monkeypatch.setattr(
        "app.services.instagram_scraper._build_sessions",
        lambda: [
            ("authenticated", MagicMock()),
            ("anonymous", MagicMock()),
        ],
    )
    monkeypatch.setattr(
        "app.services.instagram_scraper.instaloader.Post.from_shortcode",
        fake_from_shortcode,
    )

    result = get_post_metadata("https://www.instagram.com/p/ABC123/")
    assert result.platform == "instagram"
    assert result.description == "A caption"
    assert call_count == 2


def test_get_post_metadata_raises_when_all_sessions_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When all sessions hit rate limits, raise after exhausting them."""
    from instaloader import TooManyRequestsException

    monkeypatch.setattr(
        "app.services.instagram_scraper._build_sessions",
        lambda: [
            ("authenticated", MagicMock()),
            ("anonymous", MagicMock()),
        ],
    )
    monkeypatch.setattr(
        "app.services.instagram_scraper.instaloader.Post.from_shortcode",
        lambda context, shortcode: (_ for _ in ()).throw(
            TooManyRequestsException("429 Too Many Requests")
        ),
    )

    with pytest.raises(InstagramScraperError, match="rate.limit"):
        get_post_metadata("https://www.instagram.com/p/ABC123/")


# ── API integration tests ─────────────────────────────────────────

@pytest.fixture
def api_client() -> TestClient:
    return TestClient(app)


def test_enrich_endpoint_returns_200_for_valid_url(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_validate(url: str) -> None:
        return None

    def fake_enrich(url: str) -> PostMetadataResponse:
        return PostMetadataResponse(
            platform="tiktok",
            kind="video",
            description="Test desc",
            thumbnailUrl="https://img.example.com/thumb.jpg",
            authorHandle="testuser",
            publishedAt=None,
        )

    monkeypatch.setattr(
        "app.api.v1.enrich.validate_url_safety", fake_validate
    )
    monkeypatch.setattr(
        "app.api.v1.enrich.enrich_url", fake_enrich
    )

    res = api_client.get("/api/v1/enrich?url=https://www.tiktok.com/@user/video/123")

    assert res.status_code == 200
    body = res.json()
    assert body["platform"] == "tiktok"
    assert body["kind"] == "video"
    assert body["description"] == "Test desc"
    assert body["thumbnailUrl"] == "https://img.example.com/thumb.jpg"
    assert body["authorHandle"] == "testuser"


def test_enrich_endpoint_rejects_invalid_url(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_validate(url: str) -> None:
        raise ValueError("URL scheme must be http or https, got 'ftp'")

    monkeypatch.setattr(
        "app.api.v1.enrich.validate_url_safety", fake_validate
    )

    res = api_client.get("/api/v1/enrich?url=ftp://example.com")

    assert res.status_code == 400
    assert "ftp" in res.json()["detail"]


def test_enrich_endpoint_requires_url_param(api_client: TestClient) -> None:
    res = api_client.get("/api/v1/enrich")
    assert res.status_code == 422
