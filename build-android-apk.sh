#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_DIR="$ROOT_DIR/android"
DIST_DIR="$ROOT_DIR/dist"
IMAGE_NAME="mreader-android-builder:rc4.81-history-public-metrics"
GRADLE_CACHE_VOLUME="mreader-android-gradle-cache"
APK_NAME="Mreader-ver.1.1.0-debug.apk"
BASE_URL="${MREADER_BASE_URL:-https://overlord.seahorse-banded.ts.net}"
DOCKER_ROOT="$ROOT_DIR"
DOCKER_MEMORY="${MREADER_ANDROID_DOCKER_MEMORY:-3g}"
DOCKER_CPUS="${MREADER_ANDROID_DOCKER_CPUS:-2}"
FORCE_TOOLCHAIN_REBUILD="${MREADER_ANDROID_FORCE_TOOLCHAIN_REBUILD:-0}"

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

case "$(uname -s 2>/dev/null || true)" in
  MINGW*|MSYS*|CYGWIN*)
    command -v cygpath >/dev/null 2>&1 || die "cygpath is required when running from Git Bash/MSYS."
    DOCKER_ROOT="$(cygpath -w "$ROOT_DIR")"
    ;;
esac

command -v docker >/dev/null 2>&1 || die "Docker is required. Install/start Docker Desktop or Docker Engine, then rerun this script."
docker info >/dev/null 2>&1 || die "Docker daemon is not reachable. Start Docker and rerun this script."
[[ -f "$ANDROID_DIR/docker/Dockerfile" ]] || die "Missing android/docker/Dockerfile"
[[ -f "$ANDROID_DIR/settings.gradle.kts" ]] || die "Missing Android Gradle project"

mkdir -p "$DIST_DIR"
# Never leave a previous Android artifact looking like the result of a failed build.
rm -f "$DIST_DIR/$APK_NAME" "$DIST_DIR/$APK_NAME.sha256"

log "Running Android source/API integration audit"
"$ROOT_DIR/scripts/android-static-audit.sh"

log "Checking Android reader against the working web-reader contract"
"$ROOT_DIR/scripts/android-web-reader-contract-audit.sh"

if command -v curl >/dev/null 2>&1; then
  log "Probing the configured public MReader API from the host (informational)"
  if ! "$ROOT_DIR/scripts/android-public-gateway-smoke.sh" "$BASE_URL"; then
    printf 'WARNING: Host-side public API probe failed. The APK can still be built; use Android Settings -> Connection and tap refresh for a phone-side connectivity check.\n' >&2
  fi
fi

if [[ "$FORCE_TOOLCHAIN_REBUILD" == "1" ]] || ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  log "Building isolated Android toolchain image"
  DOCKER_BUILDKIT=1 docker build \
    --pull \
    --progress=plain \
    -t "$IMAGE_NAME" \
    -f "$ANDROID_DIR/docker/Dockerfile" \
    "$ANDROID_DIR/docker"
else
  log "Reusing cached Android toolchain image $IMAGE_NAME"
fi

log "Checking AndroidX/AAR metadata compatibility, compiling Kotlin, running unit tests, and building debug APK"
if [[ "$(uname -s 2>/dev/null || true)" == MINGW* || "$(uname -s 2>/dev/null || true)" == MSYS* || "$(uname -s 2>/dev/null || true)" == CYGWIN* ]]; then
  export MSYS_NO_PATHCONV=1
fi

docker run --rm \
  --memory="$DOCKER_MEMORY" \
  --cpus="$DOCKER_CPUS" \
  -e GRADLE_USER_HOME=/gradle-cache \
  -e MREADER_BASE_URL="$BASE_URL" \
  -v "$GRADLE_CACHE_VOLUME:/gradle-cache" \
  -v "$DOCKER_ROOT:/workspace" \
  -w /workspace/android \
  "$IMAGE_NAME" \
  bash -lc 'set -Eeuo pipefail; gradle --version; gradle --no-daemon --max-workers=2 --stacktrace :app:checkDebugAarMetadata :app:compileDebugKotlin :app:testDebugUnitTest :app:assembleDebug -PMREADER_BASE_URL="$MREADER_BASE_URL"' 

SOURCE_APK="$ANDROID_DIR/app/build/outputs/apk/debug/app-debug.apk"
[[ -f "$SOURCE_APK" ]] || die "Gradle completed but APK was not found at $SOURCE_APK"
cp -f "$SOURCE_APK" "$DIST_DIR/$APK_NAME"

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$DIST_DIR/$APK_NAME" | tee "$DIST_DIR/$APK_NAME.sha256"
fi

log "APK ready"
printf '%s\n' "$DIST_DIR/$APK_NAME"
