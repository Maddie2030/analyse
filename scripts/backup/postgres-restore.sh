#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"
[[ -f .env ]] || { echo "ERROR: .env is required." >&2; exit 2; }
MREADER_DB_PROTECTION_ROOT="$(bash "$ROOT/scripts/env/resolve-db-protection-root.sh" .env)"
export MREADER_DB_PROTECTION_ROOT
bash "$ROOT/scripts/env/migrate-known-settings.sh" .env
TARGET="${1:-latest}"
# Canonical selectors: latest | latest-snapshot | opaque bkp_[0-9a-f]{24} public recovery id.
ASSUME=false
[[ "${2:-}" == "--yes" || "${2:-}" == "-y" || "${1:-}" == "--yes" ]] && ASSUME=true
if [[ "$TARGET" == "--yes" || "$TARGET" == "-y" ]]; then TARGET=latest; fi
case "$TARGET" in
  latest|latest-snapshot|bkp_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "ERROR: restore selector must be 'latest', 'latest-snapshot', or an opaque bkp_<24 hex> recovery id." >&2; exit 2 ;;
esac
REQUEST_JSON="$(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml run --rm backup_agent resolve-restore-request "$TARGET")" \
  || { echo "ERROR: restore selector '$TARGET' could not be resolved to a verified recovery point." >&2; exit 2; }
REQUEST_FIELDS_RAW="$("$PYTHON_RUNTIME" - "$REQUEST_JSON" <<'PY'
import json
import sys

try:
    payload = json.loads(sys.argv[1])
except (IndexError, json.JSONDecodeError) as exc:
    raise SystemExit(f"invalid restore request JSON: {exc}")

for key in ("public_id", "installation_fingerprint", "restore_generation", "sha256"):
    value = payload.get(key, "")
    if value is None:
        value = ""
    print(value)
PY
)" || { echo "ERROR: backup agent returned unreadable restore-control JSON." >&2; exit 2; }
mapfile -t REQUEST_FIELDS <<<"$REQUEST_FIELDS_RAW"
PUBLIC_ID="${REQUEST_FIELDS[0]:-}"
INSTALLATION_FINGERPRINT="${REQUEST_FIELDS[1]:-}"
RESTORE_GENERATION="${REQUEST_FIELDS[2]:-}"
SOURCE_SHA256="${REQUEST_FIELDS[3]:-}"
[[ "$PUBLIC_ID" =~ ^bkp_[0-9a-f]{24}$ && "$INSTALLATION_FINGERPRINT" =~ ^inst_[0-9a-f]{16}$ \
   && "$RESTORE_GENERATION" =~ ^[0-9]+$ && "$RESTORE_GENERATION" -ge 1 && "$SOURCE_SHA256" =~ ^[0-9a-f]{64}$ ]] \
  || { echo "ERROR: backup agent returned an invalid restore-control request." >&2; exit 2; }
CONFIRMATION="RESTORE ${PUBLIC_ID} ON ${INSTALLATION_FINGERPRINT} GEN ${RESTORE_GENERATION}"
if ! $ASSUME; then
  echo "DANGER: this replaces the current PostgreSQL database from verified recovery point '$PUBLIC_ID'."
  echo "The restore engine will re-check the exact source hash, installation fingerprint, and generation immediately before cutover."
  printf 'Type %s to continue: ' "$CONFIRMATION"
  read -r ans
  [[ "$ans" == "$CONFIRMATION" ]] || { echo "Restore cancelled."; exit 3; }
fi
ctx="$(kubectl config current-context 2>/dev/null || true)"
[[ "$ctx" == "docker-desktop" ]] || { echo "ERROR: kubectl context must be docker-desktop (got '$ctx')." >&2; exit 2; }

echo "==> Stopping background backup scheduler during restore"
docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml stop backup_agent >/dev/null 2>&1 || true

echo "==> Quiescing Kubernetes database clients"
kubectl delete -f deploy/docker-desktop-hybrid/user-keda.yaml --ignore-not-found=true --wait=true >/dev/null 2>&1 || true
kubectl delete -f deploy/docker-desktop-hybrid/admin-keda.yaml --ignore-not-found=true --wait=true >/dev/null 2>&1 || true
kubectl delete -f deploy/docker-desktop-hybrid/user-hpa.yaml --ignore-not-found=true --wait=true >/dev/null 2>&1 || true
kubectl -n mreader-user scale deployment --all --replicas=0
kubectl -n mreader-admin scale deployment --all --replicas=0
sleep 5

restore_failed=0
docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml run --rm backup_agent \
  restore-public-id "$PUBLIC_ID" "$INSTALLATION_FINGERPRINT" "$RESTORE_GENERATION" "$SOURCE_SHA256" || restore_failed=1
if (( restore_failed )); then
  echo "ERROR: database restore failed; application remains quiesced for safety." >&2
  echo "Inspect with ./db-backup.sh status and retry the restore. Do not run hybrid-up until the DB state is understood." >&2
  exit 5
fi

echo "==> Resuming through canonical P09.4 deployment gate"
if ! bash "$ROOT/scripts/hybrid/deploy.sh"; then
  echo "ERROR: database restore completed, but canonical application resume failed; application remains quiesced for safety." >&2
  echo "Resolve the P09.4 readiness/deployment failure before restoring autoscaling or application traffic." >&2
  exit 6
fi

echo "Database restore completed and canonical application resume verified from: $PUBLIC_ID"
echo "Both logical .dump backups and physical snapshot .tar backups use the same staged validation + pre-restore safety backup + atomic cutover path."
