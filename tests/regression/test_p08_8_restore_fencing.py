import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "scripts/backup/backup-agent.sh"
MIGRATION = ROOT / "db/migrations/060_database_restore_fencing.sql"
PROTECTION = ROOT / "services/scraper_service/app/database_protection.py"
FACADE = ROOT / "services/scraper_service/app/database_facade.py"
MODELS = ROOT / "services/scraper_service/app/models.py"
API_CLIENT = ROOT / "frontend/src/api/client.ts"
ADMIN_DATABASE = ROOT / "frontend/src/pages/AdminDatabase.tsx"
POSTGRES_RESTORE = ROOT / "scripts/backup/postgres-restore.sh"


def source_block(path: Path, start_marker: str, end_marker: str) -> str:
    source = path.read_text()
    if start_marker not in source or end_marker not in source:
        return ""
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def assert_block_excludes(testcase: unittest.TestCase, path: Path, start_marker: str, end_marker: str, forbidden: tuple[str, ...]) -> None:
    block = source_block(path, start_marker, end_marker).lower()
    testcase.assertTrue(block)
    testcase.assertFalse(any(marker in block for marker in forbidden), forbidden)


def run_agent(command: str, *, local_root: Path, spool: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "POSTGRES_BACKUP_LOCAL_ROOT": str(local_root),
            "POSTGRES_BACKUP_SPOOL": str(spool),
            "MREADER_LOCAL_RECOVERY_STORE": str(ROOT / "scripts/backup/local-recovery-store.sh"),
        }
    )
    return subprocess.run(
        ["bash", str(AGENT), command],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class P088RestoreControlTests(unittest.TestCase):
    def test_restore_control_snapshot_is_persistent_and_browser_safe(self):
        with tempfile.TemporaryDirectory(prefix="mreader-p088-control-") as directory:
            root = Path(directory) / "recovery"
            root.mkdir()
            spool = root / "staging" / "backup-agent"
            first = run_agent("restore-control", local_root=root, spool=spool)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_payload = json.loads(first.stdout)
            self.assertRegex(first_payload["installation_fingerprint"], r"^inst_[0-9a-f]{16}$")
            self.assertEqual(first_payload["restore_generation"], 1)
            self.assertNotIn("installation_id", first_payload)

            second = run_agent("restore-control", local_root=root, spool=spool)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(second.stdout), first_payload)

            control = root / "control" / "restore-control.json"
            stored = json.loads(control.read_text())
            self.assertRegex(stored["installation_id"], r"^[0-9a-f]{32}$")
            self.assertEqual(stored["installation_fingerprint"], first_payload["installation_fingerprint"])
            self.assertEqual(stored["restore_generation"], 1)

    def test_initialize_restore_state_creates_control_and_uses_guarded_database_seed(self):
        with tempfile.TemporaryDirectory(prefix="mreader-p088-init-") as directory:
            fixture = Path(directory)
            root = fixture / "recovery"
            root.mkdir()
            spool = root / "staging" / "backup-agent"
            bindir = fixture / "bin"
            bindir.mkdir()
            captured = fixture / "psql.sql"
            fake_psql = bindir / "psql"
            fake_psql.write_text(
                "#!/usr/bin/env bash\n"
                "cat > \"$P088_CAPTURE_SQL\"\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_psql.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bindir}:{env['PATH']}",
                    "P088_CAPTURE_SQL": str(captured),
                    "POSTGRES_BACKUP_LOCAL_ROOT": str(root),
                    "POSTGRES_BACKUP_SPOOL": str(spool),
                    "MREADER_LOCAL_RECOVERY_STORE": str(ROOT / "scripts/backup/local-recovery-store.sh"),
                }
            )
            result = subprocess.run(
                ["bash", str(AGENT), "initialize-restore-state"],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            control = json.loads((root / "control" / "restore-control.json").read_text())
            self.assertEqual(control["restore_generation"], 1)
            self.assertRegex(control["installation_fingerprint"], r"^inst_[0-9a-f]{16}$")
            sql = captured.read_text(encoding="utf-8")
            for marker in (
                "database_restore_state",
                "installation_fingerprint = ''",
                "restore_generation = 0",
                "restore generation mirror mismatch",
                "UPDATE database_restore_state",
            ):
                self.assertIn(marker, sql)

    def test_restore_control_rejects_symlinked_control_directory_without_mutating_target(self):
        with tempfile.TemporaryDirectory(prefix="mreader-p088-control-link-") as directory:
            fixture = Path(directory)
            root = fixture / "recovery"
            root.mkdir()
            target = fixture / "outside"
            target.mkdir()
            (root / "control").symlink_to(target, target_is_directory=True)
            result = run_agent("restore-control", local_root=root, spool=root / "staging" / "backup-agent")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((target / "restore-control.json").exists())

    def test_database_restore_state_mirror_has_singleton_generation_contract(self):
        self.assertTrue(MIGRATION.is_file(), "missing P08.8 restore-fencing migration")
        sql = MIGRATION.read_text()
        for marker in (
            "CREATE TABLE IF NOT EXISTS database_restore_state",
            "singleton BOOLEAN PRIMARY KEY",
            "installation_fingerprint VARCHAR(64) NOT NULL",
            "restore_generation BIGINT NOT NULL",
            "last_restore_operation_id UUID NULL",
            "last_restore_source_public_id VARCHAR(32) NULL",
            "ON CONFLICT (singleton) DO NOTHING",
        ):
            self.assertIn(marker, sql)

    def test_agent_defines_generation_commit_helper_but_drills_do_not_use_it(self):
        source = AGENT.read_text()
        self.assertIn("advance_restore_generation(){", source)
        start = source.index("restore_drill_selected(){")
        end = source.index("capture_pre_restore_safety_ids(){", start)
        drill_block = source[start:end]
        self.assertNotIn("advance_restore_generation", drill_block)
        self.assertNotIn("restore-cutover-", drill_block)


class P088AdminConfirmationTests(unittest.TestCase):
    def test_backend_requires_installation_generation_and_exact_source_fence(self):
        protection = PROTECTION.read_text()
        facade = FACADE.read_text()
        models = MODELS.read_text()
        required = {
            "database_protection.py": (
                '"restore_control"',
                'installation_fingerprint',
                'restore_generation',
            ),
            "database_facade.py": (
                'expected_installation_fingerprint',
                'expected_restore_generation',
                'recovery_sha256',
                'RESTORE {payload.backup_id} ON {fingerprint} GEN {generation}',
            ),
            "models.py": (
                'installation_fingerprint: str',
                'restore_generation: int',
            ),
        }
        sources = {
            "database_protection.py": protection,
            "database_facade.py": facade,
            "models.py": models,
        }
        missing = {
            name: [marker for marker in markers if marker not in sources[name]]
            for name, markers in required.items()
        }
        self.assertEqual({name: values for name, values in missing.items() if values}, {})

    def test_frontend_confirmation_uses_runtime_installation_and_generation(self):
        client = API_CLIENT.read_text()
        page = ADMIN_DATABASE.read_text()
        for marker in (
            'restore_control:',
            'installation_fingerprint: string',
            'restore_generation: number',
            'createDatabaseRestore: (backupId: string, confirmation: string, installationFingerprint: string, restoreGeneration: number)',
            'installation_fingerprint: installationFingerprint',
            'restore_generation: restoreGeneration',
        ):
            self.assertIn(marker, client)
        for marker in (
            'data?.runtime.restore_control',
            'RESTORE ${restoreTarget.id} ON ${restoreControl.installation_fingerprint} GEN ${restoreControl.restore_generation}',
            'restoreControl.installation_fingerprint',
            'restoreControl.restore_generation',
        ):
            self.assertIn(marker, page)


class P088AgentFenceTests(unittest.TestCase):
    def test_operator_cli_resolves_exact_source_before_confirmation_and_uses_one_restore_path(self):
        source = POSTGRES_RESTORE.read_text()
        required = (
            'PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"',
            'resolve-restore-request "$TARGET"',
            'mapfile -t REQUEST_FIELDS',
            'json.loads(sys.argv[1])',
            'PUBLIC_ID="${REQUEST_FIELDS[0]:-}"',
            'INSTALLATION_FINGERPRINT="${REQUEST_FIELDS[1]:-}"',
            'RESTORE_GENERATION="${REQUEST_FIELDS[2]:-}"',
            'SOURCE_SHA256="${REQUEST_FIELDS[3]:-}"',
            'RESTORE ${PUBLIC_ID} ON ${INSTALLATION_FINGERPRINT} GEN ${RESTORE_GENERATION}',
            'restore-public-id "$PUBLIC_ID" "$INSTALLATION_FINGERPRINT" "$RESTORE_GENERATION" "$SOURCE_SHA256"',
        )
        self.assertEqual([marker for marker in required if marker not in source], [])
        self.assertNotIn('jq -r', source)
        self.assertNotIn('Type RESTORE-MREADER-DB to continue', source)
        self.assertNotIn('restore-latest-daily || restore_failed=1', source)
        self.assertNotIn('restore-latest-snapshot || restore_failed=1', source)

    def test_backup_agent_claims_and_rechecks_exact_restore_fence(self):
        source = AGENT.read_text()
        required = (
            'resolve_restore_request(){',
            'validate_restore_request_fence(){',
            "metadata->>'recovery_public_id'",
            "metadata->>'recovery_sha256'",
            "metadata->>'expected_installation_fingerprint'",
            "metadata->>'expected_restore_generation'",
            'restore-fence-rejected',
        )
        self.assertEqual([marker for marker in required if marker not in source], [])
        process_start = source.index('process_database_operation(){')
        process_end = source.index('ensure_daily_today(){', process_start)
        process_block = source[process_start:process_end]
        self.assertIn('validate_restore_request_fence', process_block)
        cutover_start = source.index('restore_logical_source_enterprise(){')
        cutover_end = source.index('restore_selected_enterprise(){', cutover_start)
        cutover_block = source[cutover_start:cutover_end]
        self.assertIn('validate_restore_request_fence', cutover_block)

    def test_cli_restore_queue_metadata_matches_admin_fence_shape(self):
        source = AGENT.read_text()
        for marker in (
            'recovery_public_id:$recovery_public_id',
            'recovery_sha256:$recovery_sha256',
            'expected_installation_fingerprint:$expected_installation_fingerprint',
            'expected_restore_generation:$expected_restore_generation',
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()

class P088CutoverJournalTests(unittest.TestCase):
    def test_cutover_journal_records_exact_source_safety_and_generation_fences(self):
        source = AGENT.read_text()
        required = (
            'write_restore_cutover_journal(){',
            '$RESTORE_CONTROL_DIR/restore-cutover-${opid}.json',
            'schema_version:2',
            'source_public_id:$source_public_id',
            'source_recovery_id:$source_recovery_id',
            'source_sha256:$source_sha256',
            'safety_public_id:$safety_public_id',
            'safety_recovery_id:$safety_recovery_id',
            'expected_restore_generation:$expected_restore_generation',
            'next_restore_generation:$next_restore_generation',
            '$SPOOL/state/latest-pre-restore.json',
        )
        self.assertEqual([marker for marker in required if marker not in source], [])

    def test_cutover_journal_brackets_each_destructive_rename_phase(self):
        source = AGENT.read_text()
        restore_start = source.index('restore_logical_source_enterprise(){')
        restore_end = source.index('restore_selected_enterprise(){', restore_start)
        restore_block = source[restore_start:restore_end]
        cutover_start = source.index('journaled_database_cutover(){')
        cutover_end = source.index('restore_logical_source_enterprise(){', cutover_start)
        cutover_block = source[cutover_start:cutover_end]
        self.assertIn('--arg phase prepared', restore_block)
        self.assertIn('write_restore_cutover_journal "$cutover_marker" "$journal_payload"', restore_block)
        phases = ('rename-live-pending', 'live-renamed', 'promote-staged-pending', 'cutover-live')
        positions = [cutover_block.index(phase) if phase in cutover_block else -1 for phase in phases]
        self.assertTrue(all(position >= 0 for position in positions), positions)
        self.assertEqual(positions, sorted(positions))
        self.assertGreaterEqual(cutover_block.count('update_restore_cutover_phase'), 4)
        self.assertNotIn('$SPOOL/state/restore-cutover-${opid}.json', restore_block + cutover_block)

    def test_retention_pins_v2_source_and_safety_ids_and_keeps_legacy_marker_support(self):
        source = AGENT.read_text()
        start = source.index('build_retention_pin_file(){')
        end = source.index('prune_local_recovery_store(){', start)
        block = source[start:end]
        for marker in (
            '"$RESTORE_CONTROL_DIR"/restore-cutover-*.json',
            '.source_recovery_id // empty',
            '.safety_recovery_id // empty',
            '"$SPOOL"/state/restore-cutover-*.json',
            '.filename // empty',
        ):
            self.assertIn(marker, block)


class P088GenerationRecoveryTests(unittest.TestCase):
    def test_v2_recovery_classifier_covers_expected_interruption_matrix(self):
        source = AGENT.read_text()
        required = (
            'classify_v2_restore_recovery(){',
            'abort-unstarted',
            'rollback-first-rename',
            'finalize-expected-generation',
            'finalize-committed-generation',
            'ambiguous',
            'current_generation == expected_generation',
            'current_generation == next_generation',
        )
        self.assertEqual([marker for marker in required if marker not in source], [])

    def test_generation_commit_order_is_database_mirror_then_host_then_terminal_ledger(self):
        mirror = source_block(AGENT, 'prepare_restore_generation_mirror(){', 'commit_restored_generation(){')
        self.assertTrue(mirror)
        mirror_order = ('validate_database_contents', 'sync_database_restore_state')
        mirror_positions = [mirror.index(marker) if marker in mirror else -1 for marker in mirror_order]
        self.assertTrue(all(position >= 0 for position in mirror_positions), mirror_positions)
        self.assertEqual(mirror_positions, sorted(mirror_positions), mirror_positions)

        helper = source_block(AGENT, 'commit_restored_generation(){', 'complete_recovered_restore_ledger(){')
        self.assertTrue(helper)
        helper_markers = (
            'reconciling',
            'reconcile_restored_application_work',
            'prepare_restore_generation_mirror',
            'generation-commit-pending',
            'advance_restore_generation',
            'generation-committed',
        )
        helper_positions = [helper.index(marker) if marker in helper else -1 for marker in helper_markers]
        self.assertTrue(all(position >= 0 for position in helper_positions), helper_positions)
        self.assertEqual(helper_positions, sorted(helper_positions), helper_positions)

        restore = source_block(AGENT, 'restore_logical_source_enterprise(){', 'restore_selected_enterprise(){')
        self.assertTrue(restore)
        terminal_markers = (
            'commit_restored_generation',
            'operation_update "$opid" completed restore-complete',
            'dropdb',
            'rm -f',
        )
        terminal_positions = [restore.rfind(marker) if marker in restore else -1 for marker in terminal_markers]
        self.assertTrue(all(position >= 0 for position in terminal_positions), terminal_positions)
        self.assertEqual(terminal_positions, sorted(terminal_positions), terminal_positions)

    def test_startup_reconciliation_reads_v2_journal_control_generation_and_fails_closed(self):
        block = source_block(AGENT, 'reconcile_v2_restore_cutover(){', 'reconcile_orphaned_database_operations_on_startup(){')
        self.assertTrue(block)
        required = (
            '.schema_version // 1',
            '.installation_fingerprint // empty',
            '.expected_restore_generation // empty',
            '.next_restore_generation // empty',
            '.phase // empty',
            'restore_control_snapshot',
            'classify_v2_restore_recovery',
            'ambiguous v2 restore recovery state',
            'leaving journal for operator inspection',
        )
        self.assertEqual([marker for marker in required if marker not in block], [])

    def test_host_generation_already_next_never_auto_rolls_back(self):
        source = AGENT.read_text()
        self.assertIn('reconcile_v2_restore_cutover(){', source)
        start = source.index('reconcile_v2_restore_cutover(){')
        end = source.index('reconcile_restore_cutovers(){', start)
        block = source[start:end]
        self.assertIn('finalize-committed-generation', block)
        committed = block[block.index('finalize-committed-generation'):]
        self.assertNotIn('rollback_database_cutover', committed.split(';;', 1)[0])

class P088StaleWorkReconciliationTests(unittest.TestCase):
    def test_reconciliation_transaction_fences_ingestion_media_and_outbox(self):
        block = source_block(AGENT, 'reconcile_restored_application_work(){', 'prepare_restore_generation_mirror(){')
        self.assertTrue(block)
        required = (
            'BEGIN;',
            'UPDATE ingestion_operations',
            "status='cancelled'",
            "phase='superseded-by-restore'",
            'revision=revision+1',
            'lease_generation=lease_generation+1',
            "error_code='restore-superseded'",
            "status IN ('queued','running','cancel_requested')",
            'UPDATE media_operations',
            "status='failed'",
            'media_generation=media_generation+1',
            'queue_dispatched_at=NULL',
            'processing_heartbeat_at=NULL',
            "status IN ('queued','retry','processing')",
            'UPDATE event_outbox',
            'published_at=now()',
            'locked_at=NULL',
            'locked_by=NULL',
            "'restore_suppressed', true",
            "'restore_generation', :restore_generation::bigint",
            'WHERE published_at IS NULL',
            'COMMIT;',
        )
        self.assertEqual([marker for marker in required if marker not in block], [])

    def test_restore_reconciliation_does_not_flush_lifecycle_or_brokers(self):
        assert_block_excludes(
            self,
            AGENT,
            'reconcile_restored_application_work(){',
            'prepare_restore_generation_mirror(){',
            (
                'lifecycle_cleanup_jobs',
                'truncate lifecycle',
                'redis-cli flush',
                'flushall',
                'rabbitmqctl purge',
                'rabbitmqadmin purge',
            ),
        )

class P088DrillIsolationTests(unittest.TestCase):
    def test_restore_drills_never_enter_production_cutover_or_generation_paths(self):
        drill_block = source_block(AGENT, 'snapshot_restore_drill_selected(){', 'capture_pre_restore_safety_ids(){').lower()
        self.assertTrue(drill_block)
        forbidden = (
            'advance_restore_generation',
            'write_restore_cutover_journal',
            'capture_pre_restore_safety_ids',
            'reconcile_restored_application_work',
            'sync_database_restore_state',
            'generation-commit-pending',
            'generation-committed',
            'restore_suppressed',
        )
        self.assertFalse(any(marker in drill_block for marker in forbidden), forbidden)

    def test_operator_drill_uses_only_read_only_media_check_and_drill_operation(self):
        source = (ROOT / 'scripts/backup/postgres-restore-drill.sh').read_text()
        self.assertIn('--check', source)
        self.assertIn('restore-drill-public-id "$BACKUP_ID"', source)
        for forbidden in (' restore-public-id ', ' pre-restore ', 'restore-cutover-', 'advance_restore_generation', 'scripts/hybrid/deploy.sh'):
            self.assertNotIn(forbidden, source)
