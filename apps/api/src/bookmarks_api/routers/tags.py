from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import ViewingUser
from ..models import BookmarkTag, Tag, UserBookmark
from ..schemas import TagOut

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=list[TagOut])
def list_tags(
    db: Annotated[Session, Depends(get_db)],
    user: ViewingUser,
    q: str | None = Query(default=None, description="Substring match on tag name"),
    min_count: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[TagOut]:
    """Your tags, with how often you have used them.

    The vocabulary is global (ADR 0002) but the counts are yours: what belongs in an
    autocomplete list is how often *you* reach for a tag. Ranking by usage rather than
    alphabetically is what makes a 567-entry vocabulary usable at all.
    """
    count_col = func.count(BookmarkTag.user_bookmark_id).label("usage_count")
    stmt = (
        select(Tag.id, Tag.name, count_col)
        .join(BookmarkTag, BookmarkTag.tag_id == Tag.id)
        .join(UserBookmark, UserBookmark.id == BookmarkTag.user_bookmark_id)
        .where(UserBookmark.user_id == user.id, UserBookmark.deleted_at.is_(None))
        .group_by(Tag.id, Tag.name)
        .order_by(count_col.desc(), Tag.name)
        .limit(limit)
    )
    if q:
        stmt = stmt.where(Tag.name.ilike(f"%{q}%"))
    if min_count:
        stmt = stmt.having(count_col >= min_count)

    return [TagOut(id=r.id, name=r.name, count=r.usage_count) for r in db.execute(stmt)]
