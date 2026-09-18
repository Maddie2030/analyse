from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

from app.config import settings

log = logging.getLogger("scraper.rabbitmq")

JobHandler = Callable[[dict[str, Any], int], Awaitable[None]]


class RabbitQueueBroker:
    """Durable RabbitMQ job broker for scraper operations.

    PostgreSQL remains the canonical operation state. RabbitMQ only dispatches
    compact job references, so redelivery or stale/cancelled messages are safe:
    every worker atomically re-checks/claims the durable row before doing work.
    """

    def __init__(self) -> None:
        self._connection: aio_pika.RobustConnection | None = None
        self._publish_channel: aio_pika.abc.AbstractRobustChannel | None = None
        self._jobs_exchange: aio_pika.abc.AbstractRobustExchange | None = None
        self._retry_exchange: aio_pika.abc.AbstractRobustExchange | None = None
        self._dlx_exchange: aio_pika.abc.AbstractRobustExchange | None = None
        self._declared: set[str] = set()
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._connection and not self._connection.is_closed:
            return
        async with self._lock:
            if self._connection and not self._connection.is_closed:
                return
            self._connection = await aio_pika.connect_robust(
                settings.rabbitmq_url,
                timeout=settings.rabbitmq_connect_timeout_seconds,
                client_properties={"connection_name": settings.rabbitmq_connection_name},
            )
            self._publish_channel = await self._connection.channel(publisher_confirms=True)
            self._jobs_exchange = await self._publish_channel.declare_exchange(
                settings.rabbitmq_jobs_exchange,
                ExchangeType.DIRECT,
                durable=True,
            )
            self._retry_exchange = await self._publish_channel.declare_exchange(
                f"{settings.rabbitmq_jobs_exchange}.retry",
                ExchangeType.DIRECT,
                durable=True,
            )
            self._dlx_exchange = await self._publish_channel.declare_exchange(
                f"{settings.rabbitmq_jobs_exchange}.dlx",
                ExchangeType.DIRECT,
                durable=True,
            )

    async def _declare_on(self, channel: aio_pika.abc.AbstractChannel, queue_name: str):
        jobs_exchange = await channel.declare_exchange(
            settings.rabbitmq_jobs_exchange,
            ExchangeType.DIRECT,
            durable=True,
        )
        retry_exchange = await channel.declare_exchange(
            f"{settings.rabbitmq_jobs_exchange}.retry",
            ExchangeType.DIRECT,
            durable=True,
        )
        dlx_exchange = await channel.declare_exchange(
            f"{settings.rabbitmq_jobs_exchange}.dlx",
            ExchangeType.DIRECT,
            durable=True,
        )

        main = await channel.declare_queue(
            queue_name,
            durable=True,
            arguments={"x-queue-type": "quorum"},
        )
        await main.bind(jobs_exchange, routing_key=queue_name)

        retry = await channel.declare_queue(
            f"{queue_name}.retry",
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-message-ttl": settings.rabbitmq_retry_delay_ms,
                "x-dead-letter-exchange": settings.rabbitmq_jobs_exchange,
                "x-dead-letter-routing-key": queue_name,
            },
        )
        await retry.bind(retry_exchange, routing_key=queue_name)

        dlq = await channel.declare_queue(
            f"{queue_name}.dlq",
            durable=True,
            arguments={"x-queue-type": "quorum"},
        )
        await dlq.bind(dlx_exchange, routing_key=queue_name)
        return main

    async def declare(self, queue_name: str) -> None:
        await self.connect()
        if queue_name in self._declared:
            return
        assert self._publish_channel is not None
        await self._declare_on(self._publish_channel, queue_name)
        self._declared.add(queue_name)

    async def publish(
        self,
        queue_name: str,
        job_id: str,
        *,
        payload: dict[str, Any] | None = None,
        attempt: int = 1,
        retry: bool = False,
        dead_letter: bool = False,
    ) -> None:
        await self.declare(queue_name)
        assert self._jobs_exchange is not None
        assert self._retry_exchange is not None
        assert self._dlx_exchange is not None

        body = json.dumps({"job_id": job_id, **(payload or {})}, separators=(",", ":")).encode("utf-8")
        message = Message(
            body=body,
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type="application/json",
            message_id=job_id,
            headers={"x-mreader-attempt": int(attempt)},
        )
        exchange = self._dlx_exchange if dead_letter else self._retry_exchange if retry else self._jobs_exchange
        await exchange.publish(message, routing_key=queue_name, mandatory=True)
        log.info(
            "rabbit publish queue=%s job_id=%s operation_id=%s chapter_id=%s request_id=%s attempt=%s retry=%s dead_letter=%s",
            queue_name,
            job_id,
            (payload or {}).get("operation_id") or job_id,
            (payload or {}).get("chapter_id") or "",
            (payload or {}).get("request_id") or "",
            attempt,
            retry,
            dead_letter,
        )

    async def consume_forever(
        self,
        queue_name: str,
        handler: JobHandler,
        *,
        worker_name: str,
    ) -> None:
        await self.connect()
        assert self._connection is not None
        channel = await self._connection.channel()
        await channel.set_qos(prefetch_count=1)
        queue = await self._declare_on(channel, queue_name)
        log.info("rabbit consumer started worker=%s queue=%s", worker_name, queue_name)

        try:
            async with queue.iterator() as iterator:
                async for message in iterator:
                    try:
                        payload = json.loads(message.body.decode("utf-8"))
                        attempt = int((message.headers or {}).get("x-mreader-attempt") or 1)
                        log.info(
                            "rabbit receive worker=%s queue=%s job_id=%s operation_id=%s chapter_id=%s request_id=%s attempt=%s",
                            worker_name,
                            queue_name,
                            payload.get("job_id") or message.message_id or "",
                            payload.get("operation_id") or payload.get("job_id") or "",
                            payload.get("chapter_id") or "",
                            payload.get("request_id") or "",
                            attempt,
                        )
                        await handler(payload, attempt)
                    except asyncio.CancelledError:
                        await message.nack(requeue=True)
                        raise
                    except Exception as exc:
                        attempt = int((message.headers or {}).get("x-mreader-attempt") or 1)
                        try:
                            payload = json.loads(message.body.decode("utf-8"))
                            job_id = str(payload.get("job_id") or message.message_id or "unknown")
                            if attempt < settings.rabbitmq_max_attempts:
                                await self.publish(
                                    queue_name,
                                    job_id,
                                    payload={k: v for k, v in payload.items() if k != "job_id"},
                                    attempt=attempt + 1,
                                    retry=True,
                                )
                                log.warning(
                                    "rabbit job retry queued worker=%s queue=%s job_id=%s attempt=%s/%s error=%s",
                                    worker_name,
                                    queue_name,
                                    job_id,
                                    attempt,
                                    settings.rabbitmq_max_attempts,
                                    type(exc).__name__,
                                )
                            else:
                                await self.publish(
                                    queue_name,
                                    job_id,
                                    payload={
                                        **{k: v for k, v in payload.items() if k != "job_id"},
                                        "last_error": f"{type(exc).__name__}: {exc}"[:1000],
                                    },
                                    attempt=attempt,
                                    dead_letter=True,
                                )
                                log.error(
                                    "rabbit job moved to dlq worker=%s queue=%s job_id=%s attempts=%s",
                                    worker_name,
                                    queue_name,
                                    job_id,
                                    attempt,
                                )
                            await message.ack()
                        except Exception:
                            log.exception("failed to route failed RabbitMQ job; requeueing original")
                            await message.nack(requeue=True)
                    else:
                        await message.ack()
        finally:
            await channel.close()

    async def depth(self, queue_name: str) -> int:
        await self.connect()
        assert self._publish_channel is not None
        queue = await self._declare_on(self._publish_channel, queue_name)
        result = queue.declaration_result
        return int(result.message_count or 0) if result is not None else 0

    async def position(self, _queue_name: str, _job_id: str) -> None:
        # RabbitMQ intentionally does not expose a cheap arbitrary-message
        # position primitive. The dashboard reports queue depth and durable DB
        # state instead of scanning broker contents.
        return None

    async def remove_pending(self, _queue_name: str, _job_id: str) -> int:
        # Cancellation is durable in PostgreSQL. RabbitMQ messages are compact
        # references; a stale cancelled reference is ACKed after the DB claim
        # check returns no work. Avoiding queue scans keeps cancellation O(1).
        return 0

    async def ping(self) -> bool:
        await self.connect()
        assert self._publish_channel is not None
        await self._publish_channel.declare_exchange(
            settings.rabbitmq_jobs_exchange,
            ExchangeType.DIRECT,
            durable=True,
        )
        return True

    async def close(self) -> None:
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._publish_channel = None
        self._jobs_exchange = None
        self._retry_exchange = None
        self._dlx_exchange = None
        self._declared.clear()
