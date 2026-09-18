#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
FAKE="$TMP/bin"; mkdir -p "$FAKE"
ENVF="$TMP/app.env"
printf 'MREADER_DB_PROTECTION_ROOT=%s\n' "$TMP/recovery" > "$ENVF"
cat > "$FAKE/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "$*" == *'run --rm --no-deps --build backup_agent self-test' ]] || exit 97
printf '%s\n' "$MREADER_DB_PROTECTION_ROOT" >> "$DBP_TEST_CALLS"
echo 'fixture: owner self-test reached'
exit "${DBP_TEST_OWNER_EXIT:-0}"
SH
cat > "$FAKE/curl" <<'SH'
#!/usr/bin/env bash
touch "$DBP_TEST_UNEXPECTED"
exit 98
SH
cp "$FAKE/curl" "$FAKE/kubectl"
chmod +x "$FAKE/docker" "$FAKE/curl" "$FAKE/kubectl"
export DBP_TEST_CALLS="$TMP/calls" DBP_TEST_UNEXPECTED="$TMP/unexpected"
MREADER_DB_PROTECTION_ROOT="$TMP/recovery" PATH="$FAKE:$PATH" ./scripts/storage/backup-storage-doctor.sh "$ENVF" > "$TMP/pass.log"
grep -Fxq "$TMP/recovery" "$DBP_TEST_CALLS"
grep -q 'owner self-test reached' "$TMP/pass.log"
[[ ! -e "$DBP_TEST_UNEXPECTED" ]]
set +e
DBP_TEST_OWNER_EXIT=23 MREADER_DB_PROTECTION_ROOT="$TMP/recovery" PATH="$FAKE:$PATH" ./scripts/storage/backup-storage-doctor.sh "$ENVF" > "$TMP/fail.log" 2>&1
rc=$?
set -e
[[ "$rc" -eq 23 ]]
before="$(wc -l < "$DBP_TEST_CALLS")"
set +e
MREADER_DB_PROTECTION_ROOT="$TMP/different" PATH="$FAKE:$PATH" ./scripts/storage/backup-storage-doctor.sh "$ENVF" > "$TMP/conflict.log" 2>&1
rc=$?
set -e
[[ "$rc" -ne 0 ]]
[[ "$(wc -l < "$DBP_TEST_CALLS")" == "$before" ]]
echo 'storage doctor entrypoint fixture regression PASS (no live storage tested)'
