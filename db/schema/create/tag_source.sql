--
-- Type structure for tag_source
--
-- Where a tag on a bookmark came from. The reason bookmark_tag is not merely a join
-- table: an AI suggestion and a choice a person made are different claims, and keeping
-- both in one table with this column makes "only the tags I chose myself" a WHERE clause
-- rather than a second table to keep in step.
--
-- Postgres has no CREATE TYPE IF NOT EXISTS, and a type is the object most likely to
-- survive a partial teardown -- dropping tables by hand does not remove it. So this
-- creates the type when absent, does nothing when it already exists with exactly these
-- labels, and fails loudly when it exists with different ones. Re-runnable without being
-- blind: an existing type that disagrees is a real problem and should stop the migration.
--

DO $$
DECLARE
    existing text[];
    wanted   text[] := ARRAY['user', 'ai', 'rule', 'import'];
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tag_source') THEN
        CREATE TYPE tag_source AS ENUM ('user', 'ai', 'rule', 'import');
        RETURN;
    END IF;

    SELECT array_agg(e.enumlabel ORDER BY e.enumsortorder)
      INTO existing
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
     WHERE t.typname = 'tag_source';

    IF existing IS DISTINCT FROM wanted THEN
        RAISE EXCEPTION
            'type tag_source already exists with labels %, but this schema expects %',
            existing, wanted;
    END IF;
END
$$;
