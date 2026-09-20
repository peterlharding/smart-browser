"""Bookmark routes.

The contract that matters: **save the same page as often as you like and you will never
get a duplicate.** That is not enforced here. It is enforced by `UNIQUE (url_hash)` on
`bookmark`, and this module's job is to insert in a way that constraint can arbitrate --
`ON CONFLICT DO NOTHING` followed by a read, rather than check-then-insert, which always
has a window between the check and the insert however narrow you make it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import CurrentUser, ViewingUser
from ..models import AppUser, Bookmark, BookmarkTag, Tag, TagAlias, TagSource, UserBookmark
from ..schemas import BookmarkCreate, BookmarkOut, BookmarkPage, BookmarkPatch, TagsIn
from ..urlnorm import normalise, site_of, url_hash

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])

DbDep = Annotated[Session, Depends(get_db)]


# --- helpers -----------------------------------------------------------------


def _insert(db: Session):
    """`INSERT ... ON CONFLICT` for whichever backend is in play."""
    return sqlite_insert if db.bind is not None and db.bind.dialect.name == "sqlite" else pg_insert


def _out(save: UserBookmark) -> BookmarkOut:
    return BookmarkOut(
        id=save.id,
        url=save.bookmark.url,
        title=save.title,
        site=save.bookmark.site,
        saved_from=save.saved_from,
        created_at=save.created_at,
        notes=save.notes,
        tags=save.tags,
    )


def _scoped(user: AppUser) -> Select[tuple[UserBookmark]]:
    """Every read starts here.

    `bookmark` rows are shared between users, so a query that reaches them directly leaks
    the existence of other people's saves. Starting from `user_bookmark` filtered by
    `user_id` is the invariant from ADR 0001, and `test_scoping.py` exists to keep it.
    """
    return (
        select(UserBookmark)
        .options(
            selectinload(UserBookmark.tag_links).selectinload(BookmarkTag.tag),
            selectinload(UserBookmark.bookmark),
        )
        .where(UserBookmark.user_id == user.id, UserBookmark.deleted_at.is_(None))
    )


def _load(db: Session, user: AppUser, save_id: int) -> UserBookmark:
    found = (
        db.execute(_scoped(user).where(UserBookmark.id == save_id))
        .unique()
        .scalar_one_or_none()
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Bookmark not found.")
    return found


def _upsert_bookmark(db: Session, url: str) -> Bookmark:
    """Get the `bookmark` row for *url*, creating it only if nobody has.

    `ON CONFLICT DO NOTHING` then re-read: the database decides whether this URL is new,
    and two concurrent callers cannot both conclude that it is.
    """
    normalised = normalise(url)
    digest = url_hash(url)

    db.execute(
        _insert(db)(Bookmark)
        .values(url=normalised, url_hash=digest, site=site_of(normalised))
        .on_conflict_do_nothing(index_elements=[Bookmark.url_hash])
    )
    return db.execute(select(Bookmark).where(Bookmark.url_hash == digest)).scalar_one()


def _resolve_tag(db: Session, raw: str) -> Tag:
    """Canonical tag for *raw*, following aliases and creating on first use."""
    name = raw.strip().lower()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Blank tag.")

    alias = db.execute(select(TagAlias).where(TagAlias.alias == name)).scalar_one_or_none()
    if alias is not None:
        return alias.tag

    db.execute(
        _insert(db)(Tag).values(name=name).on_conflict_do_nothing(index_elements=[Tag.name])
    )
    return db.execute(select(Tag).where(Tag.name == name)).scalar_one()


def _attach_tags(db: Session, save: UserBookmark, names: list[str],
                 source: TagSource = TagSource.USER) -> None:
    for raw in names:
        tag = _resolve_tag(db, raw)
        db.execute(
            _insert(db)(BookmarkTag)
            .values(user_bookmark_id=save.id, tag_id=tag.id, source=source.value)
            .on_conflict_do_nothing(index_elements=[
                BookmarkTag.user_bookmark_id, BookmarkTag.tag_id,
            ])
        )
    db.flush()


# --- routes ------------------------------------------------------------------


@router.post("", response_model=BookmarkOut)
def save_bookmark(
    payload: BookmarkCreate, response: Response, db: DbDep, user: CurrentUser
) -> BookmarkOut:
    """Save a page.

    201 the first time, 200 every time after, never a second row — whatever the spelling
    of the URL and however many clients call at once. Tags in the payload are merged on
    every call, so re-saving with new tags adds them rather than failing.
    """
    try:
        normalise(payload.url)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    bookmark = _upsert_bookmark(db, payload.url)

    # RETURNING rather than rowcount: it says which row, not merely how many, and it is
    # the same single statement either way.
    inserted = db.execute(
        _insert(db)(UserBookmark)
        .values(
            user_id=user.id,
            bookmark_id=bookmark.id,
            saved_from=payload.saved_from or "api",
            title_override=payload.title or None,
        )
        .on_conflict_do_nothing(index_elements=[UserBookmark.user_id, UserBookmark.bookmark_id])
        .returning(UserBookmark.id)
    ).scalar_one_or_none()
    created = inserted is not None

    save = db.execute(
        select(UserBookmark).where(
            UserBookmark.user_id == user.id, UserBookmark.bookmark_id == bookmark.id
        )
    ).scalar_one()

    # Re-saving a page you had deleted brings it back rather than staying invisible.
    if save.deleted_at is not None:
        save.deleted_at = None
        created = True

    if payload.tags:
        _attach_tags(db, save, payload.tags)

    db.commit()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _out(_load(db, user, save.id))


@router.get("", response_model=BookmarkPage)
def list_bookmarks(
    db: DbDep,
    user: ViewingUser,
    tags: str | None = Query(default=None, description="Comma-separated tag names"),
    mode: Literal["all", "any"] = Query(default="all"),
    site: str | None = None,
    q: str | None = Query(default=None, description="Substring match on title or URL"),
    untagged: bool = Query(default=False, description="Only bookmarks with no tags"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> BookmarkPage:
    """List your saves.

    `mode=all` is the intersection the tag sidebar is built on — `python` AND `fastapi`.
    `untagged=true` is how you work the backlog.
    """
    stmt = _scoped(user).join(Bookmark, Bookmark.id == UserBookmark.bookmark_id)
    count_stmt = (
        select(func.count(UserBookmark.id))
        .join(Bookmark, Bookmark.id == UserBookmark.bookmark_id)
        .where(UserBookmark.user_id == user.id, UserBookmark.deleted_at.is_(None))
    )

    wanted = [t.strip().lower() for t in tags.split(",")] if tags else []
    wanted = [t for t in wanted if t]

    def narrow(*clauses):
        nonlocal stmt, count_stmt
        stmt = stmt.where(*clauses)
        count_stmt = count_stmt.where(*clauses)

    if wanted:
        matching = (
            select(BookmarkTag.user_bookmark_id)
            .join(Tag, Tag.id == BookmarkTag.tag_id)
            .where(Tag.name.in_(wanted))
            .group_by(BookmarkTag.user_bookmark_id)
        )
        if mode == "all":
            matching = matching.having(func.count(func.distinct(Tag.name)) == len(set(wanted)))
        narrow(UserBookmark.id.in_(matching))

    if untagged:
        narrow(UserBookmark.id.notin_(select(BookmarkTag.user_bookmark_id)))

    if q:
        pattern = f"%{q}%"
        narrow(
            Bookmark.title.ilike(pattern)
            | Bookmark.url.ilike(pattern)
            | UserBookmark.title_override.ilike(pattern)
        )

    if site:
        narrow(Bookmark.site == site.strip().lower())

    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(UserBookmark.created_at.desc(), UserBookmark.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .unique()
        .scalars()
    )
    return BookmarkPage(items=[_out(s) for s in rows], total=total, limit=limit, offset=offset)


# NOTE: /lookup must be declared before /{save_id}. FastAPI matches in declaration order,
# and with the int-typed path parameter first, "lookup" would be parsed as an integer and
# rejected with 422 before reaching this handler.
@router.get("/lookup", response_model=BookmarkOut)
def lookup_bookmark(db: DbDep, user: ViewingUser, url: str = Query(min_length=1)) -> BookmarkOut:
    """Have I saved this page, and with what tags?

    A read. `POST /bookmarks` is idempotent and would answer the same question, but it is
    a write: a client calling it merely to ask would create a bookmark every time someone
    opened a popup. 404 means not saved, which is a normal answer here.
    """
    try:
        digest = url_hash(url)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    found = (
        db.execute(
            _scoped(user)
            .join(Bookmark, Bookmark.id == UserBookmark.bookmark_id)
            .where(Bookmark.url_hash == digest)
        )
        .unique()
        .scalar_one_or_none()
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not saved.")
    return _out(found)


@router.get("/{save_id}", response_model=BookmarkOut)
def get_bookmark(save_id: int, db: DbDep, user: ViewingUser) -> BookmarkOut:
    return _out(_load(db, user, save_id))


@router.patch("/{save_id}", response_model=BookmarkOut)
def patch_bookmark(
    save_id: int, payload: BookmarkPatch, db: DbDep, user: CurrentUser
) -> BookmarkOut:
    save = _load(db, user, save_id)

    if payload.title is not None:
        save.title_override = payload.title or None
    if payload.notes is not None:
        save.notes = payload.notes or None

    if payload.tags is not None:
        wanted = {t.strip().lower() for t in payload.tags if t.strip()}
        for link in list(save.tag_links):
            if link.tag.name not in wanted:
                db.delete(link)
        db.flush()
        _attach_tags(db, save, sorted(wanted))

    db.commit()
    return _out(_load(db, user, save_id))


@router.post("/{save_id}/tags", response_model=BookmarkOut)
def add_tags(save_id: int, payload: TagsIn, db: DbDep, user: CurrentUser) -> BookmarkOut:
    save = _load(db, user, save_id)
    _attach_tags(db, save, payload.tags, TagSource(payload.source))
    db.commit()
    return _out(_load(db, user, save_id))


@router.delete("/{save_id}/tags/{tag_name}", response_model=BookmarkOut)
def remove_tag(save_id: int, tag_name: str, db: DbDep, user: CurrentUser) -> BookmarkOut:
    save = _load(db, user, save_id)
    target = tag_name.strip().lower()

    removed = False
    for link in list(save.tag_links):
        if link.tag.name == target:
            db.delete(link)
            removed = True
    if not removed:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"Tag {tag_name!r} not on bookmark."
        )

    db.commit()
    return _out(_load(db, user, save_id))


@router.delete("/{save_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bookmark(save_id: int, db: DbDep, user: CurrentUser) -> None:
    """Unsave a page.

    A soft delete of *your* save. The `bookmark` row and anything crawled for it survive,
    because they belong to everyone; and re-saving the page restores this row rather than
    creating a second one.
    """
    save = _load(db, user, save_id)
    save.deleted_at = func.now()
    db.commit()
