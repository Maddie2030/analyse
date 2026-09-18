"""Durable handoff of production-object cleanup to the Lifecycle owner."""
from __future__ import annotations

from typing import Iterable

from shared import AsyncSessionLocal
from shared.lifecycle import enqueue_cleanup_job


def _exact_paths(paths: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for raw in paths:
        path = str(raw or "").replace("\\", "/").strip().lstrip("/")
        if not path or ".." in path.split("/"):
            continue
        if path not in normalized:
            normalized.append(path)
    return normalized


async def enqueue_production_output_cleanup(
    *,
    media_operation_id: str,
    media_generation: int,
    paths: Iterable[str],
    kind: str,
    reason: str,
    series_id: str | None = None,
    chapter_ids: Iterable[str] | None = None,
) -> str | None:
    """Queue exact generation-bound output cleanup; never delete production here."""
    generation = int(media_generation)
    if generation < 1:
        raise ValueError("production cleanup requires a positive media_generation")
    object_kind = str(kind or "").strip()
    if not object_kind:
        raise ValueError("production cleanup requires an object kind")

    image_paths = _exact_paths(paths)
    if not image_paths:
        return None

    object_refs = [
        {"path": path, "generation": generation, "kind": object_kind}
        for path in image_paths
    ]
    payload = {
        "schema_version": 2,
        "media_operation_id": str(media_operation_id),
        "media_generation": generation,
        "object_refs": object_refs,
        # Kept for token/cache invalidation compatibility; Lifecycle derives
        # physical deletion exclusively from exact object_refs for v2 jobs.
        "image_paths": image_paths,
        "reason": str(reason)[:200],
    }
    if series_id:
        payload["series_id"] = str(series_id)
    if chapter_ids:
        payload["chapter_ids"] = [str(value) for value in chapter_ids if str(value)]

    async with AsyncSessionLocal() as db:
        job_id = await enqueue_cleanup_job(
            db,
            entity_type="media_output",
            entity_id=media_operation_id,
            payload=payload,
        )
        await db.commit()
    return job_id
