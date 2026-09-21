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
import json
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Integer,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# The dimension of `bookmark_content.embedding`, fixed by `vector(384)` in the SQL. Not a
# setting: changing it is a migration. The embedder checks its model against the column
# itself before writing (ADR 0013).
EMBEDDING_DIM = 384


class _VectorAsJSON(TypeDecorator[list[float]]):
    """The embedding column's stand-in on SQLite, which has no pgvector.

    JSON text rather than bare Text, so the default suite stores and reads back real
    vectors: the embedder's paths are tested there, and only the index and the distance
    operators need Postgres.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else json.dumps([float(x) for x in value])

    def process_result_value(self, value, dialect):
        return None if value is None else json.loads(value)


Embedding = Vector(EMBEDDING_DIM).with_variant(_VectorAsJSON(), "sqlite")


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


# The schema files declare `bigint GENERATED ALWAYS AS IDENTITY`. Two details have to be
# mirrored here rather than approximated.
#
# `with_variant(Integer, "sqlite")`: SQLite auto-assigns only for INTEGER PRIMARY KEY,
# which is an alias for the rowid. A BIGINT primary key there is an ordinary column, and
# an insert that omits it fails -- which would take the whole fast test suite with it.
#
# `Identity(always=True)`: not `autoincrement`, and not a SERIAL default. GENERATED ALWAYS
# refuses an explicit id outright, so nothing can quietly assign one and desynchronise the
# sequence. Nothing in this codebase does; the constraint keeps it that way.
BigId = BigInteger().with_variant(Integer, "sqlite")


def _pk() -> Mapped[int]:
    return mapped_column(BigId, Identity(always=True), primary_key=True)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# --- identity ----------------------------------------------------------------


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = _pk()
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
        BigId, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email_at_link: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()

    user: Mapped[AppUser] = relationship(back_populates="identities")


# --- the URL: global, one row per page ---------------------------------------


class Bookmark(Base):
    __tablename__ = "bookmark"

    id: Mapped[int] = _pk()
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

    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bookmark_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("bookmark.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # A title a person chose. It beats everything, and only PATCH writes it.
    title_override: Mapped[str | None] = mapped_column(Text)
    # The title the client saw when it saved: the tab title, for the extension. Per save
    # rather than on `bookmark`, because a tab title can be private in a way a URL is not.
    # POST writes it, and a re-save with a title refreshes it (ADR 0010).
    saved_title: Mapped[str | None] = mapped_column(Text)
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
        """What you typed, then what you saw, then what the crawler fetched (ADR 0010).

        The saved title outranks the crawled one because for the pages where they differ
        most -- behind a login, where the crawler sees "Sign in", or single-page apps,
        where it sees the framework's default -- the saved one is the right one.
        """
        return self.title_override or self.saved_title or self.bookmark.title

    def __repr__(self) -> str:
        return f"<UserBookmark {self.id} user={self.user_id} bookmark={self.bookmark_id}>"


# --- tags: global vocabulary, per-user links ---------------------------------


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = _pk()
    # Always stored lowercase, enforced on every write path -- which is why a plain
    # UNIQUE is enough and the schema needs no citext extension (ADR 0006).
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    parent_id: Mapped[int | None] = mapped_column(BigId, ForeignKey("tag.id", ondelete="SET NULL"))
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
        BigId, ForeignKey("tag.id", ondelete="CASCADE"), nullable=False, index=True
    )

    tag: Mapped[Tag] = relationship()


class BookmarkTag(Base):
    __tablename__ = "bookmark_tag"

    user_bookmark_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("user_bookmark.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True, index=True
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


# --- what the crawler produced, and the queue that feeds it ------------------


class BookmarkContent(Base):
    """Extracted text and its embedding, keyed by the URL rather than by the save.

    Ten people saving the same page pay for one fetch and one embedding; that is ADR 0001
    earning its keep. A missing row is not "empty page": it means no successful fetch has
    produced anything yet, and `crawl_job` is where the reason lives.

    `tsv` is absent on purpose. It is a Postgres generated column with no SQLite
    equivalent, nothing in the ORM reads it, and search will be raw SQL over the GIN
    index; `db/schema/create/bookmark_content.sql` remains its single definition, and the
    schema-diff test lists it as the one deliberate difference.
    """

    __tablename__ = "bookmark_content"

    bookmark_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("bookmark.id", ondelete="CASCADE"), primary_key=True
    )
    text_: Mapped[str | None] = mapped_column("text", Text)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding)
    # Which model produced `embedding`. A re-embed is then `WHERE model <> :current`
    # rather than a guess about what is in the column.
    model: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _now()

    def __repr__(self) -> str:
        return f"<BookmarkContent bookmark={self.bookmark_id} model={self.model!r}>"


class JobState(enum.Enum):
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class CrawlJob(Base):
    """One outstanding crawl per URL.

    `bookmark_id` is the primary key rather than a job id, so that invariant is enforced
    by the database instead of remembered by the enqueue code. The row is written in the
    same transaction as the bookmark, which is what makes "saved but never queued"
    unreachable rather than merely unlikely.
    """

    __tablename__ = "crawl_job"

    bookmark_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("bookmark.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, name="job_state", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=JobState.READY,
        server_default=text("'ready'"),
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Backoff as a timestamp, not a sleep: it survives a restart, and a second worker
    # honours it too.
    next_attempt_at: Mapped[datetime] = _now()
    last_error: Mapped[str | None] = mapped_column(Text)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()

    def __repr__(self) -> str:
        return f"<CrawlJob bookmark={self.bookmark_id} {self.state.value} attempts={self.attempts}>"
