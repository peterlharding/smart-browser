"""Dependencies: auth and the acting user."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_db
from .models import AppUser

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


# A declared security scheme rather than a raw Authorization header. The behaviour is the
# same either way; what it buys is the padlock and the Authorize dialog in /api/v1/docs,
# which FastAPI only renders for a dependency deriving from SecurityBase. Reading the
# header by hand means everyone testing the API hand-types "Bearer <token>" into a header
# field -- and gets a 401 for writing "Bearer: <token>", which is the same mistake the
# dialog makes impossible. auto_error=False so the responses below stay ours.
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="API token",
    description="The token half of an API_TOKENS entry: for `plh:s3cret`, enter `s3cret`.",
)


def require_token(
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> str:
    """Bearer-token auth for writes.

    Note what happens with no tokens configured: requests are *refused*, not allowed. An
    unconfigured deployment should be inert rather than public -- failing open is how
    write endpoints quietly end up exposed.
    """
    tokens = settings.token_set
    if not tokens:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No API tokens configured; writes are disabled.",
        )

    # HTTPBearer has already rejected anything that is not `Authorization: Bearer <x>` --
    # including the `Bearer: <x>` that a header field invites -- by returning None.
    credential = credentials.credentials if credentials else ""
    if not credential:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required, as `Authorization: Bearer <token>`.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not any(secrets.compare_digest(credential, known) for known in tokens):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid token.")

    return credential


def user_named(db: Session, name: str) -> AppUser:
    """The `app_user` row for *name*, created on first use."""
    user = db.execute(select(AppUser).where(AppUser.display_name == name)).scalar_one_or_none()
    if user is None:
        user = AppUser(display_name=name)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def current_user(
    db: DbDep,
    settings: SettingsDep,
    token: Annotated[str, Depends(require_token)],
) -> AppUser:
    """Whose library this request acts on.

    Reads need this as much as writes do. Bookmarks belong to a user, so there is no
    coherent anonymous read: "list the bookmarks" has no answer without knowing whose.
    Making reads public would either leak everyone's library or silently return one
    arbitrary person's.

    M1 replaces the token lookup with an OAuth session resolving through `user_identity`
    to this same table. Every handler already takes an `AppUser`, so none of them change.
    """
    return user_named(db, settings.token_map[token])


CurrentUser = Annotated[AppUser, Depends(current_user)]
# Reads and writes resolve identically. Kept as a separate name so the routes say which
# kind of access they need, and so M1 can diverge them if sessions and tokens differ.
ViewingUser = CurrentUser
