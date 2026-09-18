#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# The current Docker Desktop twin-plane always enables the admin Catalog writer.
# A 503 must therefore fail the suite rather than being accepted as a valid mode.
! grep -R -n 'status_code == 503' tests/api --include='*.py' >/dev/null || fail 'pytest still accepts disabled Catalog writes as success'

grep -q 'test_profile_account_identifiers_are_locked' tests/api/test_03_auth_session_profile.py || fail 'locked username/email regression missing'
grep -q 'assert_status(username, 409)' tests/api/test_03_auth_session_profile.py || fail 'username lock no longer asserted'
grep -q 'assert_status(email, 409)' tests/api/test_03_auth_session_profile.py || fail 'email lock no longer asserted'
grep -q 'test_reader_prev_next_navigation_boundaries' tests/api/test_06_reader_manifest_history.py || fail 'Reader navigation boundary regression missing'
grep -q 'test_public_curation_cache_invalidates_after_admin_mutations' tests/api/test_05_catalog_admin_writes.py || fail 'public curation invalidation regression missing'
grep -q 'test_diagnostic_redaction_scrubs_query_and_non_json_text' tests/api/test_00_harness_safety.py || fail 'diagnostic secret-redaction regression missing'
grep -q 'assert cur.fetchone()\[0\] == 1' tests/api/test_16_lifecycle_integrity.py || fail 'delete retry cleanup deduplication assertion missing'

printf '%s\n' 'API test contract/edge-case static regression PASSED'
