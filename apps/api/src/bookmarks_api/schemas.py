"""Request and response models.

The v2 shape, presented over the v1 tables. Field names here are the *target* names
(created_at, saved_from, site) so that the M2 migration changes the storage without
changing the contract the browser and extensions are written against.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BookmarkCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=1024)
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
    title: str | None = Field(default=None, max_length=1024)
    tags: list[str] | None = None


class BookmarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str | None
    title: str | None
    site: str | None
    saved_from: str | None
    created_at: datetime | None
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
