#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "contracts" / "ownership" / "routes.v1.json"
COVERAGE = ROOT / "tests" / "api" / "endpoint_coverage.tsv"
ROUTE_AUDIT = ROOT / "scripts" / "tests" / "api-route-audit.py"
USER_CADDY = ROOT / "deploy" / "docker-desktop-hybrid" / "Caddyfile.user"
ADMIN_CADDY = ROOT / "deploy" / "docker-desktop-hybrid" / "Caddyfile.admin"

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
SIDE_EFFECT_FREE_COMMANDS = {("POST", "/api/social/series/metrics-batch")}
BROWSER_CONSUMERS = {"web", "android", "admin-web"}


def load_route_audit():
    spec = importlib.util.spec_from_file_location("mreader_api_route_audit_for_ownership", ROUTE_AUDIT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ROUTE_AUDIT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"missing ownership manifest: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid ownership manifest JSON: {exc}") from exc
    if data.get("contract") != "mreader.ownership-routes" or data.get("version") != 1:
        raise ValueError("invalid ownership manifest contract/version")
    if not isinstance(data.get("routes"), list) or not data["routes"]:
        raise ValueError("ownership manifest routes must be a non-empty array")
    return data


def load_coverage(audit) -> dict[tuple[str, str], dict[str, str]]:
    with COVERAGE.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    return {(r["method"].upper(), audit.normalize(r["path"])): r for r in rows}


def expected_access_plane(method: str, path: str) -> str:
    if path.startswith("/internal/v1/"):
        return "internal"
    admin_prefixes = (
        "/api/admin/database",
        "/api/scraper",
        "/api/upload",
        "/api/catalog/admin",
        "/api/auth/admin",
        "/api/notifications/admin",
    )
    if path.startswith(admin_prefixes):
        return "admin"
    if path.startswith("/api/catalog") and method in MUTATING:
        return "admin"
    return "both"


def validate_gateway_policy_inputs(errors: list[str]) -> None:
    policies = {
        "user": (
            USER_CADDY,
            ["@adminApi path /api/admin/database", "@catalogWrite", "respond @internal 404", "reverse_proxy catalog-go:8080"],
        ),
        "admin": (
            ADMIN_CADDY,
            ["@databaseAdmin path /api/admin/database", "@scraper path /api/scraper", "@upload path /api/upload", "@catalogWrite", "respond @internal 404"],
        ),
    }
    for plane, (path, markers) in policies.items():
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in text:
                errors.append(f"{plane} gateway policy marker missing: {marker}")


def current_postgres_tables() -> set[str]:
    text = (ROOT / "db" / "init.sql").read_text(encoding="utf-8")
    for migration in (ROOT / "db" / "migrations").glob("*.sql"):
        text += "\n" + migration.read_text(encoding="utf-8", errors="ignore")
    return set(re.findall(r"CREATE TABLE IF NOT EXISTS\s+([A-Za-z0-9_]+)", text))


def first_party_client_corpora() -> dict[str, str]:
    roots = {
        "web": ROOT / "frontend" / "src",
        "admin-web": ROOT / "frontend" / "src",
        "android": ROOT / "android" / "app" / "src",
    }
    corpora: dict[str, str] = {}
    for kind, source_root in roots.items():
        parts = [
            source.read_text(encoding="utf-8", errors="ignore")
            for source in source_root.rglob("*")
            if source.is_file() and source.suffix in {".ts", ".tsx", ".js", ".jsx", ".kt"}
        ] if source_root.is_dir() else []
        corpora[kind] = "\n".join(parts)
    return corpora


def index_manifest_rows(rows: list[dict[str, Any]], audit, errors: list[str]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    operations: set[str] = set()
    for row in rows:
        method = str(row.get("method", "")).upper()
        path = audit.normalize(str(row.get("path", "")))
        key = (method, path)
        if key in indexed:
            errors.append(f"duplicate manifest route: {method} {path}")
        indexed[key] = row
        operation = str(row.get("operation", ""))
        if operation in operations:
            errors.append(f"duplicate operation: {operation}")
        operations.add(operation)
    return indexed


def validate_route_sets(source, coverage, manifest, errors: list[str]) -> None:
    source_keys, coverage_keys, manifest_keys = set(source), set(coverage), set(manifest)
    if source_keys != manifest_keys:
        errors.append(
            f"route set mismatch: missing={sorted(source_keys - manifest_keys)!r} "
            f"stale={sorted(manifest_keys - source_keys)!r}"
        )
    if source_keys != coverage_keys:
        errors.append("route set mismatch between source and endpoint coverage")


def validate_auth(method: str, path: str, plane: str, row: dict[str, Any], errors: list[str]) -> None:
    auth = row.get("authentication") or {}
    consumers = row.get("consumers") or []
    if plane == "internal":
        if auth.get("mode") != "workload-token" or auth.get("principal") != "workload":
            errors.append(f"internal route auth contradiction for {method} {path}")
        browser = [c for c in consumers if c.get("kind") in BROWSER_CONSUMERS]
        if browser:
            errors.append(f"internal route has browser consumers for {method} {path}: {browser!r}")
    if plane == "admin" and (auth.get("mode") != "admin-session" or auth.get("principal") != "admin"):
        errors.append(f"admin route auth contradiction for {method} {path}")


def validate_writes(method: str, path: str, row: dict[str, Any], postgres_tables: set[str], errors: list[str]) -> None:
    writes = row.get("permitted_writes")
    key = (method, path)
    if not isinstance(writes, list):
        errors.append(f"permitted_writes must be an array for {method} {path}")
        return
    if method in MUTATING and not writes and key not in SIDE_EFFECT_FREE_COMMANDS:
        errors.append(f"permitted_writes missing for mutating route {method} {path}")
    if method == "GET" and writes:
        errors.append(f"read-only GET route declares writes for {method} {path}")
    for write in writes:
        if write.get("kind") == "postgres" and write.get("resource") not in postgres_tables:
            errors.append(f"unknown postgres resource for {method} {path}: {write.get('resource')!r}")


def validate_consumers(method: str, path: str, row: dict[str, Any], corpora: dict[str, str], errors: list[str]) -> None:
    fragments = [fragment for fragment in re.split(r"\{[^}]+\}|\*", path) if len(fragment) >= 4]
    for consumer in row.get("consumers") or []:
        kind = consumer.get("kind")
        if kind in corpora and not any(fragment in corpora[kind] for fragment in fragments):
            errors.append(f"unproven {kind} consumer for {method} {path}")


def validate_evidence(method: str, path: str, row: dict[str, Any], coverage_row: dict[str, str], audit, errors: list[str]) -> None:
    evidence = row.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"evidence missing for {method} {path}")
        return
    expected = coverage_row["evidence"]
    if expected not in evidence:
        errors.append(f"evidence for {method} {path} must include endpoint coverage evidence {expected}")
    for evidence_name in evidence:
        evidence_path = ROOT / evidence_name
        if not evidence_path.is_file():
            errors.append(f"evidence file missing for {method} {path}: {evidence_name}")
            continue
        if evidence_name != expected:
            continue
        text = evidence_path.read_text(encoding="utf-8", errors="ignore")
        missing = [fragment for fragment in audit.evidence_fragments(path) if fragment not in text]
        if missing:
            errors.append(f"evidence file does not mention route fragments for {method} {path}: missing={missing!r} evidence={evidence_name}")


def validate_route(key, row, record, coverage_row, audit, postgres_tables, corpora, errors: list[str]) -> None:
    method, path = key
    expected_handler = f"{record.source}:{record.handler}"
    if row.get("handler") != expected_handler:
        errors.append(f"handler mismatch for {method} {path}: expected {expected_handler!r}")
    plane = expected_access_plane(method, path)
    if row.get("access_plane") != plane:
        errors.append(f"access_plane mismatch for {method} {path}: expected {plane!r}, got {row.get('access_plane')!r}")
    validate_auth(method, path, plane, row, errors)
    validate_writes(method, path, row, postgres_tables, errors)
    validate_consumers(method, path, row, corpora, errors)
    validate_evidence(method, path, row, coverage_row, audit, errors)


def validate_manifest(path: Path) -> list[str]:
    audit = load_route_audit()
    data = load_manifest(path)
    errors: list[str] = []
    validate_gateway_policy_inputs(errors)
    source = {(r.method, r.path): r for r in audit.source_route_records()}
    coverage = load_coverage(audit)
    manifest = index_manifest_rows(data["routes"], audit, errors)
    validate_route_sets(source, coverage, manifest, errors)
    postgres_tables = current_postgres_tables()
    corpora = first_party_client_corpora()
    for key in sorted(set(source) & set(manifest) & set(coverage)):
        validate_route(key, manifest[key], source[key], coverage[key], audit, postgres_tables, corpora, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit MReader route ownership contract against current source")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    try:
        errors = validate_manifest(args.manifest)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Ownership route audit PASS: {len(load_manifest(args.manifest)['routes'])} current routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
