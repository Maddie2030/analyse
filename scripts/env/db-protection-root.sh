#!/usr/bin/env bash
# Shared recovery-root contract. This file is sourced by startup scripts and
# tests; it never sources a user's .env and never evaluates path text as code.

dbp_error() {
  printf 'ERROR: %s\n' "$1" >&2
  return 2
}

dbp_windows_path_to_drive() {
  local value="${1:-}"
  value="${value//\\//}"
  if [[ "$value" =~ ^/cygdrive/([A-Za-z])(/.*)?$ ]]; then
    value="${BASH_REMATCH[1]}:${BASH_REMATCH[2]:-/}"
  elif [[ "$value" =~ ^/([A-Za-z])(/.*)?$ ]]; then
    value="${BASH_REMATCH[1]}:${BASH_REMATCH[2]:-/}"
  fi
  printf '%s\n' "$value"
}

dbp_normalize_root() {
  local platform="${1:-}" host_home="${2:-}" profile="${3:-}" value="${4:-}"
  local default_home compare_value compare_home

  case "$platform" in
    linux)
      default_home="$host_home"
      ;;
    windows)
      default_home="${profile:-$host_home}"
      default_home="$(dbp_windows_path_to_drive "$default_home")"
      ;;
    *)
      dbp_error 'Unsupported host platform; use Linux or Windows/Git Bash.'
      return 2
      ;;
  esac

  # env_get intentionally returns literal dotenv text. Accept one matching
  # pair of quotes for paths containing spaces, but never perform expansion.
  if [[ ${#value} -ge 2 ]]; then
    if [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]] ||
       [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi

  if [[ -z "$value" ]]; then
    if [[ "$platform" == windows ]]; then
      # Windows/Git Bash fresh installs use one stable, dedicated host directory.
      # This avoids depending on USERPROFILE/HOME path shapes that vary across
      # MINGW/MSYS/Cygwin shells while keeping the bind mount outside the repo.
      value="C:/mreader/database-protection"
    else
      [[ -n "$default_home" ]] || {
        dbp_error 'Host home is unknown; set MREADER_DB_PROTECTION_ROOT explicitly.'
        return 2
      }
      value="${default_home%/}/.mreader/database-protection"
    fi
  fi

  # Git Bash supplies Windows paths with backslashes. Convert them before
  # validation so the persisted representation is stable across entry points.
  if [[ "$platform" == windows ]]; then
    value="$(dbp_windows_path_to_drive "$value")"
  fi

  if [[ ${#value} -gt 4096 || "$value" =~ [[:cntrl:]] ||
        "$value" == *'$'* || "$value" == *'`'* || "$value" == *'#'* ||
        "$value" == *"'"* || "$value" == *'"'* || "$value" =~ [\\] ||
        "$value" == ' '* || "$value" == *' ' ]]; then
    dbp_error 'Recovery root must be a bounded literal path without interpolation or control characters.'
    return 2
  fi

  [[ "$value" == / || "$value" == *:/ ]] || value="${value%/}"
  if [[ "$value" == *'//'* || "/$value/" == *'/../'* || "/$value/" == *'/./'* ]]; then
    dbp_error 'Recovery root must not contain traversal, repeated separators, or UNC syntax.'
    return 2
  fi

  if [[ "$platform" == windows ]]; then
    [[ "$value" =~ ^[A-Za-z]:/[^:]+$ ]] || {
      dbp_error 'Use an absolute Windows drive path, such as C:/Users/name/.mreader/database-protection.'
      return 2
    }
    value="$(printf '%s' "${value:0:1}" | tr '[:lower:]' '[:upper:]')${value:1}"
  else
    [[ "$value" == /* && "$value" != *:* ]] || {
      dbp_error 'Use an absolute Linux recovery path.'
      return 2
    }
  fi

  case "$value" in
    /|/home|/root|/Users|/tmp|/var|/srv|[A-Za-z]:/[Uu][Ss][Ee][Rr][Ss])
      dbp_error 'Choose a dedicated recovery directory, not a broad system directory.'
      return 2
      ;;
  esac

  compare_value="$value"
  compare_home="${default_home%/}"
  if [[ "$platform" == windows ]]; then
    compare_value="$(printf '%s' "$compare_value" | tr '[:upper:]' '[:lower:]')"
    compare_home="$(printf '%s' "$compare_home" | tr '[:upper:]' '[:lower:]')"
  fi
  if [[ "$compare_value" == "$compare_home" || "$value" == "${host_home%/}" ]]; then
    dbp_error 'Choose a dedicated recovery directory, not the entire user home.'
    return 2
  fi

  printf '%s\n' "$value"
}

dbp_resolve_env() {
  local file="${1:-}" platform="${2:-}" host_home="${3:-}" profile="${4:-}"
  local override="${5:-}" size assignments configured selected normalized_override

  [[ -f "$file" && ! -L "$file" ]] || {
    dbp_error 'A regular, non-symlink environment file is required.'
    return 2
  }
  size="$(_env_size "$file")" || return 2
  [[ "$size" =~ ^[0-9]+$ && "$size" -le "${MREADER_ENV_MAX_BYTES:-1048576}" ]] || {
    dbp_error 'Environment file exceeds the supported size; repair it before configuring recovery.'
    return 2
  }
  assignments="$(awk '/^MREADER_DB_PROTECTION_ROOT=/{n++} END{print n+0}' "$file")"
  [[ "$assignments" -le 1 ]] || {
    dbp_error 'Resolve duplicate MREADER_DB_PROTECTION_ROOT assignments explicitly.'
    return 2
  }

  configured="$(env_get "$file" MREADER_DB_PROTECTION_ROOT)"
  if [[ -n "$configured" ]]; then
    selected="$(dbp_normalize_root "$platform" "$host_home" "$profile" "$configured")" || return 2
    if [[ -n "$override" ]]; then
      normalized_override="$(dbp_normalize_root "$platform" "$host_home" "$profile" "$override")" || return 2
      [[ "$selected" == "$normalized_override" ]] || {
        dbp_error 'Process and saved recovery roots disagree; reconcile configuration before startup.'
        return 2
      }
    fi
  else
    selected="$(dbp_normalize_root "$platform" "$host_home" "$profile" "$override")" || return 2
  fi

  if [[ "$configured" != "$selected" ]]; then
    (umask 077; env_set "$file" MREADER_DB_PROTECTION_ROOT "$selected") || return 2
  fi
  printf '%s\n' "$selected"
}
