import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class RC485P02ReadingSourceAudit(unittest.TestCase):
    def test_normal_progress_runtime_uses_sync_commands_and_drain_is_maintenance_only(self):
        main = read("services/progress_go/cmd/api/main.go")
        config = read("services/progress_go/internal/config/config.go")
        service = read("services/progress_go/internal/progress/service.go")

        self.assertIn('getenv("PROGRESS_GO_DRAIN_LEGACY_STREAM", "0") == "1"', config)
        drain = main.index("if cfg.DrainLegacyStream {")
        flusher = main.index("progressService.RunFlusher(ctx)", drain)
        return_after_flusher = main.index("return", flusher)
        api_new = main.index("api := httpapi.New(")
        self.assertLess(drain, flusher)
        self.assertLess(flusher, return_after_flusher)
        self.assertLess(return_after_flusher, api_new)
        self.assertIn("return s.store.OpenReadingState", service)
        self.assertIn("return s.store.CommitReadingState", service)
        self.assertEqual(service.count("s.store.UpsertBatch("), 1)

    def test_command_path_mutates_resume_ledger_and_outbox_in_one_transaction(self):
        commands = read("services/progress_go/internal/store/commands.go")
        events = read("services/progress_go/internal/store/events.go")

        self.assertIn("func (s *Store) OpenReadingState", commands)
        self.assertIn("func (s *Store) CommitReadingState", commands)
        self.assertIn("pg_advisory_xact_lock", commands)
        self.assertIn("FOR KEY SHARE", commands)
        self.assertIn("INSERT INTO reading_progress", commands)
        self.assertIn("INSERT INTO chapter_reads", commands)
        self.assertIn("UPDATE chapter_reads SET", commands)
        self.assertIn("enqueueProgressUpdatedTx", commands)
        self.assertIn("tx.Commit(ctx)", commands)
        self.assertLess(commands.index("enqueueProgressUpdatedTx"), commands.index("tx.Commit(ctx)"))
        self.assertIn('"payload_schema": "v2/progress.updated.schema.json"', events)
        self.assertIn('"revision":', events)

    def test_http_contract_fences_account_and_reports_unsaved_storage(self):
        api = read("services/progress_go/internal/httpapi/api.go")
        self.assertIn('r.Header.Get("X-MReader-Account-ID")', api)
        self.assertIn('"code":   "account_mismatch"', api)
        self.assertIn('"code": "progress_unsaved"', api)
        self.assertIn("http.StatusServiceUnavailable", api)
        self.assertIn("DisallowUnknownFields", api)
        self.assertIn("http.MaxBytesReader(w, r.Body, 4096)", api)

    def test_reading_projection_separates_exact_history_from_migrated_reach(self):
        migration = read("db/migrations/052_reading_evidence_provenance.sql")
        self.assertIn("CREATE OR REPLACE VIEW reading_state_v1", migration)
        self.assertIn("cr.provenance <> 'migrated_reach'", migration)
        self.assertRegex(
            migration,
            re.compile(r"CASE WHEN exact\.has_history THEN rp\.chapter_id END AS resume_chapter_id", re.I),
        )
        self.assertIn("furthest.chapter_id AS furthest_chapter_id", migration)
        self.assertIn("ck_chapter_reads_inferred_reach", migration)

    def test_social_library_consumes_one_progress_projection_and_one_query_envelope(self):
        social = read("services/social_ts/src/routes.ts")
        self.assertIn("SELECT * FROM reading_state_v1", social)
        self.assertIn("const SMART_LIBRARY_BASE_SQL", social)
        self.assertIn("summary AS MATERIALIZED", social)
        self.assertIn("recently_opened: { items: envelope.recent_items", social)
        self.assertIn("prisma.$queryRawUnsafe<SmartLibraryEnvelope[]>", social)
        # Library must not rebuild its truth with a Progress HTTP history fallback.
        self.assertNotIn('/api/progress/history', social)

    def test_default_hybrid_deployment_does_not_enable_legacy_drain(self):
        manifest = read("deploy/docker-desktop-hybrid/user-apps.yaml")
        progress_start = manifest.index("name: progress-go")
        progress_end = manifest.find("\n---", progress_start)
        progress = manifest[progress_start: progress_end if progress_end != -1 else None]
        self.assertNotIn("PROGRESS_GO_DRAIN_LEGACY_STREAM", progress)
        self.assertIn("PROGRESS_GO_PORT", progress)

    def test_reading_and_event_contract_json_is_parseable(self):
        paths = [
            "contracts/reading/v1/open.schema.json",
            "contracts/reading/v1/commit.schema.json",
            "contracts/events/v2/progress.updated.schema.json",
        ]
        for path in paths:
            with self.subTest(path=path):
                parsed = json.loads(read(path))
                self.assertEqual(parsed.get("type"), "object")
                self.assertFalse(parsed.get("additionalProperties", True))


if __name__ == "__main__":
    unittest.main()
