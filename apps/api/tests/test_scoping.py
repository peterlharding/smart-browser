"""One person's library must be invisible to another.

`bookmark` rows are shared between users -- that is the point of ADR 0001 -- so every read
has to join through `user_bookmark` filtered by `user_id`. A query that reaches `bookmark`
directly leaks the existence of someone else's saves. That is the one invariant in the
schema worth its own test file rather than a code review.
"""

from fastapi import status


def post(client, auth, **payload):
    return client.post("/api/v2/bookmarks", json=payload, headers=auth)


def test_a_list_shows_only_your_own_saves(client, auth, other_client, other_auth):
    post(client, auth, url="https://example.com/mine", tags=["mine"])
    post(other_client, other_auth, url="https://example.com/theirs", tags=["theirs"])

    mine = client.get("/api/v2/bookmarks", headers=auth).json()
    assert mine["total"] == 1
    assert mine["items"][0]["url"] == "https://example.com/mine"


def test_you_cannot_fetch_another_users_save_by_id(client, auth, other_client, other_auth):
    theirs = post(other_client, other_auth, url="https://example.com/theirs").json()
    assert (
        client.get(f"/api/v2/bookmarks/{theirs['id']}", headers=auth).status_code
        == status.HTTP_404_NOT_FOUND
    )


def test_you_cannot_modify_another_users_save(client, auth, other_client, other_auth):
    theirs = post(other_client, other_auth, url="https://example.com/theirs").json()

    assert client.patch(
        f"/api/v2/bookmarks/{theirs['id']}", json={"title": "hijacked"}, headers=auth
    ).status_code == status.HTTP_404_NOT_FOUND

    assert client.delete(
        f"/api/v2/bookmarks/{theirs['id']}", headers=auth
    ).status_code == status.HTTP_404_NOT_FOUND

    assert client.post(
        f"/api/v2/bookmarks/{theirs['id']}/tags", json={"tags": ["x"]}, headers=auth
    ).status_code == status.HTTP_404_NOT_FOUND


def test_lookup_does_not_reveal_that_someone_else_saved_a_page(
    client, auth, other_client, other_auth
):
    """A shared `bookmark` row exists; that must not make the page appear in your library."""
    post(other_client, other_auth, url="https://example.com/theirs")

    r =client.get(
        "/api/v2/bookmarks/lookup", params={"url": "https://example.com/theirs"}, headers=auth
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND


def test_tag_counts_are_yours_not_everyones(client, auth, other_client, other_auth):
    post(client, auth, url="https://example.com/mine", tags=["python"])
    for i in range(3):
        post(other_client, other_auth, url=f"https://example.com/theirs{i}", tags=["python"])

    counts = {t["name"]: t["count"] for t in client.get("/api/v2/tags", headers=auth).json()}
    assert counts == {"python": 1}


def test_deleting_your_save_leaves_the_other_users_alone(
    client, auth, other_client, other_auth
):
    mine = post(client, auth, url="https://example.com/shared").json()
    post(other_client, other_auth, url="https://example.com/shared")

    client.delete(f"/api/v2/bookmarks/{mine['id']}", headers=auth)

    assert client.get("/api/v2/bookmarks", headers=auth).json()["total"] == 0
    assert other_client.get("/api/v2/bookmarks", headers=other_auth).json()["total"] == 1
