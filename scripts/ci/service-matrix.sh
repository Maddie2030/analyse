#!/usr/bin/env bash
set -euo pipefail
ALL=(auth-service catalog-go reader-go progress-go social-ts scraper-service image-service thumbnail-transformer outbox-relay notification-worker realtime-go frontend migrate api-tests browser-tests)
branch="${BRANCH_NAME:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)}"
if [[ "${FORCE_FULL_BUILD:-0}" == 1 || "$branch" == main || "$branch" == release/* || "$branch" == refs/tags/* || -n "${TAG_NAME:-}" ]]; then
  printf '%s\n' "${ALL[@]}"
  exit 0
fi
base="${CHANGE_TARGET:-}"
if [[ -n "$base" ]] && git show-ref --verify --quiet "refs/remotes/origin/$base"; then
  range="origin/$base...HEAD"
elif git rev-parse HEAD^ >/dev/null 2>&1; then
  range="HEAD^...HEAD"
else
  printf '%s\n' "${ALL[@]}"
  exit 0
fi
changed="$(git diff --name-only "$range")"
# Shared contracts/migrations/current deployment changes require a complete compatibility build.
if grep -Eq '^(shared/|contracts/|db/migrations/|deploy/compose/|deploy/docker-desktop-hybrid/|Jenkinsfile|scripts/ci/)' <<<"$changed"; then
  printf '%s\n' "${ALL[@]}"
  exit 0
fi
declare -A pick=()
while IFS= read -r path; do
  case "$path" in
    services/auth_service/*) pick[auth-service]=1 ;;
    services/catalog_go/*) pick[catalog-go]=1 ;;
    services/reader_go/*) pick[reader-go]=1 ;;
    services/progress_go/*) pick[progress-go]=1 ;;
    services/social_ts/*) pick[social-ts]=1 ;;
    services/scraper_service/*) pick[scraper-service]=1 ;;
    services/image_service/*) pick[image-service]=1 ;;
    services/thumbnail_transformer/*) pick[thumbnail-transformer]=1 ;;
    services/outbox_relay/*) pick[outbox-relay]=1 ;;
    services/notification_worker/*) pick[notification-worker]=1 ;;
    services/realtime_go/*) pick[realtime-go]=1 ;;
    frontend/*) pick[frontend]=1 ;;
    ops/migrate/*) pick[migrate]=1 ;;
    tests/api/*) pick[api-tests]=1 ;;
    tests/browser/*) pick[browser-tests]=1 ;;
  esac
done <<<"$changed"
# Test-tool images are intentionally change-driven on ordinary branches.
# They do not embed production service code, and feature-branch build-checks do
# not run the Kubernetes integration stage. Main/release/tag/full builds still
# include both through ALL above, where the integration gate actually uses them.
for c in "${ALL[@]}"; do [[ ${pick[$c]:-0} == 1 ]] && echo "$c"; done
