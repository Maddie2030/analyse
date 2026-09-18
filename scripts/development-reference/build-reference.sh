#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
OUT=""
CHECKPOINT=""
RUN_GRAPHIFY=1
RUN_RIPWIRE=1
INSTALL_PROJECT_GRAPH=0

usage() {
  cat <<'EOF'
Usage: build-reference.sh [--root PATH] [--out PATH] [--checkpoint SHA]
                          [--no-graphify] [--no-ripwire] [--install-project-graph]

Build a deterministic MReader development reference for the selected source tree.
Generated artifacts are package/build evidence and need not be committed to Git.
EOF
}

while (($#)); do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --checkpoint) CHECKPOINT="$2"; shift 2 ;;
    --no-graphify) RUN_GRAPHIFY=0; shift ;;
    --no-ripwire) RUN_RIPWIRE=0; shift ;;
    --install-project-graph) INSTALL_PROJECT_GRAPH=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$ROOT" && pwd -P)"
PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"
[[ -x "$PYTHON_RUNTIME" ]] || { echo "ERROR: shared Python runtime is missing or not executable: $PYTHON_RUNTIME" >&2; exit 2; }
: "${OUT:=$ROOT/development-reference}"
mkdir -p "$OUT/graphify-out" "$OUT/graphify-evidence" "$OUT/ripwire-evidence"
if [[ -z "$CHECKPOINT" ]]; then
  CHECKPOINT="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || printf UNKNOWN)"
fi

"$PYTHON_RUNTIME" "$SCRIPT_DIR/build_mreader_code_graph.py" --root "$ROOT" --out "$OUT/graphify-out" --checkpoint "$CHECKPOINT"
"$PYTHON_RUNTIME" "$SCRIPT_DIR/build_mreader_development_graph.py" --root "$ROOT" --out "$OUT/graphify-out" --checkpoint "$CHECKPOINT"

for f in ISSUE-TO-CHANGE-INDEX.md SERVICE-LOCATOR.md CHANGE-IMPACT-WORKFLOW.md GRAPHIFY-PLAYBOOK.md MREADER-DEVELOPMENT-REFERENCE.md MREADER-CODE-MAP.md ISSUE-IMPACT-CATALOG.json; do
  cp "$ROOT/docs/development-reference/$f" "$OUT/$f"
done
cp "$SCRIPT_DIR/mreader-impact.py" "$OUT/mreader-impact.py"
printf '%s\n' "$CHECKPOINT" > "$OUT/SOURCE-CHECKPOINT.txt"
"$PYTHON_RUNTIME" - "$OUT/ISSUE-IMPACT-CATALOG.json" "$CHECKPOINT" <<'PYJSON'
import json, sys
from pathlib import Path
p=Path(sys.argv[1]); d=json.loads(p.read_text()); d["source_checkpoint"]=sys.argv[2]; p.write_text(json.dumps(d,indent=2)+"\n")
PYJSON

CODE_META="$OUT/graphify-out/CODE-GRAPH-METADATA.json"
DEV_META="$OUT/graphify-out/DEVELOPMENT-GRAPH-METADATA.json"
"$PYTHON_RUNTIME" - "$CHECKPOINT" "$CODE_META" "$DEV_META" "$OUT/README.md" "$OUT/REFERENCE-MANIFEST.md" <<'PY'
import json, sys
from pathlib import Path
checkpoint, code_path, dev_path, readme_path, manifest_path = sys.argv[1:]
code=json.loads(Path(code_path).read_text())
dev=json.loads(Path(dev_path).read_text())
short=checkpoint[:7]
Path(readme_path).write_text(f'''# MReader RC4.85 development reference — {short}\n\nThis directory maps source checkpoint `{checkpoint}` for Drushti/Ripwire/Graphify issue triage.\n\n- `graphify-out/development-graph.json`: issue-oriented architecture graph.\n- `graphify-out/code-graph.json`: deeper file/symbol/import graph.\n- `ISSUE-TO-CHANGE-INDEX.md`: symptom → likely change surface/tests.\n- `mreader-impact.py`: issue lookup CLI.\n- `graphify-evidence/`: Graphify query/explain/path/affected evidence when Graphify is available.\n- `ripwire-evidence/`: Ripwire orientation/impact evidence when Ripwire is available.\n\nGraph counts: code `{code['nodes']}` nodes / `{code['edges']}` edges / `{code['files_indexed']}` files; development `{dev['nodes']}` nodes / `{dev['edges']}` edges / `{dev['routes']}` routes.\n\nNative Graphify AST extraction is not claimed when Drushti reports Tree-sitter parser support unavailable. The deterministic builders tag inferred relationships as `INFERRED` and extracted relationships as `EXTRACTED`; Graphify is then used as the navigation/blast-radius engine over these graphs.\n''')
Path(manifest_path).write_text(f'''# Development-reference manifest\n\n- Product: MReader RC4.85\n- Source checkpoint: `{checkpoint}`\n- Code graph: {code['nodes']} nodes, {code['edges']} edges, {code['files_indexed']} indexed files\n- Development graph: {dev['nodes']} nodes, {dev['edges']} edges, {dev['routes']} ownership routes\n- Rebuild command: `./scripts/development-reference/build-reference.sh --out <dir> --checkpoint {checkpoint}`\n\nRegenerate after changes to route ownership, service/storage boundaries, publication/deletion flow, event topology, client persistence, deployment topology, or major module moves.\n''')
PY


run_evidence() {
  local seconds="$1" output="$2"; shift 2
  set +e
  if command -v timeout >/dev/null 2>&1; then
    timeout "$seconds" "$@" >"$output" 2>&1
  else
    "$@" >"$output" 2>&1
  fi
  local rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    printf '\nEVIDENCE_EXIT_CODE=%s\n' "$rc" >>"$output"
  fi
  return 0
}

G="$OUT/graphify-out/development-graph.json"
C="$OUT/graphify-out/code-graph.json"
if (( RUN_GRAPHIFY )) && command -v graphify >/dev/null 2>&1; then
  run_evidence 10 "$OUT/graphify-evidence/version.txt" graphify --version
  run_evidence 20 "$OUT/graphify-evidence/god-nodes.txt" graphify god-nodes --top 20 --graph "$G"
  run_evidence 25 "$OUT/graphify-evidence/query-publication.txt" graphify query "publication" --graph "$G" --budget 1800
  run_evidence 25 "$OUT/graphify-evidence/query-reading.txt" graphify query "reading progress history protected asset" --graph "$G" --budget 1800
  run_evidence 25 "$OUT/graphify-evidence/query-diagnostics.txt" graphify query "diagnostics actor journey report" --graph "$G" --budget 1800
  run_evidence 20 "$OUT/graphify-evidence/explain-catalog.txt" graphify explain "service:catalog_go" --graph "$G"
  run_evidence 25 "$OUT/graphify-evidence/affected-diagnostics-report.txt" graphify affected "scripts/diagnostics/report_builder.py" --depth 3 --graph "$C"
  run_evidence 25 "$OUT/graphify-evidence/affected-catalog-publication.txt" graphify affected "services/catalog_go/internal/store/publication.go" --depth 3 --graph "$G"
  run_evidence 20 "$OUT/graphify-evidence/path-web-reader.txt" graphify path "User Web" "service:reader_go" --graph "$G"
else
  printf 'Graphify unavailable; graph generation succeeded but query evidence was skipped.\n' > "$OUT/graphify-evidence/SKIPPED.txt"
fi

if (( RUN_RIPWIRE )) && command -v ripwire >/dev/null 2>&1; then
  run_evidence 30 "$OUT/ripwire-evidence/orient.txt" ripwire "$ROOT" --for="MReader architecture service ownership publication reading diagnostics" --token-budget=4500
  run_evidence 30 "$OUT/ripwire-evidence/diagnostics.txt" ripwire "$ROOT" --for="actor journey diagnostics report builder runtime evidence" --token-budget=3200
  run_evidence 30 "$OUT/ripwire-evidence/report-builder-impact.txt" ripwire "$ROOT" --impact=build_report --limit=80
else
  printf 'Ripwire unavailable; evidence skipped.\n' > "$OUT/ripwire-evidence/SKIPPED.txt"
fi


if (( INSTALL_PROJECT_GRAPH )); then
  mkdir -p "$ROOT/graphify-out"
  cp "$OUT/graphify-out/development-graph.json" "$ROOT/graphify-out/graph.json"
  cp "$OUT/graphify-out/DEVELOPMENT-GRAPH-METADATA.json" "$ROOT/graphify-out/DEVELOPMENT-GRAPH-METADATA.json"
fi

# Graphify may leave query cache/timestamp state; it is execution cache, not reference evidence.
rm -rf "$OUT/graphify-out/cache"
# Make evidence portable: do not persist sandbox/host absolute paths.
"$PYTHON_RUNTIME" - "$ROOT" "$OUT" <<'PYSAN'
from pathlib import Path
import sys
root, out = sys.argv[1:3]
for base in (Path(out)/"graphify-evidence", Path(out)/"ripwire-evidence"):
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        try:
            text=p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for raw, repl in ((out,"<development-reference>"),(root,"<repo-root>"),(out.lstrip("/"),"<development-reference>"),(root.lstrip("/"),"<repo-root>")):
            text=text.replace(raw,repl)
        p.write_text(text,encoding="utf-8")
PYSAN

(
  cd "$OUT"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
printf 'Development reference built at %s for %s\n' "$OUT" "$CHECKPOINT"
