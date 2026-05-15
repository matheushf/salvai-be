from functools import lru_cache
from typing import Annotated

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


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> AuthenticatedUser:
    """
    FastAPI dependency that validates the Supabase JWT from the Authorization header
    and returns the authenticated user. Raises 401 on any validation failure.

    Supabase may sign user JWTs with:

    - **HS256** using the project's JWT secret (legacy / some configs), or
    - **ES256** / **RS256** with keys published at
      `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`.

    Validation steps:

    1. Signature verified (symmetric secret for HS256, JWKS for ES256/RS256).
    2. ``aud`` must be ``authenticated`` (Supabase-issued user token).
    3. ``iss`` must match ``<SUPABASE_URL>/auth/v1``.
    4. ``sub`` must be present (the user UUID).
    5. Expiry checked with short leeway for clock skew.
    """
    token = credentials.credentials
    settings = get_settings()

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

        issuer = settings.supabase_jwt_issuer

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
            jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
            jwk_client = _jwks_client(jwks_url)
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
            raise credentials_exception
    except ExpiredSignatureError:
        raise expired_exception
    except PyJWTError:
        raise credentials_exception

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise credentials_exception

    return AuthenticatedUser(
        id=user_id,
        email=payload.get("email"),
        role=payload.get("role", "authenticated"),
    )


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
