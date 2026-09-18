#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENTRYPOINT="$ROOT/scripts/docker/mreader-staging-entrypoint.sh"

fail(){ echo "FAIL: $*" >&2; exit 1; }
skip(){ echo "SKIP: $*" >&2; exit 77; }

# Always retain source-level coverage, even on Windows hosts where POSIX
# ownership semantics cannot be exercised directly.
sh -n "$ENTRYPOINT" || fail "staging entrypoint has invalid shell syntax"
grep -q 'repair_staging_permissions' "$ENTRYPOINT" || fail "permission repair function missing"
grep -q 'chown -R "$APP_UID:$APP_GID" "$STAGING_ROOT"' "$ENTRYPOINT" || fail "recursive drift repair missing"
grep -q 'chmod 0770 "$STAGING_ROOT"' "$ENTRYPOINT" || fail "staging root mode repair missing"
grep -q 'chmod 0660 "$marker"' "$ENTRYPOINT" || fail "marker mode repair missing"
grep -q 'exec gosu "$APP_UID:$APP_GID" "$@"' "$ENTRYPOINT" || fail "privilege drop missing"

run_direct_linux(){
  local tmp
  tmp="$(mktemp -d)"
  chmod 0755 "$tmp"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/spool"
  printf '%s\n' '11111111-1111-1111-1111-111111111111' > "$tmp/spool/.mreader-staging-spool-id"
  chown 0:0 "$tmp/spool" "$tmp/spool/.mreader-staging-spool-id"
  chmod 0755 "$tmp/spool"
  chmod 0600 "$tmp/spool/.mreader-staging-spool-id"

  SCRAPER_STAGING_ROOT="$tmp/spool" \
  MREADER_APP_UID=65534 \
  MREADER_APP_GID=65534 \
  "$ENTRYPOINT" sh -ec '
    test "$(id -u)" = 65534
    test "$(id -g)" = 65534
    test -r "$SCRAPER_STAGING_ROOT/.mreader-staging-spool-id"
    test -w "$SCRAPER_STAGING_ROOT"
    probe="$SCRAPER_STAGING_ROOT/.runtime-write-probe"
    printf ok > "$probe"
    rm -f "$probe"
  '

  [[ "$(stat -c %u "$tmp/spool")" == 65534 ]]
  [[ "$(stat -c %g "$tmp/spool")" == 65534 ]]
  [[ "$(stat -c %a "$tmp/spool")" == 770 ]]
  [[ "$(stat -c %u "$tmp/spool/.mreader-staging-spool-id")" == 65534 ]]
  [[ "$(stat -c %g "$tmp/spool/.mreader-staging-spool-id")" == 65534 ]]
  [[ "$(stat -c %a "$tmp/spool/.mreader-staging-spool-id")" == 660 ]]
}

resolve_scraper_image(){
  if [[ -n "${MREADER_SCRAPER_TEST_IMAGE:-}" ]]; then
    printf '%s\n' "$MREADER_SCRAPER_TEST_IMAGE"
    return 0
  fi
  awk '
    $1 == "scraper_service:" { in_service=1; next }
    in_service && $1 == "image:" { print $2; exit }
    in_service && /^[^[:space:]]/ { in_service=0 }
  ' "$ROOT/deploy/compose/docker-compose.hybrid-build.yml"
}

run_docker_linux(){
  command -v docker >/dev/null 2>&1 || skip "Linux ownership test requires Docker on this non-Linux/non-root host"
  docker info >/dev/null 2>&1 || skip "Docker Engine is unavailable for the Linux ownership test"

  local image volume
  image="$(resolve_scraper_image)"
  [[ -n "$image" ]] || skip "could not resolve scraper-service image tag"
  docker image inspect "$image" >/dev/null 2>&1 || skip "scraper image '$image' is not present locally; deploy/build the current release first"

  volume="mreader-staging-regression-${RANDOM}-$$"
  docker volume create "$volume" >/dev/null
  cleanup_volume(){ docker volume rm -f "$volume" >/dev/null 2>&1 || true; }
  trap cleanup_volume RETURN

  # Seed the exact historical failure shape as root inside a Linux named volume.
  docker run --rm --entrypoint sh -v "$volume:/spool" "$image" -ec '
    printf "%s\n" 11111111-1111-1111-1111-111111111111 > /spool/.mreader-staging-spool-id
    chown 0:0 /spool /spool/.mreader-staging-spool-id
    chmod 0755 /spool
    chmod 0600 /spool/.mreader-staging-spool-id
  '

  # Use the image's real ENTRYPOINT so repair + gosu are exercised exactly as
  # they run in Docker Desktop/Kubernetes.
  docker run --rm \
    -v "$volume:/var/lib/mreader/scraper-staging" \
    -e SCRAPER_STAGING_ROOT=/var/lib/mreader/scraper-staging \
    -e MREADER_APP_UID=65534 \
    -e MREADER_APP_GID=65534 \
    "$image" sh -ec '
      test "$(id -u)" = 65534
      test "$(id -g)" = 65534
      test -r "$SCRAPER_STAGING_ROOT/.mreader-staging-spool-id"
      test -w "$SCRAPER_STAGING_ROOT"
      probe="$SCRAPER_STAGING_ROOT/.runtime-write-probe"
      printf ok > "$probe"
      rm -f "$probe"
    '

  docker run --rm --entrypoint sh -v "$volume:/spool" "$image" -ec '
    test "$(stat -c %u /spool)" = 65534
    test "$(stat -c %g /spool)" = 65534
    test "$(stat -c %a /spool)" = 770
    test "$(stat -c %u /spool/.mreader-staging-spool-id)" = 65534
    test "$(stat -c %g /spool/.mreader-staging-spool-id)" = 65534
    test "$(stat -c %a /spool/.mreader-staging-spool-id)" = 660
  '
}

case "$(uname -s 2>/dev/null || echo unknown)" in
  Linux)
    if [[ "$(id -u)" == 0 ]] && command -v gosu >/dev/null 2>&1; then
      run_direct_linux
    else
      run_docker_linux
    fi
    ;;
  *)
    run_docker_linux
    ;;
esac

echo "staging entrypoint permission repair: PASS"
