import pytest

from bookmarks_api.urlnorm import normalise, site_of, url_hash


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # scheme and host casing
        ("HTTPS://Example.COM/Path", "https://example.com/Path"),
        # default ports go, non-default stay
        ("https://example.com:443/x", "https://example.com/x"),
        ("http://example.com:80/x", "http://example.com/x"),
        ("https://example.com:8443/x", "https://example.com:8443/x"),
        # bare host gets a scheme and a root path
        ("example.com", "https://example.com/"),
        # trailing slash collapses below root, root keeps its slash
        ("https://example.com/docs/", "https://example.com/docs"),
        ("https://example.com/", "https://example.com/"),
        # tracking params removed, real params kept and sorted
        ("https://example.com/?utm_source=x&id=7", "https://example.com/?id=7"),
        ("https://example.com/?fbclid=abc", "https://example.com/"),
        ("https://example.com/?b=2&a=1", "https://example.com/?a=1&b=2"),
        # fragments dropped, hashbang preserved where it routes
        ("https://example.com/p#section", "https://example.com/p"),
        ("https://twitter.com/x#!/status/1", "https://twitter.com/x#!/status/1"),
        # trailing dot on the host is not part of identity
        ("https://example.com./x", "https://example.com/x"),
        # credentials are dropped rather than stored
        ("https://user:pw@example.com/x", "https://example.com/x"),
    ],
)
def test_normalise(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "HTTPS://Example.COM:443/docs/?utm_source=nl&b=2&a=1#frag",
        "example.com",
        "https://example.com/?a=1",
    ],
)
def test_normalise_is_idempotent(raw: str) -> None:
    once = normalise(raw)
    assert normalise(once) == once


def test_normalise_rejects_empty() -> None:
    with pytest.raises(ValueError):
        normalise("   ")


def test_equivalent_urls_share_a_hash() -> None:
    a = "https://example.com/docs/?utm_campaign=x&id=1"
    b = "HTTPS://Example.com:443/docs?id=1#top"
    assert url_hash(a) == url_hash(b)


def test_distinct_urls_do_not_share_a_hash() -> None:
    assert url_hash("https://example.com/a") != url_hash("https://example.com/b")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://docs.python.org/3/library/", "python.org"),
        ("https://example.co.uk/x", "example.co.uk"),
        ("https://stackoverflow.com/q/1", "stackoverflow.com"),
    ],
)
def test_site_of(url: str, expected: str) -> None:
    assert site_of(url) == expected


def test_paths_that_differ_are_not_merged() -> None:
    """Guard against over-normalisation.

    A normaliser that changes which page you land on is worse than a duplicate row,
    so these must stay distinct.
    """
    assert normalise("https://example.com/a") != normalise("https://example.com/b")
    assert normalise("https://example.com/?id=1") != normalise("https://example.com/?id=2")
    assert normalise("http://example.com/x") != normalise("https://example.com/x")
