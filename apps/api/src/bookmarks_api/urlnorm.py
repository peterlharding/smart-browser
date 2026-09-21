"""URL normalisation.

The output is two things at once: the identity (`url_hash` is its SHA-256, and
`UNIQUE (url_hash)` is the whole no-duplicates guarantee) and the stored URL -- the link
you open, the URL the crawler fetches, and the one every later saver of the page inherits.

So this merges only spellings of the same resource, and nothing that merely *usually* is
(ADR 0011). A duplicate row is untidy and can be merged later. A wrong merge rewrites your
link into a different one and files a second person's different page under the first
person's row, and it cannot be undone, because the original spelling was never stored.

Changing these rules changes the key of existing rows: run `make rehash-urls` after.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import unquote_plus, urlsplit

import tldextract

# Use the bundled public-suffix snapshot: no network call at import time, and no
# surprise failure when the process starts somewhere without egress.
_extract = tldextract.TLDExtract(suffix_list_urls=())

# The crawler fetches nothing else, `chrome://` and `about:` are not pages, and a
# `file://` path means nothing on another machine.
SCHEMES = frozenset({"http", "https"})
DEFAULT_PORTS = {"http": 80, "https": 443}

# Known click and campaign trackers whose value never selects what a page shows. A
# generic name that some site uses to select content (`campaign_id`, `ref`, `trk`) does
# not qualify, however often it is a tracker elsewhere. Lowercase: keys are matched
# case-insensitively.
TRACKING_PREFIXES = ("utm_", "pk_", "mc_", "hsa_", "vero_", "_hs")
TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "twclid",
    "igshid", "yclid", "mkt_tok", "s_kwcid",
})

# RFC 3986 section 2.3. Escapes of these may be decoded without changing the resource;
# escapes of anything else may not.
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")

# `localhost:8080/x` is a host and port with the scheme left off; `about:blank` and
# `mailto:x@y` are schemes. A scheme-less input counts as a host when what follows the
# first colon is a port.
_SCHEME_PREFIX = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):(.*)$", re.DOTALL)
_PORT_THEN_REST = re.compile(r"^\d*(?:[/?#]|$)")


def _is_tracking(key: str) -> bool:
    lowered = unquote_plus(key).lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PREFIXES)


def _normalise_escapes(component: str) -> str:
    """Uppercase every escape's hex digits and decode escapes of unreserved characters.

    RFC 3986 section 6.2.2. Nothing else is decoded, and a `%` not followed by two hex
    digits is left exactly as it was: a malformed escape is part of the URL as saved.
    """

    def fix(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else f"%{match.group(1).upper()}"

    return _ESCAPE.sub(fix, component)


def _host(raw: str) -> str:
    host = raw.lower().rstrip(".")
    if not host:
        raise ValueError("no host in url")
    if ":" in host:
        return f"[{host}]"  # IPv6: urlsplit strips the brackets the URL needs
    if not host.isascii():
        # Punycode is what Chrome reports for a tab, so a typed `bücher.de` and a saved
        # `xn--bcher-kva.de` must be one host.
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError(f"invalid host: {raw!r}") from exc
    return host


def normalise(url: str) -> str:
    """Return the canonical spelling of *url*.

    Idempotent: ``normalise(normalise(u)) == normalise(u)``. Raises ValueError for
    anything that is not an http or https URL with a host.
    """
    url = url.strip()
    if not url:
        raise ValueError("empty url")

    if "://" not in url:
        scheme_like = _SCHEME_PREFIX.match(url)
        if scheme_like and not _PORT_THEN_REST.match(scheme_like.group(2)):
            raise ValueError(
                f"unsupported scheme {scheme_like.group(1).lower()!r}: "
                "only http and https URLs can be saved"
            )
        # Bare "example.com/x" -- assume https rather than rejecting it.
        url = "https://" + url

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in SCHEMES:
        raise ValueError(f"unsupported scheme {scheme!r}: only http and https URLs can be saved")

    # Userinfo is credentials, not identity, and does not belong in the database. The one
    # deliberate exception to "never change the resource" -- dropped by using only the
    # host and port below.
    host = _host(parts.hostname or "")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"invalid port in url: {url!r}") from exc
    netloc = host if port is None or DEFAULT_PORTS[scheme] == port else f"{host}:{port}"

    # Empty and "/" are the same path for http (RFC 3986 section 6.2.3). A trailing slash
    # anywhere else is kept: `/docs` and `/docs/` are different URLs.
    path = _normalise_escapes(parts.path) or "/"

    # Tracking parameters are cut out of the query as written. What remains keeps its
    # order, its encoding and the difference between `?edit` and `?edit=`; parsing and
    # re-encoding would change all three.
    before_fragment = url.split("#", 1)[0]
    query = ""
    if "?" in before_fragment:
        pieces = parts.query.split("&") if parts.query else []
        kept = [p for p in pieces if not _is_tracking(p.split("=", 1)[0])]
        if kept or not pieces:
            query = "?" + _normalise_escapes("&".join(kept))

    # A fragment is a position within the page, except in a hash-routed app, where it
    # names the page. Routes start with `/` or `!`, on any host.
    fragment = ""
    if parts.fragment.startswith(("/", "!")):
        fragment = "#" + _normalise_escapes(parts.fragment)

    return f"{scheme}://{netloc}{path}{query}{fragment}"


def url_hash(url: str) -> bytes:
    """SHA-256 of the normalised URL. Stored as ``bytea``, under ``UNIQUE (url_hash)``."""
    return hashlib.sha256(normalise(url).encode("utf-8")).digest()


def site_of(url: str) -> str | None:
    """Registrable domain, e.g. ``docs.python.org`` -> ``python.org``.

    The domain a page belongs to, which is a different fact from the client that saved
    it -- ``saved_from``. Conflating the two is why the predecessor's list-by-domain
    never worked (audit finding 6).
    """
    result = _extract(url)
    return result.top_domain_under_public_suffix or None
