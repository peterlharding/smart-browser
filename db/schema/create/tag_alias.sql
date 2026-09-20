--
-- Table structure for table tag_alias
--
-- Misspellings and variants resolving to a canonical tag. The audit found 32
-- near-duplicate pairs in a 567-tag vocabulary -- bootstrap/boorstrap,
-- letsencrypt/letsencrypy, fontawesome/font-awesome -- kept at bay by a hardcoded
-- corrections dict in application code. This is that dict as data, so a merge fixes the
-- vocabulary for everyone at once.
--

CREATE TABLE tag_alias (
    alias   text     NOT NULL,
    tag_id  integer  NOT NULL,

    CONSTRAINT tag_alias_pkey PRIMARY KEY (alias),
    CONSTRAINT tag_alias_tag_id_fkey FOREIGN KEY (tag_id)
        REFERENCES tag (id) ON DELETE CASCADE
);

CREATE INDEX tag_alias_tag_idx ON tag_alias (tag_id);
