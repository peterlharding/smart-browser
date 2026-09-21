"""URL normalisation (ADR 0011).

The output is both the identity and the stored link, so the tests come in two kinds: the
spellings that must merge, and -- the more important kind -- the URLs that must come out
exactly as saved, because every rule that touched them would rewrite someone's link.
"""

import pytest

from bookmarks_api.urlnorm import normalise, site_of, url_hash


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # scheme and host casing, and the trailing dot on a host
        ("HTTPS://Example.COM/Path", "https://example.com/Path"),
        ("https://example.com./x", "https://example.com/x"),
        # default ports go, non-default stay
        ("https://example.com:443/x", "https://example.com/x"),
        ("http://example.com:80/x", "http://example.com/x"),
        ("https://example.com:8443/x", "https://example.com:8443/x"),
        # bare host gets a scheme and a root path; bare host and port too
        ("example.com", "https://example.com/"),
        ("localhost:8080/x", "https://localhost:8080/x"),
        # an internationalised host becomes punycode, which is what Chrome reports
        ("https://bücher.de/x", "https://xn--bcher-kva.de/x"),
        # escapes: hex uppercased, unreserved characters decoded, nothing else
        ("https://example.com/a%7eb%2f", "https://example.com/a~b%2F"),
        ("https://example.com/?q=%7e", "https://example.com/?q=~"),
        # tracking params removed, case-insensitively; the ? goes when nothing is left
        ("https://example.com/?utm_source=x&id=7", "https://example.com/?id=7"),
        ("https://example.com/?UTM_Source=x&id=7&fbclid=z", "https://example.com/?id=7"),
        ("https://example.com/?fbclid=abc", "https://example.com/"),
        # a fragment is dropped unless it is a route, on any host
        ("https://example.com/p#section", "https://example.com/p"),
        ("https://example.com/p#:~:text=hello", "https://example.com/p"),
        ("https://x.com/i#!/status/1", "https://x.com/i#!/status/1"),
        ("https://app.example.com/#/settings", "https://app.example.com/#/settings"),
        # credentials are dropped rather than stored
        ("https://user:pw@example.com/x", "https://example.com/x"),
    ],
)
def test_normalise(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


@pytest.mark.parametrize(
    "url",
    [
        # A trailing slash is a different URL, and relative links resolve differently.
        "https://example.com/docs/",
        # Repeated keys are an ordered list to most frameworks; order of distinct keys
        # matters to some. Nothing is sorted.
        "https://example.com/?a=2&a=1",
        "https://example.com/?b=2&a=1",
        # A bare key and an empty value differ to some servers.
        "https://example.com/wiki?edit",
        # Encodings stay as written: %20 is not re-spelt +, / is not escaped.
        "https://example.com/?q=a%20b",
        "https://example.com/?q=a+b",
        "https://example.com/?path=a/b",
        # A malformed escape is part of the URL as saved, not something to repair into
        # U+FFFD.
        "https://example.com/?x=%E0%A4",
        "https://example.com/100%",
        # Generic names some site uses to select content are not trackers.
        "https://ads.example.com/report?campaign_id=123",
        "https://example.com/?trk=home&ref_src=nav&icid=1",
        # A hash route names the page.
        "https://app.example.com/#/settings/profile",
        # An empty query is kept, as RFC 3986 section 6.2.3 asks.
        "https://example.com/?",
        # IPv6 keeps the brackets a URL needs.
        "http://[::1]:8080/x",
    ],
)
def test_urls_that_must_come_out_exactly_as_saved(url: str) -> None:
    assert normalise(url) == url


@pytest.mark.parametrize(
    "raw",
    [
        "chrome://extensions",
        "chrome-extension://abcdefghijklmnop/popup.html",
        "about:blank",
        "mailto:someone@example.com",
        "javascript:alert(1)",
        "file:///Users/someone/notes.html",
        "ftp://ftp.example.com/pub",
    ],
)
def test_only_http_and_https_are_accepted(raw: str) -> None:
    """The crawler can fetch nothing else, and these are not pages to it."""
    with pytest.raises(ValueError, match="only http and https URLs can be saved"):
        normalise(raw)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("   ", "empty url"),
        ("http://", "no host"),
        ("https://example.com:99999/", "invalid port"),
    ],
)
def test_invalid_urls_say_what_is_wrong(raw: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalise(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "HTTPS://User:pw@Example.COM.:443/a%7eb%2f?utm_source=nl&b=2&a=1#frag",
        "https://bücher.de/x?q=%7e#/route",
        "http://[::1]:8080/x?edit",
        "example.com",
        "https://example.com/?",
        "https://example.com/?x=%E0%A4",
    ],
)
def test_normalise_is_idempotent(raw: str) -> None:
    once = normalise(raw)
    assert normalise(once) == once


def test_equivalent_spellings_share_a_hash() -> None:
    a = "https://example.com/docs/?utm_campaign=x&id=1"
    b = "HTTPS://Example.com:443/docs/?id=1#top"
    assert url_hash(a) == url_hash(b)


def test_punycode_and_unicode_hosts_share_a_hash() -> None:
    assert url_hash("https://bücher.de/") == url_hash("https://xn--bcher-kva.de/")


def test_distinct_urls_do_not_share_a_hash() -> None:
    assert url_hash("https://example.com/a") != url_hash("https://example.com/b")


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://example.com/a", "https://example.com/b"),
        ("https://example.com/?id=1", "https://example.com/?id=2"),
        ("http://example.com/x", "https://example.com/x"),
        ("https://www.example.com/x", "https://example.com/x"),
        ("https://example.com/docs", "https://example.com/docs/"),
        ("https://example.com/?a=1&b=2", "https://example.com/?b=2&a=1"),
        ("https://app.example.com/#/a", "https://app.example.com/#/b"),
    ],
)
def test_spellings_that_usually_mean_one_page_are_not_merged(a: str, b: str) -> None:
    """Guard against over-normalisation.

    "Usually the same page" is exactly the case ADR 0011 declines: a duplicate can be
    merged later, and a wrong merge loses a page for good.
    """
    assert normalise(a) != normalise(b)


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
