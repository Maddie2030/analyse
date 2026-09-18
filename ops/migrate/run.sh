#!/bin/sh
set -eu

DB_USER="${POSTGRES_USER:-manhwa}"
DB_NAME="${POSTGRES_DB:-manhwa}"
DB_HOST="${POSTGRES_HOST:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"
export PGPASSWORD="${POSTGRES_PASSWORD:-manhwa}"

echo "==> Waiting for PostgreSQL ${DB_HOST}:${DB_PORT}"
i=0
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "PostgreSQL did not become ready" >&2
    exit 1
  fi
  sleep 2
done

sh /usr/local/lib/mreader/migrate/apply.sh \
  -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME"
echo "Database migrations complete."
