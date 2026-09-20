"""Dependencies: auth and the acting identity."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class CurrentUser:
    """The acting identity.

    The system is multi-user by design (ADR 0001), but M0 runs against the pre-migration
    schema, which has no ownership columns -- so this resolves to the configured id for
    now. M1 replaces the body with a real lookup: token -> app_user. Every handler is
    already written against a user, so none of them change when it does.
    """

    id: str


def require_token(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Bearer-token auth for writes.

    Note what happens with no tokens configured: writes are *refused*, not allowed. An
    unconfigured deployment should be inert, not open -- which is the failure mode that
    left /xyzzy world-writable.
    """
    tokens = settings.token_set
    if not tokens:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No API tokens configured; writes are disabled.",
        )

    scheme, _, credential = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not credential:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # compare_digest against each candidate: constant time, no early exit on a prefix match.
    if not any(secrets.compare_digest(credential, known) for known in tokens):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid token.")

    return credential


def current_user(
    settings: SettingsDep,
    _: Annotated[str, Depends(require_token)],
) -> CurrentUser:
    return CurrentUser(id=settings.single_user_id)
