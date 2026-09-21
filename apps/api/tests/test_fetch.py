"""The real fetcher, against a real HTTP server on this machine (ADR 0012).

No internet: the server is a thread on 127.0.0.1. That address is private, so the tests
that are not about the private-address rule allow it; the ones that are, refuse it, and
check that the server never saw a request.
"""

from __future__ import annotations

import socketserver
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bookmarks_api.fetch import (
    USER_AGENT,
    HttpxFetcher,
    Permanent,
    Transient,
    is_private,
    retry_after_seconds,
)

PAGE = b"<html><head><title>Hello</title></head><body><p>Hi</p></body></html>"


class Handler(BaseHTTPRequestHandler):
    seen: list[tuple[str, str]] = []

    def log_message(self, *args) -> None:  # keep test output clean
        pass

    def send(self, status: int, body: bytes = b"", ctype: str = "text/html", **headers) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - the name http.server calls
        Handler.seen.append((self.path, self.headers.get("User-Agent", "")))
        path = self.path
        if path == "/page":
            self.send(200, PAGE, "text/html; charset=utf-8")
        elif path == "/pdf":
            self.send(200, b"%PDF-" + b"x" * 1000, "application/pdf")
        elif path == "/big":
            self.send(200, b"x" * 5000)
        elif path == "/big-undeclared":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"x" * 5000)
        elif path.startswith("/hop/"):
            left = int(path.rsplit("/", 1)[1])
            self.send(302, Location="/page" if left == 0 else f"/hop/{left - 1}")
        elif path == "/to-localhost":
            port = self.server.server_address[1]
            self.send(302, Location=f"http://localhost:{port}/page")
        elif path == "/to-ftp":
            self.send(302, Location="ftp://example.com/file")
        elif path == "/missing":
            self.send(404, b"<html>gone</html>")
        elif path == "/busy":
            self.send(429, b"", Retry_After="120")
        elif path == "/slow":
            time.sleep(1.0)
            self.send(200, PAGE)
        else:
            self.send(500)


class Server(ThreadingHTTPServer):
    daemon_threads = True  # a handler still sleeping for /slow must not hold up the exit

    def server_bind(self) -> None:
        # HTTPServer.server_bind looks up its own name with socket.getfqdn(), a reverse
        # DNS query that took 35 seconds here. The name is never used.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def fetcher() -> Iterator[HttpxFetcher]:
    Handler.seen.clear()
    f = HttpxFetcher(allow_private=True, host_interval=0, max_bytes=4096, read_timeout=0.5)
    try:
        yield f
    finally:
        f.close()


def test_an_html_page_is_read(server, fetcher):
    result = fetcher.fetch(f"{server}/page")
    assert (result.status, result.content_type, result.body) == (200, "text/html", PAGE)


def test_it_says_who_it_is(server, fetcher):
    fetcher.fetch(f"{server}/page")
    assert Handler.seen[-1][1] == USER_AGENT


def test_a_non_html_body_is_not_downloaded(server, fetcher):
    result = fetcher.fetch(f"{server}/pdf")
    assert (result.status, result.content_type, result.body) == (200, "application/pdf", b"")


def test_an_error_status_is_returned_not_raised(server, fetcher):
    assert fetcher.fetch(f"{server}/missing").status == 404


def test_retry_after_is_read(server, fetcher):
    result = fetcher.fetch(f"{server}/busy")
    assert (result.status, result.retry_after) == (429, 120.0)


@pytest.mark.parametrize("path", ["/big", "/big-undeclared"])
def test_a_body_over_the_cap_is_abandoned(server, fetcher, path):
    with pytest.raises(Permanent, match="body over 4096 bytes"):
        fetcher.fetch(f"{server}{path}")


def test_redirects_are_followed_to_the_end(server, fetcher):
    result = fetcher.fetch(f"{server}/hop/4")  # /hop/4 ... /hop/0, /page: five redirects
    assert result.status == 200
    assert result.url == f"{server}/page"


def test_more_than_five_redirects_is_permanent(server, fetcher):
    with pytest.raises(Permanent, match="more than 5 redirects"):
        fetcher.fetch(f"{server}/hop/5")


def test_a_redirect_off_the_web_is_refused(server, fetcher):
    with pytest.raises(Permanent, match="unsupported scheme 'ftp'"):
        fetcher.fetch(f"{server}/to-ftp")


def test_a_slow_server_is_a_transient_timeout(server, fetcher):
    with pytest.raises(Transient, match="timeout"):
        fetcher.fetch(f"{server}/slow")


def test_nothing_listening_is_transient():
    f = HttpxFetcher(allow_private=True)
    try:
        with pytest.raises(Transient, match="ConnectError"):
            f.fetch("http://127.0.0.1:9/")
    finally:
        f.close()


# --- private addresses --------------------------------------------------------------


def test_a_private_address_is_refused_before_any_request(server):
    Handler.seen.clear()
    f = HttpxFetcher(allow_private=False)
    try:
        with pytest.raises(Permanent, match="private address: 127.0.0.1"):
            f.fetch(f"{server}/page")
    finally:
        f.close()
    assert Handler.seen == []


def test_a_redirect_to_a_private_address_is_refused(server):
    """Checked at every hop, not only the first.

    The resolver claims 127.0.0.1 is a public address, so the first hop is allowed and
    connects to the test server, which redirects to `localhost`, which resolves private.
    """

    def resolver(host: str, port: int) -> list[str]:
        return ["93.184.216.34"] if host == "127.0.0.1" else ["127.0.0.1"]

    f = HttpxFetcher(allow_private=False, resolver=resolver, host_interval=0)
    try:
        with pytest.raises(Permanent, match="private address: localhost"):
            f.fetch(f"{server}/to-localhost")
    finally:
        f.close()


def test_a_public_name_that_resolves_private_is_refused():
    f = HttpxFetcher(allow_private=False, resolver=lambda host, port: ["10.0.0.7"])
    try:
        with pytest.raises(Permanent, match="private address: intranet.example"):
            f.fetch("https://intranet.example/")
    finally:
        f.close()


@pytest.mark.parametrize(
    ("address", "private"),
    [
        ("127.0.0.1", True),
        ("10.1.2.3", True),
        ("172.16.0.1", True),
        ("192.168.1.1", True),
        ("169.254.169.254", True),  # cloud metadata
        ("100.64.0.1", True),  # carrier-grade NAT
        ("0.0.0.0", True),
        ("::1", True),
        ("fc00::1", True),
        ("fe80::1%en0", True),
        ("::ffff:127.0.0.1", True),  # IPv4 inside IPv6
        ("224.0.0.1", True),
        ("93.184.216.34", False),
        ("2606:2800:220:1:248:1893:25c8:1946", False),
    ],
)
def test_what_counts_as_private(address, private):
    assert is_private(address) is private


# --- politeness and headers ---------------------------------------------------------


def test_a_second_request_to_one_host_waits_out_the_interval(server):
    now = [100.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    f = HttpxFetcher(allow_private=True, host_interval=1.0, clock=lambda: now[0], sleep=sleep)
    try:
        f.fetch(f"{server}/page")
        now[0] += 0.25
        f.fetch(f"{server}/page")
    finally:
        f.close()
    assert waits == [pytest.approx(0.75)]


def test_retry_after_in_either_form():
    from datetime import UTC, datetime

    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    assert retry_after_seconds("30") == 30.0
    assert retry_after_seconds("Mon, 21 Sep 2026 12:02:00 GMT", now) == 120.0
    assert retry_after_seconds("soon") is None
    assert retry_after_seconds(None) is None
