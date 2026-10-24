"""WorkRun projections preserve lifecycle protection across legacy snapshots."""

import pytest

from core.runtime_manager.work_run_status import resolve_work_run_activity, work_run_has_execution
from core.runtime_manager.work_run_store import (
    active_work_payload_blocks_lifecycle,
    active_work_status_blocks_lifecycle,
)


@pytest.mark.parametrize("status", ["ready", "idle", "needs_continue", "paused_limit"])
def test_resting_or_finished_round_releases_lifecycle(status):
    activity = resolve_work_run_activity({"status": status})
    assert not activity["blocksLifecycle"]
    assert not active_work_status_blocks_lifecycle(status)


@pytest.mark.parametrize("payload", [{}, {"status": "paused"}, {"status": "unknown"}, {"status": "future_state"}])
def test_unproven_or_paused_work_remains_protected(payload):
    activity = resolve_work_run_activity(payload)
    assert activity["blocksLifecycle"]
    assert not activity["outcome"]
    assert active_work_payload_blocks_lifecycle(payload)


@pytest.mark.parametrize("status", ["blocked", "danger", "unhealthy", "crashed", "timeout", "timed_out"])
def test_other_domains_failure_or_display_words_cannot_release_work_run_protection(status):
    activity = resolve_work_run_activity({"status": status, "currentPhase": "completed", "terminalReason": "success"})
    assert activity["execution"] == "unknown"
    assert activity["outcome"] == activity["reason"] == activity["phase"] == ""
    assert activity["blocksLifecycle"]
    assert not work_run_has_execution({"status": status})


@pytest.mark.parametrize("timestamp_field", ["finishedAt", "endedAt"])
@pytest.mark.parametrize("status", ["running", "paused", "future_state", ""])
def test_end_receipt_releases_even_stale_or_unknown_state_without_fabricating_success(timestamp_field, status):
    payload = {"status": status, timestamp_field: "2026-10-24T00:00:00Z"}
    activity = resolve_work_run_activity(payload)
    assert activity["execution"] == "settled"
    assert activity["outcome"] == activity["phase"] == ""
    assert not activity["blocksLifecycle"]
    assert not active_work_payload_blocks_lifecycle(payload)


@pytest.mark.parametrize(("status", "outcome"), [
    ("force_stopped", "stopped"), ("stopped_by_user", "stopped"),
    ("canceled", "cancelled"), ("success", "completed"), ("succeeded", "completed"),
    ("stop_failed", "failed"), ("partial", "partial"), ("closed", "closed"), ("routed", "routed"),
    ("failure", "failed"), ("error", "failed"), ("aborted", "stopped"),
])
def test_terminal_aliases_preserve_cause_and_release_lifecycle(status, outcome):
    activity = resolve_work_run_activity({"status": status, "currentPhase": "reading"})
    assert activity == {
        "execution": "settled", "phase": "", "outcome": outcome,
        "reason": status, "rawStatus": status, "blocksLifecycle": False,
    }
    assert not active_work_status_blocks_lifecycle(status)


@pytest.mark.parametrize("field", ["status", "currentPhase", "phase", "runtimeStatus"])
def test_activity_phase_is_live_evidence_and_cannot_fabricate_completion(field):
    activity = resolve_work_run_activity({field: "reading", "terminalReason": "success"})
    assert activity["execution"] == "running"
    assert activity["phase"] == "reading"
    assert activity["outcome"] == activity["reason"] == ""
    assert activity["blocksLifecycle"]


@pytest.mark.parametrize(("payload", "raw", "execution", "outcome", "blocking"), [
    ({"status": "future_state", "currentPhase": "completed", "phase": "ready", "runtimeStatus": "success"}, "future_state", "unknown", "", True),
    ({"status": "running", "currentPhase": "completed", "runtimeStatus": "force_stopped"}, "running", "running", "", True),
    ({"status": "completed", "currentPhase": "running"}, "completed", "settled", "completed", False),
    ({"status": "ready", "currentPhase": "reading"}, "ready", "idle", "", False),
    ({"currentPhase": "future_state", "phase": "completed"}, "future_state", "unknown", "", True),
    ({"phase": "running", "runtimeStatus": "completed"}, "running", "running", "", True),
    ({"runtimeStatus": "force_stopped"}, "force_stopped", "settled", "stopped", False),
])
def test_first_explicit_status_controls_fallback_conflicts(payload, raw, execution, outcome, blocking):
    activity = resolve_work_run_activity(payload)
    assert (activity["rawStatus"], activity["execution"], activity["outcome"], activity["blocksLifecycle"]) == (
        raw, execution, outcome, blocking,
    )
    assert active_work_payload_blocks_lifecycle(payload) == blocking


def test_active_phase_and_stop_cause_are_separate_projection_fields():
    assert resolve_work_run_activity({"status": "running", "currentPhase": "reading"}) == {
        "execution": "running", "phase": "reading", "outcome": "", "reason": "",
        "rawStatus": "running", "blocksLifecycle": True,
    }
    stopped = resolve_work_run_activity({"status": "stopped", "terminalReason": "success", "runtimeStatus": "force_stopped"})
    assert stopped["outcome"] == "stopped"
    assert stopped["reason"] == "force_stopped"


def test_end_receipt_is_independent_of_other_empty_timestamp_and_does_not_rewrite_snapshot():
    snapshot = {"status": "future_state", "finishedAt": " ", "endedAt": "2026-10-24T00:00:00Z"}
    before = dict(snapshot)
    assert not resolve_work_run_activity(snapshot)["blocksLifecycle"]
    assert snapshot == before


@pytest.mark.parametrize("status", ["queued", "running", "stopping", "paused", "force_stopping", "reading"])
def test_identified_execution_is_distinct_from_unknown_safety_blocking(status):
    assert work_run_has_execution({"status": status})
    assert not work_run_has_execution({"status": status, "finishedAt": "2026-10-24T00:00:00Z"})
    assert not work_run_has_execution({"status": "future_state", "currentPhase": status})


@pytest.mark.parametrize("status", ["", "unknown", "ready", "needs_continue", "paused_limit", "completed"])
def test_missing_resting_or_settled_state_cannot_claim_an_active_owner(status):
    assert not work_run_has_execution({"status": status})
