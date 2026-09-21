"""Recompute every bookmark's URL and key under the current normalisation rules.

`bookmark.url` and `bookmark.url_hash` are the output of `urlnorm.normalise()` as it was
when the row was saved. Change the rules -- and the tracking list will keep growing -- and
existing rows hold keys the new rules would never produce: a re-save of the same page then
misses its row and creates a second one. ADR 0011.

    uv run python -m bookmarks_api.rehash             # say what would change
    uv run python -m bookmarks_api.rehash --confirm   # change it

Two outcomes are reported and never acted on. A row whose new key belongs to another row is
a *collision*: the two rows are now spellings of one page, and merging them means choosing
whose saves and tags survive, which is a decision for a person. A row the new rules reject
outright (a stored `chrome://` URL, say) is *invalid*, and deleting someone's save is not a
rehash's business either.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Bookmark
from .urlnorm import normalise, site_of, url_hash


@dataclass(frozen=True)
class Change:
    bookmark_id: int
    old_url: str
    new_url: str


@dataclass(frozen=True)
class Collision:
    bookmark_id: int
    old_url: str
    new_url: str
    other_ids: tuple[int, ...]


@dataclass(frozen=True)
class Invalid:
    bookmark_id: int
    url: str
    reason: str


@dataclass
class Plan:
    changes: list[Change] = field(default_factory=list)
    collisions: list[Collision] = field(default_factory=list)
    invalid: list[Invalid] = field(default_factory=list)
    unchanged: int = 0


def plan(db: Session) -> Plan:
    """What rehashing would do. Reads only."""
    rows = db.execute(select(Bookmark.id, Bookmark.url, Bookmark.url_hash)).all()
    current = {row.url_hash: row.id for row in rows}

    proposed: dict[bytes, list[tuple[int, str, str]]] = {}
    result = Plan()
    for row in rows:
        try:
            new_url = normalise(row.url)
        except ValueError as exc:
            result.invalid.append(Invalid(row.id, row.url, str(exc)))
            continue
        new_hash = url_hash(new_url)
        if new_hash == row.url_hash:
            result.unchanged += 1
            continue
        proposed.setdefault(new_hash, []).append((row.id, row.url, new_url))

    # A changing row collides when its new key is some other row's key now, or another
    # changing row's key-to-be. Neither is applied, so the apply step below can never trip
    # UNIQUE (url_hash) part way through.
    for new_hash, claimants in proposed.items():
        holder = current.get(new_hash)
        for bookmark_id, old_url, new_url in claimants:
            others = [other for other, _, _ in claimants if other != bookmark_id]
            if holder is not None:
                others.append(holder)
            if others:
                result.collisions.append(
                    Collision(bookmark_id, old_url, new_url, tuple(sorted(others)))
                )
            else:
                result.changes.append(Change(bookmark_id, old_url, new_url))

    result.changes.sort(key=lambda c: c.bookmark_id)
    result.collisions.sort(key=lambda c: c.bookmark_id)
    return result


def apply(db: Session, work: Plan) -> None:
    """Apply *work*'s changes in one transaction. Collisions and invalid rows are left alone."""
    for change in work.changes:
        bookmark = db.get(Bookmark, change.bookmark_id)
        assert bookmark is not None
        bookmark.url = change.new_url
        bookmark.url_hash = url_hash(change.new_url)
        bookmark.site = site_of(change.new_url)
    db.commit()


def report(work: Plan) -> str:
    collisions = len(work.collisions)
    lines = [
        f"{len(work.changes)} to change, {work.unchanged} unchanged, "
        f"{collisions} {'collision' if collisions == 1 else 'collisions'}, "
        f"{len(work.invalid)} invalid"
    ]
    for change in work.changes:
        lines.append(f"  change    {change.bookmark_id}: {change.old_url}  ->  {change.new_url}")
    for collision in work.collisions:
        others = ", ".join(str(i) for i in collision.other_ids)
        lines.append(
            f"  collision {collision.bookmark_id}: {collision.old_url}  ->  {collision.new_url}"
            f"  (the key of {others}; merge by hand)"
        )
    for invalid in work.invalid:
        lines.append(f"  invalid   {invalid.bookmark_id}: {invalid.url}  ({invalid.reason})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm", action="store_true", help="apply the changes")
    args = parser.parse_args(argv)

    from .db import get_sessionmaker

    with get_sessionmaker()() as db:
        work = plan(db)
        print(report(work))
        if not work.changes:
            return 0
        if not args.confirm:
            print("\nNothing changed. Re-run with --confirm (make rehash-urls CONFIRM=yes).")
            return 0
        apply(db, work)
        changed = len(work.changes)
        print(f"\nChanged {changed} {'row' if changed == 1 else 'rows'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
