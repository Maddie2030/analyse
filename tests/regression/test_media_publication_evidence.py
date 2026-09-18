import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "image_service"))
sys.path.insert(0, str(ROOT / "shared"))

from app import media_operations  # noqa: E402


class FakeDB:
    def __init__(self, rowcount=1):
        self.calls = []
        self.rowcount = rowcount

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return SimpleNamespace(rowcount=self.rowcount)


class MediaPublicationEvidenceTests(IsolatedAsyncioTestCase):
    async def test_start_increments_media_generation_with_attempt(self):
        db = FakeDB()
        current = {
            "status": "queued",
            "attempt_count": 2,
            "media_generation": 4,
            "processing_heartbeat_at": None,
        }
        with patch.object(media_operations, "get_media_operation", AsyncMock(return_value=current)):
            result = await media_operations.start_media_operation(db, "11111111-1111-4111-8111-111111111111")

        self.assertEqual(result["attempt_count"], 3)
        self.assertEqual(result["media_generation"], 5)
        self.assertIn("media_generation = media_generation + 1", db.calls[0][0])

    async def test_completed_operation_records_generation_bound_evidence(self):
        db = FakeDB()
        current = {
            "status": "completed",
            "media_generation": 3,
            "completion_evidence": None,
        }
        with patch.object(media_operations, "get_media_operation", AsyncMock(return_value=current)):
            result = await media_operations.record_publication_completion_evidence(
                db,
                media_operation_id="11111111-1111-4111-8111-111111111111",
                operation_id="22222222-2222-4222-8222-222222222222",
                actor_id="33333333-3333-4333-8333-333333333333",
                source_revision=7,
                manifest_sha256="a" * 64,
                page_count=12,
            )

        self.assertEqual(result["media_generation"], 3)
        self.assertEqual(result["page_count"], 12)
        sql, params = db.calls[0]
        self.assertIn("media_generation = :media_generation", sql)
        self.assertEqual(params["media_generation"], 3)
        self.assertEqual(json.loads(params["completion_evidence"]), result)

    async def test_identical_evidence_replays_without_second_write(self):
        expected = {
            "schema_version": 1,
            "status": "completed",
            "media_operation_id": "11111111-1111-4111-8111-111111111111",
            "operation_id": "22222222-2222-4222-8222-222222222222",
            "actor_id": "33333333-3333-4333-8333-333333333333",
            "source_revision": 7,
            "media_generation": 3,
            "page_count": 12,
            "manifest_sha256": "a" * 64,
        }
        db = FakeDB()
        current = {"status": "completed", "media_generation": 3, "completion_evidence": expected}
        with patch.object(media_operations, "get_media_operation", AsyncMock(return_value=current)):
            result = await media_operations.record_publication_completion_evidence(
                db,
                media_operation_id=expected["media_operation_id"],
                operation_id=expected["operation_id"],
                actor_id=expected["actor_id"],
                source_revision=expected["source_revision"],
                manifest_sha256=expected["manifest_sha256"],
                page_count=expected["page_count"],
            )
        self.assertEqual(result, expected)
        self.assertEqual(db.calls, [])

    async def test_same_media_operation_cannot_rebind_different_evidence(self):
        existing = {
            "schema_version": 1,
            "status": "completed",
            "media_operation_id": "11111111-1111-4111-8111-111111111111",
            "operation_id": "22222222-2222-4222-8222-222222222222",
            "actor_id": "33333333-3333-4333-8333-333333333333",
            "source_revision": 7,
            "media_generation": 3,
            "page_count": 12,
            "manifest_sha256": "a" * 64,
        }
        db = FakeDB()
        current = {"status": "completed", "media_generation": 3, "completion_evidence": existing}
        with patch.object(media_operations, "get_media_operation", AsyncMock(return_value=current)):
            with self.assertRaisesRegex(ValueError, "evidence conflict"):
                await media_operations.record_publication_completion_evidence(
                    db,
                    media_operation_id=existing["media_operation_id"],
                    operation_id=existing["operation_id"],
                    actor_id=existing["actor_id"],
                    source_revision=8,
                    manifest_sha256=existing["manifest_sha256"],
                    page_count=existing["page_count"],
                )
        self.assertEqual(db.calls, [])

    async def test_incomplete_or_generation_zero_operation_cannot_issue_evidence(self):
        for current, message in [
            ({"status": "processing", "media_generation": 2}, "completed"),
            ({"status": "completed", "media_generation": 0}, "positive media generation"),
        ]:
            db = FakeDB()
            with patch.object(media_operations, "get_media_operation", AsyncMock(return_value=current)):
                with self.assertRaisesRegex(ValueError, message):
                    await media_operations.record_publication_completion_evidence(
                        db,
                        media_operation_id="11111111-1111-4111-8111-111111111111",
                        operation_id="22222222-2222-4222-8222-222222222222",
                        actor_id="33333333-3333-4333-8333-333333333333",
                        source_revision=1,
                        manifest_sha256="a" * 64,
                        page_count=1,
                    )


if __name__ == "__main__":
    import unittest
    unittest.main()
