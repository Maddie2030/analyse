#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "python runtime packaging regression FAILED: $*" >&2; exit 1; }
for file in services/scraper_service/Dockerfile services/scraper_service/Dockerfile.browser; do
  grep -Fq 'COPY shared /shared' "$file" || fail "$file does not copy shared package"
  grep -Eq 'RUN (python -m )?pip install .*[- ]e /shared|RUN pip install --no-deps -e /shared' "$file" || fail "$file does not install shared package"
done
! grep -Eq '^from \.(database|models|auth) import' shared/shared/__init__.py || fail 'shared package eagerly imports heavyweight modules'
grep -Fq 'def __getattr__(name: str)' shared/shared/__init__.py || fail 'shared lazy export hook missing'
for module in app.batch_worker app.series_worker app.worker app.lifecycle_worker; do
  grep -A6 -B2 -- "- $module" deploy/docker-desktop-hybrid/admin-apps.yaml >/dev/null || fail "hybrid worker $module is missing"
  if grep -B3 -- "- $module" deploy/docker-desktop-hybrid/admin-apps.yaml | grep -q 'command:'; then fail "hybrid worker $module overrides Docker ENTRYPOINT"; fi
  grep -B3 -- "- $module" deploy/docker-desktop-hybrid/admin-apps.yaml | grep -q 'args:' || fail "hybrid worker $module must use args"
done
# Current staging is strict: a different/missing PVC is a deployment error, never an auto-adoption/reconstruction path.
grep -Fq 'Current MReader does not auto-adopt a new PVC/spool' services/scraper_service/app/staging_store.py || fail 'scraper strict staging contract missing'
grep -Fq 'Lifecycle worker sees a different scraper staging PVC/spool' services/image_service/app/lifecycle_worker.py || fail 'lifecycle strict staging contract missing'
! grep -Fq 'reference_missing_unrecoverable' services/image_service/app/lifecycle_worker.py || fail 'legacy recoverable staging classification remains'
! grep -Fq 'adopted new scraper staging spool' services/image_service/app/lifecycle_worker.py || fail 'legacy spool adoption remains'
! grep -Fq 'Restore/migrate the old spool before' services/image_service/app/lifecycle_worker.py || fail 'legacy spool migration fallback remains'
echo 'python runtime packaging/entrypoint regression PASSED'
