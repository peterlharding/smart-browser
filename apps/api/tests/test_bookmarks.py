"""Bookmark routes.

The idempotency tests are the important ones: 2,216 of 9,472 rows in the current corpus
are duplicate URLs, created by an endpoint that inserts unconditionally.
"""

from fastapi import status


def post(client, auth, **payload):
    return client.post("/api/v1/bookmarks", json=payload, headers=auth)


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
    assert client.get("/api/v1/bookmarks", headers=auth).json()["total"] == 1


def test_urls_differing_only_by_tracking_params_are_the_same_bookmark(client, auth):
    post(client, auth, url="https://example.com/a")
    second = post(client, auth, url="https://example.com/a?utm_source=newsletter")

    assert second.status_code == status.HTTP_200_OK
    assert client.get("/api/v1/bookmarks", headers=auth).json()["total"] == 1


def test_urls_differing_by_a_real_param_are_distinct(client, auth):
    post(client, auth, url="https://example.com/a?id=1")
    post(client, auth, url="https://example.com/a?id=2")
    assert client.get("/api/v1/bookmarks", headers=auth).json()["total"] == 2


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


def test_site_is_the_registrable_domain_not_the_posting_client(client, auth):
    """Two different facts. Conflating them is why the predecessor's list-by-domain never worked."""
    r = post(client, auth, url="https://docs.python.org/3/library/", saved_from="AASDev")
    body = r.json()
    assert body["site"] == "python.org"
    assert body["saved_from"] == "AASDev"


def test_site_filter_is_an_exact_match_on_the_stored_domain(client, auth):
    post(client, auth, url="https://docs.python.org/3/")
    post(client, auth, url="https://pypi.org/project/x/")
    assert client.get(
        "/api/v1/bookmarks", params={"site": "python.org"}, headers=auth
    ).json()["total"] == 1


# --- tag filtering -----------------------------------------------------------


def _seed(client, auth):
    post(client, auth, url="https://example.com/1", tags=["python", "fastapi"])
    post(client, auth, url="https://example.com/2", tags=["python"])
    post(client, auth, url="https://example.com/3", tags=["javascript"])
    post(client, auth, url="https://example.com/4")


def test_mode_all_is_the_intersection(client, auth):
    _seed(client, auth)
    r =client.get(
        "/api/v1/bookmarks", params={"tags": "python,fastapi", "mode": "all"}, headers=auth
    )
    assert r.json()["total"] == 1


def test_mode_any_is_the_union(client, auth):
    _seed(client, auth)
    r =client.get(
        "/api/v1/bookmarks", params={"tags": "python,javascript", "mode": "any"}, headers=auth
    )
    assert r.json()["total"] == 3


def test_untagged_filter_finds_the_backlog(client, auth):
    _seed(client, auth)
    r = client.get("/api/v1/bookmarks", params={"untagged": True}, headers=auth)
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["url"] == "https://example.com/4"


def test_text_search_matches_title_or_url(client, auth):
    post(client, auth, url="https://example.com/x", title="Postgres tuning")
    post(client, auth, url="https://postgresql.org/docs", title="Docs")

    assert client.get(
        "/api/v1/bookmarks", params={"q": "postgres"}, headers=auth
    ).json()["total"] == 2
    assert client.get(
        "/api/v1/bookmarks", params={"q": "tuning"}, headers=auth
    ).json()["total"] == 1


def test_pagination_reports_total_beyond_the_page(client, auth):
    for i in range(5):
        post(client, auth, url=f"https://example.com/{i}")
    body = client.get("/api/v1/bookmarks", params={"limit": 2}, headers=auth).json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2


# --- mutation ----------------------------------------------------------------


def test_patch_replaces_the_tag_set(client, auth):
    created = post(client, auth, url="https://example.com/a", tags=["python", "old"]).json()
    r = client.patch(
        f"/api/v1/bookmarks/{created['id']}", json={"tags": ["python", "new"]}, headers=auth
    )
    assert r.json()["tags"] == ["new", "python"]


def test_patch_title_leaves_tags_alone(client, auth):
    created = post(client, auth, url="https://example.com/a", tags=["python"]).json()
    r = client.patch(
        f"/api/v1/bookmarks/{created['id']}", json={"title": "Renamed"}, headers=auth
    )
    assert r.json()["title"] == "Renamed"
    assert r.json()["tags"] == ["python"]


def test_add_and_remove_a_single_tag(client, auth):
    created = post(client, auth, url="https://example.com/a").json()
    bid = created["id"]

    added = client.post(
        f"/api/v1/bookmarks/{bid}/tags", json={"tags": ["python"]}, headers=auth
    )
    assert added.json()["tags"] == ["python"]

    removed = client.delete(f"/api/v1/bookmarks/{bid}/tags/python", headers=auth)
    assert removed.json()["tags"] == []


def test_removing_an_absent_tag_is_404(client, auth):
    created = post(client, auth, url="https://example.com/a").json()
    r = client.delete(f"/api/v1/bookmarks/{created['id']}/tags/nope", headers=auth)
    assert r.status_code == status.HTTP_404_NOT_FOUND


def test_long_tags_are_accepted_now_the_column_is_text(client, auth):
    """`tag.name` is text: nothing about a tag justifies a length limit."""
    long_tag = "x" * 80
    r = post(client, auth, url="https://example.com/a", tags=[long_tag])
    assert r.json()["tags"] == [long_tag]


def test_blank_tags_are_rejected(client, auth):
    """One blank tag on 43 bookmarks is exactly how a vocabulary decays."""
    r = client.post(
        "/api/v1/bookmarks/1/tags", json={"tags": ["  "]}, headers=auth
    )
    assert r.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT)


def test_delete_hides_the_save_but_keeps_the_url_record(client, auth, db):
    """Soft delete: the shared bookmark row belongs to everyone, your save does not."""
    from bookmarks_api.models import Bookmark

    created = post(client, auth, url="https://example.com/a", tags=["python"]).json()
    assert client.delete(
        f"/api/v1/bookmarks/{created['id']}", headers=auth
    ).status_code == status.HTTP_204_NO_CONTENT

    assert client.get(f"/api/v1/bookmarks/{created['id']}", headers=auth).status_code == 404
    assert client.get("/api/v1/bookmarks", headers=auth).json()["total"] == 0
    assert db.query(Bookmark).count() == 1


def test_resaving_a_deleted_page_restores_it(client, auth):
    created = post(client, auth, url="https://example.com/a").json()
    client.delete(f"/api/v1/bookmarks/{created['id']}", headers=auth)

    again = post(client, auth, url="https://example.com/a")
    assert again.status_code == status.HTTP_201_CREATED
    assert again.json()["id"] == created["id"], "restored, not duplicated"
    assert client.get("/api/v1/bookmarks", headers=auth).json()["total"] == 1


def test_missing_bookmark_is_404(client, auth):
    assert client.get(
        "/api/v1/bookmarks/999999", headers=auth
    ).status_code == status.HTTP_404_NOT_FOUND


# --- lookup ------------------------------------------------------------------


def test_lookup_finds_a_saved_url_with_its_tags(client, auth):
    post(client, auth, url="https://example.com/a", tags=["python"])
    r =client.get(
        "/api/v1/bookmarks/lookup", params={"url": "https://example.com/a"}, headers=auth
    )
    assert r.status_code == status.HTTP_200_OK
    assert r.json()["tags"] == ["python"]


def test_lookup_matches_through_normalisation(client, auth):
    post(client, auth, url="https://example.com/docs")
    r = client.get(
        "/api/v1/bookmarks/lookup",
        params={"url": "HTTPS://Example.COM:443/docs/?utm_source=x#frag"},
        headers=auth,
    )
    assert r.status_code == status.HTTP_200_OK


def test_lookup_of_an_unsaved_url_is_404(client, auth):
    r =client.get(
        "/api/v1/bookmarks/lookup", params={"url": "https://example.com/never"}, headers=auth
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND


def test_lookup_does_not_create_anything(client, auth):
    """The whole point: asking must not be answering with a side effect."""
    client.get("/api/v1/bookmarks/lookup", params={"url": "https://example.com/new"}, headers=auth)
    client.get("/api/v1/bookmarks/lookup", params={"url": "https://example.com/new"}, headers=auth)
    assert client.get("/api/v1/bookmarks", headers=auth).json()["total"] == 0


def test_lookup_is_not_shadowed_by_the_id_route(client, auth):
    """Regression guard: declared after /{bookmark_id}, this would 422 on "lookup"."""
    post(client, auth, url="https://example.com/a")
    r =client.get(
        "/api/v1/bookmarks/lookup", params={"url": "https://example.com/a"}, headers=auth
    )
    assert r.status_code != status.HTTP_422_UNPROCESSABLE_CONTENT


def test_lookup_rejects_an_invalid_url(client, auth):
    r = client.get("/api/v1/bookmarks/lookup", params={"url": "   "}, headers=auth)
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_lookup_requires_a_token(client, auth):
    """It reveals whether *you* saved a page, so it needs to know who you are."""
    post(client, auth, url="https://example.com/a")
    assert client.get(
        "/api/v1/bookmarks/lookup", params={"url": "https://example.com/a"}
    ).status_code == status.HTTP_401_UNAUTHORIZED
