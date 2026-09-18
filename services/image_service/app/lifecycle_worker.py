"""Durable post-commit cleanup worker for deleted/replaced MReader entities."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import redis.asyncio as aioredis
from sqlalchemy import text

from shared import AsyncSessionLocal, close_redis_pool, close_seaweedfs_client, get_redis, get_seaweedfs, init_redis_pool, init_seaweedfs_client

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("mreader.lifecycle")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
CACHE_MODE = os.getenv("LIFECYCLE_IMAGE_CACHE_MODE", "passive").strip().lower()
CACHE_ROOT = Path(os.getenv("IMAGE_EDGE_CACHE_ROOT", "/var/cache/nginx/mreader-images"))
POLL_SECONDS = max(1.0, float(os.getenv("LIFECYCLE_CLEANUP_POLL_SECONDS", "2")))
HEARTBEAT_SECONDS = max(5.0, float(os.getenv("LIFECYCLE_HEARTBEAT_SECONDS", "30")))
STALE_PROCESSING_SECONDS = max(60, int(os.getenv("LIFECYCLE_PROCESSING_STALE_SECONDS", "300")))
RECOVERY_INTERVAL_SECONDS = max(15.0, float(os.getenv("LIFECYCLE_RECOVERY_INTERVAL_SECONDS", "60")))
COMPLETED_RETENTION_DAYS = max(1, int(os.getenv("LIFECYCLE_COMPLETED_RETENTION_DAYS", "30")))
PRUNE_INTERVAL_SECONDS = max(300.0, float(os.getenv("LIFECYCLE_PRUNE_INTERVAL_SECONDS", "3600")))
SCRAPER_STAGING_ROOT = Path(os.getenv("SCRAPER_STAGING_ROOT", "/var/lib/mreader/scraper-staging")).expanduser().resolve()
SPOOL_MARKER = ".mreader-staging-spool-id"
CACHE_REDIS_URL = os.getenv("CACHE_REDIS_URL", "redis://redis-cache:6380/0").strip()
_cache_redis: aioredis.Redis | None = None


def _init_cache_redis() -> None:
    global _cache_redis
    if _cache_redis is None:
        _cache_redis = aioredis.from_url(
            CACHE_REDIS_URL, decode_responses=True, socket_connect_timeout=5,
            socket_timeout=5, health_check_interval=30,
        )


async def _get_cache_redis() -> aioredis.Redis:
    if _cache_redis is None:
        _init_cache_redis()
    assert _cache_redis is not None
    return _cache_redis


async def _close_cache_redis() -> None:
    global _cache_redis
    if _cache_redis is not None:
        await _cache_redis.aclose()
        _cache_redis = None


def _mountinfo_has_path(path: Path) -> bool:
    try:
        wanted = str(path)
        for line in Path("/proc/self/mountinfo").read_text(errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 5:
                mountpoint = parts[4].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
                if mountpoint == wanted:
                    return True
    except OSError:
        pass
    return False


def _read_or_create_spool_id() -> str:
    SCRAPER_STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    marker = SCRAPER_STAGING_ROOT / SPOOL_MARKER
    try:
        return str(uuid.UUID(marker.read_text(encoding="utf-8").strip()))
    except FileNotFoundError:
        pass
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"Invalid scraper staging spool marker at {marker}: {exc}") from exc
    candidate = str(uuid.uuid4())
    try:
        fd = os.open(str(marker), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o660)
    except FileExistsError:
        return str(uuid.UUID(marker.read_text(encoding="utf-8").strip()))
    try:
        # os.open mode is subject to umask; force the shared marker mode so
        # scraper/lifecycle images can read the same volume marker reliably.
        os.fchmod(fd, 0o660)
        os.write(fd, (candidate + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return candidate


async def _staging_reference_status() -> dict[str, Any]:
    """Verify every live PostgreSQL staging reference exists on the shared PVC.

    Current MReader deliberately avoids source-URL/previous-spool reconstruction. A
    staged reference is valid only while its file exists on the canonical
    scraper-staging PVC. Missing files require an explicit re-stage/re-upload.
    """
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("""
            WITH refs AS (
                SELECT p->>'staging_path' AS path
                FROM scraper_series_draft_chapters c
                CROSS JOIN LATERAL jsonb_array_elements(COALESCE(c.pages,'[]'::jsonb)) p
                WHERE c.published_chapter_id IS NULL
                  AND COALESCE(p->>'staging_path','') LIKE '_scraper/%'
                UNION
                SELECT d.cover_staging_path AS path
                FROM scraper_series_drafts d
                WHERE d.published_series_id IS NULL
                  AND COALESCE(d.cover_staging_path,'') LIKE '_scraper/%'
                UNION
                SELECT p->>'staging_path' AS path
                FROM scraper_drafts d
                CROSS JOIN LATERAL jsonb_array_elements(COALESCE(d.pages,'[]'::jsonb)) p
                WHERE COALESCE(p->>'staging_path','') LIKE '_scraper/%'
                UNION
                SELECT p->>'staging_path' AS path
                FROM scraper_batch_items i
                CROSS JOIN LATERAL jsonb_array_elements(COALESCE(i.source_files,'[]'::jsonb)) p
                WHERE COALESCE(p->>'staging_path','') LIKE '_scraper/%'
                  AND i.status NOT IN ('completed','discarded')
            )
            SELECT path FROM refs WHERE path IS NOT NULL AND path <> '' ORDER BY path LIMIT 200
        """))).scalars().all()

    missing: list[str] = []
    visible = 0
    for raw in rows:
        normalized = str(raw or '').replace('\\', '/').strip().lstrip('/')
        if not normalized.startswith('_scraper/') or '..' in normalized.split('/'):
            missing.append(normalized)
            continue
        target = (SCRAPER_STAGING_ROOT / normalized).resolve()
        try:
            target.relative_to(SCRAPER_STAGING_ROOT)
            exists = await asyncio.to_thread(target.is_file)
        except (ValueError, OSError):
            exists = False
        if exists:
            visible += 1
        else:
            missing.append(normalized)
    return {
        'reference_sample': len(rows),
        'reference_visible': visible,
        'reference_missing': len(missing),
        'reference_missing_examples': missing[:5],
    }


async def _ensure_scraper_staging_spool() -> str:
    """Verify lifecycle cleanup sees the exact spool registered by scraper workers."""
    if not _mountinfo_has_path(SCRAPER_STAGING_ROOT):
        raise RuntimeError(
            "Lifecycle worker SCRAPER_STAGING_ROOT is not the expected Docker named-volume mount: "
            f"{SCRAPER_STAGING_ROOT}. Recreate containers and verify the shared scraper_staging_data volume."
        )
    spool_id = await asyncio.to_thread(_read_or_create_spool_id)
    reference_status = await _staging_reference_status()
    if int(reference_status.get("reference_missing") or 0) > 0:
        examples = ", ".join(reference_status.get("reference_missing_examples") or [])
        raise RuntimeError(
            "Lifecycle worker found PostgreSQL staging references missing from the canonical scraper PVC. "
            f"Re-stage/re-upload them before continuing. missing_examples=[{examples}]"
        )
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await db.execute(text(
                "SELECT pg_advisory_xact_lock(hashtext('mreader:scraper-staging-spool-registry'))"
            ))
            row = (await db.execute(text(
                "SELECT spool_id::text FROM scraper_staging_spool_registry WHERE id=1 FOR UPDATE"
            ))).mappings().first()
            if row is None:
                await db.execute(text(
                    "INSERT INTO scraper_staging_spool_registry(id,spool_id,logical_root,last_service,last_seen_at) "
                    "VALUES (1,CAST(:spool AS uuid),:root,'lifecycle-worker',NOW())"
                ), {"spool": spool_id, "root": str(SCRAPER_STAGING_ROOT)})
            elif str(row["spool_id"]) != spool_id:
                raise RuntimeError(
                    "Lifecycle worker sees a different scraper staging PVC/spool. "
                    "Current MReader does not auto-adopt or reconstruct staged files; restore the registered PVC "
                    f"or explicitly clear/re-stage test drafts. expected={row['spool_id']} actual={spool_id}"
                )
            else:
                await db.execute(text(
                    "UPDATE scraper_staging_spool_registry SET logical_root=:root,last_service='lifecycle-worker',last_seen_at=NOW() WHERE id=1"
                ), {"root": str(SCRAPER_STAGING_ROOT)})
    return spool_id


def _safe_paths(payload: dict[str, Any], key: str) -> list[str]:
    out: list[str] = []
    for value in payload.get(key) or []:
        value = str(value).strip().lstrip("/")
        if value and ".." not in value:
            out.append(value)
    return sorted(set(out))


def _safe_local_staging_prefixes(payload: dict[str, Any]) -> list[Path]:
    """Resolve explicit scraper-PVC cleanup prefixes against the local spool."""
    out: list[Path] = []
    for value in payload.get("local_staging_prefixes") or []:
        normalized = str(value).replace("\\", "/").strip().lstrip("/")
        if not normalized.startswith("_scraper/") or ".." in normalized.split("/"):
            continue
        target = (SCRAPER_STAGING_ROOT / normalized).resolve()
        try:
            target.relative_to(SCRAPER_STAGING_ROOT)
        except ValueError:
            continue
        out.append(target)
    return sorted(set(out), key=lambda value: len(value.parts), reverse=True)


async def _purge_local_staging(payload: dict[str, Any]) -> None:
    import shutil

    for target in _safe_local_staging_prefixes(payload):
        def remove() -> None:
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        await asyncio.to_thread(remove)


def _nginx_cache_file(image_path: str) -> Path:
    # image-edge proxy_cache_key is "$request_method:$uri" and the external URI
    # is /images/<logical path>. nginx levels=1:2 uses the tail of the MD5.
    key = f"GET:/images/{image_path.lstrip('/')}"
    digest = hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return CACHE_ROOT / digest[-1] / digest[-3:-1] / digest


async def _purge_local_cache(image_paths: list[str]) -> None:
    if CACHE_MODE != "filesystem":
        return
    for image_path in image_paths:
        try:
            _nginx_cache_file(image_path).unlink(missing_ok=True)
        except OSError:
            log.warning("local image cache purge failed path=%s", image_path, exc_info=True)


async def _redis_cleanup(payload: dict[str, Any], image_paths: list[str]) -> None:
    state_redis = await get_redis()
    cache_redis = await _get_cache_redis()
    series_id = str(payload.get("series_id") or "").strip()
    chapter_ids = {str(v).strip() for v in (payload.get("chapter_ids") or []) if str(v).strip()}

    # Derived response caches and Reader chapter grants are owned by redis-cache.
    for pattern in ("cache:series:*", "cache:catalog:*", "cache:chapter:*", "cache:reader:*"):
        async for key in cache_redis.scan_iter(match=pattern, count=200):
            await cache_redis.delete(key)

    # Progress/session-adjacent state remains on the critical Redis instance.
    if series_id:
        async for key in state_redis.scan_iter(match=f"progress:*:{series_id}", count=200):
            await state_redis.delete(key)

    image_set = set(image_paths)
    async for key in cache_redis.scan_iter(match="imgtoken:*", count=200):
        raw = await cache_redis.get(key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stored_paths = {str(v) for v in (data.get("paths") or [])}
        chapter_id = str(data.get("chapter_id") or "")
        if bool(stored_paths & image_set) or chapter_id in chapter_ids:
            await cache_redis.delete(key)


def _external_urls(payload: dict[str, Any], image_paths: list[str]) -> list[str]:
    base = str(os.getenv("IMAGE_CDN_URL", "")).strip().rstrip("/")
    if not base:
        return []
    return [f"{base}/images/{p.lstrip('/')}" for p in image_paths]


async def _purge_external_cdn(payload: dict[str, Any], image_paths: list[str]) -> None:
    urls = _external_urls(payload, image_paths)
    if not urls:
        return
    async with httpx.AsyncClient(timeout=20) as client:
        cf_zone = os.getenv("CLOUDFLARE_ZONE_ID", "").strip()
        cf_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        if cf_zone and cf_token:
            for start in range(0, len(urls), 30):
                response = await client.post(
                    f"https://api.cloudflare.com/client/v4/zones/{cf_zone}/purge_cache",
                    headers={"Authorization": f"Bearer {cf_token}"},
                    json={"files": urls[start:start + 30]},
                )
                response.raise_for_status()

        # Gcore exposes POST /cdn/purge. Keep this optional because account/API
        # permission differs by CDN resource; failures are retried durably.
        gcore_token = os.getenv("GCORE_API_TOKEN", "").strip()
        gcore_resource = os.getenv("GCORE_CDN_RESOURCE_ID", "").strip()
        if gcore_token and gcore_resource:
            paths = ["/images/" + p.lstrip("/") for p in image_paths]
            for start in range(0, len(paths), 50):
                response = await client.post(
                    "https://api.gcore.com/cdn/purge",
                    headers={"Authorization": f"Bearer {gcore_token}"},
                    json={"resource_id": int(gcore_resource), "paths": paths[start:start + 50]},
                )
                response.raise_for_status()


class UnsafeLegacyCleanupPayload(RuntimeError):
    """Permanent quarantine for historical broad-prefix production deletion."""


def _safe_object_refs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized exact refs; legacy exact image_paths remain supported.

    Schema-v2 producers must provide object_refs. Historical jobs that only
    contain image_paths are still exact-path work, so they can be handled
    conservatively with generation 0. Broad storage_prefixes are rejected in
    _cleanup_job and never become object refs.
    """
    refs: list[dict[str, Any]] = []
    for raw in payload.get("object_refs") or []:
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path") or "").replace("\\", "/").strip().lstrip("/")
        kind = str(raw.get("kind") or "").strip()
        try:
            generation = int(raw.get("generation") or 0)
        except (TypeError, ValueError):
            continue
        if not path or ".." in path.split("/") or not kind or generation < 0:
            continue
        ref = {"path": path, "generation": generation, "kind": kind}
        if ref not in refs:
            refs.append(ref)

    if refs or int(payload.get("schema_version") or 0) >= 2:
        return refs

    return [
        {"path": path, "generation": 0, "kind": "legacy-exact-path"}
        for path in _safe_paths(payload, "image_paths")
    ]


async def _filter_unowned_object_refs(
    object_refs: list[dict[str, Any]],
    *,
    media_operation_id: str | None = None,
) -> list[dict[str, Any]]:
    """Re-check live Catalog path+generation ownership before physical delete.

    A path is protected whenever Catalog currently references it, regardless of
    generation. The current generation is still read and logged so delayed v2
    work can be distinguished from the replacement generation that owns the
    same deterministic path. Media-originated orphan cleanup is additionally
    fenced by the operation's current media_generation.
    """
    if not object_refs:
        return []
    paths = sorted({str(ref["path"]) for ref in object_refs})

    async with AsyncSessionLocal() as db:
        owner_rows = (await db.execute(
            text(
                """
                SELECT image_path AS path, media_generation AS generation,
                       'page-primary'::text AS kind
                FROM pages WHERE image_path = ANY(:paths)
                UNION ALL
                SELECT responsive_image_path AS path, media_generation AS generation,
                       'page-responsive'::text AS kind
                FROM pages WHERE responsive_image_path = ANY(:paths)
                UNION ALL
                SELECT cover_image_path AS path, cover_media_generation AS generation,
                       'cover'::text AS kind
                FROM series
                WHERE cover_image_path IS NOT NULL AND cover_image_path = ANY(:paths)
                """
            ),
            {"paths": paths},
        )).mappings().all()

        current_media_generation: int | None = None
        if media_operation_id:
            row = (await db.execute(
                text(
                    """
                    SELECT media_generation
                    FROM media_operations
                    WHERE operation_id=CAST(:operation_id AS uuid)
                    """
                ),
                {"operation_id": media_operation_id},
            )).mappings().first()
            if row is not None:
                current_media_generation = int(row["media_generation"] or 0)

    catalog_owners: dict[str, list[tuple[int, str]]] = {}
    for row in owner_rows:
        path = str(row.get("path") or "")
        if not path:
            continue
        catalog_owners.setdefault(path, []).append(
            (int(row.get("generation") or 0), str(row.get("kind") or ""))
        )

    allowed: list[dict[str, Any]] = []
    for ref in object_refs:
        path = str(ref["path"])
        generation = int(ref.get("generation") or 0)
        owners = catalog_owners.get(path) or []
        if owners:
            log.info(
                "cleanup protected live Catalog object path=%s retired_generation=%s owners=%s",
                path,
                generation,
                owners,
            )
            continue
        if media_operation_id and generation > 0:
            if current_media_generation is None:
                log.warning(
                    "cleanup protected object because Media generation cannot be rechecked operation=%s path=%s generation=%s",
                    media_operation_id,
                    path,
                    generation,
                )
                continue
            if current_media_generation != generation:
                log.info(
                    "cleanup protected replacement Media generation operation=%s path=%s retired_generation=%s current_generation=%s",
                    media_operation_id,
                    path,
                    generation,
                    current_media_generation,
                )
                continue
        allowed.append(ref)
    return allowed


async def _cleanup_job(payload: dict[str, Any]) -> None:
    storage_prefixes = _safe_paths(payload, "storage_prefixes")
    if storage_prefixes:
        raise UnsafeLegacyCleanupPayload(
            "legacy broad storage_prefixes cleanup is quarantined; exact object_refs are required: "
            + ", ".join(storage_prefixes[:5])
        )

    object_refs = _safe_object_refs(payload)
    requested_image_paths = sorted(
        set(_safe_paths(payload, "image_paths"))
        | {str(ref["path"]) for ref in object_refs}
    )
    media_operation_id = str(payload.get("media_operation_id") or "").strip() or None
    unowned_refs = await _filter_unowned_object_refs(
        object_refs,
        media_operation_id=media_operation_id,
    )
    image_paths = sorted({str(ref["path"]) for ref in unowned_refs})
    skipped = sorted(set(requested_image_paths) - set(image_paths))
    if skipped:
        log.info("cleanup skipped currently-owned/replacement image paths=%s", skipped)

    # Local scraper staging is private disposable state and is never interpreted
    # as a production storage prefix. Re-running local purge is idempotent.
    await _purge_local_staging(payload)

    sw = get_seaweedfs()
    # Lifecycle is the sole physical deleter for production objects. Only exact
    # refs that survived the live ownership/generation fence reach SeaweedFS.
    for path in image_paths:
        await sw.delete_via_filer(path)

    # Token revocation must consider every originally-retired entity path, even
    # if a path was reused and therefore protected from physical deletion.
    await _redis_cleanup(payload, requested_image_paths)
    await _purge_local_cache(image_paths)
    await _purge_external_cdn(payload, image_paths)


async def _recover_stale_processing() -> int:
    """Return abandoned cleanup leases to the retry queue after worker loss."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            UPDATE lifecycle_cleanup_jobs
            SET status='retry', next_attempt_at=NOW(), locked_at=NULL, locked_by=NULL,
                updated_at=NOW(),
                last_error=COALESCE(last_error || ' | ', '') || 'Recovered stale processing lease'
            WHERE status='processing'
              AND (locked_at IS NULL OR locked_at < NOW() - (:seconds * INTERVAL '1 second'))
        """), {"seconds": STALE_PROCESSING_SECONDS})
        await db.commit()
        return int(result.rowcount or 0)


async def _heartbeat(job_id: str) -> None:
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            async with AsyncSessionLocal() as db:
                await db.execute(text("""
                    UPDATE lifecycle_cleanup_jobs
                    SET locked_at=NOW(), updated_at=NOW()
                    WHERE id=CAST(:id AS uuid)
                      AND status='processing' AND locked_by=:worker
                """), {"id": job_id, "worker": WORKER_ID})
                await db.commit()
    except asyncio.CancelledError:
        raise


async def _claim_job() -> dict[str, Any] | None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            row = (await db.execute(text("""
                SELECT id::text, entity_type, entity_id::text, payload, attempts, max_attempts
                FROM lifecycle_cleanup_jobs
                WHERE status IN ('queued','retry') AND next_attempt_at <= NOW()
                ORDER BY next_attempt_at, created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            """))).mappings().first()
            if row is None:
                return None
            await db.execute(text("""
                UPDATE lifecycle_cleanup_jobs
                SET status='processing', attempts=attempts+1, locked_at=NOW(), locked_by=:worker,
                    updated_at=NOW(), last_error=NULL
                WHERE id=CAST(:id AS uuid)
            """), {"worker": WORKER_ID, "id": row["id"]})
            return dict(row)


async def _finish(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            UPDATE lifecycle_cleanup_jobs
            SET status='completed', completed_at=NOW(), updated_at=NOW(), locked_at=NULL, locked_by=NULL
            WHERE id=CAST(:id AS uuid)
        """), {"id": job_id})
        await db.commit()


async def _fail(job: dict[str, Any], error: Exception) -> None:
    # attempts in the claimed row is the pre-increment count.
    attempt = int(job.get("attempts") or 0) + 1
    maximum = int(job.get("max_attempts") or 20)
    # Broad-prefix cleanup is a permanently unsafe historical payload shape,
    # not transient infrastructure work. Quarantine it immediately instead of
    # retrying a request that must never execute against production storage.
    terminal = isinstance(error, UnsafeLegacyCleanupPayload) or attempt >= maximum
    delay = min(3600, 2 ** min(attempt, 10))
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            UPDATE lifecycle_cleanup_jobs
            SET status=:status,
                next_attempt_at=CASE WHEN :terminal THEN next_attempt_at ELSE NOW() + (:delay * INTERVAL '1 second') END,
                last_error=:error, updated_at=NOW(), locked_at=NULL, locked_by=NULL
            WHERE id=CAST(:id AS uuid)
        """), {
            "status": "failed" if terminal else "retry",
            "terminal": terminal,
            "delay": delay,
            "error": str(error)[:4000],
            "id": job["id"],
        })
        await db.commit()


async def _prune_completed_jobs() -> int:
    """Bound lifecycle-table growth while retaining every unresolved failure."""
    async with AsyncSessionLocal() as db:
        # Collapse any scraper recovery ledger that still points at an old
        # completed cleanup before the FK is cleared by job pruning. This makes
        # pruning correct even when all scraper workers were offline for weeks.
        await db.execute(text("""
            UPDATE scraper_storage_attempts a
            SET status='cleanup_complete', object_paths='[]'::jsonb,
                updated_at=NOW(), finished_at=COALESCE(a.finished_at,NOW())
            FROM lifecycle_cleanup_jobs j
            WHERE a.cleanup_job_id=j.id
              AND a.status='cleanup_queued'
              AND j.status='completed'
              AND j.completed_at < NOW() - (:days * INTERVAL '1 day')
        """), {"days": COMPLETED_RETENTION_DAYS})
        result = await db.execute(text("""
            DELETE FROM lifecycle_cleanup_jobs
            WHERE status='completed'
              AND completed_at < NOW() - (:days * INTERVAL '1 day')
        """), {"days": COMPLETED_RETENTION_DAYS})
        await db.commit()
        return int(result.rowcount or 0)


async def run() -> None:
    init_redis_pool()
    _init_cache_redis()
    init_seaweedfs_client()
    spool_id = await _ensure_scraper_staging_spool()
    log.info("validated shared scraper staging spool id=%s root=%s", spool_id, SCRAPER_STAGING_ROOT)
    recovered = await _recover_stale_processing()
    log.info("lifecycle worker started id=%s recovered_stale=%s", WORKER_ID, recovered)
    last_recovery = time.monotonic()
    last_prune = time.monotonic()
    try:
        infrastructure_failures = 0
        while True:
            try:
                now = time.monotonic()
                if now - last_recovery >= RECOVERY_INTERVAL_SECONDS:
                    recovered = await _recover_stale_processing()
                    if recovered:
                        log.warning("recovered %s stale lifecycle cleanup jobs", recovered)
                    last_recovery = now

                if now - last_prune >= PRUNE_INTERVAL_SECONDS:
                    try:
                        removed = await _prune_completed_jobs()
                        if removed:
                            log.info("pruned completed lifecycle jobs count=%s", removed)
                    except Exception:
                        log.warning("completed lifecycle job prune failed", exc_info=True)
                    last_prune = now

                job = await _claim_job()
                if job is None:
                    infrastructure_failures = 0
                    await asyncio.sleep(POLL_SECONDS)
                    continue

                heartbeat = asyncio.create_task(_heartbeat(job["id"]))
                try:
                    await _cleanup_job(dict(job.get("payload") or {}))
                    await _finish(job["id"])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.exception("lifecycle cleanup failed job=%s", job["id"])
                    try:
                        await _fail(job, exc)
                    except Exception:
                        # If PostgreSQL is unavailable while recording the retry,
                        # do not crash the worker or attempt direct cleanup. The
                        # processing lease remains durable and stale-lease recovery
                        # will return it to retry once the DB is reachable again.
                        log.exception(
                            "failed to persist lifecycle retry state job=%s; preserving lease for stale recovery",
                            job["id"],
                        )
                finally:
                    heartbeat.cancel()
                    try:
                        await heartbeat
                    except asyncio.CancelledError:
                        pass
                infrastructure_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                # A temporary DB/network outage should not turn the cleanup
                # worker into a restart loop. Back off in-process and resume
                # polling; durable leases/jobs remain canonical in PostgreSQL.
                infrastructure_failures += 1
                delay = min(30.0, float(2 ** min(infrastructure_failures, 5)))
                log.exception(
                    "lifecycle worker infrastructure failure; retrying loop in %.1fs", delay
                )
                await asyncio.sleep(delay)
    finally:
        await _close_cache_redis()
        await close_redis_pool()
        await close_seaweedfs_client()


if __name__ == "__main__":
    asyncio.run(run())
