"""`make rehash-urls`: rekeying rows saved under older normalisation rules (ADR 0011).

Rows are inserted directly, as an older normaliser would have stored them: `url` its
output and `url_hash` the SHA-256 of that.
"""

import hashlib

from sqlalchemy import select

from bookmarks_api import rehash
from bookmarks_api.models import Bookmark
from bookmarks_api.urlnorm import url_hash


def stored(db, url: str) -> int:
    row = Bookmark(url=url, url_hash=hashlib.sha256(url.encode()).digest())
    db.add(row)
    db.commit()
    return row.id


def test_a_row_the_rules_now_spell_differently_is_rekeyed(db):
    bookmark_id = stored(db, "https://bücher.de/a%7eb")

    rehash.apply(db, rehash.plan(db))

    row = db.get(Bookmark, bookmark_id)
    assert row.url == "https://xn--bcher-kva.de/a~b"
    assert row.url_hash == url_hash("https://xn--bcher-kva.de/a~b")
    assert row.site == "xn--bcher-kva.de"


def test_the_plan_changes_nothing_until_applied(db):
    bookmark_id = stored(db, "https://bücher.de/")

    work = rehash.plan(db)

    assert [c.bookmark_id for c in work.changes] == [bookmark_id]
    assert db.get(Bookmark, bookmark_id).url == "https://bücher.de/"


def test_rehashing_twice_changes_nothing_the_second_time(db):
    stored(db, "https://bücher.de/")
    stored(db, "https://example.com/docs/")

    rehash.apply(db, rehash.plan(db))
    again = rehash.plan(db)

    assert again.changes == [] and again.unchanged == 2


def test_a_row_whose_new_key_is_taken_is_reported_not_merged(db):
    """Merging chooses whose saves and tags survive, which is a decision for a person."""
    punycode = stored(db, "https://xn--bcher-kva.de/")
    unicode_ = stored(db, "https://bücher.de/")

    work = rehash.plan(db)
    rehash.apply(db, work)

    assert work.changes == []
    assert [(c.bookmark_id, c.other_ids) for c in work.collisions] == [(unicode_, (punycode,))]
    assert db.execute(select(Bookmark.url).order_by(Bookmark.id)).scalars().all() == [
        "https://xn--bcher-kva.de/", "https://bücher.de/",
    ]


def test_two_rows_converging_on_one_new_key_are_both_reported(db):
    first = stored(db, "https://bücher.de/")
    second = stored(db, "https://BÜCHER.de/")

    work = rehash.plan(db)

    assert work.changes == []
    assert sorted((c.bookmark_id, c.other_ids) for c in work.collisions) == [
        (first, (second,)), (second, (first,)),
    ]


def test_a_row_the_rules_now_reject_is_reported_and_kept(db):
    bookmark_id = stored(db, "chrome://extensions/")

    work = rehash.plan(db)
    rehash.apply(db, work)

    assert [i.bookmark_id for i in work.invalid] == [bookmark_id]
    assert "only http and https" in work.invalid[0].reason
    assert db.get(Bookmark, bookmark_id) is not None


def test_the_report_names_every_outcome(db):
    stored(db, "https://bücher.de/x")
    stored(db, "https://xn--bcher-kva.de/")
    stored(db, "https://bücher.de/")
    stored(db, "chrome://extensions/")
    stored(db, "https://example.com/")

    text = rehash.report(rehash.plan(db))

    assert text.splitlines()[0] == "1 to change, 2 unchanged, 1 collision, 1 invalid"
    assert "merge by hand" in text
