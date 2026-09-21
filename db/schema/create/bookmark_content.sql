--
-- Table structure for table bookmark_content
--
-- What the crawler extracted, keyed by the URL rather than by anybody's save: ten people
-- saving the same page pay for one fetch and one embedding. That is the whole reason
-- bookmark and user_bookmark are separate tables (ADR 0001).
--
-- A row here means the fetch succeeded and produced something. A bookmark with no row
-- has either never been fetched (bookmark.fetched_at IS NULL) or has been fetched and
-- yielded nothing usable -- crawl_job holds the difference.
--

CREATE TABLE bookmark_content (
    bookmark_id  bigint PRIMARY KEY REFERENCES bookmark(id) ON DELETE CASCADE,

    text         text,
    -- Generated, not maintained: a trigger or an application write can be forgotten, and
    -- a stale tsv is a search index that lies. 'english' is a choice, and changing it
    -- later is a table rewrite.
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED,

    embedding    vector(384),
    -- Which model produced `embedding`, so a re-embed is a WHERE clause rather than an
    -- archaeology exercise. NULL embedding with a NULL model means not embedded yet.
    model        text,
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX bookmark_content_tsv_idx ON bookmark_content USING gin (tsv);

-- hnsw, not ivfflat: it needs no training pass over existing data, which matters when the
-- table starts empty and fills one save at a time.
CREATE INDEX bookmark_content_emb_idx ON bookmark_content
    USING hnsw (embedding vector_cosine_ops);
