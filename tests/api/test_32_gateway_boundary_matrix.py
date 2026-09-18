from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import NamedTuple

import pytest


class RouteBoundaryCase(NamedTuple):
    operation: str
    method: str
    path: str
    access_plane: str
    owner: str
    id: str


def _repo_root() -> Path:
    configured = Path(os.getenv("MREADER_REPO_ROOT", "/repo"))
    if (configured / "contracts/ownership/routes.v1.json").is_file():
        return configured
    local = Path(__file__).resolve().parents[2]
    if (local / "contracts/ownership/routes.v1.json").is_file():
        return local
    raise RuntimeError("MReader route ownership contract is unavailable to boundary diagnostics")


ROUTES = json.loads(
    (_repo_root() / "contracts/ownership/routes.v1.json").read_text(encoding="utf-8")
)["routes"]


def _case(route: dict) -> RouteBoundaryCase:
    return RouteBoundaryCase(
        str(route["operation"]),
        str(route["method"]).upper(),
        str(route["path"]),
        str(route["access_plane"]),
        str(route["owner"]),
        f"route:{route['operation']}",
    )


ROUTE_BOUNDARY_CASES = [_case(route) for route in ROUTES]
ADMIN_ISOLATION_CASES = [_case(route) for route in ROUTES if route["access_plane"] == "admin"]
BOTH_PLANE_PARITY_CASES = [_case(route) for route in ROUTES if route["access_plane"] == "both"]
pytestmark = pytest.mark.boundary

_PARAM = re.compile(r"\{([^{}]+)\}")
_UUID = "00000000-0000-4000-8000-000000000127"


def _placeholder(name: str) -> str:
    lowered = name.lower()
    if "id" in lowered:
        return _UUID
    if "page" == lowered or lowered.endswith("_page"):
        return "1"
    if "thumbnail" in lowered or "filename" in lowered or lowered.endswith("_name"):
        return "diagnostic-missing.webp"
    return "diagnostic-missing"


def _materialize(path: str) -> str:
    return _PARAM.sub(lambda match: _placeholder(match.group(1)), path)


def _preflight(session, case: RouteBoundaryCase):
    origin = os.getenv("MREADER_TEST_ALLOWED_ORIGIN", "http://localhost:5173")
    return session.options(
        _materialize(case.path),
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": case.method,
            "Access-Control-Request-Headers": "content-type",
        },
        timeout=10,
    )


def _assert_routed(response, case: RouteBoundaryCase):
    assert response.status_code < 500, (
        f"gateway/service boundary returned {response.status_code}: "
        f"{case.method} {case.path}; body={response.text[:300]}"
    )
    assert response.headers.get("X-MReader-Owner") == case.owner, (
        f"route owner mismatch for {case.method} {case.path}: "
        f"expected {case.owner!r}, got {response.headers.get('X-MReader-Owner')!r}; "
        f"status={response.status_code}"
    )
    allow_origin = response.headers.get("Access-Control-Allow-Origin")
    if allow_origin:
        requested = os.getenv("MREADER_TEST_ALLOWED_ORIGIN", "http://localhost:5173")
        assert allow_origin in {"*", requested}, (
            f"unexpected CORS allow-origin {allow_origin!r} for {case.path}; "
            f"requested={requested!r}"
        )


@pytest.mark.parametrize("case", ROUTE_BOUNDARY_CASES, ids=lambda case: case.id)
def test_route_preflight_reaches_expected_gateway_owner(anonymous, admin_anonymous, case: RouteBoundaryCase):
    if case.access_plane == "internal":
        response = _preflight(anonymous, case)
        assert response.status_code == 404
        assert response.headers.get("X-MReader-Owner") is None
        return
    session = admin_anonymous if case.access_plane == "admin" else anonymous
    _assert_routed(_preflight(session, case), case)


@pytest.mark.parametrize("case", ADMIN_ISOLATION_CASES, ids=lambda case: f"user-fence:{case.operation}")
def test_admin_route_is_network_fenced_from_user_gateway(anonymous, case: RouteBoundaryCase):
    path = _materialize(case.path)
    kwargs = {"timeout": 10}
    if case.method in {"POST", "PUT", "PATCH"}:
        kwargs["json"] = {}
    response = anonymous.request(case.method, path, **kwargs)
    assert response.status_code == 404, (
        f"admin route leaked through user plane: {case.method} {case.path}; "
        f"status={response.status_code} body={response.text[:300]}"
    )
    assert response.headers.get("X-MReader-Owner") is None


@pytest.mark.parametrize("case", BOTH_PLANE_PARITY_CASES, ids=lambda case: f"both-plane:{case.operation}")
def test_both_plane_route_resolves_same_owner(anonymous, admin_anonymous, case: RouteBoundaryCase):
    user_response = _preflight(anonymous, case)
    admin_response = _preflight(admin_anonymous, case)
    _assert_routed(user_response, case)
    _assert_routed(admin_response, case)
