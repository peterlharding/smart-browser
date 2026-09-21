--
-- Type structure for type job_state
--
-- Idempotent in the same way as tag_source, and for the same reason: Postgres has no
-- CREATE TYPE IF NOT EXISTS, and a type survives dropping the tables that use it, so a
-- half-torn-down database would otherwise be un-migratable. Matching labels pass in
-- silence; different labels stop the migration rather than leaving it to fail later on a
-- value that does not fit.
--

DO $$
DECLARE
    existing text[];
    wanted   text[] := ARRAY['ready', 'running', 'done', 'failed'];
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'job_state') THEN
        CREATE TYPE job_state AS ENUM ('ready', 'running', 'done', 'failed');
        RETURN;
    END IF;

    SELECT array_agg(e.enumlabel ORDER BY e.enumsortorder) INTO existing
      FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
     WHERE t.typname = 'job_state';

    IF existing IS DISTINCT FROM wanted THEN
        RAISE EXCEPTION
            'type job_state already exists with labels %, but this schema expects %',
            existing, wanted;
    END IF;
END
$$;
