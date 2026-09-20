--
-- Table structure for table user_bookmark
--
-- One person's save of one URL. Every read joins through here filtered by user_id;
-- reaching bookmark directly would leak the existence of other people's saves.
--

CREATE TABLE user_bookmark (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    user_id          bigint      NOT NULL,
    bookmark_id      bigint      NOT NULL,

    -- Your title beats the crawled one, without overwriting it for anyone else.
    title_override   text,
    notes            text,
    saved_from       varchar(64),
    created_at       timestamptz  NOT NULL DEFAULT now(),
    last_visited_at  timestamptz,
    visit_count      integer      NOT NULL DEFAULT 0,
    -- Soft delete. Unsaving removes your save; the URL record survives for everyone else,
    -- and re-saving restores this row rather than creating a second one.
    deleted_at       timestamptz,

    CONSTRAINT user_bookmark_uniq UNIQUE (user_id, bookmark_id),
    CONSTRAINT user_bookmark_user_id_fkey FOREIGN KEY (user_id)
        REFERENCES app_user (id) ON DELETE CASCADE,
    CONSTRAINT user_bookmark_bookmark_id_fkey FOREIGN KEY (bookmark_id)
        REFERENCES bookmark (id) ON DELETE CASCADE
);

CREATE INDEX user_bookmark_user_idx     ON user_bookmark (user_id);
CREATE INDEX user_bookmark_bookmark_idx ON user_bookmark (bookmark_id);
