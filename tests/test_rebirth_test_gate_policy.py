"""evolution.test_gate_enabled / test_gate_timeout wiring tests.

The two fields existed on the panel but the restart gate always ran pytest with
a hardcoded 120s timeout. These tests lock the read-through:

- default config keeps the gate on with 120s;
- explicit off/timeout values are honoured;
- a broken config keeps the gate on (never silently disables it).
"""

from __future__ import annotations

from types import SimpleNamespace

from tools import rebirth_tools


def _cfg(enabled: bool, timeout: int):
    return SimpleNamespace(
        evolution=SimpleNamespace(
            test_gate_enabled=enabled, test_gate_timeout=timeout
        )
    )


def test_defaults_stay_on(monkeypatch):
    import config

    monkeypatch.setattr(config, "get_config", lambda: _cfg(True, 120))
    assert rebirth_tools._evolution_test_gate_policy() == (True, 120)


def test_disabled_and_timeout_are_read(monkeypatch):
    import config

    monkeypatch.setattr(config, "get_config", lambda: _cfg(False, 7))
    assert rebirth_tools._evolution_test_gate_policy() == (False, 7)


def test_config_failure_keeps_gate_on(monkeypatch):
    import config

    def _boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(config, "get_config", _boom)
    assert rebirth_tools._evolution_test_gate_policy() == (True, 120)


def test_zero_timeout_falls_back_to_default(monkeypatch):
    import config

    monkeypatch.setattr(config, "get_config", lambda: _cfg(True, 0))
    assert rebirth_tools._evolution_test_gate_policy() == (True, 120)
