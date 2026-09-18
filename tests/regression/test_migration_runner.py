"""Executable shell-runner contracts; these do not simulate PostgreSQL semantics."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "ops/migrate"


class MigrationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.migrations = self.root / "migrations with spaces"
        self.migrations.mkdir()
        self.names = ["047_consolidate_reading_state_rc482.sql", "048_rc483_current_baseline.sql"]
        for name in self.names:
            (self.migrations / name).write_bytes((ROOT / "db/migrations" / name).read_bytes())
        self.hook = self.root / "preserve.sql"
        self.hook.write_text("-- preservation fixture\nSELECT 'preserved';\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # Record the fully rendered input seen by psql, without emulating SQL.
        (self.bin / "psql").write_text(
            "#!/usr/bin/env python3\nimport os, pathlib, sys\n"
            "p = pathlib.Path(os.environ['RECORD'])\n"
            "with p.open('a') as out: out.write(repr(sys.argv[1:]) + '\\n')\n"
            "f = next(a.split('=',1)[1] for a in sys.argv if a.startswith('--file='))\n"
            "pathlib.Path(os.environ['SCRIPT']).write_bytes(pathlib.Path(f).read_bytes())\n"
            "sys.exit(int(os.environ.get('PSQL_EXIT','0')))\n"
        )
        (self.bin / "psql").chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        RECORD=str(self.root / "calls"), SCRIPT=str(self.root / "script.sql"),
                        MREADER_MIGRATIONS_DIR=str(self.migrations),
                        MREADER_READING_PRESERVATION_SQL=str(self.hook),
                        TMPDIR=str(self.root))

    def render(self):
        return subprocess.run(["sh", str(RUNNER / "render.sh"), str(self.migrations), str(self.hook)],
                              text=True, capture_output=True, env=self.env)

    def apply(self):
        return subprocess.run(["sh", str(RUNNER / "apply.sh"), "-d", "fixture database"],
                              text=True, capture_output=True, env=self.env)

    def test_preservation_and_original_bodies_are_inside_each_transaction(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        script = result.stdout
        self.assertLess(script.index("pg_advisory_lock(77160485, 1)"), script.index("CREATE TABLE"))
        self.assertEqual(script.count("AS apply_migration \\gset"), 2)
        self.assertEqual(script.count("\\if :apply_migration"), 2)
        for name in self.names:
            body = (self.migrations / name).read_text()
            self.assertIn("BEGIN;\n" + self.hook.read_text() + "\n" + body, script)
            self.assertLess(script.index(body), script.index("INSERT INTO schema_migrations(version) VALUES ('" + name + "')"))
        self.assertTrue(script.rstrip().endswith("SELECT pg_advisory_unlock(77160485, 1);"))

    def test_one_connection_and_temporary_input_cleanup(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = (self.root / "calls").read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertIn("'-X'", calls[0])
        self.assertIn("'ON_ERROR_STOP=1'", calls[0])
        self.assertIn("'fixture database'", calls[0])
        self.assertIn("pg_advisory_lock", (self.root / "script.sql").read_text())
        self.assertEqual(list(self.root.glob("mreader-migrations.*")), [])

    def test_psql_failure_is_returned_and_temp_input_removed(self):
        self.env["PSQL_EXIT"] = "23"
        result = self.apply()
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(list(self.root.glob("mreader-migrations.*")), [])

    def test_missing_hook_cannot_connect_or_apply_partial_input(self):
        self.hook.unlink()
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "calls").exists())

    def test_missing_and_empty_migration_directory_fail_before_connect(self):
        for path in [self.root / "absent", self.root / "empty"]:
            if path.name == "empty":
                path.mkdir()
            self.env["MREADER_MIGRATIONS_DIR"] = str(path)
            self.assertNotEqual(self.apply().returncode, 0)
            self.assertFalse((self.root / "calls").exists())

    def test_invalid_version_name_fails_before_connect(self):
        (self.migrations / "049_bad'\\name.sql").write_text("SELECT 1;\n")
        self.assertNotEqual(self.apply().returncode, 0)
        self.assertFalse((self.root / "calls").exists())


if __name__ == "__main__":
    unittest.main()
