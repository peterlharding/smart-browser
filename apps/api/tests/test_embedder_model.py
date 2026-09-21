"""The real embedding model (ADR 0013). Opt in with `pytest -m model` or `make test-model`.

Downloads `bge-small-en-v1.5` once, 64 MB, into EMBEDDING_CACHE_DIR. The default suite
never does: everything else about the embedder is tested with a fake model. This is the
test that can reach what the fake cannot -- that the configured model exists, loads, is the
width of the column, and puts related pages nearer each other than unrelated ones.
"""

import math

import pytest

from bookmarks_api.config import get_settings
from bookmarks_api.embedder import FastembedModel
from bookmarks_api.models import EMBEDDING_DIM

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def model() -> FastembedModel:
    settings = get_settings()
    return FastembedModel(settings.embedding_model, settings.embedding_cache_dir)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_the_configured_model_fits_the_column(model):
    assert model.dim == EMBEDDING_DIM


def test_vectors_are_unit_length(model):
    (vector,) = model.embed(["Tuning Postgres for analytical queries."])
    assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, rel_tol=1e-6)


def test_related_pages_are_nearer_than_unrelated_ones(model):
    postgres, postgres_again, bread = model.embed([
        "Tuning Postgres: work memory matters more than shared buffers for sorts.",
        "PostgreSQL performance: configuring work_mem and shared_buffers.",
        "A sourdough recipe with a long cold fermentation and a very hot oven.",
    ])
    assert cosine(postgres, postgres_again) > cosine(postgres, bread) + 0.2


def test_a_page_longer_than_the_model_reads_is_truncated_not_refused(model):
    (vector,) = model.embed(["word " * 5000])
    assert len(vector) == EMBEDDING_DIM
