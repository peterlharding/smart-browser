"""URL normalisation.

This is the load-bearing piece of the dedupe story: 2,216 of 9,472 rows in the 2025
dump are duplicate URLs (doc/audit-2026-09-20.md). Normalising before hashing is what
makes `POST /bookmarks` idempotent, which is what stops the extension creating a new
row every time you hit the shortcut twice.

Deliberately conservative. Normalisation that changes which page you land on is worse
than a duplicate row, so when in doubt this leaves the URL alone.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import tldextract

# Use the bundled public-suffix snapshot: no network call at import time, and no
# surprise failure when the process starts somewhere without egress.
_extract = tldextract.TLDExtract(suffix_list_urls=())

DEFAULT_PORTS = {"http": 80, "https": 443}

# Tracking parameters carry no page identity. Removing them merges rows that are the
# same page arrived at by different routes.
TRACKING_PREFIXES = ("utm_", "pk_", "mc_", "hsa_", "vero_", "_hs")
TRACKING_PARAMS = frozenset(
    {
        "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "twclid",
        "igshid", "mkt_tok", "yclid", "ref_src", "ref_url", "s_kwcid",
        "icid", "scid", "cmpid", "campaign_id", "trk", "trkCampaign",
    }
)

# Fragments are page-internal *except* where they aren't: these hosts route on them.
HASHBANG_HOSTS = frozenset({"groups.google.com", "twitter.com", "x.com"})


def _is_tracking(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PREFIXES)


def normalise(url: str) -> str:
    """Return a canonical form of *url*.

    Idempotent: ``normalise(normalise(u)) == normalise(u)``.
    """
    url = url.strip()
    if not url:
        raise ValueError("empty url")

    # Bare "example.com/x" -- assume https rather than rejecting it.
    if "://" not in url:
        url = "https://" + url

    parts = urlsplit(url)
    scheme = parts.scheme.lower()

    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError(f"no host in url: {url!r}")

    # Drop the default port; keep a non-default one.
    port = parts.port
    netloc = host if port is None or DEFAULT_PORTS.get(scheme) == port else f"{host}:{port}"

    # Userinfo is credentials, not identity -- and we do not want it in the database.
    # It is dropped silently rather than preserved.

    path = parts.path or "/"
    # Collapse a bare trailing slash only at the root; "/docs/" and "/docs" can differ.
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/") or "/"

    query_pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                   if not _is_tracking(k)]
    # Sort for stability: ?a=1&b=2 and ?b=2&a=1 are the same request.
    query = urlencode(sorted(query_pairs), doseq=True)

    fragment = parts.fragment if (host in HASHBANG_HOSTS and parts.fragment.startswith("!")) else ""

    return urlunsplit((scheme, netloc, path, query, fragment))


def url_hash(url: str) -> bytes:
    """SHA-256 of the normalised URL. Stored as ``bytea``; the unique index in M2."""
    return hashlib.sha256(normalise(url).encode("utf-8")).digest()


def site_of(url: str) -> str | None:
    """Registrable domain, e.g. ``docs.python.org`` -> ``python.org``.

    This is the field ``/bookmarks/list-by-domain`` always meant. The existing `host`
    column holds the *poster's* hostname (`AASDev` on 8,661 rows), which is a different
    thing entirely -- see doc/audit-2026-09-20.md finding 6.
    """
    result = _extract(url)
    return result.top_domain_under_public_suffix or None
