-- ============================================================================
-- ResQLink — Local Dev Reset Script
-- Drops the public schema (everything in it) and rebuilds it from schema.sql,
-- then loads sample data from seed_data.sql. Safe to re-run as many times as
-- you like; it is fully idempotent for local/dev use.
--
-- Usage (from the database/scripts directory):
--   psql "$DATABASE_URL" -f reset_db.sql
--
-- To tear down WITHOUT reseeding, comment out the final \ir line below.
-- ============================================================================

\echo '>>> Dropping and recreating public schema...'
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO CURRENT_USER;

\echo '>>> Rebuilding schema (extensions, tables, indexes, triggers)...'
\ir ../schema.sql

\echo '>>> Loading seed data...'
\ir seed_data.sql

\echo '>>> Done. ResQLink local database is ready.'
