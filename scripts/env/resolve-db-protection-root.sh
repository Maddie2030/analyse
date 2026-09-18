#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env-lib.sh"
source "$SCRIPT_DIR/db-protection-root.sh"

[[ $# -le 1 ]] || {
  dbp_error 'Usage: resolve-db-protection-root.sh [ENV_FILE]'
  exit 2
}
env_file="${1:-.env}"

case "$(uname -s)" in
  Linux) platform=linux ;;
  MINGW*|MSYS*|CYGWIN*) platform=windows ;;
  *)
    dbp_error 'Unsupported host platform; use Linux or Windows/Git Bash.'
    exit 2
    ;;
esac

host_home="${HOME:-}"
profile="${USERPROFILE:-}"
if [[ "$platform" == windows ]]; then
  normalized_profile="$(dbp_windows_path_to_drive "$profile")"
  if [[ -z "$profile" || ! "$normalized_profile" =~ ^[A-Za-z]:/ ]]; then
    if command -v cmd.exe >/dev/null 2>&1; then
      windows_profile="$(MSYS_NO_PATHCONV=1 cmd.exe /d /c echo %USERPROFILE% 2>/dev/null | tr -d '\r' | tail -n 1)"
      if [[ -n "$windows_profile" && "$windows_profile" != '%USERPROFILE%' ]]; then
        profile="$windows_profile"
      fi
    fi
  fi
fi

if [[ -n "${SUDO_USER:-}" && -z "${MREADER_DB_PROTECTION_ROOT:-}" &&
      -z "$(env_get "$env_file" MREADER_DB_PROTECTION_ROOT)" ]]; then
  dbp_error 'Run setup as the host user, or set an explicit recovery root before using sudo.'
  exit 2
fi

dbp_resolve_env "$env_file" "$platform" "$host_home" "$profile" "${MREADER_DB_PROTECTION_ROOT:-}"
