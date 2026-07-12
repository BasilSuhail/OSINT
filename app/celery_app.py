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
    # Memory discipline (#388): prefork children hold their high-water RSS
    # forever (one ACLED xlsx parse ≈ 2 GB) — recycle them so it comes back.
    worker_max_tasks_per_child=20,
    worker_max_memory_per_child=512_000,  # KB
)

# The analytical jobs are the heavy ones (pandas panels, TF-IDF windows, the
# nightly Ollama batch). Routing them to one queue consumed by a dedicated
# --concurrency 1 worker makes them run strictly one-by-one (#388): peak
# memory is max(one job), not sum(everything the beat fires together).
# Fetchers stay on the default queue — small, I/O-bound, fine concurrently.
app.conf.task_routes = {
    task: {"queue": "analytics"}
    for task in (
        "app.tasks.cluster_stories",
        "app.tasks.sensor_check_stories",
        "app.tasks.score_disagreement",
        "app.tasks.extract_claims",
        "app.tasks.weekly_briefing",
        "app.tasks.journal_daily",
        "app.tasks.compute_composite",
        "app.tasks.compute_cii",
        "app.tasks.run_housekeeping",
        "app.tasks.brain_narrate",
    )
}

# Beat schedule is populated by `app.tasks` so the schedule lives next to the
# task definitions it triggers.
