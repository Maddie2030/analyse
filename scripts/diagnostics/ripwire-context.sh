#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$repo_root" ]]; then
  echo "ERROR: run inside the MReader git repository" >&2
  exit 2
fi

ripwire_bin="${MREADER_RIPWIRE_BIN:-}"
workspace_ripwire="$repo_root/../../tools/ripwire/bin/ripwire"

if [[ -n "$ripwire_bin" && ! -x "$ripwire_bin" ]]; then
  echo "ERROR: MREADER_RIPWIRE_BIN is not executable: $ripwire_bin" >&2
  exit 127
fi
if [[ -z "$ripwire_bin" ]] && command -v ripwire >/dev/null 2>&1; then
  ripwire_bin="$(command -v ripwire)"
fi
if [[ -z "$ripwire_bin" && -x "$workspace_ripwire" ]]; then
  ripwire_bin="$workspace_ripwire"
fi
if [[ -z "$ripwire_bin" ]]; then
  cat >&2 <<'MSG'
Ripwire is unavailable.
Checked MREADER_RIPWIRE_BIN, PATH, and the dedicated workspace candidate ../../tools/ripwire/bin/ripwire.
No Ripwire result has been produced.
MSG
  exit 127
fi

export PATH="$(dirname "$ripwire_bin"):$PATH"

mode="${1:-doctor}"
shift || true

case "$mode" in
  doctor)
    exec "$ripwire_bin" "$repo_root" --doctor --legend=compact
    ;;
  pack)
    task="${1:-}"
    [[ -n "$task" ]] || { echo "usage: $0 pack <task>" >&2; exit 2; }
    exec "$ripwire_bin" "$repo_root" --pack-task="$task" --legend=compact
    ;;
  impact)
    sym="${1:-}"
    [[ -n "$sym" ]] || { echo "usage: $0 impact <symbol>" >&2; exit 2; }
    exec "$ripwire_bin" "$repo_root" --impact="$sym" --legend=compact
    ;;
  bug)
    symptom="${1:-}"
    [[ -n "$symptom" ]] || { echo "usage: $0 bug <symptom>" >&2; exit 2; }
    exec "$ripwire_bin" "$repo_root" --for="$symptom" --legend=compact
    ;;
  change-check)
    exec "$ripwire_bin" "$repo_root" --pr-context --legend=compact
    ;;
  test-gate)
    exec "$ripwire_bin" "$repo_root" --test-gate --legend=compact
    ;;
  handoff)
    exec "$ripwire_bin" "$repo_root" --handoff --legend=compact
    ;;
  *)
    echo "usage: $0 {doctor|pack|impact|bug|change-check|test-gate|handoff} [argument]" >&2
    exit 2
    ;;
esac
