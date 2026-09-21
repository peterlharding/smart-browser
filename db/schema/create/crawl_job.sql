--
-- Table structure for table crawl_job
--
-- The work queue. A row is written in the same transaction as the bookmark it belongs
-- to, so a crash between "saved" and "needs fetching" is not a state this system can
-- reach: either both committed or neither did.
--
-- bookmark_id is the primary key, not a job id. One outstanding crawl per URL is the
-- invariant, and this way the database enforces it rather than the enqueue code
-- remembering to check.
--

CREATE TABLE crawl_job (
    bookmark_id      bigint PRIMARY KEY REFERENCES bookmark(id) ON DELETE CASCADE,

    state            job_state   NOT NULL DEFAULT 'ready',
    attempts         integer     NOT NULL DEFAULT 0,
    -- When this may next be claimed. Backoff is a timestamp rather than a sleep so it
    -- survives the worker being restarted, and so a second worker honours it too.
    next_attempt_at  timestamptz NOT NULL DEFAULT now(),
    -- Why the last attempt failed, in the far end's own words. The difference between
    -- "404" and "connection reset" is the difference between deleting the bookmark and
    -- trying again tomorrow.
    last_error       text,
    claimed_at       timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- The only query the worker runs often, and partial so the index is the size of the
-- backlog rather than of the corpus. A finished crawl leaves no trace in it.
CREATE INDEX crawl_job_ready_idx ON crawl_job (next_attempt_at)
    WHERE state = 'ready';
