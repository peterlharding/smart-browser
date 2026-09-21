"""Auth behaviour.

The predecessor's write endpoint accepted anything, from anyone, for ten years. These
tests exist so that cannot happen here quietly.
"""

from fastapi import status

PAYLOAD = {"url": "https://example.com/a"}


def test_write_without_token_is_rejected(client):
    r = client.post("/api/v1/bookmarks", json=PAYLOAD)
    assert r.status_code == status.HTTP_401_UNAUTHORIZED
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_write_with_wrong_token_is_rejected(client):
    r = client.post(
        "/api/v1/bookmarks", json=PAYLOAD, headers={"Authorization": "Bearer nope"}
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_write_with_non_bearer_scheme_is_rejected(client):
    r = client.post(
        "/api/v1/bookmarks", json=PAYLOAD, headers={"Authorization": "Basic abc123"}
    )
    assert r.status_code == status.HTTP_401_UNAUTHORIZED


def test_a_colon_after_bearer_is_rejected(client, auth):
    """`Bearer: <token>` is not the header, however reasonable it looks.

    It is what you write when the docs page gives you a bare header field instead of an
    Authorize dialog -- which is why auth is declared as a security scheme, and why this
    asserts the rejection is a clean 401 rather than something confusing.
    """
    token = auth["Authorization"].split(" ", 1)[1]
    r = client.post(
        "/api/v1/bookmarks", json=PAYLOAD, headers={"Authorization": f"Bearer: {token}"}
    )
    assert r.status_code == status.HTTP_401_UNAUTHORIZED


def test_the_docs_page_offers_an_authorize_dialog(client):
    """Every protected operation must carry the declared scheme.

    Swagger UI draws the padlock and the Authorize dialog from `security` in the schema,
    and FastAPI only emits that for a dependency deriving from SecurityBase. Read the
    Authorization header by hand instead and the docs page silently loses its auth UI --
    no test fails, the API just becomes unusable from the one place people try it first.
    """
    schema = client.app.openapi()
    assert schema["components"]["securitySchemes"], "no security scheme declared"

    unprotected = [
        f"{method.upper()} {path}"
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if not operation.get("security") and not path.endswith("/health")
    ]
    assert not unprotected, f"operations with no declared auth: {unprotected}"


def test_unconfigured_deployment_refuses_writes_rather_than_allowing_them(anon_client, auth):
    """With no API_TOKENS set, writes must fail closed.

    Failing *open* on a missing config is how write endpoints quietly end up exposed, so
    this asserts 503 specifically rather than merely 'not 200'.
    """
    r = anon_client.post("/api/v1/bookmarks", json=PAYLOAD, headers=auth)
    assert r.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_reads_require_a_token_too(client):
    """Bookmarks belong to a user, so there is no coherent anonymous read.

    "List the bookmarks" has no answer without knowing whose. A public read would either
    leak every library or silently return one arbitrary person's.
    """
    assert client.get("/api/v1/bookmarks").status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get("/api/v1/tags").status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get(
        "/api/v1/bookmarks/lookup", params={"url": "https://example.com/a"}
    ).status_code == status.HTTP_401_UNAUTHORIZED


def test_health_needs_no_token(client):
    """Liveness has to be checkable by things that hold no credential."""
    assert client.get("/api/v1/health").status_code == status.HTTP_200_OK


def test_two_tokens_are_two_users(client, auth, other_auth):
    client.post("/api/v1/bookmarks", json={"url": "https://example.com/a"}, headers=auth)
    assert client.get("/api/v1/bookmarks", headers=auth).json()["total"] == 1
    assert client.get("/api/v1/bookmarks", headers=other_auth).json()["total"] == 0


def test_write_with_valid_token_succeeds(client, auth):
    r = client.post("/api/v1/bookmarks", json=PAYLOAD, headers=auth)
    assert r.status_code == status.HTTP_201_CREATED
