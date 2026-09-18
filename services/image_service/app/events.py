from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text


MEDIA_UPLOADED_TOPIC = "media.uploaded"
MEDIA_UPLOADED_EVENT_TYPE = "media.uploaded"
MEDIA_PROCESSED_TOPIC = "media.processed"
MEDIA_PROCESSED_EVENT_TYPE = "media.processed"
MEDIA_EVENT_VERSION = 1
MEDIA_EVENT_PRODUCER = "image-service"


def _safe_event_metadata(metadata: dict | None) -> dict:
    values = {"owner": "media"}
    if not metadata:
        return values
    for key in ("request_id", "operation_id", "revision", "error_code", "retryable"):
        value = metadata.get(key)
        if value is None or value == "":
            continue
        values[key] = value
    return values


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def enqueue_media_uploaded(
    db,
    *,
    upload_id: str,
    series_id: str | None,
    chapter_id: str | None,
    object_paths: list[str],
    source: str,
    partition_key: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Write media.uploaded to PostgreSQL in the caller's transaction."""
    occurred_at = datetime.now(timezone.utc)
    payload = {
        "upload_id": str(upload_id),
        "series_id": (str(series_id) if series_id else None),
        "chapter_id": (str(chapter_id) if chapter_id else None),
        "object_paths": [str(path) for path in object_paths],
        "uploaded_at": _iso_timestamp(occurred_at),
    }
    headers = {
        "content_type": "application/json",
        "payload_schema": "v1/media.uploaded.schema.json",
        "source": source,
        **_safe_event_metadata(metadata),
    }
    result = await db.execute(
        text(
            """
            SELECT enqueue_event_outbox_v1(
                :topic, :event_type, :event_version,
                :aggregate_type, :aggregate_id, :partition_key, :producer,
                CAST(:payload AS jsonb), NULL, NULL, CAST(:headers AS jsonb),
                :occurred_at
            )::text
            """
        ),
        {
            "topic": MEDIA_UPLOADED_TOPIC,
            "event_type": MEDIA_UPLOADED_EVENT_TYPE,
            "event_version": MEDIA_EVENT_VERSION,
            "aggregate_type": "media_operation",
            "aggregate_id": str(upload_id),
            "partition_key": str(partition_key or series_id or upload_id),
            "producer": MEDIA_EVENT_PRODUCER,
            "payload": json.dumps(payload, separators=(",", ":")),
            "headers": json.dumps(headers, separators=(",", ":")),
            "occurred_at": occurred_at,
        },
    )
    event_id = result.scalar_one_or_none()
    if not event_id:
        raise RuntimeError("Failed to enqueue media.uploaded outbox event.")
    return str(event_id)


async def enqueue_media_processed(
    db,
    *,
    job_id: str,
    series_id: str | None,
    chapter_id: str | None,
    status: str,
    output_paths: list[str],
    error: str | None,
    source: str,
    partition_key: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Write one terminal media.processed event in the caller's transaction."""
    if status not in {"processed", "failed"}:
        raise ValueError("media.processed status must be processed or failed")
    occurred_at = datetime.now(timezone.utc)
    payload = {
        "job_id": str(job_id),
        "series_id": (str(series_id) if series_id else None),
        "chapter_id": (str(chapter_id) if chapter_id else None),
        "status": status,
        "output_paths": [str(path) for path in output_paths],
        "error": error,
        "processed_at": _iso_timestamp(occurred_at),
    }
    headers = {
        "content_type": "application/json",
        "payload_schema": "v1/media.processed.schema.json",
        "source": source,
        **_safe_event_metadata(metadata),
    }
    result = await db.execute(
        text(
            """
            SELECT enqueue_event_outbox_v1(
                :topic, :event_type, :event_version,
                :aggregate_type, :aggregate_id, :partition_key, :producer,
                CAST(:payload AS jsonb), NULL, NULL, CAST(:headers AS jsonb),
                :occurred_at
            )::text
            """
        ),
        {
            "topic": MEDIA_PROCESSED_TOPIC,
            "event_type": MEDIA_PROCESSED_EVENT_TYPE,
            "event_version": MEDIA_EVENT_VERSION,
            "aggregate_type": "media_operation",
            "aggregate_id": str(job_id),
            "partition_key": str(partition_key or series_id or job_id),
            "producer": MEDIA_EVENT_PRODUCER,
            "payload": json.dumps(payload, separators=(",", ":")),
            "headers": json.dumps(headers, separators=(",", ":")),
            "occurred_at": occurred_at,
        },
    )
    event_id = result.scalar_one_or_none()
    if not event_id:
        raise RuntimeError("Failed to enqueue media.processed outbox event.")
    return str(event_id)
