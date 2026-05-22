"""Tests for URL enrichment endpoint and services."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import UpstreamError
from app.main import app
from app.schemas.instagram import PostMetadataResponse
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


# ── Webpage service ───────────────────────────────────────────────

_SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Awesome Event 2026</title>
  <meta property="og:title" content="Awesome Event 2026 — Tickets">
  <meta property="og:description" content="Join us for the best event of the year">
  <meta property="og:image" content="https://example.com/hero.jpg">
  <meta property="og:site_name" content="Sympla">
  <meta name="description" content="Fallback description">
  <script type="application/ld+json">
  {
    "@type": "Event",
    "name": "Awesome Event 2026",
    "startDate": "2026-06-15T20:00:00",
    "endDate": "2026-06-16T02:00:00",
    "location": {"name": "Audio Club, Sao Paulo"}
  }
  </script>
</head>
<body>
  <article>
    <h1>Awesome Event 2026</h1>
    <p>The biggest electronic music festival. Join us at Audio Club on June 15th.</p>
    <nav>Home | About | Contact</nav>
  </article>
</body>
</html>"""


def test_webpage_enrich_extracts_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = MagicMock(spec=httpx.Response)
    resp.text = _SAMPLE_HTML
    resp.raise_for_status.return_value = None

    def fake_get(*args, **kwargs):
        return resp

    monkeypatch.setattr(httpx, "get", fake_get)

    from app.services.webpage_service import enrich_webpage

    result = enrich_webpage("https://www.sympla.com.br/event")

    assert result.platform == "unknown"
    assert result.kind == "post"
    assert result.thumbnailUrl == "https://example.com/hero.jpg"
    assert result.authorHandle == "Sympla"
    assert result.publishedAt is None
    assert result.description is not None
    assert "Awesome Event 2026" in result.description
    assert "startDate: 2026-06-15T20:00:00" in result.description
    assert "Audio Club" in result.description


def test_webpage_enrich_handles_minimal_html(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = MagicMock(spec=httpx.Response)
    resp.text = "<html><head><title>Minimal</title></head><body><p>Hello.</p></body></html>"
    resp.raise_for_status.return_value = None

    def fake_get(*args, **kwargs):
        return resp

    monkeypatch.setattr(httpx, "get", fake_get)

    from app.services.webpage_service import enrich_webpage

    result = enrich_webpage("https://example.com")
    assert result.platform == "unknown"
    assert result.description is not None
    assert "Minimal" in result.description


def test_webpage_enrich_raises_upstream_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(*args, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "get", fake_get)

    from app.services.webpage_service import enrich_webpage

    with pytest.raises(UpstreamError, match="timed out"):
        enrich_webpage("https://example.com")


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
