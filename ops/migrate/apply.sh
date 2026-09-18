#!/bin/sh
set -eu
umask 077
runner_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
migration_script="$(mktemp "${TMPDIR:-/tmp}/mreader-migrations.XXXXXXXX")"
trap 'rm -f "$migration_script"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
sh "$runner_dir/render.sh" "${MREADER_MIGRATIONS_DIR:-/migrations}" \
  "${MREADER_READING_PRESERVATION_SQL:-/migration-safety/preserve-reading-evidence.sql}" >"$migration_script"
# ON_ERROR_STOP terminates the connection on failure, releasing the session lock
# and rolling back the active migration together with its ledger write.
psql -X -v ON_ERROR_STOP=1 "$@" --file="$migration_script"
