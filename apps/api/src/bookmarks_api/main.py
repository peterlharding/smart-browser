"""Application entry point.

The API is versioned in its path so that a breaking change can be made without breaking
installed clients -- an extension updates on its own schedule, not the server's.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import API_CONTRACT_VERSION, __version__
from .config import get_settings
from .db import engine
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
        verify(engine)
    yield


app = FastAPI(
    title="Smart-Browser Bookmarks API",
    version=__version__,
    description=(
        f"Tag-first bookmarks. Contract version {API_CONTRACT_VERSION}. "
        "See doc/architecture.md."
    ),
    docs_url="/api/v2/docs",
    openapi_url="/api/v2/openapi.json",
    lifespan=lifespan,
)

app.include_router(health.router, prefix="/api/v2")
app.include_router(bookmarks.router, prefix="/api/v2")
app.include_router(tags.router, prefix="/api/v2")
