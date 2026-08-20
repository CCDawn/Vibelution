from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.launcher import branch_instance_lifecycle as lifecycle

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "desktop"
    / "electron"
    / "src"
    / "lifecycle"
    / "__fixtures__"
    / "instanceLifecycleProjection.cases.json"
)


def _load_cases() -> list[dict]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert isinstance(cases, list)
    return cases


CASES = _load_cases()


def _projection_kwargs(raw_input: dict) -> dict:
    return {
        "observed_state": str(raw_input.get("observedState") or ""),
        "phase": str(raw_input.get("phase") or ""),
        "registry_status": str(raw_input.get("registryStatus") or ""),
        "backend_alive": bool(raw_input.get("backendAlive")),
        "backend_healthy": bool(raw_input.get("backendHealthy")),
        "backend_listening": bool(raw_input.get("backendListening")),
        "backend_conflict": bool(raw_input.get("backendConflict")),
        "frontend_ready": bool(raw_input.get("frontendReady")),
        "window_open": bool(raw_input.get("windowOpen")),
        "failure_message": str(raw_input.get("failureMessage") or ""),
        "desired_state": str(raw_input.get("desiredState") or ""),
        "start_supervisor_lost": bool(raw_input.get("startSupervisorLost")),
    }


def test_shared_fixture_has_enough_unique_cases():
    assert len(CASES) >= 30
    ids = [str(item.get("id") or "") for item in CASES]
    assert "" not in ids
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("case", CASES, ids=lambda item: str(item.get("id") or "missing-id"))
def test_python_projection_matches_shared_fixture(case: dict):
    expected = case["expected"]
    raw_input = case["input"] if isinstance(case.get("input"), dict) else {}
    state, code = lifecycle._instance_lifecycle_state(**_projection_kwargs(raw_input))
    assert state == expected["lifecycleState"]
    assert code == expected["errorCode"]
    startable = lifecycle._lifecycle_projection_is_startable(
        state,
        bool(raw_input.get("backendAlive") or raw_input.get("backendListening") or raw_input.get("windowOpen")),
    )
    assert startable is expected["startable"]
