"""Auth behaviour.

The v1 `/xyzzy` endpoint writes to the database with no credentials at all. These tests
exist so that regression cannot happen quietly.
"""

from fastapi import status

PAYLOAD = {"url": "https://example.com/a"}


def test_write_without_token_is_rejected(client):
    r = client.post("/api/v2/bookmarks", json=PAYLOAD)
    assert r.status_code == status.HTTP_401_UNAUTHORIZED
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_write_with_wrong_token_is_rejected(client):
    r = client.post(
        "/api/v2/bookmarks", json=PAYLOAD, headers={"Authorization": "Bearer nope"}
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_write_with_non_bearer_scheme_is_rejected(client):
    r = client.post(
        "/api/v2/bookmarks", json=PAYLOAD, headers={"Authorization": "Basic abc123"}
    )
    assert r.status_code == status.HTTP_401_UNAUTHORIZED


def test_unconfigured_deployment_refuses_writes_rather_than_allowing_them(anon_client, auth):
    """With no API_TOKENS set, writes must fail closed.

    Failing *open* here is precisely how /xyzzy ended up world-writable, so this asserts
    503 rather than merely 'not 200'.
    """
    r = anon_client.post("/api/v2/bookmarks", json=PAYLOAD, headers=auth)
    assert r.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_reads_do_not_require_a_token(client):
    assert client.get("/api/v2/bookmarks").status_code == status.HTTP_200_OK
    assert client.get("/api/v2/tags").status_code == status.HTTP_200_OK


def test_write_with_valid_token_succeeds(client, auth):
    r = client.post("/api/v2/bookmarks", json=PAYLOAD, headers=auth)
    assert r.status_code == status.HTTP_201_CREATED
