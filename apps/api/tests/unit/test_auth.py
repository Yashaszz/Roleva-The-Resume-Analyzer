"""Tests for Supabase JWT verification.

Tokens are minted locally with a known secret, so these exercise the real
verification path without needing a Supabase project.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest

from roleva.api.auth import decode_token
from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings

# At least 32 bytes, matching what Supabase actually issues.
SECRET = "test-jwt-secret-value-padded-to-32-bytes-min"
USER_ID = "8f14e45f-ea8d-4b2c-9b7a-1c3d5e7f9a1b"


def settings(secret: str = SECRET) -> Settings:
    return Settings(supabase_jwt_secret=secret)


def make_token(
    *,
    secret: str = SECRET,
    expires_in: timedelta = timedelta(hours=1),
    audience: str = "authenticated",
    subject: str | None = USER_ID,
    algorithm: str = "HS256",
    **extra: Any,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "aud": audience,
        "exp": now + expires_in,
        "iat": now,
        "role": "authenticated",
        **extra,
    }
    if subject is not None:
        claims["sub"] = subject
    return jwt.encode(claims, secret, algorithm=algorithm)


class TestValidTokens:
    def test_a_well_formed_token_identifies_the_user(self) -> None:
        user = decode_token(make_token(), settings())
        assert user.id == USER_ID
        assert user.role == "authenticated"

    def test_a_confirmation_timestamp_marks_the_email_verified(self) -> None:
        token = make_token(email_confirmed_at="2026-01-01T00:00:00Z")
        assert decode_token(token, settings()).is_verified is True

    def test_a_boolean_claim_also_marks_the_email_verified(self) -> None:
        token = make_token(user_metadata={"email_verified": True})
        assert decode_token(token, settings()).is_verified is True

    def test_an_unconfirmed_account_is_not_verified(self) -> None:
        assert decode_token(make_token(), settings()).is_verified is False


class TestRejection:
    """Every rejection returns the same error: detail would help an attacker."""

    @pytest.mark.parametrize(
        ("label", "token_factory"),
        [
            (
                "wrong signing key",
                lambda: make_token(secret="attacker-secret-also-32-bytes-long-here"),
            ),
            ("expired", lambda: make_token(expires_in=timedelta(hours=-1))),
            ("wrong audience", lambda: make_token(audience="anon")),
            ("no subject", lambda: make_token(subject=None)),
            ("not a jwt", lambda: "not-a-token"),
            ("empty", lambda: ""),
        ],
    )
    def test_invalid_tokens_are_refused(self, label: str, token_factory: Any) -> None:
        with pytest.raises(RolevaError) as exc:
            decode_token(token_factory(), settings())
        assert exc.value.code is ErrorCode.UNAUTHORIZED

    def test_an_unsigned_token_is_refused(self) -> None:
        """The `alg: none` attack — a token with no signature at all."""
        forged = jwt.encode({"sub": USER_ID, "aud": "authenticated"}, key="", algorithm="none")
        with pytest.raises(RolevaError):
            decode_token(forged, settings())

    def test_verification_fails_closed_when_no_secret_is_configured(self) -> None:
        """A misconfigured server must reject everyone, not accept everyone."""
        with pytest.raises(RolevaError) as exc:
            decode_token(make_token(), settings(secret=""))
        assert exc.value.code is ErrorCode.UNAUTHORIZED
