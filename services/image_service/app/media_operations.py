from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.events import enqueue_media_processed, enqueue_media_uploaded


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _mapping(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row._mapping)


class IngestionOperationAuthorityError(RuntimeError):
    pass


class MediaOperationLeaseLost(RuntimeError):
    """Raised when a worker tries to mutate a Media operation it no longer owns."""


@dataclass(frozen=True)
class IngestionAuthorityRequest:
    operation_id: str
    source_kind: str
    actor_id: str
    source_revision: int
    lease_generation: int


def _validate_ingestion_authority(
    authority: dict[str, Any],
    expected: IngestionAuthorityRequest,
) -> dict[str, Any]:
    if str(authority.get("source_kind") or "") != expected.source_kind:
        raise IngestionOperationAuthorityError("ingestion operation source kind does not match")
    if str(authority.get("requesting_actor_id") or "") != expected.actor_id:
        raise IngestionOperationAuthorityError("ingestion operation is owned by another requesting actor")
    if int(authority.get("source_revision") or 0) != int(expected.source_revision):
        raise IngestionOperationAuthorityError("ingestion operation source revision is stale")
    if int(authority.get("lease_generation") or 0) != int(expected.lease_generation):
        raise IngestionOperationAuthorityError("ingestion operation lease generation is stale")
    status_value = str(authority.get("status") or "")
    if authority.get("cancel_requested_at") is not None or status_value in {"cancel_requested", "cancelled"}:
        raise IngestionOperationAuthorityError("ingestion operation is cancelled")
    if status_value != "running":
        raise IngestionOperationAuthorityError("ingestion operation is not running")
    return authority


async def authorize_ingestion_operation(
    db,
    expected: IngestionAuthorityRequest,
    *,
    create_ingestion_header: bool,
) -> dict[str, Any]:
    """Create manual authority or validate an existing Scraper-owned header."""
    result = await db.execute(
        text(
            """
            SELECT id::text AS id, source_kind, requesting_actor_id::text AS requesting_actor_id,
                   status, phase, source_revision, lease_generation, cancel_requested_at
            FROM ingestion_operations
            WHERE id = CAST(:operation_id AS uuid)
            FOR UPDATE
            """
        ),
        {"operation_id": expected.operation_id},
    )
    authority = _mapping(result.first())

    if authority is None:
        if not create_ingestion_header:
            raise IngestionOperationAuthorityError("ingestion operation does not exist")
        if expected.source_kind != "manual-upload":
            raise IngestionOperationAuthorityError("only manual upload may create ingestion authority in Media")
        result = await db.execute(
            text(
                """
                INSERT INTO ingestion_operations(
                    id, source_kind, requesting_actor_id, status, phase,
                    source_revision, revision, lease_generation, selected_count, staged_count
                ) VALUES(
                    CAST(:operation_id AS uuid), :source_kind, CAST(:actor_id AS uuid),
                    'running', 'media_transform', :source_revision, 1, :lease_generation, 1, 1
                )
                RETURNING id::text AS id, source_kind,
                          requesting_actor_id::text AS requesting_actor_id, status, phase,
                          source_revision, lease_generation, cancel_requested_at
                """
            ),
            {
                "operation_id": expected.operation_id,
                "source_kind": expected.source_kind,
                "actor_id": expected.actor_id,
                "source_revision": int(expected.source_revision),
                "lease_generation": int(expected.lease_generation),
            },
        )
        authority = _mapping(result.first())

    if authority is None:
        raise IngestionOperationAuthorityError("ingestion operation authority is unavailable")
    return _validate_ingestion_authority(authority, expected)


async def create_media_operation(
    db,
    *,
    operation_id: str,
    job_type: str,
    series_id: str | None,
    series_slug: str,
    chapter_slug: str | None,
    staged_object_path: str,
    staged_object_paths: list[str] | None = None,
    input_filename: str | None,
    input_content_type: str | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Create durable accepted work and media.uploaded in one transaction."""
    await db.execute(
        text(
            """
            INSERT INTO media_operations (
                operation_id, job_type, status, series_id, series_slug,
                event_partition_key, chapter_slug, staged_object_path, input_filename,
                input_content_type, metadata
            ) VALUES (
                CAST(:operation_id AS uuid), :job_type, 'queued',
                CAST(:series_id AS uuid), :series_slug, :event_partition_key, :chapter_slug,
                :staged_object_path, :input_filename, :input_content_type,
                CAST(:metadata AS jsonb)
            )
            """
        ),
        {
            "operation_id": operation_id,
            "job_type": job_type,
            "series_id": series_id,
            "series_slug": series_slug,
            "event_partition_key": str(series_id or operation_id),
            "chapter_slug": chapter_slug,
            "staged_object_path": staged_object_path,
            "input_filename": input_filename,
            "input_content_type": input_content_type,
            "metadata": _json(metadata),
        },
    )

    accepted_paths: list[str] = []
    for path in staged_object_paths or [staged_object_path]:
        normalized = str(path or "").strip()
        if normalized and normalized not in accepted_paths:
            accepted_paths.append(normalized)
    if staged_object_path not in accepted_paths:
        accepted_paths.insert(0, staged_object_path)

    source_revision = int(metadata.get("source_revision") or 0)
    event_id = await enqueue_media_uploaded(
        db,
        upload_id=operation_id,
        series_id=series_id,
        chapter_id=None,
        object_paths=accepted_paths,
        source=job_type,
        partition_key=str(series_id or operation_id),
        metadata={
            "owner": "media",
            "request_id": str(metadata.get("request_id") or "").strip(),
            "operation_id": str(metadata.get("operation_id") or operation_id).strip(),
            "revision": source_revision if source_revision > 0 else None,
        },
    )

    await db.execute(
        text(
            """
            UPDATE media_operations
            SET uploaded_event_id = CAST(:event_id AS uuid),
                updated_at = NOW()
            WHERE operation_id = CAST(:operation_id AS uuid)
            """
        ),
        {"operation_id": operation_id, "event_id": event_id},
    )

    return await get_media_operation(db, operation_id)


async def get_media_operation(db, operation_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if for_update else ""
    result = await db.execute(
        text(
            """
            SELECT operation_id::text AS operation_id,
                   job_type, status,
                   series_id::text AS series_id, series_slug, event_partition_key,
                   chapter_id::text AS chapter_id, chapter_slug,
                   staged_object_path, input_filename, input_content_type,
                   metadata, result, output_paths,
                   media_generation, publication_operation_id::text AS publication_operation_id,
                   publication_actor_id::text AS publication_actor_id, source_revision,
                   manifest_sha256, publication_page_count, completion_evidence,
                   attempt_count, last_error, last_queue_error, queue_dispatched_at,
                   uploaded_event_id::text AS uploaded_event_id,
                   processed_event_id::text AS processed_event_id,
                   created_at, updated_at, processing_started_at, processing_heartbeat_at,
                   completed_at, failed_at
            FROM media_operations
            WHERE operation_id = CAST(:operation_id AS uuid)
            """ + suffix
        ),
        {"operation_id": operation_id},
    )
    return _mapping(result.first())


async def start_media_operation(
    db,
    operation_id: str,
    *,
    stale_after_seconds: int = 120,
) -> dict[str, Any] | None:
    """Acquire the durable single-owner processing lease for a Media job.

    RabbitMQ is at-least-once. A duplicate delivery while another worker has a
    fresh heartbeat must be deferred, not ACKed as completed and not executed a
    second time. If the previous worker disappeared and its heartbeat is stale,
    the replacement delivery may reclaim the row immediately.
    """
    operation = await get_media_operation(db, operation_id, for_update=True)
    if operation is None:
        return None
    if operation["status"] in {"completed", "failed"}:
        operation["skip_before_start"] = True
        operation["skip_reason"] = operation["status"]
        return operation

    if operation["status"] == "processing":
        heartbeat = (
            operation.get("processing_heartbeat_at")
            or operation.get("processing_started_at")
            or operation.get("updated_at")
        )
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(30, int(stale_after_seconds)))
        if heartbeat is not None and heartbeat >= cutoff:
            operation["defer_before_start"] = True
            operation["skip_reason"] = "processing"
            return operation

    await db.execute(
        text(
            """
            UPDATE media_operations
            SET status = 'processing',
                attempt_count = attempt_count + 1,
                media_generation = media_generation + 1,
                processing_started_at = NOW(),
                processing_heartbeat_at = NOW(),
                updated_at = NOW(),
                last_queue_error = NULL
            WHERE operation_id = CAST(:operation_id AS uuid)
            """
        ),
        {"operation_id": operation_id},
    )
    operation["status"] = "processing"
    operation["attempt_count"] = int(operation.get("attempt_count") or 0) + 1
    operation["media_generation"] = int(operation.get("media_generation") or 0) + 1
    operation["processing_heartbeat_at"] = datetime.now(timezone.utc)
    return operation


async def heartbeat_media_operation(db, operation_id: str, *, expected_generation: int) -> bool:
    result = await db.execute(
        text(
            """
            UPDATE media_operations
            SET processing_heartbeat_at = NOW(),
                updated_at = NOW()
            WHERE operation_id = CAST(:operation_id AS uuid)
              AND status = 'processing'
              AND media_generation = :expected_generation
            """
        ),
        {"operation_id": operation_id, "expected_generation": int(expected_generation)},
    )
    return bool(getattr(result, "rowcount", 0))


_MARK_MEDIA_RETRY_SQL = """
UPDATE media_operations
SET status = 'retry',
    last_error = :error,
    processing_heartbeat_at = NULL,
    updated_at = NOW()
WHERE operation_id = CAST(:operation_id AS uuid)
  AND status = 'processing'
  AND media_generation = :expected_generation
"""

_RECORD_CATALOG_RECEIPT_SQL = """
UPDATE media_operations
SET result = jsonb_set(
        COALESCE(result, '{}'::jsonb),
        '{catalog_receipt}',
        CAST(:receipt AS jsonb),
        true
    ),
    updated_at = NOW()
WHERE operation_id = CAST(:operation_id AS uuid)
  AND status = 'completed'
  AND completion_evidence IS NOT NULL
"""


async def _execute_operation_update(db, sql: str, params: dict[str, Any]):
    return await db.execute(text(sql), params)


async def mark_media_retry(db, operation_id: str, error: str, *, expected_generation: int) -> None:
    result = await _execute_operation_update(
        db,
        _MARK_MEDIA_RETRY_SQL,
        {
            "operation_id": operation_id,
            "error": error[:8000],
            "expected_generation": int(expected_generation),
        },
    )
    if not getattr(result, "rowcount", 0):
        raise MediaOperationLeaseLost(
            f"media operation {operation_id} generation {expected_generation} is no longer owned"
        )


def _require_media_generation(
    operation: dict[str, Any],
    operation_id: str,
    expected_generation: int,
) -> None:
    if int(operation.get("media_generation") or 0) != int(expected_generation):
        raise MediaOperationLeaseLost(
            f"media operation {operation_id} generation {expected_generation} is no longer owned"
        )


async def record_queue_error(db, operation_id: str, error: str | None) -> None:
    await db.execute(
        text(
            """
            UPDATE media_operations
            SET last_queue_error = :error,
                queue_dispatched_at = CASE WHEN :error IS NULL THEN NOW() ELSE NULL END,
                updated_at = NOW()
            WHERE operation_id = CAST(:operation_id AS uuid)
              AND status IN ('queued','retry')
            """
        ),
        {"operation_id": operation_id, "error": (error[:8000] if error else None)},
    )


def _media_operation_event_metadata(operation: dict[str, Any], *, status: str) -> dict[str, Any]:
    operation_metadata = dict(operation.get("metadata") or {})
    source_revision = int(operation.get("source_revision") or operation_metadata.get("source_revision") or 0)
    return {
        "owner": "media",
        "request_id": str(operation_metadata.get("request_id") or "").strip(),
        "operation_id": str(
            operation.get("publication_operation_id")
            or operation_metadata.get("operation_id")
            or operation.get("operation_id")
            or ""
        ).strip(),
        "revision": source_revision if source_revision > 0 else None,
        "error_code": "media.processing_failed" if status == "failed" else None,
        "retryable": False if status == "failed" else None,
    }


async def _prepare_terminal_media_event(
    db,
    *,
    operation_id: str,
    expected_generation: int,
    source: str,
    status: str,
    series_id: str | None = None,
    chapter_id: str | None = None,
    output_paths: list[str] | None = None,
    error: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    operation = await get_media_operation(db, operation_id, for_update=True)
    if operation is None:
        return None, None
    _require_media_generation(operation, operation_id, expected_generation)
    if operation.get("processed_event_id"):
        return operation, str(operation["processed_event_id"])
    if status == "failed" and operation.get("status") == "completed":
        return operation, None

    resolved_series_id = series_id or operation.get("series_id")
    resolved_chapter_id = chapter_id or operation.get("chapter_id")
    resolved_paths = list(output_paths if output_paths is not None else (operation.get("output_paths") or []))
    event_id = await enqueue_media_processed(
        db,
        job_id=operation_id,
        series_id=resolved_series_id,
        chapter_id=resolved_chapter_id,
        status=status,
        output_paths=resolved_paths,
        error=(error[:8000] if error else None),
        source=source,
        partition_key=operation.get("event_partition_key"),
        metadata=_media_operation_event_metadata(operation, status=status),
    )
    return operation, event_id


async def _persist_media_completion(
    db,
    *,
    operation_id: str,
    expected_generation: int,
    series_id: str | None,
    chapter_id: str | None,
    result: dict[str, Any],
    output_paths: list[str],
    event_id: str,
) -> None:
    await db.execute(
        text(
            """
            UPDATE media_operations
            SET status = 'completed',
                series_id = COALESCE(CAST(:series_id AS uuid), series_id),
                chapter_id = COALESCE(CAST(:chapter_id AS uuid), chapter_id),
                result = CAST(:result AS jsonb),
                output_paths = CAST(:output_paths AS jsonb),
                processed_event_id = CAST(:event_id AS uuid),
                last_error = NULL,
                last_queue_error = NULL,
                completed_at = NOW(),
                failed_at = NULL,
                processing_heartbeat_at = NULL,
                updated_at = NOW()
            WHERE operation_id = CAST(:operation_id AS uuid)
              AND media_generation = :expected_generation
            """
        ),
        {
            "operation_id": operation_id,
            "series_id": series_id,
            "chapter_id": chapter_id,
            "result": _json(result),
            "output_paths": _json(output_paths),
            "event_id": event_id,
            "expected_generation": int(expected_generation),
        },
    )


async def _persist_media_failure(
    db,
    *,
    operation_id: str,
    expected_generation: int,
    error: str,
    event_id: str,
) -> None:
    await db.execute(
        text(
            """
            UPDATE media_operations
            SET status = 'failed',
                last_error = :error,
                processed_event_id = CAST(:event_id AS uuid),
                failed_at = NOW(),
                processing_heartbeat_at = NULL,
                updated_at = NOW()
            WHERE operation_id = CAST(:operation_id AS uuid)
              AND media_generation = :expected_generation
            """
        ),
        {
            "operation_id": operation_id,
            "error": error[:8000],
            "event_id": event_id,
            "expected_generation": int(expected_generation),
        },
    )


async def _finish_media_operation(
    db,
    *,
    operation_id: str,
    expected_generation: int,
    source: str,
    status: str,
    series_id: str | None = None,
    chapter_id: str | None = None,
    output_paths: list[str] | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> str | None:
    operation, event_id = await _prepare_terminal_media_event(
        db,
        operation_id=operation_id,
        expected_generation=expected_generation,
        source=source,
        status=status,
        series_id=series_id,
        chapter_id=chapter_id,
        output_paths=output_paths,
        error=error,
    )
    if operation is None or event_id is None:
        return event_id
    if status == "processed":
        await _persist_media_completion(
            db,
            operation_id=operation_id,
            expected_generation=expected_generation,
            series_id=series_id,
            chapter_id=chapter_id,
            result=dict(result or {}),
            output_paths=list(output_paths or []),
            event_id=event_id,
        )
    else:
        await _persist_media_failure(
            db,
            operation_id=operation_id,
            expected_generation=expected_generation,
            error=str(error or ""),
            event_id=event_id,
        )
    return event_id


async def complete_media_operation(
    db,
    *,
    operation_id: str,
    series_id: str | None,
    chapter_id: str | None,
    output_paths: list[str],
    result: dict[str, Any],
    source: str,
    expected_generation: int,
) -> str | None:
    """Commit terminal success + media.processed in the caller's transaction."""
    normalized_paths = [str(path) for path in output_paths]
    normalized_result = dict(result)
    event_id = await _finish_media_operation(
        db,
        operation_id=operation_id,
        expected_generation=expected_generation,
        source=source,
        status="processed",
        series_id=series_id,
        chapter_id=chapter_id,
        output_paths=normalized_paths,
        result=normalized_result,
    )
    return event_id


async def record_publication_completion_evidence(
    db,
    *,
    media_operation_id: str,
    operation_id: str,
    actor_id: str,
    source_revision: int,
    manifest_sha256: str,
    page_count: int,
) -> dict[str, Any]:
    """Attach immutable Catalog-consumable evidence to a completed Media operation.

    This extends the existing ``media_operations`` durability boundary. It does not
    create a second Media queue or declare production Catalog publication success.
    """
    operation = await get_media_operation(db, media_operation_id, for_update=True)
    if operation is None:
        raise ValueError("media operation not found")

    status = str(operation.get("status") or "")
    if status != 'completed':
        raise ValueError("publication evidence requires a completed media operation")

    media_generation = int(operation.get("media_generation") or 0)
    if media_generation < 1:
        raise ValueError("publication evidence requires a positive media generation")
    if int(source_revision) < 1:
        raise ValueError("source_revision must be positive")
    if int(page_count) < 1 or int(page_count) > 4096:
        raise ValueError("page_count must be between 1 and 4096")

    digest = str(manifest_sha256 or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("manifest_sha256 must be lowercase sha256 hex")

    completion_evidence = {
        "schema_version": 1,
        "status": "completed",
        "media_operation_id": str(media_operation_id),
        "operation_id": str(operation_id),
        "actor_id": str(actor_id),
        "source_revision": int(source_revision),
        "media_generation": media_generation,
        "page_count": int(page_count),
        "manifest_sha256": digest,
    }

    existing = operation.get("completion_evidence")
    if existing is not None:
        if dict(existing) == completion_evidence:
            return completion_evidence
        raise ValueError("publication completion evidence conflict")

    await db.execute(
        text(
            """
            UPDATE media_operations
            SET publication_operation_id = CAST(:operation_id AS uuid),
                publication_actor_id = CAST(:actor_id AS uuid),
                source_revision = :source_revision,
                manifest_sha256 = :manifest_sha256,
                publication_page_count = :page_count,
                completion_evidence = CAST(:completion_evidence AS jsonb),
                updated_at = NOW()
            WHERE operation_id = CAST(:media_operation_id AS uuid)
              AND status = 'completed'
              AND media_generation = :media_generation
            """
        ),
        {
            "media_operation_id": media_operation_id,
            "operation_id": operation_id,
            "actor_id": actor_id,
            "source_revision": int(source_revision),
            "manifest_sha256": digest,
            "page_count": int(page_count),
            "media_generation": media_generation,
            "completion_evidence": _json(completion_evidence),
        },
    )
    return completion_evidence


async def record_catalog_publication_receipt(
    db,
    *,
    operation_id: str,
    receipt: dict[str, Any],
) -> None:
    """Record Catalog's authoritative receipt as an observation on Media work.

    Media remains the transformation owner; this copy exists only so retries can
    distinguish a completed transform that still needs Catalog reconciliation.
    """
    await _execute_operation_update(
        db,
        _RECORD_CATALOG_RECEIPT_SQL,
        {"operation_id": operation_id, "receipt": _json(receipt)},
    )


async def fail_media_operation(
    db,
    *,
    operation_id: str,
    error: str,
    source: str,
    expected_generation: int,
) -> str | None:
    """Commit one terminal failed state + media.processed event."""
    failure_message = str(error).strip() or "media operation failed"
    event_id = await _finish_media_operation(
        db,
        operation_id=operation_id,
        expected_generation=expected_generation,
        source=source,
        status="failed",
        error=failure_message,
    )
    return event_id


async def recoverable_media_operations(
    db,
    *,
    limit: int = 500,
    stale_after_seconds: int = 120,
) -> list[dict[str, Any]]:
    """Return transform work plus completed publications still needing reconciliation."""
    await db.execute(
        text(
            """
            UPDATE media_operations
            SET status = 'retry',
                last_error = COALESCE(last_error, 'Recovered stale processing operation after worker restart.'),
                queue_dispatched_at = NULL,
                processing_heartbeat_at = NULL,
                updated_at = NOW()
            WHERE status = 'processing'
              AND COALESCE(processing_heartbeat_at, processing_started_at, updated_at)
                    < NOW() - (:stale_after_seconds * INTERVAL '1 second')
            """
        ),
        {"stale_after_seconds": max(30, int(stale_after_seconds))},
    )
    result = await db.execute(
        text(
            """
            SELECT operation_id::text AS operation_id,
                   job_type, status, series_slug, chapter_slug,
                   staged_object_path, input_filename, input_content_type,
                   metadata
            FROM media_operations
            WHERE (
                    status IN ('queued','retry')
                    AND queue_dispatched_at IS NULL
                  )
               OR (
                    job_type = 'chapter-ingestion'
                    AND status = 'completed'
                    AND completion_evidence IS NOT NULL
                    AND COALESCE(result, '{}'::jsonb)->'catalog_receipt' IS NULL
                  )
            ORDER BY created_at, operation_id
            LIMIT :limit
            """
        ),
        {"limit": max(1, min(5000, int(limit)))},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def operation_api_payload(operation: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(operation.get("metadata") or {})
    payload = {
        **metadata,
        "series_slug": operation.get("series_slug"),
        "chapter_slug": operation.get("chapter_slug"),
        "source_path": operation.get("staged_object_path"),
    }
    return {
        "job_id": operation["operation_id"],
        "job_type": operation["job_type"],
        "status": operation["status"],
        "payload": payload,
        "result": operation.get("result"),
        "error": operation.get("last_error") or operation.get("last_queue_error"),
        "attempt_count": int(operation.get("attempt_count") or 0),
        "updated_at": _timestamp(operation.get("updated_at")),
        "durable": True,
    }


def _timestamp(value: datetime | None) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp())
