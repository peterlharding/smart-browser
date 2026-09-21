"""The embedding pass (ADR 0013), with a fake model and no download.

Pages are made the way the crawl worker makes them -- a `bookmark` with a crawled title
and a `bookmark_content` row -- so the embedder is tested against the state it will meet.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from bookmarks_api import embedder, worker
from bookmarks_api.models import Bookmark, BookmarkContent
from bookmarks_api.urlnorm import url_hash
from conftest import FakeModel

T0 = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
def factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def crawled(factory, url: str, *, title=None, description=None, text=None, content=True) -> int:
    with factory() as session:
        page = Bookmark(url=url, url_hash=url_hash(url), title=title, description=description)
        session.add(page)
        session.flush()
        if content:
            session.add(BookmarkContent(bookmark_id=page.id, text_=text))
        session.commit()
        return page.id


def content(factory, bookmark_id: int) -> BookmarkContent:
    with factory() as session:
        return session.get(BookmarkContent, bookmark_id)


def run_once(factory, model) -> int:
    return embedder.run(factory, model, once=True, clock=lambda: T0, log=lambda _: None)


def test_a_crawled_page_is_embedded_and_labelled(factory):
    bid = crawled(factory, "https://a.example/", title="Tuning Postgres", text="Work memory.")
    model = FakeModel()

    assert run_once(factory, model) == 1

    row = content(factory, bid)
    assert row.model == "fake/model|title+description+text"
    assert len(row.embedding) == 384
    assert math.isclose(math.sqrt(sum(x * x for x in row.embedding)), 1.0)
    assert row.updated_at.replace(tzinfo=UTC) == T0


def test_the_passage_is_title_description_and_text(factory):
    crawled(factory, "https://a.example/", title=" T ", description="D", text="Body.")
    model = FakeModel()
    run_once(factory, model)
    assert model.calls == [["T\n\nD\n\nBody."]]


@pytest.mark.parametrize(
    ("title", "description", "body", "expected"),
    [
        ("T", None, None, "T"),
        (None, "D", "Body", "D\n\nBody"),
        ("  ", "", "Body", "Body"),
        (None, None, None, None),
    ],
)
def test_missing_parts_are_left_out(title, description, body, expected):
    assert embedder.passage(title, description, body) == expected


def test_a_shell_with_only_a_title_is_embedded_from_its_title(factory):
    """A single-page app's shell has no text, and its title still says what it is."""
    bid = crawled(factory, "https://app.example/", title="My App", text=None)
    run_once(factory, FakeModel())
    assert content(factory, bid).embedding is not None


def test_a_page_with_nothing_to_embed_is_skipped(factory):
    bid = crawled(factory, "https://empty.example/", text=None)
    model = FakeModel()
    assert run_once(factory, model) == 0
    assert model.calls == []
    assert content(factory, bid).embedding is None


def test_a_page_embedded_with_the_current_model_is_not_embedded_again(factory):
    crawled(factory, "https://a.example/", title="A", text="Body")
    model = FakeModel()
    run_once(factory, model)
    assert run_once(factory, model) == 0
    assert len(model.calls) == 1


def test_a_new_model_re_embeds_everything(factory):
    bid = crawled(factory, "https://a.example/", title="A", text="Body")
    run_once(factory, FakeModel("old/model"))

    assert run_once(factory, FakeModel("new/model")) == 1
    assert content(factory, bid).model == "new/model|title+description+text"


def test_a_new_recipe_re_embeds_everything(factory, monkeypatch):
    bid = crawled(factory, "https://a.example/", title="A", text="Body")
    run_once(factory, FakeModel())

    monkeypatch.setattr(embedder, "RECIPE", "title+text")
    assert run_once(factory, FakeModel()) == 1
    assert content(factory, bid).model == "fake/model|title+text"


def test_a_recrawled_page_is_embedded_again(factory):
    """The crawl worker clears `embedding` and `model` when it writes new text."""
    bid = crawled(factory, "https://a.example/", title="A", text="Old text")
    model = FakeModel()
    run_once(factory, model)
    with factory() as session:
        row = session.get(BookmarkContent, bid)
        row.text_, row.embedding, row.model = "New text", None, None
        session.commit()

    assert run_once(factory, model) == 1
    assert model.calls[-1] == ["A\n\nNew text"]


def test_work_is_done_in_batches(factory):
    for i in range(70):
        crawled(factory, f"https://p{i}.example/", title=f"Page {i}")
    model = FakeModel()

    assert run_once(factory, model) == 70
    assert [len(batch) for batch in model.calls] == [32, 32, 6]


def test_a_failing_batch_writes_nothing_and_fails_the_run(factory, capsys):
    bid = crawled(factory, "https://a.example/", title="A", text="Body")
    with pytest.raises(RuntimeError, match="model exploded"):
        run_once(factory, FakeModel(fail=True))
    assert content(factory, bid).embedding is None
    assert "RuntimeError: model exploded" in capsys.readouterr().err


def test_a_model_returning_the_wrong_number_of_vectors_writes_nothing(factory):
    bid = crawled(factory, "https://a.example/", title="A", text="Body")
    crawled(factory, "https://b.example/", title="B", text="Body")

    class Short(FakeModel):
        def embed(self, texts):
            return super().embed(texts)[:1]

    with pytest.raises(RuntimeError, match="returned 1 vectors for 2 texts"):
        run_once(factory, Short())
    assert content(factory, bid).embedding is None


def test_a_model_of_the_wrong_dimension_is_refused_before_writing(factory):
    with factory() as session, pytest.raises(ValueError, match="makes 768-dimension vectors"):
        embedder.check_dimension(session, FakeModel("big/model", dim=768))


def test_crawl_status_reports_the_embedding_pass(factory):
    crawled(factory, "https://a.example/", title="A", text="Body")
    crawled(factory, "https://b.example/", title="B", text="Body")
    crawled(factory, "https://empty.example/", text=None)
    with factory() as session:
        embedder.embed_batch(session, FakeModel(), T0, size=1)

    with factory() as session:
        text = worker.status(session, embedding_label=embedder.label("fake/model"))
    assert "embedded 1 of 2 pages with content, as fake/model|title+description+text" in text
