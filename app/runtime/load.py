"""Lightweight local backpressure for expensive optional work.

The live app can keep fetchers, API, and frontend up while a local model eval is
running, but optional enrichment/analytics should not compete with it on a Pi.
This module uses a small heartbeat file under data/runtime; no broker feature or
new dependency is required.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.settings import settings

LOCK_FILE = "busy.json"


def _now() -> datetime:
    return datetime.now(UTC)


def lock_path() -> Path:
    return Path(settings.data_dir) / "runtime" / LOCK_FILE


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _read_lock() -> dict[str, Any] | None:
    path = lock_path()
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def active_activity(*, now: datetime | None = None) -> dict[str, Any] | None:
    payload = _read_lock()
    if payload is None:
        return None
    heartbeat_at = _parse_dt(payload.get("heartbeat_at"))
    if heartbeat_at is None:
        return None
    now = now or _now()
    ttl = timedelta(seconds=settings.runtime_busy_lock_ttl_s)
    if heartbeat_at + ttl < now:
        return None
    return payload


def busy_reason(*, now: datetime | None = None) -> str | None:
    payload = active_activity(now=now)
    if payload is None:
        return None
    activity = payload.get("activity") or "runtime activity"
    return f"{activity} active — backing off optional heavy work"


def heartbeat(activity: str) -> None:
    now = _now().isoformat()
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "activity": activity,
                "pid": os.getpid(),
                "heartbeat_at": now,
            },
            sort_keys=True,
        )
    )


def clear(activity: str) -> None:
    payload = _read_lock()
    if payload is None:
        return
    if payload.get("activity") != activity or payload.get("pid") != os.getpid():
        return
    try:
        lock_path().unlink()
    except FileNotFoundError:
        return


@contextmanager
def activity(activity_name: str) -> Iterator[None]:
    heartbeat(activity_name)
    try:
        yield
    finally:
        clear(activity_name)
