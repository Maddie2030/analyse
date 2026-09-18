#!/usr/bin/env bash
set -euo pipefail
environment="${1:-verification}"
images_file="${2:-.ci-artifacts/images.env}"
[[ -n "${AZURE_RELEASE_AUDIT_URL:-}" ]] || exit 0
: "${AZURE_RELEASE_AUDIT_TOKEN:?AZURE_RELEASE_AUDIT_TOKEN required when audit URL is configured}"
[[ -f "$images_file" ]] || { echo "images manifest not found: $images_file" >&2; exit 2; }
command -v jq >/dev/null 2>&1 || { echo 'jq is required by CI release audit' >&2; exit 2; }
images_json="$(jq -Rn '[inputs | select(length>0) | capture("^(?<key>[^=]+)=(?<value>.*)$") | {(.key): .value}] | add // {}' < "$images_file")"
payload="$(jq -cn \
  --arg environment "$environment" \
  --arg git_sha "${GIT_COMMIT:-unknown}" \
  --arg build "${BUILD_TAG:-unknown}" \
  --arg branch "${BRANCH_NAME:-}" \
  --argjson images "$images_json" \
  '{environment:$environment,git_sha:$git_sha,jenkins_build:$build,branch:$branch,images:$images,security_gates:"passed"}')"
if ! curl --fail --silent --show-error --max-time 15 \
  -H 'Content-Type: application/json' \
  -H "x-mreader-audit-token: $AZURE_RELEASE_AUDIT_TOKEN" \
  --data-binary "$payload" "$AZURE_RELEASE_AUDIT_URL" >/dev/null; then
  echo 'WARNING: Azure release-audit satellite unavailable; deployment remains authoritative in GitOps.' >&2
fi
