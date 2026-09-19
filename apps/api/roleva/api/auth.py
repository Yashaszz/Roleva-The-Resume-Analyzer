"""Supabase JWT verification.

The browser talks to Supabase Auth directly and receives a signed JWT. Roleva's
backend never sees a password; it only verifies the token's signature and reads
the user id from it.

Supabase issues tokens under two different schemes, and a project can migrate
from one to the other, so both are supported:

  * **ES256 / RS256** — asymmetric. The project publishes public keys at a JWKS
    endpoint; the private key never leaves Supabase. This is the default for
    newer projects.
  * **HS256** — a shared secret in `SUPABASE_JWT_SECRET`. Legacy projects.

Which one applies is decided by the token's own `alg` header, but the key
*source* is bound to the algorithm and never mixed: a shared secret is only ever
used for HS256, and a JWKS public key only ever for ES256/RS256. That separation
is what blocks the classic algorithm-confusion attack, where an attacker signs a
token with HS256 using a public key as the HMAC secret.

Verification sits alongside Row Level Security rather than replacing it. Neither
is trusted to be sufficient on its own.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings, get_settings

#: Supabase signs access tokens with this audience claim.
_AUDIENCE = "authenticated"

#: Asymmetric algorithms verified against the project's published public keys.
_ASYMMETRIC = ("ES256", "RS256")

#: The only symmetric algorithm accepted, and only with the shared secret.
_SYMMETRIC = ("HS256",)

_bearer = HTTPBearer(auto_error=False)

# PyJWKClient caches fetched keys, but building one performs no I/O, so a client
# per project URL is created once and reused. The lock keeps two concurrent
# first-requests from each building their own.
_jwks_clients: dict[str, jwt.PyJWKClient] = {}
_jwks_lock = threading.Lock()


def _jwks_client(settings: Settings) -> jwt.PyJWKClient:
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    client = _jwks_clients.get(url)
    if client is None:
        with _jwks_lock:
            client = _jwks_clients.get(url)
            if client is None:
                client = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)
                _jwks_clients[url] = client
    return client


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email_verified: bool
    role: str

    @property
    def is_verified(self) -> bool:
        return self.email_verified


def _resolve_key(token: str, settings: Settings) -> tuple[Any, tuple[str, ...]]:
    """Pick the verification key from the token's declared algorithm.

    Returns the key together with the *only* algorithms it may be used for, so
    the caller cannot accidentally verify an HS256 token against a public key.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise RolevaError(ErrorCode.UNAUTHORIZED) from exc

    algorithm = header.get("alg")

    if algorithm in _ASYMMETRIC:
        if not settings.supabase_url:
            raise RolevaError(
                ErrorCode.UNAUTHORIZED,
                "Authentication is not configured on this server.",
            )
        try:
            return _jwks_client(settings).get_signing_key_from_jwt(token).key, _ASYMMETRIC
        except jwt.PyJWTError as exc:
            raise RolevaError(ErrorCode.UNAUTHORIZED) from exc

    if algorithm in _SYMMETRIC:
        if not settings.supabase_jwt_secret:
            raise RolevaError(
                ErrorCode.UNAUTHORIZED,
                "Authentication is not configured on this server.",
            )
        return settings.supabase_jwt_secret, _SYMMETRIC

    # Anything else, including "none", is refused outright.
    raise RolevaError(ErrorCode.UNAUTHORIZED)


def decode_token(token: str, settings: Settings) -> AuthenticatedUser:
    """Verify a Supabase access token and extract the caller's identity.

    Signature, expiry and audience are all checked. A token failing any of them
    is indistinguishable, from the caller's point of view, from no token at all —
    error detail here would only help an attacker.
    """
    key, algorithms = _resolve_key(token, settings)

    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=list(algorithms),
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
