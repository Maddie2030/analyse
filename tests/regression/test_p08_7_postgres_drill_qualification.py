from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "scripts/backup/backup-agent.sh"
DRILL = ROOT / "scripts/backup/postgres-restore-drill.sh"
CATALOG_RESTORE = ROOT / "scripts/recovery/catalog-restore.sh"


def markers(path: Path, required=(), forbidden=()):
    text = path.read_text() if path.exists() else ""
    result = {
        "missing": [value for value in required if value not in text],
        "unexpected": [value for value in forbidden if value in text],
    }
    return {key: value for key, value in result.items() if value}


class P087DatabaseValidationContracts(unittest.TestCase):
    def test_drill_validates_schema_integrity_encoding_migrations_grants_and_scope(self):
        errors = markers(
            AGENT,
            required=(
                "validate_recovery_database_state(){",
                "current_setting('server_encoding')",
                "orphan_rows",
                "encoding_version <> 4",
                "NOT convalidated",
                "schema_migrations",
                "has_database_privilege",
                "has_table_privilege",
                "extra_databases",
                "latest_migration",
            ),
        )
        self.assertEqual(errors, {})

    def test_logical_and_snapshot_drills_publish_structured_validation_evidence(self):
        text = AGENT.read_text()
        for function_name in ("restore_drill_selected(){", "snapshot_restore_drill_selected(){"):
            start = text.index(function_name)
            block = text[start : text.find("\n}\n", start) + 3]
            self.assertIn("validate_recovery_database_state", block)
            self.assertIn("validation", block)
        self.assertIn('source_format:"logical-dump"', text)
        self.assertIn('source_format:"physical-snapshot"', text)


class P087OperatorDrillContracts(unittest.TestCase):
    def test_backup_agent_exposes_opaque_id_restore_drill_without_new_engine(self):
        errors = markers(
            AGENT,
            required=(
                "resolve_public_restore_target(){",
                "restore_drill_public_id(){",
                'resolve_public_restore_target "$public_id" category recovery_id',
                'run_cli_database_operation restore_drill "$category" "$recovery_id" verified',
                "restore-drill-public-id)",
            ),
            forbidden=("queue_cli_database_operation drill_v2",),
        )
        self.assertEqual(errors, {})

    def test_operator_drill_combines_read_only_nas_validation_with_restore_engine(self):
        errors = markers(
            DRILL,
            required=(
                "--backup-id",
                "catalog-restore.sh",
                "--check",
                "backup_agent restore-drill-public-id",
                "NAS/media validation",
            ),
            forbidden=("--import", "curl -X PUT", "curl -X DELETE"),
        )
        self.assertEqual(errors, {})
        catalog_text = CATALOG_RESTORE.read_text()
        self.assertIn("NAS SeaweedFS is read-only", catalog_text)


if __name__ == "__main__":
    unittest.main()
