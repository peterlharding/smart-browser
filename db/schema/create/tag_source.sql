--
-- Type structure for tag_source
--
-- Where a tag on a bookmark came from. The reason bookmark_tag is not merely a join
-- table: an AI suggestion and a choice a person made are different claims, and keeping
-- both in one table with this column makes "only the tags I chose myself" a WHERE clause
-- rather than a second table to keep in step.
--

CREATE TYPE tag_source AS ENUM ('user', 'ai', 'rule', 'import');
