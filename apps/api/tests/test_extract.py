"""Extraction (ADR 0012): the article, not the page around it."""

from bookmarks_api.extract import MAX_TEXT, MAX_TITLE, extract

ARTICLE = """<html><head>
<meta charset="utf-8">
<title>Tuning Postgres | Some Blog</title>
<meta property="og:title" content="Tuning Postgres">
<meta name="description" content="How   to make   it fast.">
</head><body>
<nav><a href="/">Home</a> <a href="/about">About</a> Subscribe to the newsletter</nav>
<article>
<h1>Tuning Postgres</h1>
<p>Shared buffers are the first setting anyone reaches for, and usually the wrong one to
start with, because the operating system is already caching the same pages.</p>
<p>Work memory matters more for the queries that sort, and it is allocated per operation,
which is how a modest-looking value takes a server down under concurrency.</p>
</article>
<footer>Copyright 2026. Accept all cookies to continue.</footer>
</body></html>"""


def test_the_main_text_is_the_article_and_not_its_surroundings():
    text = extract(ARTICLE.encode(), "https://blog.example/pg").text
    assert "Work memory matters more" in text
    assert "Subscribe to the newsletter" not in text
    assert "Accept all cookies" not in text


def test_the_title_prefers_the_pages_own_name_for_itself():
    assert extract(ARTICLE.encode(), "https://blog.example/pg").title == "Tuning Postgres"


def test_the_description_has_its_whitespace_collapsed():
    assert extract(ARTICLE.encode(), "https://blog.example/pg").description == (
        "How to make it fast."
    )


def test_a_page_with_no_main_text_still_gives_its_title():
    """A single-page app's shell: the text arrives later, from JavaScript."""
    shell = b'<html><head><title>My   App</title></head><body><div id="root"></div></body></html>'
    result = extract(shell, "https://app.example/")
    assert (result.title, result.text) == ("My App", None)


def test_the_character_set_comes_from_the_page():
    latin1 = (
        '<html><head><meta charset="windows-1252"><title>Café</title></head><body></body></html>'
    )
    assert extract(latin1.encode("windows-1252"), "https://x.example/").title == "Café"


def test_nothing_parseable_is_nothing():
    assert extract(b"", "https://x.example/").title is None


def test_long_titles_and_texts_are_capped():
    words = " ".join(f"word{i}" for i in range(60_000))
    page = (
        f"<html><head><title>{'t' * 5000}</title></head>"
        f"<body><article><p>{words}</p></article></body></html>"
    )
    result = extract(page.encode(), "https://x.example/")
    assert len(result.title) == MAX_TITLE
    assert len(result.text) <= MAX_TEXT
