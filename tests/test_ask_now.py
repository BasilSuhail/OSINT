"""The terminal ask (#997) — it exists so a failure names itself."""

import ast
from pathlib import Path

from app.brain import ask_now

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = (ROOT / "Makefile").read_text()
SOURCE = (ROOT / "app" / "brain" / "ask_now.py").read_text()


class TestItRunsWhereItIsCalled:
    def test_the_makefile_calls_the_module_that_exists(self) -> None:
        target = next(line for line in MAKEFILE.splitlines() if "ask_now" in line)
        assert "app.brain.ask_now" in target

    #: The image copies `app/` and not `scripts/`. A diagnostic that only runs
    #: for somebody with a host virtualenv cannot diagnose the machine that has
    #: the problem, which is the Pi.
    def test_it_lives_under_app_so_the_image_has_it(self) -> None:
        assert (ROOT / "app" / "brain" / "ask_now.py").exists()

    #: The API is the process holding the model connection the console uses.
    def test_it_runs_in_the_api_container(self) -> None:
        target = next(line for line in MAKEFILE.splitlines() if "ask_now" in line)
        assert "exec -T api" in target


class TestTheErrorSurvives:
    #: The whole point. Every other path turns the exception into a typed
    #: sentence at HTTP 200; if this one catches too, there is nothing left that
    #: can say what went wrong.
    def test_the_model_call_is_not_wrapped_in_a_handler(self) -> None:
        assert not [
            node for node in ast.walk(ast.parse(SOURCE)) if isinstance(node, ast.ExceptHandler)
        ]

    def test_a_blocked_gate_is_reported_rather_than_obeyed(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr(ask_now.gate, "qa_ram_blocked", lambda: True)
        monkeypatch.setattr(ask_now.gate, "ram_free_mb", lambda: 512)
        monkeypatch.setattr(ask_now.gate, "ollama_is_local", lambda: True)
        ask_now._report_environment()
        assert "BLOCKED" in capsys.readouterr().out


class TestWhatItReports:
    def test_it_names_the_floor_beside_what_is_free(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr(ask_now.gate, "qa_ram_blocked", lambda: False)
        monkeypatch.setattr(ask_now.gate, "ram_free_mb", lambda: 4096)
        monkeypatch.setattr(ask_now.gate, "ollama_is_local", lambda: True)
        ask_now._report_environment()
        out = capsys.readouterr().out
        assert "4096 MB" in out and "floor" in out

    #: Ollama truncates an oversized prompt silently and answers anyway, so a
    #: prompt that no longer fits reads as a model that has got worse.
    def test_an_oversized_prompt_is_called_truncated(self, capsys) -> None:
        ask_now._report_prompt("x" * (ask_now.client._NUM_CTX * 4 + 4))
        assert "TRUNCATED" in capsys.readouterr().out

    def test_a_prompt_that_fits_is_not(self, capsys) -> None:
        ask_now._report_prompt("x" * 100)
        assert "TRUNCATED" not in capsys.readouterr().out

    #: This command goes past `ASK_ENABLED` on purpose — running it is itself a
    #: decision to ask. Printing the setting is what stops that being confusing:
    #: an answer here beside no ask control on screen is a difference the
    #: operator can read off the output rather than one they have to deduce.
    def test_it_names_the_question_setting_beside_the_gate(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr(ask_now.gate, "qa_ram_blocked", lambda: False)
        monkeypatch.setattr(ask_now.gate, "ollama_is_local", lambda: False)
        monkeypatch.setattr(ask_now.settings, "ask_enabled", False)
        ask_now._report_environment()
        assert "ask_enabled" in capsys.readouterr().out

    def test_it_says_so_when_the_console_has_the_box(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr(ask_now.gate, "qa_ram_blocked", lambda: False)
        monkeypatch.setattr(ask_now.gate, "ollama_is_local", lambda: False)
        monkeypatch.setattr(ask_now.settings, "ask_enabled", True)
        ask_now._report_environment()
        assert "ask_enabled    true" in capsys.readouterr().out
