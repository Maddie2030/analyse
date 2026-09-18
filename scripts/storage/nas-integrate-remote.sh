#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
[[ -f .env ]] || { echo 'ERROR: .env is required.' >&2; exit 2; }
command -v ssh >/dev/null 2>&1 || { echo 'ERROR: OpenSSH client (ssh) is required for remote NAS verification.' >&2; exit 2; }
get(){ awk -F= -v k="$1" '$1==k{sub(/^[^=]*=/,"");print;exit}' .env | tr -d '\r'; }
host="$(get NAS_SEAWEEDFS_HOST)"; port="$(get NAS_SSH_PORT)"; user="$(get NAS_SSH_USER)"
backup_path="$(get POSTGRES_BACKUP_NAS_PATH)"
port="${port:-22}"; backup_path="${backup_path:-backups/mreader/postgres}"
[[ -n "$host" ]] || { echo 'ERROR: NAS_SEAWEEDFS_HOST is missing.' >&2; exit 2; }
[[ -n "$user" ]] || { echo 'ERROR: NAS_SSH_USER is missing; set only the NAS login name, never a password.' >&2; exit 2; }
[[ "$port" =~ ^[0-9]+$ ]] || { echo 'ERROR: NAS_SSH_PORT must be numeric.' >&2; exit 2; }
[[ "$backup_path" == backups/* && "$backup_path" != *'..'* ]] || { echo 'ERROR: invalid POSTGRES_BACKUP_NAS_PATH.' >&2; exit 2; }
echo "Running non-disruptive storage verification on ${user}@${host} ..."
ssh -p "$port" -T -- "${user}@${host}" "bash -s -- '$backup_path'" < "$ROOT/scripts/storage/nas-verify-standalone.sh"
