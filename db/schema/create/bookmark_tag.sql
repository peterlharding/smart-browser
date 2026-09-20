--
-- Table structure for table bookmark_tag
--
-- Tags hang off the save, not off the URL, so one person's tagging is invisible to
-- another. source and confidence carry provenance: see the tag_source type.
--

CREATE TABLE bookmark_tag (
    user_bookmark_id  integer      NOT NULL,
    tag_id            integer      NOT NULL,
    source            tag_source   NOT NULL DEFAULT 'user',
    -- NULL for a tag a person chose. Set for a machine suggestion, so the UI can show it
    -- as provisional and a bulk accept or reject is a query rather than a migration.
    confidence        double precision,
    created_at        timestamptz  NOT NULL DEFAULT now(),

    CONSTRAINT bookmark_tag_pkey PRIMARY KEY (user_bookmark_id, tag_id),
    CONSTRAINT bookmark_tag_user_bookmark_id_fkey FOREIGN KEY (user_bookmark_id)
        REFERENCES user_bookmark (id) ON DELETE CASCADE,
    CONSTRAINT bookmark_tag_tag_id_fkey FOREIGN KEY (tag_id)
        REFERENCES tag (id) ON DELETE CASCADE
);

-- The lookup the entire product depends on: "everything tagged python".
CREATE INDEX bookmark_tag_tag_idx ON bookmark_tag (tag_id, user_bookmark_id);
