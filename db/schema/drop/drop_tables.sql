--
-- Drop every object, in reverse dependency order.
--
-- Used by the downgrade of Alembic revision 0001, and runnable directly:
--
--     psql "$DATABASE_URL" -f db/schema/drop/drop_tables.sql
--
-- IF EXISTS throughout so a partial schema drops cleanly. No CASCADE: a dependency this
-- file does not know about should stop the drop and be looked at, not be swept away.
--
-- alembic_version is deliberately absent. This file is the downgrade body, and alembic
-- writes the new revision to that table immediately afterwards -- dropping it here would
-- break the downgrade it implements. `make schema-drop` removes it separately, because
-- resetting to nothing is a different operation from stepping back one revision.
--

\echo 'Drop table - bookmark_tag'
DROP TABLE IF EXISTS bookmark_tag;

\echo 'Drop table - tag_alias'
DROP TABLE IF EXISTS tag_alias;

\echo 'Drop table - tag'
DROP TABLE IF EXISTS tag;

\echo 'Drop table - user_bookmark'
DROP TABLE IF EXISTS user_bookmark;

\echo 'Drop table - bookmark'
DROP TABLE IF EXISTS bookmark;

\echo 'Drop table - user_identity'
DROP TABLE IF EXISTS user_identity;

\echo 'Drop table - app_user'
DROP TABLE IF EXISTS app_user;

\echo 'Drop type  - tag_source'
DROP TYPE IF EXISTS tag_source;
