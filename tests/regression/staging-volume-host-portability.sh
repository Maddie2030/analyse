#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"

cat > "$TMP/bin/uname" <<'FAKE'
#!/usr/bin/env bash
echo 'MINGW64_NT-10.0-22631'
FAKE
cat > "$TMP/bin/docker" <<'FAKE'
#!/usr/bin/env bash
# Docker CLI may be installed but the engine may be stopped/unavailable.
exit 1
FAKE
chmod +x "$TMP/bin/uname" "$TMP/bin/docker"

set +e
PATH="$TMP/bin:$PATH" bash tests/regression/staging-volume-permissions.sh >"$TMP/out" 2>&1
rc=$?
set -e
[[ $rc -eq 77 ]] || { cat "$TMP/out" >&2; echo "FAIL: Windows/no-engine staging capability should SKIP(77), got $rc" >&2; exit 1; }
grep -q '^SKIP:' "$TMP/out" || { cat "$TMP/out" >&2; echo 'FAIL: staging capability skip was not explicit' >&2; exit 1; }
grep -q 'Docker Engine is unavailable' "$TMP/out" || { cat "$TMP/out" >&2; echo 'FAIL: skip reason did not identify Docker Engine capability' >&2; exit 1; }

echo 'staging Windows/no-Docker capability classification PASSED'
