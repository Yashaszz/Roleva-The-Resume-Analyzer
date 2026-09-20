"""Creating, resolving and revoking share links.

A share token is the whole of the access control: anyone holding it can read the
report. That makes three properties non-negotiable.

**The token must be unguessable.** 32 bytes from `secrets.token_urlsafe`, which
is 256 bits of CSPRNG output. A sequential id or a short token would let someone
walk the space and read strangers' resumes.

**Expiry is not optional.** Every link dies, by default in a week. A link that
lives forever is one the owner forgets they created, and it will still be
working the day somebody finds it in an old message.

**Revocation is immediate.** `revoked_at` is checked on every resolution, not
swept by a job, so "revoke" means revoked now rather than revoked eventually.

The lookup runs with the service-role key, and that is deliberate: a share link
is read by somebody who is not signed in and owns nothing, so there is no user
token to apply RLS with. The token *is* the authorisation, which is why the
three properties above carry the weight they do.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings, get_settings
from roleva.sharing.redaction import Visibility
from roleva.storage.supabase import Supabase, SupabaseError
from roleva.telemetry.logging import get_logger

logger = get_logger(__name__)

#: 32 bytes, URL-safe. Long enough that guessing is not a strategy.
TOKEN_BYTES = 32

DEFAULT_EXPIRY_DAYS = 7
MAX_EXPIRY_DAYS = 30


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


@dataclass(frozen=True)
class ShareLink:
    token: str
    analysis_id: str
    visibility: Visibility
    expires_at: datetime
    view_count: int
    revoked: bool

    @property
    def active(self) -> bool:
        return not self.revoked and self.expires_at > datetime.now(UTC)


def _clamp_expiry(days: int | None) -> datetime:
    """Expiry within the allowed window.

    Clamped rather than rejected: a caller asking for a year gets a month, which
    is a better outcome than an error nobody expected. The maximum is the
    product's promise, not a suggestion.
    """
    requested = DEFAULT_EXPIRY_DAYS if days is None else days
    bounded = max(1, min(int(requested), MAX_EXPIRY_DAYS))
    return datetime.now(UTC) + timedelta(days=bounded)


async def create(
    db: Supabase,
    *,
    user_id: str,
    analysis_id: str,
    visibility: Visibility,
    expires_in_days: int | None = None,
) -> ShareLink:
    """Mint a link for an analysis the caller owns.

    Written with the caller's own token, so RLS refuses to create a link for
    somebody else's analysis — the ownership check is the database's, not a
    condition written here that could be forgotten.
    """
    expires_at = _clamp_expiry(expires_in_days)
    token = new_token()

    row = await db.insert(
        "share_links",
        {
            "analysis_id": analysis_id,
            "user_id": user_id,
            "token": token,
            "visibility_mode": visibility.value,
            "expires_at": expires_at.isoformat(),
        },
    )
    if not row:
        raise RolevaError(ErrorCode.NOT_FOUND)

    logger.info("share.created", analysis_id=analysis_id, visibility=visibility.value)
    return ShareLink(
        token=token,
        analysis_id=analysis_id,
        visibility=visibility,
        expires_at=expires_at,
        view_count=0,
        revoked=False,
    )


async def resolve(token: str, settings: Settings | None = None) -> ShareLink:
    """Look up a live link, or raise NOT_FOUND.

    Expired and revoked links raise exactly the same error as a token that never
    existed. Distinguishing them would tell whoever is holding an old link that
    it used to be real, which is information the owner did not agree to share.
    """
    config = settings or get_settings()
    admin = Supabase(service_role=True, settings=config)

    try:
        rows = await admin.select(
            "share_links",
            columns="token,analysis_id,visibility_mode,expires_at,revoked_at,view_count",
            filters={"token": f"eq.{token}"},
            limit=1,
        )
    except SupabaseError:
        raise RolevaError(ErrorCode.NOT_FOUND) from None

    if not rows:
        raise RolevaError(ErrorCode.NOT_FOUND)

    link = _from_row(rows[0])
    if not link.active:
        logger.info("share.rejected", reason="revoked" if link.revoked else "expired")
        raise RolevaError(ErrorCode.NOT_FOUND)

    return link


async def record_view(token: str, settings: Settings | None = None) -> None:
    """Count one view. Never fails the request.

    The counter is for the owner's benefit — "this was opened four times" — not
    for billing or rate limiting, so a lost increment costs nothing worth
    handling.
    """
    config = settings or get_settings()
    admin = Supabase(service_role=True, settings=config)
    try:
        await admin.rpc("bump_share_view", {"p_token": token})
    except Exception:
        # Deliberately broad. The docstring above promises this never fails the
        # request, and catching only SupabaseError did not keep that promise:
        # an empty 204 body raised a JSONDecodeError and took the shared report
        # down with it.
        logger.info("share.view_not_counted")


async def revoke(db: Supabase, *, user_id: str, token: str) -> None:
    """Kill a link now.

    Scoped to the owner as well as the token: RLS would refuse anyway, and
    asking for both means a misconfigured policy cannot turn a guessed token
    into somebody else's revocation.
    """
    await db.update(
        "share_links",
        filters={"token": f"eq.{token}", "user_id": f"eq.{user_id}"},
        values={"revoked_at": datetime.now(UTC).isoformat()},
    )
    logger.info("share.revoked")


async def list_for_user(db: Supabase, user_id: str) -> list[ShareLink]:
    rows = await db.select(
        "share_links",
        columns="token,analysis_id,visibility_mode,expires_at,revoked_at,view_count",
        filters={"user_id": f"eq.{user_id}"},
        order="created_at.desc",
        limit=50,
    )
    return [_from_row(row) for row in rows]


def _from_row(row: dict[str, Any]) -> ShareLink:
    return ShareLink(
        token=str(row["token"]),
        analysis_id=str(row["analysis_id"]),
        visibility=Visibility(row["visibility_mode"]),
        expires_at=_parse(row["expires_at"]),
        view_count=int(row.get("view_count") or 0),
        revoked=row.get("revoked_at") is not None,
    )


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    # A naive timestamp compared against an aware one raises, and Postgres can
    # return either depending on the column type.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
