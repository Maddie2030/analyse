import asyncio
import logging

import asyncpg
import httpx

from app.batch_queue import QUEUE_KEY, process_item, recover_batch_jobs
from app.config import settings
from app.db import configure_connection
from app.rabbitmq import RabbitQueueBroker
from app.staging_store import cleanup_incomplete_staging_files, ensure_staging_spool
from app.storage_attempts import recover_stale_storage_attempts


logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)

# libvips emits very verbose per-operation diagnostics at INFO. Keep
# warnings/errors visible, but do not let image internals drown workflow logs.
logging.getLogger("pyvips").setLevel(logging.WARNING)
logging.getLogger("pyvips.voperation").setLevel(logging.WARNING)
log = logging.getLogger("scraper.batch-worker")


async def _recovery_loop(pool: asyncpg.Pool, queue: RabbitQueueBroker) -> None:
    while True:
        try:
            await asyncio.sleep(60)
            storage = await recover_stale_storage_attempts(pool)
            recovered = await recover_batch_jobs(pool, queue)
            if any(storage.values()) or recovered["enqueued_missing"] or recovered["reset_processing"]:
                log.info("recovered durable batch jobs storage=%s batch=%s", storage, recovered)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("durable batch recovery failed")


async def main() -> None:
    pool = await asyncpg.create_pool(
        settings.batch_database_url,
        init=configure_connection,
        min_size=1,
        max_size=max(2, settings.scraper_batch_db_max_connections),
        command_timeout=30,
    )
    staging = await ensure_staging_spool(pool, service_name="scraper-batch-worker")
    log.info("validated shared staging spool status=%s", staging)
    queue = RabbitQueueBroker()
    await queue.connect()
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(60.0),
        limits=httpx.Limits(
            max_connections=max(8, settings.scraper_batch_http_max_connections),
            max_keepalive_connections=max(4, settings.scraper_batch_http_keepalive_connections),
        ),
    )

    removed_parts = await cleanup_incomplete_staging_files()
    storage_recovered = await recover_stale_storage_attempts(pool)
    recovered = await recover_batch_jobs(pool, queue, reset_processing=True)
    log.info(
        "batch worker started broker=rabbitmq storage_recovered=%s recovered=%s stale_parts_removed=%s",
        storage_recovered, recovered, removed_parts,
    )

    async def handle(payload: dict, _attempt: int) -> None:
        item_id = str(payload.get("job_id") or "")
        if not item_id:
            raise ValueError("RabbitMQ batch message is missing job_id")
        await process_item(pool, client, item_id)

    recovery_task = asyncio.create_task(_recovery_loop(pool, queue), name="scraper-batch-recovery")
    try:
        await queue.consume_forever(QUEUE_KEY, handle, worker_name="batch-worker")
    finally:
        recovery_task.cancel()
        await asyncio.gather(recovery_task, return_exceptions=True)
        await client.aclose()
        await queue.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
