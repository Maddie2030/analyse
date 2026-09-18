#!/bin/sh
# Render before connecting: a missing input must never leave a partial upgrade.
set -eu
export LC_ALL=C
[ "$#" -eq 2 ] || { echo "Usage: render.sh MIGRATION_DIRECTORY PRESERVATION_SQL" >&2; exit 2; }
migration_dir="$1"
preservation_sql="$2"
[ -d "$migration_dir" ] || { echo "Migration directory is missing" >&2; exit 2; }
[ -r "$preservation_sql" ] && [ -s "$preservation_sql" ] || { echo "Reading preservation SQL is missing or empty" >&2; exit 2; }

set -- "$migration_dir"/*.sql
[ -f "$1" ] || { echo "Migration directory contains no SQL files" >&2; exit 2; }
for file do
  [ -r "$file" ] && [ -s "$file" ] || { echo "Unreadable or empty migration" >&2; exit 2; }
  version="${file##*/}"
  case "$version" in
    *[!a-zA-Z0-9_.-]*|[!0-9]*) echo "Invalid migration version name" >&2; exit 2 ;;
  esac
done

cat <<'SQL'
-- One connection owns the lock, ledger decisions and migration transactions.
SET search_path = public;
SELECT pg_advisory_lock(77160485, 1);
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
SQL
for file do
  version="${file##*/}"
  printf "SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version='%s') AS apply_migration \\gset\n" "$version"
  printf '%s\n' '\if :apply_migration' "\\echo APPLY $version" 'BEGIN;'
  case "$version" in
    047_consolidate_reading_state_rc482.sql|048_rc483_current_baseline.sql)
      cat "$preservation_sql"
      printf '\n'
      ;;
  esac
  cat "$file"
  printf "\nINSERT INTO schema_migrations(version) VALUES ('%s');\n" "$version"
  printf '%s\n' 'COMMIT;' '\else' "\\echo SKIP $version" '\endif'
done
printf '%s\n' 'SELECT pg_advisory_unlock(77160485, 1);'
