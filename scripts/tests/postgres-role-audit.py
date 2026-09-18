#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "contracts" / "ownership" / "postgres-roles.v1.json"
ROUTES = ROOT / "contracts" / "ownership" / "routes.v1.json"
OWNERSHIP_AUDIT = ROOT / "scripts" / "run-ownership-route-audit.sh"
WRITE_PRIVS = {"insert", "update", "delete"}
BOOTSTRAP_KEYS = {"POSTGRES_USER", "POSTGRES_PASSWORD", "DATABASE_URL"}
OWNER_CAPABILITY = {
    "auth": "auth_runtime",
    "catalog": "catalog_runtime",
    "progress": "progress_runtime",
    "social": "social_runtime",
    "notifications": "social_runtime",
    "reader": "reader_runtime",
    "scraper": "scraper_runtime",
    "media": "media_runtime",
    "realtime": "realtime_runtime",
    "database-protection": "database_protection_api_runtime",
}


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load {path}: {exc}") from exc


def current_schema_objects() -> tuple[set[str], set[str], set[str], set[str]]:
    text = (ROOT / "db" / "init.sql").read_text(encoding="utf-8", errors="ignore")
    for migration in sorted((ROOT / "db" / "migrations").glob("*.sql")):
        text += "\n" + migration.read_text(encoding="utf-8", errors="ignore")
    create_table = re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?[\"`]?([A-Za-z_][\w]*)", re.I)
    drop_table = re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?[\"`]?([A-Za-z_][\w]*)", re.I)
    create_view = re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:public\.)?[\"`]?([A-Za-z_][\w]*)", re.I)
    create_function = re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?[\"`]?([A-Za-z_][\w]*)", re.I)
    create_sequence = re.compile(r"\bCREATE\s+SEQUENCE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?[\"`]?([A-Za-z_][\w]*)", re.I)
    create_table_body = re.compile(
        r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?[\"`]?([A-Za-z_][\w]*)[\"`]?\s*\((.*?)\)\s*;",
        re.I | re.S,
    )
    serial_column = re.compile(
        r"(?:^|,)\s*[\"`]?([A-Za-z_][\w]*)[\"`]?\s+(?:BIG)?SERIAL\b", re.I
    )
    tables = set(create_table.findall(text)) - set(drop_table.findall(text))
    sequences = set(create_sequence.findall(text))
    for table, body in create_table_body.findall(text):
        for column in serial_column.findall(body):
            sequences.add(f"{table}_{column}_seq")
    return tables, set(create_view.findall(text)), set(create_function.findall(text)), sequences


def p09_2_required_writes(routes: dict[str, Any]) -> dict[str, dict[str, set[str]]]:
    required: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for route in routes.get("routes", []):
        owner = route.get("owner")
        for write in route.get("permitted_writes", []):
            if write.get("kind") != "postgres":
                continue
            capability = OWNER_CAPABILITY.get(str(owner))
            if not capability:
                raise ValueError(f"unmapped P09.2 postgres owner: {owner}")
            required[capability][str(write.get("resource"))].update(str(a).lower() for a in write.get("actions", []))
    return required


def capability_grants(contract: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {str(cap["name"]): list(cap.get("grants", [])) for cap in contract.get("capabilities", [])}


def grant_write_index(grants: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, set[str]]]:
    indexed: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for capability, rows in grants.items():
        for grant in rows:
            if grant.get("object_type") not in {"table", "view"}:
                continue
            indexed[capability][str(grant.get("resource"))].update(
                p for p in (str(v).lower() for v in grant.get("privileges", [])) if p in WRITE_PRIVS
            )
    return indexed


def validate_schema_resources(contract: dict[str, Any], errors: list[str]) -> None:
    tables, views, functions, sequences = current_schema_objects()
    for capability in contract.get("capabilities", []):
        for grant in capability.get("grants", []):
            kind, resource = grant.get("object_type"), str(grant.get("resource", ""))
            if kind == "table" and resource not in tables:
                errors.append(f"unknown postgres table: {resource} ({capability.get('name')})")
            elif kind == "view" and resource not in views:
                errors.append(f"unknown postgres view: {resource} ({capability.get('name')})")
            elif kind == "function" and resource not in functions:
                errors.append(f"unknown postgres function: {resource} ({capability.get('name')})")
            elif kind == "sequence" and resource not in sequences:
                errors.append(f"unknown postgres sequence: {resource} ({capability.get('name')})")


def validate_capability_security(contract: dict[str, Any], errors: list[str]) -> set[str]:
    names: set[str] = set()
    for capability in contract.get("capabilities", []):
        name = str(capability.get("name", ""))
        if name in names:
            errors.append(f"duplicate capability: {name}")
        names.add(name)
        if capability.get("login") != "NOLOGIN" or capability.get("role_attributes"):
            errors.append(f"unsafe capability role attributes: {name}")
    return names


def validate_workload_security(contract: dict[str, Any], capabilities: set[str], errors: list[str]) -> None:
    workloads, roles = set(), set()
    for workload in contract.get("workloads", []):
        name, role = str(workload.get("workload", "")), str(workload.get("role", ""))
        if name in workloads or role in roles:
            errors.append(f"duplicate workload/role identity: {name}/{role}")
        workloads.add(name); roles.add(role)
        if workload.get("login") != "LOGIN" or workload.get("role_attributes"):
            errors.append(f"unsafe workload role attributes: {name}")
        if str(workload.get("dsn_env", "")) in BOOTSTRAP_KEYS:
            errors.append(f"bootstrap credential is not a workload DSN: {name}")
        missing = set(workload.get("capabilities", [])) - capabilities
        if missing:
            errors.append(f"unknown capability membership for {name}: {sorted(missing)}")
        scope = ROOT / str(workload.get("scope_file", ""))
        if not scope.is_file():
            errors.append(f"workload scope file missing: {name}: {scope}")


def validate_role_security(contract: dict[str, Any], errors: list[str]) -> None:
    validate_workload_security(contract, validate_capability_security(contract, errors), errors)


def validate_request_write_coverage(contract: dict[str, Any], routes: dict[str, Any], errors: list[str]) -> None:
    required = p09_2_required_writes(routes)
    actual = grant_write_index(capability_grants(contract))
    for capability, resources in required.items():
        for resource, actions in resources.items():
            missing = actions - actual.get(capability, {}).get(resource, set())
            if missing:
                errors.append(
                    f"uncovered P09.2 postgres write: capability={capability} resource={resource} privileges={sorted(missing)}"
                )


def validate_extra_writes(contract: dict[str, Any], routes: dict[str, Any], errors: list[str]) -> None:
    required = p09_2_required_writes(routes)
    actual = grant_write_index(capability_grants(contract))
    exceptions = {
        (str(exc.get("resource")), str(priv).lower())
        for exc in contract.get("worker_exceptions", [])
        for priv in exc.get("privileges", [])
        if str(priv).lower() in WRITE_PRIVS
    }
    for capability, resources in actual.items():
        for resource, actions in resources.items():
            route_actions = required.get(capability, {}).get(resource, set())
            for action in actions - route_actions:
                if (resource, action) not in exceptions:
                    errors.append(
                        f"undocumented extra write: capability={capability} resource={resource} privilege={action}"
                    )


def validate_worker_exceptions(contract: dict[str, Any], errors: list[str]) -> None:
    workloads = {w.get("workload") for w in contract.get("workloads", [])}
    for exc in contract.get("worker_exceptions", []):
        if exc.get("workload") not in workloads:
            errors.append(f"worker exception names unknown workload: {exc.get('workload')}")
        for evidence in exc.get("evidence", []):
            if not (ROOT / str(evidence)).exists():
                errors.append(f"worker exception evidence missing: {evidence}")


def privileges_for(contract: dict[str, Any], capability_name: str, resource: str) -> set[str]:
    for capability in contract.get("capabilities", []):
        if capability.get("name") != capability_name:
            continue
        for grant in capability.get("grants", []):
            if grant.get("resource") == resource:
                return {str(v).lower() for v in grant.get("privileges", [])}
    return set()


def validate_special_boundaries(contract: dict[str, Any], errors: list[str]) -> None:
    keda = capability_grants(contract).get("keda_metrics_runtime", [])
    for grant in keda:
        if set(map(str.lower, grant.get("privileges", []))) & WRITE_PRIVS:
            errors.append(f"KEDA must be read-only: {grant.get('resource')}")
    social_notifications = privileges_for(contract, "social_runtime", "notifications")
    if "insert" in social_notifications:
        errors.append("notification boundary: social_runtime must not create notifications")
    worker_notifications = privileges_for(contract, "notification_worker_runtime", "notifications")
    if "insert" not in worker_notifications:
        errors.append("notification boundary: notification_worker_runtime must create notifications")
    relay = privileges_for(contract, "outbox_relay_runtime", "event_outbox")
    if "update" not in relay or "insert" in relay:
        errors.append("outbox boundary: relay requires update without producer insert")
    lifecycle = privileges_for(contract, "lifecycle_worker_runtime", "lifecycle_cleanup_jobs")
    if not {"update", "delete"} <= lifecycle or "insert" in lifecycle:
        errors.append("lifecycle boundary: worker requires execute/status rights without enqueue insert")
    trending = privileges_for(contract, "reader_runtime", "series_trending_hourly")
    if not {"insert", "update", "delete"} <= trending:
        errors.append("reader trending boundary missing derived writer privileges")


def validate_contract(path: Path) -> list[str]:
    owner = subprocess.run([str(OWNERSHIP_AUDIT)], cwd=ROOT, text=True, capture_output=True, check=False)
    if owner.returncode != 0:
        raise ValueError("P09.2 ownership audit failed before P09.3 validation: " + owner.stderr.strip())
    contract, routes = load_json(path), load_json(ROUTES)
    if contract.get("contract") != "mreader.postgres-roles" or contract.get("version") != 1:
        raise ValueError("invalid postgres role contract/version")
    errors: list[str] = []
    validate_role_security(contract, errors)
    validate_schema_resources(contract, errors)
    validate_request_write_coverage(contract, routes, errors)
    validate_extra_writes(contract, routes, errors)
    validate_worker_exceptions(contract, errors)
    validate_special_boundaries(contract, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit MReader PostgreSQL runtime-role contract against current ownership/source")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args(argv)
    try:
        errors = validate_contract(args.contract)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
        return 1
    contract = load_json(args.contract)
    print(f"Postgres role audit PASS: {len(contract['capabilities'])} capabilities, {len(contract['workloads'])} workload identities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
