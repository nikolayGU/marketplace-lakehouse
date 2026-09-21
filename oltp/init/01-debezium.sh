#!/bin/bash
# Runs once, on an empty data directory, as the postgres superuser.
# Creates the CDC role and the publication. Tables come later from oltp/migrations.
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v dbz_user="$DEBEZIUM_USER" \
     -v dbz_password="$DEBEZIUM_PASSWORD" \
     -v db_name="$POSTGRES_DB" <<'EOSQL'
create schema if not exists shop;

create role :"dbz_user" with login replication password :'dbz_password';
grant connect on database :"db_name" to :"dbz_user";
grant usage on schema shop to :"dbz_user";
grant select on all tables in schema shop to :"dbz_user";
alter default privileges in schema shop grant select on tables to :"dbz_user";

-- Postgres 15+: the publication follows the schema, so tables created by later
-- migrations are captured without touching the connector.
create publication shop_publication for tables in schema shop;
EOSQL
