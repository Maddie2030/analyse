import asyncio
import logging
import os

import asyncpg
import httpx
from redis.asyncio import Redis

from app.config import settings
from app.db import configure_connection
from app.rabbitmq import RabbitQueueBroker
from app.operation_events import record_operation_event
from app.staging_store import cleanup_incomplete_staging_files, ensure_staging_spool
from app.storage_attempts import expire_abandoned_staging, recover_stale_storage_attempts
from app.series_drafts import (
    CHAPTER_PUBLISH_QUEUE,
    DISCOVERY_QUEUE,
    PUBLISH_QUEUE,
    STAGE_QUEUE,
    publish_one_chapter,
    publish_one_series,
    finalize_pending_cancelled_operations,
    recover_incomplete_discovery_jobs,
    recover_incomplete_publish_jobs,
    recover_incomplete_chapter_publish_jobs,
    recover_incomplete_stage_jobs,
    run_series_discovery,
    stage_one_chapter,
)


logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)

# libvips emits very verbose per-operation diagnostics at INFO. Keep
# warnings/errors visible, but do not let image internals drown workflow logs.
logging.getLogger("pyvips").setLevel(logging.WARNING)
logging.getLogger("pyvips.voperation").setLevel(logging.WARNING)
log = logging.getLogger("scraper.series-worker")


def _worker_concurrency() -> int:
    try:
        value = int(os.getenv("SCRAPER_SERIES_WORKER_CONCURRENCY", "4"))
    except ValueError:
        value = 4
    return max(1, min(16, value))


async def _recover(pool: asyncpg.Pool, queue: RabbitQueueBroker, client: httpx.AsyncClient) -> dict[str, int]:
    # Resolve cross-storage transaction ambiguity before requeueing stale work.
    # Recovery queries deliberately refuse to steal jobs with a live attempt.
    storage = await recover_stale_storage_attempts(pool)
    cancelled = await finalize_pending_cancelled_operations(pool, queue, client)
    discovery, staging, publish, chapter_publish = await asyncio.gather(
        recover_incomplete_discovery_jobs(pool, queue),
        recover_incomplete_stage_jobs(pool, queue),
        recover_incomplete_publish_jobs(pool, queue),
        recover_incomplete_chapter_publish_jobs(pool, queue),
    )
    return {
        "storage_committed": storage.get("committed", 0),
        "storage_cleanup_queued": storage.get("cleanup_queued", 0),
        "storage_cleanup_complete": storage.get("cleanup_complete", 0),
        "cancelled": cancelled,
        "discovery": discovery,
        "staging": staging,
        "publish": publish,
        "chapter_publish": chapter_publish,
    }


async def _recovery_loop(pool: asyncpg.Pool, queue: RabbitQueueBroker, client: httpx.AsyncClient) -> None:
    try:
        interval = max(5, min(300, int(os.getenv("SCRAPER_RECOVERY_INTERVAL_SECONDS", "15"))))
    except ValueError:
        interval = 15
    while True:
        try:
            await asyncio.sleep(interval)
            recovered = await _recover(pool, queue, client)
            if any(recovered.values()):
                log.info("recovered durable scraper jobs counts=%s", recovered)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("durable scraper job recovery failed")


async def _retention_loop(pool: asyncpg.Pool) -> None:
    ttl_hours = int(settings.scraper_staging_ttl_hours)
    if ttl_hours <= 0:
        log.info("automatic staging retention is disabled ttl_hours=0")
        return
    interval = max(60, int(settings.scraper_staging_retention_scan_seconds))
    log.info("automatic staging retention enabled ttl_hours=%s scan_seconds=%s", ttl_hours, interval)
    while True:
        try:
            await asyncio.sleep(interval)
            expired = await expire_abandoned_staging(pool)
            if expired:
                log.info("queued abandoned staging cleanup drafts=%s", expired)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A remote PostgreSQL outage must defer retention, never turn it into
            # direct filesystem deletion. The next scan retries safely.
            log.warning("staging retention scan failed; preserving local staging", exc_info=True)


async def main() -> None:
    concurrency = _worker_concurrency()
    pool = await asyncpg.create_pool(
        settings.series_database_url,
        init=configure_connection,
        min_size=1,
        max_size=max(concurrency + 2, settings.scraper_series_db_max_connections),
        command_timeout=60,
    )
    staging = await ensure_staging_spool(pool, service_name="scraper-series-worker")
    log.info("validated shared staging spool status=%s", staging)
    queue = RabbitQueueBroker()
    await queue.connect()
    cache = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=max(8, settings.scraper_redis_max_connections),
    )
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(60.0),
        limits=httpx.Limits(
            max_connections=max(8, settings.scraper_series_http_max_connections, concurrency * 6),
            max_keepalive_connections=max(4, settings.scraper_series_http_keepalive_connections, concurrency * 3),
        ),
    )

    removed_parts = await cleanup_incomplete_staging_files()
    recovered = await _recover(pool, queue, client)
    log.info(
        "series scraper worker started broker=rabbitmq concurrency=%s recovered=%s stale_parts_removed=%s",
        concurrency, recovered, removed_parts,
    )

    semaphore = asyncio.Semaphore(concurrency)

    async def handle(queue_name: str, payload: dict, attempt: int) -> None:
        value = str(payload.get("job_id") or "")
        if not value:
            raise ValueError("RabbitMQ scraper message is missing job_id")
        operation_id = str(payload.get("operation_id") or (value if queue_name in {PUBLISH_QUEUE, DISCOVERY_QUEUE} else ""))
        chapter_id = str(payload.get("chapter_id") or (value if queue_name in {CHAPTER_PUBLISH_QUEUE, STAGE_QUEUE} else ""))
        request_id = str(payload.get("request_id") or "")
        if operation_id:
            await record_operation_event(
                pool,
                operation_id=operation_id,
                chapter_id=chapter_id or None,
                request_id=request_id or None,
                service="scraper-worker",
                event_type="rabbit_delivery_received",
                phase=queue_name.rsplit('.', 1)[-1],
                status="running",
                message=f"RabbitMQ delivery claimed by {queue_name} worker.",
                metadata={"attempt": attempt, "job_id": value},
            )
        async with semaphore:
            try:
                if queue_name == PUBLISH_QUEUE:
                    await publish_one_series(pool, client, cache, value)
                elif queue_name == CHAPTER_PUBLISH_QUEUE:
                    await publish_one_chapter(pool, client, cache, value)
                elif queue_name == DISCOVERY_QUEUE:
                    await run_series_discovery(pool, client, value)
                elif queue_name == STAGE_QUEUE:
                    await stage_one_chapter(pool, client, value)
                else:
                    raise ValueError(f"Unknown scraper queue: {queue_name}")
            except Exception as exc:
                if operation_id:
                    await record_operation_event(
                        pool,
                        operation_id=operation_id,
                        chapter_id=chapter_id or None,
                        request_id=request_id or None,
                        service="scraper-worker",
                        event_type="rabbit_delivery_failed",
                        phase=queue_name.rsplit('.', 1)[-1],
                        status="failed",
                        message=f"Worker delivery failed: {type(exc).__name__}: {exc}",
                        metadata={"attempt": attempt, "job_id": value},
                    )
                raise
            else:
                if operation_id:
                    await record_operation_event(
                        pool,
                        operation_id=operation_id,
                        chapter_id=chapter_id or None,
                        request_id=request_id or None,
                        service="scraper-worker",
                        event_type="rabbit_delivery_completed",
                        phase=queue_name.rsplit('.', 1)[-1],
                        status="completed",
                        message="Worker handler completed and the RabbitMQ delivery can be acknowledged.",
                        metadata={"attempt": attempt, "job_id": value},
                    )

    tasks: list[asyncio.Task] = []
    # Staging is the high-fan-out workload for a scraped series. Run the
    # configured number of independent RabbitMQ consumers so
    # SCRAPER_SERIES_WORKER_CONCURRENCY actually controls chapter parallelism.
    # Different series are intentionally allowed to stage/publish concurrently.
    # Correctness is enforced by PostgreSQL per-series advisory locks and durable
    # row claims, not by globally serializing the RabbitMQ consumers. The shared
    # semaphore remains the per-pod resource ceiling.
    consumer_counts = {
        PUBLISH_QUEUE: min(2, concurrency),
        CHAPTER_PUBLISH_QUEUE: min(2, concurrency),
        DISCOVERY_QUEUE: 1,
        STAGE_QUEUE: concurrency,
    }
    for queue_name, consumer_count in consumer_counts.items():
        for index in range(consumer_count):
            worker_name = f"series-{queue_name.rsplit('.', 1)[-1]}-{index + 1}"
            tasks.append(asyncio.create_task(
                queue.consume_forever(
                    queue_name,
                    lambda payload, attempt, q=queue_name: handle(q, payload, attempt),
                    worker_name=worker_name,
                ),
                name=f"scraper-consumer-{queue_name}-{index + 1}",
            ))
    tasks.append(asyncio.create_task(_recovery_loop(pool, queue, client), name="scraper-series-recovery"))
    if int(settings.scraper_staging_ttl_hours) > 0:
        tasks.append(asyncio.create_task(_retention_loop(pool), name="scraper-staging-retention"))

    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.aclose()
        await cache.aclose()
        await queue.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
