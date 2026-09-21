--
-- One-time bootstrap. Run as a superuser, once per database:
--
--     make db-bootstrap
--
-- pgvector is not a trusted extension -- vector.control carries no `trusted = true` -- so
-- CREATE EXTENSION requires a superuser, and the application role that runs migrations is
-- deliberately not one. This is therefore the one piece of schema that a migration cannot
-- apply; revision 0002 checks for it and names this file if it is missing.
--
-- Everything after this runs as the ordinary application role: the vector columns, the
-- hnsw and gin indexes and the queries over them all work without further privileges.
--

CREATE EXTENSION IF NOT EXISTS vector;
