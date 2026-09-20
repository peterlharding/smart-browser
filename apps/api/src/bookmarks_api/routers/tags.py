from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import BookmarkTag, Tag
from ..schemas import TagOut

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=list[TagOut])
def list_tags(
    db: Annotated[Session, Depends(get_db)],
    q: str | None = Query(default=None, description="Substring match on tag name"),
    min_count: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[TagOut]:
    """Tags with usage counts.

    Counts matter more than the names here: the audit found 10 tags never used and one
    blank tag on 43 bookmarks, and the browser's sidebar needs to rank by usage rather
    than list 567 entries alphabetically.
    """
    # Labelled `usage_count`, not `count`: `row.count` would resolve to the Row's
    # own tuple.count method rather than the column.
    count_col = func.count(BookmarkTag.id).label("usage_count")
    stmt = (
        select(Tag.id, Tag.tag, count_col)
        .outerjoin(BookmarkTag, BookmarkTag.tag_fk == Tag.id)
        .group_by(Tag.id, Tag.tag)
        .order_by(count_col.desc(), Tag.tag)
        .limit(limit)
    )
    if q:
        stmt = stmt.where(Tag.tag.ilike(f"%{q}%"))
    if min_count:
        stmt = stmt.having(count_col >= min_count)

    return [
        TagOut(id=row.id, name=row.tag or "", count=row.usage_count)
        for row in db.execute(stmt)
    ]
