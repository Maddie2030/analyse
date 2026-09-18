from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/ownership/postgres-roles.v1.json"
RENDER_GENERATION = ROOT / "scripts/hybrid/render-generation-manifests.py"
RENDER_INDEX = ROOT / "scripts/hybrid/render-db-deployment-index.py"
USER_APPS = ROOT / "deploy/docker-desktop-hybrid/user-apps.yaml"
ADMIN_APPS = ROOT / "deploy/docker-desktop-hybrid/admin-apps.yaml"


class P094DeploymentIndexTests(unittest.TestCase):
    def test_generated_manifest_index_completes_and_maps_all_database_workloads(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        expected = {
            row["workload"]
            for row in contract["workloads"]
            if row["workload"] != "keda-postgres"
        }
        token = "p094-" + ("a" * 64)

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "manifests"
            subprocess.run(
                [
                    sys.executable,
                    str(RENDER_GENERATION),
                    "--contract",
                    str(CONTRACT),
                    "--generation",
                    token,
                    "--input",
                    str(USER_APPS),
                    "--input",
                    str(ADMIN_APPS),
                    "--output-dir",
                    str(output_dir),
                ],
                check=True,
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(RENDER_INDEX),
                    "--contract",
                    str(CONTRACT),
                    "--manifest",
                    str(output_dir / "user-apps.yaml"),
                    "--manifest",
                    str(output_dir / "admin-apps.yaml"),
                ],
                check=True,
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=5,
            )

        rows = [line.split("\t", 1) for line in result.stdout.splitlines() if line]
        self.assertEqual(expected, {workload for _, workload in rows})
        self.assertEqual(len(expected), len(rows))
        self.assertTrue(all(namespace in {"mreader-user", "mreader-admin"} for namespace, _ in rows))


    def test_hybrid_p09_metadata_matchers_are_line_bounded(self) -> None:
        checked = [
            ROOT / "scripts/hybrid/render-generation-manifests.py",
            ROOT / "scripts/hybrid/deploy.sh",
            ROOT / "scripts/test/p09-4-runtime-gate.sh",
        ]
        for path in checked:
            with self.subTest(path=path):
                self.assertNotIn("(?ms)^metadata:", path.read_text(encoding="utf-8"))

    def test_deploy_uses_file_backed_indexer_not_stdin_python(self) -> None:
        deploy = (ROOT / "scripts/hybrid/deploy.sh").read_text(encoding="utf-8")
        self.assertIn("render-db-deployment-index.py", deploy)
        self.assertNotIn('"$PYTHON_RUNTIME" - "$POSTGRES_ROLE_CONTRACT" "$GENERATION_MANIFEST_DIR/user-apps.yaml"', deploy)


if __name__ == "__main__":
    unittest.main()
