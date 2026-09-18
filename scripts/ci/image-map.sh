#!/bin/sh
set -eu
component="${1:-}"
case "$component" in
  auth-service) echo '.|services/auth_service/Dockerfile' ;;
  catalog-go) echo '.|services/catalog_go/Dockerfile' ;;
  reader-go) echo '.|services/reader_go/Dockerfile' ;;
  progress-go) echo '.|services/progress_go/Dockerfile' ;;
  social-ts) echo '.|services/social_ts/Dockerfile' ;;
  scraper-service) echo '.|services/scraper_service/Dockerfile' ;;
  image-service) echo '.|services/image_service/Dockerfile' ;;
  thumbnail-transformer) echo '.|services/thumbnail_transformer/Dockerfile' ;;
  outbox-relay) echo '.|services/outbox_relay/Dockerfile' ;;
  notification-worker) echo '.|services/notification_worker/Dockerfile' ;;
  realtime-go) echo '.|services/realtime_go/Dockerfile' ;;
  frontend) echo 'frontend|frontend/Dockerfile' ;;
  migrate) echo '.|ops/migrate/Dockerfile' ;;
  api-tests) echo '.|tests/api/Dockerfile' ;;
  browser-tests) echo '.|tests/browser/Dockerfile' ;;
  *) echo "unknown image component: $component" >&2; exit 2 ;;
esac
