import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.regression.test_local_recovery_catalog import create_logical_bundle


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/backup/sync-local-recovery-catalog.sh"


class SyncLocalRecoveryCatalogTests(unittest.TestCase):
    def run_sync(self, *, fail=False):
        temporary = tempfile.TemporaryDirectory(prefix="mreader-sync-catalog-")
        fixture = Path(temporary.name)
        recovery = fixture / "recovery root"
        create_logical_bundle(
            recovery, "manual", "manual-sync", "2026-09-12T03:00:00Z"
        )
        binary = fixture / "bin"
        binary.mkdir()
        capture = fixture / "psql-input"
        fake_psql = binary / "psql"
        fake_psql.write_text(
            """#!/usr/bin/env bash
sql="$(cat)"
printf "%s\n" "$sql" > "$DBP_SYNC_CAPTURE"
tsv="$(printf "%s\n" "$sql" | awk -F"'" '/^\\\\copy / {print $2; exit}')"
if [[ -n "$tsv" && -f "$tsv" ]]; then
  printf "TSV:%s\n" "$(cat "$tsv")" >> "$DBP_SYNC_CAPTURE"
fi
exit "${DBP_SYNC_FAIL:-0}"
"""
        )
        fake_psql.chmod(0o755)
        environment = dict(
            os.environ,
            PATH=f"{binary}:{os.environ['PATH']}",
            POSTGRES_BACKUP_LOCAL_ROOT=str(recovery),
            MREADER_LOCAL_RECOVERY_STORE=str(
                ROOT / "scripts/backup/local-recovery-store.sh"
            ),
            DBP_SYNC_CAPTURE=str(capture),
            DBP_SYNC_FAIL="42" if fail else "0",
            POSTGRES_HOST="db",
            POSTGRES_PORT="5432",
            POSTGRES_USER="mreader",
            POSTGRES_DB="mreader",
        )
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        return temporary, recovery, capture, result

    def test_sync_upserts_safe_relative_inventory_and_marks_missing(self):
        temporary, recovery, capture, result = self.run_sync()
        with temporary:
            self.assertEqual(result.returncode, 0, result.stderr)
            recorded = capture.read_text()
            self.assertIn("INSERT INTO database_recovery_points", recorded)
            self.assertIn("available=TRUE", recorded)
            self.assertIn("available=FALSE", recorded)
            self.assertIn("manual-sync", recorded)
            self.assertIn("dumps/manual/manual-sync", recorded)
            self.assertRegex(recorded, r"bkp_[0-9a-f]{24}")
            self.assertNotIn(str(recovery), recorded)

    def test_database_failure_is_not_reported_as_a_successful_sync(self):
        temporary, _recovery, _capture, result = self.run_sync(fail=True)
        with temporary:
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
