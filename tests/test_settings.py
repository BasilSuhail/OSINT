import pytest
from pydantic import ValidationError

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


#: The key `env.example` ships blank. Blank has to mean on, or the file the
#: project ships would refuse to start the project — pydantic reads a bool from
#: a small vocabulary and an empty string is not in it.
def test_a_blank_question_setting_is_on(monkeypatch):
    monkeypatch.setenv("ASK_ENABLED", "")
    assert Settings(_env_file=None).ask_enabled is True


def test_an_absent_question_setting_is_on(monkeypatch):
    monkeypatch.delenv("ASK_ENABLED", raising=False)
    assert Settings(_env_file=None).ask_enabled is True


#: The vocabulary the console's own reader was widened to match. Every word
#: here has to mean the same thing on both sides, or the console draws an ask
#: control for an endpoint that refuses.
def test_every_word_for_off_is_off(monkeypatch):
    for word in ("false", "f", "no", "n", "off", "0", "FALSE", "Off"):
        monkeypatch.setenv("ASK_ENABLED", word)
        assert Settings(_env_file=None).ask_enabled is False, word


def test_every_word_for_on_is_on(monkeypatch):
    for word in ("true", "t", "yes", "y", "on", "1", "TRUE", "On"):
        monkeypatch.setenv("ASK_ENABLED", word)
        assert Settings(_env_file=None).ask_enabled is True, word


#: Loudly, not silently. A word neither side knows is a mistake, and guessing
#: at it is how a console ends up disagreeing with the API about this setting.
def test_a_word_nobody_knows_stops_the_api(monkeypatch):
    monkeypatch.setenv("ASK_ENABLED", "maybe")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
