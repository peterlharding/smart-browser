"""Request and response models.

`BookmarkOut.id` is the id of *your save* (`user_bookmark`), not of the shared `bookmark`
row. Clients address their own saves and never the global URL record -- which is what
keeps one person's library invisible to another (ADR 0001).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BookmarkCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(
        default=None,
        max_length=1024,
        description=(
            "The page's title as the client saw it, such as the browser tab's title. "
            "Refreshed by every save that sends one. A title you choose goes through PATCH "
            "instead, and wins over this one and over the crawled title."
        ),
    )
    saved_from: str | None = Field(default=None, max_length=256)
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for tag in v:
            cleaned = tag.strip().lower()
            if cleaned:
                seen.setdefault(cleaned, None)
        return list(seen)


class BookmarkPatch(BaseModel):
    title: str | None = Field(
        default=None,
        max_length=1024,
        description=(
            "A title you choose. It wins over the title seen at save time and the crawled "
            "one, and survives every re-save. An empty string clears it."
        ),
    )
    notes: str | None = None
    tags: list[str] | None = None


class BookmarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    title: str | None
    site: str | None
    saved_from: str | None
    created_at: datetime | None
    notes: str | None = None
    tags: list[str]


class BookmarkPage(BaseModel):
    items: list[BookmarkOut]
    total: int
    limit: int
    offset: int


class TagOut(BaseModel):
    id: int
    name: str
    count: int


class TagsIn(BaseModel):
    tags: list[str] = Field(min_length=1)
    source: Literal["user", "ai", "rule", "import"] = "user"


class Health(BaseModel):
    """What a client needs to decide whether it can talk to this deployment.

    `contract` is the one to check: it is the API contract version, independent of
    `version`, which is the release label and moves every deploy.
    """

    status: Literal["ok", "degraded"]
    database: bool
    version: str
    contract: int
    schema_revision: str | None = None
