"""JWT auth must return 401, never a generic 500, when the token is unusable."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_invalid_bearer_token_returns_401_not_500() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/profiles/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid authentication token"


def test_missing_bearer_token_is_not_500() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/profiles/me")
    assert res.status_code in {401, 403}
