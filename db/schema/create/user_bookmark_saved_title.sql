--
-- Column user_bookmark.saved_title
--
-- The title the client saw when it saved: the browser tab's title, for the extension.
-- Per save, like saved_from, because a tab title can be private in a way a URL is not,
-- and bookmark is shared. Display precedence is
--
--     title_override  ->  saved_title  ->  bookmark.title
--
-- what you typed, then what you saw, then what the crawler fetched. See ADR 0010.
--

ALTER TABLE user_bookmark ADD COLUMN saved_title text;

-- Until this column existed, clients wrote the tab title into title_override, and no
-- client has ever offered a way to type one. Every existing override is therefore a
-- title as seen, not a title chosen, and moves to where that now lives.
UPDATE user_bookmark
   SET saved_title = title_override,
       title_override = NULL
 WHERE title_override IS NOT NULL;
