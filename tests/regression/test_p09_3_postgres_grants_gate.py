from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts/test/p09-3-postgres-grants-gate.sh"


class P093PostgresGrantsGateSourceTests(unittest.TestCase):
    def test_gate_source_contract(self):
        self.assertTrue(GATE.exists())
        text = GATE.read_text()
        marker_groups = {
            "target safety": (
                "MREADER_P09_3_POSTGRES_DSN",
                "MREADER_P09_3_ALLOW_DISPOSABLE_DSN",
                "postgres:16.10-alpine3.22",
                "command -v docker",
            ),
            "terminal states": (
                "P09.3 POSTGRES GRANTS GATE PASSED",
                "P09.3 POSTGRES GRANTS GATE FAILED",
                "P09.3 POSTGRES GRANTS GATE BLOCKED:",
                "exit 2",
            ),
            "all workload probes": (
                "contract['workloads']",
                "role_connection_uri",
                "run_as_workload",
                "required SELECT",
                "CREATE ROLE p093_forbidden",
                "CREATE DATABASE p093_forbidden",
                "CREATE TABLE public.p093_new_table",
                "SELECT * FROM public.p093_new_table",
                "CREATE FUNCTION public.p093_new_function",
                "SELECT public.p093_new_function()",
                "forbidden cross-domain INSERT",
                "forbidden cross-domain UPDATE",
                "forbidden cross-domain DELETE",
                "DEFAULT VALUES",
                "WHERE false",
            ),
            "named boundaries": (
                "notification creation/read-state",
                "outbox producer/relay",
                "lifecycle enqueue/execute",
                "catalog parent-delete",
                "reader trending write",
                "keda select-only",
                "mreader_notification_worker",
                "mreader_social_ts",
                "mreader_outbox_relay",
                "mreader_lifecycle_worker",
                "mreader_catalog_go",
                "mreader_reader_go",
                "mreader_keda_metrics",
            ),
        }
        for group, markers in marker_groups.items():
            for marker in markers:
                with self.subTest(group=group, marker=marker):
                    self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
