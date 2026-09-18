import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.regression.test_local_recovery_catalog import (
    create_logical_bundle,
    sha256,
)
from tests.regression.test_local_recovery_api_catalog import load_module as load_catalog_module

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "scripts/backup/local-recovery-store.sh"
AGENT = ROOT / "scripts/backup/backup-agent.sh"
FACADE = ROOT / "services/scraper_service/app/database_facade.py"
API_CLIENT = ROOT / "frontend/src/api/client.ts"
ADMIN_DATABASE = ROOT / "frontend/src/pages/AdminDatabase.tsx"


def run_store(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(STORE), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def assert_source_markers(testcase: unittest.TestCase, path: Path, markers: tuple[str, ...]) -> None:
    source = path.read_text()
    missing = [marker for marker in markers if marker not in source]
    testcase.assertEqual(missing, [], f"missing source markers in {path}: {missing}")


def rewrite_manifest(bundle: Path, **changes) -> None:
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update(changes)
    manifest_path.write_text(json.dumps(manifest, separators=(",", ":")))
    files = [name for name in ("database.dump", "globals.sql", "snapshot.tar", "manifest.json") if (bundle / name).is_file()]
    (bundle / "checksums.sha256").write_text(
        "".join(f"{sha256(bundle / name)}  {name}\n" for name in files)
    )


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class _PagingConnection:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return len(self.rows)

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        if len(args) == 1:
            limit_plus_one = args[0]
            return self.rows[:limit_plus_one]
        created_at, public_id, limit_plus_one = args
        remaining = [
            row
            for row in self.rows
            if (row["created_at"], row["public_id"]) < (created_at, public_id)
        ]
        return remaining[:limit_plus_one]


class _Pool:
    def __init__(self, rows):
        self.connection = _PagingConnection(rows)

    def acquire(self):
        return _Acquire(self.connection)


def recovery_row(public_id: str, created_at: str):
    return {
        "recovery_id": public_id.replace("bkp_", "recovery-"),
        "public_id": public_id,
        "kind": "logical_dump",
        "purpose": "manual",
        "relative_directory": "dumps/manual/example",
        "artifact_name": "database.dump",
        "created_at": created_at,
        "postgres_major": 16,
        "mreader_version": "v1.3.0-rc4.85",
        "size_bytes": 10,
        "sha256": "a" * 64,
        "verified": True,
        "available": True,
    }


class P085RecoveryInventoryTests(unittest.TestCase):
    def test_verify_rejects_unsupported_postgres_major(self):
        directory = tempfile.mkdtemp(prefix="mreader-p085-major-")
        try:
            root = Path(directory)
            bundle = create_logical_bundle(root, "manual", "legacy-major", "2026-09-10T00:00:00Z")
            rewrite_manifest(bundle, postgres_major=15)
            result = run_store("verify-bundle", str(bundle))
            self.assertNotEqual(result.returncode, 0)
            self.assertRegex(result.stderr.lower(), r"unsupported postgresql major")
        finally:
            shutil.rmtree(directory)

    def test_explicit_import_reverifies_copies_and_records_local_provenance(self):
        with tempfile.TemporaryDirectory(prefix="mreader-p085-import-") as directory:
            fixture = Path(directory)
            legacy_root = fixture / "legacy-nas"
            local_root = fixture / "local"
            source = create_logical_bundle(
                legacy_root, "manual", "legacy-manual", "2026-09-08T04:05:06Z"
            )
            original_database = (source / "database.dump").read_bytes()
            result = run_store("import-bundle", str(local_root), str(source))
            self.assertEqual(result.returncode, 0, result.stderr)
            imported = Path(result.stdout.strip())
            self.assertTrue(source.is_dir(), "explicit import must not delete the NAS source")
            self.assertTrue(imported.is_dir())
            self.assertTrue(str(imported).startswith(str(local_root)))
            self.assertNotEqual(imported.name, source.name)
            self.assertEqual((imported / "database.dump").read_bytes(), original_database)
            manifest = json.loads((imported / "manifest.json").read_text())
            self.assertEqual(manifest["import_source"], "legacy-nas")
            self.assertEqual(manifest["imported_from_recovery_id"], "legacy-manual")
            self.assertRegex(manifest["imported_at"], r"Z$")
            self.assertEqual(manifest["recovery_id"], imported.name)
            verified = run_store("verify-bundle", str(imported))
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertNotIn(str(legacy_root), (imported / "manifest.json").read_text())

    def test_explicit_import_rejects_symlink_root_without_creating_staging(self):
        with tempfile.TemporaryDirectory(prefix="mreader-p085-import-root-") as directory:
            fixture = Path(directory)
            source = create_logical_bundle(
                fixture / "legacy", "manual", "legacy-safe", "2026-09-08T04:05:06Z"
            )
            target = fixture / "canonical-target"
            target.mkdir()
            supplied_root = fixture / "local-link"
            supplied_root.symlink_to(target, target_is_directory=True)
            result = run_store("import-bundle", str(supplied_root), str(source))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(
                (target / "staging").exists(),
                "rejecting a symlinked import root must not mutate the symlink target",
            )

    def test_explicit_import_rejects_tampered_source_without_publishing(self):
        with tempfile.TemporaryDirectory(prefix="mreader-p085-import-bad-") as directory:
            fixture = Path(directory)
            source = create_logical_bundle(
                fixture / "legacy", "manual", "legacy-tampered", "2026-09-08T04:05:06Z"
            )
            (source / "database.dump").write_bytes(b"PGDMP-tampered")
            local_root = fixture / "local"
            result = run_store("import-bundle", str(local_root), str(source))
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(source.is_dir())
            catalog = run_store("catalog", str(local_root))
            self.assertEqual(catalog.returncode, 0, catalog.stderr)
            self.assertEqual(json.loads(catalog.stdout)["count"], 0)

    def test_prune_preserves_transient_pin_and_current_safety_points(self):
        with tempfile.TemporaryDirectory(prefix="mreader-p085-pins-") as directory:
            root = Path(directory)
            old_unpinned = create_logical_bundle(root, "automatic", "auto-old", "2026-08-01T00:00:00Z")
            pinned = create_logical_bundle(root, "manual", "manual-pinned", "2026-08-01T01:00:00Z")
            old_upgrade = create_logical_bundle(root, "pre-upgrade", "upgrade-old", "2026-08-01T02:00:00Z")
            current_upgrade = create_logical_bundle(root, "pre-upgrade", "upgrade-current", "2026-08-02T02:00:00Z")
            current_restore = create_logical_bundle(root, "pre-restore", "restore-current", "2026-08-02T03:00:00Z")
            pins = root / "active-pins.txt"
            pins.write_text("manual-pinned\n")
            result = run_store("prune", str(root), "2026-09-13T00:00:00Z", "4", "2", str(pins))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(old_unpinned.exists())
            self.assertTrue(pinned.exists())
            self.assertFalse(old_upgrade.exists(), "only the current pre-upgrade safety point is pinned")
            self.assertTrue(current_upgrade.exists())
            self.assertTrue(current_restore.exists())
            summary = json.loads(result.stdout)
            protected = {item["recovery_id"] for item in summary["protected"]}
            self.assertIn("manual-pinned", protected)
            self.assertIn("upgrade-current", protected)
            self.assertIn("restore-current", protected)

    def test_prune_never_deletes_the_last_verified_recovery_point(self):
        with tempfile.TemporaryDirectory(prefix="mreader-p085-last-") as directory:
            root = Path(directory)
            create_logical_bundle(root, "automatic", "auto-oldest", "2026-08-01T00:00:00Z")
            create_logical_bundle(root, "automatic", "auto-last", "2026-08-02T00:00:00Z")
            result = run_store("prune", str(root), "2026-09-13T00:00:00Z", "4", "2")
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertTrue(summary["degraded_protection"])
            self.assertEqual(summary["last_verified_recovery_id"], "auto-last")
            catalog = json.loads(run_store("catalog", str(root)).stdout)
            self.assertEqual(
                [item["recovery_id"] for item in catalog["recovery_points"]],
                ["auto-last"],
            )

    def test_capture_timestamp_is_taken_after_capture_finishes(self):
        source = AGENT.read_text()
        logical = source[source.index("logical_backup(){"):source.index("snapshot_backup(){")]
        snapshot = source[source.index("snapshot_backup(){"):source.index("latest_daily_name(){")]
        self.assertGreater(logical.index('ts="$(date -u'), logical.index("pg_dumpall"))
        self.assertLess(logical.index('ts="$(date -u'), logical.index("finish_local_logical_bundle"))
        self.assertGreater(snapshot.index('ts="$(date -u'), snapshot.index("tar -cf"))
        self.assertLess(snapshot.index('ts="$(date -u'), snapshot.index("finish_local_snapshot_bundle"))

    def test_backup_agent_generates_transient_retention_pins_for_active_restore_and_cutover(self):
        source = AGENT.read_text()
        pin_builder = source[
            source.index("build_retention_pin_file(){"):
            source.index("prune_local_recovery_store(){")
        ]
        required = {
            "build_retention_pin_file",
            "operation_type IN ('restore','restore_drill')",
            "status IN ('queued','running')",
            "restore-cutover-*.json",
            ".filename // empty",
            'prune "$LOCAL_ROOT"',
            '"$pin_file"',
        }
        self.assertEqual(sorted(marker for marker in required if marker not in source), [])
        self.assertIn("if ! psql", pin_builder)

    def test_recovery_inventory_supports_bounded_opaque_keyset_paging(self):
        module = load_catalog_module()
        rows = [
            recovery_row("bkp_aaaaaaaaaaaaaaaaaaaaaaaa", "2026-09-12T03:00:03+00:00"),
            recovery_row("bkp_bbbbbbbbbbbbbbbbbbbbbbbb", "2026-09-12T03:00:02+00:00"),
            recovery_row("bkp_cccccccccccccccccccccccc", "2026-09-12T03:00:01+00:00"),
        ]
        pool = _Pool(rows)
        first = asyncio.run(module.list_recovery_page(pool, limit=2))
        self.assertEqual(first["total"], 3)
        self.assertEqual(len(first["items"]), 2)
        self.assertRegex(first["next_cursor"], r"^[A-Za-z0-9_-]+$")
        self.assertNotIn("2026-", first["next_cursor"])
        second = asyncio.run(module.list_recovery_page(pool, limit=2, cursor=first["next_cursor"]))
        self.assertEqual(len(second["items"]), 1)
        self.assertIsNone(second["next_cursor"])
        with self.assertRaises(ValueError):
            asyncio.run(module.list_recovery_page(pool, limit=2, cursor="../../unsafe"))
        fetch_sql = "\n".join(call[1] for call in pool.connection.calls if call[0] == "fetch")
        self.assertIn("(created_at, public_id) <", fetch_sql)
        self.assertIn("LIMIT", fetch_sql)

    def test_database_facade_exposes_page_metadata_without_storage_paths(self):
        source = FACADE.read_text()
        self.assertIn("list_recovery_page", source)
        self.assertIn("cursor: str | None = Query", source)
        self.assertIn('"backup_page"', source)
        self.assertIn('"next_cursor"', source)
        self.assertIn('"total"', source)
        self.assertNotIn("relative_directory", source)

    def test_admin_recovery_inventory_consumes_cursor_paging(self):
        assert_source_markers(
            self,
            API_CLIENT,
            (
                "backup_page: {",
                "next_cursor: string | null",
                "getDatabaseProtection: (limit = 50, cursor?: string | null)",
                "cursor=${encodeURIComponent(cursor)}",
            ),
        )
        assert_source_markers(
            self,
            ADMIN_DATABASE,
            (
                "const [backupCursor",
                "const [backupCursorStack",
                "data?.backup_page.next_cursor",
                "Previous page",
                "Next page",
            ),
        )


if __name__ == "__main__":
    unittest.main()
