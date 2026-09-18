"""Durable lifecycle-cleanup job helpers.

Database deletes remain authoritative. External cleanup (SeaweedFS, Valkey,
local image cache, optional CDN caches) is recorded in the same transaction and
performed after commit by the media lifecycle worker.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def enqueue_cleanup_job(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str | uuid.UUID | None,
    payload: dict[str, Any],
    max_attempts: int = 20,
) -> str:
    result = await db.execute(
        text(
            """
            INSERT INTO lifecycle_cleanup_jobs
                (entity_type, entity_id, payload, max_attempts)
            VALUES
                (:entity_type, CAST(:entity_id AS uuid), CAST(:payload AS jsonb), :max_attempts)
            RETURNING id::text
            """
        ),
        {
            "entity_type": str(entity_type)[:32],
            "entity_id": str(entity_id) if entity_id else None,
            "payload": json.dumps(payload, separators=(",", ":"), default=str),
            "max_attempts": max(1, min(int(max_attempts), 100)),
        },
    )
    return str(result.scalar_one())
