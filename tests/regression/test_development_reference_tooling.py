import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "development-reference"


class DevelopmentReferenceToolingTests(unittest.TestCase):
    def test_builders_are_repo_relative_and_checkpoint_parameterized(self):
        expected = [
            SCRIPTS / "build_mreader_code_graph.py",
            SCRIPTS / "build_mreader_development_graph.py",
            SCRIPTS / "build-reference.sh",
            SCRIPTS / "mreader-impact.py",
        ]
        for path in expected:
            self.assertTrue(path.exists(), f"missing development-reference tool: {path.relative_to(ROOT)}")
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("/mnt/data/", text, f"hard-coded sandbox path in {path}")
            self.assertNotIn("7f52ea56269ee8c7a0103a432ec0b0691991ed25", text, f"stale checkpoint in {path}")


    def test_reference_builder_uses_shared_python_runtime(self):
        text = (SCRIPTS / "build-reference.sh").read_text(encoding="utf-8")
        self.assertIn('PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"', text)
        executable_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertFalse(
            any(line.startswith("python ") or line.startswith("python3 ") for line in executable_lines),
            "development-reference builder must not require host Python",
        )

    def test_generated_reference_directories_are_ignored(self):
        rules = {
            line.strip()
            for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("/graphify-out/", rules)
        self.assertIn("/development-reference/", rules)
        self.assertNotIn("docs/development-reference/", rules)
        self.assertNotIn("scripts/development-reference/", rules)

    def test_graph_builders_bind_outputs_to_requested_checkpoint(self):
        checkpoint = "0123456789abcdef0123456789abcdef01234567"
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "graphify-out"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "build_mreader_code_graph.py"),
                    "--root",
                    str(ROOT),
                    "--out",
                    str(out),
                    "--checkpoint",
                    checkpoint,
                ],
                check=True,
                cwd=ROOT,
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "build_mreader_development_graph.py"),
                    "--root",
                    str(ROOT),
                    "--out",
                    str(out),
                    "--checkpoint",
                    checkpoint,
                ],
                check=True,
                cwd=ROOT,
            )

            code_meta = json.loads((out / "CODE-GRAPH-METADATA.json").read_text(encoding="utf-8"))
            dev_meta = json.loads((out / "DEVELOPMENT-GRAPH-METADATA.json").read_text(encoding="utf-8"))
            graph = json.loads((out / "development-graph.json").read_text(encoding="utf-8"))

            self.assertEqual(code_meta["source_checkpoint"], checkpoint)
            self.assertEqual(dev_meta["source_checkpoint"], checkpoint)
            self.assertEqual(dev_meta["routes"], 139)
            self.assertEqual(graph["graph"]["source_checkpoint"], checkpoint)
            self.assertGreater(code_meta["nodes"], 1000)
            self.assertGreater(dev_meta["nodes"], 500)


if __name__ == "__main__":
    unittest.main()
