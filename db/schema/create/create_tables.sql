--
-- Create every object, in dependency order.
--
-- This file is the single ordered manifest. It runs directly under psql:
--
--     psql "$DATABASE_URL" -f db/schema/create/create_tables.sql
--
-- and Alembic revision 0001 parses the \ir lines from it and executes each named file in
-- turn, so there is one order rather than two that can drift.
--
-- \ir, not \i: \i resolves relative to psql's working directory, \ir relative to this
-- file. The difference is whether running it from the repo root works.
--
-- No DROP statements here, deliberately. The convention elsewhere puts a
-- DROP TABLE IF EXISTS at the top of each create file so a rebuild is idempotent; on a
-- migration's upgrade path that is a silent data-loss footgun. Drops live in
-- ../drop/drop_tables.sql, which the downgrade uses.
--

\echo 'Create type  - tag_source'
\ir tag_source.sql

\echo 'Create table - app_user'
\ir app_user.sql

\echo 'Create table - user_identity'
\ir user_identity.sql

\echo 'Create table - bookmark'
\ir bookmark.sql

\echo 'Create table - user_bookmark'
\ir user_bookmark.sql

\echo 'Create table - tag'
\ir tag.sql

\echo 'Create table - tag_alias'
\ir tag_alias.sql

\echo 'Create table - bookmark_tag'
\ir bookmark_tag.sql
