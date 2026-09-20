--
-- Table structure for table user_identity
--
-- One row per provider a person has linked. provider_subject is Google's `sub` or
-- GitHub's numeric id: immutable, unlike the email beside it.
--

CREATE TABLE user_identity (
    provider          varchar(32)   NOT NULL,
    provider_subject  varchar(255)  NOT NULL,
    user_id           integer       NOT NULL,
    email_at_link     text,
    created_at        timestamptz   NOT NULL DEFAULT now(),

    CONSTRAINT user_identity_pkey PRIMARY KEY (provider, provider_subject),
    CONSTRAINT user_identity_user_id_fkey FOREIGN KEY (user_id)
        REFERENCES app_user (id) ON DELETE CASCADE
);

CREATE INDEX user_identity_user_idx ON user_identity (user_id);
