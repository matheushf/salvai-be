"""JWT auth must return 401, never a generic 500, when the token is unusable."""

from __future__ import annotations

import json
import time
from base64 import urlsafe_b64encode
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError

from app.core.auth import (
    _JWKS_TIMEOUT_SECONDS,
    _jwks_client,
    _token_debug_meta,
    prefetch_jwks as prefetch_jwks_impl,
)
from app.main import app


def _b64url(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unsigned_es256_token() -> str:
    header = _b64url({"alg": "ES256", "kid": "test-kid", "typ": "JWT"})
    payload = _b64url(
        {
            "sub": "user-1",
            "aud": "authenticated",
            "iss": "http://localhost:54321/auth/v1",
            "exp": int(time.time()) + 3600,
        }
    )
    return f"{header}.{payload}.fakesig"


def test_invalid_bearer_token_returns_401_not_500() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/profiles/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid authentication token"


def test_missing_bearer_token_is_not_500() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/profiles/me")
    assert res.status_code in {401, 403}


def test_jwks_client_uses_short_timeout() -> None:
    _jwks_client.cache_clear()
    client = _jwks_client("http://localhost:54321/auth/v1/.well-known/jwks.json")
    assert client.timeout == _JWKS_TIMEOUT_SECONDS
    assert client.jwk_set_cache is not None


def test_es256_jwks_timeout_returns_401_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_jwks = MagicMock()
    mock_jwks.get_signing_key_from_jwt.side_effect = PyJWKClientConnectionError(
        'Fail to fetch data from the url, err: "timed out"'
    )
    monkeypatch.setattr("app.core.auth._jwks_client", lambda _url: mock_jwks)

    client = TestClient(app)
    res = client.get(
        "/api/v1/profiles/me",
        headers={"Authorization": f"Bearer {_unsigned_es256_token()}"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid authentication token"


def test_prefetch_jwks_logs_failure_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_jwks = MagicMock()
    mock_jwks.get_jwk_set.side_effect = PyJWKClientConnectionError(
        'Fail to fetch data from the url, err: "timed out"'
    )
    monkeypatch.setattr("app.core.auth._jwks_client", lambda _url: mock_jwks)

    prefetch_jwks_impl()


def test_prefetch_jwks_logs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_jwks = MagicMock()
    mock_jwks.get_jwk_set.return_value = MagicMock(keys=["k1", "k2"])
    monkeypatch.setattr("app.core.auth._jwks_client", lambda _url: mock_jwks)

    prefetch_jwks_impl()
    mock_jwks.get_jwk_set.assert_called_once_with(refresh=True)


def test_token_debug_meta_includes_timing_and_expected_iss() -> None:
    now = int(time.time())
    header = _b64url({"alg": "ES256", "kid": "abc-kid", "typ": "JWT"})
    payload = _b64url(
        {
            "sub": "ddf3c965-9fb1-4e54-aa59-ae409f5964dc",
            "aud": "authenticated",
            "iss": "https://example.supabase.co/auth/v1",
            "role": "authenticated",
            "exp": now + 120,
            "iat": now - 10,
        }
    )
    meta = _token_debug_meta(
        f"{header}.{payload}.sig",
        expected_iss="https://example.supabase.co/auth/v1",
    )
    assert "alg=ES256" in meta
    assert "kid=abc-kid" in meta
    assert "expected_iss=https://example.supabase.co/auth/v1" in meta
    assert "sub=ddf3c965" in meta
    assert "exp_in_s=" in meta
    assert "iat_age_s=" in meta
    assert "parts=3" in meta


def test_expired_hs256_returns_token_expired_detail() -> None:
    import jwt as pyjwt

    token = pyjwt.encode(
        {
            "sub": "user-1",
            "aud": "authenticated",
            "iss": "http://localhost:54321/auth/v1",
            "exp": int(time.time()) - 120,
            "iat": int(time.time()) - 240,
        },
        "test-jwt-secret-for-pytest",
        algorithm="HS256",
    )
    client = TestClient(app)
    res = client.get("/api/v1/profiles/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Token has expired"
