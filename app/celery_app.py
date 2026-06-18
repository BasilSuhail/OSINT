"""Celery application stub.

Workers register against this app. The Beat schedule lives here so the cron-style
configuration is auditable in one file.
"""

from celery import Celery

from app.settings import settings

app = Celery(
    "osint",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[],
)

app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

# Beat schedule will populate as workers are added.
# See docs/architecture/03-ingestion.md for the planned cadences per source.
app.conf.beat_schedule = {}
