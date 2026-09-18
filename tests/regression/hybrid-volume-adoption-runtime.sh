#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/mreader-volume-adoption-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
cp .env.example "$TMP/env"
mkdir -p "$TMP/bin"
cat > "$TMP/bin/docker" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
scenario="${MREADER_MOCK_SCENARIO:-legacy-only}"
cmd="${1:-}"; shift || true
case "$cmd" in
  info) exit 0 ;;
  volume)
    sub="${1:-}"; shift || true
    [[ "$sub" == inspect ]] || exit 1
    name="${1:-}"
    case "$scenario:$name" in
      legacy-only:mreader-hybrid-stateful_pgdata) exit 0 ;;
      both:mreader-hybrid-stateful_pgdata|both:mreader_pgdata) exit 0 ;;
      explicit:mreader_pgdata) exit 0 ;;
      *) exit 1 ;;
    esac
    ;;
  run)
    joined=" $* "
    case "$scenario" in
      legacy-only) [[ "$joined" == *" mreader-hybrid-stateful_pgdata:/probe:ro "* ]] && exit 0 || exit 1 ;;
      both) [[ "$joined" == *" mreader-hybrid-stateful_pgdata:/probe:ro "* || "$joined" == *" mreader_pgdata:/probe:ro "* ]] && exit 0 || exit 1 ;;
      explicit) [[ "$joined" == *" mreader_pgdata:/probe:ro "* ]] && exit 0 || exit 1 ;;
    esac
    ;;
  *) exit 1 ;;
esac
MOCK
chmod +x "$TMP/bin/docker"
export PATH="$TMP/bin:$PATH"

# Only the legacy PostgreSQL volume exists and is valid: adopt it.
MREADER_MOCK_SCENARIO=legacy-only scripts/hybrid/adopt-existing-stateful-volumes.sh "$TMP/env" >/dev/null
grep -qx 'HYBRID_PGDATA_VOLUME_NAME=mreader-hybrid-stateful_pgdata' "$TMP/env"


# Both PGDATA volumes are structurally valid, but only legacy contains catalog data:
# catalog-aware adoption must select legacy instead of failing on physical non-emptiness.
cat > "$TMP/inspect-catalog.sh" <<'MOCK_INSPECT'
#!/usr/bin/env bash
cat <<'OUT'
==> Inspecting PostgreSQL volume: mreader_pgdata
volume=mreader_pgdata
exists=yes
pgdata_valid=yes
catalog_state=empty_catalog

==> Inspecting PostgreSQL volume: mreader-hybrid-stateful_pgdata
volume=mreader-hybrid-stateful_pgdata
exists=yes
pgdata_valid=yes
catalog_state=contains_mreader_catalog
OUT
MOCK_INSPECT
chmod +x "$TMP/inspect-catalog.sh"
cp .env.example "$TMP/env-both-one-catalog"
MREADER_MOCK_SCENARIO=both \
MREADER_PG_VOLUME_INSPECTOR="$TMP/inspect-catalog.sh" \
  scripts/hybrid/adopt-existing-stateful-volumes.sh "$TMP/env-both-one-catalog" >/dev/null
grep -qx 'HYBRID_PGDATA_VOLUME_NAME=mreader-hybrid-stateful_pgdata' "$TMP/env-both-one-catalog"

# Both contain PostgreSQL data and inspection is inconclusive: legacy wins by default for upgrade continuity.
cp .env.example "$TMP/env-both"
MREADER_MOCK_SCENARIO=both scripts/hybrid/adopt-existing-stateful-volumes.sh "$TMP/env-both" >/dev/null 2>&1
grep -qx 'HYBRID_PGDATA_VOLUME_NAME=mreader-hybrid-stateful_pgdata' "$TMP/env-both"

# Operator can deliberately keep canonical state by disabling legacy-first selection.
cp .env.example "$TMP/env-explicit"
sed -i 's/^HYBRID_PGDATA_VOLUME_NAME=.*/HYBRID_PGDATA_VOLUME_NAME=mreader_pgdata/' "$TMP/env-explicit"
MREADER_PREFER_LEGACY_STATEFUL_VOLUMES=false MREADER_MOCK_SCENARIO=explicit scripts/hybrid/adopt-existing-stateful-volumes.sh "$TMP/env-explicit" >/dev/null
grep -qx 'HYBRID_PGDATA_VOLUME_NAME=mreader_pgdata' "$TMP/env-explicit"

echo 'hybrid stateful volume adoption runtime regression PASSED'
