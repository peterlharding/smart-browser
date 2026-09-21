"""The title, description and main text of a fetched page (ADR 0012).

`trafilatura` separates the article from the page around it. That matters more than
anything else the crawler does: this text is what M4 prompts with and what the embeddings
are computed from, and navigation, footers and cookie banners in it are noise every later
stage pays for.
"""

from __future__ import annotations

from dataclasses import dataclass

import trafilatura
from trafilatura.settings import Document
from trafilatura.utils import load_html

MAX_TITLE = 1024
MAX_DESCRIPTION = 2048
MAX_TEXT = 200_000


@dataclass(frozen=True)
class Extracted:
    title: str | None
    description: str | None
    text: str | None


def _clean(value: str | None, limit: int) -> str | None:
    """Whitespace collapsed, capped, and None rather than empty."""
    if not value:
        return None
    return " ".join(value.split())[:limit] or None


def extract(body: bytes, url: str) -> Extracted:
    """Extract from raw bytes; the character set is detected from the page itself."""
    tree = load_html(body)
    if tree is None:
        return Extracted(None, None, None)

    # bare_extraction prunes the tree it is given, so metadata for a page with no main
    # text -- a single-page app's empty shell, say -- comes from a fresh parse.
    document = trafilatura.bare_extraction(
        tree, url=url, with_metadata=True, include_comments=False
    )
    if not isinstance(document, Document):  # None: no main text; never a dict without as_dict
        metadata = trafilatura.extract_metadata(load_html(body), default_url=url)
        return Extracted(
            title=_clean(metadata.title, MAX_TITLE),
            description=_clean(metadata.description, MAX_DESCRIPTION),
            text=None,
        )

    text = (document.text or "").strip()
    return Extracted(
        title=_clean(document.title, MAX_TITLE),
        description=_clean(document.description, MAX_DESCRIPTION),
        text=text[:MAX_TEXT] or None,
    )
