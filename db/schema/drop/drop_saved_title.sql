--
-- Drop revision 0003's objects.
--
-- The downgrade body for revision 0003, and runnable directly:
--
--     psql "$DATABASE_URL" -f db/schema/drop/drop_saved_title.sql
--
-- Before 0003 the title as seen lived in title_override, so it goes back there rather than
-- being thrown away. Where a save has both, the override is the one a person chose and it
-- is kept; the saved title is the only thing a downgrade loses.
--
-- IF EXISTS on the table as well as the column: `make schema-drop` runs every revision's
-- drop script newest first, against whatever state the database is in.
--

UPDATE user_bookmark
   SET title_override = saved_title
 WHERE title_override IS NULL
   AND saved_title IS NOT NULL;

\echo 'Drop column  - user_bookmark.saved_title'
ALTER TABLE IF EXISTS user_bookmark DROP COLUMN IF EXISTS saved_title;
