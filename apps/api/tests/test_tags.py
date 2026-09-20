"""Tag listing.

Counts matter more than names: the audit found 10 tags never used and one blank tag on 43
bookmarks, so the sidebar must rank by usage rather than list 567 entries alphabetically.
"""


def post(client, auth, **payload):
    return client.post("/api/v2/bookmarks", json=payload, headers=auth)


def test_tags_are_returned_with_usage_counts(client, auth):
    post(client, auth, url="https://example.com/1", tags=["python", "fastapi"])
    post(client, auth, url="https://example.com/2", tags=["python"])

    counts = {t["name"]: t["count"] for t in client.get("/api/v2/tags", headers=auth).json()}
    assert counts == {"python": 2, "fastapi": 1}


def test_tags_are_ordered_by_usage(client, auth):
    post(client, auth, url="https://example.com/1", tags=["rare"])
    post(client, auth, url="https://example.com/2", tags=["common"])
    post(client, auth, url="https://example.com/3", tags=["common"])

    names = [t["name"] for t in client.get("/api/v2/tags", headers=auth).json()]
    assert names[0] == "common"


def test_min_count_hides_the_long_tail(client, auth):
    post(client, auth, url="https://example.com/1", tags=["rare"])
    post(client, auth, url="https://example.com/2", tags=["common"])
    post(client, auth, url="https://example.com/3", tags=["common"])

    names = [t["name"] for t in client.get(
        "/api/v2/tags", params={"min_count": 2}, headers=auth
    ).json()]
    assert names == ["common"]


def test_substring_search(client, auth):
    post(client, auth, url="https://example.com/1", tags=["python", "javascript"])
    names = [t["name"] for t in client.get(
        "/api/v2/tags", params={"q": "script"}, headers=auth
    ).json()]
    assert names == ["javascript"]


def test_tags_are_stored_lowercased(client, auth):
    post(client, auth, url="https://example.com/1", tags=["Python", "FASTAPI"])
    names = sorted(t["name"] for t in client.get("/api/v2/tags", headers=auth).json())
    assert names == ["fastapi", "python"]
