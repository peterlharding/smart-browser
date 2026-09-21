--
-- Drop revision 0002's objects, in reverse dependency order.
--
-- The downgrade body for revision 0002, and runnable directly:
--
--     psql "$DATABASE_URL" -f db/schema/drop/drop_content.sql
--
-- The `vector` extension is deliberately left alone. It was installed by a superuser as a
-- bootstrap step, it may be in use by something else in this database, and dropping an
-- extension this role did not create is not a downgrade's business.
--

\echo 'Drop table - crawl_job'
DROP TABLE IF EXISTS crawl_job;

\echo 'Drop type  - job_state'
DROP TYPE IF EXISTS job_state;

\echo 'Drop table - bookmark_content'
DROP TABLE IF EXISTS bookmark_content;
