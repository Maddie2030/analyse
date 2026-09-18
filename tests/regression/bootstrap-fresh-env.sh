#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/app/scripts/hybrid" "$TMP/app/scripts/env" "$TMP/bin"
cp "$ROOT/scripts/bootstrap.sh" "$TMP/app/scripts/bootstrap.sh"
cp "$ROOT/scripts/hybrid/adopt-existing-stateful-volumes.sh" "$TMP/app/scripts/hybrid/adopt-existing-stateful-volumes.sh"
cp "$ROOT/scripts/env/env-lib.sh" "$TMP/app/scripts/env/env-lib.sh"
cp "$ROOT/scripts/env/db-protection-root.sh" "$TMP/app/scripts/env/db-protection-root.sh"
cp "$ROOT/scripts/env/resolve-db-protection-root.sh" "$TMP/app/scripts/env/resolve-db-protection-root.sh"
cp "$ROOT/.env.example" "$TMP/app/.env.example"
printf '%s\n' '1.3.0-rc4.84' > "$TMP/app/VERSION"
cat > "$TMP/app/scripts/preflight.sh" <<'PREFLIGHT'
#!/usr/bin/env bash
set -euo pipefail
[[ -f .env ]] || { echo 'preflight: .env missing' >&2; exit 9; }
grep -q '^HYBRID_PGDATA_VOLUME_NAME=mreader_pgdata$' .env || { echo 'preflight: volume ownership not recorded' >&2; exit 10; }
PREFLIGHT
chmod +x "$TMP/app/scripts/bootstrap.sh" "$TMP/app/scripts/preflight.sh" "$TMP/app/scripts/hybrid/adopt-existing-stateful-volumes.sh"
cat > "$TMP/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  compose)
    [[ "${2:-}" == version ]] && exit 0
    ;;
  info)
    exit 0
    ;;
  volume)
    [[ "${2:-}" == inspect ]] && exit 1
    ;;
  run)
    exit 1
    ;;
esac
exit 0
DOCKER
chmod +x "$TMP/bin/docker"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    if command -v cygpath >/dev/null 2>&1; then
      RECOVERY_ROOT="$(cygpath -m "$TMP/recovery with spaces")"
    else
      # Keeps the fixture runnable under a simulated Windows uname on non-Windows CI.
      RECOVERY_ROOT='C:/mreader/bootstrap-fresh-env-test/recovery with spaces'
    fi
    ;;
  *)
    RECOVERY_ROOT="$TMP/recovery with spaces"
    ;;
esac
if ! (
  cd "$TMP/app"
  TERM=dumb PATH="$TMP/bin:$PATH" MREADER_DB_PROTECTION_ROOT="$RECOVERY_ROOT" ./scripts/bootstrap.sh >"$TMP/bootstrap.log" 2>&1
); then
  cat "$TMP/bootstrap.log" >&2
  exit 1
fi
[[ -f "$TMP/app/.env" ]] || { cat "$TMP/bootstrap.log" >&2; echo 'bootstrap did not create .env' >&2; exit 1; }
grep -q 'Created .env from .env.example' "$TMP/bootstrap.log" || { cat "$TMP/bootstrap.log" >&2; echo 'bootstrap did not report env creation' >&2; exit 1; }
grep -q '^HYBRID_PGDATA_VOLUME_NAME=mreader_pgdata$' "$TMP/app/.env" || { cat "$TMP/bootstrap.log" >&2; echo 'bootstrap did not adopt canonical pg volume after env creation' >&2; exit 1; }
grep -Fxq "MREADER_DB_PROTECTION_ROOT=$RECOVERY_ROOT" "$TMP/app/.env" || { cat "$TMP/bootstrap.log" >&2; echo 'bootstrap did not persist the explicit recovery root' >&2; exit 1; }
echo 'bootstrap fresh-env regression: PASS'
