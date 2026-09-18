#!/usr/bin/env bash
set -euo pipefail
umask 077

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  return 1
}

require_tools() {
  local tool
  for tool in jq sha256sum find realpath date stat sort mktemp; do
    command -v "$tool" >/dev/null 2>&1 || fail "required recovery-store tool is missing: $tool" || return 1
  done
}

valid_recovery_id() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]
}

valid_public_id() {
  [[ "$1" =~ ^bkp_[0-9a-f]{24}$ ]]
}

verify_bundle() {
  local supplied="$1" bundle recovery_id manifest type purpose artifact kind expected_names actual_names
  local created_at size checksum postgres_major mreader_version public_id
  [[ -d "$supplied" ]] || fail "recovery bundle is not a directory" || return 1
  [[ ! -L "$supplied" ]] || fail "recovery bundle must not be a symlink" || return 1
  bundle="$(realpath -e -- "$supplied")" || return 1
  [[ -z "$(find "$bundle" -mindepth 1 -type l -print -quit)" ]] || fail "recovery bundle contains a symlink" || return 1
  [[ -z "$(find "$bundle" -mindepth 1 -type d -print -quit)" ]] || fail "recovery bundle contains a nested directory" || return 1

  recovery_id="$(basename "$bundle")"
  valid_recovery_id "$recovery_id" || fail "invalid recovery identifier" || return 1
  manifest="$bundle/manifest.json"
  [[ -f "$manifest" && ! -L "$manifest" ]] || fail "recovery manifest is missing" || return 1
  jq -e 'type == "object" and .schema_version == 1 and .verification == "verified" and
         (.recovery_id | type == "string") and (.created_at | type == "string") and
         (.postgres_major | type == "number") and (.mreader_version | type == "string") and
         (.files | type == "array") and .checksums_file == "checksums.sha256"' \
    "$manifest" >/dev/null || fail "recovery manifest is invalid" || return 1
  [[ "$(jq -r '.recovery_id' "$manifest")" == "$recovery_id" ]] || fail "manifest recovery identifier does not match its bundle" || return 1

  type="$(jq -r '.type' "$manifest")"
  purpose="$(jq -r '.purpose' "$manifest")"
  case "$type:$purpose" in
    logical:automatic|logical:manual|logical:pre-upgrade|logical:pre-restore)
      artifact="database.dump"
      kind="logical_dump"
      expected_names=$'checksums.sha256\ndatabase.dump\nglobals.sql\nmanifest.json'
      [[ "$(jq -c '.files | sort' "$manifest")" == '["database.dump","globals.sql"]' ]] || fail "logical bundle file declaration is invalid" || return 1
      [[ "$(head -c 5 "$bundle/database.dump" 2>/dev/null || true)" == "PGDMP" ]] || fail "logical backup is not PostgreSQL custom format" || return 1
      ;;
    physical:snapshot)
      artifact="snapshot.tar"
      kind="physical_snapshot"
      expected_names=$'checksums.sha256\nmanifest.json\nsnapshot.tar'
      [[ "$(jq -c '.files | sort' "$manifest")" == '["snapshot.tar"]' ]] || fail "snapshot bundle file declaration is invalid" || return 1
      [[ -s "$bundle/snapshot.tar" ]] || fail "snapshot archive is empty" || return 1
      ;;
    *) fail "unsupported recovery bundle type or purpose" || return 1 ;;
  esac

  actual_names="$(
    find "$bundle" -mindepth 1 -maxdepth 1 -type f -print0 |
      while IFS= read -r -d '' item; do
        printf '%s\n' "${item##*/}"
      done | sort
  )"
  [[ "$actual_names" == "$expected_names" ]] || fail "recovery bundle contains missing or unexpected files" || return 1
  [[ -s "$bundle/checksums.sha256" ]] || fail "recovery checksums are missing" || return 1
  if ! awk '
      NF != 2 { exit 1 }
      $1 !~ /^[0-9a-f]{64}$/ { exit 1 }
      { name=$2; sub(/^\*/, "", name) }
      name !~ /^(database\.dump|globals\.sql|snapshot\.tar|manifest\.json)$/ { exit 1 }
      { seen[name]++ }
      END { for (name in seen) if (seen[name] != 1) exit 1 }
    ' "$bundle/checksums.sha256"; then
    fail "checksum manifest contains an unsafe or duplicate entry" || return 1
  fi
  case "$kind" in
    logical_dump)
      [[ "$(awk '{ name=$2; sub(/^\*/, "", name); print name }' "$bundle/checksums.sha256" | sort)" == $'database.dump\nglobals.sql\nmanifest.json' ]] || fail "logical checksum set is incomplete" || return 1
      ;;
    physical_snapshot)
      [[ "$(awk '{ name=$2; sub(/^\*/, "", name); print name }' "$bundle/checksums.sha256" | sort)" == $'manifest.json\nsnapshot.tar' ]] || fail "snapshot checksum set is incomplete" || return 1
      ;;
  esac
  (cd "$bundle" && sha256sum -c checksums.sha256 >/dev/null) || fail "recovery bundle checksum verification failed" || return 1

  created_at="$(jq -r '.created_at' "$manifest")"
  date -u -d "$created_at" +%s >/dev/null 2>&1 || fail "recovery creation timestamp is invalid" || return 1
  size="$(stat -c '%s' "$bundle/$artifact")"
  checksum="$(sha256sum "$bundle/$artifact" | awk '{print $1}')"
  public_id="bkp_$(printf 'local\0%s' "$recovery_id" | sha256sum | cut -c1-24)"
  postgres_major="$(jq -r '.postgres_major' "$manifest")"
  [[ "$postgres_major" == "16" ]] || fail "unsupported PostgreSQL major: $postgres_major" || return 1
  mreader_version="$(jq -r '.mreader_version' "$manifest")"
  [[ "$mreader_version" =~ ^[A-Za-z0-9._-]{1,128}$ ]] || fail "MReader version metadata is invalid" || return 1
  jq -cn \
    --arg recovery_id "$recovery_id" --arg public_id "$public_id" --arg kind "$kind" --arg purpose "$purpose" \
    --arg created_at "$created_at" --arg artifact "$artifact" --arg checksum "$checksum" \
    --arg mreader_version "$mreader_version" --argjson postgres_major "$postgres_major" \
    --argjson size_bytes "$size" \
    '{recovery_id:$recovery_id,public_id:$public_id,kind:$kind,purpose:$purpose,created_at:$created_at,
      postgres_major:$postgres_major,mreader_version:$mreader_version,size_bytes:$size_bytes,
      sha256:$checksum,artifact:$artifact,verified:true}'
}

each_bundle() {
  local root="$1" area
  for area in dumps/automatic dumps/manual dumps/pre-upgrade dumps/pre-restore snapshots; do
    [[ -d "$root/$area" ]] || continue
    find "$root/$area" -mindepth 1 -maxdepth 1 -type d -print0
  done
}

canonical_parent() {
  local root="$1" purpose="$2"
  case "$purpose" in
    automatic|manual|pre-upgrade|pre-restore) printf '%s/dumps/%s\n' "$root" "$purpose" ;;
    snapshot) printf '%s/snapshots\n' "$root" ;;
    *) fail "unsupported recovery purpose" ;;
  esac
}

publish_staged() {
  local supplied_root="$1" supplied_staging="$2" root staging staging_parent item purpose recovery_id parent final
  mkdir -p "$supplied_root/staging"
  [[ ! -L "$supplied_root" && ! -L "$supplied_root/staging" ]] || fail "recovery root and staging directory must not be symlinks" || return 1
  root="$(realpath -e -- "$supplied_root")"
  staging="$(realpath -e -- "$supplied_staging")" || return 1
  staging_parent="$(realpath -e -- "$(dirname "$staging")")"
  [[ "$staging_parent" == "$root/staging" ]] || fail "bundle must be an immediate child of the canonical staging directory" || return 1
  item="$(verify_bundle "$staging")" || return 1
  purpose="$(jq -r '.purpose' <<<"$item")"
  recovery_id="$(jq -r '.recovery_id' <<<"$item")"
  parent="$(canonical_parent "$root" "$purpose")" || return 1
  mkdir -p "$parent"
  [[ ! -L "$parent" ]] || fail "canonical recovery destination must not be a symlink" || return 1
  final="$parent/$recovery_id"
  [[ ! -e "$final" && ! -L "$final" ]] || fail "recovery point already exists" || return 1
  mv -- "$staging" "$final"
  sync "$final" 2>/dev/null || true
  printf '%s\n' "$final"
}

import_bundle() {
  local supplied_root="$1" supplied_source="$2" root source item source_id recovery_id stage final kind imported_at
  [[ ! -L "$supplied_root" ]] || fail "recovery root must not be a symlink" || return 1
  mkdir -p "$supplied_root/staging"
  [[ ! -L "$supplied_root/staging" ]] || fail "recovery staging directory must not be a symlink" || return 1
  root="$(realpath -e -- "$supplied_root")" || return 1
  source="$(realpath -e -- "$supplied_source")" || return 1
  item="$(verify_bundle "$source")" || return 1
  source_id="$(jq -r '.recovery_id' <<<"$item")"
  imported_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  recovery_id="import-$(date -u +%Y%m%dT%H%M%SZ)-$(printf '%s\0%s\0%s' "$source_id" "$(date +%s%N)" "$$" | sha256sum | cut -c1-12)"
  valid_recovery_id "$recovery_id" || fail "generated import recovery identifier is invalid" || return 1
  stage="$root/staging/$recovery_id"
  [[ ! -e "$stage" && ! -L "$stage" ]] || fail "import staging bundle already exists" || return 1
  mkdir "$stage"

  kind="$(jq -r '.kind' <<<"$item")"
  if [[ "$kind" == "physical_snapshot" ]]; then
    cp -- "$source/snapshot.tar" "$stage/snapshot.tar" || { rm -rf -- "$stage"; fail "could not copy imported snapshot" || return 1; }
  else
    cp -- "$source/database.dump" "$stage/database.dump" || { rm -rf -- "$stage"; fail "could not copy imported database dump" || return 1; }
    cp -- "$source/globals.sql" "$stage/globals.sql" || { rm -rf -- "$stage"; fail "could not copy imported globals" || return 1; }
  fi
  if ! jq -c \
      --arg recovery_id "$recovery_id" \
      --arg imported_at "$imported_at" \
      --arg source_id "$source_id" \
      '.recovery_id=$recovery_id |
       .import_source="legacy-nas" |
       .imported_from_recovery_id=$source_id |
       .imported_at=$imported_at' \
      "$source/manifest.json" > "$stage/manifest.json"; then
    rm -rf -- "$stage"
    fail "could not create imported recovery manifest" || return 1
  fi
  if [[ "$kind" == "physical_snapshot" ]]; then
    (cd "$stage" && sha256sum snapshot.tar manifest.json > checksums.sha256)
  else
    (cd "$stage" && sha256sum database.dump globals.sql manifest.json > checksums.sha256)
  fi
  chmod 600 "$stage"/* 2>/dev/null || true
  if ! final="$(publish_staged "$root" "$stage")"; then
    rm -rf -- "$stage"
    return 1
  fi
  printf '%s\n' "$final"
}

resolve_public_id() {
  local supplied_root="$1" public_id="$2" root bundle item found='' count=0
  valid_public_id "$public_id" || fail "invalid public recovery identifier" || return 1
  [[ -d "$supplied_root" && ! -L "$supplied_root" ]] || fail "canonical recovery root is unavailable or unsafe" || return 1
  root="$(realpath -e -- "$supplied_root")" || return 1
  while IFS= read -r -d '' bundle; do
    item="$(verify_bundle "$bundle" 2>/dev/null)" || continue
    if [[ "$(jq -r '.public_id' <<<"$item")" == "$public_id" ]]; then
      found="$item"
      count=$((count + 1))
    fi
  done < <(each_bundle "$root")
  (( count == 1 )) || fail "public recovery identifier did not resolve to exactly one verified bundle" || return 1
  printf '%s\n' "$found"
}

copy_public_artifact() {
  local supplied_root="$1" public_id="$2" destination="$3" item recovery_id
  item="$(resolve_public_id "$supplied_root" "$public_id")" || return 1
  recovery_id="$(jq -r '.recovery_id' <<<"$item")"
  copy_artifact "$supplied_root" "$recovery_id" "$destination"
}

copy_artifact() {
  local supplied_root="$1" recovery_id="$2" destination="$3" root staging destination_parent
  local area candidate found='' count=0 item artifact expected actual tmp checksum_tmp
  valid_recovery_id "$recovery_id" || fail "invalid recovery identifier" || return 1
  root="$(realpath -e -- "$supplied_root")" || return 1
  staging="$root/staging"
  mkdir -p "$staging"
  [[ ! -L "$staging" ]] || fail "canonical staging directory must not be a symlink" || return 1
  mkdir -p "$(dirname "$destination")"
  destination_parent="$(realpath -e -- "$(dirname "$destination")")"
  case "$destination_parent" in
    "$staging"|"$staging"/*) ;;
    *) fail "artifact destination must be inside the canonical staging directory" || return 1 ;;
  esac
  [[ ! -e "$destination" && ! -L "$destination" ]] || fail "artifact destination already exists" || return 1
  for area in dumps/automatic dumps/manual dumps/pre-upgrade dumps/pre-restore snapshots; do
    candidate="$root/$area/$recovery_id"
    if [[ -d "$candidate" && ! -L "$candidate" ]]; then
      found="$candidate"
      count=$((count + 1))
    fi
  done
  (( count == 1 )) || fail "recovery identifier did not resolve to exactly one bundle" || return 1
  item="$(verify_bundle "$found")" || return 1
  artifact="$(jq -r '.artifact' <<<"$item")"
  expected="$(jq -r '.sha256' <<<"$item")"
  tmp="$destination.tmp.$$"
  checksum_tmp="$destination.sha256.tmp.$$"
  rm -f -- "$tmp" "$checksum_tmp"
  if ! cp -- "$found/$artifact" "$tmp"; then
    rm -f -- "$tmp" "$checksum_tmp"
    fail "could not copy recovery artifact" || return 1
  fi
  actual="$(sha256sum "$tmp" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    rm -f -- "$tmp" "$checksum_tmp"
    fail "copied recovery artifact checksum mismatch" || return 1
  fi
  printf '%s  %s\n' "$actual" "$(basename "$destination")" > "$checksum_tmp"
  chmod 600 "$tmp" "$checksum_tmp" 2>/dev/null || true
  mv -- "$tmp" "$destination"
  mv -- "$checksum_tmp" "$destination.sha256"
  printf '%s\n' "$item"
}

catalog() {
  local supplied="$1" root records invalid=0 bundle item tmp purpose expected_parent relative
  mkdir -p "$supplied"
  [[ ! -L "$supplied" ]] || fail "recovery root must not be a symlink" || return 1
  root="$(realpath -e -- "$supplied")"
  tmp="$(mktemp)"
  while IFS= read -r -d '' bundle; do
    if item="$(verify_bundle "$bundle" 2>/dev/null)"; then
      purpose="$(jq -r '.purpose' <<<"$item")"
      expected_parent="$(canonical_parent "$root" "$purpose")"
      if [[ "$(dirname "$bundle")" == "$expected_parent" ]]; then
        relative="${bundle#"$root"/}"
        item="$(jq -c --arg relative "$relative" '. + {relative_directory:$relative}' <<<"$item")"
        printf '%s\n' "$item" >> "$tmp"
      else
        invalid=$((invalid + 1))
      fi
    else
      invalid=$((invalid + 1))
    fi
  done < <(each_bundle "$root")
  records="$(jq -s 'sort_by(.created_at) | reverse' "$tmp")"
  rm -f -- "$tmp"
  jq -cn --arg generated_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --argjson invalid "$invalid" --argjson records "$records" \
    '{generated_at:$generated_at,count:($records|length),invalid_count:$invalid,recovery_points:$records}'
}

validate_retention_pin_file() {
  local pin_file="$1" line
  [[ -z "$pin_file" ]] && return 0
  [[ -f "$pin_file" && ! -L "$pin_file" ]] || fail "retention pin file must be a regular file" || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    valid_recovery_id "$line" || fail "retention pin file contains an invalid recovery identifier" || return 1
  done < "$pin_file"
}

retention_protection_snapshot() {
  local root="$1" bundle item id purpose created
  local last_id='' last_epoch=-1 upgrade_id='' upgrade_epoch=-1 restore_id='' restore_epoch=-1
  while IFS= read -r -d '' bundle; do
    item="$(verify_bundle "$bundle" 2>/dev/null)" || continue
    id="$(jq -r '.recovery_id' <<<"$item")"
    purpose="$(jq -r '.purpose' <<<"$item")"
    created="$(date -u -d "$(jq -r '.created_at' <<<"$item")" +%s)"
    if (( created > last_epoch )); then
      last_epoch="$created"
      last_id="$id"
    fi
    if [[ "$purpose" == "pre-upgrade" ]] && (( created > upgrade_epoch )); then
      upgrade_epoch="$created"
      upgrade_id="$id"
    fi
    if [[ "$purpose" == "pre-restore" ]] && (( created > restore_epoch )); then
      restore_epoch="$created"
      restore_id="$id"
    fi
  done < <(each_bundle "$root")
  jq -cn --arg last "$last_id" --arg upgrade "$upgrade_id" --arg restore "$restore_id" \
    '{last_verified:$last,current_pre_upgrade:$upgrade,current_pre_restore:$restore}'
}

retention_protection_reason() {
  local id="$1" pin_file="$2" upgrade_id="$3" restore_id="$4" last_id="$5"
  if [[ -n "$pin_file" ]] && grep -Fxq -- "$id" "$pin_file"; then
    printf 'active-source\n'
  elif [[ -n "$upgrade_id" && "$id" == "$upgrade_id" ]]; then
    printf 'current-pre-upgrade\n'
  elif [[ -n "$restore_id" && "$id" == "$restore_id" ]]; then
    printf 'current-pre-restore\n'
  elif [[ -n "$last_id" && "$id" == "$last_id" ]]; then
    printf 'last-verified\n'
  fi
}

delete_recovery_bundle() {
  local root="$1" bundle="$2" id="$3"
  case "$bundle" in
    "$root"/dumps/automatic/"$id"|"$root"/dumps/manual/"$id"|"$root"/dumps/pre-upgrade/"$id"|"$root"/dumps/pre-restore/"$id"|"$root"/snapshots/"$id") rm -rf -- "$bundle" ;;
    *) fail "refusing to prune a bundle outside the canonical recovery layout" || return 1 ;;
  esac
}

prune() {
  local supplied="$1" now_text="$2" dump_days="$3" snapshot_days="$4" pin_file="${5:-}"
  local root now bundle item kind created cutoff id protection last_id upgrade_id restore_id reason
  local deleted protected deleted_tmp protected_tmp degraded=0
  [[ "$dump_days" =~ ^[0-9]+$ && "$snapshot_days" =~ ^[0-9]+$ ]] || fail "retention days must be non-negative integers" || return 1
  root="$(realpath -e -- "$supplied")" || return 1
  now="$(date -u -d "$now_text" +%s)" || fail "invalid retention reference timestamp" || return 1
  validate_retention_pin_file "$pin_file" || return 1
  protection="$(retention_protection_snapshot "$root")" || return 1
  last_id="$(jq -r '.last_verified' <<<"$protection")"
  upgrade_id="$(jq -r '.current_pre_upgrade' <<<"$protection")"
  restore_id="$(jq -r '.current_pre_restore' <<<"$protection")"

  deleted_tmp="$(mktemp)"
  protected_tmp="$(mktemp)"
  while IFS= read -r -d '' bundle; do
    item="$(verify_bundle "$bundle" 2>/dev/null)" || continue
    kind="$(jq -r '.kind' <<<"$item")"
    created="$(date -u -d "$(jq -r '.created_at' <<<"$item")" +%s)"
    if [[ "$kind" == "physical_snapshot" ]]; then
      cutoff=$((now - snapshot_days * 86400))
    else
      cutoff=$((now - dump_days * 86400))
    fi
    (( created < cutoff )) || continue
    id="$(jq -r '.recovery_id' <<<"$item")"
    reason="$(retention_protection_reason "$id" "$pin_file" "$upgrade_id" "$restore_id" "$last_id")"
    [[ -n "$last_id" && "$id" == "$last_id" ]] && degraded=1
    if [[ -n "$reason" ]]; then
      jq -cn --arg recovery_id "$id" --arg reason "$reason" '{recovery_id:$recovery_id,reason:$reason}' >> "$protected_tmp"
      continue
    fi
    delete_recovery_bundle "$root" "$bundle" "$id" || return 1
    jq -cn --arg recovery_id "$id" '{recovery_id:$recovery_id}' >> "$deleted_tmp"
  done < <(each_bundle "$root")
  deleted="$(jq -s '.' "$deleted_tmp")"
  protected="$(jq -s '.' "$protected_tmp")"
  rm -f -- "$deleted_tmp" "$protected_tmp"
  if [[ -n "$last_id" ]]; then
    jq -cn --argjson deleted "$deleted" --argjson protected "$protected" --arg last_verified "$last_id" --argjson degraded "$degraded" \
      '{deleted_count:($deleted|length),deleted:$deleted,protected:$protected,degraded_protection:($degraded == 1),last_verified_recovery_id:$last_verified}'
  else
    jq -cn --argjson deleted "$deleted" --argjson protected "$protected" \
      '{deleted_count:($deleted|length),deleted:$deleted,protected:$protected,degraded_protection:false,last_verified_recovery_id:null}'
  fi
}

main() {
  require_tools
  local command="${1:-}"
  shift || true
  case "$command" in
    verify-bundle) [[ $# -eq 1 ]] || fail "verify-bundle requires BUNDLE"; verify_bundle "$1" ;;
    catalog) [[ $# -eq 1 ]] || fail "catalog requires ROOT"; catalog "$1" ;;
    prune) [[ $# -ge 4 && $# -le 5 ]] || fail "prune requires ROOT NOW DUMP_DAYS SNAPSHOT_DAYS [PIN_FILE]"; prune "$1" "$2" "$3" "$4" "${5:-}" ;;
    import-bundle) [[ $# -eq 2 ]] || fail "import-bundle requires ROOT SOURCE_BUNDLE"; import_bundle "$1" "$2" ;;
    publish-staged) [[ $# -eq 2 ]] || fail "publish-staged requires ROOT STAGED_BUNDLE"; publish_staged "$1" "$2" ;;
    resolve-public-id) [[ $# -eq 2 ]] || fail "resolve-public-id requires ROOT PUBLIC_ID"; resolve_public_id "$1" "$2" ;;
    copy-public-artifact) [[ $# -eq 3 ]] || fail "copy-public-artifact requires ROOT PUBLIC_ID DESTINATION"; copy_public_artifact "$1" "$2" "$3" ;;
    copy-artifact) [[ $# -eq 3 ]] || fail "copy-artifact requires ROOT RECOVERY_ID DESTINATION"; copy_artifact "$1" "$2" "$3" ;;
    *) fail "usage: local-recovery-store.sh {verify-bundle BUNDLE|catalog ROOT|prune ROOT NOW DUMP_DAYS SNAPSHOT_DAYS [PIN_FILE]|import-bundle ROOT SOURCE_BUNDLE|publish-staged ROOT STAGED_BUNDLE|resolve-public-id ROOT PUBLIC_ID|copy-public-artifact ROOT PUBLIC_ID DESTINATION|copy-artifact ROOT RECOVERY_ID DESTINATION}" ;;
  esac
}

main "$@"
