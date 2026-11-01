from __future__ import annotations

from core.launcher import freshness as launcher_freshness


def test_freshness_is_current_when_start_matches_head(monkeypatch):
    launcher_freshness.reset_launcher_start_identity_for_tests()
    monkeypatch.setattr(launcher_freshness, "_git_identity", lambda: {"commit": "aaa111", "branch": "main"})

    launcher_freshness.capture_launcher_start_identity()
    payload = launcher_freshness.get_launcher_freshness()

    assert payload["current"] is True
    assert payload["runningCommit"] == "aaa111"
    assert payload["headCommit"] == "aaa111"
    assert "已是最新" in payload["label"]


def test_freshness_is_stale_when_head_moves_after_start(monkeypatch):
    launcher_freshness.reset_launcher_start_identity_for_tests()
    states = iter(
        [
            {"commit": "aaa111bbbb", "branch": "main"},
            {"commit": "ccc222dddd", "branch": "main"},
        ]
    )
    monkeypatch.setattr(launcher_freshness, "_git_identity", lambda: next(states))

    launcher_freshness.capture_launcher_start_identity()
    payload = launcher_freshness.get_launcher_freshness()

    assert payload["current"] is False
    assert payload["runningShort"] == "aaa111bbbb"[:12]
    assert payload["headShort"] == "ccc222dddd"[:12]
    assert "落后本地 main" in payload["label"]


def test_freshness_retries_when_first_git_identity_is_empty(monkeypatch):
    launcher_freshness.reset_launcher_start_identity_for_tests()
    # One identity capture per freshness read; the start identity reuses it.
    states = iter(
        [
            {"commit": "", "branch": ""},
            {"commit": "aaa111bbbbcc", "branch": "main"},
        ]
    )
    monkeypatch.setattr(launcher_freshness, "_git_identity", lambda: next(states))

    first = launcher_freshness.get_launcher_freshness()
    assert first["current"] is None
    assert first["label"] == "Launcher 版本未知"

    second = launcher_freshness.get_launcher_freshness()
    assert second["current"] is True
    assert second["runningCommit"] == "aaa111bbbbcc"
    assert "已是最新" in second["label"]


def test_freshness_first_read_captures_head_identity_once(monkeypatch):
    """One HEAD capture serves both the start identity and the head comparison."""

    launcher_freshness.reset_launcher_start_identity_for_tests()
    calls: list[int] = []

    def identity() -> dict[str, str]:
        calls.append(1)
        return {"commit": "aaa111bbbbcc", "branch": "main"}

    monkeypatch.setattr(launcher_freshness, "_git_identity", identity)

    payload = launcher_freshness.get_launcher_freshness()

    assert len(calls) == 1
    assert payload["current"] is True
    assert payload["runningCommit"] == "aaa111bbbbcc"
    assert payload["headCommit"] == "aaa111bbbbcc"
    assert payload["runningBranch"] == "main"
    assert payload["startedAt"]


def test_capture_start_identity_reuses_caller_supplied_head(monkeypatch):
    launcher_freshness.reset_launcher_start_identity_for_tests()

    def fail() -> dict[str, str]:
        raise AssertionError("a supplied head must not trigger a second git capture")

    monkeypatch.setattr(launcher_freshness, "_git_identity", fail)
    supplied = {"commit": "bbb222", "branch": "codex/lane"}

    started = launcher_freshness.capture_launcher_start_identity(captured_head=supplied)

    assert started["commit"] == "bbb222"
    assert started["branch"] == "codex/lane"
    assert started["startedAt"]
    # The caller's dict is copied, not adopted.
    assert "startedAt" not in supplied
