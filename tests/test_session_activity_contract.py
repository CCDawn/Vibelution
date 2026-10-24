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


def test_native_notification_policy_is_generated_from_backend_receipts():
    from core.chat.session_activity import SESSION_NOTIFICATION_CONTRACT
    from scripts.generate_activity_contract import NATIVE_NOTIFICATION_OUTPUT, render_notification_contract

    assert NATIVE_NOTIFICATION_OUTPUT.read_text(encoding="utf-8") == render_notification_contract()
    admitted = set(SESSION_NOTIFICATION_CONTRACT["terminalStatuses"])
    assert {"completed", "needs_continue", "paused_limit", "failed_provider", "failed_runtime", "aborted", "cancelled"} <= admitted
    assert not admitted.intersection({"ready", "idle", "running", "paused", "stopped", "stopped_by_user", "force_stopped", "", "future_status"})
    # The renderer transports successful aliases as the canonical completed.
    assert not admitted.intersection({"done", "success", "succeeded"})
    assert SESSION_NOTIFICATION_CONTRACT["successTerminalStatuses"] == ["completed"]
    assert SESSION_NOTIFICATION_CONTRACT["continuationTerminalStatuses"] == ["needs_continue", "paused_limit"]


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
    assert set(SESSION_ACTIVITY_CONTRACT["executions"].values()) <= SESSION_ACTIVITY_CONTRACT["labels"].keys()
    assert set(SESSION_ACTIVITY_CONTRACT["outcomes"].values()) <= SESSION_ACTIVITY_CONTRACT["labels"].keys()
    from core.runtime_manager.work_run_status import WORK_RUN_ACTIVITY_CONTRACT

    assert set(WORK_RUN_ACTIVITY_CONTRACT["executions"].values()) <= WORK_RUN_ACTIVITY_CONTRACT["labels"].keys()
    assert set(WORK_RUN_ACTIVITY_CONTRACT["outcomes"].values()) <= WORK_RUN_ACTIVITY_CONTRACT["labels"].keys()


POLICY_CASES = json.loads((Path(__file__).parent / "fixtures/activity_policy_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", POLICY_CASES, ids=lambda case: case["name"])
def test_session_activity_policy(case):
    from core.chat.session_activity import session_activity_policy

    assert session_activity_policy(case["session"]) == case["expected"]
    from core.chat.session_activity import session_activity_group

    assert session_activity_group(case["session"]) == case["expectedGroup"]


WORK_CASES = json.loads((Path(__file__).parent / "fixtures/work_run_activity_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", WORK_CASES, ids=lambda case: case["name"])
def test_work_run_activity_behavior(case):
    from core.runtime_manager.work_run_status import resolve_work_run_activity

    assert resolve_work_run_activity(case["snapshot"]) == case["expected"]


def test_all_activity_display_languages_cover_the_same_keys():
    from scripts.generate_activity_contract import render_contract

    contract = json.loads(render_contract().split(" = ", 1)[1].removesuffix(" as const;\n"))
    for domain in contract.values():
        assert domain["labels"].keys() == domain["labelsEn"].keys()
        if "phaseLabels" in domain and "phaseLabelsEn" in domain:
            assert domain["phaseLabels"].keys() == domain["phaseLabelsEn"].keys()
