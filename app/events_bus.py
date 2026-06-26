"""Lightweight Redis pub/sub used to wake SSE clients when new events land.

The payload is just the inserted-row count; subscribers re-query the DB for the
actual rows. Redis is already the Celery broker, so no new infrastructure.
"""

from __future__ import annotations

from collections.abc import Iterator

from redis import Redis

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


def subscribe_new_events(client: Redis | None = None) -> Iterator[str]:
    """Yield each message payload published to the events channel (blocking)."""
    pubsub = (client or _default_client()).pubsub()
    pubsub.subscribe(EVENTS_CHANNEL)
    try:
        for message in pubsub.listen():
            if message.get("type") == "message":
                yield message["data"]
    finally:
        pubsub.close()
