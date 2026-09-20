"""SQLAlchemy models — the target schema.

Shaped by ADR 0001 (two levels) and ADR 0002 (one tag vocabulary).

The idea that carries the most weight here: **the URL and the save are different things.**
`Bookmark` is the page — global, unique on `url_hash`, owned by nobody, crawled and
embedded once however many people save it. `UserBookmark` is one person's save of it, and
tags hang off that. Crawling and embedding 7,000-odd URLs is the expensive part of this
system, and this is what keeps that cost per-URL instead of per-user-per-URL.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class TagSource(enum.Enum):
    """Where a tag on a bookmark came from.

    The reason `bookmark_tag` is not just a join table: an AI suggestion and a choice you
    made are different claims, and keeping them in one table with this column means "only
    the tags I chose myself" is a WHERE clause rather than a second table to keep in sync.
    """

    USER = "user"
    AI = "ai"
    RULE = "rule"
    IMPORT = "import"

    # No `str` mixin: nothing here needs the enum to *be* a string, and `TagSource("ai")`
    # and `.value` cover both directions. It also keeps the module importable below 3.11,
    # where `enum.StrEnum` does not exist.


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# --- identity ----------------------------------------------------------------


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    # Informational only. Identity is keyed on (provider, provider_subject) -- never on
    # email, which providers let people change and which makes account linking a
    # pre-account-takeover path (ADR 0003).
    email: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # server_default, not just default: a Python-side default only applies when the
    # ORM does the insert. The schema files carry it, and the two must agree.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    identities: Mapped[list[UserIdentity]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AppUser {self.id} {self.display_name!r}>"


class UserIdentity(Base):
    __tablename__ = "user_identity"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider_subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email_at_link: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()

    user: Mapped[AppUser] = relationship(back_populates="identities")


# --- the URL: global, one row per page ---------------------------------------


class Bookmark(Base):
    __tablename__ = "bookmark"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 of the normalised URL. UNIQUE, and that constraint is the whole duplication
    # guarantee: saving the same page twice cannot produce two rows, whatever the client
    # does and however many clients do it at once.
    url_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    site: Mapped[str | None] = mapped_column(Text, index=True)
    first_seen_at: Mapped[datetime] = _now()
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # NULL means never fetched, which is a different thing from 410 Gone.
    http_status: Mapped[int | None] = mapped_column(Integer)

    def __repr__(self) -> str:
        return f"<Bookmark {self.id} {self.url!r}>"


# --- the save: per user ------------------------------------------------------


class UserBookmark(Base):
    __tablename__ = "user_bookmark"
    __table_args__ = (UniqueConstraint("user_id", "bookmark_id", name="user_bookmark_uniq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bookmark_id: Mapped[int] = mapped_column(
        ForeignKey("bookmark.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Your title beats the crawled one, without overwriting it for everyone else.
    title_override: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    saved_from: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()
    last_visited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    visit_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    bookmark: Mapped[Bookmark] = relationship(lazy="joined")
    tag_links: Mapped[list[BookmarkTag]] = relationship(
        back_populates="user_bookmark", cascade="all, delete-orphan"
    )

    @property
    def tags(self) -> list[str]:
        return sorted(link.tag.name for link in self.tag_links if link.tag)

    @property
    def title(self) -> str | None:
        return self.title_override or self.bookmark.title

    def __repr__(self) -> str:
        return f"<UserBookmark {self.id} user={self.user_id} bookmark={self.bookmark_id}>"


# --- tags: global vocabulary, per-user links ---------------------------------


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Always stored lowercase, enforced on every write path -- which is why a plain
    # UNIQUE is enough and the schema needs no citext extension (ADR 0006).
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tag.id", ondelete="SET NULL"))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()

    def __repr__(self) -> str:
        return f"<Tag {self.id} {self.name!r}>"


class TagAlias(Base):
    """Misspellings and variants resolving to a canonical tag.

    Free-text tag entry decays without this: the audit measured 32 near-duplicate pairs
    in a 567-tag vocabulary -- `bootstrap`/`boorstrap`, `fontawesome`/`font-awesome`,
    `letsencrypt`/`letsencrypy`. Aliasing fixes the vocabulary for everyone at once, which
    a per-client correction list cannot.
    """

    __tablename__ = "tag_alias"

    alias: Mapped[str] = mapped_column(Text, primary_key=True)
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tag.id", ondelete="CASCADE"), nullable=False, index=True
    )

    tag: Mapped[Tag] = relationship()


class BookmarkTag(Base):
    __tablename__ = "bookmark_tag"

    user_bookmark_id: Mapped[int] = mapped_column(
        ForeignKey("user_bookmark.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    source: Mapped[TagSource] = mapped_column(
        Enum(TagSource, name="tag_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=TagSource.USER,
        server_default=text("'user'"),
    )
    # NULL for tags a person chose. Set for machine suggestions, so the UI can show them
    # as provisional and a bulk accept/reject is a query rather than a migration.
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = _now()

    user_bookmark: Mapped[UserBookmark] = relationship(back_populates="tag_links")
    tag: Mapped[Tag] = relationship(lazy="joined")
