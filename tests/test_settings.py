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
    assert s.retention_hazard_days == 2  # default preserved
