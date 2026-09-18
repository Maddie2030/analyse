from __future__ import annotations

"""RabbitMQ job-dispatch helpers for scraper workers.

PostgreSQL is the durable source of truth. RabbitMQ carries only job references
and uses publisher confirms + durable quorum queues. DB-side atomic claims make
redelivery safe and cancellation remains DB-authoritative.
"""


async def enqueue_unique(
    broker,
    queue: str,
    item_id: str,
    *,
    payload: dict | None = None,
) -> bool:
    # RabbitMQ has no built-in arbitrary-message dedupe. Repeated endpoint or
    # recovery publishes are safe because every worker first atomically claims
    # the PostgreSQL row. Recovery itself is stale-time bounded.
    await broker.publish(queue, item_id, payload=payload)
    return True


async def remove_pending(broker, queue: str, item_id: str) -> int:
    return int(await broker.remove_pending(queue, item_id))


async def queue_depth(broker, queue: str) -> int:
    return int(await broker.depth(queue))


async def queue_position(broker, queue: str, item_id: str):
    return await broker.position(queue, item_id)
