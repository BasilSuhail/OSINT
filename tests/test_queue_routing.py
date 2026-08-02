"""Every heavy task reaches a worker that consumes its queue (#634).

Two independent ways this has already broken:

- The compose `worker` carried no `-Q`, so it consumed only the default queue
  and nothing anywhere consumed `analytics`. Thirteen tasks were published to a
  queue with no consumer and silently never ran.
- `grade_news_severity` was added to the beat without a routing entry, so it
  ran on the fetcher queue at concurrency 4, contending with the brain for the
  model the analytics queue exists to serialise.

Neither failed loudly. Both are caught here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# Importing the module is what registers the tasks. Aliased because the plain
# `import app.tasks` form binds the name `app` to the package and shadows the
# Celery app above.
import app.tasks as _tasks_module  # noqa: F401
from app.celery_app import app

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"

#: Tasks that must never run on the fetcher queue: they hold a pandas panel, a
#: TF-IDF window, or the Ollama model. Concurrency 1 is the whole point (#388).
HEAVY_TASKS: tuple[str, ...] = (
    "app.tasks.cluster_stories",
    "app.tasks.sensor_check_stories",
    "app.tasks.score_disagreement",
    "app.tasks.extract_claims",
    "app.tasks.weekly_briefing",
    "app.tasks.journal_daily",
    "app.tasks.compute_composite",
    "app.tasks.compute_cii",
    "app.tasks.enrich_footprints",
    "app.tasks.enrich_news_places",
    "app.tasks.run_housekeeping",
    "app.tasks.brain_narrate",
    "app.tasks.brain_enrich",
    "app.tasks.grade_news_severity",
    "app.tasks.data_audit",
)


def _service_command(service: str) -> list[str]:
    compose = yaml.safe_load(COMPOSE.read_text())
    return compose["services"][service]["command"]


def _queues_consumed(service: str) -> set[str]:
    """The queues a compose worker service actually consumes.

    A celery worker with no `-Q` consumes `task_default_queue` only, which is
    where the silent failure came from — so the absent flag has to read as
    'default queue', not as 'everything'.
    """
    command = _service_command(service)
    if "-Q" not in command:
        return {app.conf.task_default_queue or "celery"}
    return set(command[command.index("-Q") + 1].split(","))


class TestRouting:
    @pytest.mark.parametrize("task", HEAVY_TASKS)
    def test_heavy_tasks_route_to_analytics(self, task: str):
        assert app.conf.task_routes.get(task) == {"queue": "analytics"}, (
            f"{task} would run on the fetcher queue"
        )

    def test_every_routed_task_is_actually_registered(self):
        """A typo in the routing table is silent: the route matches nothing and
        the task quietly keeps the default queue."""
        unknown = [t for t in app.conf.task_routes if t not in app.tasks]

        assert unknown == []


class TestComposeConsumers:
    def test_a_worker_consumes_the_analytics_queue(self):
        """The bug: nothing did, so thirteen jobs were published into a void."""
        consumed: set[str] = set()
        for service in ("worker", "worker-analytics"):
            consumed |= _queues_consumed(service)

        assert "analytics" in consumed

    def test_a_worker_consumes_the_default_queue(self):
        consumed: set[str] = set()
        for service in ("worker", "worker-analytics"):
            consumed |= _queues_consumed(service)

        assert "celery" in consumed

    def test_every_routed_queue_has_a_consumer(self):
        """Adding a third queue to the routing table without a worker for it is
        the same failure again, so derive the requirement rather than list it."""
        routed = {r["queue"] for r in app.conf.task_routes.values()}
        consumed = _queues_consumed("worker") | _queues_consumed("worker-analytics")

        assert routed <= consumed

    def test_the_analytics_worker_runs_one_job_at_a_time(self):
        """Concurrency 1 is what makes peak memory max(one job) instead of
        sum(everything beat fired together) — an 8 GB Pi depends on it."""
        command = _service_command("worker-analytics")

        assert command[command.index("--concurrency") + 1] == "1"

    def test_both_workers_state_their_queue_explicitly(self):
        """`worker` relying on the default was how this hid for so long."""
        for service in ("worker", "worker-analytics"):
            assert "-Q" in _service_command(service), f"{service} has no explicit -Q"


class TestDevOverlayIsNotAutoLoaded:
    def test_the_dev_overlay_is_not_named_override(self):
        """docker-compose.override.yml is auto-loaded by compose, which would
        apply the source mounts and --reload to the Pi as well."""
        root = COMPOSE.parent

        assert not (root / "docker-compose.override.yml").exists()
        assert (root / "docker-compose.dev.yml").exists()

    def test_dev_up_passes_the_overlay_explicitly(self):
        script = (COMPOSE.parent / "scripts" / "dev-up.sh").read_text()

        assert re.search(r"-f\s+docker-compose\.dev\.yml", script)
