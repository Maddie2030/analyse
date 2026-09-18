from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from tests.diagnostics.support import load_script

RUNNER_PATH = Path(__file__).with_name('runner.py')

def load_runner():
    return load_script(RUNNER_PATH)

class RunnerProtocolTests(unittest.TestCase):
    def test_run_stage_records_failure_without_raising(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = runner.run_stage(root, 'failing-stage', ['sh','-c','echo boom; exit 7'])
            self.assertEqual(7, result.exit_code)
            self.assertEqual('FAIL', result.status)
            self.assertIn('boom', (root/'logs'/'failing-stage.log').read_text())
            self.assertIn('failing-stage', (root/'stages.tsv').read_text())

    def test_run_stage_timeout_is_recorded_as_124(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = runner.run_stage(root, 'hung-stage', ['sh','-c','sleep 2'], timeout_seconds=0.05)
            self.assertEqual(124, result.exit_code)
            self.assertEqual('FAIL', result.status)
            self.assertIn('timed out', (root/'logs'/'hung-stage.log').read_text().lower())

    def test_run_stages_continues_after_failure(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            results = runner.run_stages(root, [('first',['sh','-c','exit 3']),('second',['sh','-c','echo survived'])])
            self.assertEqual([3,0], [r.exit_code for r in results])
            self.assertIn('survived', (root/'logs'/'second.log').read_text())

    def test_container_done_sentinel_is_created(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); runner.mark_container_tests_done(root)
            self.assertTrue((root/'.container-tests-done').exists())

    def test_wait_for_host_capture_times_out_cleanly(self):
        runner=load_runner()
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(runner.wait_for_host_capture(Path(td), timeout_seconds=0.05, poll_seconds=0.01))

    def test_full_mode_runs_core_actor_and_optional_external_suite(self):
        runner=load_runner()
        core=dict(runner._commands('full',False))['pytest-api']
        external=dict(runner._commands('full',True))['pytest-api']
        self.assertEqual('/tests', core[-1])
        self.assertIn('not external', core)
        self.assertEqual('/tests', external[-1])
        self.assertNotIn('external', external)

    def test_quick_mode_uses_bounded_core_modules(self):
        runner=load_runner(); commands=dict(runner._commands('quick',False)); pytest_cmd=commands['pytest-api']
        self.assertIn('/tests/test_01_health_gateway.py', pytest_cmd)
        self.assertIn('/tests/test_17_smart_library.py', pytest_cmd)
        self.assertIn('/tests/test_28_user_actor_journeys.py', pytest_cmd)
        self.assertNotEqual('/tests', pytest_cmd[-1])

    def test_wait_for_host_capture_accepts_sentinel(self):
        runner=load_runner()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'.host-post-capture-done').touch()
            self.assertTrue(runner.wait_for_host_capture(root, timeout_seconds=0.05, poll_seconds=0.01))


class LayeredRunnerProtocolTests(unittest.TestCase):
    def test_full_mode_adds_permission_boundary_and_optional_external_stages(self):
        runner=load_runner()
        core_commands=dict(runner._diagnostic_commands('full',False))
        external_commands=dict(runner._diagnostic_commands('full',True))
        self.assertTrue({'pytest-permissions','pytest-boundary','pytest-api'} <= set(core_commands))
        self.assertIn('not external and not permission and not boundary', core_commands['pytest-api'])
        self.assertNotIn('pytest-external', core_commands)
        self.assertEqual('/tests', external_commands['pytest-external'][-1])

    def test_quick_layered_mode_keeps_core_scope_bounded(self):
        runner=load_runner(); pytest_cmd=dict(runner._diagnostic_commands('quick',False))['pytest-api']
        expected={'/tests/test_01_health_gateway.py','/tests/test_17_smart_library.py','/tests/test_28_user_actor_journeys.py'}
        self.assertTrue(expected <= set(pytest_cmd))
        self.assertFalse({'/tests/test_14_scraper_existing_batch.py','/tests/test_15_scraper_new_series.py'} & set(pytest_cmd))

    def test_core_pytest_marker_filter_never_replaces_python_module_name(self):
        runner=load_runner()
        pytest_cmd=dict(runner._diagnostic_commands('full',False))['pytest-api']
        self.assertEqual(['-m', 'pytest'], pytest_cmd[2:4])
        marker_indexes=[index for index, value in enumerate(pytest_cmd) if value == '-m']
        self.assertGreaterEqual(len(marker_indexes), 2)
        self.assertEqual(
            'not external and not permission and not boundary',
            pytest_cmd[marker_indexes[-1] + 1],
        )

    def test_layered_pytest_stages_emit_junit_xml(self):
        runner=load_runner()
        commands=dict(runner._diagnostic_commands('full',True))
        expected={
            'pytest-permissions':'--junitxml=/results/pytest/permissions/junit.xml',
            'pytest-boundary':'--junitxml=/results/pytest/boundary/junit.xml',
            'pytest-api':'--junitxml=/results/pytest/junit-api.xml',
            'pytest-external':'--junitxml=/results/pytest/external/junit.xml',
        }
        for stage, junit_arg in expected.items():
            self.assertIn(junit_arg, commands[stage])

if __name__ == '__main__': unittest.main()
