"""Saving the same page repeatedly must never produce a second row.

This is the promise the whole save flow is built around, so it gets its own file. The
audit measured 23% duplicates -- 2,216 rows of 9,472 -- in a system whose save endpoint
inserted unconditionally. These tests are the reason that cannot happen here.
"""


from bookmarks_api.models import Bookmark, UserBookmark


def post(client, auth, **payload):
    return client.post("/api/v2/bookmarks", json=payload, headers=auth)


def test_saving_twenty_times_creates_one_row(client, auth, db):
    for _ in range(20):
        post(client, auth, url="https://example.com/a")

    assert db.query(Bookmark).count() == 1
    assert db.query(UserBookmark).count() == 1
    assert client.get("/api/v2/bookmarks", headers=auth).json()["total"] == 1


def test_first_save_is_201_and_the_rest_are_200(client, auth):
    assert post(client, auth, url="https://example.com/a").status_code == 201
    for _ in range(3):
        assert post(client, auth, url="https://example.com/a").status_code == 200


def test_every_spelling_of_the_same_page_is_one_row(client, auth, db):
    """The spellings that produced most of the duplicates the audit measured."""
    for variant in [
        "https://example.com/docs",
        "https://example.com/docs/",
        "HTTPS://EXAMPLE.COM/docs",
        "https://example.com:443/docs",
        "https://example.com/docs#section",
        "https://example.com/docs?utm_source=newsletter",
        "https://example.com/docs?fbclid=xyz",
        "https://user:pw@example.com/docs",
        "https://example.com./docs",
        "example.com/docs",
    ]:
        post(client, auth, url=variant)

    assert db.query(Bookmark).count() == 1


def test_pages_that_really_differ_stay_separate(client, auth, db):
    """The guard against over-merging, which would be worse than duplicating."""
    for url in [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/a?id=1",
        "https://example.com/a?id=2",
        "http://example.com/a",
        "https://example.com:8443/a",
    ]:
        post(client, auth, url=url)

    assert db.query(Bookmark).count() == 6


def test_repeat_saves_accumulate_tags_rather_than_replacing_them(client, auth):
    post(client, auth, url="https://example.com/a", tags=["python"])
    post(client, auth, url="https://example.com/a", tags=["fastapi"])
    body = post(client, auth, url="https://example.com/a", tags=["postgres"]).json()
    assert body["tags"] == ["fastapi", "postgres", "python"]


def test_repeating_the_same_tag_does_not_duplicate_the_link(client, auth, db):
    from bookmarks_api.models import BookmarkTag

    for _ in range(5):
        post(client, auth, url="https://example.com/a", tags=["python", "PYTHON", " python "])

    assert db.query(BookmarkTag).count() == 1


def test_two_users_saving_one_page_share_the_url_record(client, auth, db, other_client, other_auth):
    """The point of splitting the URL from the save: one crawl and one embedding, ever."""
    post(client, auth, url="https://example.com/a")
    post(other_client, other_auth, url="https://example.com/a")

    assert db.query(Bookmark).count() == 1
    assert db.query(UserBookmark).count() == 2


def test_the_constraint_not_the_code_is_what_enforces_it(db):
    """A direct insert bypassing the API must still be rejected.

    If this passes only because `save_bookmark` is careful, the guarantee is a code
    convention. It should be a database constraint.
    """
    import pytest
    from sqlalchemy.exc import IntegrityError

    from bookmarks_api.urlnorm import url_hash

    digest = url_hash("https://example.com/a")
    db.add(Bookmark(url="https://example.com/a", url_hash=digest))
    db.commit()

    db.add(Bookmark(url="https://example.com/a-different-spelling", url_hash=digest))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
