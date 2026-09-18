#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

fail(){ echo "ERROR: $*" >&2; exit 1; }

CONFT="tests/api/conftest.py"
OPS="tests/api/test_18_scraper_operations.py"
HELPERS="tests/api/helpers.py"
MEDIA="tests/api/test_13_media.py"
[[ -f "$CONFT" ]] || fail "missing $CONFT"
[[ -f "$OPS" ]] || fail "missing $OPS"
[[ -f "$HELPERS" ]] || fail "missing $HELPERS"
[[ -f "$MEDIA" ]] || fail "missing $MEDIA"

grep -q 'encoding_version, encoding_rows, encoding_columns, encoding_seed' "$CONFT" || fail "pytest page fixture is missing v4 encoding metadata"
grep -q 'VALUES (%s::uuid, %s, %s, 24, 32, 4, 1, 1, %s)' "$CONFT" || fail "pytest page fixture is not inserting valid identity v4 encoding metadata"
grep -q '_ACCOUNT_RUN_TOKEN' "$CONFT" || fail "pytest identity generator does not use a short Auth-safe run token"
grep -q 're.sub(r"\[\^A-Za-z0-9_\]"' "$CONFT" || fail "pytest identity suffix is not sanitized for Auth username constraints"
grep -q 'MREADER_TEST_HTTP_COOKIE_REPLAY' "$HELPERS" || fail "Docker pytest session does not replay Secure cookies for local HTTP diagnostics"
grep -q 'admin_user.session.post(' "$CONFT" || fail "seed content does not create canonical series through Catalog Admin API"
grep -q 'assert_status(response, 202)' "$MEDIA" || fail "Media compatibility tests still expect obsolete synchronous 201 semantics"
grep -q 'compatibility chapter media job' "$MEDIA" || fail "Media compatibility test does not wait for durable job completion"
grep -q 'state=acknowledged' "$OPS" || fail "scraper acknowledgement tests do not verify retained-history semantics"
grep -q 'history_retained' "$OPS" || fail "scraper acknowledgement tests do not verify history retention"
if grep -q 'SELECT COUNT(\*) FROM scraper_series_drafts WHERE id=%s::uuid' "$OPS"; then
  fail "scraper operation tests still require physical draft-row deletion"
fi

echo "pytest fixture/current-operation-contract regression PASSED"
