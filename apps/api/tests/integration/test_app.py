"""End-to-end checks against the running app."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from roleva.config import Settings, get_settings
from roleva.main import app

SECRET = "integration-jwt-secret-padded-to-32-bytes"
USER_ID = "3b1f0c2a-7d4e-4f18-9a55-2e6b8c1d0f33"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def authed_client() -> TestClient:
    """A client whose tokens the app will actually accept."""
    app.dependency_overrides[get_settings] = lambda: Settings(supabase_jwt_secret=SECRET)
    yield TestClient(app)
    app.dependency_overrides.clear()


def token(**extra: object) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": USER_ID,
            "aud": "authenticated",
            "exp": now + timedelta(hours=1),
            "iat": now,
            **extra,
        },
        SECRET,
        algorithm="HS256",
    )


class TestHealth:
    def test_health_is_open_and_reports_ok(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_every_response_carries_a_request_id(self, client: TestClient) -> None:
        assert client.get("/health").headers.get("x-request-id")

    def test_a_caller_supplied_request_id_is_preserved(self, client: TestClient) -> None:
        response = client.get("/health", headers={"x-request-id": "trace-me"})
        assert response.headers["x-request-id"] == "trace-me"


class TestProtectedRoutes:
    def test_a_request_without_a_token_is_rejected(self, client: TestClient) -> None:
        response = client.get("/me")
        assert response.status_code == 401
        assert response.json()["code"] == "unauthorized"

    def test_a_forged_token_is_rejected(self, authed_client: TestClient) -> None:
        forged = jwt.encode(
            {"sub": USER_ID, "aud": "authenticated"}, "wrong-secret-value-here-padded-32b"
        )
        response = authed_client.get("/me", headers={"Authorization": f"Bearer {forged}"})
        assert response.status_code == 401

    def test_a_valid_token_identifies_the_user(self, authed_client: TestClient) -> None:
        response = authed_client.get("/me", headers={"Authorization": f"Bearer {token()}"})
        assert response.status_code == 200
        assert response.json()["id"] == USER_ID

    def test_the_response_does_not_echo_personal_data(self, authed_client: TestClient) -> None:
        response = authed_client.get(
            "/me",
            headers={"Authorization": f"Bearer {token(email='priya@example.com')}"},
        )
        assert "priya@example.com" not in response.text


class TestErrorShape:
    def test_errors_are_machine_readable(self, client: TestClient) -> None:
        body = client.get("/me").json()
        assert set(body) == {"code", "message"}
        assert isinstance(body["message"], str)

    def test_errors_never_leak_a_stack_trace(self, client: TestClient) -> None:
        text = client.get("/me").text
        assert "Traceback" not in text
        assert "roleva/" not in text
