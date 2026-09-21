"""What a tag name may be, and aliases on every path that names a tag (ADR 0014).

Each test here was a bug first, reproduced against a running API: a comma-bearing tag that
no filter could reach, an alias that found nothing, deleted nothing, and turned an AI
suggestion into your own choice, and a tag with a slash that could never be removed.
"""

import pytest
from fastapi import status
from sqlalchemy import select

from bookmarks_api.models import BookmarkTag, Tag, TagAlias, TagSource
from bookmarks_api.schemas import clean_tag

BOOKMARKS = "/api/v1/bookmarks"


def post(client, auth, **payload):
    return client.post(BOOKMARKS, json=payload, headers=auth)


@pytest.fixture
def alias(db):
    """`boorstrap` resolves to `bootstrap`, as the audit's misspelling does."""
    tag = Tag(name="bootstrap")
    db.add(tag)
    db.flush()
    db.add(TagAlias(alias="boorstrap", tag_id=tag.id))
    db.commit()


def total(client, auth, **params) -> int:
    return client.get(BOOKMARKS, params=params, headers=auth).json()["total"]


# --- what a tag name may be -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("  Python ", "python"),
        ("c++", "c++"),
        ("c#", "c#"),
        ("ci/cd", "ci/cd"),
        ("web-dev", "web-dev"),
        ("日本語", "日本語"),
        ("👨‍💻", "👨‍💻"),  # zero-width joiners are not control characters
        ("x" * 200, "x" * 200),  # no length limit (ADR 0006)
        ("   ", ""),
    ],
)
def test_names_that_are_tags(raw, stored):
    assert clean_tag(raw) == stored


@pytest.mark.parametrize("raw", ["red,green", "machine learning", "tab\there", "new\nline",
                                 "no break", "bell\x07"])
def test_names_that_are_not(raw):
    with pytest.raises(ValueError, match="cannot contain commas, whitespace or control"):
        clean_tag(raw)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", BOOKMARKS, {"url": "https://a.example/", "tags": ["red,green"]}),
        ("post", f"{BOOKMARKS}/{{id}}/tags", {"tags": ["machine learning"]}),
        ("patch", f"{BOOKMARKS}/{{id}}", {"tags": ["tab\there"]}),
    ],
)
def test_every_write_path_refuses_them(client, auth, method, path, body):
    saved = post(client, auth, url="https://saved.example/").json()
    r = getattr(client, method)(path.format(id=saved["id"]), json=body, headers=auth)
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "cannot contain commas, whitespace or control characters" in r.text


def test_a_blank_entry_in_a_typed_list_is_dropped_not_refused(client, auth):
    """A trailing comma in the save sheet is not an error."""
    r = post(client, auth, url="https://a.example/", tags=["python", "  "])
    assert r.json()["tags"] == ["python"]


# --- a tag containing a slash ------------------------------------------------------


def test_a_tag_with_a_slash_can_be_removed(client, auth):
    saved = post(client, auth, url="https://a.example/", tags=["ci/cd", "python"]).json()
    r = client.delete(f"{BOOKMARKS}/{saved['id']}/tags/ci%2Fcd", headers=auth)
    assert r.status_code == status.HTTP_200_OK
    assert r.json()["tags"] == ["python"]


def test_a_tag_with_a_slash_can_be_filtered_on(client, auth):
    post(client, auth, url="https://a.example/", tags=["ci/cd"])
    assert total(client, auth, tags="ci/cd") == 1


# --- aliases ------------------------------------------------------------------------


def test_saving_with_an_alias_stores_the_tag(client, auth, alias):
    assert post(client, auth, url="https://a.example/", tags=["boorstrap"]).json()["tags"] == [
        "bootstrap"
    ]


def test_filtering_by_an_alias_finds_the_tag(client, auth, alias):
    post(client, auth, url="https://a.example/", tags=["bootstrap"])
    assert total(client, auth, tags="boorstrap") == 1


def test_an_alias_and_its_tag_in_one_filter_are_one_tag(client, auth, alias):
    """mode=all counts distinct tags; the alias must not count as a second one."""
    post(client, auth, url="https://a.example/", tags=["bootstrap"])
    assert total(client, auth, tags="bootstrap,boorstrap", mode="all") == 1


def test_removing_by_an_alias_removes_the_tag(client, auth, alias):
    saved = post(client, auth, url="https://a.example/", tags=["bootstrap", "css"]).json()
    r = client.delete(f"{BOOKMARKS}/{saved['id']}/tags/boorstrap", headers=auth)
    assert r.status_code == status.HTTP_200_OK
    assert r.json()["tags"] == ["css"]


def test_patching_with_an_alias_keeps_the_links_source(client, auth, db, alias):
    """Deleting and re-adding the link would turn an AI suggestion into your own choice."""
    saved = post(client, auth, url="https://a.example/").json()
    client.post(f"{BOOKMARKS}/{saved['id']}/tags", json={"tags": ["bootstrap"], "source": "ai"},
                headers=auth)

    r = client.patch(f"{BOOKMARKS}/{saved['id']}", json={"tags": ["boorstrap"]}, headers=auth)

    assert r.json()["tags"] == ["bootstrap"]
    db.expire_all()
    source = db.execute(
        select(BookmarkTag.source).where(BookmarkTag.user_bookmark_id == saved["id"])
    ).scalar_one()
    assert source is TagSource.AI


def test_patching_with_an_alias_of_a_new_tag_adds_the_tag(client, auth, alias):
    saved = post(client, auth, url="https://a.example/", tags=["css"]).json()
    r = client.patch(f"{BOOKMARKS}/{saved['id']}", json={"tags": ["css", "boorstrap"]},
                     headers=auth)
    assert r.json()["tags"] == ["bootstrap", "css"]
