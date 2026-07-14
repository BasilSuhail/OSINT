from datetime import UTC, datetime, timedelta

from app.runtime import load


def test_runtime_busy_reason_reports_active_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(load.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(load.settings, "runtime_busy_lock_ttl_s", 60)

    load.heartbeat("brain-qa-eval")

    assert load.busy_reason()
    load.clear("brain-qa-eval")
    assert load.busy_reason() is None


def test_runtime_lock_ignores_stale_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(load.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(load.settings, "runtime_busy_lock_ttl_s", 60)
    load.heartbeat("brain-qa-eval")

    later = datetime.now(UTC) + timedelta(seconds=61)

    assert load.active_activity(now=later) is None
