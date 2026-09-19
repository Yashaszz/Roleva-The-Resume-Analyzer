"""A thin Supabase REST client.

Deliberately thin. Roleva has ten tables and a handful of queries, so an ORM
would be more machinery than the problem needs, and PostgREST over httpx is
already a perfectly good query interface.

The important thing this module encodes is **which key is used for what**:

* **User-owned rows are written with the user's own token.** RLS then applies to
  the backend exactly as it applies to the browser, so a bug in a query cannot
  return somebody else's resume — the database refuses, not the code. This is
  the property the live RLS tests exist to prove.
* **The service-role key is used only for tables with no user column at all**:
  anonymous score samples, cohort statistics, rate-limit counters. These have
  RLS enabled and no policy, so they are unreachable any other way.

A query that needs the service key to read user data is a query that has been
written wrong. There is deliberately no convenience method for it.
"""

from __future__ import annotations

from typing import Any

import httpx

from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings, get_settings
from roleva.telemetry.logging import get_logger

logger = get_logger(__name__)

TIMEOUT = 15.0


class SupabaseError(RuntimeError):
    """A database call failed. Never shown to a user as-is."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"supabase {status}: {body[:200]}")
        self.status = status
        self.body = body


class Supabase:
    """PostgREST access for one caller.

    `token` is the signed-in user's access token. Omitting it falls back to the
    service-role key, which is correct only for tables that hold no user rows.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        settings: Settings | None = None,
        service_role: bool = False,
    ) -> None:
        self.settings = settings or get_settings()
        self.token = token
        self.service_role = service_role

        if not service_role and token is None:
            raise ValueError(
                "A user token is required for user-owned tables. Pass "
                "service_role=True only for tables with no user_id column."
            )

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.supabase_url
            and (self.settings.supabase_anon_key or self.settings.supabase_service_role_key)
        )

    def _url(self, table: str) -> str:
        return f"{self.settings.supabase_url.rstrip('/')}/rest/v1/{table}"

    def _headers(self, prefer: str | None = None) -> dict[str, str]:
        if self.service_role:
            key = self.settings.supabase_service_role_key
            bearer = key
        else:
            key = self.settings.supabase_anon_key
            bearer = self.token or key

        headers = {
            "apikey": key,
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    async def _request(self, method: str, table: str, **kwargs: Any) -> httpx.Response:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.request(method, self._url(table), **kwargs)

        if response.status_code >= 400:
            # The body can quote column values, which for these tables means
            # resume content. It goes to the log, never to the client.
            logger.warning("db.error", table=table, status=response.status_code)
            raise SupabaseError(response.status_code, response.text)
        return response

    async def insert(
        self, table: str, row: dict[str, Any], *, returning: bool = True
    ) -> dict[str, Any] | None:
        prefer = "return=representation" if returning else "return=minimal"
        response = await self._request("POST", table, headers=self._headers(prefer), json=row)
        if not returning:
            return None
        rows: list[dict[str, Any]] = response.json()
        return rows[0] if rows else None

    async def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: dict[str, str] | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"select": columns, **(filters or {})}
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)

        response = await self._request("GET", table, headers=self._headers(), params=params)
        rows: list[dict[str, Any]] = response.json()
        return rows

    async def update(self, table: str, *, filters: dict[str, str], values: dict[str, Any]) -> None:
        await self._request(
            "PATCH",
            table,
            headers=self._headers("return=minimal"),
            params=filters,
            json=values,
        )

    async def delete(self, table: str, *, filters: dict[str, str]) -> None:
        await self._request(
            "DELETE", table, headers=self._headers("return=minimal"), params=filters
        )

    async def rpc(self, function: str, payload: dict[str, Any]) -> Any:
        response = await self._request(
            "POST", f"rpc/{function}", headers=self._headers(), json=payload
        )
        return response.json()


def require_configured(client: Supabase) -> None:
    """Fail with a written message rather than a connection error.

    Running without Supabase is supported for local development, but a user
    reaching a persistence path in that state should be told the service is
    unavailable rather than shown a stack trace.
    """
    if not client.configured:
        raise RolevaError(
            ErrorCode.ANALYSIS_FAILED,
            "Storage is not configured on this server.",
        )
