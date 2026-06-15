import copy
import json
import threading
from pathlib import Path

import pytest

from core.web.services import supervised_control_service as service
from core.web.services import supervised_conversation_harness_adapter as conversation_adapter
from tests.helpers.chat_turn_harness import wait_for_condition

pytestmark = pytest.mark.serial


def _terminal_bench_environment_contract() -> dict:
    return {
        "kind": "terminal_bench_task_environment",
        "preflight": {"required": True, "strategy": "path_alias"},
        "required_paths": [],
        "official_verifier": {
            "status": "harbor_pending",
            "requires": ["uv", "docker daemon"],
        },
        "official_score_available": False,
    }


def _write_custom_terminal_bench_bundle(tmp_path: Path, bundle_name: str = "terminal_bench_core_v1") -> Path:
    contract = _terminal_bench_environment_contract()
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / f"{bundle_name}.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps(
            {
                "bundle_name": bundle_name,
                "dataset": {
                    "official_verifier_status": "harbor_pending",
                    "evaluation_mode": "custom_harness",
                    "score_label": "Vibelution custom score",
                    "environment_contract": copy.deepcopy(contract),
                },
                "cases": [
                    {
                        "case_id": "tb2",
                        "official_runner": "harbor_pending",
                        "requires_official_task_environment": False,
                        "environment_contract": copy.deepcopy(contract),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return bundle_path


@pytest.fixture(autouse=True)
def reset_supervised_run_state(monkeypatch: pytest.MonkeyPatch):
    manager_store: dict[str, dict[str, dict]] = {"self": {}, "supervised": {}}
    manager_index: dict[str, dict[str, str]] = {
        "self": {"activeRunId": "", "latestRunId": ""},
        "supervised": {"activeRunId": "", "latestRunId": ""},
    }

    def fake_persist_manager_run_snapshot(kind: str, snapshot: dict, *, active_run_id: str = "") -> dict:
        run_id = str(snapshot.get("runId") or "").strip()
        payload = copy.deepcopy(snapshot)
        manager_store.setdefault(kind, {})[run_id] = payload
        manager_index.setdefault(kind, {"activeRunId": "", "latestRunId": ""})
        manager_index[kind]["activeRunId"] = str(active_run_id or "").strip()
        manager_index[kind]["latestRunId"] = run_id
        return copy.deepcopy(payload)

    def fake_load_manager_run_snapshot(kind: str, run_id: str) -> dict | None:
        payload = manager_store.get(kind, {}).get(str(run_id or "").strip())
        return copy.deepcopy(payload) if payload is not None else None

    def fake_load_manager_active_run_snapshot(kind: str) -> dict | None:
        active_run_id = manager_index.get(kind, {}).get("activeRunId", "")
        return fake_load_manager_run_snapshot(kind, active_run_id)

    def fake_delete_manager_run_snapshot(kind: str, run_id: str) -> dict:
        normalized = str(run_id or "").strip()
        store = manager_store.setdefault(kind, {})
        index = manager_index.setdefault(kind, {"activeRunId": "", "latestRunId": ""})
        existed = normalized in store
        if existed:
            store.pop(normalized, None)
        cleared_active = index.get("activeRunId") == normalized
        cleared_latest = index.get("latestRunId") == normalized
        if cleared_active:
            index["activeRunId"] = ""
        if cleared_latest:
            candidates = list(store.values())
            if candidates:
                latest = max(
                    candidates,
                    key=lambda item: (
                        str(item.get("updatedAt") or ""),
                        str(item.get("startedAt") or ""),
                        str(item.get("runId") or ""),
                    ),
                )
                index["latestRunId"] = str(latest.get("runId") or "")
            else:
                index["latestRunId"] = ""
        return {
            "deleted": existed,
            "runId": normalized,
            "clearedActive": cleared_active,
            "clearedLatest": cleared_latest,
            "activeRunId": index.get("activeRunId", ""),
            "latestRunId": index.get("latestRunId", ""),
        }

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(service, "persist_manager_run_snapshot", fake_persist_manager_run_snapshot)
    monkeypatch.setattr(service, "load_manager_run_snapshot", fake_load_manager_run_snapshot)
    monkeypatch.setattr(service, "load_manager_active_run_snapshot", fake_load_manager_active_run_snapshot)
    monkeypatch.setattr(service, "delete_manager_run_snapshot", fake_delete_manager_run_snapshot)
    with service._RUN_STATE_LOCK:
        service._RUN_STATES.clear()
        service._RUN_CONTROLLERS.clear()
        service._ACTIVE_RUN_ID = None
    with service._RUN_SUBSCRIBERS_LOCK:
        service._RUN_SUBSCRIBERS.clear()
    yield
    with service._RUN_STATE_LOCK:
        service._RUN_STATES.clear()
        service._RUN_CONTROLLERS.clear()
        service._ACTIVE_RUN_ID = None
    with service._RUN_SUBSCRIBERS_LOCK:
        service._RUN_SUBSCRIBERS.clear()


def _seed_running_run() -> str:
    context = {
        "runId": "web-supervised-test",
        "lang": "en",
        "sourceKind": "bundle",
        "datasetName": "",
        "datasetLimit": None,
        "bundleName": "manual_bundle",
        "keepWorktree": False,
        "startedAt": "2026-05-18T12:00:00Z",
    }
    state = service._initial_run_state(context)
    state["status"] = "running"
    state["currentPhase"] = "running"
    state["runtimeStatus"] = "running"
    state["sessionId"] = "supervised_session"
    state["caseTotal"] = 2
    state["currentCaseIndex"] = 1
    state["currentCaseId"] = "case_1"
    state["currentRole"] = "candidate"
    with service._RUN_STATE_LOCK:
        service._RUN_STATES[context["runId"]] = state
        service._RUN_CONTROLLERS[context["runId"]] = service._SupervisedRunController()
        service._ACTIVE_RUN_ID = context["runId"]
    return context["runId"]


def _valid_agent_bindings() -> dict[str, dict[str, object]]:
    return {
        "baseline": {
            "agentId": "a-base",
            "displayName": "Baseline",
            "dialogueModelId": "model-xiaomi-baseline",
            "llmBindings": {"dialogue": {"modelId": "model-xiaomi-baseline"}},
            "role": "baseline",
        },
        "candidate": {
            "agentId": "a-candidate",
            "displayName": "Candidate",
            "dialogueModelId": "model-xiaomi-candidate",
            "llmBindings": {"dialogue": {"modelId": "model-xiaomi-candidate"}},
            "role": "candidate",
        },
    }


def test_supervised_checkpoint_pauses_then_resumes():
    run_id = _seed_running_run()
    result = {"error": None}

    pause_snapshot = service.request_pause_supervised_run(run_id)
    assert pause_snapshot["pauseRequested"] is True
    assert pause_snapshot["status"] == "running"
    assert pause_snapshot["currentPhase"] == "pause_requested"

    thread = threading.Thread(
        target=lambda: _checkpoint_in_thread(run_id, result),
        daemon=True,
    )
    thread.start()

    wait_for_condition(
        "supervised run paused",
        timeout_s=1.0,
        predicate=lambda: service.get_supervised_run_snapshot(run_id)["status"] == "paused",
    )
    paused_snapshot = service.get_supervised_run_snapshot(run_id)
    assert paused_snapshot["currentPhase"] == "paused"
    assert paused_snapshot["runtimeStatus"] == "paused"

    resume_snapshot = service.request_resume_supervised_run(run_id)
    assert resume_snapshot["pauseRequested"] is False

    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert result["error"] is None
    running_snapshot = service.get_supervised_run_snapshot(run_id)
    assert running_snapshot["status"] == "running"


def test_supervised_checkpoint_stops_at_safe_boundary():
    run_id = _seed_running_run()

    stop_snapshot = service.request_stop_supervised_run(run_id)
    assert stop_snapshot["status"] == "stopping"
    assert stop_snapshot["stopRequested"] is True

    with pytest.raises(service._SupervisedRunInterrupted):
        service._checkpoint_supervised_run(run_id, {"phase": "case_boundary", "case_id": "case_1"})

    final_snapshot = service.get_supervised_run_snapshot(run_id)
    assert final_snapshot["status"] == "cancelled"
    assert service.get_active_supervised_run() is None


def test_supervised_checkpoint_stops_at_role_boundary_before_next_role():
    run_id = _seed_running_run()

    stop_snapshot = service.request_stop_supervised_run(run_id)
    assert stop_snapshot["status"] == "stopping"
    assert stop_snapshot["stopRequested"] is True

    with pytest.raises(service._SupervisedRunInterrupted):
        service._checkpoint_supervised_run(
            run_id,
            {"phase": "role_boundary", "case_id": "case_1", "role": "baseline"},
        )

    final_snapshot = service.get_supervised_run_snapshot(run_id)
    assert final_snapshot["status"] == "cancelled"
    assert final_snapshot["currentRole"] == "candidate"
    assert service.get_active_supervised_run() is None


def test_request_stop_supervised_run_closes_file_only_queued_run(monkeypatch):
    run_id = "web-supervised-file-only-queued"
    persisted: dict[str, object] = {}
    stored = {
        "runId": run_id,
        "status": "queued",
        "currentPhase": "queued",
        "runtimeStatus": "queued",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
        "finishedAt": "",
        "latestMessage": "queued",
        "currentTask": "queued",
        "pauseRequested": False,
        "pauseRequestedAt": "",
        "stopRequested": False,
        "stopRequestedAt": "",
        "eventTail": [],
    }

    monkeypatch.setattr(
        service,
        "load_manager_run_snapshot",
        lambda kind, loaded_run_id: copy.deepcopy(stored) if kind == "supervised" and loaded_run_id == run_id else None,
    )

    def fake_persist(kind: str, payload: dict, *, active_run_id: str = "") -> dict:
        persisted["kind"] = kind
        persisted["payload"] = copy.deepcopy(payload)
        persisted["active_run_id"] = active_run_id
        return copy.deepcopy(payload)

    monkeypatch.setattr(service, "persist_manager_run_snapshot", fake_persist)

    snapshot = service.request_stop_supervised_run(run_id)

    assert snapshot["status"] == "cancelled"
    assert snapshot["currentPhase"] == "cancelled"
    assert snapshot["runtimeStatus"] == "idle"
    assert snapshot["stopRequested"] is True
    assert snapshot["finishedAt"]
    assert persisted["kind"] == "supervised"
    assert persisted["active_run_id"] == ""
    assert persisted["payload"]["status"] == "cancelled"


def test_request_stop_supervised_run_closes_file_only_running_run(monkeypatch):
    run_id = "web-supervised-file-only-running"
    persisted: dict[str, object] = {}
    stored = {
        "runId": run_id,
        "status": "running",
        "currentPhase": "running",
        "runtimeStatus": "running",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
        "finishedAt": "",
        "latestMessage": "running",
        "currentTask": "running",
        "pauseRequested": False,
        "pauseRequestedAt": "",
        "stopRequested": False,
        "stopRequestedAt": "",
        "eventTail": [],
    }

    monkeypatch.setattr(
        service,
        "load_manager_run_snapshot",
        lambda kind, loaded_run_id: copy.deepcopy(stored) if kind == "supervised" and loaded_run_id == run_id else None,
    )

    def fake_persist(kind: str, payload: dict, *, active_run_id: str = "") -> dict:
        persisted["kind"] = kind
        persisted["payload"] = copy.deepcopy(payload)
        persisted["active_run_id"] = active_run_id
        return copy.deepcopy(payload)

    monkeypatch.setattr(service, "persist_manager_run_snapshot", fake_persist)

    snapshot = service.request_stop_supervised_run(run_id)

    assert snapshot["status"] == "cancelled"
    assert snapshot["runtimeStatus"] == "idle"
    assert snapshot["stopRequested"] is True
    assert snapshot["finishedAt"]
    assert persisted["active_run_id"] == ""
    assert persisted["payload"]["status"] == "cancelled"


def test_delete_supervised_run_snapshot_clears_file_only_queued_run(monkeypatch):
    run_id = "web-supervised-file-only-queued"
    stored = {
        "runId": run_id,
        "status": "queued",
        "currentPhase": "queued",
        "runtimeStatus": "queued",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
        "finishedAt": "",
        "latestMessage": "queued",
        "currentTask": "queued",
        "pauseRequested": False,
        "pauseRequestedAt": "",
        "stopRequested": False,
        "stopRequestedAt": "",
        "eventTail": [],
    }
    deleted: dict[str, object] = {}

    monkeypatch.setattr(
        service,
        "load_manager_run_snapshot",
        lambda kind, loaded_run_id: copy.deepcopy(stored) if kind == "supervised" and loaded_run_id == run_id else None,
    )

    def fake_delete(kind: str, loaded_run_id: str) -> dict:
        deleted["kind"] = kind
        deleted["run_id"] = loaded_run_id
        return {
            "deleted": True,
            "runId": loaded_run_id,
            "clearedActive": True,
            "clearedLatest": True,
            "activeRunId": "",
            "latestRunId": "",
        }

    monkeypatch.setattr(service, "delete_manager_run_snapshot", fake_delete)

    result = service.delete_supervised_run_snapshot(run_id)

    assert result["deleted"] is True
    assert result["runId"] == run_id
    assert result["clearedActive"] is True
    assert result["clearedLatest"] is True
    assert deleted == {"kind": "supervised", "run_id": run_id}


def test_delete_supervised_run_snapshot_clears_corrupt_index_only_run(monkeypatch):
    run_id = "web-supervised-corrupt-active"

    monkeypatch.setattr(service, "load_manager_run_snapshot", lambda kind, loaded_run_id: None)
    monkeypatch.setattr(
        service,
        "delete_manager_run_snapshot",
        lambda kind, loaded_run_id: {
            "deleted": False,
            "runId": loaded_run_id,
            "clearedActive": True,
            "clearedLatest": True,
            "activeRunId": "",
            "latestRunId": "",
        },
    )

    result = service.delete_supervised_run_snapshot(run_id)

    assert result["deleted"] is True
    assert result["runId"] == run_id
    assert result["activeRunId"] == ""
    assert result["latestRunId"] == ""


def test_delete_supervised_run_snapshot_rejects_running_run():
    run_id = _seed_running_run()

    with pytest.raises(service.SupervisedRunStateError):
        service.delete_supervised_run_snapshot(run_id)

    assert service.get_supervised_run_snapshot(run_id)["status"] == "running"


def test_delete_queued_supervised_run_prevents_background_execution(monkeypatch):
    run_id = "web-supervised-delete-before-start"
    context = {
        "runId": run_id,
        "lang": "en",
        "sourceKind": "bundle",
        "datasetName": "",
        "datasetLimit": None,
        "bundleName": "manual_bundle",
        "keepWorktree": False,
        "startedAt": "2026-05-18T12:00:00Z",
    }
    with service._RUN_STATE_LOCK:
        state = service._initial_run_state(context)
        service._RUN_STATES[run_id] = state
        service._RUN_CONTROLLERS[run_id] = service._SupervisedRunController()
        service._ACTIVE_RUN_ID = run_id
    service.persist_manager_run_snapshot("supervised", state, active_run_id=run_id)

    calls: list[str] = []
    monkeypatch.setattr(service, "run_workbench_session", lambda **kwargs: calls.append("ran"))

    result = service.delete_supervised_run_snapshot(run_id)
    service._run_supervised_session(context)

    assert result["deleted"] is True
    assert calls == []
    assert service.get_active_supervised_run() is None


def test_stop_requested_run_cancels_active_harness_without_waiting_for_checkpoint(monkeypatch):
    run_id = _seed_running_run()
    observed: dict[str, object] = {}

    def fake_run_workbench_session(**kwargs):
        observed["cancel_checker"] = kwargs.get("cancel_checker")
        service.request_stop_supervised_run(run_id)
        reason = kwargs["cancel_checker"]()
        observed["reason"] = reason
        raise service.SupervisedEvolutionCancelled(str(reason), session_id="cancelled_session")

    monkeypatch.setattr(service, "run_workbench_session", fake_run_workbench_session)

    service._run_supervised_session(
        {
            "runId": run_id,
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        }
    )

    snapshot = service.get_supervised_run_snapshot(run_id)
    assert callable(observed["cancel_checker"])
    assert observed["reason"]
    assert snapshot["status"] == "cancelled"
    assert snapshot["runtimeStatus"] == "idle"
    assert snapshot["decision"] == ""
    assert service.get_active_supervised_run() is None


def test_retry_supervised_run_starts_new_run_from_finished_decision(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    decision_path = tmp_path / "workspace" / "supervised_evolution" / "decisions" / "supervised_old.json"
    decision_path.parent.mkdir(parents=True)
    decision_path.write_text('{"baseline_runs":[],"candidate_runs":[]}', encoding="utf-8")
    source_run_id = "web-supervised-old"
    source_snapshot = {
        "runId": source_run_id,
        "status": "done",
        "currentPhase": "done",
        "runtimeStatus": "idle",
        "sourceKind": "dataset",
        "datasetName": "terminal_bench_smoke",
        "datasetLimit": 1,
        "bundleName": "terminal_bench_smoke_v1",
        "keepWorktree": False,
        "decisionPath": str(decision_path),
        "eventTail": [],
    }
    service.persist_manager_run_snapshot("supervised", source_snapshot, active_run_id="")
    monkeypatch.setattr(service, "supervised_agent_bindings", _valid_agent_bindings)
    monkeypatch.setattr(service, "_RUN_EXECUTOR", _ImmediateExecutor())
    observed: dict[str, object] = {}

    def fake_run_workbench_session(**kwargs):
        observed.update(kwargs)
        raise service.SupervisedEvolutionCancelled("stop after capture", session_id="retry_session")

    monkeypatch.setattr(service, "run_workbench_session", fake_run_workbench_session)

    snapshot = service.retry_supervised_run(source_run_id)

    assert snapshot["runId"] != source_run_id
    assert snapshot["retryOfRunId"] == source_run_id
    assert snapshot["resumeFromDecisionPath"] == str(decision_path)
    assert observed["resume_from_decision_path"] == decision_path
    assert observed["bundle_name"] == "terminal_bench_smoke_v1"
    assert observed["agent_bindings"]["baseline"]["agentId"] == "a-base"


def test_start_supervised_run_blocks_custom_terminal_bench_bundle_when_environment_preflight_fails(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    _write_custom_terminal_bench_bundle(tmp_path)
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(
        "core.evaluation.supervised_workbench.preflight_environment_contract",
        lambda *args, **kwargs: {
            "status": "missing_verifier_dependency",
            "available": False,
            "missing": [],
            "official_verifier": {
                "missing": [{"name": "docker daemon", "available": False}],
                "available": False,
            },
        },
    )

    with pytest.raises(service.SupervisedRunValidationError, match="docker daemon"):
        service.start_supervised_run(
            {
                "sourceKind": "bundle",
                "bundleName": "terminal_bench_core_v1",
                "mentalModelMode": "disabled",
            }
        )


def test_start_supervised_run_allows_custom_terminal_bench_bundle_when_environment_ready(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    _write_custom_terminal_bench_bundle(tmp_path)
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(service.shutil, "which", lambda name: None)
    monkeypatch.setattr(service, "_docker_daemon_available", lambda: False)
    monkeypatch.setattr(
        "core.evaluation.supervised_workbench.preflight_environment_contract",
        lambda *args, **kwargs: {
            "status": "available",
            "available": True,
            "missing": [],
            "official_verifier": {"missing": [], "available": True},
        },
    )
    monkeypatch.setattr(service, "supervised_agent_bindings", _valid_agent_bindings)
    monkeypatch.setattr(service, "_RUN_EXECUTOR", _ImmediateExecutor())
    calls: list[object] = []

    def fake_run_workbench_session(**kwargs):
        calls.append(kwargs)
        raise service.SupervisedEvolutionCancelled("stop after capture", session_id="custom_tb")

    monkeypatch.setattr(service, "run_workbench_session", fake_run_workbench_session)

    snapshot = service.start_supervised_run(
        {
            "sourceKind": "bundle",
            "bundleName": "terminal_bench_core_v1",
            "mentalModelMode": "disabled",
        }
    )

    assert snapshot["bundleName"] == "terminal_bench_core_v1"
    assert calls and calls[0]["bundle_name"] == "terminal_bench_core_v1"
    assert snapshot["mentalModelMode"] == "disabled"
    assert snapshot["mentalModelEnabled"] is False
    assert calls[0]["mental_model_mode"] == "disabled"
    assert callable(calls[0]["harness_runner"])


def test_conversation_harness_treats_completed_session_turn_as_success(monkeypatch, tmp_path):
    events: list[dict] = []
    captured_submit: dict[str, object] = {}

    monkeypatch.setattr(
        conversation_adapter,
        "create_supervised_agent_session",
        lambda **kwargs: {"id": "session-hidden", "sessionKind": "supervised", "hiddenFromIndex": True},
    )

    def fake_submit_session_message(session_id, prompt, **kwargs):
        captured_submit.update({"session_id": session_id, "prompt": prompt, **kwargs})
        return {"turnId": "turn-1"}

    monkeypatch.setattr(conversation_adapter, "submit_session_message", fake_submit_session_message)
    monkeypatch.setattr(
        conversation_adapter,
        "get_session_detail",
        lambda session_id: {
            "id": session_id,
            "lastTurnStatus": "completed",
            "updatedAt": "2026-06-11T00:00:03Z",
            "messages": [
                {"role": "user", "content": "inspect current state", "timestamp": "2026-06-11T00:00:01Z"},
                {
                    "role": "assistant",
                    "content": "state inspected",
                    "timestamp": "2026-06-11T00:00:03Z",
                    "thought": "inspect first",
                    "toolCalls": [{"name": "inspect_state", "status": "success"}],
                    "mentalSnapshot": {"mood": "focused"},
                },
            ],
        },
    )

    result = service._run_supervised_conversation_harness(
        repo_root=tmp_path,
        mode="single_turn",
        prompt="inspect current state",
        timeout_seconds=1,
        expect_restart=False,
        post_restart_observe_seconds=0,
        keep_worktree=False,
        scenario="strategy",
        agent_binding={"agentId": "agent-a", "role": "baseline"},
        mental_model_mode="enabled",
        mental_model_enabled=True,
        progress_callback=events.append,
    )

    assert result.status == "success"
    assert result.primary_returncode == 0
    assert result.agent_runtime_env["VIBELUTION_SUPERVISED_MENTAL_MODEL_MODE"] == "enabled"
    assert result.agent_runtime_env["VIBELUTION_SUPERVISED_MENTAL_MODEL_ENABLED"] == "true"
    assert captured_submit["message_source"] == "supervised_evolution"
    assert captured_submit["mental_model_enabled"] is True
    assert events[-1]["phase"] == "conversation_turn_finished"
    assert events[-1]["conversation_session_id"] == "session-hidden"
    assert events[-1]["conversation_turn_id"] == "turn-1"
    assert events[-1]["conversation_messages"][0]["id"] == "session-hidden-message-1"
    assert events[-1]["conversation_messages"][0]["role"] == "user"
    assert events[-1]["conversation_messages"][1]["thought"] == "inspect first"
    assert events[-1]["conversation_messages"][1]["toolCalls"][0]["name"] == "inspect_state"
    assert events[-1]["conversation_messages"][1]["mentalSnapshot"]["mood"] == "focused"


def test_conversation_harness_returns_cancelled_after_stop_grace(monkeypatch, tmp_path):
    events: list[dict] = []
    stopped_sessions: list[str] = []
    clock = {"now": 0.0}

    monkeypatch.setattr(
        conversation_adapter,
        "create_supervised_agent_session",
        lambda **kwargs: {"id": "session-hidden", "sessionKind": "supervised", "hiddenFromIndex": True},
    )
    monkeypatch.setattr(conversation_adapter, "submit_session_message", lambda *args, **kwargs: {"turnId": "turn-1"})
    monkeypatch.setattr(
        conversation_adapter,
        "get_session_detail",
        lambda session_id: {
            "id": session_id,
            "lastTurnStatus": "running",
            "updatedAt": "2026-06-11T00:00:03Z",
            "messages": [
                {"role": "user", "content": "inspect current state", "timestamp": "2026-06-11T00:00:01Z"},
            ],
        },
    )
    monkeypatch.setattr(conversation_adapter, "request_stop_session_turn", lambda session_id: stopped_sessions.append(session_id))
    monkeypatch.setattr(conversation_adapter, "CONVERSATION_HARNESS_CANCEL_GRACE_SECONDS", 1.0)
    monkeypatch.setattr(conversation_adapter.time, "monotonic", lambda: clock["now"])

    def fake_sleep(seconds: float) -> None:
        clock["now"] += float(seconds)

    monkeypatch.setattr(conversation_adapter.time, "sleep", fake_sleep)

    result = service._run_supervised_conversation_harness(
        repo_root=tmp_path,
        mode="single_turn",
        prompt="inspect current state",
        timeout_seconds=60,
        expect_restart=False,
        post_restart_observe_seconds=0,
        keep_worktree=False,
        scenario="strategy",
        agent_binding={"agentId": "agent-a", "role": "baseline"},
        mental_model_mode="enabled",
        mental_model_enabled=True,
        progress_callback=events.append,
        cancel_checker=lambda: "operator stop",
    )

    assert result.status == "cancelled"
    assert result.reason == "operator stop"
    assert result.primary_returncode is None
    assert stopped_sessions == ["session-hidden"]
    assert events[-1]["phase"] == "conversation_cancelled"
    assert events[-1]["mental_model_mode"] == "enabled"
    assert events[-1]["mental_model_enabled"] is True


def test_start_supervised_run_blocks_incomplete_agent_model_binding(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text('{"bundle_name":"manual_bundle","cases":[]}', encoding="utf-8")
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(
        service,
        "supervised_agent_bindings",
        lambda: {"baseline": {"agentId": "a-base", "role": "baseline"}},
    )

    with pytest.raises(service.SupervisedRunValidationError, match="baseline"):
        service.start_supervised_run({"sourceKind": "bundle", "bundleName": "manual_bundle"})


def test_start_supervised_run_blocks_official_terminal_bench_bundle_when_requested(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "terminal_bench_core_v1.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        (
            '{"bundle_name":"terminal_bench_core_v1",'
            '"dataset":{"official_verifier_status":"harbor_pending","evaluation_mode":"custom_harness"},'
            '"cases":[{"case_id":"tb2","official_runner":"harbor_pending"}]}'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(service.shutil, "which", lambda name: None)
    monkeypatch.setattr(service, "_docker_daemon_available", lambda: False)

    with pytest.raises(service.SupervisedRunValidationError) as exc:
        service.start_supervised_run(
            {
                "sourceKind": "bundle",
                "bundleName": "terminal_bench_core_v1",
                "evaluationMode": "official",
            }
        )

    assert "Harbor/Docker" in str(exc.value)
    assert "/app sandbox" in str(exc.value)


def test_retry_supervised_run_allows_custom_terminal_bench_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    decision_path = tmp_path / "workspace" / "supervised_evolution" / "decisions" / "supervised_old.json"
    decision_path.parent.mkdir(parents=True)
    decision_path.write_text('{"baseline_runs":[],"candidate_runs":[]}', encoding="utf-8")
    _write_custom_terminal_bench_bundle(tmp_path)
    source_run_id = "web-supervised-old"
    service.persist_manager_run_snapshot(
        "supervised",
        {
            "runId": source_run_id,
            "status": "failed",
            "sourceKind": "bundle",
            "bundleName": "terminal_bench_core_v1",
            "decisionPath": str(decision_path),
        },
        active_run_id="",
    )
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(service.shutil, "which", lambda name: None)
    monkeypatch.setattr(service, "_docker_daemon_available", lambda: False)
    monkeypatch.setattr(
        "core.evaluation.supervised_workbench.preflight_environment_contract",
        lambda *args, **kwargs: {
            "status": "available",
            "available": True,
            "missing": [],
            "official_verifier": {"missing": [], "available": True},
        },
    )
    monkeypatch.setattr(service, "supervised_agent_bindings", _valid_agent_bindings)
    monkeypatch.setattr(service, "_RUN_EXECUTOR", _ImmediateExecutor())
    calls: list[object] = []

    def fake_run_workbench_session(**kwargs):
        calls.append(kwargs)
        raise service.SupervisedEvolutionCancelled("stop after capture", session_id="custom_tb_retry")

    monkeypatch.setattr(service, "run_workbench_session", fake_run_workbench_session)

    snapshot = service.retry_supervised_run(source_run_id)

    assert snapshot["retryOfRunId"] == source_run_id
    assert calls and calls[0]["bundle_name"] == "terminal_bench_core_v1"


def test_handle_progress_event_updates_current_case_io_snapshot():
    run_id = _seed_running_run()

    service._handle_progress_event(
        run_id,
        {
            "event": "role_start",
            "case_index": 1,
            "case_total": 2,
            "case_id": "case_1",
            "role": "candidate",
            "scenario": "transaction",
            "mode": "single_turn",
            "prompt": "compare the candidate behavior",
        },
    )
    service._handle_progress_event(
        run_id,
        {
            "event": "role_live",
            "case_index": 1,
            "case_total": 2,
            "case_id": "case_1",
            "role": "candidate",
            "scenario": "transaction",
            "mode": "single_turn",
            "prompt": "compare the candidate behavior",
            "conversation_path": "log_info/conversation_case_1.jsonl",
            "conversation_session_id": "session-hidden-case-1",
            "conversation_turn_id": "turn-case-1",
            "latest_input": "compare the candidate behavior",
            "latest_output": "assistant produced a live update",
            "latest_output_kind": "assistant",
            "latest_output_label": "assistant",
            "updated_at": "2026-05-19T12:00:03Z",
            "transcript": [
                {
                    "timestamp": "2026-05-19T12:00:01Z",
                    "kind": "input",
                    "label": "prompt",
                    "content": "compare the candidate behavior",
                },
                {
                    "timestamp": "2026-05-19T12:00:02Z",
                    "kind": "error",
                    "label": "llm_error",
                    "content": "network_error: [SSL: UNEXPECTED_EOF_WHILE_READING]",
                    "status": "recovered",
                },
                {
                    "timestamp": "2026-05-19T12:00:03Z",
                    "kind": "assistant",
                    "label": "assistant",
                    "content": "assistant produced a live update",
                },
            ],
            "conversation_messages": [
                {
                    "id": "message-user-1",
                    "role": "user",
                    "content": "compare the candidate behavior",
                    "timestamp": "2026-05-19T12:00:01Z",
                },
                {
                    "id": "message-assistant-1",
                    "role": "assistant",
                    "content": "assistant produced a live update",
                    "timestamp": "2026-05-19T12:00:03Z",
                    "thought": "compare baseline and candidate",
                    "toolCalls": [{"name": "inspect_case", "status": "success"}],
                },
            ],
        },
    )

    snapshot = service.get_supervised_run_snapshot(run_id)

    assert snapshot["currentCasePrompt"] == "compare the candidate behavior"
    assert snapshot["currentCaseScenario"] == "transaction"
    assert snapshot["currentCaseMode"] == "single_turn"
    assert snapshot["currentCaseIo"]["latestOutput"] == "assistant produced a live update"
    assert snapshot["currentCaseIo"]["latestOutputKind"] == "assistant"
    assert snapshot["currentCaseIo"]["conversationSessionId"] == "session-hidden-case-1"
    assert snapshot["currentCaseIo"]["conversationTurnId"] == "turn-case-1"
    assert snapshot["currentCaseIo"]["conversationMessages"][0]["role"] == "user"
    assert snapshot["currentCaseIo"]["conversationMessages"][1]["thought"] == "compare baseline and candidate"
    assert snapshot["currentCaseIo"]["conversationMessages"][1]["toolCalls"][0]["name"] == "inspect_case"
    assert snapshot["currentCaseIo"]["transcript"][0]["kind"] == "input"
    assert snapshot["currentCaseIo"]["transcript"][1]["status"] == "recovered"
    assert snapshot["latestMessage"] == "assistant produced a live update"
    assert snapshot["eventTail"][-1]["event"] == "role_start"


def test_handle_progress_event_records_environment_preflight_live_event():
    run_id = _seed_running_run()

    service._handle_progress_event(
        run_id,
        {
            "event": "role_live",
            "case_index": 1,
            "case_total": 1,
            "case_id": "tb2",
            "role": "baseline",
            "scenario": "transaction",
            "mode": "multi_step_react",
            "prompt": "run tb case",
            "phase": "environment_preflight",
            "environment_contract_kind": "terminal_bench_task_environment",
            "environment_preflight": {
                "status": "missing_verifier_dependency",
                "available": False,
                "missing": [],
                "official_verifier": {
                    "missing": [
                        {"name": "docker", "available": False, "evidence": "not_found"},
                    ],
                },
            },
        },
    )

    snapshot = service.get_supervised_run_snapshot(run_id)

    assert snapshot["eventTail"][-1]["event"] == "role_live"
    assert snapshot["eventTail"][-1]["phase"] == "environment_preflight"
    assert snapshot["eventTail"][-1]["environmentPreflight"]["status"] == "missing_verifier_dependency"
    assert snapshot["eventTail"][-1]["environmentContractKind"] == "terminal_bench_task_environment"
    assert snapshot["latestMessage"] == "tb2 baseline environment_preflight status=missing_verifier_dependency available=False"
    assert snapshot["currentTask"] == "正在预检 case 1/1 的任务环境。"


def _checkpoint_in_thread(run_id: str, result: dict[str, object]) -> None:
    try:
        service._checkpoint_supervised_run(run_id, {"phase": "case_boundary", "case_id": "case_1"})
    except Exception as exc:  # pragma: no cover - surfaced through assertion
        result["error"] = exc


class _ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return None


def test_runtime_manager_start_supervised_run_submits_command(monkeypatch):
    calls: list[object] = []

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "_ensure_runtime_manager_daemon", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)) or {"commandId": "cmd-1"},
    )
    monkeypatch.setattr(
        service,
        "wait_for_result",
        lambda command_id, *, timeout_seconds=60: pytest.fail("accepted submission must not poll for command completion"),
    )
    monkeypatch.setattr(service, "_load_immediate_runtime_manager_command_result", lambda command_id: calls.append(("immediate", command_id)) or None)

    result = service.start_supervised_run({"sourceKind": "bundle", "bundleName": "manual_bundle"})

    assert result["accepted"] is True
    assert result["commandId"] == "cmd-1"
    assert result["commandType"] == "start_supervised_run"
    assert result["status"] == "queued"
    assert calls[0] == "ensure"
    assert calls[1] == (
        "start_supervised_run",
        {"payload": {"sourceKind": "bundle", "bundleName": "manual_bundle"}},
        "web_ui",
    )
    assert calls[2] == ("immediate", "cmd-1")


def test_runtime_manager_start_supervised_run_rejects_immediate_manager_failure(monkeypatch):
    calls: list[object] = []

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "_ensure_runtime_manager_daemon", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)) or {"commandId": "cmd-empty"},
    )
    monkeypatch.setattr(
        service,
        "wait_for_result",
        lambda command_id, *, timeout_seconds=60: pytest.fail("accepted submission must not poll for command completion"),
    )
    monkeypatch.setattr(
        service,
        "_load_immediate_runtime_manager_command_result",
        lambda command_id: {"ok": False, "message": "Runtime manager is shutting down.", "errorType": "RuntimeManagerStoppingError"},
    )

    with pytest.raises(service.SupervisedRunValidationError, match="shutting down"):
        service.start_supervised_run({"sourceKind": "bundle", "bundleName": "manual_bundle"})

    assert calls[0] == "ensure"
    assert calls[1] == (
        "start_supervised_run",
        {"payload": {"sourceKind": "bundle", "bundleName": "manual_bundle"}},
        "web_ui",
    )


def test_runtime_manager_delete_supervised_run_submits_command_without_waiting_for_completion(monkeypatch):
    calls: list[object] = []

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "_ensure_runtime_manager_daemon", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)) or {"commandId": "cmd-delete"},
    )
    monkeypatch.setattr(
        service,
        "wait_for_result",
        lambda command_id, *, timeout_seconds=60: pytest.fail("accepted submission must not poll for command completion"),
    )
    monkeypatch.setattr(service, "_load_immediate_runtime_manager_command_result", lambda command_id: calls.append(("immediate", command_id)) or None)

    result = service.delete_supervised_run_snapshot("web-supervised-managed")

    assert result["accepted"] is True
    assert result["commandId"] == "cmd-delete"
    assert result["commandType"] == "delete_supervised_run"
    assert result["runId"] == "web-supervised-managed"
    assert calls[0] == "ensure"
    assert calls[1] == (
        "delete_supervised_run",
        {"runId": "web-supervised-managed"},
        "web_ui",
    )
    assert calls[2] == ("immediate", "cmd-delete")


def test_runtime_manager_get_active_supervised_run_reads_store(monkeypatch):
    snapshot = {
        "runId": "web-supervised-managed",
        "status": "running",
        "runtimeManagerControl": {
            "ownerPid": 222,
            "kind": "supervised",
            "claimedAt": "2026-05-18T12:00:00Z",
        },
    }

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "_current_runtime_manager_owner_pid", lambda: 222)
    monkeypatch.setattr(service, "load_manager_active_run_snapshot", lambda kind: snapshot if kind == "supervised" else None)

    result = service.get_active_supervised_run()

    assert result is not None
    assert result["runId"] == snapshot["runId"]
    assert result["status"] == snapshot["status"]
    assert result["actionStates"]["pause"]["enabled"] is True


def test_runtime_manager_latest_supervised_run_reuses_loaded_active_snapshot(monkeypatch):
    active = {
        "runId": "web-supervised-active",
        "status": "running",
        "runtimeManagerControl": {
            "ownerPid": 222,
            "kind": "supervised",
            "claimedAt": "2026-05-18T12:00:00Z",
        },
    }
    active_loads = 0

    def fail_active_load(kind):
        nonlocal active_loads
        active_loads += 1
        raise AssertionError("loaded active snapshot should be reused")

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "_current_runtime_manager_owner_pid", lambda: 222)
    monkeypatch.setattr(service, "load_manager_active_run_snapshot", fail_active_load)
    monkeypatch.setattr(service, "load_manager_latest_run_snapshot", lambda kind: pytest.fail("active snapshot should satisfy latest"))

    result = service.get_latest_supervised_run(active_run=active, active_run_loaded=True)

    assert active_loads == 0
    assert result is not None
    assert result["runId"] == active["runId"]
    assert result["actionStates"]["pause"]["enabled"] is True


def test_runtime_manager_workbench_can_skip_catalog_scan(monkeypatch):
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "default_bundle_name", lambda: "default_bundle")
    monkeypatch.setattr(service, "get_workbench_state_payload", lambda **kwargs: pytest.fail("provided saved state should be reused"))
    monkeypatch.setattr(service, "list_dataset_choices", lambda project_root: pytest.fail("catalog-light workbench should not scan datasets"))
    monkeypatch.setattr(service, "list_available_workbench_bundles", lambda project_root: pytest.fail("catalog-light workbench should not scan bundles"))

    payload = service.get_supervised_workbench(
        active_run={"runId": "active-1"},
        active_run_loaded=True,
        include_catalog=False,
        saved_state={"source": "bundle"},
    )

    assert payload["defaultBundleName"] == "default_bundle"
    assert payload["savedState"] == {"source": "bundle"}
    assert payload["bundles"] == []
    assert payload["datasets"] == []
    assert payload["activeRun"]["runId"] == "active-1"


def test_local_workbench_can_skip_catalog_scan(monkeypatch):
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(service, "default_bundle_name", lambda: "default_bundle")
    monkeypatch.setattr(service, "get_workbench_state_payload", lambda **kwargs: pytest.fail("provided saved state should be reused"))
    monkeypatch.setattr(service, "list_dataset_choices", lambda project_root: pytest.fail("catalog-light workbench should not scan datasets"))
    monkeypatch.setattr(service, "list_available_workbench_bundles", lambda project_root: pytest.fail("catalog-light workbench should not scan bundles"))

    payload = service.get_supervised_workbench(
        active_run={"runId": "active-local"},
        active_run_loaded=True,
        include_catalog=False,
        saved_state={"source": "bundle"},
    )

    assert payload["defaultBundleName"] == "default_bundle"
    assert payload["savedState"] == {"source": "bundle"}
    assert payload["bundles"] == []
    assert payload["datasets"] == []
    assert payload["activeRun"]["runId"] == "active-local"


def test_runtime_manager_active_supervised_run_closes_stale_locked_snapshot(monkeypatch):
    run_id = "web-supervised-stale-active"
    snapshot = {
        "runId": run_id,
        "status": "queued",
        "currentPhase": "queued",
        "runtimeStatus": "queued",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
        "finishedAt": "",
        "latestMessage": "queued",
        "currentTask": "queued",
        "pauseRequested": False,
        "pauseRequestedAt": "",
        "stopRequested": False,
        "stopRequestedAt": "",
        "eventTail": [],
        "runtimeManagerControl": {
            "ownerPid": 111,
            "kind": "supervised",
            "claimedAt": "2026-05-18T12:00:00Z",
        },
    }
    service.persist_manager_run_snapshot("supervised", snapshot, active_run_id=run_id)

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "_current_runtime_manager_owner_pid", lambda: 222)

    result = service.get_active_supervised_run()
    persisted = service.load_manager_run_snapshot("supervised", run_id)

    assert result is None
    assert service.load_manager_active_run_snapshot("supervised") is None
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["runtimeStatus"] == "idle"
    assert persisted["stopRequested"] is True
    assert persisted["runtimeManagerControl"]["reason"] == "orphaned"


def test_runtime_manager_active_supervised_run_finishes_successfully_closed_stale_snapshot(monkeypatch):
    run_id = "web-supervised-stale-success"
    snapshot = {
        "runId": run_id,
        "status": "running",
        "currentPhase": "running",
        "runtimeStatus": "running",
        "startedAt": "2026-05-21T23:06:28",
        "updatedAt": "2026-05-21T23:08:10",
        "finishedAt": "",
        "latestMessage": "running",
        "currentTask": "running",
        "pauseRequested": False,
        "pauseRequestedAt": "",
        "stopRequested": False,
        "stopRequestedAt": "",
        "eventTail": [],
        "currentCaseIo": {
            "transcript": [
                {
                    "timestamp": "2026-05-21T23:07:54",
                    "kind": "error",
                    "label": "llm_error",
                    "content": "network_error: [SSL: UNEXPECTED_EOF_WHILE_READING]",
                },
                {
                    "timestamp": "2026-05-21T23:08:10",
                    "kind": "tool",
                    "label": "close_evolution_transaction_tool",
                    "content": '{"status":"success","transaction_status":"success"}',
                    "status": "success",
                },
            ],
        },
        "runtimeManagerControl": {
            "ownerPid": 111,
            "kind": "supervised",
            "claimedAt": "2026-05-21T23:06:28",
        },
    }
    service.persist_manager_run_snapshot("supervised", snapshot, active_run_id=run_id)

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "_current_runtime_manager_owner_pid", lambda: 222)

    result = service.get_active_supervised_run()
    persisted = service.load_manager_run_snapshot("supervised", run_id)

    assert result is None
    assert service.load_manager_active_run_snapshot("supervised") is None
    assert persisted is not None
    assert persisted["status"] == "done"
    assert persisted["currentPhase"] == "done"
    assert persisted["runtimeStatus"] == "idle"
    assert persisted["stopRequested"] is False
    assert persisted["runtimeManagerControl"]["reason"] == "orphaned_success"
    assert persisted["eventTail"][-1]["event"] == "run_completed"


def test_snapshot_has_successful_transaction_close_accepts_bom_status():
    snapshot = {
        "currentCaseIo": {
            "transcript": [
                {
                    "kind": "tool",
                    "label": "close_evolution_transaction_tool",
                    "status": "\ufeffsuccess",
                    "content": '{"status":"\\ufeffsuccess","transaction_status":"\\ufeffsuccess","txn_id":"demo"}',
                }
            ]
        }
    }

    assert service._snapshot_has_successful_transaction_close(snapshot) is True


def test_snapshot_has_successful_transaction_close_accepts_ok_status():
    snapshot = {
        "currentCaseIo": {
            "transcript": [
                {
                    "kind": "tool",
                    "label": "close_evolution_transaction_tool",
                    "status": "ok",
                    "content": '{"status":"ok","transaction_status":"ok","txn_id":"demo"}',
                }
            ]
        }
    }

    assert service._snapshot_has_successful_transaction_close(snapshot) is True


def test_snapshot_has_successful_transaction_close_accepts_dict_content_payload():
    snapshot = {
        "currentCaseIo": {
            "transcript": [
                {
                    "kind": "tool",
                    "label": "close_evolution_transaction_tool",
                    "status": "success",
                    "content": {"status": "success", "transaction_status": "success", "txn_id": "demo"},
                }
            ]
        }
    }

    assert service._snapshot_has_successful_transaction_close(snapshot) is True


def test_force_cancel_active_supervised_runs_for_shutdown_releases_file_only_snapshot(monkeypatch):
    run_id = "web-supervised-shutdown-active"
    snapshot = {
        "runId": run_id,
        "status": "stopping",
        "currentPhase": "stopping",
        "runtimeStatus": "stopping",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:01Z",
        "finishedAt": "",
        "latestMessage": "stopping",
        "currentTask": "stopping",
        "pauseRequested": False,
        "pauseRequestedAt": "",
        "stopRequested": True,
        "stopRequestedAt": "2026-05-18T12:00:01Z",
        "eventTail": [],
        "leases": ["evaluation"],
        "runtimeManagerControl": {
            "ownerPid": 222,
            "kind": "supervised",
            "claimedAt": "2026-05-18T12:00:00Z",
        },
    }
    service.persist_manager_run_snapshot("supervised", snapshot, active_run_id=run_id)

    closed = service.force_cancel_active_supervised_runs_for_shutdown("closing")
    persisted = service.load_manager_run_snapshot("supervised", run_id)

    assert len(closed) == 1
    assert closed[0]["runId"] == run_id
    assert closed[0]["status"] == "cancelled"
    assert service.load_manager_active_run_snapshot("supervised") is None
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["currentPhase"] == "cancelled"
    assert persisted["runtimeStatus"] == "idle"
    assert persisted["finishedAt"]
    assert persisted["runtimeManagerControl"]["reason"] == "shutdown"


def test_force_cancel_active_supervised_runs_for_shutdown_preserves_successfully_closed_snapshot(monkeypatch):
    run_id = "web-supervised-shutdown-success"
    snapshot = {
        "runId": run_id,
        "status": "running",
        "currentPhase": "running",
        "runtimeStatus": "running",
        "startedAt": "2026-05-21T23:06:28",
        "updatedAt": "2026-05-21T23:08:10",
        "finishedAt": "",
        "latestMessage": "running",
        "currentTask": "running",
        "pauseRequested": False,
        "pauseRequestedAt": "",
        "stopRequested": False,
        "stopRequestedAt": "",
        "eventTail": [],
        "leases": ["evaluation"],
        "currentCaseIo": {
            "transcript": [
                {
                    "timestamp": "2026-05-21T23:08:10",
                    "kind": "tool",
                    "label": "close_evolution_transaction_tool",
                    "content": '{"status":"success","transaction_status":"success"}',
                    "status": "success",
                },
            ],
        },
        "runtimeManagerControl": {
            "ownerPid": 222,
            "kind": "supervised",
            "claimedAt": "2026-05-21T23:06:28",
        },
    }
    service.persist_manager_run_snapshot("supervised", snapshot, active_run_id=run_id)

    closed = service.force_cancel_active_supervised_runs_for_shutdown("closing")
    persisted = service.load_manager_run_snapshot("supervised", run_id)

    assert len(closed) == 1
    assert closed[0]["status"] == "done"
    assert service.load_manager_active_run_snapshot("supervised") is None
    assert persisted is not None
    assert persisted["status"] == "done"
    assert persisted["currentPhase"] == "done"
    assert persisted["runtimeStatus"] == "idle"
    assert persisted["stopRequested"] is False
    assert persisted["runtimeManagerControl"]["reason"] == "shutdown_success"


def test_runtime_manager_active_supervised_run_keeps_current_owner(monkeypatch):
    run_id = "web-supervised-current-active"
    snapshot = {
        "runId": run_id,
        "status": "running",
        "currentPhase": "running",
        "runtimeStatus": "running",
        "pauseRequested": False,
        "stopRequested": False,
        "eventTail": [],
        "runtimeManagerControl": {
            "ownerPid": 222,
            "kind": "supervised",
            "claimedAt": "2026-05-18T12:00:00Z",
        },
    }
    service.persist_manager_run_snapshot("supervised", snapshot, active_run_id=run_id)

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "_current_runtime_manager_owner_pid", lambda: 222)

    result = service.get_active_supervised_run()
    persisted = service.load_manager_run_snapshot("supervised", run_id)

    assert result is not None
    assert result["runId"] == run_id
    assert result["status"] == "running"
    assert persisted is not None
    assert persisted["status"] == "running"
    assert service.load_manager_active_run_snapshot("supervised") is not None


def test_runtime_manager_live_control_requires_matching_project_root(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        service,
        "load_runtime_snapshot",
        lambda: {"daemonRunning": True, "projectRoot": str(Path.cwd())},
        raising=False,
    )

    from core.runtime_manager import daemon as runtime_daemon

    monkeypatch.setattr(
        runtime_daemon,
        "load_runtime_snapshot",
        lambda: {"daemonRunning": True, "projectRoot": str(Path.cwd())},
    )

    assert service._runtime_manager_live_control_enabled() is False
