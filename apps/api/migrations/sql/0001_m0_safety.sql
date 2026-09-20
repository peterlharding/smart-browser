-- M0 safety migration -- ADDITIVE ONLY.
--
-- Everything here is invisible to the existing v1 FastAPI app: no column is dropped,
-- renamed or retyped, and no constraint is added that current data would violate. It is
-- safe to apply to the live database before any of the M1 work begins.
--
-- What it fixes:
--   1. No sequences. `id` is a bare integer with no default, so the v1 app allocates with
--      SELECT MAX(id)+1 in Python. That races. Attaching real sequences removes the race
--      for every new insert while leaving existing rows untouched.
--   2. No index on bookmark(url). Every idempotent save does a URL lookup; without this
--      it is a sequential scan over 9,472 rows, and over far more later.
--   3. No index on bookmark_tag(tag_fk). This is the lookup the entire product depends on
--      -- "show me everything tagged python" -- and it has never been indexed.
--
-- Applied by Alembic revision 0001 (migrations/versions/0001_m0_safety.py), which reads this
-- file so that the SQL stays reviewable as SQL and `psql -f` still works in an emergency.
--
-- There is no BEGIN/COMMIT here: Alembic owns the transaction, and everything is guarded
-- by IF NOT EXISTS so a partial apply is safe to re-run.
--
-- PRECONDITION: run this as the table owner (plh) or a superuser.
--   CREATE SEQUENCE ... OWNED BY and ALTER TABLE ... SET DEFAULT both require ownership.
--   Running as an unprivileged role fails partway, leaving sequences created but not
--   attached. Everything is IF NOT EXISTS, so re-running as the owner recovers cleanly.
--   Check with:  \dt  -- the Owner column must match your session_user, or you are super.
--
-- Rollback is at the bottom, commented out.

-- 1. Sequences ---------------------------------------------------------------

CREATE SEQUENCE IF NOT EXISTS bookmark_id_seq     OWNED BY bookmark.id;
CREATE SEQUENCE IF NOT EXISTS tag_id_seq          OWNED BY tag.id;
CREATE SEQUENCE IF NOT EXISTS bookmark_tag_id_seq OWNED BY bookmark_tag.id;

-- Start each sequence above the current maximum. setval with is_called = true means the
-- next nextval() returns max+1.
SELECT setval('bookmark_id_seq',     COALESCE((SELECT MAX(id) FROM bookmark),     0) + 1, false);
SELECT setval('tag_id_seq',          COALESCE((SELECT MAX(id) FROM tag),          0) + 1, false);
SELECT setval('bookmark_tag_id_seq', COALESCE((SELECT MAX(id) FROM bookmark_tag), 0) + 1, false);

ALTER TABLE bookmark     ALTER COLUMN id SET DEFAULT nextval('bookmark_id_seq');
ALTER TABLE tag          ALTER COLUMN id SET DEFAULT nextval('tag_id_seq');
ALTER TABLE bookmark_tag ALTER COLUMN id SET DEFAULT nextval('bookmark_tag_id_seq');

-- ###AUTOCOMMIT### -----------------------------------------------------------
-- Everything below this marker runs outside a transaction. CREATE INDEX CONCURRENTLY
-- cannot run inside one, and the Alembic revision splits the file here.
--
-- 2. Indexes
-- On a table this size these complete near-instantly; CONCURRENTLY is habit, not need.

CREATE INDEX CONCURRENTLY IF NOT EXISTS bookmark_url_idx
    ON bookmark (url);

CREATE INDEX CONCURRENTLY IF NOT EXISTS bookmark_tag_tag_fk_idx
    ON bookmark_tag (tag_fk, bookmark_fk);

CREATE INDEX CONCURRENTLY IF NOT EXISTS bookmark_tag_bookmark_fk_idx
    ON bookmark_tag (bookmark_fk);

CREATE INDEX CONCURRENTLY IF NOT EXISTS bookmark_used_idx
    ON bookmark (used DESC);

ANALYZE bookmark;
ANALYZE tag;
ANALYZE bookmark_tag;

-- Rollback -------------------------------------------------------------------
-- DROP INDEX CONCURRENTLY IF EXISTS bookmark_url_idx;
-- DROP INDEX CONCURRENTLY IF EXISTS bookmark_tag_tag_fk_idx;
-- DROP INDEX CONCURRENTLY IF EXISTS bookmark_tag_bookmark_fk_idx;
-- DROP INDEX CONCURRENTLY IF EXISTS bookmark_used_idx;
-- ALTER TABLE bookmark     ALTER COLUMN id DROP DEFAULT;
-- ALTER TABLE tag          ALTER COLUMN id DROP DEFAULT;
-- ALTER TABLE bookmark_tag ALTER COLUMN id DROP DEFAULT;
-- DROP SEQUENCE IF EXISTS bookmark_id_seq, tag_id_seq, bookmark_tag_id_seq;
