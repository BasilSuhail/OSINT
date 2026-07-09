from app.settings import Settings


def test_data_dir_defaults_to_local_data():
    s = Settings(_env_file=None)
    assert s.data_dir == "./data"


def test_retention_overrides_from_env(monkeypatch):
    monkeypatch.setenv("RETENTION_GDELT_DAYS", "1")
    monkeypatch.setenv("RETENTION_NEWS_DAYS", "2")
    s = Settings(_env_file=None)
    assert s.retention_gdelt_days == 1
    assert s.retention_news_days == 2
    assert s.retention_hazard_days == 30  # default preserved


def test_retention_defaults_are_thirty_days():
    s = Settings(_env_file=None)
    assert s.retention_gdelt_days == 30
    assert s.retention_news_days == 30
    assert s.retention_hazard_days == 30


def test_storage_cap_defaults():
    s = Settings(_env_file=None)
    assert s.storage_cap_gb == 30
    assert s.storage_cap_floor_days == 7


def test_storage_cap_overrides_from_env(monkeypatch):
    monkeypatch.setenv("STORAGE_CAP_GB", "26")
    monkeypatch.setenv("STORAGE_CAP_FLOOR_DAYS", "3")
    s = Settings(_env_file=None)
    assert s.storage_cap_gb == 26
    assert s.storage_cap_floor_days == 3
