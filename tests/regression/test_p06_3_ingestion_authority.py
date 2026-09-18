from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "db/migrations/055_ingestion_operation_authority.sql"
STORE = ROOT / "services/catalog_go/internal/store/publication.go"
DB_TEST = ROOT / "services/catalog_go/internal/store/publication_postgres_test.go"


class P063IngestionAuthorityTests(unittest.TestCase):
    def test_canonical_ingestion_operation_header_exists(self):
        self.assertTrue(MIGRATION.is_file(), "P06.3 prerequisite needs the canonical ingestion operation header")
        text = MIGRATION.read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS ingestion_operations", text)
        for field in (
            "requesting_actor_id", "source_kind", "status", "phase", "source_revision",
            "revision", "lease_generation", "cancel_requested_at", "acknowledged_at",
            "selected_count", "staged_count", "published_count", "failed_count", "error_code",
        ):
            self.assertIn(field, text)
        for status in (
            "queued", "running", "needs_review", "cancel_requested", "cancelled",
            "completed", "completed_with_errors", "failed",
        ):
            self.assertIn(status, text)

    def test_catalog_fences_and_reads_ingestion_authority_without_cross_domain_update_privilege(self):
        text = STORE.read_text()
        self.assertIn("func lockPublicationIngestionOperationTx(", text)
        self.assertIn("pg_advisory_xact_lock(hashtextextended($1, 485063))", text)
        self.assertIn("lockPublicationIngestionOperationTx(ctx, tx, command.OperationID)", text)
        self.assertIn("func publicationIngestionAuthorityTx(", text)
        block = text.split("func publicationIngestionAuthorityTx", 1)[1].split("func publicationActorAuthorizedTx", 1)[0]
        self.assertIn("FROM ingestion_operations", block)
        self.assertNotIn("FOR UPDATE", block)
        self.assertNotIn("FOR SHARE", block)
        self.assertIn("publicationIngestionAuthorityTx(ctx, tx, command.OperationID)", text)

    def test_catalog_compares_actor_source_revision_generation_and_cancellation(self):
        text = STORE.read_text()
        self.assertIn("ErrPublicationActorUnauthorized", text)
        self.assertIn("ErrStaleIngestionSourceRevision", text)
        self.assertIn("ErrStaleIngestionGeneration", text)
        self.assertIn("ErrIngestionCancelled", text)
        self.assertIn("authority.ActorID != command.ActorID", text)
        self.assertIn("authority.SourceRevision != command.SourceRevision", text)
        self.assertIn("authority.LeaseGeneration != command.IngestionGeneration", text)
        self.assertIn("authority.CancelRequestedAt != nil", text)
        self.assertIn('authority.Status != "running"', text)

    def test_catalog_rechecks_current_admin_authorization_with_read_only_auth_access(self):
        text = STORE.read_text()
        self.assertIn("func publicationActorAuthorizedTx(", text)
        block = text.split("func publicationActorAuthorizedTx", 1)[1].split("func validatePublicationIngestionAuthority", 1)[0]
        self.assertIn("FROM users", block)
        self.assertIn("is_active", block)
        self.assertIn("role", block)
        self.assertNotIn("FOR SHARE", block)
        self.assertNotIn("FOR UPDATE", block)
        self.assertIn('role != "admin"', text)

    def test_receipt_replay_precedes_ingestion_fence_and_authority_checks_precede_catalog_mutation(self):
        text = STORE.read_text()
        receipt = text.index("publicationReceiptTx(ctx, tx, command.IdempotencyKey)")
        fence = text.index("lockPublicationIngestionOperationTx(ctx, tx, command.OperationID)")
        authority = text.index("publicationIngestionAuthorityTx(ctx, tx, command.OperationID)")
        series_lock = text.index("FROM series", authority)
        self.assertLess(receipt, fence)
        self.assertLess(fence, authority)
        self.assertLess(authority, series_lock)
        found_block = text.index("if found {", receipt)
        found_return = text.index("return existing, nil", found_block)
        actor_check = text.index("publicationActorAuthorizedTx(ctx, tx, command.ActorID)", found_block)
        self.assertLess(actor_check, found_return)
        self.assertLess(found_return, fence)

    def test_real_db_suite_declares_fence_cancel_actor_and_concurrent_create_cases(self):
        text = DB_TEST.read_text()
        for test_name in (
            "TestCommitPublicationRejectsCancelledOrStaleIngestionAuthority",
            "TestCommitPublicationRejectsInactiveOrNonAdminActor",
            "TestCommitPublicationConcurrentCreateHasOneAuthoritativeWinner",
        ):
            self.assertIn("func " + test_name + "(", text)


if __name__ == "__main__":
    unittest.main()
