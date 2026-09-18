import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
WRAPPER = REPO / "scripts" / "diagnostics" / "ripwire-context.sh"


class RipwireContextWrapperTests(unittest.TestCase):
    def test_explicit_binary_override_is_used_without_path_install(self):
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "ripwire"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "printf 'FAKE_RIPWIRE:%s\\n' \"$*\"\n"
                "printf 'FAKE_PATH:%s\\n' \"$PATH\"\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            env = os.environ.copy()
            env["MREADER_RIPWIRE_BIN"] = str(fake)
            env["PATH"] = "/usr/bin:/bin"
            result = subprocess.run(
                ["bash", str(WRAPPER), "doctor"],
                cwd=REPO,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"FAKE_RIPWIRE:{REPO} --doctor --legend=compact", result.stdout)
            path_line = next(line for line in result.stdout.splitlines() if line.startswith("FAKE_PATH:"))
            self.assertEqual(Path(path_line.split(":", 1)[1].split(":", 1)[0]), Path(td))

    def test_wrapper_declares_workspace_local_binary_candidate(self):
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("../../tools/ripwire/bin/ripwire", text)


if __name__ == "__main__":
    unittest.main()
