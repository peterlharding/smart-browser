"""Cross-origin access for browser clients.

Every client of this API is a browser: the extension now, the Electron shell in M5.
A missing CORS header does not look like a server problem -- the request arrives, the
handler runs, the log records a 200, and the browser discards the response and hands the
client an opaque network error. These tests pin the headers so that cannot regress
quietly into an afternoon spent debugging the wrong layer.
"""

from fastapi import status

EXTENSION = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


def test_preflight_from_an_extension_is_allowed(client):
    r = client.options(
        "/api/v2/bookmarks",
        headers={
            "Origin": EXTENSION,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert r.status_code == status.HTTP_200_OK
    assert r.headers["access-control-allow-origin"] == EXTENSION
    # The extension sends both on every write; a preflight that omits either fails the
    # actual request while the preflight itself looks fine.
    allowed = r.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed
    assert "content-type" in allowed


def test_an_extension_may_read_the_response(client, auth):
    """The preflight passing is not the same as the response being readable."""
    r = client.get("/api/v2/tags", headers={**auth, "Origin": EXTENSION})
    assert r.status_code == status.HTTP_200_OK
    assert r.headers["access-control-allow-origin"] == EXTENSION


def test_the_open_web_is_not_allowed_in(client, auth):
    """An origin rule matching extensions must not match a web page.

    A localhost API that any page you visit can read is a bookmark library exfiltrated by
    a drive-by fetch -- the token would not protect it, because the browser attaches the
    request the page asks for.
    """
    r = client.get(
        "/api/v2/tags", headers={**auth, "Origin": "https://not-your-extension.example"}
    )
    assert "access-control-allow-origin" not in r.headers


def test_credentials_are_not_allowed(client, auth):
    """Auth is a bearer token, so nothing should ever ride on a cookie.

    `allow_credentials` together with a permissive origin rule is how a CORS policy turns
    into a vulnerability; this asserts the combination never appears.
    """
    r = client.get("/api/v2/tags", headers={**auth, "Origin": EXTENSION})
    assert "access-control-allow-credentials" not in r.headers
