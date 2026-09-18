import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
QUIESCE = ROOT / "scripts/hybrid/quiesce-before-migration.sh"
STATEFUL = ROOT / "scripts/hybrid/stateful-up.sh"
MIGRATE = ROOT / "scripts/migrate.sh"


class MigrationQuiescenceSourceTests(unittest.TestCase):
    def test_quiescence_helper_exists_and_is_wired_before_capture_and_migration(self):
        self.assertTrue(QUIESCE.is_file(), "missing migration quiescence helper")
        text = STATEFUL.read_text()
        q = text.index('quiesce-before-migration.sh')
        capture = text.index('create-local-preupgrade-backup.sh')
        migrate = text.index('--profile migration run --rm migrate')
        self.assertLess(q, capture)
        self.assertLess(q, migrate)
        self.assertIn('stateful-up.sh" core', MIGRATE.read_text())

    def test_autoscalers_are_disabled_before_any_workload_is_scaled(self):
        text = QUIESCE.read_text()
        autoscale = min(text.index('delete hpa'), text.index('delete scaledobject'))
        scale = text.index('scale deployment')
        self.assertLess(autoscale, scale)

    def test_non_progress_workloads_stop_before_legacy_progress_drain(self):
        text = QUIESCE.read_text()
        stop_others = text.index('scale_non_progress_workloads')
        drain = text.index('drain_legacy_progress')
        self.assertLess(stop_others, drain)
        self.assertIn('progress-go', text)
        self.assertIn('PROGRESS_GO_DRAIN_LEGACY_STREAM=1', text)
        self.assertIn('rollout status deployment/progress-go', text)

    def test_drain_requires_both_zero_pending_and_zero_lag(self):
        text = QUIESCE.read_text()
        self.assertIn('XINFO GROUPS', text)
        self.assertRegex(text, r'pending[^\n]*==[^\n]*0')
        self.assertRegex(text, r'lag[^\n]*==[^\n]*0')
        self.assertIn('PROGRESS_GO_CONSUMER_GROUP', text)
        self.assertIn('PROGRESS_GO_STREAM', text)

    def test_progress_is_stopped_after_drain_and_all_deployments_are_verified_zero(self):
        text = QUIESCE.read_text()
        drain = text.rindex('\ndrain_legacy_progress\n')
        final_scale = text.rindex('scale deployment progress-go --replicas=0')
        verify = text.rindex('\nverify_all_deployments_stopped\n')
        self.assertLess(drain, final_scale)
        self.assertLess(final_scale, verify)
        self.assertIn('status.replicas', text)

    def test_fresh_install_without_mreader_namespaces_is_a_noop(self):
        text = QUIESCE.read_text()
        self.assertIn('kubectl get namespace', text)
        self.assertIn('No existing MReader Kubernetes workloads require quiescence', text)


if __name__ == '__main__':
    unittest.main()
