#!/usr/bin/env bash
set -Eeuo pipefail
BASE_URL="${1:-${MREADER_BASE_URL:-https://overlord.seahorse-banded.ts.net}}"
BASE_URL="${BASE_URL%/}"

command -v curl >/dev/null 2>&1 || { echo 'curl unavailable; skipping public gateway smoke test' >&2; exit 2; }

printf '==> Public MReader gateway smoke test: %s\n' "$BASE_URL"
printf '  healthz: '
curl -fsS --connect-timeout 8 --max-time 15 "$BASE_URL/healthz" | grep -qi '^ok$' && echo OK

printf '  catalog: '
catalog="$(curl -fsS --connect-timeout 8 --max-time 20 "$BASE_URL/api/catalog/series?sort=updated&offset=0&limit=1")"
[[ "$catalog" == \[* ]] || { echo 'unexpected response'; exit 1; }
echo OK

printf '  auth/profile: '
status="$(curl -sS -o /tmp/mreader-android-auth-smoke.$$ -w '%{http_code}' --connect-timeout 8 --max-time 15 "$BASE_URL/api/auth/profile" || true)"
rm -f /tmp/mreader-android-auth-smoke.$$
case "$status" in
  200|401) echo "OK (HTTP $status)" ;;
  *) echo "FAILED (HTTP ${status:-none})"; exit 1 ;;
esac

printf '  image edge auth: '
status="$(curl -sS -o /tmp/mreader-android-image-smoke.$$ -w '%{http_code}' --connect-timeout 8 --max-time 15 "$BASE_URL/images/__mreader_android_probe__" || true)"
rm -f /tmp/mreader-android-image-smoke.$$
case "$status" in
  400|401|403|404) echo "OK (HTTP $status, protected route reachable)" ;;
  *) echo "FAILED (HTTP ${status:-none})"; exit 1 ;;
esac
