from pathlib import Path
import unittest

from p10_1_ui_support import forbid_all, require_all

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend" / "src" / "pages" / "AdminDatabase.tsx"
APP = ROOT / "frontend" / "src" / "App.tsx"
CONFIG = ROOT / "services" / "scraper_service" / "app" / "config.py"
AGENT = ROOT / "scripts" / "backup" / "backup-agent.sh"
STORE = ROOT / "scripts" / "backup" / "local-recovery-store.sh"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class P101DatabaseProtectionUiTests(unittest.TestCase):
    def test_database_protection_is_admin_only_and_retains_all_guarded_actions(self):
        page = read(PAGE)
        app = read(APP)
        self.assertIn('<Route path="/admin/database" element={<AdminOnly><AdminDatabase /></AdminOnly>} />', app)
        for call in (
            "api.getDatabaseProtection(75, cursor)",
            "api.createDatabaseBackup",
            "api.createDatabaseSnapshot",
            "api.createDatabaseRestoreDrill(item.id)",
            "api.createDatabaseRestore(",
            "api.cancelDatabaseOperation(op.id)",
        ):
            self.assertIn(call, page)
        self.assertIn('/api/admin/database/backups/${encodeURIComponent(item.id)}/download', page)
        self.assertIn("installation_fingerprint", page)
        self.assertIn("restore_generation", page)

    def test_initial_status_failure_does_not_fabricate_zero_offline_or_empty_recovery_state(self):
        page = read(PAGE)
        require_all(self, page, (
            "data ? `${storage?.backup_count ?? 0} recovery points indexed` : 'Recovery point count unknown'",
            "data ? (storage?.local_storage_ready ? 'Ready' : 'Unavailable') : 'Unknown'",
            "data ? (runtime?.available ? (runtime.status === 'ready' ? 'Ready' : 'Degraded') : 'Offline') : 'Unknown'",
            "data && backups.length === 0", "!data && !loading",
            "Recovery catalog unavailable", "Operation history unavailable",
        ))

    def test_recovery_policy_keeps_4_2_retention_and_safety_pins(self):
        config = read(CONFIG)
        agent = read(AGENT)
        store = read(STORE)
        self.assertIn("postgres_backup_daily_retention_days: int = 4", config)
        self.assertIn("postgres_backup_snapshot_retention_days: int = 2", config)
        self.assertIn("build_retention_pin_file", agent)
        self.assertIn("retention_protection_snapshot", store)
        self.assertIn("current-pre-restore", store)
        self.assertIn("current-pre-upgrade", store)

    def test_host_storage_path_remains_backend_only(self):
        page = read(PAGE)
        require_all(self, page, ("Internal filesystem paths, storage endpoints and device details remain backend-only",))
        forbid_all(self, page, ("MREADER_DB_PROTECTION_ROOT", ".mreader/database-protection"))


if __name__ == "__main__":
    unittest.main()
