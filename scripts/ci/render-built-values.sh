#!/bin/sh
set -eu
src="${1:-.ci-artifacts/images.env}"
out="${2:-.ci-artifacts/built-values.yaml}"
: "${MREADER_REGISTRY:?MREADER_REGISTRY is required}"
[ -f "$src" ] || { echo "missing image manifest: $src" >&2; exit 2; }
mkdir -p "$(dirname "$out")"
key_for(){
  case "$1" in
    auth-service) echo authService;; catalog-go) echo catalogGo;; reader-go) echo readerGo;;
    progress-go) echo progressGo;; social-ts) echo socialTs;; scraper-service) echo scraperService;;
    image-service) echo imageService;; thumbnail-transformer) echo thumbnailTransformer;;
    outbox-relay) echo outboxRelay;; notification-worker) echo notificationWorker;; realtime-go) echo realtimeGo;;
    frontend) echo frontend;; migrate) echo migrate;; api-tests) echo apiTests;; browser-tests) echo browserTests;;
    *) echo "unknown image component: $1" >&2; return 2;;
  esac
}
{
  printf 'global:\n  imageRegistry: "%s"\nimages:\n' "${MREADER_REGISTRY%/}"
  while IFS='=' read -r component ref; do
    [ -n "$component" ] || continue
    key="$(key_for "$component")"
    repo_digest="${ref#*@}"
    case "$ref" in *@*) ;; *) echo "invalid immutable image ref: $ref" >&2; exit 2;; esac
    repo="${ref%@*}"; repo="${repo##*/}"
    printf '  %s:\n    repository: "%s"\n    tag: ""\n    digest: "%s"\n' "$key" "$repo" "$repo_digest"
  done < "$src"
} > "$out"
printf '%s\n' "$out"
