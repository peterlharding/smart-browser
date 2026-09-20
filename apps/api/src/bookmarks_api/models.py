"""SQLAlchemy models.

These mirror the schema *as it exists today* (bookmarks_20250510a.sql), not the target
schema in doc/architecture.md. M0's job is to put a correct, authenticated, idempotent
API in front of the current database without migrating it; M2 changes the shape.

Consequences of that, all temporary:
  - `used` is doing duty as created_at.
  - `host` holds the posting client, not the site. `Bookmark.site` is computed, not stored.
  - `bookmark_tag` has a surrogate id and no uniqueness. M2 replaces it with a composite PK.
  - No url_hash column yet, so idempotency here matches on the normalised URL string.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Bookmark(Base):
    __tablename__ = "bookmark"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str | None] = mapped_column(String(256))
    title: Mapped[str | None] = mapped_column(String(256))
    host: Mapped[str | None] = mapped_column(String(256))
    used: Mapped[datetime | None] = mapped_column(DateTime)

    tag_links: Mapped[list[BookmarkTag]] = relationship(
        back_populates="bookmark", cascade="all, delete-orphan"
    )

    @property
    def tags(self) -> list[str]:
        return sorted(link.tag.tag for link in self.tag_links if link.tag and link.tag.tag)

    def __repr__(self) -> str:
        return f"<Bookmark {self.id} {self.url!r}>"


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tag: Mapped[str | None] = mapped_column(String(32))

    links: Mapped[list[BookmarkTag]] = relationship(back_populates="tag")

    def __repr__(self) -> str:
        return f"<Tag {self.id} {self.tag!r}>"


class BookmarkTag(Base):
    __tablename__ = "bookmark_tag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bookmark_fk: Mapped[int | None] = mapped_column(ForeignKey("bookmark.id"))
    tag_fk: Mapped[int | None] = mapped_column(ForeignKey("tag.id"))

    bookmark: Mapped[Bookmark | None] = relationship(back_populates="tag_links")
    tag: Mapped[Tag | None] = relationship(back_populates="links")

    def __repr__(self) -> str:
        return f"<BookmarkTag {self.bookmark_fk}->{self.tag_fk}>"
