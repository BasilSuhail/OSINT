"""Lightweight Redis pub/sub used to wake SSE clients when new events land.

The payload is just the inserted-row count; subscribers re-query the DB for the
actual rows. Redis is already the Celery broker, so no new infrastructure.
"""

from __future__ import annotations

from collections.abc import Iterator
from time import sleep

from redis import Redis
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.settings import settings

EVENTS_CHANNEL = "events:new"

_client: Redis | None = None


def _default_client() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def publish_new_events(count: int, *, client: Redis | None = None) -> None:
    """Announce that ``count`` new events were inserted. No-op when count <= 0."""
    if count <= 0:
        return
    (client or _default_client()).publish(EVENTS_CHANNEL, str(count))


def subscribe_new_events(client: Redis | None = None) -> Iterator[str | None]:
    """Yield message payloads, or None as an SSE keepalive tick while idle."""
    pubsub = (client or _default_client()).pubsub()
    pubsub.subscribe(EVENTS_CHANNEL)
    try:
        while True:
            try:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
            except RedisTimeoutError:
                yield None
                continue
            except RedisError:
                yield None
                sleep(1)
                continue
            if message is None:
                yield None
                continue
            if message.get("type") == "message":
                yield message["data"]
    finally:
        pubsub.close()
