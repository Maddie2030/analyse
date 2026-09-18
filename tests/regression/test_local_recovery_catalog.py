import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/backup/local-recovery-store.sh"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_logical_bundle(root: Path, purpose: str, recovery_id: str, created_at: str) -> Path:
    bundle = root / "dumps" / purpose / recovery_id
    bundle.mkdir(parents=True)
    (bundle / "database.dump").write_bytes(b"PGDMP-test-database")
    (bundle / "globals.sql").write_text("-- PostgreSQL globals\n")
    manifest = {
        "schema_version": 1,
        "recovery_id": recovery_id,
        "type": "logical",
        "purpose": purpose,
        "scope": "mreader_database_plus_globals",
        "database": "mreader",
        "postgres_major": 16,
        "mreader_version": "v1.3.0-rc4.85",
        "created_at": created_at,
        "verification": "verified",
        "files": ["database.dump", "globals.sql"],
        "checksums_file": "checksums.sha256",
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))
    checksums = "".join(
        f"{sha256(bundle / name)}  {name}\n"
        for name in ("database.dump", "globals.sql", "manifest.json")
    )
    (bundle / "checksums.sha256").write_text(checksums)
    return bundle


def create_snapshot_bundle(root: Path, recovery_id: str, created_at: str) -> Path:
    bundle = root / "snapshots" / recovery_id
    bundle.mkdir(parents=True)
    (bundle / "snapshot.tar").write_bytes(b"snapshot-test-data")
    manifest = {
        "schema_version": 1,
        "recovery_id": recovery_id,
        "type": "physical",
        "purpose": "snapshot",
        "scope": "postgres_cluster",
        "postgres_major": 16,
        "mreader_version": "v1.3.0-rc4.85",
        "created_at": created_at,
        "verification": "verified",
        "files": ["snapshot.tar"],
        "checksums_file": "checksums.sha256",
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))
    checksums = "".join(
        f"{sha256(bundle / name)}  {name}\n"
        for name in ("snapshot.tar", "manifest.json")
    )
    (bundle / "checksums.sha256").write_text(checksums)
    return bundle


def run_store(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


class LocalRecoveryCatalogTests(unittest.TestCase):
    def test_verify_accepts_complete_logical_bundle(self):
        with tempfile.TemporaryDirectory(prefix="mreader-catalog-") as directory:
            root = Path(directory)
            bundle = create_logical_bundle(
                root, "manual", "manual-20260912T010000Z", "2026-09-12T01:00:00Z"
            )
            result = run_store("verify-bundle", str(bundle))
            self.assertEqual(result.returncode, 0, result.stderr)
            item = json.loads(result.stdout)
            self.assertEqual(item["recovery_id"], "manual-20260912T010000Z")
            self.assertRegex(item["public_id"], r"^bkp_[0-9a-f]{24}$")
            self.assertEqual(item["artifact"], "database.dump")
            self.assertEqual(item["kind"], "logical_dump")
            self.assertNotIn(str(root), result.stdout)

    def test_verify_accepts_complete_logical_bundle_with_busybox_find(self):
        with tempfile.TemporaryDirectory(prefix="mreader-catalog-") as directory:
            root = Path(directory)
            bundle = create_logical_bundle(
                root, "manual", "manual-busybox", "2026-09-12T01:00:00Z"
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            os.symlink("/usr/bin/busybox", bin_dir / "find")
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            result = run_store("verify-bundle", str(bundle), env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            item = json.loads(result.stdout)
            self.assertEqual(item["recovery_id"], "manual-busybox")

    def test_verify_accepts_windows_binary_checksum_markers_with_busybox_tools(self):
        with tempfile.TemporaryDirectory(prefix="mreader-catalog-") as directory:
            root = Path(directory)
            bundle = create_logical_bundle(
                root, "manual", "manual-windows-binary", "2026-09-12T01:00:00Z"
            )
            checksums = "".join(
                f"{sha256(bundle / name)} *{name}\n"
                for name in ("database.dump", "globals.sql", "manifest.json")
            )
            (bundle / "checksums.sha256").write_text(checksums)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            for tool in ("find", "awk", "sha256sum"):
                os.symlink("/usr/bin/busybox", bin_dir / tool)
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            result = run_store("verify-bundle", str(bundle), env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            item = json.loads(result.stdout)
            self.assertEqual(item["recovery_id"], "manual-windows-binary")

    def test_verify_rejects_duplicate_checksum_name_across_text_and_binary_markers(self):
        with tempfile.TemporaryDirectory(prefix="mreader-catalog-") as directory:
            root = Path(directory)
            bundle = create_logical_bundle(
                root, "manual", "manual-duplicate-marker", "2026-09-12T01:00:00Z"
            )
            lines = (bundle / "checksums.sha256").read_text().splitlines()
            digest = sha256(bundle / "database.dump")
            (bundle / "checksums.sha256").write_text(
                "\n".join([f"{digest}  database.dump", f"{digest} *database.dump", *lines[1:]]) + "\n"
            )
            result = run_store("verify-bundle", str(bundle))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsafe or duplicate", result.stderr.lower())

    def test_verify_rejects_checksum_corruption_and_symlinks(self):
        with tempfile.TemporaryDirectory(prefix="mreader-catalog-") as directory:
            root = Path(directory)
            corrupted = create_logical_bundle(
                root, "automatic", "automatic-corrupt", "2026-09-10T01:00:00Z"
            )
            (corrupted / "database.dump").write_bytes(b"PGDMP-changed")
            result = run_store("verify-bundle", str(corrupted))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checksum", result.stderr.lower())

            linked = create_logical_bundle(
                root, "manual", "manual-linked", "2026-09-11T01:00:00Z"
            )
            target = linked / "real.dump"
            target.write_bytes((linked / "database.dump").read_bytes())
            (linked / "database.dump").unlink()
            os.symlink(target.name, linked / "database.dump")
            result = run_store("verify-bundle", str(linked))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr.lower())

    def test_catalog_contains_only_verified_bundles_and_no_host_paths(self):
        with tempfile.TemporaryDirectory(prefix="mreader-catalog-") as directory:
            root = Path(directory)
            create_logical_bundle(
                root, "manual", "manual-valid", "2026-09-12T01:00:00Z"
            )
            broken = create_logical_bundle(
                root, "automatic", "automatic-broken", "2026-09-11T01:00:00Z"
            )
            (broken / "manifest.json").unlink()
            result = run_store("catalog", str(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            catalog = json.loads(result.stdout)
            self.assertEqual(catalog["count"], 1)
            self.assertEqual(catalog["invalid_count"], 1)
            self.assertEqual(catalog["recovery_points"][0]["recovery_id"], "manual-valid")
            self.assertEqual(
                catalog["recovery_points"][0]["relative_directory"],
                "dumps/manual/manual-valid",
            )
            self.assertNotIn(str(root), result.stdout)

    def test_catalog_rejects_a_valid_bundle_in_the_wrong_owned_directory(self):
        with tempfile.TemporaryDirectory(prefix="mreader-catalog-") as directory:
            root = Path(directory)
            misplaced = create_logical_bundle(
                root, "automatic", "manual-misplaced", "2026-09-12T01:00:00Z"
            )
            manifest = json.loads((misplaced / "manifest.json").read_text())
            manifest["purpose"] = "manual"
            (misplaced / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))
            lines = "".join(
                f"{sha256(misplaced / name)}  {name}\n"
                for name in ("database.dump", "globals.sql", "manifest.json")
            )
            (misplaced / "checksums.sha256").write_text(lines)
            result = run_store("catalog", str(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            catalog = json.loads(result.stdout)
            self.assertEqual(catalog["count"], 0)
            self.assertEqual(catalog["invalid_count"], 1)

    def test_prune_uses_four_days_for_dumps_and_two_for_snapshots(self):
        with tempfile.TemporaryDirectory(prefix="mreader-catalog-") as directory:
            root = Path(directory)
            old_dump = create_logical_bundle(
                root, "automatic", "automatic-old", "2026-09-07T00:00:00Z"
            )
            recent_dump = create_logical_bundle(
                root, "automatic", "automatic-recent", "2026-09-09T01:00:01Z"
            )
            old_snapshot = create_snapshot_bundle(
                root, "snapshot-old", "2026-09-10T23:59:59Z"
            )
            recent_snapshot = create_snapshot_bundle(
                root, "snapshot-recent", "2026-09-11T00:00:01Z"
            )
            result = run_store("prune", str(root), "2026-09-13T00:00:00Z", "4", "2")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(old_dump.exists())
            self.assertTrue(recent_dump.exists())
            self.assertFalse(old_snapshot.exists())
            self.assertTrue(recent_snapshot.exists())

    def test_publish_staged_is_atomic_and_copy_revalidates_the_artifact(self):
        with tempfile.TemporaryDirectory(prefix="mreader-catalog-") as directory:
            root = Path(directory)
            built = create_logical_bundle(
                root / "build", "manual", "manual-publish", "2026-09-12T02:00:00Z"
            )
            (root / "staging").mkdir()
            staged = root / "staging" / "manual-publish"
            built.rename(staged)
            result = run_store("publish-staged", str(root), str(staged))
            self.assertEqual(result.returncode, 0, result.stderr)
            final = root / "dumps" / "manual" / "manual-publish"
            self.assertTrue(final.is_dir())
            self.assertFalse(staged.exists())

            destination = root / "staging" / "restore-copy.dump"
            copied = run_store(
                "copy-artifact", str(root), "manual-publish", str(destination)
            )
            self.assertEqual(copied.returncode, 0, copied.stderr)
            self.assertEqual(destination.read_bytes(), (final / "database.dump").read_bytes())
            self.assertEqual(
                (destination.with_name(destination.name + ".sha256")).read_text().split()[0],
                sha256(destination),
            )

    def test_publish_rejects_staging_outside_the_recovery_root(self):
        with tempfile.TemporaryDirectory(prefix="mreader-catalog-") as directory:
            fixture = Path(directory)
            root = fixture / "recovery"
            staged = create_logical_bundle(
                fixture / "outside", "manual", "manual-outside", "2026-09-12T02:00:00Z"
            )
            result = run_store("publish-staged", str(root), str(staged))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("staging", result.stderr.lower())
            self.assertTrue(staged.exists())


if __name__ == "__main__":
    unittest.main()
