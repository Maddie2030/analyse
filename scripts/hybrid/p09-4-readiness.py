#!/usr/bin/env python3
"""Pure helpers for P09.4 hybrid readiness and restore-generation enforcement."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FINGERPRINT = re.compile(r"^inst_[0-9a-f]{16}$")
MIGRATION = re.compile(r"^(\d+)_.*\.sql$")
FORBIDDEN_SCOPE_KEYS = {"POSTGRES_USER", "POSTGRES_PASSWORD", "DATABASE_URL", "POSTGRES_URL"}


class ReadinessError(ValueError):
    def __init__(self, category: str, detail: str):
        super().__init__(detail)
        self.category = category
        self.detail = detail


def latest_migration_name(migrations_dir: Path) -> str:
    candidates: list[tuple[int, str]] = []
    for path in migrations_dir.glob("*.sql"):
        match = MIGRATION.fullmatch(path.name)
        if match:
            candidates.append((int(match.group(1)), path.name))
    if not candidates:
        raise ReadinessError("schema-not-ready", f"no numbered migrations in {migrations_dir}")
    return max(candidates)[1]


def contract_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ReadinessError("grants-not-ready", f"cannot read role contract: {path}") from exc


def load_restore_control(path: Path) -> tuple[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReadinessError("generation-not-ready", f"cannot read restore control: {path}") from exc
    fingerprint = data.get("installation_fingerprint")
    generation = data.get("restore_generation")
    if not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(fingerprint):
        raise ReadinessError("generation-not-ready", "restore control installation fingerprint is invalid")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise ReadinessError("generation-not-ready", "restore control generation must be a positive integer")
    return fingerprint, generation


def _scope_keys(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReadinessError("credentials-not-ready", f"cannot read workload scope: {path}") from exc
    return {line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")}


def validate_workload_credentials(contract: dict, env: dict[str, str], root: Path) -> list[dict[str, str]]:
    validated: list[dict[str, str]] = []
    for row in contract.get("workloads", []):
        if row.get("workload") == "keda-postgres":
            continue
        workload = str(row.get("workload", ""))
        role = str(row.get("role", ""))
        dsn_env = str(row.get("dsn_env", ""))
        scope_file = str(row.get("scope_file", ""))
        if not workload or not role or not dsn_env or not scope_file:
            raise ReadinessError("credentials-not-ready", f"incomplete workload credential contract: {workload or role}")
        role_key = f"MREADER_DB_DSN_{role.upper()}"
        dsn = env.get(role_key, "")
        parsed = urlparse(dsn)
        if parsed.scheme not in {"postgresql", "postgres"} or parsed.username != role or not parsed.hostname:
            raise ReadinessError("credentials-not-ready", f"{workload}:{role_key}")
        scope_path = root / scope_file
        keys = _scope_keys(scope_path)
        if dsn_env not in keys:
            raise ReadinessError("credentials-not-ready", f"{workload}:{dsn_env} missing from scope")
        leaked = keys & FORBIDDEN_SCOPE_KEYS
        if leaked:
            raise ReadinessError("credentials-not-ready", f"{workload}:bootstrap database scope keys {sorted(leaked)}")
        validated.append({"workload": workload, "role": role, "dsn_env": dsn_env, "dsn_key": role_key})
    return validated


def deployment_generation_token(*, generation: int, installation_fingerprint: str, migration: str, contract_sha256: str) -> str:
    if generation < 1:
        raise ReadinessError("generation-not-ready", "generation must be positive")
    if not FINGERPRINT.fullmatch(installation_fingerprint):
        raise ReadinessError("generation-not-ready", "installation fingerprint is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", contract_sha256):
        raise ReadinessError("grants-not-ready", "role contract hash is invalid")
    payload = {
        "contract_sha256": contract_sha256,
        "installation_fingerprint_sha256": hashlib.sha256(installation_fingerprint.encode()).hexdigest(),
        "latest_migration": migration,
        "restore_generation": generation,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "p094-" + hashlib.sha256(serialized).hexdigest()


def render_readiness_sql(*, database: str, migration: str, installation_fingerprint: str, generation: int) -> str:
    if not IDENTIFIER.fullmatch(database):
        raise ReadinessError("schema-not-ready", f"invalid database identifier: {database}")
    if not migration.endswith(".sql"):
        raise ReadinessError("schema-not-ready", "latest migration identity is invalid")
    if not FINGERPRINT.fullmatch(installation_fingerprint) or generation < 1:
        raise ReadinessError("generation-not-ready", "restore control values are invalid")
    return "\n".join(
        [
            "\\set ON_ERROR_STOP on",
            "BEGIN;",
            "CREATE TEMP TABLE p094_expected(migration text, installation_fingerprint text, restore_generation bigint, database_name text) ON COMMIT DROP;",
            "INSERT INTO p094_expected VALUES (:'latest_migration', :'installation_fingerprint', :restore_generation::bigint, :'database_name');",
            "DO $p094$",
            "DECLARE restore_rows integer; expected record;",
            "BEGIN",
            "  SELECT * INTO STRICT expected FROM p094_expected;",
            "  IF current_database() <> expected.database_name THEN RAISE EXCEPTION 'P09.4 schema-not-ready: database mismatch'; END IF;",
            "  IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = expected.migration) THEN",
            "    RAISE EXCEPTION 'P09.4 schema-not-ready: latest migration missing';",
            "  END IF;",
            "  SELECT count(*) INTO restore_rows FROM database_restore_state WHERE singleton = TRUE;",
            "  IF restore_rows <> 1 THEN RAISE EXCEPTION 'P09.4 generation-not-ready: restore mirror row count'; END IF;",
            "  IF NOT EXISTS (",
            "    SELECT 1 FROM database_restore_state",
            "    WHERE singleton = TRUE",
            "      AND installation_fingerprint = expected.installation_fingerprint",
            "      AND restore_generation = expected.restore_generation",
            "  ) THEN RAISE EXCEPTION 'P09.4 generation-not-ready: host/database mirror mismatch'; END IF;",
            "END",
            "$p094$;",
            "ROLLBACK;",
            "",
        ]
    )


def _read_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReadinessError("credentials-not-ready", f"cannot read env file: {path}") from exc
    env: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        env[key.strip()] = value
    return env


def _load_contract(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReadinessError("grants-not-ready", f"cannot read role contract: {path}") from exc
    if data.get("contract") != "mreader.postgres-roles" or data.get("version") != 1:
        raise ReadinessError("grants-not-ready", "unsupported role contract/version")
    return data


def metadata(args: argparse.Namespace) -> dict[str, object]:
    contract = _load_contract(args.contract)
    migration = latest_migration_name(args.migrations_dir)
    fingerprint, generation = load_restore_control(args.control_file)
    validate_workload_credentials(contract, _read_env_file(args.env_file), args.root)
    contract_hash = contract_sha256(args.contract)
    token = deployment_generation_token(
        generation=generation,
        installation_fingerprint=fingerprint,
        migration=migration,
        contract_sha256=contract_hash,
    )
    return {
        "contract_sha256": contract_hash,
        "installation_fingerprint": fingerprint,
        "latest_migration": migration,
        "restore_generation": generation,
        "token": token,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P09.4 readiness and deployment-generation helper")
    sub = parser.add_subparsers(dest="command", required=True)
    meta = sub.add_parser("metadata")
    meta.add_argument("--contract", required=True, type=Path)
    meta.add_argument("--env-file", required=True, type=Path)
    meta.add_argument("--root", required=True, type=Path)
    meta.add_argument("--control-file", required=True, type=Path)
    meta.add_argument("--migrations-dir", required=True, type=Path)
    sql = sub.add_parser("sql")
    sql.add_argument("--database", required=True)
    sql.add_argument("--migration", required=True)
    sql.add_argument("--installation-fingerprint", required=True)
    sql.add_argument("--generation", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "metadata":
            print(json.dumps(metadata(args), sort_keys=True, separators=(",", ":")))
        else:
            print(
                render_readiness_sql(
                    database=args.database,
                    migration=args.migration,
                    installation_fingerprint=args.installation_fingerprint,
                    generation=args.generation,
                ),
                end="",
            )
    except ReadinessError as exc:
        print(f"P09_4_READINESS={exc.category} {exc.detail}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
