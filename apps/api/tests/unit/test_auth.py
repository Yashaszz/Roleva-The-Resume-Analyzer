"""Tests for Supabase JWT verification.

Tokens are minted locally — with a shared secret for HS256, and with a
throwaway EC keypair for ES256 — so these exercise the real verification path
without needing a Supabase project.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from roleva.api import auth as auth_module
from roleva.api.auth import decode_token
from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings

# At least 32 bytes, matching what Supabase actually issues.
SECRET = "test-jwt-secret-value-padded-to-32-bytes-min"
USER_ID = "8f14e45f-ea8d-4b2c-9b7a-1c3d5e7f9a1b"
PROJECT_URL = "https://testproject.supabase.co"

_EC_KEY = ec.generate_private_key(ec.SECP256R1())
_EC_KID = "test-key-1"


def settings(secret: str = SECRET, url: str = "") -> Settings:
    return Settings(supabase_jwt_secret=secret, supabase_url=url)


def claims(
    *,
    expires_in: timedelta = timedelta(hours=1),
    audience: str = "authenticated",
    subject: str | None = USER_ID,
    **extra: Any,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "aud": audience,
        "exp": now + expires_in,
        "iat": now,
        "role": "authenticated",
        **extra,
    }
    if subject is not None:
        payload["sub"] = subject
    return payload


def hs256_token(*, secret: str = SECRET, **kwargs: Any) -> str:
    return jwt.encode(claims(**kwargs), secret, algorithm="HS256")


def es256_token(*, key: Any = None, **kwargs: Any) -> str:
    return jwt.encode(
        claims(**kwargs),
        key or _EC_KEY,
        algorithm="ES256",
        headers={"kid": _EC_KID},
    )


@pytest.fixture
def asymmetric(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Point the JWKS lookup at our throwaway public key instead of the network."""

    class FakeSigningKey:
        key = _EC_KEY.public_key()

    class FakeJwksClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        def get_signing_key_from_jwt(self, token: str) -> FakeSigningKey:
            header = jwt.get_unverified_header(token)
            if header.get("kid") != _EC_KID:
                raise jwt.PyJWKClientError("no matching key")
            return FakeSigningKey()

    monkeypatch.setattr(auth_module.jwt, "PyJWKClient", FakeJwksClient)
    auth_module._jwks_clients.clear()
    return settings(secret="", url=PROJECT_URL)


class TestAsymmetricTokens:
    """ES256 is what newer Supabase projects issue."""

    def test_a_valid_es256_token_identifies_the_user(self, asymmetric: Settings) -> None:
        user = decode_token(es256_token(), asymmetric)
        assert user.id == USER_ID

    def test_an_es256_token_signed_by_another_key_is_refused(self, asymmetric: Settings) -> None:
        attacker_key = ec.generate_private_key(ec.SECP256R1())
        with pytest.raises(RolevaError):
            decode_token(es256_token(key=attacker_key), asymmetric)

    def test_an_expired_es256_token_is_refused(self, asymmetric: Settings) -> None:
        with pytest.raises(RolevaError):
            decode_token(es256_token(expires_in=timedelta(hours=-1)), asymmetric)

    def test_an_unknown_key_id_is_refused(self, asymmetric: Settings) -> None:
        token = jwt.encode(claims(), _EC_KEY, algorithm="ES256", headers={"kid": "other"})
        with pytest.raises(RolevaError):
            decode_token(token, asymmetric)

    def test_verification_fails_closed_without_a_project_url(self) -> None:
        with pytest.raises(RolevaError):
            decode_token(es256_token(), settings(secret="", url=""))


class TestSymmetricTokens:
    """HS256 is what legacy projects issue; both schemes must keep working."""

    def test_a_valid_hs256_token_identifies_the_user(self) -> None:
        user = decode_token(hs256_token(), settings())
        assert user.id == USER_ID
        assert user.role == "authenticated"

    def test_a_confirmation_timestamp_marks_the_email_verified(self) -> None:
        token = hs256_token(email_confirmed_at="2026-01-01T00:00:00Z")
        assert decode_token(token, settings()).is_verified is True

    def test_a_boolean_claim_also_marks_the_email_verified(self) -> None:
        token = hs256_token(user_metadata={"email_verified": True})
        assert decode_token(token, settings()).is_verified is True

    def test_an_unconfirmed_account_is_not_verified(self) -> None:
        assert decode_token(hs256_token(), settings()).is_verified is False

    def test_verification_fails_closed_when_no_secret_is_configured(self) -> None:
        """A misconfigured server must reject everyone, not accept everyone."""
        with pytest.raises(RolevaError) as exc:
            decode_token(hs256_token(), settings(secret=""))
        assert exc.value.code is ErrorCode.UNAUTHORIZED


class TestAlgorithmConfusion:
    """The key source is bound to the algorithm, never mixed.

    The classic attack: take the project's *public* key, sign a token with
    HS256 using it as the HMAC secret, and hope the server verifies with
    whichever key it has to hand.
    """

    def test_an_hs256_token_is_never_verified_against_a_jwks_key(
        self, asymmetric: Settings
    ) -> None:
        public_pem = _EC_KEY.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        # Built by hand: PyJWT refuses to *mint* this, which is itself a defence,
        # but an attacker has no such scruples. The token has to be assembled
        # directly to prove the verifier rejects it on its own merits.
        header = jwt.utils.base64url_encode(
            json.dumps({"alg": "HS256", "typ": "JWT", "kid": _EC_KID}).encode()
        )
        payload = jwt.utils.base64url_encode(
            json.dumps(claims(), default=lambda o: int(o.timestamp())).encode()
        )
        signing_input = header + b"." + payload
        signature = jwt.utils.base64url_encode(
            hmac.new(public_pem, signing_input, hashlib.sha256).digest()
        )
        forged = (signing_input + b"." + signature).decode()

        # The project has no shared secret configured, so this must fail rather
        # than fall back to the public key it holds for ES256.
        with pytest.raises(RolevaError):
            decode_token(forged, asymmetric)

    def test_an_es256_token_is_never_verified_against_the_shared_secret(self) -> None:
        """A symmetric-only server must refuse an asymmetric token outright."""
        with pytest.raises(RolevaError):
            decode_token(es256_token(), settings(secret=SECRET, url=""))


class TestRejection:
    """Every rejection returns the same error: detail would help an attacker."""

    @pytest.mark.parametrize(
        ("label", "token_factory"),
        [
            (
                "wrong signing key",
                lambda: hs256_token(secret="attacker-secret-also-32-bytes-long-here"),
            ),
            ("expired", lambda: hs256_token(expires_in=timedelta(hours=-1))),
            ("wrong audience", lambda: hs256_token(audience="anon")),
            ("no subject", lambda: hs256_token(subject=None)),
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
        forged = jwt.encode(claims(), key="", algorithm="none")
        with pytest.raises(RolevaError):
            decode_token(forged, settings())

    def test_an_unexpected_algorithm_is_refused(self) -> None:
        header = jwt.utils.base64url_encode(
            json.dumps({"alg": "HS512", "typ": "JWT"}).encode()
        ).decode()
        payload = jwt.utils.base64url_encode(json.dumps({"sub": USER_ID}).encode()).decode()
        with pytest.raises(RolevaError):
            decode_token(f"{header}.{payload}.signature", settings())
