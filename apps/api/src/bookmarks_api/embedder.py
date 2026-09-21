"""The embedding pass: turn crawled text into vectors (ADR 0013).

    uv run python -m bookmarks_api.embedder           # run until stopped   (make embed)
    uv run python -m bookmarks_api.embedder --once    # embed what is waiting, then exit

A separate process from the crawl worker (ADR 0012), so a model problem never stops
crawling and the fetch loop never carries the model. There is no queue table: a page needs
embedding when it has something to embed and `bookmark_content.model` is not the current
label, which covers never embedded, re-crawled (the worker clears both columns) and
embedded by an older model or recipe alike.
"""

from __future__ import annotations

import argparse
import math
import signal
import sys
import threading
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from .models import EMBEDDING_DIM, Bookmark, BookmarkContent

# What goes into a vector, named so that changing it is a re-embed: the label stored in
# `bookmark_content.model` is the model *and* this.
RECIPE = "title+description+text"
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
BATCH = 32
IDLE_WAIT = 10.0


class Model(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def label(model_name: str) -> str:
    """What `bookmark_content.model` holds for a vector this code would write now."""
    return f"{model_name}|{RECIPE}"


class FastembedModel:
    """`bge-small-en-v1.5` through fastembed: ONNX, 64 MB, no PyTorch (ADR 0013).

    `fastembed` truncates at the model's 512 tokens, so a page is represented by its
    title, description and the opening of its text.
    """

    def __init__(self, name: str, cache_dir: str) -> None:
        from fastembed import TextEmbedding  # heavy; only the embedder process pays for it

        self.name = name
        try:
            self._model = TextEmbedding(name, cache_dir=str(Path(cache_dir).expanduser()))
        except ValueError as exc:
            # fastembed's message names neither the setting nor the fix. Until 0.3.0 the
            # example .env said `bge-small-en-v1.5`, which fastembed does not recognise.
            raise ValueError(
                f"EMBEDDING_MODEL={name!r} is not a model fastembed knows ({exc}). "
                f"The default is {DEFAULT_MODEL!r}; fastembed names models with their "
                f"publisher, so an EMBEDDING_MODEL copied from an example .env before 0.3.0 "
                f"needs the 'BAAI/' prefix."
            ) from exc
        self.dim = len(self.embed(["dimension probe"])[0])

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for vector in self._model.embed(texts, batch_size=BATCH):
            values = [float(x) for x in vector]
            norm = math.sqrt(sum(x * x for x in values)) or 1.0
            vectors.append([x / norm for x in values])  # the cosine index expects unit length
        return vectors


def passage(title: str | None, description: str | None, body: str | None) -> str | None:
    """The text a page is embedded from: title, description and text, blank-line separated."""
    parts = [p.strip() for p in (title, description, body) if p and p.strip()]
    return "\n\n".join(parts) or None


def _has_something():
    return or_(
        BookmarkContent.text_.is_not(None),
        Bookmark.title.is_not(None),
        Bookmark.description.is_not(None),
    )


def _outdated(current: str):
    return or_(BookmarkContent.model.is_(None), BookmarkContent.model != current)


def column_dimension(session: Session) -> int:
    """The dimension the database will accept: pgvector keeps it as the column's typmod."""
    if session.get_bind().dialect.name != "postgresql":
        return EMBEDDING_DIM
    return session.execute(text(
        "SELECT atttypmod FROM pg_attribute "
        "WHERE attrelid = 'bookmark_content'::regclass AND attname = 'embedding'"
    )).scalar_one()


def check_dimension(session: Session, model: Model) -> None:
    column = column_dimension(session)
    if model.dim != column:
        raise ValueError(
            f"{model.name} makes {model.dim}-dimension vectors, but "
            f"bookmark_content.embedding is vector({column}). Set EMBEDDING_MODEL to a "
            f"{column}-dimension model, or change the column in a migration."
        )


def embed_batch(session: Session, model: Model, now: datetime, size: int = BATCH) -> int:
    """Embed up to *size* waiting pages and commit. Returns how many were written.

    The rows are claimed `FOR UPDATE SKIP LOCKED`, so a second embedder takes different
    ones, and they stay locked while the model runs: a few seconds, on rows nobody waits on.
    """
    current = label(model.name)
    rows = session.execute(
        select(BookmarkContent, Bookmark.title, Bookmark.description)
        .join(Bookmark, Bookmark.id == BookmarkContent.bookmark_id)
        .where(_outdated(current), _has_something())
        .order_by(BookmarkContent.bookmark_id)
        .limit(size)
        .with_for_update(skip_locked=True, of=BookmarkContent)
    ).all()
    if not rows:
        session.rollback()
        return 0

    texts = [
        passage(title, description, content.text_) or ""
        for content, title, description in rows
    ]
    vectors = model.embed(texts)
    if len(vectors) != len(rows):
        raise RuntimeError(f"{model.name} returned {len(vectors)} vectors for {len(rows)} texts")
    for (content, _, _), vector in zip(rows, vectors, strict=True):
        content.embedding = vector
        content.model = current
        content.updated_at = now
    session.commit()
    return len(rows)


def run(
    factory: sessionmaker[Session],
    model: Model,
    *,
    once: bool = False,
    stop: threading.Event | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    idle: float = IDLE_WAIT,
    log: Callable[[str], None] = print,
) -> int:
    """Embed until stopped, or with *once* until nothing is waiting. Returns a count.

    A batch that raises is a bug, not a verdict on a page: it is logged, nothing from it is
    written, and it is left for the next run. With *once* it is raised, so a scripted run
    exits non-zero instead of reporting success.
    """
    stop = stop or threading.Event()
    done = 0
    while not stop.is_set():
        try:
            with factory() as session:
                written = embed_batch(session, model, clock())
        except Exception as exc:
            traceback.print_exc()
            log(f"embed batch failed: {type(exc).__name__}: {exc}")
            if once:
                raise
            stop.wait(idle)
            continue
        if written:
            done += written
            log(f"embedded {written} ({done} this run)")
            continue
        if once:
            break
        stop.wait(idle)
    return done


def status_line(session: Session, current: str) -> str:
    with_content = session.execute(
        select(func.count())
        .select_from(BookmarkContent)
        .join(Bookmark, Bookmark.id == BookmarkContent.bookmark_id)
        .where(_has_something())
    ).scalar_one()
    embedded = session.execute(
        select(func.count()).select_from(BookmarkContent).where(BookmarkContent.model == current)
    ).scalar_one()
    return f"embedded {embedded} of {with_content} pages with content, as {current}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bookmarks_api.embedder")
    parser.add_argument("--once", action="store_true", help="embed what is waiting, then exit")
    args = parser.parse_args(argv)

    from .config import get_settings
    from .db import get_engine, get_sessionmaker
    from .schema_guard import verify

    settings = get_settings()
    if settings.schema_check:
        verify(get_engine())
    factory = get_sessionmaker()

    print(f"loading {settings.embedding_model} from {settings.embedding_cache_dir}")
    model = FastembedModel(settings.embedding_model, settings.embedding_cache_dir)
    with factory() as session:
        check_dimension(session, model)

    stop = threading.Event()

    def finish_then_exit(signum: int, _frame: object) -> None:
        stop.set()
        signal.signal(signum, signal.SIG_DFL)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, finish_then_exit)

    print(f"embedder started as {label(model.name)}")
    count = run(factory, model, once=args.once, stop=stop)
    print(f"embedder stopped after {count} {'page' if count == 1 else 'pages'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
