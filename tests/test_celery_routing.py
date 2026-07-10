"""Tests for the analytics queue split + child recycling (#388)."""

from __future__ import annotations

from app.tasks import app as celery_app

ANALYTICAL_TASKS = (
    "app.tasks.cluster_stories",
    "app.tasks.sensor_check_stories",
    "app.tasks.score_disagreement",
    "app.tasks.extract_claims",
    "app.tasks.journal_daily",
    "app.tasks.compute_composite",
    "app.tasks.compute_cii",
    "app.tasks.run_housekeeping",
)


def test_analytical_tasks_route_to_analytics_queue() -> None:
    routes = celery_app.conf.task_routes
    for task in ANALYTICAL_TASKS:
        assert routes[task]["queue"] == "analytics", f"{task} not serialized"


def test_fetchers_stay_on_default_queue() -> None:
    routes = celery_app.conf.task_routes
    assert "app.tasks.run_fetcher" not in routes


def test_children_are_recycled() -> None:
    assert celery_app.conf.worker_max_tasks_per_child == 20
    assert celery_app.conf.worker_max_memory_per_child == 512_000
