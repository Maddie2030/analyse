#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
MODE="${1:-nas}"
COMPOSE_FILE="deploy/compose/docker-compose.${MODE}.yml"
[[ -f "$COMPOSE_FILE" ]] || COMPOSE_FILE="deploy/compose/docker-compose.yml"
VOLUME_NAME="$(sed -n 's/^SCRAPER_STAGING_VOLUME_NAME=//p' .env 2>/dev/null | tail -n1 | tr -d '\r')"
VOLUME_NAME="${VOLUME_NAME:-mreader_scraper_staging}"

echo "Compose: $COMPOSE_FILE"
echo "Configured scraper staging volume: $VOLUME_NAME"
if docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
  docker volume inspect "$VOLUME_NAME" --format 'volume={{.Name}} driver={{.Driver}} mountpoint={{.Mountpoint}}'
else
  echo "volume not created yet"
fi

for svc in scraper_service scraper_batch_worker scraper_series_worker lifecycle_worker; do
  cid="$(docker compose -f "$COMPOSE_FILE" ps -q "$svc" 2>/dev/null || true)"
  if [[ -z "$cid" ]]; then
    echo "$svc: not running"
    continue
  fi
  echo
  echo "[$svc]"
  docker inspect "$cid" --format '{{range .Mounts}}{{if eq .Destination "/var/lib/mreader/scraper-staging"}}{{println "type=" .Type " name=" .Name " source=" .Source " container=" .Destination}}{{end}}{{end}}'
  docker compose -f "$COMPOSE_FILE" exec -T "$svc" sh -lc 'python - <<"PY"
from pathlib import Path
import os
p=Path("/var/lib/mreader/scraper-staging")
marker=p/".mreader-staging-spool-id"
print("uid_gid=", f"{os.getuid()}:{os.getgid()}")
print("root=", p.resolve())
try:
    st=p.stat()
    print("root_owner=", f"{st.st_uid}:{st.st_gid}")
    print("root_mode=", oct(st.st_mode & 0o7777))
except Exception as exc:
    print("root_stat_error=", repr(exc))
print("writable=", os.access(p, os.W_OK))
try:
    print("spool_id=", marker.read_text().strip() if marker.exists() else "MISSING")
except Exception as exc:
    print("spool_id_error=", repr(exc))
print("files=", sum(1 for x in p.rglob("*") if x.is_file()))
PY'
done
