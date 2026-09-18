#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/env/env-lib.sh"
ENV_FILE="${1:-.env}"
[[ -f "$ENV_FILE" ]] || { echo "ERROR: env file not found: $ENV_FILE" >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required for stateful-volume adoption." >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "ERROR: Docker Engine is not ready." >&2; exit 2; }

probe_image="${MREADER_VOLUME_PROBE_IMAGE:-postgres:16.10-alpine3.22}"
prefer_legacy="${MREADER_PREFER_LEGACY_STATEFUL_VOLUMES:-true}"

volume_exists() { docker volume inspect "$1" >/dev/null 2>&1; }
volume_nonempty() {
  local volume="$1"
  volume_exists "$volume" || return 1
  docker run --rm --network none -v "$volume:/probe:ro" "$probe_image" sh -ceu '
    first="$(find /probe -mindepth 1 -maxdepth 2 -print -quit 2>/dev/null || true)"
    [ -n "$first" ]
  ' >/dev/null 2>&1
}
postgres_volume_valid() {
  local volume="$1"
  volume_exists "$volume" || return 1
  docker run --rm --network none -v "$volume:/probe:ro" "$probe_image" sh -ceu '
    test -f /probe/PG_VERSION
    major="$(cat /probe/PG_VERSION)"
    case "$major" in 16|17) ;; *) exit 2;; esac
    test -d /probe/base
    test -d /probe/global
  ' >/dev/null 2>&1
}

backup_env_once() {
  local stamp backup
  stamp="$(date +%Y%m%d-%H%M%S)"
  backup="${ENV_FILE}.before-stateful-adoption.${stamp}"
  cp -a "$ENV_FILE" "$backup"
  chmod 600 "$backup" 2>/dev/null || true
  echo "$backup"
}

select_volume() {
  local key="$1" canonical="$2" legacy="$3" kind="$4" configured c_exists l_exists c_live l_live selected
  configured="$(env_get "$ENV_FILE" "$key")"
  if [[ -n "$configured" ]]; then
    if [[ "$configured" == "$legacy" || "$configured" != "$canonical" || "$prefer_legacy" != true ]]; then
      echo "$key already pinned to '$configured'."
      return 0
    fi
    echo "$key currently uses canonical default '$canonical'; checking for populated legacy upgrade data."
  fi

  c_exists=false; l_exists=false; c_live=false; l_live=false
  volume_exists "$canonical" && c_exists=true
  volume_exists "$legacy" && l_exists=true

  if [[ "$kind" == postgres ]]; then
    postgres_volume_valid "$canonical" && c_live=true || true
    postgres_volume_valid "$legacy" && l_live=true || true

    if $l_live; then
      # Upgrade continuity rule: the populated legacy PGDATA volume is the
      # authoritative source during this recovery phase. A newly initialized
      # canonical volume must never shadow it just because both are valid
      # PostgreSQL clusters. Operators can opt out by setting
      # MREADER_PREFER_LEGACY_STATEFUL_VOLUMES=false or explicitly pinning a
      # different volume before bootstrap.
      selected="$legacy"
      $c_live && echo "WARN: both PostgreSQL volumes are valid; preferring legacy volume '$legacy' for upgrade continuity." >&2 || true
    elif $c_live; then
      selected="$canonical"
    elif $l_exists && ! $c_exists; then
      selected="$legacy"
    else
      selected="$canonical"
    fi
  else
    volume_nonempty "$canonical" && c_live=true || true
    volume_nonempty "$legacy" && l_live=true || true

    # Non-PostgreSQL legacy volumes are upgrade state, not catalog candidates.
    # Prefer any populated legacy generation instead of blocking because a
    # bootstrap-created canonical volume also contains files.
    if $l_live; then
      selected="$legacy"
      $c_live && echo "WARN: both $key volumes contain data; preferring legacy volume '$legacy' for upgrade continuity." >&2 || true
    elif $c_live; then
      selected="$canonical"
    elif $l_exists && ! $c_exists; then
      selected="$legacy"
    else
      selected="$canonical"
    fi
  fi

  if [[ -z "${ENV_BACKUP_CREATED:-}" ]]; then
    ENV_BACKUP_CREATED="$(backup_env_once)"
    export ENV_BACKUP_CREATED
  fi
  env_set "$ENV_FILE" "$key" "$selected"
  echo "$key=$selected"
}

select_volume HYBRID_PGDATA_VOLUME_NAME mreader_pgdata mreader-hybrid-stateful_pgdata postgres
select_volume HYBRID_REDIS_VOLUME_NAME mreader_redis_data mreader-hybrid-stateful_redis_data generic
select_volume HYBRID_RABBITMQ_VOLUME_NAME mreader_rabbitmq_data mreader-hybrid-stateful_rabbitmq_data generic
select_volume HYBRID_IMAGE_CACHE_VOLUME_NAME mreader_image_cache mreader-hybrid-stateful_image_cache generic
# PostgreSQL recovery now uses the explicit host-home bind mount. Older backup
# spool volumes are left untouched for deliberate recovery/import inspection.

if [[ -n "${ENV_BACKUP_CREATED:-}" ]]; then
  echo "Stateful volume ownership recorded in $ENV_FILE (previous env: $ENV_BACKUP_CREATED)."
else
  echo "Stateful volume ownership was already explicit; no changes required."
fi
