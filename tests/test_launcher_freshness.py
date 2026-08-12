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
