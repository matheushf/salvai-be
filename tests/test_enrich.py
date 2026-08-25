"""Tests for URL enrichment endpoint and services."""

from __future__ import annotations

import json
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
    _session_for_mode,
    get_post_metadata,
    shortcode_from_identifier,
)
from app.services.ssrf_validator import validate_url_safety
from app.services.event_extraction import iso_to_display_date
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
    resp.is_success = 200 <= status_code < 300
    resp.headers = {}
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

def _disable_chocodata(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = MagicMock()
    mock.instagram_chocodata_enabled = False
    mock.choco_data_api_key = ""
    monkeypatch.setattr("app.services.instagram_scraper.get_settings", lambda: mock)


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
    """When credentials are set, _build_sessions returns [anonymous, authenticated]."""
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
    assert sessions[0][0] == "anonymous"
    assert sessions[1][0] == "authenticated"


def test_session_for_mode_returns_none_for_missing_authenticated_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.instagram_scraper.get_settings",
        lambda: MagicMock(instagram_username="", instagram_session_file=""),
    )
    assert _session_for_mode("anonymous") is not None
    assert _session_for_mode("authenticated") is None


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


def test_get_post_metadata_falls_back_to_authenticated_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When anonymous session is rate-limited, fall back to authenticated."""
    from instaloader import QueryReturnedForbiddenException

    fake_post = MagicMock()
    fake_post.typename = "GraphImage"
    fake_post.is_video = False
    fake_post.caption = "A caption"
    fake_post.url = "https://example.com/img.jpg"
    fake_post.owner_username = "author"
    fake_post.date_utc.isoformat.return_value = "2026-05-22T12:00:00"

    _disable_chocodata(monkeypatch)
    call_count = 0

    def fake_from_shortcode(context, shortcode):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise QueryReturnedForbiddenException("403 Forbidden")
        return fake_post

    monkeypatch.setattr(
        "app.services.instagram_scraper._session_for_mode",
        lambda mode: MagicMock() if mode in ("anonymous", "authenticated") else None,
    )
    monkeypatch.setattr(
        "app.services.scraper_client.scraper_is_configured",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.services.instagram_scraper.instaloader.Post.from_shortcode",
        fake_from_shortcode,
    )

    result = get_post_metadata("https://www.instagram.com/p/ABC123/")
    assert result.platform == "instagram"
    assert result.description == "A caption"
    assert call_count == 2


def test_get_post_metadata_falls_back_to_scraper_on_be_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both local sessions are rate-limited, fall back to salvai-scraper."""
    from instaloader import TooManyRequestsException

    scraper_result = PostMetadataResponse(
        platform="instagram",
        kind="image",
        description="From scraper",
        thumbnailUrl="https://example.com/scraper.jpg",
        authorHandle="scraper_author",
        publishedAt=None,
    )

    _disable_chocodata(monkeypatch)
    monkeypatch.setattr(
        "app.services.instagram_scraper._session_for_mode",
        lambda mode: MagicMock() if mode in ("anonymous", "authenticated") else None,
    )
    monkeypatch.setattr(
        "app.services.scraper_client.scraper_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.instagram_scraper.instaloader.Post.from_shortcode",
        lambda context, shortcode: (_ for _ in ()).throw(
            TooManyRequestsException("429 Too Many Requests")
        ),
    )
    monkeypatch.setattr(
        "app.services.scraper_client.fetch_instagram_post",
        lambda identifier, session: scraper_result
        if session == "anonymous"
        else scraper_result,
    )

    result = get_post_metadata("https://www.instagram.com/p/ABC123/")
    assert result.description == "From scraper"


def test_get_post_metadata_tries_all_four_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each layer is attempted in order until one succeeds."""
    from instaloader import TooManyRequestsException

    attempts: list[str] = []
    scraper_result = PostMetadataResponse(
        platform="instagram",
        kind="video",
        description="Layer 4 success",
        thumbnailUrl=None,
        authorHandle=None,
        publishedAt=None,
    )

    def fake_from_shortcode(context, shortcode):
        attempts.append("be")
        raise TooManyRequestsException("429")

    def fake_fetch_instagram_post(identifier: str, session: str) -> PostMetadataResponse:
        attempts.append(f"scraper:{session}")
        if session == "authenticated":
            return scraper_result
        raise InstagramScraperError("rate limit", status_code=429)

    _disable_chocodata(monkeypatch)
    monkeypatch.setattr(
        "app.services.instagram_scraper._session_for_mode",
        lambda mode: MagicMock() if mode in ("anonymous", "authenticated") else None,
    )
    monkeypatch.setattr(
        "app.services.scraper_client.scraper_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.instagram_scraper.instaloader.Post.from_shortcode",
        fake_from_shortcode,
    )
    monkeypatch.setattr(
        "app.services.scraper_client.fetch_instagram_post",
        fake_fetch_instagram_post,
    )

    result = get_post_metadata("https://www.instagram.com/p/ABC123/")
    assert result.description == "Layer 4 success"
    assert attempts == ["be", "be", "scraper:anonymous", "scraper:authenticated"]


def test_get_post_metadata_raises_when_all_layers_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When all layers hit rate limits, raise after exhausting them."""
    from instaloader import TooManyRequestsException

    _disable_chocodata(monkeypatch)
    monkeypatch.setattr(
        "app.services.instagram_scraper._session_for_mode",
        lambda mode: MagicMock() if mode in ("anonymous", "authenticated") else None,
    )
    monkeypatch.setattr(
        "app.services.scraper_client.scraper_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.instagram_scraper.instaloader.Post.from_shortcode",
        lambda context, shortcode: (_ for _ in ()).throw(
            TooManyRequestsException("429 Too Many Requests")
        ),
    )
    monkeypatch.setattr(
        "app.services.scraper_client.fetch_instagram_post",
        lambda identifier, session: (_ for _ in ()).throw(
            InstagramScraperError("rate limit", status_code=429)
        ),
    )

    with pytest.raises(InstagramScraperError, match="rate.limit"):
        get_post_metadata("https://www.instagram.com/p/ABC123/")


_CHOCODATA_POST = {
    "id": "DWm8OQKlKvC",
    "shortcode": "DWm8OQKlKvC",
    "media_type": "carousel",
    "is_video": False,
    "title": "NASA launches Artemis II to the moon!",
    "author": "agpfoto",
    "author_name": None,
    "images": ["https://example.com/1.jpg"],
    "thumbnail": "https://example.com/thumb.jpg",
    "caption": "NASA launches Artemis II to the moon!",
    "taken_at": "2026-04-02T00:02:44.000Z",
}


def _enable_chocodata(monkeypatch: pytest.MonkeyPatch, api_key: str = "cd_test_key") -> None:
    mock = MagicMock()
    mock.instagram_chocodata_enabled = True
    mock.choco_data_api_key = api_key
    mock.choco_data_country = "br"
    monkeypatch.setattr("app.services.instagram_scraper.get_settings", lambda: mock)


def test_map_chocodata_post_carousel() -> None:
    from app.services.chocodata_instagram import map_chocodata_post

    result = map_chocodata_post(_CHOCODATA_POST)
    assert result.platform == "instagram"
    assert result.kind == "carousel"
    assert result.description == "NASA launches Artemis II to the moon!"
    assert result.thumbnailUrl == "https://example.com/thumb.jpg"
    assert result.authorHandle == "agpfoto"
    assert result.publishedAt == "2026-04-02T00:02:44.000Z"


def test_map_chocodata_post_reel_without_taken_at() -> None:
    from app.services.chocodata_instagram import map_chocodata_post

    result = map_chocodata_post(
        {
            "media_type": "video",
            "product_type": "clips",
            "is_video": True,
            "caption": "Event this Saturday",
            "author": "venue",
            "thumbnail": "https://example.com/reel.jpg",
            "taken_at": None,
        }
    )
    assert result.kind == "video"
    assert result.description == "Event this Saturday"
    assert result.publishedAt is None
    assert result.authorHandle == "venue"


def test_map_chocodata_post_caption_div() -> None:
    from app.services.chocodata_instagram import map_chocodata_post

    result = map_chocodata_post(
        {
            "id": "DcQvVNhoBue",
            "shortcode": "DcQvVNhoBue",
            "media_type": "post",
            "is_video": None,
            "title": "Goiânia entra no clima do Rally dos Sertões 2026",
            "author": "guiacurtamais",
            "author_name": None,
            "images": [],
            "thumbnail": None,
            "caption": "Goiânia entra no clima do Rally dos Sertões 2026",
            "taken_at": None,
            "data_source": "caption-div",
        }
    )
    assert result.kind == "post"
    assert result.description == "Goiânia entra no clima do Rally dos Sertões 2026"
    assert result.authorHandle == "guiacurtamais"
    assert result.thumbnailUrl is None


def test_map_chocodata_post_strips_html_caption() -> None:
    from app.services.chocodata_instagram import map_chocodata_post

    result = map_chocodata_post(
        {
            "media_type": "post",
            "title": "Rally dos Sertões 2026",
            "author": "guiacurtamais",
            "caption": (
                "<div>Goiânia entra no clima do Rally dos Sertões 2026"
                "<br/>Ingressos em São Paulo</div>"
            ),
            "data_source": "caption-div",
        }
    )
    assert result.description is not None
    assert "<" not in result.description
    assert "Goiânia entra no clima do Rally dos Sertões 2026" in result.description
    assert "Ingressos em São Paulo" in result.description
    assert "&nbsp;" not in result.description


def test_map_chocodata_post_strips_view_all_comments() -> None:
    from app.services.chocodata_instagram import to_plain_text

    text = to_plain_text(
        "Festival no MuZa.\nAcesse o link na Bio | Curta Mais.View all comments"
    )
    assert text is not None
    assert "View all comments" not in text
    assert "Festival no MuZa." in text


def test_map_chocodata_post_prepends_distinct_title() -> None:
    from app.services.chocodata_instagram import map_chocodata_post

    result = map_chocodata_post(
        {
            "media_type": "post",
            "title": "Rock in Rio",
            "caption": "Shows no Parque Olímpico dia 13/09",
            "author": "rockinrio",
        }
    )
    assert result.description == "Rock in Rio\n\nShows no Parque Olímpico dia 13/09"


def test_map_chocodata_post_unwraps_nested_payload() -> None:
    from app.services.chocodata_instagram import map_chocodata_post

    result = map_chocodata_post(
        {
            "success": True,
            "post": {
                "media_type": "image",
                "caption": "Nested caption",
                "author_name": "nested_user",
                "thumbnail": "https://example.com/nested.jpg",
            },
        }
    )
    assert result.description == "Nested caption"
    assert result.authorHandle == "nested_user"
    assert result.thumbnailUrl == "https://example.com/nested.jpg"


def test_canonical_instagram_post_url_strips_query() -> None:
    from app.services.chocodata_instagram import canonical_instagram_post_url

    assert (
        canonical_instagram_post_url(
            "https://www.instagram.com/p/DcQvVNhoBue/?utm_source=ig_web_button_native_share"
        )
        == "https://www.instagram.com/p/DcQvVNhoBue/"
    )
    assert (
        canonical_instagram_post_url("https://www.instagram.com/reel/ABC123/")
        == "https://www.instagram.com/reel/ABC123/"
    )


def test_fetch_instagram_post_sends_url_and_country(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.chocodata_instagram import fetch_instagram_post

    captured: dict[str, object] = {}

    def fake_get(*args, **kwargs):
        captured["params"] = kwargs.get("params")
        return _mock_httpx_response(_CHOCODATA_POST)

    monkeypatch.setattr(httpx, "get", fake_get)

    fetch_instagram_post(
        "https://www.instagram.com/p/DWm8OQKlKvC/?utm_source=ig_web_button_native_share",
        "cd_test_key",
        country="br",
    )
    params = captured["params"]
    assert isinstance(params, dict)
    assert params["shortcode"] == "DWm8OQKlKvC"
    assert params["url"] == "https://www.instagram.com/p/DWm8OQKlKvC/"
    assert params["country"] == "br"
    assert params["api_key"] == "cd_test_key"


def test_map_chocodata_post_uses_first_image_when_thumbnail_missing() -> None:
    from app.services.chocodata_instagram import map_chocodata_post

    result = map_chocodata_post(
        {
            "media_type": "image",
            "is_video": False,
            "caption": "Hello",
            "author": "user",
            "images": ["https://example.com/first.jpg"],
        }
    )
    assert result.kind == "image"
    assert result.thumbnailUrl == "https://example.com/first.jpg"


def test_get_post_metadata_uses_chocodata_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_chocodata(monkeypatch)

    def fake_get(*args, **kwargs):
        return _mock_httpx_response(_CHOCODATA_POST)

    monkeypatch.setattr(httpx, "get", fake_get)
    instaloader_called = False

    def fail_instaloader(*args, **kwargs):
        nonlocal instaloader_called
        instaloader_called = True
        raise AssertionError("instaloader should not run when ChocoData is enabled")

    monkeypatch.setattr(
        "app.services.instagram_scraper.instaloader.Post.from_shortcode",
        fail_instaloader,
    )

    result = get_post_metadata("https://www.instagram.com/p/DWm8OQKlKvC/")
    assert result.description == "NASA launches Artemis II to the moon!"
    assert result.authorHandle == "agpfoto"
    assert result.kind == "carousel"
    assert instaloader_called is False


def test_get_post_metadata_chocodata_item_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_chocodata(monkeypatch)

    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 404
    resp.is_success = False
    resp.headers = {}
    resp.json.return_value = {
        "error": "item_not_found",
        "message": "not found",
        "request_id": "req_test",
    }

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: resp)

    with pytest.raises(InstagramScraperError, match="does not exist") as exc_info:
        get_post_metadata("https://www.instagram.com/p/missing/")
    assert exc_info.value.status_code == 404


def test_get_post_metadata_falls_back_to_instaloader_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = MagicMock()
    mock.instagram_chocodata_enabled = True
    mock.choco_data_api_key = "   "
    monkeypatch.setattr("app.services.instagram_scraper.get_settings", lambda: mock)

    fake_post = MagicMock()
    fake_post.typename = "GraphImage"
    fake_post.is_video = False
    fake_post.caption = "From instaloader"
    fake_post.url = "https://example.com/img.jpg"
    fake_post.owner_username = "author"
    fake_post.date_utc.isoformat.return_value = "2026-05-22T12:00:00"

    monkeypatch.setattr(
        "app.services.instagram_scraper._session_for_mode",
        lambda mode: MagicMock() if mode == "anonymous" else None,
    )
    monkeypatch.setattr(
        "app.services.scraper_client.scraper_is_configured",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.services.instagram_scraper.instaloader.Post.from_shortcode",
        lambda context, shortcode: fake_post,
    )

    chocodata_called = False

    def fail_chocodata(*args, **kwargs):
        nonlocal chocodata_called
        chocodata_called = True
        raise AssertionError("ChocoData should not run without an API key")

    monkeypatch.setattr(httpx, "get", fail_chocodata)

    result = get_post_metadata("https://www.instagram.com/p/ABC123/")
    assert result.description == "From instaloader"
    assert chocodata_called is False


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


# ── Enrich SQLite cache ───────────────────────────────────────────

@pytest.fixture
def enrich_cache_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = str(tmp_path / "enrich_cache.db")
    mock_settings = MagicMock()
    mock_settings.enrich_cache_enabled = True
    mock_settings.enrich_cache_db_path = db_path
    monkeypatch.setattr("app.services.enrich_cache.get_settings", lambda: mock_settings)

    import app.services.enrich_cache as enrich_cache_module

    enrich_cache_module._initialized_paths.clear()
    yield db_path
    enrich_cache_module._initialized_paths.clear()


@pytest.mark.parametrize(
    ("url", "expected_key"),
    [
        ("https://www.instagram.com/p/ABC123/", "instagram:ABC123"),
        ("https://www.instagram.com/reel/ABC123", "instagram:ABC123"),
        ("https://WWW.Example.COM/event/", "https://www.example.com/event"),
        ("https://example.com/path#fragment", "https://example.com/path"),
    ],
)
def test_normalize_enrich_url(url: str, expected_key: str) -> None:
    from app.services.enrich_cache import normalize_enrich_url

    assert normalize_enrich_url(url) == expected_key


def test_set_and_get_cached_enrich(enrich_cache_db: str) -> None:
    from app.services.enrich_cache import get_cached_enrich, set_cached_enrich

    url = "https://example.com/event"
    response = PostMetadataResponse(
        platform="unknown",
        kind="post",
        description="Event title",
        thumbnailUrl="https://example.com/thumb.jpg",
        authorHandle="Sympla",
        publishedAt=None,
    )

    set_cached_enrich(url, response)
    cached = get_cached_enrich(url)

    assert cached == response


def test_enrich_url_returns_cached_result_without_second_upstream_call(
    enrich_cache_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = 0
    sample = PostMetadataResponse(
        platform="tiktok",
        kind="video",
        description="Test desc",
        thumbnailUrl="https://img.example.com/thumb.jpg",
        authorHandle="testuser",
        publishedAt=None,
    )

    def fake_uncached(url: str) -> PostMetadataResponse:
        nonlocal call_count
        call_count += 1
        return sample

    monkeypatch.setattr(
        "app.services.enrich_dispatcher._enrich_url_uncached", fake_uncached
    )

    from app.services.enrich_dispatcher import enrich_url

    url = "https://www.tiktok.com/@user/video/123"
    first = enrich_url(url)
    second = enrich_url(url)

    assert first == sample
    assert second == sample
    assert call_count == 1


def test_enrich_url_does_not_cache_upstream_errors(
    enrich_cache_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_uncached(url: str) -> PostMetadataResponse:
        raise UpstreamError("upstream failed")

    monkeypatch.setattr(
        "app.services.enrich_dispatcher._enrich_url_uncached", fake_uncached
    )

    from app.services.enrich_cache import get_cached_enrich
    from app.services.enrich_dispatcher import enrich_url

    url = "https://www.tiktok.com/@user/video/456"
    with pytest.raises(UpstreamError, match="upstream failed"):
        enrich_url(url)

    assert get_cached_enrich(url) is None


def test_enrich_url_skips_cache_when_disabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = str(tmp_path / "disabled_enrich_cache.db")
    mock_settings = MagicMock()
    mock_settings.enrich_cache_enabled = False
    mock_settings.enrich_cache_db_path = db_path
    monkeypatch.setattr("app.services.enrich_cache.get_settings", lambda: mock_settings)

    call_count = 0
    sample = PostMetadataResponse(
        platform="unknown",
        kind="post",
        description="Event",
        thumbnailUrl=None,
        authorHandle=None,
        publishedAt=None,
    )

    def fake_uncached(url: str) -> PostMetadataResponse:
        nonlocal call_count
        call_count += 1
        return sample

    monkeypatch.setattr(
        "app.services.enrich_dispatcher._enrich_url_uncached", fake_uncached
    )

    from app.services.enrich_dispatcher import enrich_url

    url = "https://example.com/event"
    enrich_url(url)
    enrich_url(url)

    assert call_count == 2


# ── Event extraction (Groq via backend) ───────────────────────────


def test_extract_endpoint_returns_empty_when_groq_not_configured(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_settings = MagicMock()
    mock_settings.groq_api_key = ""
    mock_settings.groq_model = "llama-3.3-70b-versatile"
    monkeypatch.setattr(
        "app.services.event_extraction.get_settings", lambda: mock_settings
    )

    res = api_client.post(
        "/api/v1/enrich/extract",
        json={"description": "Show no Allianz Parque dia 03/07/2025 às 20:00"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["title"] is None
    assert body["dates"] == []
    assert body["location"] is None


def test_truncate_caption_keeps_start() -> None:
    from app.services.event_extraction import _MAX_CAPTION_CHARS, _truncate_caption

    short = "Rally dos Sertões"
    assert _truncate_caption(short) == short
    long = "a" * (_MAX_CAPTION_CHARS + 50)
    truncated = _truncate_caption(long)
    assert len(truncated) == _MAX_CAPTION_CHARS
    assert truncated == "a" * _MAX_CAPTION_CHARS


def test_extract_endpoint_rejects_empty_description(api_client: TestClient) -> None:
    res = api_client.post("/api/v1/enrich/extract", json={"description": ""})
    assert res.status_code == 422


def test_iso_to_display_date_accepts_display_and_iso() -> None:
    from datetime import date as date_cls

    from app.services.event_extraction import _normalize_time

    assert iso_to_display_date("03/07/2025") == "03/07/2025"
    assert iso_to_display_date("2025-07-03") == "03/07/2025"
    assert iso_to_display_date("not-a-date") is None
    assert iso_to_display_date("25/08", today=date_cls(2026, 8, 25)) == "25/08/2026"
    assert _normalize_time("19:00") == "19:00"
    assert _normalize_time("19h") == "19:00"
    assert _normalize_time("às 19h") == "19:00"
    assert _normalize_time("19h30") == "19:30"


def _enable_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_settings = MagicMock()
    mock_settings.groq_api_key = "gsk_test"
    mock_settings.groq_model = "qwen/qwen3.6-27b"
    monkeypatch.setattr(
        "app.services.event_extraction.get_settings", lambda: mock_settings
    )


def _groq_json_response(content: dict[str, object], status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(content)}}]
    }
    if status_code >= 400:
        request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=request, response=resp
        )
    else:
        resp.raise_for_status = MagicMock()
    return resp


def test_extract_event_sends_plain_json_example_and_caption_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.event_extraction import extract_event_from_description

    _enable_groq(monkeypatch)
    captured: dict[str, object] = {}

    def fake_post(*args, **kwargs):
        captured["json"] = kwargs.get("json")
        return _groq_json_response(
            {
                "title": "Show Allianz",
                "location": "Allianz Parque",
                "dates": ["03/07/2025"],
                "startTime": "20:00",
                "endTime": None,
                "reasoning": "Stated in caption",
            }
        )

    monkeypatch.setattr("app.services.event_extraction.httpx.post", fake_post)

    result = extract_event_from_description(
        "Show no Allianz Parque dia 03/07/2025 às 20:00",
        title="Turnê 2025",
    )

    body = captured["json"]
    assert isinstance(body, dict)
    assert body["reasoning_format"] == "hidden"
    assert body["response_format"] == {"type": "json_object"}
    user = body["messages"][1]["content"]
    assert "string | null" not in user
    assert '["DD/MM/YYYY"] | []' not in user
    assert '{"title": "Rock in Rio"' in user
    assert "Caption:" in user
    assert "Today's date is" in user
    assert "Show no Allianz Parque dia 03/07/2025 às 20:00" in user
    assert "Title:" in user
    assert "Turnê 2025" in user
    assert result.title == "Show Allianz"
    assert result.dates == ["03/07/2025"]
    assert result.startTime == "20:00"
    assert result.location == "Allianz Parque"


def test_extract_event_retries_without_json_mode_on_validate_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.event_extraction import extract_event_from_description

    _enable_groq(monkeypatch)
    calls: list[dict[str, object]] = []

    def fake_post(*args, **kwargs):
        payload = kwargs.get("json")
        assert isinstance(payload, dict)
        calls.append(payload)
        if len(calls) == 1:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 400
            resp.json.return_value = {
                "error": {
                    "type": "invalid_request_error",
                    "code": "json_validate_failed",
                    "failed_generation": '{"title":',
                }
            }
            return resp
        return _groq_json_response(
            {
                "title": "Festival de Inverno",
                "location": None,
                "dates": ["01/07/2025", "03/07/2025"],
                "startTime": None,
                "endTime": None,
                "reasoning": "Recovered on retry",
            }
        )

    monkeypatch.setattr("app.services.event_extraction.httpx.post", fake_post)

    result = extract_event_from_description("Festival de Inverno 01/07 a 03/07/2025")

    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]
    assert "reasoning_format" not in calls[1]
    assert result.title == "Festival de Inverno"
    assert result.dates == ["01/07/2025", "03/07/2025"]
