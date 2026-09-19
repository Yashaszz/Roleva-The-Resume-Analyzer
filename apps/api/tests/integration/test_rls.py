"""Row Level Security, proved against the live Supabase project.

This is the test Gate 0 exists for. Roleva stores resumes — employment history,
education, contact details — and the promise that one user cannot read
another's has to be demonstrated rather than assumed.

It is deliberately an end-to-end test against the real database. RLS is enforced
by Postgres, not by application code, so mocking it would prove nothing: the
only meaningful question is whether the database itself refuses the read.

Two real users are created, one writes a resume, and the other attempts every
way of getting at it. The run cleans up after itself even when assertions fail.

Skipped automatically when Supabase is not configured, so CI without secrets
stays green.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from roleva.config import get_settings

settings = get_settings()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (settings.supabase_url and settings.supabase_service_role_key),
        reason="Supabase not configured; set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY",
    ),
]

TIMEOUT = 30.0


@dataclass
class SupabaseUser:
    id: str
    email: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        """Requests carry the user's own token, so RLS applies to them.

        This is how the backend talks to the database for user-owned rows — the
        service role key is never used for them, precisely so that a bug cannot
        quietly bypass the isolation this test checks.
        """
        return {
            "apikey": settings.supabase_anon_key,
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }


def _admin_headers() -> dict[str, str]:
    key = settings.supabase_service_role_key
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _create_user(client: httpx.Client, label: str) -> SupabaseUser:
    email = f"rls-{label}-{uuid.uuid4().hex[:10]}@roleva-test.invalid"
    password = f"Test-{uuid.uuid4().hex[:16]}!aA1"

    created = client.post(
        f"{settings.supabase_url}/auth/v1/admin/users",
        headers=_admin_headers(),
        json={"email": email, "password": password, "email_confirm": True},
    )
    created.raise_for_status()
    user_id = created.json()["id"]

    signed_in = client.post(
        f"{settings.supabase_url}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": settings.supabase_anon_key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    signed_in.raise_for_status()

    return SupabaseUser(id=user_id, email=email, token=signed_in.json()["access_token"])


def _delete_user(client: httpx.Client, user_id: str) -> None:
    client.delete(
        f"{settings.supabase_url}/auth/v1/admin/users/{user_id}",
        headers=_admin_headers(),
    )


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="module")
def alice(client: httpx.Client) -> Iterator[SupabaseUser]:
    user = _create_user(client, "alice")
    yield user
    _delete_user(client, user.id)


@pytest.fixture(scope="module")
def bob(client: httpx.Client) -> Iterator[SupabaseUser]:
    user = _create_user(client, "bob")
    yield user
    _delete_user(client, user.id)


@pytest.fixture(scope="module")
def alices_resume(client: httpx.Client, alice: SupabaseUser) -> dict[str, Any]:
    """A resume row owned by Alice, written with Alice's own token."""
    response = client.post(
        f"{settings.supabase_url}/rest/v1/resumes",
        headers={**alice.headers, "Prefer": "return=representation"},
        json={
            "user_id": alice.id,
            "label": "RLS test resume",
            "document": {"contact": {"name": "Alice Example"}, "schema_version": 1},
            "parse_confidence": 0.9,
            "page_count": 1,
        },
    )
    response.raise_for_status()
    row: dict[str, Any] = response.json()[0]
    return row


class TestSignupWiring:
    def test_a_profile_row_is_created_automatically(
        self, client: httpx.Client, alice: SupabaseUser
    ) -> None:
        """The on_auth_user_created trigger must actually fire."""
        response = client.get(
            f"{settings.supabase_url}/rest/v1/profiles",
            headers=alice.headers,
            params={"select": "id", "id": f"eq.{alice.id}"},
        )
        assert response.status_code == 200
        assert len(response.json()) == 1


class TestOwnerAccess:
    """The isolation is worthless if it also blocks the owner."""

    def test_alice_can_read_her_own_resume(
        self, client: httpx.Client, alice: SupabaseUser, alices_resume: dict[str, Any]
    ) -> None:
        response = client.get(
            f"{settings.supabase_url}/rest/v1/resumes",
            headers=alice.headers,
            params={"select": "id,label", "id": f"eq.{alices_resume['id']}"},
        )
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["label"] == "RLS test resume"

    def test_alice_can_update_her_own_resume(
        self, client: httpx.Client, alice: SupabaseUser, alices_resume: dict[str, Any]
    ) -> None:
        response = client.patch(
            f"{settings.supabase_url}/rest/v1/resumes",
            headers={**alice.headers, "Prefer": "return=representation"},
            params={"id": f"eq.{alices_resume['id']}"},
            json={"label": "renamed by owner"},
        )
        assert response.status_code == 200
        assert response.json()[0]["label"] == "renamed by owner"


class TestCrossUserIsolation:
    """Bob holds a perfectly valid token. It must get him nowhere near Alice's data."""

    def test_the_row_really_exists(
        self, client: httpx.Client, alices_resume: dict[str, Any]
    ) -> None:
        """The control for every assertion below.

        Bob getting an empty result only means something if the row is
        actually there. Read with the service role key, which bypasses RLS,
        so an empty result for Bob is proof of policy rather than proof of an
        empty table.
        """
        response = client.get(
            f"{settings.supabase_url}/rest/v1/resumes",
            headers=_admin_headers(),
            params={"select": "id,user_id", "id": f"eq.{alices_resume['id']}"},
        )
        assert len(response.json()) == 1

    def test_bob_cannot_read_alices_resume_by_id(
        self, client: httpx.Client, bob: SupabaseUser, alices_resume: dict[str, Any]
    ) -> None:
        response = client.get(
            f"{settings.supabase_url}/rest/v1/resumes",
            headers=bob.headers,
            params={"select": "id,label,document", "id": f"eq.{alices_resume['id']}"},
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_bob_cannot_list_any_of_alices_resumes(
        self, client: httpx.Client, bob: SupabaseUser, alices_resume: dict[str, Any]
    ) -> None:
        response = client.get(
            f"{settings.supabase_url}/rest/v1/resumes",
            headers=bob.headers,
            params={"select": "id,user_id"},
        )
        assert response.status_code == 200
        assert all(row["user_id"] == bob.id for row in response.json())

    def test_bob_cannot_update_alices_resume(
        self, client: httpx.Client, bob: SupabaseUser, alices_resume: dict[str, Any]
    ) -> None:
        response = client.patch(
            f"{settings.supabase_url}/rest/v1/resumes",
            headers={**bob.headers, "Prefer": "return=representation"},
            params={"id": f"eq.{alices_resume['id']}"},
            json={"label": "hijacked"},
        )
        # RLS filters the row out, so the update matches nothing rather than
        # erroring — the request succeeds and changes zero rows.
        assert response.status_code in (200, 204)
        if response.status_code == 200:
            assert response.json() == []

        # And the owner's value is untouched.
        owned = client.get(
            f"{settings.supabase_url}/rest/v1/resumes",
            headers=_admin_headers(),
            params={"select": "label", "id": f"eq.{alices_resume['id']}"},
        )
        assert owned.json()[0]["label"] != "hijacked"

    def test_bob_cannot_delete_alices_resume(
        self, client: httpx.Client, bob: SupabaseUser, alices_resume: dict[str, Any]
    ) -> None:
        client.delete(
            f"{settings.supabase_url}/rest/v1/resumes",
            headers=bob.headers,
            params={"id": f"eq.{alices_resume['id']}"},
        )
        # The row must still be there afterwards.
        still_there = client.get(
            f"{settings.supabase_url}/rest/v1/resumes",
            headers={**_admin_headers()},
            params={"select": "id", "id": f"eq.{alices_resume['id']}"},
        )
        assert len(still_there.json()) == 1

    def test_bob_cannot_forge_a_row_owned_by_alice(
        self, client: httpx.Client, bob: SupabaseUser, alice: SupabaseUser
    ) -> None:
        """The WITH CHECK clause: Bob must not be able to write rows attributed
        to someone else, which would otherwise let him plant data in her
        account."""
        response = client.post(
            f"{settings.supabase_url}/rest/v1/resumes",
            headers=bob.headers,
            json={
                "user_id": alice.id,
                "label": "planted",
                "document": {"schema_version": 1},
            },
        )
        assert response.status_code in (401, 403)

    def test_bob_cannot_read_alices_profile(
        self, client: httpx.Client, bob: SupabaseUser, alice: SupabaseUser
    ) -> None:
        response = client.get(
            f"{settings.supabase_url}/rest/v1/profiles",
            headers=bob.headers,
            params={"select": "id", "id": f"eq.{alice.id}"},
        )
        assert response.status_code == 200
        assert response.json() == []


class TestAnonymousAccess:
    """An unauthenticated caller holding the public anon key gets nothing."""

    @pytest.fixture
    def anon_headers(self) -> dict[str, str]:
        return {
            "apikey": settings.supabase_anon_key,
            "Authorization": f"Bearer {settings.supabase_anon_key}",
        }

    @pytest.mark.parametrize("table", ["resumes", "profiles", "analyses", "job_targets"])
    def test_anonymous_reads_return_nothing(
        self, client: httpx.Client, anon_headers: dict[str, str], table: str
    ) -> None:
        response = client.get(
            f"{settings.supabase_url}/rest/v1/{table}",
            headers=anon_headers,
            params={"select": "id"},
        )
        assert response.status_code == 200
        assert response.json() == []


class TestOperationalTablesAreClosed:
    """Tables with RLS enabled and no policy are unreachable from any client.

    score_samples matters most: it holds the anonymised score vectors behind
    cohort percentiles, and it deliberately has no user_id. Letting clients read
    it wholesale would be a different kind of leak.
    """

    @pytest.mark.parametrize("table", ["score_samples", "rate_limits", "llm_usage"])
    def test_a_signed_in_user_cannot_read_operational_tables(
        self, client: httpx.Client, alice: SupabaseUser, table: str
    ) -> None:
        response = client.get(
            f"{settings.supabase_url}/rest/v1/{table}",
            headers=alice.headers,
            params={"select": "*"},
        )
        assert response.status_code in (200, 401, 403)
        if response.status_code == 200:
            assert response.json() == []

    def test_cohort_stats_are_readable_by_design(
        self, client: httpx.Client, alice: SupabaseUser
    ) -> None:
        """The one operational table with a public policy — it holds aggregates
        only, and the UI needs them to show percentiles."""
        response = client.get(
            f"{settings.supabase_url}/rest/v1/cohort_stats",
            headers=alice.headers,
            params={"select": "role_family"},
        )
        assert response.status_code == 200
