#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENT="$ROOT/scripts/backup/backup-agent.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"

cat > "$TMP/bin/jq" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
input="$(cat)"
# Test-only narrow stand-in for the production jq object validator/canonicalizer.
case "$input" in
  \{*\}) printf '%s\n' "$input" ;;
  *) exit 4 ;;
esac
SH
chmod +x "$TMP/bin/jq"

cat > "$TMP/bin/psql" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
result=''
while (($#)); do
  if [[ "$1" == '-v' && $# -ge 2 ]]; then
    shift
    case "$1" in result=*) result="${1#result=}" ;; esac
  fi
  shift || true
done
cat >/dev/null
count="$(cat "$FAKE_PSQL_COUNT" 2>/dev/null || echo 0)"
printf '%s\n' "$((count + 1))" > "$FAKE_PSQL_COUNT"
printf '%s' "$result" > "$FAKE_PSQL_CAPTURE"
exit "${FAKE_PSQL_EXIT:-0}"
SH
chmod +x "$TMP/bin/psql"

# Extract only the production function under test; sourcing the whole daemon would
# intentionally perform startup/self-test work.
eval "$(awk '/^operation_update\(\)\{/{f=1} f{print} f && /^}$/{exit}' "$AGENT")"
log(){ :; }
sleep(){ :; }
PATH="$TMP/bin:$PATH"
DB_HOST=db DB_PORT=5432 DB_USER=manhwa DB_NAME=manhwa
export FAKE_PSQL_CAPTURE="$TMP/result" FAKE_PSQL_COUNT="$TMP/count"

backup='mreader-manual-manhwa-2026-09-04_23-25-24_IST-v1.3.0-rc4.30-fa7cd8b2-admin-UPDATE-0.dump'
payload="{\"counts\":\"132,6841,173520\",\"backup\":\"$backup\"}"
operation_update '36a71501-f961-4513-acd3-61b27102f449' verified restore-drill-complete '' "$payload"
[[ "$(cat "$TMP/result")" == "$payload" ]] || { echo 'result JSON mutated before psql (extra-brace regression)' >&2; exit 1; }

: > "$TMP/result"; printf '0\n' > "$TMP/count"
operation_update '36a71501-f961-4513-acd3-61b27102f449' running claimed
[[ "$(cat "$TMP/result")" == '{}' ]] || { echo 'missing result must normalize to {}' >&2; exit 1; }

# Non-object result data is rejected before a database write.
printf '0\n' > "$TMP/count"
if operation_update '36a71501-f961-4513-acd3-61b27102f449' verified bad-result '' '[]'; then
  echo 'non-object operation result unexpectedly accepted' >&2
  exit 1
fi
[[ "$(cat "$TMP/count")" == '0' ]] || { echo 'invalid JSON reached psql' >&2; exit 1; }

# Ledger writes are not swallowed: 3 failed attempts must return failure.
printf '0\n' > "$TMP/count"
export FAKE_PSQL_EXIT=1
if operation_update '36a71501-f961-4513-acd3-61b27102f449' verified restore-drill-complete '' "$payload"; then
  echo 'failed ledger write was swallowed' >&2
  exit 1
fi
[[ "$(cat "$TMP/count")" == '3' ]] || { echo 'ledger update retry count is not 3' >&2; exit 1; }

echo 'database operation ledger runtime regression PASS'
