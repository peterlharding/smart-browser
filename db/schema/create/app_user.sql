--
-- Table structure for table app_user
--

CREATE TABLE app_user (
    id            SERIAL       PRIMARY KEY,
    display_name  text,
    -- Informational only. Identity is keyed on (provider, provider_subject) in
    -- user_identity -- never on email, which providers let people change, and which
    -- makes match-on-email account linking a pre-account-takeover path.
    email         text,
    avatar_url    text,
    created_at    timestamptz  NOT NULL DEFAULT now(),
    last_seen_at  timestamptz,
    is_active     boolean      NOT NULL DEFAULT true
);
