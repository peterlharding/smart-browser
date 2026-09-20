"""Bookmark routes.

The contract to hold on to: `POST /bookmarks` is idempotent. Saving a page you already
have returns 200 with the existing record and its tags, rather than 201 and a second row.
That is the fix for the 2,216 duplicate rows in the 2025 dump, and it is what lets the
browser's save sheet immediately show what it already knows about a page.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import CurrentUser, current_user
from ..ids import next_id, sequences_installed
from ..models import Bookmark, BookmarkTag, Tag
from ..schemas import BookmarkCreate, BookmarkOut, BookmarkPage, BookmarkPatch, TagsIn
from ..urlnorm import normalise, site_of

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])

DbDep = Annotated[Session, Depends(get_db)]
UserDep = Annotated[CurrentUser, Depends(current_user)]


# --- helpers -----------------------------------------------------------------


def _to_out(bookmark: Bookmark) -> BookmarkOut:
    return BookmarkOut(
        id=bookmark.id,
        url=bookmark.url,
        title=bookmark.title,
        site=site_of(bookmark.url) if bookmark.url else None,
        saved_from=bookmark.host,
        created_at=bookmark.used,
        tags=bookmark.tags,
    )


def _loaded(db: Session, bookmark_id: int) -> Bookmark:
    stmt = (
        select(Bookmark)
        .options(selectinload(Bookmark.tag_links).selectinload(BookmarkTag.tag))
        .where(Bookmark.id == bookmark_id)
    )
    found = db.execute(stmt).scalar_one_or_none()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Bookmark not found.")
    return found


def _find_existing(db: Session, url: str) -> Bookmark | None:
    """Match on the raw URL or its normalised form.

    Until M2 backfills `url_hash`, stored URLs are un-normalised, so an incoming URL can
    only be matched against what happens to be there. This catches the common case --
    the same page saved twice from the same client -- and M2's unique index on url_hash
    closes the rest.
    """
    candidates = {url}
    with contextlib.suppress(ValueError):
        candidates.add(normalise(url))

    stmt = (
        select(Bookmark)
        .options(selectinload(Bookmark.tag_links).selectinload(BookmarkTag.tag))
        .where(Bookmark.url.in_(candidates))
        .order_by(Bookmark.id)
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _get_or_create_tag(db: Session, name: str) -> Tag:
    cleaned = name.strip().lower()
    if not cleaned:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Blank tag.")
    if len(cleaned) > 32:
        # The current column is varchar(32). M2 widens it; until then, fail loudly
        # rather than let Postgres truncate or error mid-transaction.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Tag {cleaned!r} exceeds the current 32-character column limit.",
        )

    existing = db.execute(
        select(Tag).where(func.lower(Tag.tag) == cleaned).limit(1)
    ).scalar_one_or_none()
    if existing:
        return existing

    tag = Tag(tag=cleaned)
    if not sequences_installed(db, "tag"):
        tag.id = next_id(db, "tag")
    db.add(tag)
    db.flush()
    return tag


def _attach_tags(db: Session, bookmark: Bookmark, names: list[str]) -> None:
    present = {link.tag.tag for link in bookmark.tag_links if link.tag and link.tag.tag}
    for name in names:
        cleaned = name.strip().lower()
        if cleaned in present:
            continue
        tag = _get_or_create_tag(db, name)
        link = BookmarkTag(bookmark_fk=bookmark.id, tag_fk=tag.id)
        if not sequences_installed(db, "bookmark_tag"):
            link.id = next_id(db, "bookmark_tag")
        db.add(link)
        present.add(cleaned)
    db.flush()


# --- routes ------------------------------------------------------------------


@router.post("", response_model=BookmarkOut)
def create_bookmark(
    payload: BookmarkCreate,
    response: Response,
    db: DbDep,
    user: UserDep,
) -> BookmarkOut:
    """Save a page. Idempotent on the URL.

    Returns 200 when the bookmark already existed, 201 when it was created. Either way
    any tags in the payload are attached, so re-saving with new tags is an upsert of
    tags rather than an error.
    """
    try:
        normalise(payload.url)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    existing = _find_existing(db, payload.url)
    if existing is not None:
        if payload.tags:
            _attach_tags(db, existing, payload.tags)
            db.commit()
            existing = _loaded(db, existing.id)
        response.status_code = status.HTTP_200_OK
        return _to_out(existing)

    bookmark = Bookmark(
        url=normalise(payload.url),
        title=payload.title,
        host=payload.saved_from or "smart-browser",
        used=datetime.now(),
    )
    if not sequences_installed(db, "bookmark"):
        bookmark.id = next_id(db, "bookmark")
    db.add(bookmark)
    db.flush()

    if payload.tags:
        _attach_tags(db, bookmark, payload.tags)

    db.commit()
    response.status_code = status.HTTP_201_CREATED
    return _to_out(_loaded(db, bookmark.id))


@router.get("", response_model=BookmarkPage)
def list_bookmarks(
    db: DbDep,
    tags: str | None = Query(default=None, description="Comma-separated tag names"),
    mode: Literal["all", "any"] = Query(default="all"),
    site: str | None = None,
    q: str | None = Query(default=None, description="Substring match on title or URL"),
    untagged: bool = Query(default=False, description="Only bookmarks with no tags"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> BookmarkPage:
    """List bookmarks.

    `mode=all` is the intersection query the tag sidebar is built on -- `python` AND
    `fastapi`, not `python` OR `fastapi`. `untagged=true` is how you work the 7,655-row
    backlog the audit found.
    """
    stmt = select(Bookmark)
    count_stmt = select(func.count(Bookmark.id))

    wanted = [t.strip().lower() for t in tags.split(",")] if tags else []
    wanted = [t for t in wanted if t]

    if wanted:
        matching = (
            select(BookmarkTag.bookmark_fk)
            .join(Tag, Tag.id == BookmarkTag.tag_fk)
            .where(func.lower(Tag.tag).in_(wanted))
            .group_by(BookmarkTag.bookmark_fk)
        )
        if mode == "all":
            matching = matching.having(
                func.count(func.distinct(func.lower(Tag.tag))) == len(set(wanted))
            )
        stmt = stmt.where(Bookmark.id.in_(matching))
        count_stmt = count_stmt.where(Bookmark.id.in_(matching))

    if untagged:
        tagged = select(BookmarkTag.bookmark_fk).where(BookmarkTag.bookmark_fk.isnot(None))
        stmt = stmt.where(Bookmark.id.notin_(tagged))
        count_stmt = count_stmt.where(Bookmark.id.notin_(tagged))

    if q:
        pattern = f"%{q}%"
        clause = Bookmark.title.ilike(pattern) | Bookmark.url.ilike(pattern)
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)

    if site:
        # `site` is derived, not stored, until M2 -- so this is a suffix match on the
        # URL rather than an indexed lookup. Slow on 9k rows, unusable on 100k; M2's
        # stored `site` column with an index is the fix, not a cleverer LIKE.
        pattern = f"%{site.lower()}%"
        stmt = stmt.where(func.lower(Bookmark.url).like(pattern))
        count_stmt = count_stmt.where(func.lower(Bookmark.url).like(pattern))

    total = db.execute(count_stmt).scalar_one()
    stmt = (
        stmt.options(selectinload(Bookmark.tag_links).selectinload(BookmarkTag.tag))
        .order_by(Bookmark.used.desc().nullslast(), Bookmark.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [_to_out(b) for b in db.execute(stmt).scalars()]
    return BookmarkPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{bookmark_id}", response_model=BookmarkOut)
def get_bookmark(bookmark_id: int, db: DbDep) -> BookmarkOut:
    return _to_out(_loaded(db, bookmark_id))


@router.patch("/{bookmark_id}", response_model=BookmarkOut)
def patch_bookmark(
    bookmark_id: int, payload: BookmarkPatch, db: DbDep, user: UserDep
) -> BookmarkOut:
    bookmark = _loaded(db, bookmark_id)

    if payload.title is not None:
        bookmark.title = payload.title

    if payload.tags is not None:
        wanted = {t.strip().lower() for t in payload.tags if t.strip()}
        for link in list(bookmark.tag_links):
            if link.tag and link.tag.tag not in wanted:
                db.delete(link)
        db.flush()
        _attach_tags(db, bookmark, sorted(wanted))

    db.commit()
    return _to_out(_loaded(db, bookmark_id))


@router.post("/{bookmark_id}/tags", response_model=BookmarkOut)
def add_tags(bookmark_id: int, payload: TagsIn, db: DbDep, user: UserDep) -> BookmarkOut:
    """Attach tags.

    `source` is accepted and currently discarded: the column arrives in M2. It is in the
    contract now so the browser and the categoriser can be written against the final
    shape and need no change when the column lands.
    """
    bookmark = _loaded(db, bookmark_id)
    _attach_tags(db, bookmark, payload.tags)
    db.commit()
    return _to_out(_loaded(db, bookmark_id))


@router.delete("/{bookmark_id}/tags/{tag_name}", response_model=BookmarkOut)
def remove_tag(bookmark_id: int, tag_name: str, db: DbDep, user: UserDep) -> BookmarkOut:
    bookmark = _loaded(db, bookmark_id)
    target = tag_name.strip().lower()
    removed = False
    for link in list(bookmark.tag_links):
        if link.tag and (link.tag.tag or "").lower() == target:
            db.delete(link)
            removed = True
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Tag {tag_name!r} not on bookmark.")
    db.commit()
    return _to_out(_loaded(db, bookmark_id))


@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bookmark(bookmark_id: int, db: DbDep, user: UserDep) -> None:
    """Delete a bookmark and its tag links.

    WARNING: this is a hard delete. The target schema has `deleted_at` and this becomes
    a soft delete at M2; until then there is no undo, so the browser should not wire a
    one-keystroke delete to this endpoint yet.
    """
    bookmark = _loaded(db, bookmark_id)
    db.delete(bookmark)
    db.commit()
