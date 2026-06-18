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
    include=["app.tasks"],
)

app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

# Beat schedule is populated by `app.tasks` so the schedule lives next to the
# task definitions it triggers.
