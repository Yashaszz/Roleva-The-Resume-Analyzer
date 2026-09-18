"""Supabase JWT verification.

The browser talks to Supabase Auth directly and receives a signed JWT. Roleva's
backend never sees a password; it only verifies the token's signature and reads
the user id from it.

Two independent protections, deliberately:

  * This middleware, which decides whether a request is authenticated at all.
  * Row Level Security in Postgres, which refuses cross-user reads even if a
    bug here lets the wrong user through.

Neither is trusted to be sufficient on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings, get_settings

#: Supabase signs access tokens with this audience claim.
_AUDIENCE = "authenticated"

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email_verified: bool
    role: str

    @property
    def is_verified(self) -> bool:
        return self.email_verified


def decode_token(token: str, settings: Settings) -> AuthenticatedUser:
    """Verify a Supabase access token and extract the caller's identity.

    Signature, expiry and audience are all checked. A token that fails any of
    them is indistinguishable, from the caller's point of view, from no token
    at all — error detail here would only help an attacker.
    """
    if not settings.supabase_jwt_secret:
        raise RolevaError(
            ErrorCode.UNAUTHORIZED,
            "Authentication is not configured on this server.",
        )

    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience=_AUDIENCE,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise RolevaError(ErrorCode.UNAUTHORIZED) from exc

    subject = claims.get("sub")
    if not subject:
        raise RolevaError(ErrorCode.UNAUTHORIZED)

    # Supabase reports verification either as a boolean claim or as a
    # confirmation timestamp, depending on how the project is configured.
    metadata = claims.get("user_metadata") or {}
    email_verified = bool(
        claims.get("email_confirmed_at")
        or metadata.get("email_verified")
        or claims.get("email_verified")
    )

    return AuthenticatedUser(
        id=str(subject),
        email_verified=email_verified,
        role=str(claims.get("role", "authenticated")),
    )


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedUser:
    """FastAPI dependency: the signed-in user, or a 401."""
    if credentials is None or not credentials.credentials:
        raise RolevaError(ErrorCode.UNAUTHORIZED)

    user = decode_token(credentials.credentials, settings)
    # Bound here so downstream logs carry the user id without any call site
    # having to pass it — and the id is a UUID, not personal data.
    request.state.user_id = user.id
    return user


async def verified_user(
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> AuthenticatedUser:
    """Analysis endpoints require a verified email.

    Unverified accounts are the cheapest way to burn a shared free-tier quota,
    so verification is the gate on anything that costs an LLM request.
    """
    if not user.is_verified:
        raise RolevaError(
            ErrorCode.UNAUTHORIZED,
            "Please verify your email address before running an analysis.",
        )
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]
VerifiedUser = Annotated[AuthenticatedUser, Depends(verified_user)]
