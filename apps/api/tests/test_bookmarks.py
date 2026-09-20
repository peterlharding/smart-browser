"""Bookmark routes.

The idempotency tests are the important ones: 2,216 of 9,472 rows in the current corpus
are duplicate URLs, created by an endpoint that inserts unconditionally.
"""

from fastapi import status


def post(client, auth, **payload):
    return client.post("/api/v2/bookmarks", json=payload, headers=auth)


# --- idempotency -------------------------------------------------------------


def test_saving_a_new_url_creates_it(client, auth):
    r = post(client, auth, url="https://example.com/a", title="A")
    assert r.status_code == status.HTTP_201_CREATED
    assert r.json()["title"] == "A"


def test_saving_the_same_url_twice_does_not_duplicate(client, auth):
    first = post(client, auth, url="https://example.com/a")
    second = post(client, auth, url="https://example.com/a")

    assert first.status_code == status.HTTP_201_CREATED
    assert second.status_code == status.HTTP_200_OK
    assert first.json()["id"] == second.json()["id"]
    assert client.get("/api/v2/bookmarks").json()["total"] == 1


def test_urls_differing_only_by_tracking_params_are_the_same_bookmark(client, auth):
    post(client, auth, url="https://example.com/a")
    second = post(client, auth, url="https://example.com/a?utm_source=newsletter")

    assert second.status_code == status.HTTP_200_OK
    assert client.get("/api/v2/bookmarks").json()["total"] == 1


def test_urls_differing_by_a_real_param_are_distinct(client, auth):
    post(client, auth, url="https://example.com/a?id=1")
    post(client, auth, url="https://example.com/a?id=2")
    assert client.get("/api/v2/bookmarks").json()["total"] == 2


def test_resaving_with_new_tags_adds_them(client, auth):
    post(client, auth, url="https://example.com/a", tags=["python"])
    r = post(client, auth, url="https://example.com/a", tags=["fastapi"])

    assert r.status_code == status.HTTP_200_OK
    assert r.json()["tags"] == ["fastapi", "python"]


def test_repeated_tags_do_not_create_duplicate_links(client, auth):
    post(client, auth, url="https://example.com/a", tags=["python"])
    r = post(client, auth, url="https://example.com/a", tags=["python", "PYTHON", " python "])
    assert r.json()["tags"] == ["python"]


def test_stored_url_is_normalised(client, auth):
    r = post(client, auth, url="HTTPS://Example.COM:443/docs/?utm_medium=x#frag")
    assert r.json()["url"] == "https://example.com/docs"


def test_invalid_url_is_rejected(client, auth):
    assert post(client, auth, url="   ").status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


# --- derived fields ----------------------------------------------------------


def test_site_is_the_registrable_domain_not_the_posting_host(client, auth):
    """`host` in the v1 schema holds the poster, not the site -- see audit finding 6."""
    r = post(client, auth, url="https://docs.python.org/3/library/", saved_from="AASDev")
    body = r.json()
    assert body["site"] == "python.org"
    assert body["saved_from"] == "AASDev"


# --- tag filtering -----------------------------------------------------------


def _seed(client, auth):
    post(client, auth, url="https://example.com/1", tags=["python", "fastapi"])
    post(client, auth, url="https://example.com/2", tags=["python"])
    post(client, auth, url="https://example.com/3", tags=["javascript"])
    post(client, auth, url="https://example.com/4")


def test_mode_all_is_the_intersection(client, auth):
    _seed(client, auth)
    r = client.get("/api/v2/bookmarks", params={"tags": "python,fastapi", "mode": "all"})
    assert r.json()["total"] == 1


def test_mode_any_is_the_union(client, auth):
    _seed(client, auth)
    r = client.get("/api/v2/bookmarks", params={"tags": "python,javascript", "mode": "any"})
    assert r.json()["total"] == 3


def test_untagged_filter_finds_the_backlog(client, auth):
    _seed(client, auth)
    r = client.get("/api/v2/bookmarks", params={"untagged": True})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["url"] == "https://example.com/4"


def test_text_search_matches_title_or_url(client, auth):
    post(client, auth, url="https://example.com/x", title="Postgres tuning")
    post(client, auth, url="https://postgresql.org/docs", title="Docs")

    assert client.get("/api/v2/bookmarks", params={"q": "postgres"}).json()["total"] == 2
    assert client.get("/api/v2/bookmarks", params={"q": "tuning"}).json()["total"] == 1


def test_pagination_reports_total_beyond_the_page(client, auth):
    for i in range(5):
        post(client, auth, url=f"https://example.com/{i}")
    body = client.get("/api/v2/bookmarks", params={"limit": 2}).json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2


# --- mutation ----------------------------------------------------------------


def test_patch_replaces_the_tag_set(client, auth):
    created = post(client, auth, url="https://example.com/a", tags=["python", "old"]).json()
    r = client.patch(
        f"/api/v2/bookmarks/{created['id']}", json={"tags": ["python", "new"]}, headers=auth
    )
    assert r.json()["tags"] == ["new", "python"]


def test_patch_title_leaves_tags_alone(client, auth):
    created = post(client, auth, url="https://example.com/a", tags=["python"]).json()
    r = client.patch(
        f"/api/v2/bookmarks/{created['id']}", json={"title": "Renamed"}, headers=auth
    )
    assert r.json()["title"] == "Renamed"
    assert r.json()["tags"] == ["python"]


def test_add_and_remove_a_single_tag(client, auth):
    created = post(client, auth, url="https://example.com/a").json()
    bid = created["id"]

    added = client.post(
        f"/api/v2/bookmarks/{bid}/tags", json={"tags": ["python"]}, headers=auth
    )
    assert added.json()["tags"] == ["python"]

    removed = client.delete(f"/api/v2/bookmarks/{bid}/tags/python", headers=auth)
    assert removed.json()["tags"] == []


def test_removing_an_absent_tag_is_404(client, auth):
    created = post(client, auth, url="https://example.com/a").json()
    r = client.delete(f"/api/v2/bookmarks/{created['id']}/tags/nope", headers=auth)
    assert r.status_code == status.HTTP_404_NOT_FOUND


def test_tag_longer_than_the_column_is_rejected_not_truncated(client, auth):
    """The current column is varchar(32). Silent truncation would corrupt the vocabulary."""
    r = post(client, auth, url="https://example.com/a", tags=["x" * 33])
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_delete_removes_the_bookmark_and_its_links(client, auth, db):
    from bookmarks_api.models import BookmarkTag

    created = post(client, auth, url="https://example.com/a", tags=["python"]).json()
    assert client.delete(
        f"/api/v2/bookmarks/{created['id']}", headers=auth
    ).status_code == status.HTTP_204_NO_CONTENT

    assert client.get(f"/api/v2/bookmarks/{created['id']}").status_code == 404
    assert db.query(BookmarkTag).count() == 0


def test_missing_bookmark_is_404(client):
    assert client.get("/api/v2/bookmarks/999999").status_code == status.HTTP_404_NOT_FOUND
