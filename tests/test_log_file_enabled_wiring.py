"""log.file_enabled wiring tests.

The field was visible on the config panel but the conversation JSONL sink
wrote unconditionally. These tests lock the read-through and the fail-open
default used when the config cannot be read.
"""

from __future__ import annotations

from types import SimpleNamespace

import config
import importlib

logger_mod = importlib.import_module("core.logging.logger")


def _cfg(file_enabled: bool):
    return SimpleNamespace(log=SimpleNamespace(file_enabled=file_enabled))


def test_configured_off_disables_the_sink(monkeypatch):
    monkeypatch.setattr(config, "get_config", lambda: _cfg(False))
    assert logger_mod._resolve_file_logging_enabled() is False


def test_configured_on_keeps_the_sink(monkeypatch):
    monkeypatch.setattr(config, "get_config", lambda: _cfg(True))
    assert logger_mod._resolve_file_logging_enabled() is True


def test_broken_config_keeps_the_sink_on(monkeypatch):
    def _boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(config, "get_config", _boom)
    assert logger_mod._resolve_file_logging_enabled() is True


def test_write_skips_file_when_disabled(tmp_path, monkeypatch):
    recorder = logger_mod.ConversationLogger()
    monkeypatch.setattr(recorder, "_log_dir", str(tmp_path))
    monkeypatch.setattr(recorder, "_current_session_file", None)
    monkeypatch.setattr(recorder, "_file_logging_enabled", False)

    recorder._write({"type": "probe"})

    assert list(tmp_path.iterdir()) == []


def test_write_still_writes_when_enabled(tmp_path, monkeypatch):
    recorder = logger_mod.ConversationLogger()
    monkeypatch.setattr(recorder, "_log_dir", str(tmp_path))
    monkeypatch.setattr(recorder, "_current_session_file", None)
    monkeypatch.setattr(recorder, "_file_logging_enabled", True)

    recorder._write({"type": "probe"})

    written = list(tmp_path.iterdir())
    assert len(written) == 1
    assert '"type": "probe"' in written[0].read_text(encoding="utf-8")
