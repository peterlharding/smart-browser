--
-- Revision 0002 -- content and the crawl queue, in dependency order.
--
-- Each Alembic revision has its own manifest: create_tables.sql is revision 0001 and this
-- is 0002. They are not nested, deliberately -- the migration runner executes the files a
-- manifest names, and a manifest that named another manifest would run a file of
-- meta-commands and quietly do nothing. A from-scratch psql build runs them in order:
--
--     psql "$DATABASE_URL" -f db/schema/create/create_tables.sql
--     psql "$DATABASE_URL" -f db/schema/create/create_content.sql
--
-- The `vector` extension must already exist; see ../bootstrap.sql. Creating it needs a
-- superuser, which the application role is not, so it cannot be done from here.
--

\echo 'Create table - bookmark_content'
\ir bookmark_content.sql

\echo 'Create type  - job_state'
\ir job_state.sql

\echo 'Create table - crawl_job'
\ir crawl_job.sql
