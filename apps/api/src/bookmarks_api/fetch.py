"""Fetching one saved page, within limits (ADR 0012).

The only module in the crawler that touches the network. The worker takes a `Fetcher` as a
parameter, so everything else -- claiming, backoff, the outcome of each status -- is tested
with a fake one and no network at all.

A fetch either returns a `FetchResult`, whatever the status code, or raises `Transient`
(worth retrying: a timeout, a refused connection) or `Permanent` (not worth retrying: a
private address, a body over the cap). What a status code *means* is the worker's call.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from . import __version__

USER_AGENT = f"SmartBrowser/{__version__} (personal bookmark indexer)"
HTML_TYPES = ("text/html", "application/xhtml+xml")
REDIRECTS = frozenset({301, 302, 303, 307, 308})

MAX_REDIRECTS = 5
MAX_BYTES = 5 * 1024 * 1024
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 10.0
DEADLINE = 30.0
HOST_INTERVAL = 1.0


class FetchError(Exception):
    """A fetch that produced no response worth classifying by status."""


class Transient(FetchError):
    """Worth trying again later: the far end may answer next time."""


class Permanent(FetchError):
    """Not worth trying again: the same request will fail the same way."""


@dataclass(frozen=True)
class FetchResult:
    url: str  # after redirects
    status: int
    content_type: str  # media type only, lowercased: "text/html"
    body: bytes  # empty unless the status is 2xx and the type is HTML
    retry_after: float | None = None  # seconds, from a Retry-After header

    @property
    def is_html(self) -> bool:
        return self.content_type in HTML_TYPES


class Fetcher(Protocol):
    def fetch(self, url: str) -> FetchResult: ...


Resolver = Callable[[str, int], list[str]]


def resolve(host: str, port: int) -> list[str]:
    """Every address *host* resolves to. A resolution failure is transient: DNS recovers."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise Transient(f"DNS: {host}: {exc}") from exc
    return [str(info[4][0]) for info in infos]


def is_private(address: str) -> bool:
    """True for anything a public crawler has no business connecting to.

    Loopback, link-local (where cloud metadata services live), RFC 1918, unique-local
    IPv6, and every other range `ipaddress` does not call global -- including an IPv4
    address smuggled inside IPv6.
    """
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


def retry_after_seconds(value: str | None, now: datetime | None = None) -> float | None:
    """A Retry-After header as seconds from now: either form, or None if unreadable."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


class HttpxFetcher:
    """The real fetcher: `httpx`, TLS verified, every limit in ADR 0012.

    Redirects are followed by hand rather than by httpx, so that every hop is checked
    against the private-address rule and the scheme rule, not only the first. The limits
    and the clock are parameters so the tests can make them small and fast.
    """

    def __init__(
        self,
        *,
        allow_private: bool = False,
        resolver: Resolver = resolve,
        max_redirects: int = MAX_REDIRECTS,
        max_bytes: int = MAX_BYTES,
        connect_timeout: float = CONNECT_TIMEOUT,
        read_timeout: float = READ_TIMEOUT,
        deadline: float = DEADLINE,
        host_interval: float = HOST_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.allow_private = allow_private
        self.resolver = resolver
        self.max_redirects = max_redirects
        self.max_bytes = max_bytes
        self.deadline = deadline
        self.host_interval = host_interval
        self.clock = clock
        self.sleep = sleep
        self._last_request: dict[str, float] = {}
        self._client = httpx.Client(
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
            follow_redirects=False,
            verify=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            },
        )

    def close(self) -> None:
        self._client.close()

    def fetch(self, url: str) -> FetchResult:
        started = self.clock()
        for _ in range(self.max_redirects + 1):
            if self.clock() - started > self.deadline:
                raise Transient(f"timeout: over {self.deadline:g}s in total")
            self._check_target(url)
            self._wait_for_host(url)
            try:
                result = self._request(url, started)
            except httpx.TimeoutException as exc:
                raise Transient(f"timeout: {type(exc).__name__}: {exc}") from exc
            except httpx.TransportError as exc:
                raise Transient(f"{type(exc).__name__}: {exc}") from exc
            if isinstance(result, FetchResult):
                return result
            url = result
        raise Permanent(f"more than {self.max_redirects} redirects")

    def _check_target(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise Permanent(f"redirect to unsupported scheme {parts.scheme!r}")
        host = parts.hostname or ""
        if self.allow_private:
            return
        port = parts.port or (443 if parts.scheme == "https" else 80)
        private = [a for a in self.resolver(host, port) if is_private(a)]
        if private:
            raise Permanent(f"private address: {host} resolves to {', '.join(private)}")

    def _wait_for_host(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        last = self._last_request.get(host)
        if last is not None:
            wait = self.host_interval - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_request[host] = self.clock()

    def _request(self, url: str, started: float) -> FetchResult | str:
        """A result, or the URL a redirect points to."""
        with self._client.stream("GET", url) as response:
            if response.status_code in REDIRECTS and "location" in response.headers:
                return urljoin(str(response.url), response.headers["location"])

            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            result = FetchResult(
                url=str(response.url),
                status=response.status_code,
                content_type=content_type.strip().lower(),
                body=b"",
                retry_after=retry_after_seconds(response.headers.get("retry-after")),
            )
            # Only an HTML success is worth reading: a 404 page or a PDF is not extracted,
            # so downloading it would be 5 MB spent on nothing.
            if not (200 <= result.status < 300 and result.is_html):
                return result

            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > self.max_bytes:
                raise Permanent(f"body over {self.max_bytes} bytes (declared {declared})")

            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self.max_bytes:
                    raise Permanent(f"body over {self.max_bytes} bytes")
                if self.clock() - started > self.deadline:
                    raise Transient(f"timeout: over {self.deadline:g}s in total")
                chunks.append(chunk)
            return FetchResult(
                url=result.url,
                status=result.status,
                content_type=result.content_type,
                body=b"".join(chunks),
                retry_after=result.retry_after,
            )
