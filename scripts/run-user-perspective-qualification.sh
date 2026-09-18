#!/usr/bin/env bash
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ADMIN_USERNAME="${MREADER_TEST_ADMIN_USERNAME:-}"
ADMIN_EMAIL="${MREADER_TEST_ADMIN_EMAIL:-mreader.diagnostics.admin@gmail.com}"
ADMIN_PASSWORD="${MREADER_TEST_ADMIN_PASSWORD:-}"
SERIES_URL="${MREADER_DIAGNOSTICS_SERIES_URL:-}"
CHAPTER_URL="${MREADER_DIAGNOSTICS_CHAPTER_URL:-}"
KEEP_DATA=0

while (($#)); do
  case "$1" in
    --admin-username) shift; ADMIN_USERNAME="${1:?username required}" ;;
    --admin-email) shift; ADMIN_EMAIL="${1:?email required}" ;;
    --admin-password) shift; ADMIN_PASSWORD="${1:?password required}" ;;
    --scraper-series-url) shift; SERIES_URL="${1:?URL required}" ;;
    --scraper-chapter-url) shift; CHAPTER_URL="${1:?URL required}" ;;
    --keep-test-data) KEEP_DATA=1 ;;
    -h|--help)
      cat <<'HELP'
Usage: ./test-mreader.sh --user-800 [qualification options]

Options:
  --admin-username USER          disposable admin username used by API + browser tests
  --admin-email EMAIL            disposable admin email (default: diagnostics address)
  --admin-password PASS          disposable admin password used by API + browser tests
  --scraper-series-url URL       real public series URL for scraper discovery/API/UI tests
  --scraper-chapter-url URL      optional real chapter URL for chapter staging tests
  --keep-test-data               retain disposable diagnostic data where supported

For shell-history safety you may set MREADER_TEST_ADMIN_USERNAME,
MREADER_TEST_ADMIN_PASSWORD, and MREADER_DIAGNOSTICS_SERIES_URL instead of
passing credentials on the command line.

The run executes static regressions, inventories every React route/clickable
access point, then launches the full Dockerized diagnostics stack: complete API
functional/integration tests, 139-route coverage audit, PostgreSQL permission
matrix, user/admin gateway boundary matrix, real external scraper journeys, and
Playwright user/admin E2E. It writes a canonical 800-case ledger but fails on
ANY failure in the larger executed suite.
HELP
      exit 0 ;;
    *) echo "ERROR: unsupported qualification option: $1" >&2; exit 2 ;;
  esac
  shift
done

[[ -n "$ADMIN_USERNAME" ]] || { echo 'ERROR: disposable admin username is required (--admin-username or MREADER_TEST_ADMIN_USERNAME).' >&2; exit 2; }
[[ -n "$ADMIN_PASSWORD" ]] || { echo 'ERROR: disposable admin password is required (--admin-password or MREADER_TEST_ADMIN_PASSWORD).' >&2; exit 2; }
[[ -n "$SERIES_URL" ]] || { echo 'ERROR: real scraper series URL is required (--scraper-series-url or MREADER_DIAGNOSTICS_SERIES_URL).' >&2; exit 2; }

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OUT="$ROOT/test-results/user-qualification/$RUN_ID"
mkdir -p "$OUT/logs" "$OUT/ui-access"
printf 'run_id=%s\nversion=%s\n' "$RUN_ID" "$(tr -d '\r\n' < VERSION)" > "$OUT/run.env"

export MREADER_TEST_ADMIN_USERNAME="$ADMIN_USERNAME"
export MREADER_TEST_ADMIN_EMAIL="$ADMIN_EMAIL"
export MREADER_TEST_ADMIN_PASSWORD="$ADMIN_PASSWORD"
export MREADER_BROWSER_ADMIN_USERNAME="$ADMIN_USERNAME"
export MREADER_BROWSER_ADMIN_EMAIL="$ADMIN_EMAIL"
export MREADER_BROWSER_ADMIN_PASSWORD="$ADMIN_PASSWORD"
export MREADER_DIAGNOSTICS_SERIES_URL="$SERIES_URL"
[[ -n "$CHAPTER_URL" ]] && export MREADER_DIAGNOSTICS_CHAPTER_URL="$CHAPTER_URL"

phase_table="$OUT/phases.tsv"
printf 'phase\tstatus\texit_code\n' > "$phase_table"
record(){ local phase="$1" rc="$2"; local status=PASS; [[ "$rc" -eq 0 ]] || status=FAIL; printf '%s\t%s\t%s\n' "$phase" "$status" "$rc" >> "$phase_table"; }

# Drushti is an orchestration/development aid.  Qualification remains runnable
# even when invoked directly from the repository on a clean machine.
if command -v Drushti >/dev/null 2>&1; then
  set +e; Drushti doctor >"$OUT/logs/drushti-doctor.log" 2>&1; rc=$?; set -e
  record drushti-doctor "$rc"
else
  printf 'Drushti CLI not present; deterministic repository tests continue.\n' >"$OUT/logs/drushti-doctor.log"
  record drushti-doctor 0
fi

set +e
./scripts/run-regression-tests.sh --static 2>&1 | tee "$OUT/logs/static-regressions.log"
STATIC_RC=${PIPESTATUS[0]}
set -e
record static-regressions "$STATIC_RC"

set +e
MREADER_PYTHON_FORCE_DOCKER=1 "$ROOT/scripts/hybrid/python-runtime.sh" ./scripts/tests/ui-access-point-audit.py --out-dir "$OUT/ui-access" 2>&1 | tee "$OUT/logs/ui-access-audit.log"
UI_RC=${PIPESTATUS[0]}
set -e
record ui-access-audit "$UI_RC"

DIAG_ARGS=(--full --external --scraper-series-url "$SERIES_URL")
[[ -n "$CHAPTER_URL" ]] && DIAG_ARGS+=(--scraper-chapter-url "$CHAPTER_URL")
[[ "$KEEP_DATA" -eq 1 ]] && DIAG_ARGS+=(--keep-test-data)
set +e
./diagnose-mreader.sh "${DIAG_ARGS[@]}" 2>&1 | tee "$OUT/logs/diagnostics.log"
DIAG_RC=${PIPESTATUS[0]}
set -e
record diagnostics "$DIAG_RC"

DIAG_DIR="$(sed -nE 's/^(Output|Results):[[:space:]]+//p' "$OUT/logs/diagnostics.log" | head -1 | tr -d '\r')"
if [[ -z "$DIAG_DIR" || ! -d "$DIAG_DIR" ]]; then
  echo 'ERROR: could not locate diagnostics result directory from diagnostics output.' >&2
  record qualification-report 2
  exit 2
fi
printf 'diagnostic_dir=%s\n' "$DIAG_DIR" >> "$OUT/run.env"

set +e
MREADER_PYTHON_FORCE_DOCKER=1 "$ROOT/scripts/hybrid/python-runtime.sh" ./scripts/tests/build-user-perspective-report.py \
  "$DIAG_DIR" \
  --ui-audit-dir "$OUT/ui-access" \
  --out-dir "$OUT" \
  2>&1 | tee "$OUT/logs/qualification-report.log"
REPORT_RC=${PIPESTATUS[0]}
set -e
record qualification-report "$REPORT_RC"

# Preserve the complete diagnostic evidence next to the qualification ledger.
if [[ -f "$DIAG_DIR/REPORT_BUNDLE.zip" ]]; then
  cp -f "$DIAG_DIR/REPORT_BUNDLE.zip" "$OUT/DIAGNOSTIC_REPORT_BUNDLE.zip"
fi

cat <<EOF

MReader user-perspective qualification: $RUN_ID
Report: $OUT/REPORT.md
Canonical 800-case ledger: $OUT/qualification-800.tsv
Machine summary: $OUT/qualification-summary.json
Diagnostic baseline/retest bundle: $OUT/DIAGNOSTIC_REPORT_BUNDLE.zip
EOF

if [[ "$STATIC_RC" -ne 0 || "$UI_RC" -ne 0 || "$DIAG_RC" -ne 0 || "$REPORT_RC" -ne 0 ]]; then
  exit 1
fi
exit 0
