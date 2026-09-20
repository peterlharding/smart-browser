--
-- Table structure for table tag
--
-- One global vocabulary, no owner: ownership lives on the link in bookmark_tag. Names are
-- lowercased by the application on every write path, so a plain UNIQUE is sufficient and
-- the schema needs no citext extension.
--

CREATE TABLE tag (
    id           SERIAL       PRIMARY KEY,
    name         text         NOT NULL,
    parent_id    integer,
    description  text,
    created_at   timestamptz  NOT NULL DEFAULT now(),

    CONSTRAINT tag_name_key UNIQUE (name),
    -- trim(), not btrim(): standard SQL, so this file also runs outside Postgres.
    -- One blank tag on 43 bookmarks is how a vocabulary decays.
    CONSTRAINT tag_name_not_blank CHECK (length(trim(name)) > 0),
    CONSTRAINT tag_parent_id_fkey FOREIGN KEY (parent_id)
        REFERENCES tag (id) ON DELETE SET NULL
);
