"""Tests for universal link verification and event share fallback routes."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.links import build_apple_app_site_association, build_assetlinks, build_event_fallback_html
from app.main import app

EVENT_ID = "11111111-2222-4333-8444-555555555555"


def _settings(**overrides: object) -> SimpleNamespace:
    defaults = {
        "ios_app_team_id": "FTHN8739FL",
        "ios_bundle_id": "com.matheushf.salvai",
        "android_package_name": "com.matheushf.salvai",
        "android_sha256_cert_fingerprints": "",
        "share_base_url": "https://salvai.cloud",
        "ios_app_store_url": "https://apps.apple.com/app/salvai/id0000000000",
        "android_play_store_url": (
            "https://play.google.com/store/apps/details?id=com.matheushf.salvai"
        ),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_build_apple_app_site_association() -> None:
    payload = build_apple_app_site_association(_settings())
    assert payload["applinks"]["details"][0]["appID"] == "FTHN8739FL.com.matheushf.salvai"
    assert payload["applinks"]["details"][0]["paths"] == ["/events/*"]


def test_build_assetlinks_without_fingerprints() -> None:
    assert build_assetlinks(_settings()) == []


def test_build_assetlinks_with_fingerprints() -> None:
    payload = build_assetlinks(
        _settings(
            android_sha256_cert_fingerprints=(
                "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:"
                "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99"
            )
        )
    )
    assert payload[0]["target"]["package_name"] == "com.matheushf.salvai"
    assert len(payload[0]["target"]["sha256_cert_fingerprints"]) == 1


def test_build_event_fallback_html_includes_links() -> None:
    html_body = build_event_fallback_html(
        event_id=EVENT_ID,
        share_base_url="https://salvai.cloud",
        deep_link_url=f"salvai://events/{EVENT_ID}",
        ios_app_store_url="https://apps.apple.com/app/salvai/id123",
        android_play_store_url="https://play.google.com/store/apps/details?id=com.matheushf.salvai",
    )
    assert f"salvai://events/{EVENT_ID}" in html_body
    assert "https://salvai.cloud/events/" in html_body


def test_apple_app_site_association_route() -> None:
    client = TestClient(app)
    response = client.get("/.well-known/apple-app-site-association")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["applinks"]["details"][0]["appID"] == "FTHN8739FL.com.matheushf.salvai"


def test_assetlinks_route() -> None:
    client = TestClient(app)
    response = client.get("/.well-known/assetlinks.json")
    assert response.status_code == 200
    assert response.json() == []


def test_event_share_fallback_route() -> None:
    client = TestClient(app)
    response = client.get(f"/events/{EVENT_ID}")
    assert response.status_code == 200
    assert "Open in Salvaí" in response.text
    assert f"salvai://events/{EVENT_ID}" in response.text


def test_event_share_fallback_rejects_invalid_id() -> None:
    client = TestClient(app)
    response = client.get("/events/not-a-uuid")
    assert response.status_code == 404
