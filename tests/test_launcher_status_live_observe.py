from __future__ import annotations


def test_status_skips_live_observe_only_when_runtime_already_reports_open():
    from core.launcher import service as launcher_service

    runtime_state = {
        "workbench": {
            "observedState": "open",
            "desiredState": "open",
            "phase": "steady",
            "backendPort": 8002,
        }
    }
    assert launcher_service._runtime_state_workbench_is_live(runtime_state) is True
    assert launcher_service._runtime_state_workbench_is_live({"workbench": {"observedState": "closed"}}) is False


def test_status_live_observes_when_runtime_still_says_closed(monkeypatch):
    from core.launcher import service as launcher_service

    calls: list[int] = []
    runtime_state = {
        "daemonRunning": True,
        "updatedAt": "2099-01-01T00:00:00+00:00",
        "workbench": {
            "observedState": "closed",
            "desiredState": "open",
            "phase": "steady",
            "backendPort": 8002,
        },
    }
    monkeypatch.setattr(
        launcher_service,
        "_observed_workbench",
        lambda: calls.append(1) or {"observedState": "open"},
    )

    observed = launcher_service._status_observed_workbench(runtime_state)

    assert calls == [1]
    assert observed["observedState"] == "open"
