#!/bin/bash
# Docker init step (runs after 01_schema.sql and 02_seed_data.sql).
# Migration 0015 creates the API login role `resqlink_app` as NOLOGIN without
# a password (secrets never live in migrations). Give it a login here from the
# APP_DB_PASSWORD environment variable. resqlink_app is NOSUPERUSER,
# NOBYPASSRLS and NOINHERIT: it can only act through SET LOCAL ROLE api_*.
set -euo pipefail
if [ -z "${APP_DB_PASSWORD:-}" ]; then
    echo "APP_DB_PASSWORD is not set; refusing to create a passwordless API login." >&2
    exit 1
fi
psql -v ON_ERROR_STOP=1 -v app_pw="$APP_DB_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
ALTER ROLE resqlink_app LOGIN PASSWORD :'app_pw';
SQL
