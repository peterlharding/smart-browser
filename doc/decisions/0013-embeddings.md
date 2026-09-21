# 0013 - Embeddings

- **Date:** 2026-09-21
- **Status:** Accepted
- **Builds on:** [ADR 0012](0012-crawl-worker.md) (the text it embeds), `architecture.md` section 2 (the model)

## Context

The crawl worker fills `bookmark_content.text`.
The last part of M3 turns that text into a vector in `bookmark_content.embedding`, which is what M4's tag suggestions and M6's "similar pages" will compare.

Three things are already settled.
The model is `bge-small-en-v1.5`, 384 dimensions, run locally (architecture.md, 2026-09-20).
The column is `vector(384)` with an `hnsw` cosine index (revision `0002`).
And embedding is a second pass in its own process, never in the fetch loop (ADR 0012).

What is left: which library runs the model, what text goes in, and how the pass runs.

### Measured

Both candidate runtimes were installed into scratch environments on Python 3.14, the API's interpreter, and run on the same 200 short texts on this Mac.
Both install on macOS arm64 and on Linux x86_64, CI's platform.

| | `fastembed` (ONNX) | `sentence-transformers` (PyTorch) |
| --- | --- | --- |
| Installed size | 142 MB | 797 MB |
| Model download | 64 MB | 137 MB |
| Load, warm | 0.3 s | 9.4 s |
| 200 short texts | 0.75 s | 0.36 s |
| 64 full 512-token passages | 5.3 s, 12 a second | not measured |
| Agreement | cosine 1.0000 with the other, on every text | |

They produce the same vectors.
As a sanity check, two texts about Postgres tuning scored 0.87 against each other and 0.44 against a bread recipe.

## Decision

### The runtime is `fastembed`

It is a fifth of the size, loads thirty times faster, and gives the same vectors.
PyTorch's throughput advantage does not matter at this scale: at 12 full pages a second, 7,256 pages, the size of the predecessor's corpus, is about ten minutes, once.

The model is downloaded on first use, 64 MB from Hugging Face, into `EMBEDDING_CACHE_DIR` (default `~/.cache/smart-browser/models`), and never again.

### What goes in

**One vector per page**, from the crawled title, the description and the extracted text, joined with blank lines.
The model reads at most 512 tokens, about 350 words, and `fastembed` truncates beyond that.
So in practice a page is represented by its title, its description and the opening of its article.
Pages with no text but a title (a single-page app's shell) are embedded from what they have; pages with nothing are skipped.

**No instruction prefix.**
`bge` models take a prefix on short *queries* ("Represent this sentence for searching relevant passages: "), and none on the passages being searched.
Stored pages are passages.
The query side belongs to M6's search.

**Vectors are stored normalised to length 1**, which is what the cosine index expects.

### Knowing when to re-embed

`bookmark_content.model` records both the model and the recipe that produced the vector, for example `BAAI/bge-small-en-v1.5|title+description+text`.
A row needs embedding when it has text or a title and its `model` differs from the current value, which includes NULL.
Changing the model *or* the recipe is therefore a re-embed of everything, found by the same query, with no migration.
A re-crawl already clears both columns (ADR 0012), so changed text is picked up the same way.

### How it runs

- **`python -m bookmarks_api.embedder`, run as `make embed`**, alongside `make worker`.
  `--once` embeds what is waiting and exits.
- **No queue table.**
  The query above is the queue: embedding is local and deterministic, so there are no retries, backoff or leases to keep.
  A batch that raises is a bug, logged and left for the next run.
- **Batches of 32**, claimed with `FOR UPDATE SKIP LOCKED` so two embedders never do the same rows, and committed per batch.
  The model runs with the batch's rows locked; at about three seconds per batch of full pages, that holds nothing anyone waits on.
- **The model's dimension is checked against the column's before anything is written**, so a configured model that is not 384-dimensional stops the process with a message rather than failing on every insert.
- **`make crawl-status` gains an embedding line**: how many pages have text, how many are embedded with the current model.

## Options not taken

- **`sentence-transformers`.**
  The reference implementation, and twice the throughput, for 650 MB more of PyTorch and nine seconds of startup, to produce identical vectors.
- **Embedding inside the crawl worker.**
  One process fewer to run, but ADR 0012 decided against it: a model problem would then stop crawling, and the fetch loop would carry 64 MB of model it does not need.
- **Averaging chunk embeddings over the whole text.**
  It would represent a long page's later sections, at several times the cost, and averaging blurs a page toward generic vectors.
  Nothing measured says it is better for this corpus.
  The opening of an article is what it is about far more often than not.
  The M4 benchmark against the 1,817 hand-tagged bookmarks is where to find out, and the recipe in `model` makes switching a re-run, not a migration.
- **A vector per chunk, in its own table.**
  Better for finding a passage inside a long page, which nothing here needs yet, and a schema change.

## Consequences

- A third process for a full local setup: `make api-dev`, `make worker`, `make embed`.
- `fastembed` brings `onnxruntime` and `tokenizers`, about 140 MB, into the API environment.
- **The default test suite never downloads the model.**
  The embedder takes the model as a parameter, as the worker takes its fetcher, and a fake one drives every path.
  The real model runs in an opt-in test (`-m model`) that checks dimension, normalisation and that related texts score above unrelated ones.
  CI runs it with the model cached between runs.
- A Postgres test writes real 384-dimension vectors through the embedder and finds a page's nearest neighbour with the `hnsw` index.
