#!/usr/bin/env python3
"""Render deterministic, fail-closed PostgreSQL runtime-role reconciliation SQL."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FUNCTION_SIGNATURES = {
    "enqueue_event_outbox_v1": (
        "public.enqueue_event_outbox_v1("
        "TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, TEXT, JSONB, "
        "UUID, UUID, JSONB, TIMESTAMPTZ)"
    ),
}
PRIVILEGE_ORDER = ("select", "insert", "update", "delete", "truncate", "references", "trigger", "usage", "execute")


def sql_ident(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid PostgreSQL identifier: {value!r}")
    return '"' + value.replace('"', '""') + '"'


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def password_env(role: str) -> str:
    return f"MREADER_DB_ROLE_PASSWORD_{role.upper()}"


def load_contract(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("contract") != "mreader.postgres-roles" or data.get("version") != 1:
        raise ValueError("unsupported postgres role contract/version")
    return data


def ensure_roles(contract: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for capability in contract["capabilities"]:
        name = str(capability["name"])
        ident = sql_ident(name)
        literal = sql_literal(name)
        lines += [
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {literal}) THEN CREATE ROLE {ident} NOLOGIN; END IF; END $$;",
            f"ALTER ROLE {ident} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;",
        ]
    for workload in contract["workloads"]:
        role = str(workload["role"])
        ident = sql_ident(role)
        literal = sql_literal(role)
        key = password_env(role)
        password = os.environ.get(key, "")
        if not password:
            raise ValueError(f"missing required password environment variable: {key}")
        password_sql = sql_literal(password)
        lines += [
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {literal}) THEN CREATE ROLE {ident} LOGIN PASSWORD {password_sql}; END IF; END $$;",
            f"ALTER ROLE {ident} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {password_sql};",
        ]
    return lines


def revoke_runtime_surface(contract: dict[str, Any], database: str) -> list[str]:
    role_names = [str(c["name"]) for c in contract["capabilities"]] + [str(w["role"]) for w in contract["workloads"]]
    role_array = ", ".join(sql_literal(name) for name in role_names)
    db = sql_ident(database)
    lines = [
        "-- Reset current runtime objects explicitly. New objects remain inaccessible until this reconciler runs after migrations.",
        "DO $mreader_revoke$",
        "DECLARE",
        "  principal text;",
        "  obj record;",
        "BEGIN",
        f"  FOREACH principal IN ARRAY ARRAY[{role_array}] LOOP",
        "    FOR obj IN",
        "      SELECT c.relkind, n.nspname, c.relname",
        "      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace",
        "      WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','S')",
        "    LOOP",
        "      IF obj.relkind = 'S' THEN",
        "        EXECUTE format('REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM %I', obj.nspname, obj.relname, principal);",
        "      ELSE",
        "        EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM %I', obj.nspname, obj.relname, principal);",
        "      END IF;",
        "    END LOOP;",
        "    FOR obj IN",
        "      SELECT p.oid::regprocedure::text AS signature",
        "      FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace",
        "      WHERE n.nspname = 'public'",
        "    LOOP",
        "      EXECUTE format('REVOKE ALL PRIVILEGES ON FUNCTION %s FROM %I', obj.signature, principal);",
        "    END LOOP;",
        "  END LOOP;",
        "END",
        "$mreader_revoke$;",
    ]
    for name in role_names:
        ident = sql_ident(name)
        lines += [
            f"REVOKE ALL PRIVILEGES ON DATABASE {db} FROM {ident};",
            f"REVOKE ALL PRIVILEGES ON SCHEMA public FROM {ident};",
        ]
    return lines


def revoke_public_surface() -> list[str]:
    return [
        "DO $mreader_public_revoke$",
        "DECLARE obj record;",
        "BEGIN",
        "  -- Remove any legacy/broad PUBLIC relation privileges before exact runtime grants are reapplied.",
        "  FOR obj IN",
        "    SELECT c.relkind, n.nspname, c.relname",
        "    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace",
        "    WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','S')",
        "  LOOP",
        "    IF obj.relkind = 'S' THEN",
        "      EXECUTE format('REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM PUBLIC', obj.nspname, obj.relname);",
        "    ELSE",
        "      EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM PUBLIC', obj.nspname, obj.relname);",
        "    END IF;",
        "  END LOOP;",
        "  -- PostgreSQL grants EXECUTE on functions to PUBLIC by default; remove it from the current public surface.",
        "  FOR obj IN",
        "    SELECT p.oid::regprocedure::text AS signature",
        "    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace",
        "    WHERE n.nspname = 'public'",
        "  LOOP",
        "    EXECUTE format('REVOKE ALL PRIVILEGES ON FUNCTION %s FROM PUBLIC', obj.signature);",
        "  END LOOP;",
        "END",
        "$mreader_public_revoke$;",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;",
    ]


def verification_assertion(condition: str, label: str) -> str:
    return (
        "  IF NOT ("
        + condition
        + ") THEN RAISE EXCEPTION "
        + sql_literal(f"P09.3 effective privilege verification failed: {label}")
        + "; END IF;"
    )


def grant_verification_condition(role: str, grant: dict[str, Any], privilege: str) -> str:
    kind = str(grant["object_type"])
    resource = str(grant["resource"])
    sql_ident(resource)
    privilege_name = privilege.upper()
    if kind in {"table", "view"}:
        return (
            f"has_table_privilege({role}, "
            f"{sql_literal('public.' + resource)}, {sql_literal(privilege_name)})"
        )
    if kind == "sequence":
        return (
            f"has_sequence_privilege({role}, "
            f"{sql_literal('public.' + resource)}, {sql_literal(privilege_name)})"
        )
    if kind == "function":
        signature = FUNCTION_SIGNATURES.get(resource)
        if not signature:
            raise ValueError(f"missing exact function signature mapping: {resource}")
        return f"has_function_privilege({role}, {sql_literal(signature)}, {sql_literal(privilege_name)})"
    raise ValueError(f"unsupported object type: {kind}")


def verify_capability_privileges(capability: dict[str, Any]) -> list[str]:
    name = str(capability["name"])
    sql_ident(name)
    role = sql_literal(name)
    lines = [
        verification_assertion(
            "EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            + role
            + " AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb "
            "AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)",
            f"capability role baseline {name}",
        ),
        verification_assertion(
            f"has_schema_privilege({role}, 'public', 'USAGE')",
            f"schema USAGE {name}",
        ),
    ]
    for grant in capability.get("grants", []):
        resource = str(grant["resource"])
        kind = str(grant["object_type"])
        for privilege in grant.get("privileges", []):
            privilege_name = str(privilege).upper()
            lines.append(
                verification_assertion(
                    grant_verification_condition(role, grant, str(privilege)),
                    f"{name} {privilege_name} {kind} {resource}",
                )
            )
    return lines


def verify_workload_privileges(workload: dict[str, Any], capabilities: list[str], database: str) -> list[str]:
    role_name = str(workload["role"])
    sql_ident(role_name)
    role = sql_literal(role_name)
    lines = [
        verification_assertion(
            "EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            + role
            + " AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb "
            "AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)",
            f"workload role baseline {role_name}",
        ),
        verification_assertion(
            f"has_database_privilege({role}, {sql_literal(database)}, 'CONNECT')",
            f"database CONNECT {role_name}",
        ),
        verification_assertion(
            f"has_schema_privilege({role}, 'public', 'USAGE')",
            f"schema USAGE {role_name}",
        ),
    ]
    assigned = {str(capability) for capability in workload.get("capabilities", [])}
    for capability in capabilities:
        cap = sql_literal(capability)
        condition = f"pg_has_role({role}, {cap}, 'MEMBER')"
        label = f"membership {role_name}->{capability}"
        if capability not in assigned:
            condition = "NOT " + condition
            label = f"unexpected membership {role_name}->{capability}"
        lines.append(verification_assertion(condition, label))
    return lines


def verify_effective_privileges(contract: dict[str, Any], database: str) -> list[str]:
    """Render catalog assertions proving the exact role model applied successfully."""

    capabilities = [str(c["name"]) for c in contract["capabilities"]]
    lines = ["DO $mreader_verify$", "BEGIN"]
    for capability in contract["capabilities"]:
        lines.extend(verify_capability_privileges(capability))
    for workload in contract["workloads"]:
        lines.extend(verify_workload_privileges(workload, capabilities, database))
    lines += ["END", "$mreader_verify$;"]
    return lines


def grant_table_object(role: str, resource: str, ordered: list[str], columns: list[str]) -> list[str]:
    target = f"TABLE public.{sql_ident(resource)}"
    if not columns:
        return [f"GRANT {', '.join(ordered)} ON {target} TO {role};"]
    column_list = ", ".join(sql_ident(column) for column in columns)
    statements: list[str] = []
    for privilege in ordered:
        if privilege not in {"SELECT", "INSERT", "UPDATE", "REFERENCES"}:
            raise ValueError(f"column-scoped privilege not supported: {privilege} on {resource}")
        statements.append(f"GRANT {privilege} ({column_list}) ON {target} TO {role};")
    return statements


def grant_object(capability: str, grant: dict[str, Any]) -> list[str]:
    role = sql_ident(capability)
    kind = str(grant["object_type"])
    resource = str(grant["resource"])
    privileges = [str(p).lower() for p in grant.get("privileges", [])]
    unknown = set(privileges) - set(PRIVILEGE_ORDER)
    if unknown:
        raise ValueError(f"unsupported privileges for {capability}/{resource}: {sorted(unknown)}")
    ordered = [p.upper() for p in PRIVILEGE_ORDER if p in privileges]
    if not ordered:
        return []
    if kind in {"table", "view"}:
        return grant_table_object(role, resource, ordered, [str(c) for c in grant.get("columns", [])])
    if kind == "function":
        signature = FUNCTION_SIGNATURES.get(resource)
        if not signature:
            raise ValueError(f"missing exact function signature mapping: {resource}")
        return [f"GRANT {', '.join(ordered)} ON FUNCTION {signature} TO {role};"]
    if kind == "sequence":
        return [f"GRANT {', '.join(ordered)} ON SEQUENCE public.{sql_ident(resource)} TO {role};"]
    raise ValueError(f"unsupported object type: {kind}")


def apply_exact_grants(contract: dict[str, Any], database: str) -> list[str]:
    db = sql_ident(database)
    capabilities = [str(c["name"]) for c in contract["capabilities"]]
    lines: list[str] = []
    for capability in contract["capabilities"]:
        name = str(capability["name"])
        ident = sql_ident(name)
        lines.append(f"GRANT USAGE ON SCHEMA public TO {ident};")
        for grant in capability.get("grants", []):
            lines.extend(grant_object(name, grant))
    for workload in contract["workloads"]:
        role_name = str(workload["role"])
        role = sql_ident(role_name)
        for capability in capabilities:
            lines.append(f"REVOKE {sql_ident(capability)} FROM {role};")
        lines += [
            f"GRANT CONNECT ON DATABASE {db} TO {role};",
            f"GRANT USAGE ON SCHEMA public TO {role};",
        ]
        for capability in workload.get("capabilities", []):
            if str(capability) not in capabilities:
                raise ValueError(f"unknown capability membership for {role_name}: {capability}")
            lines.append(f"GRANT {sql_ident(str(capability))} TO {role};")
    return lines


def render(contract: dict[str, Any], database: str) -> str:
    sql_ident(database)
    parts = ["\\set ON_ERROR_STOP on", "BEGIN;"]
    parts.extend(ensure_roles(contract))
    parts.extend(revoke_runtime_surface(contract, database))
    parts.extend(revoke_public_surface())
    parts.extend(apply_exact_grants(contract, database))
    parts.extend(verify_effective_privileges(contract, database))
    parts += ["COMMIT;", ""]
    return "\n".join(parts)


def render_verify_only(contract: dict[str, Any], database: str) -> str:
    sql_ident(database)
    parts = ["\\set ON_ERROR_STOP on", "BEGIN;"]
    parts.extend(verify_effective_privileges(contract, database))
    parts += ["ROLLBACK;", ""]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render MReader PostgreSQL runtime role reconciliation SQL")
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--database", required=True)
    parser.add_argument("--mode", choices=("reconcile", "verify"), default="reconcile")
    args = parser.parse_args(argv)
    try:
        contract = load_contract(args.contract)
        sql = render(contract, args.database) if args.mode == "reconcile" else render_verify_only(contract, args.database)
        print(sql, end="")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
