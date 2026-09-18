from __future__ import annotations

import re
import unittest
from pathlib import Path
from tests.diagnostics.support import load_script

ROOT = Path(__file__).resolve().parents[2]
PERMISSION_TEST = ROOT / "tests/api/test_31_postgres_permission_matrix.py"
API_DOCKERFILE = ROOT / "tests/api/Dockerfile"
RUNNER = ROOT / "tests/diagnostics/runner.py"
BOUNDARY_TEST = ROOT / "tests/api/test_32_gateway_boundary_matrix.py"
VALIDATOR = ROOT / "scripts/validate-current-release.sh"


class P127DeepDiagnosticsContractTests(unittest.TestCase):
    def test_permission_oracle_defines_at_least_500_individually_named_cases(self):
        self.assertTrue(PERMISSION_TEST.is_file(), "live permission matrix test module is missing")
        module = load_script(PERMISSION_TEST)
        cases = [
            *module.CAPABILITY_PRIVILEGE_CASES,
            *module.WORKLOAD_PRIVILEGE_CASES,
            *module.WORKLOAD_BASELINE_CASES,
            *module.WORKLOAD_MEMBERSHIP_CASES,
        ]
        self.assertGreaterEqual(len(cases), 800)
        ids = [case.id for case in cases]
        self.assertEqual(len(ids), len(set(ids)), "permission case IDs must be unique")

    def test_gateway_boundary_matrix_covers_every_route_and_admin_fence(self):
        self.assertTrue(BOUNDARY_TEST.is_file(), "gateway boundary matrix is missing")
        module = load_script(BOUNDARY_TEST)
        self.assertEqual(139, len(module.ROUTE_BOUNDARY_CASES))
        self.assertEqual(
            sum(route["access_plane"] == "admin" for route in module.ROUTES),
            len(module.ADMIN_ISOLATION_CASES),
        )
        self.assertGreaterEqual(len(module.ROUTE_BOUNDARY_CASES) + len(module.ADMIN_ISOLATION_CASES), 200)

    def test_packaging_and_release_integration_contracts(self):
        docker_sources = set(re.findall(r"^COPY\s+(\S+)", API_DOCKERFILE.read_text(encoding="utf-8"), re.M))
        self.assertSetEqual({"contracts"}, docker_sources & {"contracts"})
        validator_targets = set(re.findall(r"tests\.regression\.test_p12_7_[A-Za-z0-9_]+", VALIDATOR.read_text(encoding="utf-8")))
        self.assertTrue({
            "tests.regression.test_p12_7_permission_surface",
            "tests.regression.test_p12_7_deep_diagnostics_contracts",
        }.issubset(validator_targets))

    def test_diagnostics_runner_executes_permission_oracle_before_functionality(self):
        runner = load_script(RUNNER)
        names = [name for name, _command in runner._diagnostic_commands("full", False)]
        self.assertIn("pytest-permissions", names)
        self.assertLess(names.index("pytest-permissions"), names.index("pytest-api"))
        commands = dict(runner._diagnostic_commands("full", False))
        permission_command = commands["pytest-permissions"]
        boundary_command = commands["pytest-boundary"]
        self.assertIn("/tests/test_31_postgres_permission_matrix.py", permission_command)
        self.assertIn("PYTEST_RESULTS_DIR=/results/pytest/permissions", permission_command)
        self.assertIn("PYTEST_RESULTS_DIR=/results/pytest/boundary", boundary_command)


if __name__ == "__main__":
    unittest.main()
