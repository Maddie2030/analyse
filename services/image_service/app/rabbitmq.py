from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

from shared import settings

log = logging.getLogger("media.rabbitmq")

THUMBNAIL_QUEUE = "mreader.media.thumbnail"
CHAPTER_QUEUE = "mreader.media.chapter"

JobHandler = Callable[[dict[str, Any], int], Awaitable[None]]


class JobDeferred(RuntimeError):
    """Retry later without consuming the bounded failure-attempt budget."""


class RabbitJobBroker:
    def __init__(self, connection_name: str = "mreader-media") -> None:
        self.connection_name = connection_name
        self.connection: aio_pika.RobustConnection | None = None
        self.channel: aio_pika.abc.AbstractRobustChannel | None = None
        self.jobs: aio_pika.abc.AbstractRobustExchange | None = None
        self.retry: aio_pika.abc.AbstractRobustExchange | None = None
        self.dlx: aio_pika.abc.AbstractRobustExchange | None = None
        self._lock = asyncio.Lock()
        self._declared: set[str] = set()

    async def connect(self) -> None:
        if self.connection and not self.connection.is_closed:
            return
        async with self._lock:
            if self.connection and not self.connection.is_closed:
                return
            self.connection = await aio_pika.connect_robust(
                str(settings.RABBITMQ_URL),
                timeout=float(settings.RABBITMQ_CONNECT_TIMEOUT_SECONDS),
                client_properties={"connection_name": self.connection_name},
            )
            self.channel = await self.connection.channel(publisher_confirms=True)
            self.jobs = await self.channel.declare_exchange(settings.RABBITMQ_JOBS_EXCHANGE, ExchangeType.DIRECT, durable=True)
            self.retry = await self.channel.declare_exchange(f"{settings.RABBITMQ_JOBS_EXCHANGE}.retry", ExchangeType.DIRECT, durable=True)
            self.dlx = await self.channel.declare_exchange(f"{settings.RABBITMQ_JOBS_EXCHANGE}.dlx", ExchangeType.DIRECT, durable=True)

    async def _declare_on(self, channel, queue_name: str):
        jobs = await channel.declare_exchange(settings.RABBITMQ_JOBS_EXCHANGE, ExchangeType.DIRECT, durable=True)
        retry = await channel.declare_exchange(f"{settings.RABBITMQ_JOBS_EXCHANGE}.retry", ExchangeType.DIRECT, durable=True)
        dlx = await channel.declare_exchange(f"{settings.RABBITMQ_JOBS_EXCHANGE}.dlx", ExchangeType.DIRECT, durable=True)
        main = await channel.declare_queue(queue_name, durable=True, arguments={"x-queue-type": "quorum"})
        await main.bind(jobs, queue_name)
        delayed = await channel.declare_queue(
            f"{queue_name}.retry",
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-message-ttl": int(settings.RABBITMQ_RETRY_DELAY_MS),
                "x-dead-letter-exchange": settings.RABBITMQ_JOBS_EXCHANGE,
                "x-dead-letter-routing-key": queue_name,
            },
        )
        await delayed.bind(retry, queue_name)
        dead = await channel.declare_queue(f"{queue_name}.dlq", durable=True, arguments={"x-queue-type": "quorum"})
        await dead.bind(dlx, queue_name)
        return main

    async def declare(self, queue_name: str) -> None:
        await self.connect()
        if queue_name in self._declared:
            return
        assert self.channel is not None
        await self._declare_on(self.channel, queue_name)
        self._declared.add(queue_name)

    async def publish(self, queue_name: str, job_id: str, payload: dict[str, Any], *, attempt: int = 1, retry: bool = False, dead: bool = False) -> None:
        await self.declare(queue_name)
        assert self.jobs and self.retry and self.dlx
        body = json.dumps({"job_id": job_id, **payload}, separators=(",", ":")).encode()
        message = Message(
            body=body,
            message_id=job_id,
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            headers={"x-mreader-attempt": int(attempt)},
        )
        exchange = self.dlx if dead else self.retry if retry else self.jobs
        await exchange.publish(message, queue_name, mandatory=True)

    async def consume_forever(self, queue_name: str, handler: JobHandler, *, worker_name: str) -> None:
        await self.connect()
        assert self.connection is not None
        channel = await self.connection.channel()
        await channel.set_qos(prefetch_count=1)
        queue = await self._declare_on(channel, queue_name)
        log.info("media RabbitMQ consumer started worker=%s queue=%s", worker_name, queue_name)
        try:
            async with queue.iterator() as iterator:
                async for message in iterator:
                    attempt = int((message.headers or {}).get("x-mreader-attempt") or 1)
                    try:
                        payload = json.loads(message.body.decode())
                        await handler(payload, attempt)
                    except asyncio.CancelledError:
                        await message.nack(requeue=True)
                        raise
                    except JobDeferred:
                        try:
                            payload = json.loads(message.body.decode())
                            job_id = str(payload.get("job_id") or message.message_id or "unknown")
                            rest = {k: v for k, v in payload.items() if k != "job_id"}
                            await self.publish(queue_name, job_id, rest, attempt=attempt, retry=True)
                            await message.ack()
                        except Exception:
                            log.exception("failed to defer busy media job; original will be requeued")
                            await message.nack(requeue=True)
                    except Exception as exc:
                        try:
                            payload = json.loads(message.body.decode())
                            job_id = str(payload.get("job_id") or message.message_id or "unknown")
                            rest = {k: v for k, v in payload.items() if k != "job_id"}
                            if attempt < int(settings.RABBITMQ_MAX_ATTEMPTS):
                                await self.publish(queue_name, job_id, rest, attempt=attempt + 1, retry=True)
                            else:
                                await self.publish(queue_name, job_id, {**rest, "last_error": f"{type(exc).__name__}: {exc}"[:1000]}, attempt=attempt, dead=True)
                            await message.ack()
                        except Exception:
                            log.exception("failed to route failed media job; original will be requeued")
                            await message.nack(requeue=True)
                    else:
                        await message.ack()
        finally:
            await channel.close()

    async def ping(self) -> bool:
        await self.connect()
        assert self.channel is not None
        await self.channel.declare_exchange(settings.RABBITMQ_JOBS_EXCHANGE, ExchangeType.DIRECT, durable=True)
        return True

    async def close(self) -> None:
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
        self.connection = None
        self.channel = None


_broker: RabbitJobBroker | None = None


def get_broker() -> RabbitJobBroker:
    global _broker
    if _broker is None:
        _broker = RabbitJobBroker()
    return _broker


async def init_broker() -> RabbitJobBroker:
    broker = get_broker()
    await broker.connect()
    await broker.declare(THUMBNAIL_QUEUE)
    await broker.declare(CHAPTER_QUEUE)
    return broker


async def close_broker() -> None:
    global _broker
    if _broker is not None:
        await _broker.close()
        _broker = None
