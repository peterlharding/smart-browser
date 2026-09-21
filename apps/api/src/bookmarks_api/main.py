"""Application entry point.

The API is versioned in its path so that a breaking change can be made without breaking
installed clients -- an extension updates on its own schedule, not the server's.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import API_CONTRACT_VERSION, __version__
from .config import get_settings
from .db import get_engine
from .routers import bookmarks, health, tags
from .schema_guard import verify


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Fail fast on a schema the code does not match.

    Starting anyway would trade a clear startup error for a 500 on one endpoint at some
    later hour. `SCHEMA_CHECK=false` exists for the case where you knowingly need to run
    against an unstamped database -- it is not something to set by default.
    """
    if get_settings().schema_check:
        verify(get_engine())
    yield


app = FastAPI(
    title="Smart-Browser Bookmarks API",
    version=__version__,
    description=(
        f"Tag-first bookmarks. Contract version {API_CONTRACT_VERSION}. "
        "See doc/architecture.md."
    ),
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)

# Browser clients -- the extension now, the Electron shell in M5 -- read responses from a
# different origin than the API's. Without this the request still reaches the server and
# the browser throws the answer away, which surfaces as a network error in the client and
# a perfectly ordinary 200 in the API log: a mismatch that costs an afternoon.
#
# No `allow_credentials`: auth is a bearer token in a header, so nothing here should ever
# ride on a cookie, and combining credentials with a permissive origin rule is how a CORS
# policy becomes a vulnerability.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_origin_regex=get_settings().cors_origin_regex,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(bookmarks.router, prefix="/api/v1")
app.include_router(tags.router, prefix="/api/v1")
