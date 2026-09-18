import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "services/scraper_service/app/local_recovery_catalog.py"


def load_module():
    spec = importlib.util.spec_from_file_location("local_recovery_catalog", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_database_protection_module():
    asyncpg = types.ModuleType("asyncpg")
    asyncpg.Record = object
    asyncpg.Pool = object
    asyncpg.PostgresError = RuntimeError
    httpx = types.ModuleType("httpx")
    httpx.AsyncClient = object
    httpx.HTTPError = RuntimeError
    previous_asyncpg = sys.modules.get("asyncpg")
    previous_httpx = sys.modules.get("httpx")
    sys.modules["asyncpg"] = asyncpg
    sys.modules["httpx"] = httpx
    try:
        path = ROOT / "services/scraper_service/app/database_protection.py"
        spec = importlib.util.spec_from_file_location("database_protection", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if previous_asyncpg is None:
            sys.modules.pop("asyncpg", None)
        else:
            sys.modules["asyncpg"] = previous_asyncpg
        if previous_httpx is None:
            sys.modules.pop("httpx", None)
        else:
            sys.modules["httpx"] = previous_httpx


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.rows[: args[0]]

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        for row in self.rows:
            if row["public_id"] == args[0] and row["available"] and row["verified"]:
                return row
        return None


class Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


def fake_pool(rows):
    connection = FakeConnection(rows)
    return types.SimpleNamespace(
        connection=connection,
        acquire=lambda: Acquire(connection),
    )


def recovery_row(**overrides):
    value = {
        "recovery_id": "manual-internal-id",
        "public_id": "bkp_0123456789abcdef01234567",
        "kind": "logical_dump",
        "purpose": "manual",
        "relative_directory": "dumps/manual/manual-internal-id",
        "artifact_name": "database.dump",
        "created_at": "2026-09-12T03:00:00+00:00",
        "postgres_major": 16,
        "mreader_version": "v1.3.0-rc4.85",
        "size_bytes": 1234,
        "sha256": "a" * 64,
        "verified": True,
        "available": True,
    }
    value.update(overrides)
    return value


class LocalRecoveryApiCatalogTests(unittest.TestCase):
    def test_admin_routes_use_the_local_projection_and_ui_is_compact(self):
        facade = (ROOT / "services/scraper_service/app/database_facade.py").read_text()
        ui = (ROOT / "frontend/src/pages/AdminDatabase.tsx").read_text()
        self.assertIn("list_recovery_page", facade)
        self.assertIn('backup_page["next_cursor"]', facade)
        self.assertIn("resolve_recovery_point(request.app.state.db, payload.backup_id)", facade)
        self.assertNotIn("fetch_database_backup_index", facade)
        self.assertNotIn("settings.postgres_backup_nas_path", facade)
        self.assertNotIn("physical storage verification", facade)
        self.assertNotIn("backup inventory", facade)
        self.assertIn("Local recovery storage", ui)
        self.assertNotIn("Physical storage protection", ui)
        self.assertNotIn("databaseBackupDownloadUrl", ui)

    def test_public_item_hides_internal_storage_target(self):
        module = load_module()
        public = module.public_recovery_point(recovery_row())
        self.assertEqual(public["id"], "bkp_0123456789abcdef01234567")
        self.assertTrue(public["verified"])
        for field in ("recovery_id", "relative_directory", "artifact_name", "sha256"):
            self.assertNotIn(field, public)
        self.assertNotIn("dumps/manual", repr(public))

    def test_list_and_resolve_use_only_available_verified_projection_rows(self):
        module = load_module()
        pool = fake_pool([recovery_row()])
        listed = asyncio.run(module.list_recovery_points(pool, 50))
        self.assertEqual(len(listed), 1)
        self.assertIn("WHERE available AND verified", pool.connection.calls[0][0])
        resolved = asyncio.run(
            module.resolve_recovery_point(pool, "bkp_0123456789abcdef01234567")
        )
        self.assertEqual(resolved["recovery_id"], "manual-internal-id")
        self.assertEqual(resolved["purpose"], "manual")

    def test_resolve_rejects_invalid_or_missing_public_ids(self):
        module = load_module()
        pool = fake_pool([])
        with self.assertRaises(ValueError):
            asyncio.run(module.resolve_recovery_point(pool, "../../database.dump"))
        with self.assertRaises(LookupError):
            asyncio.run(
                module.resolve_recovery_point(pool, "bkp_0123456789abcdef01234567")
            )

    def test_storage_summary_is_catalog_based_and_path_free(self):
        module = load_module()
        status = module.public_local_storage_status(
            {"available": True, "capabilities": {"local_storage_ready": True}},
            [recovery_row()],
        )
        self.assertTrue(status["healthy"])
        self.assertEqual(status["backup_count"], 1)
        self.assertNotIn("path", repr(status).lower())

    def test_operation_uses_the_catalog_public_id_without_rehashing_internal_id(self):
        module = load_database_protection_module()
        public = module.public_operation(
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "operation_type": "restore_drill",
                "status": "queued",
                "phase": "queued",
                "category": "manual",
                "backup_filename": "manual-internal-id",
                "metadata": {"recovery_public_id": "bkp_0123456789abcdef01234567"},
                "result": {},
                "requested_by_username": "admin",
                "requested_at": "2026-09-12T03:00:00+00:00",
                "started_at": None,
                "completed_at": None,
            }
        )
        self.assertEqual(public["backup_id"], "bkp_0123456789abcdef01234567")
        self.assertNotIn("manual-internal-id", repr(public))

    def test_completed_backup_uses_the_catalog_public_id_from_agent_result(self):
        module = load_database_protection_module()
        public = module.public_operation(
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "operation_type": "backup",
                "status": "verified",
                "phase": "backup-verified",
                "category": None,
                "backup_filename": None,
                "metadata": {},
                "result": {
                    "recovery_id": "manual-internal-id",
                    "recovery_public_id": "bkp_0123456789abcdef01234567",
                },
                "requested_by_username": "admin",
                "requested_at": "2026-09-12T03:00:00+00:00",
                "started_at": "2026-09-12T03:00:01+00:00",
                "completed_at": "2026-09-12T03:00:02+00:00",
            }
        )
        self.assertEqual(public["backup_id"], "bkp_0123456789abcdef01234567")
        self.assertNotIn("manual-internal-id", repr(public))

    def test_database_protection_module_has_no_nas_inventory_or_target_resolver(self):
        module = load_database_protection_module()
        for legacy_name in (
            "backup_public_id",
            "public_backup_inventory",
            "resolve_public_backup",
            "public_storage_status",
            "validate_backup_target",
            "fetch_backup_index",
            "classify_storage_contract",
            "fetch_storage_proof",
        ):
            self.assertFalse(hasattr(module, legacy_name), legacy_name)


if __name__ == "__main__":
    unittest.main()
