from __future__ import annotations

import json
import os
from pathlib import Path
from typing import NamedTuple

import pytest


class PrivilegeCase(NamedTuple):
    role: str
    object_type: str
    resource: str
    privilege: str
    id: str


class BaselineCase(NamedTuple):
    role: str
    check: str
    id: str


class MembershipCase(NamedTuple):
    workload: str
    role: str
    capability: str
    expected: bool
    id: str


def _repo_root() -> Path:
    configured = Path(os.getenv("MREADER_REPO_ROOT", "/repo"))
    if (configured / "contracts/ownership/postgres-roles.v1.json").is_file():
        return configured
    local = Path(__file__).resolve().parents[2]
    if (local / "contracts/ownership/postgres-roles.v1.json").is_file():
        return local
    raise RuntimeError("MReader ownership contract is unavailable to permission diagnostics")


CONTRACT_PATH = _repo_root() / "contracts/ownership/postgres-roles.v1.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
CAPABILITIES = {capability["name"]: capability for capability in CONTRACT["capabilities"]}


def _capability_cases() -> list[PrivilegeCase]:
    rows: list[PrivilegeCase] = []
    for capability in CONTRACT["capabilities"]:
        role = str(capability["name"])
        for grant in capability.get("grants", []):
            kind = str(grant["object_type"])
            resource = str(grant["resource"])
            for privilege in grant.get("privileges", []):
                privilege = str(privilege).lower()
                rows.append(
                    PrivilegeCase(
                        role,
                        kind,
                        resource,
                        privilege,
                        f"capability:{role}:{kind}:{resource}:{privilege}",
                    )
                )
    return rows


def _workload_cases() -> list[PrivilegeCase]:
    rows: list[PrivilegeCase] = []
    for workload in CONTRACT["workloads"]:
        workload_name = str(workload["workload"])
        role = str(workload["role"])
        for capability_name in workload.get("capabilities", []):
            capability = CAPABILITIES[str(capability_name)]
            for grant in capability.get("grants", []):
                kind = str(grant["object_type"])
                resource = str(grant["resource"])
                for privilege in grant.get("privileges", []):
                    privilege = str(privilege).lower()
                    rows.append(
                        PrivilegeCase(
                            role,
                            kind,
                            resource,
                            privilege,
                            (
                                f"workload:{workload_name}:{capability_name}:"
                                f"{kind}:{resource}:{privilege}"
                            ),
                        )
                    )
    return rows


def _membership_cases() -> list[MembershipCase]:
    capability_names = [str(capability["name"]) for capability in CONTRACT["capabilities"]]
    rows: list[MembershipCase] = []
    for workload in CONTRACT["workloads"]:
        workload_name = str(workload["workload"])
        role = str(workload["role"])
        declared = {str(name) for name in workload.get("capabilities", [])}
        for capability in capability_names:
            expected = capability in declared
            expectation = "member" if expected else "isolated"
            rows.append(
                MembershipCase(
                    workload_name,
                    role,
                    capability,
                    expected,
                    f"workload:{workload_name}:capability:{capability}:{expectation}",
                )
            )
    return rows


def _baseline_cases() -> list[BaselineCase]:
    rows: list[BaselineCase] = []
    for workload in CONTRACT["workloads"]:
        workload_name = str(workload["workload"])
        role = str(workload["role"])
        rows.extend(
            [
                BaselineCase(role, "database-connect", f"workload:{workload_name}:database-connect"),
                BaselineCase(role, "schema-usage", f"workload:{workload_name}:schema-usage"),
            ]
        )
    return rows


CAPABILITY_PRIVILEGE_CASES = _capability_cases()
WORKLOAD_PRIVILEGE_CASES = _workload_cases()
WORKLOAD_BASELINE_CASES = _baseline_cases()
WORKLOAD_MEMBERSHIP_CASES = _membership_cases()
pytestmark = pytest.mark.permission


def _role_oid(db, role: str) -> int | None:
    with db.cursor() as cur:
        cur.execute("SELECT oid FROM pg_roles WHERE rolname = %s", (role,))
        row = cur.fetchone()
    return int(row[0]) if row else None


def _has_privilege(db, role_oid: int, case: PrivilegeCase) -> bool:
    privilege = case.privilege.upper()
    qualified = f"public.{case.resource}"
    with db.cursor() as cur:
        if case.object_type in {"table", "view"}:
            cur.execute(
                "SELECT has_table_privilege(%s::oid, %s, %s)",
                (role_oid, qualified, privilege),
            )
        elif case.object_type == "sequence":
            cur.execute(
                "SELECT has_sequence_privilege(%s::oid, %s, %s)",
                (role_oid, qualified, privilege),
            )
        elif case.object_type == "function":
            cur.execute(
                """
                SELECT COALESCE(bool_and(has_function_privilege(%s::oid, p.oid, %s)), false)
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public' AND p.proname = %s
                """,
                (role_oid, privilege, case.resource),
            )
        else:
            raise AssertionError(f"unsupported permission object type: {case.object_type}")
        row = cur.fetchone()
    return bool(row and row[0])


@pytest.mark.parametrize("case", CAPABILITY_PRIVILEGE_CASES, ids=lambda case: case.id)
def test_declared_capability_privilege_is_effective(db, case: PrivilegeCase):
    role_oid = _role_oid(db, case.role)
    assert role_oid is not None, f"capability role is missing: {case.role}"
    assert _has_privilege(db, role_oid, case), (
        f"missing declared capability privilege: role={case.role} "
        f"object={case.object_type}:{case.resource} privilege={case.privilege}"
    )


@pytest.mark.parametrize("case", WORKLOAD_PRIVILEGE_CASES, ids=lambda case: case.id)
def test_workload_inherits_declared_capability_privilege(db, case: PrivilegeCase):
    role_oid = _role_oid(db, case.role)
    assert role_oid is not None, f"workload role is missing: {case.role}"
    assert _has_privilege(db, role_oid, case), (
        f"workload effective privilege drift: role={case.role} "
        f"object={case.object_type}:{case.resource} privilege={case.privilege}"
    )


@pytest.mark.parametrize("case", WORKLOAD_BASELINE_CASES, ids=lambda case: case.id)
def test_workload_database_and_schema_baseline(db, case: BaselineCase):
    role_oid = _role_oid(db, case.role)
    assert role_oid is not None, f"workload role is missing: {case.role}"
    with db.cursor() as cur:
        if case.check == "database-connect":
            cur.execute(
                "SELECT has_database_privilege(%s::oid, current_database(), 'CONNECT')",
                (role_oid,),
            )
        elif case.check == "schema-usage":
            cur.execute(
                "SELECT has_schema_privilege(%s::oid, 'public', 'USAGE')",
                (role_oid,),
            )
        else:
            raise AssertionError(f"unknown workload baseline check: {case.check}")
        row = cur.fetchone()
    assert bool(row and row[0]), f"missing workload baseline privilege: role={case.role} check={case.check}"


@pytest.mark.parametrize("case", WORKLOAD_MEMBERSHIP_CASES, ids=lambda case: case.id)
def test_workload_capability_membership_matches_contract(db, case: MembershipCase):
    role_oid = _role_oid(db, case.role)
    capability_oid = _role_oid(db, case.capability)
    assert role_oid is not None, f"workload role is missing: {case.role}"
    assert capability_oid is not None, f"capability role is missing: {case.capability}"
    with db.cursor() as cur:
        cur.execute(
            "SELECT pg_has_role(%s::oid, %s::oid, 'MEMBER')",
            (role_oid, capability_oid),
        )
        row = cur.fetchone()
    actual = bool(row and row[0])
    assert actual is case.expected, (
        "workload capability membership drift: "
        f"workload={case.workload} role={case.role} capability={case.capability} "
        f"expected={'member' if case.expected else 'isolated'} actual={actual}"
    )
