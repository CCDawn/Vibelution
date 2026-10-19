"""Research supervision observes real Ledger rows and uses native replay."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.web.services.team_workflow.generic import binding, research_source, store
from core.web.services.team_workflow.research_runtime import formal_write_runtime
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    build_attempt_record, build_command_record, build_outbox_record,
)


@pytest.fixture
def source(tmp_path, monkeypatch):
    harness = CommandHarness(tmp_path / "research.sqlite3")
    harness.seed_run(status="blocked")
    monkeypatch.setattr(formal_write_runtime, "get_write_store", lambda: harness.store)
    monkeypatch.setattr(formal_write_runtime, "get_command_service", lambda: harness.command_service)
    monkeypatch.setattr(binding, "authorization_reason", lambda *args: "")
    record = {"id": "supervisor-1", "teamId": "research-team", "stopRequested": False,
              "flow": {"id": "source", "fields": [], "steps": [
                  {"id": "research-step", "kind": "research", "researchSource": {
                      "runId": "run-test", "nodeId": "problem_understanding"}}],
                  "failureRecovery": {"bindingId": "bound", "replaySafety": "idempotent"}},
              "attempts": []}

    def seed(count=1, *, code="counter_evidence_missing", status="failed", retry=True):
        def write(uow):
            for index in range(1, count + 1):
                command = build_command_record(command_id=f"cmd-source-{index}",
                                               idempotency_key=f"source-{index}")
                uow.repository.insert_command(command)
                attempt = replace(build_attempt_record(
                    node_run_id=f"nr-source-{index}", command_id=command.command_id,
                    attempt=index, status=status if index == count else "stale",
                    problem_json=json.dumps({"code": code, "detail": "private prompt secret"}),
                ), retry_of_node_run_id=f"nr-source-{index - 1}" if retry and index > 1 else None)
                uow.repository.insert_attempt(attempt)
        harness.store.submit(write, force_flush=True).result(timeout=10)
        record["attempts"] = research_source.observe(record)["attempts"]

    try:
        yield SimpleNamespace(harness=harness, record=record, seed=seed)
    finally:
        harness.close()


def test_observe_native_lineage_is_read_only_and_bounded(source):
    source.seed(3)
    before = source.harness.store.latest_event_sequence("run-test")
    result = research_source.observe(source.record)
    assert result["status"] == "failed" and result["eligible"]
    assert result["retryExhausted"]
    assert [item["key"] for item in result["attempts"]] == [f"nr-source-{i}" for i in range(1, 4)]
    assert all(item["status"] == "failed" for item in result["attempts"])
    assert all(item["nodeId"] == "research-step" for item in result["attempts"])
    assert "private prompt" not in json.dumps(result)
    assert source.harness.store.latest_event_sequence("run-test") == before
    assert len(source.harness.store.list_attempts("run-test")) == 3
    assert source.harness.store.list_pending_outbox("run-test") == []


@pytest.mark.parametrize("field,value", [("teamId", "other-team"), ("runId", "missing"),
                                       ("nodeId", "missing")])
def test_source_requires_exact_team_run_and_node(source, field, value):
    source.seed()
    record = copy.deepcopy(source.record)
    if field == "teamId":
        record[field] = value
    else:
        record["flow"]["steps"][0]["researchSource"][field] = value
    with pytest.raises(store.WorkflowError):
        research_source.observe(record)


@pytest.mark.parametrize("code,reason", [("new_unclassified_error", "source_problem_unsupported"),
                                        ("collection_run_needs_continue", "source_human_required"),
                                        ("budget_exceeded", "source_human_required")])
def test_unsupported_and_human_required_failures_cannot_escalate_or_replay(source, code, reason):
    source.seed(code=code)
    snapshot = research_source.observe(source.record)
    assert snapshot["status"] == "failed"
    assert not snapshot["eligible"] and snapshot["reason"] == reason
    assert research_source.replay(source.record) == reason
    assert len(source.harness.store.list_attempts("run-test")) == 1


@pytest.mark.parametrize("status", ["pending", "leased"])
def test_unsettled_outbox_blocks_even_terminal_attempt(source, status):
    source.seed()
    source.harness.store.submit(lambda uow: uow.repository.insert_outbox(
        build_outbox_record(command_id="cmd-source-1", status=status)), force_flush=True).result(timeout=10)
    assert research_source.observe(source.record)["reason"] == "source_execution_unsettled"
    assert research_source.replay(source.record) == "source_execution_unsettled"


def test_active_attempt_excludes_failed_source(source):
    source.seed(status="running")
    snapshot = research_source.observe(source.record)
    assert snapshot["status"] == "running" and not snapshot["eligible"]
    assert research_source.fence(source.record) == "source_execution_unsettled"


def test_disconnected_attempts_are_not_a_retry_lineage(source):
    source.seed(2, retry=False)
    snapshot = research_source.observe(source.record)
    assert snapshot["status"] == "failed"
    assert not snapshot["eligible"] and snapshot["reason"] == "source_lineage_invalid"
    assert research_source.replay(source.record) == "source_lineage_invalid"


def test_native_retry_creates_one_attempt_and_recovers_a_lost_receipt(source):
    source.seed()
    assert research_source.fence(source.record) == ""
    assert research_source.replay(source.record) == ""
    assert research_source.replay(source.record) == ""
    attempts = source.harness.store.list_attempts("run-test")
    assert len(attempts) == 2
    assert attempts[0].status == "stale"
    assert attempts[1].retry_of_node_run_id == "nr-source-1"
    assert len(source.harness.store.list_pending_outbox("run-test")) == 1
    command = source.harness.store.read(lambda repo: repo.get_command(attempts[-1].command_id))
    assert json.loads(command.requested_by_json) == {"actorType": "system", "actorId": "harness-failure-recovery"}
    assert source.harness.wake_count == 1
    assert research_source.fence(source.record) == "source_advanced"


def test_durable_replay_anchor_survives_projection_of_new_attempt(source):
    source.seed()
    source.record["_recoveryReplayAfter"] = "nr-source-1"
    assert research_source.replay(source.record) == ""
    source.record["attempts"] = research_source.observe(source.record)["attempts"]
    assert source.record["attempts"][-1]["key"] != "nr-source-1"
    assert research_source.replay(source.record) == ""
    assert len(source.harness.store.list_attempts("run-test")) == 2


def test_lost_response_after_commit_uses_the_exact_native_receipt(source, monkeypatch):
    source.seed()
    native = source.harness.command_service

    def submit(request):
        native.submit(request)
        raise TimeoutError("response lost")

    monkeypatch.setattr(formal_write_runtime, "get_command_service", lambda: SimpleNamespace(submit=submit))
    assert research_source.replay(source.record) == ""
    assert research_source.replay(source.record) == ""
    assert len(source.harness.store.list_attempts("run-test")) == 2


def test_external_new_failure_cannot_replace_the_durable_replay_anchor(source):
    source.seed(2)
    source.record["_recoveryReplayAfter"] = "nr-source-1"
    assert research_source.replay(source.record) == "source_advanced"
    assert len(source.harness.store.list_attempts("run-test")) == 2


def test_pending_human_task_excludes_repair_and_replay(source):
    source.seed()
    source.harness.store.submit(lambda uow: uow.repository.insert_human_task(
        task_id="human-1", run_id="run-test", node_run_id="nr-source-1",
        handoff_id=None, task_kind="review", prompt_json='{"text":"private"}',
        created_at_ms=1750000000000,
    ), force_flush=True).result(timeout=10)
    assert research_source.observe(source.record)["reason"] == "source_human_required"
    assert research_source.replay(source.record) == "source_human_required"


def test_run_level_human_required_problem_is_not_hidden_by_retryable_attempt(source):
    source.seed()
    source.harness.store.submit(lambda uow: uow.repository.execute(
        "UPDATE workflow_runs SET blocked_problem_json = ? WHERE run_id = ?",
        (json.dumps({"code": "budget_exceeded"}), "run-test"),
    ), force_flush=True).result(timeout=10)
    assert research_source.observe(source.record)["reason"] == "source_human_required"
    assert research_source.replay(source.record) == "source_human_required"


def test_replay_rechecks_limits_even_after_observing_available_budget(source):
    source.seed()
    assert not research_source.observe(source.record)["retryExhausted"]
    source.harness.store.submit(lambda uow: uow.repository.execute(
        "UPDATE workflow_runs SET safety_limits_json = ? WHERE run_id = ?",
        (json.dumps({"maxRetries": 0, "autoRetries": 2}), "run-test"),
    ), force_flush=True).result(timeout=10)
    assert research_source.replay(source.record) == "source_retry_budget_exhausted"
    assert len(source.harness.store.list_attempts("run-test")) == 1


def test_malformed_native_budget_never_grants_replay(source):
    source.seed()
    source.harness.store.submit(lambda uow: uow.repository.execute(
        "UPDATE workflow_runs SET safety_limits_json = ? WHERE run_id = ?",
        (json.dumps({"maxRetries": True}), "run-test"),
    ), force_flush=True).result(timeout=10)
    snapshot = research_source.observe(source.record)
    assert not snapshot["eligible"] and not snapshot["retryExhausted"]
    assert research_source.replay(source.record) == "source_retry_budget_unavailable"


def test_budget_gate_reads_fresh_native_limits_without_extending_them(source):
    source.seed(3)
    assert research_source.replay(source.record) == "source_retry_budget_exhausted"
    assert len(source.harness.store.list_attempts("run-test")) == 3
    assert source.harness.store.get_run("run-test").run_version == 1
    assert json.loads(source.harness.store.get_run("run-test").safety_limits_json)["autoRetries"] == 2


@pytest.mark.parametrize("key", ["maxRetries", "autoRetries"])
def test_launch_budget_is_authoritative_when_operator_extension_is_empty(source, key):
    source.seed(3)
    source.harness.store.submit(lambda uow: uow.repository.execute(
        "UPDATE workflow_runs SET input_snapshot_json = ?, safety_limits_json = '{}' WHERE run_id = ?",
        (json.dumps({"budgetPolicy": {key: 2}}), "run-test"),
    ), force_flush=True).result(timeout=10)
    assert research_source.observe(source.record)["eligible"]
    assert research_source.observe(source.record)["retryExhausted"]
    assert research_source.replay(source.record) == "source_retry_budget_exhausted"


def test_operator_extension_can_widen_but_not_shrink_frozen_retry_policy(source):
    source.seed(3)
    def limits(extension):
        source.harness.store.submit(lambda uow: uow.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json = ?, safety_limits_json = ? WHERE run_id = ?",
            (json.dumps({"budgetPolicy": {"maxRetries": 2}}), json.dumps({"maxRetries": extension}), "run-test"),
        ), force_flush=True).result(timeout=10)
    limits(1)
    assert research_source.observe(source.record)["retryExhausted"]
    limits(4)
    assert not research_source.observe(source.record)["retryExhausted"]
    assert json.loads(source.harness.store.get_run("run-test").input_snapshot_json)["budgetPolicy"]["maxRetries"] == 2


def test_infrastructure_history_is_not_charged_as_business_retries(source):
    source.seed(3, code="external_task_interrupted")
    assert not research_source.observe(source.record)["retryExhausted"]
    assert research_source.replay(source.record) == ""


def test_default_unknown_side_effects_and_revoked_binding_block_replay(source, monkeypatch):
    source.seed()
    source.record["flow"]["failureRecovery"].pop("replaySafety")
    assert research_source.replay(source.record) == "side_effects_unknown"
    source.record["flow"]["failureRecovery"]["replaySafety"] = "idempotent"
    monkeypatch.setattr(binding, "authorization_reason", lambda *args: "recovery_authorization_revoked_or_changed")
    assert research_source.replay(source.record) == "recovery_authorization_revoked_or_changed"


def test_native_readiness_refusal_is_not_reclassified_as_infrastructure(source, monkeypatch):
    from tests._support.readiness_fakes import StubNotReadyReadiness

    source.seed()
    monkeypatch.setattr(source.harness.command_service, "_readiness", StubNotReadyReadiness(["budget_safety_limit_reached"]))
    assert research_source.replay(source.record) == "source_node_not_ready"
    assert len(source.harness.store.list_attempts("run-test")) == 1
    assert source.harness.store.get_run("run-test").run_version == 1


@pytest.mark.parametrize("status,expected", [("succeeded", "completed"), ("cancelled", "stopped")])
def test_native_success_and_cancellation_are_observed_without_replay(source, status, expected):
    source.seed(status=status)
    assert research_source.observe(source.record)["status"] == expected
    assert research_source.replay(source.record) in {"source_step_succeeded", "source_stopped"}
    assert len(source.harness.store.list_attempts("run-test")) == 1


def test_version_change_between_snapshot_and_submit_refuses_replay(source, monkeypatch):
    source.seed()
    native = source.harness.command_service

    def submit(request):
        source.harness.store.submit(lambda uow: uow.repository.bump_run_version(
            "run-test", "research-team", 1, 0, 1750000000001), force_flush=True).result(timeout=10)
        return native.submit(request)

    monkeypatch.setattr(formal_write_runtime, "get_command_service", lambda: SimpleNamespace(submit=submit))
    assert research_source.replay(source.record) == "source_advanced"
    assert len(source.harness.store.list_attempts("run-test")) == 1
