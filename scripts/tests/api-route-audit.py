#!/usr/bin/env python3
from __future__ import annotations
import csv
import re
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'tests/api/endpoint_coverage.tsv'

PREFIX_MAP = {
    'services/auth_service/app/routers/auth.py': '/api/auth',
    'services/image_service/app/routers/upload.py': '/api/upload',
    'services/image_service/app/routers/jobs.py': '/api/upload/jobs',
    'services/image_service/app/routers/exports.py': '/api/upload/admin',
    'services/image_service/app/routers/lifecycle.py': '/api/upload/admin',
}

ROUTER_PREFIX_MAP = {
    ('services/image_service/app/routers/jobs.py', 'router'): '/api/upload/jobs',
    ('services/image_service/app/routers/jobs.py', 'internal_router'): '/internal/v1/media/jobs',
}


def python_router_prefix(rel: str, text: str, router_name: str) -> str | None:
    explicit = ROUTER_PREFIX_MAP.get((rel, router_name))
    if explicit is not None:
        return explicit
    if rel in PREFIX_MAP and router_name in {'app', 'router'}:
        return PREFIX_MAP[rel]
    match = re.search(r'APIRouter\(\s*prefix\s*=\s*["\']([^"\']+)', text)
    return match.group(1) if match else None


def normalize(path: str) -> str:
    return re.sub(r':([A-Za-z_][A-Za-z0-9_]*)', r'{\1}', path)



class RouteRecord(NamedTuple):
    method: str
    path: str
    source: str
    handler: str


def _python_handler_after(text: str, offset: int) -> str:
    match = re.search(r'\n(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', text[offset:])
    return match.group(1) if match else '<decorated-handler>'


def source_route_records() -> list[RouteRecord]:
    found: dict[tuple[str, str], RouteRecord] = {}
    for p in (ROOT / 'services').rglob('*.py'):
        rel = p.relative_to(ROOT).as_posix()
        text = p.read_text(encoding='utf-8', errors='ignore')
        for m in re.finditer(r'@(app|router|internal_router)\.(get|post|put|patch|delete)\(\s*["\']([^"\']*)', text, re.I):
            router_name = m.group(1)
            prefix = python_router_prefix(rel, text, router_name)
            path = m.group(3)
            if prefix is not None and (path == '' or path.startswith('/')):
                path = prefix + path
            if path.startswith('/api/') or path.startswith('/images') or path.startswith('/internal/v1/'):
                method = m.group(2).upper()
                path = normalize(path)
                found[(method, path)] = RouteRecord(method, path, rel, _python_handler_after(text, m.end()))

    go_route = re.compile(
        r'r\.(Get|Post|Put|Patch|Delete)\(\s*"([^\"]+)"\s*,\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)',
        re.M,
    )
    for p in (ROOT / 'services').rglob('*.go'):
        rel = p.relative_to(ROOT).as_posix()
        text = p.read_text(encoding='utf-8', errors='ignore')
        for m in go_route.finditer(text):
            path = m.group(2)
            if rel == 'services/catalog_go/internal/httpapi/api.go' and path.startswith('/'):
                if path.startswith('/internal/v1/'):
                    pass
                elif not path.startswith('/api/') and path not in {'/health', '/internal/canary/stats'}:
                    path = '/api/catalog' + path
            if path.startswith('/api/') or path.startswith('/images') or (
                rel == 'services/catalog_go/internal/httpapi/api.go' and path.startswith('/internal/v1/')
            ):
                method = m.group(1).upper()
                path = normalize(path)
                found[(method, path)] = RouteRecord(method, path, rel, m.group(3))
        for m in re.finditer(
            r'mux\.HandleFunc\("(GET|POST|PUT|PATCH|DELETE) ([^\"]+)"\s*,\s*([A-Za-z_][A-Za-z0-9_]*)',
            text,
        ):
            path = m.group(2)
            if path.startswith('/api/') or path.startswith('/images'):
                method = m.group(1)
                path = normalize(path)
                found[(method, path)] = RouteRecord(method, path, rel, m.group(3))

    for p in (ROOT / 'services').rglob('*.ts'):
        rel = p.relative_to(ROOT).as_posix()
        text = p.read_text(encoding='utf-8', errors='ignore')
        for m in re.finditer(r'app\.(get|post|put|patch|delete)\("([^\"]+)"\s*,\s*([^\n]+)', text, re.I):
            method = m.group(1).upper()
            path = normalize(m.group(2))
            if path.startswith('/api/') or path.startswith('/images'):
                callback = m.group(3).strip()
                named = re.match(r'([A-Za-z_$][A-Za-z0-9_$]*)\s*[,)]', callback)
                handler = named.group(1) if named else f'{method} {path}'
                found[(method, path)] = RouteRecord(method, path, rel, handler)
    return [found[key] for key in sorted(found)]


def source_routes() -> set[tuple[str, str]]:
    return {(record.method, record.path) for record in source_route_records()}


def evidence_fragments(path: str) -> list[str]:
    # Require every static fragment around route parameters to appear in the cited
    # test. Checking only the prefix before the first {param} can falsely credit a
    # sibling endpoint (for example /chapters/{id}/publish) to a generic series test.
    fragments = []
    for fragment in re.split(r'\{[^}]+\}|\*', path):
        fragment = fragment.strip()
        if not fragment:
            continue
        # Preserve slashes because tests normally embed the URL path directly.
        fragments.append(fragment)
    return fragments or [path]


def main() -> int:
    actual = source_routes()
    if not MANIFEST.exists():
        print(f'ERROR: missing {MANIFEST.relative_to(ROOT)}', file=sys.stderr)
        return 2
    rows = []
    with MANIFEST.open(newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh, delimiter='\t')
        required = {'method', 'path', 'coverage', 'evidence'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            print('ERROR: endpoint coverage manifest has invalid header', file=sys.stderr)
            return 2
        rows = list(reader)
    declared = {(r['method'].upper(), normalize(r['path'])) for r in rows}
    missing = sorted(actual - declared)
    stale = sorted(declared - actual)
    errors = []
    if missing:
        errors.append('Unclassified source routes:\n' + '\n'.join(f'  {m} {p}' for m, p in missing))
    if stale:
        errors.append('Stale manifest routes:\n' + '\n'.join(f'  {m} {p}' for m, p in stale))
    for r in rows:
        coverage = r['coverage'].strip()
        if coverage not in {'functional', 'integration', 'e2e', 'authz', 'validation'}:
            errors.append(f"Invalid coverage level for {r['method']} {r['path']}: {coverage}")
        evidence = ROOT / r['evidence'].strip()
        if not evidence.is_file():
            errors.append(f"Missing evidence file for {r['method']} {r['path']}: {r['evidence']}")
            continue
        text = evidence.read_text(encoding='utf-8', errors='ignore')
        missing_fragments = [fragment for fragment in evidence_fragments(r['path']) if fragment not in text]
        if missing_fragments:
            errors.append(
                f"Evidence file does not mention all route fragments for {r['method']} {r['path']}: "
                f"missing={missing_fragments!r} evidence={r['evidence']}"
            )
    if errors:
        print('\n\n'.join(errors), file=sys.stderr)
        return 1
    levels: dict[str, int] = {}
    for r in rows:
        levels[r['coverage']] = levels.get(r['coverage'], 0) + 1
    print(f'API route coverage audit PASS: {len(actual)} source routes classified')
    print('Coverage classes: ' + ', '.join(f'{k}={v}' for k, v in sorted(levels.items())))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
