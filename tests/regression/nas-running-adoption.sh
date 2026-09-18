#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
FAKE="$TMP/bin"; mkdir -p "$FAKE"
PROOF="$TMP/proof.json"
ENVF="$TMP/nas.env"
cat > "$ENVF" <<'ENV'
NAS_VOLUME_DATA_DIR=/srv/legacy/wrong-volume
NAS_FILER_DATA_DIR=/srv/legacy/wrong-filer
NAS_MASTER_DATA_DIR=/srv/legacy/wrong-master
POSTGRES_BACKUP_NAS_PATH=backups/mreader/postgres
NAS_SEAWEEDFS_PORT=9999
ENV

cat > "$FAKE/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  ps)
    printf '%s\n' mreader-seaweed-filer mreader-seaweed-volume-hdd mreader-seaweed-master
    ;;
  inspect)
    c="${2:-}"
    fmt="${4:-}"
    if [[ "$fmt" == *'project.working_dir'* ]]; then
      echo /home/maddie/mreader-seaweedfs
    elif [[ "$fmt" == *'.Destination "/data"'* ]]; then
      case "$c" in
        mreader-seaweed-volume-hdd) echo /srv/seaweed/hdd/volumes ;;
        mreader-seaweed-filer) echo /srv/seaweed/ssd/meta/filer ;;
        mreader-seaweed-master) echo /srv/seaweed/ssd/meta/master ;;
      esac
    fi
    ;;
  port)
    echo '0.0.0.0:8888'
    ;;
  *) exit 2 ;;
esac
SH
chmod +x "$FAKE/docker"

cat > "$FAKE/findmnt" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
path=''; field=''
while (($#)); do
  case "$1" in
    -T) path="$2"; shift 2 ;;
    -no) field="$2"; shift 2 ;;
    *) shift ;;
  esac
done
case "$path:$field" in
  /:SOURCE) echo /dev/mapper/ubuntu--vg-ubuntu--lv ;;
  /:TARGET) echo / ;;
  /:FSTYPE) echo ext4 ;;
  /srv/seaweed/hdd/volumes:SOURCE) echo /dev/sdb1 ;;
  /srv/seaweed/hdd/volumes:TARGET) echo /srv/seaweed/hdd ;;
  /srv/seaweed/hdd/volumes:FSTYPE) echo ext4 ;;
  /srv/seaweed/ssd/meta/filer:SOURCE|/srv/seaweed/ssd/meta/master:SOURCE) echo /dev/mapper/ubuntu--vg-seaweed--meta ;;
  /srv/seaweed/ssd/meta/filer:TARGET|/srv/seaweed/ssd/meta/master:TARGET) echo /srv/seaweed/ssd/meta ;;
  /srv/seaweed/ssd/meta/filer:FSTYPE|/srv/seaweed/ssd/meta/master:FSTYPE) echo ext4 ;;
  *) exit 1 ;;
esac
SH
chmod +x "$FAKE/findmnt"

cat > "$FAKE/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
upload=''; url=''
while (($#)); do
  case "$1" in
    -F)
      case "$2" in file=@*) upload="${2#file=@}" ;; esac
      shift 2 ;;
    -o) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
if [[ -n "$upload" && "$url" == *storage-location.json ]]; then
  cp "$upload" "$FAKE_PROOF_OUT"
fi
exit 0
SH
chmod +x "$FAKE/curl"

PATH="$FAKE:$PATH" FAKE_PROOF_OUT="$PROOF" \
  "$ROOT/ops/nas-seaweedfs/storage-contract.sh" "$ENVF" publish-running >"$TMP/out.log" 2>"$TMP/err.log"

[[ -s "$PROOF" ]]
jq -e '.verified == true' "$PROOF" >/dev/null
[[ "$(jq -r '.physical_volume_root' "$PROOF")" == '/srv/seaweed/hdd/volumes' ]]
[[ "$(jq -r '.mount_source' "$PROOF")" == '/dev/sdb1' ]]
[[ "$(jq -r '.filesystem' "$PROOF")" == 'ext4' ]]
[[ "$(jq -r '.runtime_mount_matches_config' "$PROOF")" == 'false' ]]
[[ "$(jq -r '.verification_source' "$PROOF")" == 'running-container-bind' ]]
grep -q 'No SeaweedFS data was moved or restarted' "$TMP/out.log"
grep -q 'runtime bind is authoritative' "$TMP/err.log"

echo 'NAS running-deployment adoption regression PASS'
