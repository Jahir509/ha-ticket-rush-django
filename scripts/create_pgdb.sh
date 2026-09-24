#!/usr/bin/env bash
# Create the Postgres role and database this project uses.
#
# Reads PG_NAME / PG_USER / PG_PASSWORD from .env (or .env.example if there
# is no .env). Safe to run again: an existing role just gets its password
# reset to match .env, and an existing database is left alone.
#
# Runs as the postgres superuser via sudo by default. Override ADMIN_PSQL to
# use something else, e.g.
#   ADMIN_PSQL="psql -h 127.0.0.1 -U postgres" scripts/create_pgdb.sh
set -euo pipefail

cd "$(dirname "$0")/.."

env_file=.env
[ -f "$env_file" ] || env_file=.env.example
set -a
# shellcheck disable=SC1090
. "./$env_file"
set +a

: "${PG_NAME:?PG_NAME not set in $env_file}"
: "${PG_USER:?PG_USER not set in $env_file}"
: "${PG_PASSWORD:?PG_PASSWORD not set in $env_file}"

ADMIN_PSQL=${ADMIN_PSQL:-sudo -u postgres psql}

echo "Creating role '$PG_USER' and database '$PG_NAME' (from $env_file)"

# \gexec runs each generated statement. format() with %I / %L quotes the
# names and password properly, so odd characters in .env cannot break out.
$ADMIN_PSQL -X -v ON_ERROR_STOP=1 \
  -v db="$PG_NAME" -v user="$PG_USER" -v pass="$PG_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'user', :'pass')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'user') \gexec

SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'user', :'pass')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'user') \gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'db', :'user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
SQL

echo "Done. Next: python manage.py migrate"
