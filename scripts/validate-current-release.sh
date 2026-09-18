#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"
fail(){ echo "CURRENT RELEASE VALIDATION FAILED: $*" >&2; exit 1; }
VERSION="$(tr -d '\r\n' < VERSION)"
[[ "$VERSION" == "1.3.0-rc4.84" ]] || fail "expected 1.3.0-rc4.84, got $VERSION"
required=(
  deploy/compose/docker-compose.hybrid-stateful.yml
  deploy/compose/docker-compose.hybrid-build.yml
  deploy/compose/docker-compose.hybrid-public-edge.yml
  deploy/docker-desktop-hybrid/namespaces.yaml
  deploy/docker-desktop-hybrid/user-apps.yaml
  deploy/docker-desktop-hybrid/admin-apps.yaml
  deploy/docker-desktop-hybrid/user-keda.yaml
  deploy/docker-desktop-hybrid/admin-keda.yaml
  db/migrations/048_rc483_current_baseline.sql
  scripts/recovery/catalog-restore.sh
  scripts/recovery/catalog-import.sql
  docs/recovery/CATALOG_RECOVERY.md
)
for file in "${required[@]}"; do [[ -f "$file" ]] || fail "missing $file"; done
mapfile -t compose_files < <(find deploy/compose -maxdepth 1 -type f -name 'docker-compose*.yml' -printf '%f\n' | sort)
expected=(docker-compose.hybrid-build.yml docker-compose.hybrid-public-edge.yml docker-compose.hybrid-stateful.yml)
[[ "${compose_files[*]}" == "${expected[*]}" ]] || fail "unexpected Compose deployment file remains: ${compose_files[*]}"

# Parse every Python file without importing packages or creating __pycache__.
"$PYTHON_RUNTIME" - <<'PY'
import ast
from pathlib import Path
bad=[]
for root in ('services','shared','tests','scripts'):
    base=Path(root)
    if not base.exists(): continue
    for p in base.rglob('*.py'):
        try: ast.parse(p.read_text(encoding='utf-8'), filename=str(p))
        except (SyntaxError, UnicodeDecodeError) as exc: bad.append((p,exc))
if bad:
    for p,e in bad: print(f'{p}: {e}')
    raise SystemExit(1)
print('Python syntax parse: PASS')
PY

# Shell syntax for executable operational/test scripts.
while IFS= read -r file; do bash -n "$file"; done < <(find scripts tests -type f -name '*.sh' -print | sort)
echo 'Shell syntax: PASS'

TERM=xterm bash tests/regression/rc484-consolidation-static.sh
TERM=xterm bash tests/regression/rc484-upgrade-recovery-static.sh
TERM=xterm bash tests/regression/bootstrap-fresh-env.sh
TERM=xterm bash tests/regression/hybrid-legacy-volume-priority.sh
TERM=xterm bash scripts/android-web-reader-contract-audit.sh
TERM=xterm bash scripts/android-static-audit.sh
TERM=xterm bash tests/regression/browser-reading-acceptance-static.sh
TERM=xterm bash tests/regression/release-version-consistency.sh
TERM=xterm bash tests/regression/repository-paths-static.sh
TERM=xterm bash tests/regression/python-runtime-packaging-static.sh
TERM=xterm bash tests/regression/pressure-efficiency-static.sh
TERM=xterm bash tests/regression/dependency-pins.sh
TERM=xterm bash tests/regression/twin-plane-static.sh
"$PYTHON_RUNTIME" -m unittest tests.regression.test_p12_5_live_diagnostic_repairs -v
"$PYTHON_RUNTIME" -m unittest tests.regression.test_p12_7_permission_surface -v
"$PYTHON_RUNTIME" -m unittest tests.regression.test_p12_7_deep_diagnostics_contracts -v

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && [[ -f .env ]]; then
  echo '==> Validating canonical Compose files with current .env'
  for file in "${required[@]:0:3}"; do docker compose --env-file .env -f "$file" config >/dev/null; done
else
  echo 'SKIP: Docker Compose config render requires Docker and a configured .env.'
fi

echo "MReader $VERSION current release validation PASSED"
