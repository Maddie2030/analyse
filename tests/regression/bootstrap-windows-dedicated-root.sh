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
grep -Fxq 'MREADER_DB_PROTECTION_ROOT=C:/mreader/database-protection' .env || {
  echo 'preflight: dedicated Windows database-protection root not persisted' >&2
  exit 10
}
PREFLIGHT
chmod +x "$TMP/app/scripts/bootstrap.sh" "$TMP/app/scripts/preflight.sh" "$TMP/app/scripts/hybrid/adopt-existing-stateful-volumes.sh"
cat > "$TMP/bin/uname" <<'UNAME'
#!/usr/bin/env bash
printf '%s\n' 'MINGW64_NT-10.0-19045'
UNAME
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
chmod +x "$TMP/bin/uname" "$TMP/bin/docker"
if ! (
  cd "$TMP/app"
  TERM=dumb PATH="$TMP/bin:$PATH" HOME='/odd/git-bash/home' USERPROFILE='not-a-drive-path' MREADER_DB_PROTECTION_ROOT='' ./scripts/bootstrap.sh >"$TMP/bootstrap.log" 2>&1
); then
  cat "$TMP/bootstrap.log" >&2
  exit 1
fi
grep -q 'Created .env from .env.example' "$TMP/bootstrap.log" || {
  cat "$TMP/bootstrap.log" >&2
  echo 'bootstrap did not create .env' >&2
  exit 1
}
grep -Fxq 'MREADER_DB_PROTECTION_ROOT=C:/mreader/database-protection' "$TMP/app/.env" || {
  cat "$TMP/bootstrap.log" >&2
  echo 'bootstrap did not persist the dedicated Windows recovery root' >&2
  exit 1
}

# A stale process-level value from an earlier shell/session must not override the
# dedicated fresh-install Windows root after bootstrap has just created .env.
rm -f "$TMP/app/.env"
rm -rf /c/mreader/database-protection 2>/dev/null || true
if ! (
  cd "$TMP/app"
  TERM=dumb PATH="$TMP/bin:$PATH" HOME='/odd/git-bash/home' USERPROFILE='not-a-drive-path' \
    MREADER_DB_PROTECTION_ROOT='/not/a/windows/drive/path' \
    ./scripts/bootstrap.sh >"$TMP/bootstrap-stale-env.log" 2>&1
); then
  cat "$TMP/bootstrap-stale-env.log" >&2
  exit 1
fi
grep -Fxq 'MREADER_DB_PROTECTION_ROOT=C:/mreader/database-protection' "$TMP/app/.env" || {
  cat "$TMP/bootstrap-stale-env.log" >&2
  echo 'bootstrap allowed stale process recovery root to defeat fresh dedicated Windows root' >&2
  exit 1
}

echo 'bootstrap Windows dedicated recovery-root regression: PASS'
