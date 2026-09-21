--
-- Revision 0003 -- the title as seen at save time, kept apart from the title you chose.
--
-- Its own manifest, like every revision's. A fresh psql build runs all three in order:
--
--     psql "$DATABASE_URL" -f db/schema/create/create_tables.sql
--     psql "$DATABASE_URL" -f db/schema/create/create_content.sql
--     psql "$DATABASE_URL" -f db/schema/create/create_saved_title.sql
--
-- A new column is a new file rather than an edit to user_bookmark.sql. Revision 0001
-- executes whatever that file says *now*, so editing it would change what 0001 builds,
-- and this revision's ALTER would then fail on a fresh database with the column already
-- there.
--

\echo 'Alter table  - user_bookmark.saved_title'
\ir user_bookmark_saved_title.sql
