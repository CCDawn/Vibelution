"""Behavior vectors shared by Python projections and frontend consumers."""

import json
from pathlib import Path

import pytest

from core.chat.session_activity import resolve_session_activity
from core.runtime_manager.work_run_store import active_work_payload_blocks_lifecycle

CASES = json.loads((Path(__file__).parent / "fixtures/activity_contract_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_session_activity_behavior(case):
    assert resolve_session_activity(
        case["session"], runtime_running=case.get("runtimeRunning", False),
        authoritative_runtime=case.get("authoritativeRuntime", False),
    ) == case["expected"]


@pytest.mark.parametrize("payload", [{}, {"status": "future_status"}, {"status": "paused"}])
def test_unknown_or_paused_work_is_still_protected_from_lifecycle_shutdown(payload):
    assert active_work_payload_blocks_lifecycle(payload)


def test_frontend_vocabulary_is_generated_from_backend_domains():
    from scripts.generate_activity_contract import OUTPUT, render_contract

    assert OUTPUT.read_text(encoding="utf-8") == render_contract()


def test_every_canonical_run_state_and_phase_has_a_display_mapping():
    from core.chat.session_activity import SESSION_ACTIVITY_CONTRACT
    from core.runtime_manager.agent_run_status import (
        RUN_ACTIVE_STATUSES,
        RUN_STATUS_ALIASES,
        RUN_STATUS_LABELS,
        RUN_TERMINAL_STATUSES,
    )

    assert RUN_ACTIVE_STATUSES | RUN_TERMINAL_STATUSES <= RUN_STATUS_LABELS.keys()
    assert set(RUN_STATUS_ALIASES.values()) <= RUN_STATUS_LABELS.keys()
    assert set(SESSION_ACTIVITY_CONTRACT["phases"]) == set(SESSION_ACTIVITY_CONTRACT["phaseLabels"])
