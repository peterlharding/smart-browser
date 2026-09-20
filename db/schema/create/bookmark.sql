--
-- Table structure for table bookmark
--
-- The URL itself: global, owned by nobody, one row per distinct page. A person's save of
-- it lives in user_bookmark. Splitting the two is what keeps crawling and embedding cost
-- per-URL rather than per-user-per-URL.
--

CREATE TABLE bookmark (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    url            text         NOT NULL,
    -- sha256 of the normalised URL. The UNIQUE below is the entire no-duplicates
    -- guarantee: saving the same page twice cannot produce two rows, whatever the client
    -- does and however many clients do it at once.
    url_hash       bytea        NOT NULL,
    title          text,
    description    text,
    site           text,
    first_seen_at  timestamptz  NOT NULL DEFAULT now(),
    fetched_at     timestamptz,
    -- NULL means never fetched, which is a different thing from 410 Gone.
    http_status    integer,

    CONSTRAINT bookmark_url_hash_uniq UNIQUE (url_hash)
);

CREATE INDEX bookmark_site_idx ON bookmark (site);
