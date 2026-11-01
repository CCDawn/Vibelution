"""Operator cancellation crosses ownership only with a real privileged principal."""
from __future__ import annotations

import dataclasses
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from core.web.services.external_agent.service import ExternalAgentAccessError, ExternalAgentConflictError
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests.test_external_agent_task_service import FakeRuntime, _service


@pytest.fixture
def env(tmp_path):
    runtime = FakeRuntime()
    service = _service(tmp_path / "external_agents", runtime)
    started = service.start_task(owner_id="original-owner-capability", adapter_connection_id="connection-a",
        capabilities=set(), agent_id="coder", task="SECRET original task body", permission_profile="read_only",
        client_request_id="owner-original-request", title="", runtime_revision="runtime-a")
    record = service.store.get_task(started["taskId"])
    return SimpleNamespace(service=service, runtime=runtime, record=record,
                           path=service.store.task_path(record["taskId"]))


@pytest.mark.parametrize("roles", [None, (), ("agent",), ("reader",)])
def test_cross_owner_cancel_denies_missing_or_unprivileged_operator_without_writes(env, roles):
    before, event_count = env.path.read_bytes(), len(env.runtime.events)
    if roles is None:
        with pytest.raises(ExternalAgentAccessError) as error:
            env.service.operator_cancel_task(task_id=env.record["taskId"], expected_revision=env.record["revision"])
    else:
        with server_operator_scope("real-server-reader", roles=roles):
            with pytest.raises(ExternalAgentAccessError) as error:
                env.service.operator_cancel_task(task_id=env.record["taskId"], expected_revision=env.record["revision"])
    assert error.value.code == "COMMAND_FORBIDDEN"
    assert env.path.read_bytes() == before and env.runtime.stop_calls == []
    assert len(env.runtime.events) == event_count


def test_operator_cancel_keeps_original_owner_and_waits_for_actual_stop_confirmation(env):
    with pytest.raises(ExternalAgentAccessError) as denied:
        env.service.cancel_task(owner_id="different-owner", task_id=env.record["taskId"])
    assert denied.value.code == "TASK_NOT_FOUND"
    with server_operator_scope("actual-human-operator", roles=("operator",)):
        first = env.service.operator_cancel_task(task_id=env.record["taskId"], expected_revision=env.record["revision"])
        assert first["status"] == "stop_unconfirmed" and first["accepted"] is True
        assert first["stopRequested"] is True
        assert env.runtime.stop_calls == [(env.record["sessionId"], env.record["turnId"])]
        assert env.service.store.get_task(env.record["taskId"])["completedAt"] is None
        env.runtime.details[env.record["sessionId"]]["phase"] = "stopped"
        second = env.service.operator_cancel_task(task_id=env.record["taskId"], expected_revision=first["revision"])
        assert second["status"] == "cancelled" and second["accepted"] is True
        assert len(env.runtime.stop_calls) == 1
        settled = env.service.operator_cancel_task(task_id=env.record["taskId"], expected_revision=second["revision"])
        assert settled["accepted"] is False and settled["stopRequested"] is False
    latest = env.service.store.get_task(env.record["taskId"])
    assert latest["ownerSubjectHash"] == env.record["ownerSubjectHash"]
    assert set(first) == {"taskId", "agentId", "sessionId", "status", "revision", "accepted", "stopRequested"}
    assert "SECRET" not in json.dumps([first, second, settled])
    audit = [event["kwargs"]["fields"] for event in env.runtime.events
             if event["args"][-1] == "external_agent.task.operator_cancel_requested"]
    assert audit and all(event["operatorId"] == "actual-human-operator" for event in audit)
    assert all(event["operatorReasonCode"] == "operator_cancel_requested" for event in audit)
    with pytest.raises(ExternalAgentAccessError):
        env.service.cancel_task(owner_id="different-owner", task_id=env.record["taskId"])
    assert env.service.cancel_task(owner_id="original-owner-capability", task_id=env.record["taskId"])["status"] == "cancelled"


@pytest.mark.parametrize("revision,code", [(0, "INVALID_INPUT"), (True, "INVALID_INPUT"),
                                         ("1", "INVALID_INPUT"), (-1, "INVALID_INPUT"), (999, "TASK_REVISION_CONFLICT")])
def test_operator_revision_rejection_has_no_stop_or_record_write(env, revision, code):
    before = env.path.read_bytes()
    with server_operator_scope("human-admin", roles=("admin",)):
        with pytest.raises(ExternalAgentConflictError) as error:
            env.service.operator_cancel_task(task_id=env.record["taskId"], expected_revision=revision)
    assert error.value.code == code
    assert env.path.read_bytes() == before and env.runtime.stop_calls == []


def test_native_stop_failure_remains_unconfirmed_without_inventing_an_ack(env):
    def broken_stop(*args, **kwargs):
        raise OSError("SECRET private native error")
    env.service.dependencies = dataclasses.replace(env.service.dependencies, stop_turn=broken_stop)
    with server_operator_scope("human-admin", roles=("operator",)):
        result = env.service.operator_cancel_task(task_id=env.record["taskId"], expected_revision=env.record["revision"])
    assert result["status"] == "stop_unconfirmed" and result["accepted"] is True
    assert result["stopRequested"] is False
    assert env.service.store.get_task(env.record["taskId"])["completedAt"] is None
    assert "SECRET" not in json.dumps(result)


def test_missing_session_detail_cannot_confirm_operator_cancellation(env):
    env.runtime.details.pop(env.record["sessionId"])
    env.service.dependencies = dataclasses.replace(env.service.dependencies, stop_turn=lambda *args, **kwargs: {})
    with server_operator_scope("human-admin", roles=("operator",)):
        result = env.service.operator_cancel_task(task_id=env.record["taskId"], expected_revision=env.record["revision"])
    assert result["status"] == "stop_unconfirmed" and result["accepted"] is True
    assert env.service.store.get_task(env.record["taskId"])["completedAt"] is None


def test_operator_revision_lock_serializes_two_controls_on_the_same_native_task(env):
    ready = threading.Barrier(2)
    def cancel():
        with server_operator_scope("human-admin", roles=("operator",)):
            ready.wait(timeout=3)
            try:
                return env.service.operator_cancel_task(task_id=env.record["taskId"], expected_revision=env.record["revision"])
            except ExternalAgentConflictError as error:
                return error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(cancel) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]
    assert sum(isinstance(result, dict) for result in results) == 1
    assert "TASK_REVISION_CONFLICT" in results and len(env.runtime.stop_calls) == 1


def test_operator_entry_cannot_accept_forged_actor_owner_or_reason(env):
    before = env.path.read_bytes()
    with server_operator_scope("human-admin", roles=("operator",)):
        with pytest.raises(TypeError):
            env.service.operator_cancel_task(task_id=env.record["taskId"], expected_revision=env.record["revision"],
                owner_id="original-owner-capability", operator_id="forged-admin", reason_code="SECRET user body")
    assert env.path.read_bytes() == before


def test_operator_audit_reason_does_not_echo_an_existing_terminal_record_reason(env):
    record = env.service.store.transition(env.record["taskId"], status="failed",
        expected_revision=env.record["revision"], reason_code="SECRET untrusted legacy reason")
    with server_operator_scope("actual-human", roles=("operator",)):
        result = env.service.operator_cancel_task(task_id=record["taskId"], expected_revision=record["revision"])
    assert result["accepted"] is False
    audit = env.runtime.events[-1]["kwargs"]["fields"]
    assert audit["reasonCode"] == "operator_cancel_requested" and audit["operatorId"] == "actual-human"
    assert "SECRET" not in json.dumps([result, audit])


@pytest.mark.parametrize("detail", [{}, {"phase": "unknown"}, {"currentPhase": "running"},
                                  {"currentPhase": "running", "running": False}, {"running": 0}])
def test_operator_cancel_needs_explicit_native_terminal_evidence(env, detail):
    env.runtime.details[env.record["sessionId"]] = detail
    with server_operator_scope("human-admin", roles=("operator",)):
        result = env.service.operator_cancel_task(task_id=env.record["taskId"], expected_revision=env.record["revision"])
    assert result["status"] == "stop_unconfirmed"
    assert env.service.store.get_task(env.record["taskId"])["completedAt"] is None
    ordinary_retry = env.service.cancel_task(owner_id="original-owner-capability", task_id=env.record["taskId"])
    assert ordinary_retry["status"] == "stop_unconfirmed"
    # The original resident refresh path also consumes the persisted contract.
    latest, _ = env.service._refresh(env.service.store.get_task(env.record["taskId"]))
    assert latest["status"] == "stop_unconfirmed" and latest["completedAt"] is None
    assert latest["operatorStopConfirmation"] is True
