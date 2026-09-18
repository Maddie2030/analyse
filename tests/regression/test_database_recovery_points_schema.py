from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "db/migrations/049_database_recovery_points.sql"


class DatabaseRecoveryPointsSchemaTests(unittest.TestCase):
    def test_inventory_is_a_rebuildable_projection_without_absolute_paths(self):
        sql = MIGRATION.read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS database_recovery_points", sql)
        self.assertIn("public_id TEXT NOT NULL UNIQUE", sql)
        self.assertIn("recovery_id TEXT PRIMARY KEY", sql)
        self.assertIn("relative_directory TEXT NOT NULL", sql)
        self.assertIn("available BOOLEAN NOT NULL DEFAULT TRUE", sql)
        self.assertIn("last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()", sql)
        self.assertNotIn("absolute_path", sql)
        self.assertNotIn("host_path", sql)
        self.assertNotIn("remote_url", sql)

    def test_schema_enforces_owned_kinds_purposes_and_safe_relative_targets(self):
        sql = MIGRATION.read_text()
        for value in (
            "logical_dump",
            "physical_snapshot",
            "automatic",
            "manual",
            "pre-upgrade",
            "pre-restore",
            "snapshot",
        ):
            self.assertIn(value, sql)
        self.assertIn("relative_directory !~", sql)
        self.assertIn("relative_directory NOT LIKE '%..%'", sql)
        self.assertIn("artifact_name IN ('database.dump','snapshot.tar')", sql)
        self.assertIn("sha256 ~ '^[0-9a-f]{64}$'", sql)

    def test_catalog_queries_have_newest_available_index(self):
        sql = MIGRATION.read_text()
        self.assertIn("idx_database_recovery_points_available_created", sql)
        self.assertIn("WHERE available AND verified", sql)


if __name__ == "__main__":
    unittest.main()
