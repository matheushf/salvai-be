import logging
import os
import time
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import ExpiredSignatureError, PyJWTError

from app.core.config import get_settings
from app.schemas.user import AuthenticatedUser

_bearer = HTTPBearer(auto_error=True)

_AUDIENCE = "authenticated"

# Allow a short clock-skew window between client and server clocks.
_LEEWAY_SECONDS = 10

_SUPPORTED_ASYM_ALGS = frozenset({"ES256", "RS256"})

# PyJWKClient defaults to 30s; a hanging JWKS fetch makes every API call look stuck.
_JWKS_TIMEOUT_SECONDS = 3.0
_JWKS_CACHE_LIFESPAN_SECONDS = 300.0
_EXC_MESSAGE_MAX = 200

logger = logging.getLogger("app.auth")


def _cloud_revision() -> str:
    return os.environ.get("K_REVISION") or "-"


class _LoggedJWKClient(PyJWKClient):
    """Same as PyJWKClient, but logs every network fetch (cache misses)."""

    def fetch_data(self) -> Any:
        started = time.monotonic()
        try:
            data = super().fetch_data()
        except Exception as exc:
            logger.warning(
                "jwks_fetch failed url=%s duration_ms=%.0f error=%s message=%s revision=%s",
                self.uri,
                (time.monotonic() - started) * 1000,
                type(exc).__name__,
                _safe_exc_message(exc),
                _cloud_revision(),
            )
            raise

        kids: list[str] = []
        if isinstance(data, dict):
            keys = data.get("keys")
            if isinstance(keys, list):
                for key in keys:
                    if isinstance(key, dict) and key.get("kid"):
                        kids.append(str(key["kid"]))

        logger.info(
            "jwks_fetch ok url=%s duration_ms=%.0f key_count=%s kids=%s revision=%s",
            self.uri,
            (time.monotonic() - started) * 1000,
            len(kids),
            ",".join(kids) or "-",
            _cloud_revision(),
        )
        return data


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return _LoggedJWKClient(
        jwks_url,
        cache_jwk_set=True,
        cache_keys=True,
        lifespan=_JWKS_CACHE_LIFESPAN_SECONDS,
        timeout=_JWKS_TIMEOUT_SECONDS,
    )


def _safe_exc_message(exc: BaseException) -> str:
    message = str(exc).replace("\n", " ").strip()
    if len(message) > _EXC_MESSAGE_MAX:
        return message[:_EXC_MESSAGE_MAX] + "…"
    return message


def _claim_int(payload: dict[str, Any], name: str) -> int | None:
    value = payload.get(name)
    return value if isinstance(value, int) else None


def _token_debug_meta(token: str, *, expected_iss: str | None = None) -> str:
    """Unverified header/claims for logs. Never includes the token itself."""
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
        now = int(time.time())
        exp = _claim_int(payload, "exp")
        iat = _claim_int(payload, "iat")
        sub = payload.get("sub")
        sub_prefix = sub[:8] if isinstance(sub, str) and sub else "-"
        parts = [
            f"alg={header.get('alg')}",
            f"kid={header.get('kid')}",
            f"iss={payload.get('iss')}",
            f"expected_iss={expected_iss or '-'}",
            f"aud={payload.get('aud')}",
            f"role={payload.get('role')}",
            f"sub={sub_prefix}",
            f"exp_in_s={exp - now if exp is not None else '-'}",
            f"iat_age_s={now - iat if iat is not None else '-'}",
            f"parts={token.count('.') + 1}",
            f"revision={_cloud_revision()}",
        ]
        return " ".join(parts)
    except Exception:
        return f"unreadable-token parts={token.count('.') + 1} revision={_cloud_revision()}"


def _log_jwt_verify_failed(
    token: str,
    *,
    expected_iss: str,
    error: str,
    message: str = "",
    verify_ms: float | None = None,
) -> None:
    extra = f" verify_ms={verify_ms:.0f}" if verify_ms is not None else ""
    if message:
        logger.warning(
            "jwt_verify_failed %s error=%s message=%s%s",
            _token_debug_meta(token, expected_iss=expected_iss),
            error,
            message,
            extra,
        )
        return
    logger.warning(
        "jwt_verify_failed %s error=%s%s",
        _token_debug_meta(token, expected_iss=expected_iss),
        error,
        extra,
    )


def prefetch_jwks() -> None:
    """Fetch and cache JWKS at process start so the first user request is not the probe."""
    url = get_settings().supabase_jwks_url
    started = time.monotonic()
    try:
        jwk_set = _jwks_client(url).get_jwk_set(refresh=True)
        kids = [key.key_id or "?" for key in jwk_set.keys]
        logger.info(
            "jwks_prefetch ok url=%s duration_ms=%.0f keys=%s kids=%s revision=%s",
            url,
            (time.monotonic() - started) * 1000,
            len(jwk_set.keys),
            ",".join(kids) or "-",
            _cloud_revision(),
        )
    except Exception as exc:
        logger.warning(
            "jwks_prefetch failed url=%s duration_ms=%.0f error=%s message=%s revision=%s",
            url,
            (time.monotonic() - started) * 1000,
            type(exc).__name__,
            _safe_exc_message(exc),
            _cloud_revision(),
        )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> AuthenticatedUser:
    """
    FastAPI dependency that validates the Supabase JWT from the Authorization header
    and returns the authenticated user. Raises 401 on any validation failure.

    Supabase may sign user JWTs with:

    - **HS256** using the project's JWT secret (legacy / some configs), or
    - **ES256** / **RS256** with keys published at
      ``<SUPABASE_URL>/auth/v1/.well-known/jwks.json``.

    Validation steps:

    1. Signature verified (symmetric secret for HS256, JWKS for ES256/RS256).
    2. ``aud`` must be ``authenticated`` (Supabase-issued user token).
    3. ``iss`` must match ``<SUPABASE_URL>/auth/v1``.
    4. ``sub`` must be present (the user UUID).
    5. Expiry checked with short leeway for clock skew.
    """
    token = credentials.credentials
    settings = get_settings()
    issuer = settings.supabase_jwt_issuer
    started = time.monotonic()

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    expired_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token has expired",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg") or "HS256"

        if alg == "HS256":
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=_AUDIENCE,
                issuer=issuer,
                leeway=_LEEWAY_SECONDS,
            )
        elif alg in _SUPPORTED_ASYM_ALGS:
            jwk_client = _jwks_client(settings.supabase_jwks_url)
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[alg],
                audience=_AUDIENCE,
                issuer=issuer,
                leeway=_LEEWAY_SECONDS,
            )
        else:
            _log_jwt_verify_failed(
                token,
                expected_iss=issuer,
                error="unsupported_alg",
                verify_ms=(time.monotonic() - started) * 1000,
            )
            raise credentials_exception
    except ExpiredSignatureError:
        _log_jwt_verify_failed(
            token,
            expected_iss=issuer,
            error="ExpiredSignatureError",
            verify_ms=(time.monotonic() - started) * 1000,
        )
        raise expired_exception
    except HTTPException:
        raise
    except PyJWTError as exc:
        _log_jwt_verify_failed(
            token,
            expected_iss=issuer,
            error=type(exc).__name__,
            message=_safe_exc_message(exc),
            verify_ms=(time.monotonic() - started) * 1000,
        )
        raise credentials_exception from exc
    except Exception as exc:
        # JWKS/network/crypto failures must not become HTTP 500s.
        _log_jwt_verify_failed(
            token,
            expected_iss=issuer,
            error=type(exc).__name__,
            message=_safe_exc_message(exc),
            verify_ms=(time.monotonic() - started) * 1000,
        )
        raise credentials_exception from exc

    user_id: str | None = payload.get("sub")
    if not user_id:
        _log_jwt_verify_failed(
            token,
            expected_iss=issuer,
            error="missing_sub",
            verify_ms=(time.monotonic() - started) * 1000,
        )
        raise credentials_exception

    return AuthenticatedUser(
        id=user_id,
        email=payload.get("email"),
        role=payload.get("role", "authenticated"),
    )


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
