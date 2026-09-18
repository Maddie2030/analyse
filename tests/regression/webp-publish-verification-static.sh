#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

# Debian 12 service images intentionally pin libvips 8.14.1. The newer
# VipsForeignSave keep= option is not available there, while the legacy
# strip=true saver option is. No active WebP writer may pass keep=.
# Check the actual WebP writer calls rather than counting duplicate implementations.
# The Scraper-local tilepack codec was retired during publication ownership
# consolidation; the shared codec is the single canonical reader-page codec.
"$PYTHON_RUNTIME" - <<'PY_WEBP' || exit $?
import ast
from pathlib import Path

roots = [
    Path("services/image_service"),
    Path("services/scraper_service"),
    Path("services/thumbnail_transformer"),
    Path("shared"),
]
violations = []
for root in roots:
    for path in root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "write_to_buffer" or not node.args:
                continue
            first = node.args[0]
            if not isinstance(first, ast.Constant) or first.value != ".webp":
                continue
            if any(keyword.arg == "keep" for keyword in node.keywords):
                violations.append(f"{path}:{getattr(node, 'lineno', '?')}")
if violations:
    raise SystemExit("unsupported keep= on WebP writer: " + ", ".join(violations))
PY_WEBP

[[ ! -e services/scraper_service/app/tilepack_codec.py ]] || fail 'Scraper-local tilepack codec must remain retired; use shared/shared/tilepack_codec.py'
shared_strip_count="$(grep -F 'write_to_buffer(".webp"' shared/shared/tilepack_codec.py | grep -c 'strip=True' || true)"
[[ "$shared_strip_count" -eq 2 ]] || fail "canonical shared tilepack codec must contain exactly 2 strip=True WebP writes, found $shared_strip_count"
! grep -Fq 'cover_data = image.write_to_buffer(".webp", Q=85, strip=True)' services/scraper_service/app/series_drafts.py || fail 'Scraper still owns the transitional series-cover WebP transform after cover cutover'
grep -Fq 'webp_data, width, height = await _convert_thumbnail_bytes(source_bytes)' services/image_service/app/worker.py || fail 'Media thumbnail worker no longer owns canonical cover transformation'
grep -Fq 'def _retain_icc_metadata_only' services/image_service/app/services/image_processor.py || fail 'image-service ICC compatibility helper missing'
grep -Fq 'def _retain_icc_metadata_only' services/thumbnail_transformer/app/main.py || fail 'thumbnail ICC compatibility helper missing'

grep -Fq 'libvips42=8.14.1-3+deb12u3' services/image_service/Dockerfile || fail 'image-service libvips pin changed unexpectedly'
grep -Fq 'libvips42=8.14.1-3+deb12u3' services/scraper_service/Dockerfile || fail 'scraper-service libvips pin changed unexpectedly'
grep -Fq 'libvips42=8.14.1-3+deb12u3' services/thumbnail_transformer/Dockerfile || fail 'thumbnail-transformer libvips pin changed unexpectedly'

# Post-publish verification must tolerate a short stale 404 window and verify
# both ends of a multi-page manifest without fetching the entire chapter.
grep -Fq '# Read-after-write verification can briefly see a stale 404' services/scraper_service/app/series_drafts.py || fail 'verification 404 retry guard missing'
grep -Fq 'sample_indexes = [0]' services/scraper_service/app/series_drafts.py || fail 'Reader first-page sample missing'
grep -Fq 'sample_indexes.append(len(pages) - 1)' services/scraper_service/app/series_drafts.py || fail 'Reader last-page sample missing'
grep -Fq 'did not return any pages' services/scraper_service/app/series_drafts.py || fail 'empty Reader manifest warning missing'

echo 'WebP publish/verification static regression PASSED'
