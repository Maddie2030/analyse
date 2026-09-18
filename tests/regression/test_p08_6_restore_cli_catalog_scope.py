import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.regression.test_local_recovery_catalog import create_logical_bundle

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "scripts/backup/local-recovery-store.sh"
AGENT = ROOT / "scripts/backup/backup-agent.sh"
POSTGRES_RESTORE = ROOT / "scripts/backup/postgres-restore.sh"
CATALOG_RESTORE = ROOT / "scripts/recovery/catalog-restore.sh"
CATALOG_IMPORT = ROOT / "scripts/recovery/catalog-import.sql"


def run_store(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(STORE), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def source_contract_errors(path: Path, *, present=(), absent=()):
    source = path.read_text()
    return {
        "missing": [marker for marker in present if marker not in source],
        "unexpected": [marker for marker in absent if marker in source],
    }


class P086RecoveryStoreTests(unittest.TestCase):
    def test_store_resolves_verified_bundle_only_by_opaque_public_id(self):
        with tempfile.TemporaryDirectory(prefix="mreader-p086-public-id-") as directory:
            root = Path(directory)
            create_logical_bundle(root, "manual", "manual-one", "2026-09-13T01:02:03Z")
            catalog = run_store("catalog", str(root))
            self.assertEqual(catalog.returncode, 0, catalog.stderr)
            item = json.loads(catalog.stdout)["recovery_points"][0]
            public_id = item["public_id"]
            self.assertRegex(public_id, r"^bkp_[0-9a-f]{24}$")

            resolved = run_store("resolve-public-id", str(root), public_id)
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            resolved_item = json.loads(resolved.stdout)
            self.assertEqual(resolved_item["public_id"], public_id)
            self.assertEqual(resolved_item["recovery_id"], "manual-one")
            self.assertTrue(resolved_item["verified"])

            unsafe = run_store("resolve-public-id", str(root), "../../manual-one")
            self.assertNotEqual(unsafe.returncode, 0)
            unknown = run_store("resolve-public-id", str(root), "bkp_" + "f" * 24)
            self.assertNotEqual(unknown.returncode, 0)

    def test_store_can_stage_verified_artifact_by_public_id_without_exposing_internal_id(self):
        with tempfile.TemporaryDirectory(prefix="mreader-p086-copy-public-") as directory:
            root = Path(directory)
            create_logical_bundle(root, "manual", "manual-two", "2026-09-13T02:03:04Z")
            item = json.loads(run_store("catalog", str(root)).stdout)["recovery_points"][0]
            destination = root / "staging" / "catalog-source.dump"
            copied = run_store("copy-public-artifact", str(root), item["public_id"], str(destination))
            self.assertEqual(copied.returncode, 0, copied.stderr)
            self.assertTrue(destination.is_file())
            copied_item = json.loads(copied.stdout)
            self.assertEqual(copied_item["public_id"], item["public_id"])
            self.assertEqual(copied_item["recovery_id"], "manual-two")

class P086RestoreEntrypointContractTests(unittest.TestCase):
    def test_catalog_restore_uses_containerized_recovery_store_without_host_jq(self):
        source = CATALOG_RESTORE.read_text()
        for marker in (
            'PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"',
            'mreader-local-recovery-store',
            'copy-public-artifact',
            '--no-deps',
            'MSYS_NO_PATHCONV=1 docker compose',
            'json.loads',
        ):
            self.assertIn(marker, source)
        self.assertNotIn('command -v jq', source)
        self.assertNotIn('LOCAL_STORE="$ROOT/scripts/backup/local-recovery-store.sh"', source)
        self.assertNotRegex(source, r'(?m)^\s*jq\s')

    def test_restore_entrypoints_share_canonical_verified_source_contract(self):
        contracts = (
            (
                POSTGRES_RESTORE,
                (
                    "bkp_[0-9a-f]",
                    'resolve-restore-request "$TARGET"',
                    'restore-public-id "$PUBLIC_ID" "$INSTALLATION_FINGERPRINT" "$RESTORE_GENERATION" "$SOURCE_SHA256"',
                    'TARGET="${1:-latest}"',
                    "latest-snapshot",
                ),
                (
                    'category="${TARGET%%/*}"',
                    'restore-backup "$category" "$filename"',
                    'restore-daily "$TARGET"',
                    'restore-backup snapshots "$TARGET"',
                ),
            ),
            (
                AGENT,
                (
                    "restore_public_id(){",
                    'resolve-public-id "$LOCAL_ROOT" "$public_id"',
                    "restore_backup_cli",
                    "restore-public-id)",
                ),
                (),
            ),
            (
                CATALOG_RESTORE,
                (
                    "--backup-id <bkp_...>",
                    "resolve-db-protection-root.sh",
                    "copy-public-artifact",
                    '"$MREADER_DB_PROTECTION_ROOT"',
                    "--check",
                    "--import",
                    "NAS SeaweedFS is read-only",
                ),
                (
                    "--source <backup.dump|snapshot.tar>",
                    '--source) SOURCE=',
                    "POSTGRES_BACKUP_NAS_PATH",
                    "recovery source not found: $SOURCE",
                ),
            ),
        )
        failures = {}
        for path, present, absent in contracts:
            errors = source_contract_errors(path, present=present, absent=absent)
            if errors["missing"] or errors["unexpected"]:
                failures[str(path.relative_to(ROOT))] = errors
        self.assertEqual(failures, {})

        agent = AGENT.read_text()
        block = agent[agent.index("restore_public_id(){"):agent.index("verify_restore_latest(){")]
        self.assertNotIn("queue_cli_database_operation restore", block)

class P086CatalogScopeTests(unittest.TestCase):
    def test_catalog_import_safety_capture_reuses_canonical_backup_engine(self):
        source = CATALOG_RESTORE.read_text()
        self.assertIn('run --rm backup_agent pre-restore "$SAFETY_LABEL"', source)
        self.assertIn('pre_import_backup_public_id=$SAFETY_PUBLIC_ID', source)
        self.assertNotIn('SAFETY="$ROOT/backups/recovery/pre-catalog-import-', source)
        self.assertNotIn('pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/pre-catalog-import.dump', source)

    def test_catalog_only_sql_keeps_empty_target_and_exact_seven_table_scope(self):
        sql = CATALOG_IMPORT.read_text()
        self.assertIn("catalog import requires an empty target catalog", sql)
        self.assertIn("EXISTS (SELECT 1 FROM series)", sql)
        self.assertIn("EXISTS (SELECT 1 FROM chapters)", sql)
        self.assertIn("EXISTS (SELECT 1 FROM pages)", sql)

        expected = {
            "genres",
            "tags",
            "series",
            "chapters",
            "pages",
            "series_genres",
            "series_tags",
        }
        temp_tables = {
            line.split()[3].removeprefix("recovery_")
            for line in sql.splitlines()
            if line.startswith("CREATE TEMP TABLE recovery_")
        }
        inserted = {
            line.split("(", 1)[0].split()[2]
            for line in sql.splitlines()
            if line.startswith("INSERT INTO ")
        }
        self.assertEqual(temp_tables, expected)
        self.assertEqual(inserted, expected)

        forbidden = {
            "users",
            "reading_progress",
            "chapter_reads",
            "bookmarks",
            "subscriptions",
            "comments",
            "notifications",
            "database_operations",
        }
        for table in forbidden:
            self.assertNotIn(f"INSERT INTO {table}", sql)
            self.assertNotIn(f"DELETE FROM {table}", sql)




if __name__ == "__main__":
    unittest.main()
