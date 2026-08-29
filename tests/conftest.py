"""Ensure Settings-required env vars exist before `app` is imported by tests."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret-for-pytest")
os.environ.setdefault("INSTAGRAM_CHOCODATA_ENABLED", "false")
os.environ.setdefault("CHOCO_DATA_API_KEY", "")


@pytest.fixture(autouse=True)
def _skip_jwks_prefetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifespan must not hit a real JWKS URL (3s timeout) on every TestClient."""
    monkeypatch.setattr("app.core.auth.prefetch_jwks", lambda: None)
