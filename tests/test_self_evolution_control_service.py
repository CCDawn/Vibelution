import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.orchestration.turn_runtime import prepare_agent_turn_runtime
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import evolution as evolution_routes
from core.web.services import (
    agent_directory_service,
    agent_mode_binding_service,
    prompt_template_service,
    self_evolution_control_service as service,
    session_service,
)

pytestmark = pytest.mark.serial


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture(autouse=True)
def reset_self_evolution_run_state(monkeypatch: pytest.MonkeyPatch):
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

    def fake_load_manager_latest_run_snapshot(kind: str) -> dict | None:
        latest_run_id = manager_index.get(kind, {}).get("latestRunId", "")
        return fake_load_manager_run_snapshot(kind, latest_run_id)

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(service, "persist_manager_run_snapshot", fake_persist_manager_run_snapshot)
    monkeypatch.setattr(service, "load_manager_run_snapshot", fake_load_manager_run_snapshot)
    monkeypatch.setattr(service, "load_manager_active_run_snapshot", fake_load_manager_active_run_snapshot)
    monkeypatch.setattr(service, "load_manager_latest_run_snapshot", fake_load_manager_latest_run_snapshot)
    with service._RUN_STATE_LOCK:
        service._RUN_STATES.clear()
        service._RUN_INTERNALS.clear()
        service._ACTIVE_RUN_ID = None
    with service._RUN_SUBSCRIBERS_LOCK:
        service._RUN_SUBSCRIBERS.clear()
    with service._OBSERVATION_RUN_STATE_LOCK:
        service._OBSERVATION_RUNS.clear()
        service._ACTIVE_OBSERVATION_RUN_ID = ""
    yield
    with service._RUN_STATE_LOCK:
        service._RUN_STATES.clear()
        service._RUN_INTERNALS.clear()
        service._ACTIVE_RUN_ID = None
    with service._RUN_SUBSCRIBERS_LOCK:
        service._RUN_SUBSCRIBERS.clear()
    with service._OBSERVATION_RUN_STATE_LOCK:
        service._OBSERVATION_RUNS.clear()
        service._ACTIVE_OBSERVATION_RUN_ID = ""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_latest_self_evolution_run_decorates_runtime_attention(monkeypatch):
    run_id = "web-self-live"
    with service._RUN_STATE_LOCK:
        service._RUN_STATES[run_id] = {
            "runId": run_id,
            "goal": "autonomous patch",
            "status": "running",
            "phase": "running",
            "startedAt": "2026-05-18T12:00:00Z",
            "updatedAt": "2026-05-18T12:00:01Z",
            "finishedAt": "",
            "latestMessage": "latest message",
            "currentGoal": "",
            "currentTask": "",
            "lastToolName": "",
            "runtimeStatus": "",
            "toolCallCount": 0,
            "summary": "",
            "error": "",
            "cancelRequested": False,
            "cancelRequestedAt": "",
            "stopReason": "",
            "readingTask": "",
            "readingHint": "",
            "readingSufficiency": "",
            "convergenceState": "",
            "nextToolIntent": "",
            "rollback": {
                "status": "idle",
                "reason": "",
                "baseRev": "",
                "rolledBackAt": "",
                "entryCount": 0,
                "touchedFiles": [],
                "conflictFiles": [],
                "blockedHint": "",
            },
        }
        service._ACTIVE_RUN_ID = run_id
    monkeypatch.setattr(
        service,
        "_load_runtime_state",
        lambda: {
            "current_goal": "inspect guidance",
            "last_tool_name": "rg",
            "runtime_status": "thinking",
            "updated_at": "2026-05-18T12:00:02Z",
        },
    )
    monkeypatch.setattr(
        service,
        "get_session_state",
        lambda: SimpleNamespace(
            get_attention_snapshot=lambda: {
                "reading_task": "Read supervised control flow",
                "reading_recommendation": "Check the latest pause event first",
                "reading_sufficiency": "insufficient",
                "convergence_state": "exploring",
                "next_tool_intent": "Open the control service module",
                "stop_reason": "",
            }
        ),
    )

    payload = service.get_latest_self_evolution_run()

    assert payload is not None
    assert payload["phase"] == "reading"
    assert payload["currentGoal"] == "inspect guidance"
    assert payload["currentTask"] == "Read supervised control flow"
    assert payload["readingHint"] == "Check the latest pause event first"
    assert payload["nextToolIntent"] == "Open the control service module"


def _seed_terminal_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, current_text: str = "after\n") -> dict:
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    run_id = "web-self-test"
    target_path = tmp_path / "web" / "src" / "demo.txt"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(current_text, encoding="utf-8", newline="\n")

    backup_path = tmp_path / "workspace" / "self_evolution" / "rollback" / run_id / "files" / "web" / "src" / "demo.txt"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text("before\n", encoding="utf-8", newline="\n")
    before_hash = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    after_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()

    touched_file = {
        "path": "web/src/demo.txt",
        "changeType": "modified",
        "trackedBefore": True,
        "existedBefore": True,
        "statusAfter": "M",
        "preHash": before_hash,
        "postHash": after_hash,
        "postExists": True,
        "conflict": False,
        "conflictReason": "",
    }
    rollback_state = {
        "status": "available",
        "reason": "ready",
        "baseRev": "abcdef123456",
        "rolledBackAt": "",
        "entryCount": 1,
        "touchedFiles": [touched_file],
        "conflictFiles": [],
        "blockedHint": "",
    }
    manifest_path = tmp_path / "workspace" / "self_evolution" / "rollback" / run_id / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "runId": run_id,
                "baseRev": "abcdef123456",
                "display": rollback_state,
                "entries": [
                    {
                        **touched_file,
                        "restoreSource": "backup",
                        "backupPath": str(backup_path),
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    state = {
        "runId": run_id,
        "goal": "网页回滚测试",
        "status": "done",
        "phase": "done",
        "startedAt": "2026-05-18T11:55:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
        "finishedAt": "2026-05-18T12:00:00Z",
        "latestMessage": "done",
        "currentGoal": "网页回滚测试",
        "lastToolName": "apply_patch",
        "runtimeStatus": "success",
        "toolCallCount": 1,
        "summary": "done",
        "error": "",
        "cancelRequested": False,
        "cancelRequestedAt": "",
        "stopReason": "",
        "rollback": rollback_state,
        "artifacts": {
            "rollbackDir": str(manifest_path.parent),
            "manifestPath": str(manifest_path),
        },
    }

    with service._RUN_STATE_LOCK:
        service._RUN_STATES[run_id] = copy.deepcopy(state)
        service._ACTIVE_RUN_ID = None

    return {
        "run_id": run_id,
        "target_path": target_path,
    }


def test_rollback_self_evolution_run_restores_files_from_manifest(tmp_path, monkeypatch):
    seeded = _seed_terminal_run(tmp_path, monkeypatch)

    snapshot = service.rollback_self_evolution_run(seeded["run_id"])

    assert seeded["target_path"].read_text(encoding="utf-8") == "before\n"
    assert snapshot["rollback"]["status"] == "rolled_back"
    assert snapshot["rollback"]["rolledBackAt"]


def test_rollback_self_evolution_run_blocks_when_file_changed_after_run(tmp_path, monkeypatch):
    seeded = _seed_terminal_run(tmp_path, monkeypatch)
    seeded["target_path"].write_text("externally changed\n", encoding="utf-8", newline="\n")

    snapshot = service.rollback_self_evolution_run(seeded["run_id"])

    assert seeded["target_path"].read_text(encoding="utf-8") == "externally changed\n"
    assert snapshot["rollback"]["status"] == "blocked"
    assert snapshot["rollback"]["conflictFiles"][0]["path"] == "web/src/demo.txt"


def test_self_evolution_latest_run_route_is_not_exposed():
    response = client.get("/api/evolution/self/latest-run")

    assert response.status_code in {404, 405}


def test_self_evolution_run_events_route_is_not_exposed():
    response = client.get("/api/evolution/self/runs/web-self-stream/events")

    assert response.status_code in {404, 405}


def test_runtime_manager_latest_self_evolution_run_reads_store(monkeypatch):
    snapshot = {
        "runId": "web-self-managed",
        "status": "running",
        "runtimeManagerControl": {
            "ownerPid": 222,
            "kind": "self",
            "claimedAt": "2026-05-18T12:00:00Z",
        },
    }

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "_current_runtime_manager_owner_pid", lambda: 222)
    monkeypatch.setattr(service, "load_manager_latest_run_snapshot", lambda kind: snapshot if kind == "self" else None)
    monkeypatch.setattr(service, "load_manager_active_run_snapshot", lambda kind: snapshot if kind == "self" else None)

    result = service.get_latest_self_evolution_run()

    assert result is not None
    assert result["runId"] == snapshot["runId"]
    assert result["status"] == snapshot["status"]
    assert result["runSemantics"]["runStatus"] == "running"
    assert result["actionStates"]["pause"]["enabled"] is True


def test_runtime_manager_latest_self_evolution_run_closes_orphaned_locked_snapshot(monkeypatch):
    snapshot = {
        "runId": "web-self-orphan",
        "goal": "orphan",
        "status": "queued",
        "phase": "queued",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
        "finishedAt": "",
        "latestMessage": "queued",
        "currentGoal": "orphan",
        "lastToolName": "",
        "runtimeStatus": "working",
        "toolCallCount": 0,
        "summary": "",
        "error": "",
        "cancelRequested": False,
        "cancelRequestedAt": "",
        "stopReason": "",
        "controlAction": "",
        "controlRequestedAt": "",
        "messages": [],
        "turnCount": 0,
        "resumeCount": 0,
        "rollback": {
            "status": "unavailable",
            "reason": "",
            "baseRev": "",
            "rolledBackAt": "",
            "entryCount": 0,
            "touchedFiles": [],
            "conflictFiles": [],
            "blockedHint": "",
        },
    }
    persisted: dict[str, object] = {}

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "load_manager_latest_run_snapshot", lambda kind: copy.deepcopy(snapshot) if kind == "self" else None)
    monkeypatch.setattr(service, "load_manager_active_run_snapshot", lambda kind: None)

    def fake_persist(kind: str, payload: dict, *, active_run_id: str = "") -> dict:
        persisted["kind"] = kind
        persisted["payload"] = copy.deepcopy(payload)
        persisted["active_run_id"] = active_run_id
        return copy.deepcopy(payload)

    monkeypatch.setattr(service, "persist_manager_run_snapshot", fake_persist)

    result = service.get_latest_self_evolution_run()

    assert result is not None
    assert result["status"] == "cancelled"
    assert result["phase"] == "cancelled"
    assert result["runtimeStatus"] == "idle"
    assert result["cancelRequested"] is True
    assert result["finishedAt"]
    assert result["messages"][-1]["role"] == "assistant"
    assert persisted["kind"] == "self"
    assert persisted["active_run_id"] == ""
    assert persisted["payload"]["status"] == "cancelled"


def test_runtime_manager_active_self_evolution_run_closes_stale_locked_snapshot(monkeypatch):
    snapshot = {
        "runId": "web-self-stale-active",
        "goal": "stale active",
        "status": "queued",
        "phase": "queued",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
        "finishedAt": "",
        "latestMessage": "queued",
        "currentGoal": "stale active",
        "lastToolName": "",
        "runtimeStatus": "working",
        "toolCallCount": 0,
        "summary": "",
        "error": "",
        "cancelRequested": False,
        "cancelRequestedAt": "",
        "stopReason": "",
        "controlAction": "",
        "controlRequestedAt": "",
        "messages": [],
        "turnCount": 0,
        "resumeCount": 0,
        "rollback": {
            "status": "unavailable",
            "reason": "",
            "baseRev": "",
            "rolledBackAt": "",
            "entryCount": 0,
            "touchedFiles": [],
            "conflictFiles": [],
            "blockedHint": "",
        },
        "runtimeManagerControl": {
            "ownerPid": 111,
            "kind": "self",
            "claimedAt": "2026-05-18T12:00:00Z",
        },
    }
    persisted: dict[str, object] = {}

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "_current_runtime_manager_owner_pid", lambda: 222)
    monkeypatch.setattr(service, "load_manager_active_run_snapshot", lambda kind: copy.deepcopy(snapshot) if kind == "self" else None)

    def fake_persist(kind: str, payload: dict, *, active_run_id: str = "") -> dict:
        persisted["kind"] = kind
        persisted["payload"] = copy.deepcopy(payload)
        persisted["active_run_id"] = active_run_id
        return copy.deepcopy(payload)

    monkeypatch.setattr(service, "persist_manager_run_snapshot", fake_persist)

    result = service.get_active_self_evolution_run()

    assert result is None
    assert persisted["kind"] == "self"
    assert persisted["active_run_id"] == ""
    assert persisted["payload"]["status"] == "cancelled"
    assert persisted["payload"]["runtimeManagerControl"]["reason"] == "orphaned"


def test_force_cancel_active_self_evolution_runs_for_shutdown_releases_file_only_snapshot(monkeypatch):
    run_id = "web-self-shutdown-active"
    snapshot = {
        "runId": run_id,
        "goal": "shutdown",
        "status": "stopping",
        "phase": "stopping",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:01Z",
        "finishedAt": "",
        "latestMessage": "stopping",
        "currentGoal": "shutdown",
        "lastToolName": "",
        "runtimeStatus": "stopping",
        "toolCallCount": 0,
        "summary": "",
        "error": "",
        "cancelRequested": True,
        "cancelRequestedAt": "2026-05-18T12:00:01Z",
        "stopReason": "",
        "controlAction": "terminate",
        "controlRequestedAt": "2026-05-18T12:00:01Z",
        "messages": [],
        "turnCount": 0,
        "resumeCount": 0,
        "rollback": {
            "status": "unavailable",
            "reason": "",
            "baseRev": "",
            "rolledBackAt": "",
            "entryCount": 0,
            "touchedFiles": [],
            "conflictFiles": [],
            "blockedHint": "",
        },
        "runtimeManagerControl": {
            "ownerPid": 222,
            "kind": "self",
            "claimedAt": "2026-05-18T12:00:00Z",
        },
    }
    service.persist_manager_run_snapshot("self", snapshot, active_run_id=run_id)

    closed = service.force_cancel_active_self_evolution_runs_for_shutdown("closing")
    persisted = service.load_manager_run_snapshot("self", run_id)

    assert len(closed) == 1
    assert closed[0]["runId"] == run_id
    assert closed[0]["status"] == "cancelled"
    assert service.load_manager_active_run_snapshot("self") is None
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["phase"] == "cancelled"
    assert persisted["runtimeStatus"] == "idle"
    assert persisted["finishedAt"]
    assert persisted["runtimeManagerControl"]["reason"] == "shutdown"


def test_runtime_manager_active_self_evolution_run_keeps_current_owner(monkeypatch):
    snapshot = {
        "runId": "web-self-current-active",
        "status": "queued",
        "phase": "queued",
        "latestMessage": "queued",
        "rollback": {
            "status": "unavailable",
            "reason": "",
            "baseRev": "",
            "rolledBackAt": "",
            "entryCount": 0,
            "touchedFiles": [],
            "conflictFiles": [],
            "blockedHint": "",
        },
        "runtimeManagerControl": {
            "ownerPid": 222,
            "kind": "self",
            "claimedAt": "2026-05-18T12:00:00Z",
        },
    }
    persisted: list[dict] = []

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "_current_runtime_manager_owner_pid", lambda: 222)
    monkeypatch.setattr(service, "load_manager_active_run_snapshot", lambda kind: copy.deepcopy(snapshot) if kind == "self" else None)
    monkeypatch.setattr(
        service,
        "persist_manager_run_snapshot",
        lambda kind, payload, *, active_run_id="": persisted.append(copy.deepcopy(payload)) or copy.deepcopy(payload),
    )

    result = service.get_active_self_evolution_run()

    assert result is not None
    assert result["runId"] == "web-self-current-active"
    assert result["status"] == "queued"
    assert persisted == []


def test_runtime_manager_start_self_evolution_allows_readonly_chat_session(monkeypatch):
    calls: list[object] = []
    snapshot = {"runId": "web-self-managed", "status": "queued"}

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(
        service,
        "get_workbench_contract",
        lambda: {"modeAvailability": {"self_evolution": True}},
    )
    monkeypatch.setattr(service, "active_session_has_write_leases", lambda: False)
    monkeypatch.setattr(service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(service, "_ensure_runtime_manager_daemon", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)) or {"commandId": "cmd-1"},
    )
    monkeypatch.setattr(service, "wait_for_result", lambda command_id: {"ok": True, "snapshot": snapshot})

    result = service.start_self_evolution_run({"goal": "managed"})

    assert result == snapshot
    assert calls == [
        "ensure",
        (
            "start_self_evolution_run",
            {"payload": {"goal": "managed"}},
            "web_ui",
        ),
    ]


def test_self_evolution_agent_bindings_create_fixed_role_slots(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "ROLLBACK_ROOT", tmp_path / "workspace" / "web_self_evolution")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)

    bindings = service.self_evolution_agent_bindings()

    assert set(bindings) == {"executor", "reviewer", "summarizer"}
    assert bindings["executor"]["promptTemplateId"] == "prompt-self-executor"
    assert bindings["reviewer"]["promptTemplateId"] == "prompt-self-reviewer"
    payload = agent_mode_binding_service.get_mode_bindings_payload()
    assert payload["modes"]["self_evolution"]["slots"]["executor"] == bindings["executor"]["agentId"]


def test_self_evolution_agent_repair_preserves_all_fixed_roles(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "ROLLBACK_ROOT", tmp_path / "workspace" / "web_self_evolution")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)

    service.ensure_self_evolution_agent_instances()
    session_service.list_sessions()
    agents = [
        agent
        for agent in agent_directory_service.list_agents()
        if agent["primaryMode"] == "self_evolution"
    ]

    assert {agent["roleKey"] for agent in agents} == {"executor", "reviewer", "summarizer"}
    assert {agent["promptTemplateId"] for agent in agents} == {
        "prompt-self-executor",
        "prompt-self-reviewer",
        "prompt-self-summarizer",
    }


def test_self_evolution_agent_repair_does_not_reactivate_archived_fixed_role(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "ROLLBACK_ROOT", tmp_path / "workspace" / "web_self_evolution")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    events = []
    monkeypatch.setattr(
        service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    first = service.ensure_self_evolution_agent_instances()
    executor = next(agent for agent in first if agent["roleKey"] == "executor")
    agent_mode_binding_service.remove_agent_from_mode_bindings(executor["agentId"])
    state = agent_directory_service.load_state()
    for agent in state["agents"]:
        if agent["agentId"] == executor["agentId"]:
            agent["status"] = "archived"
            agent["archivedAt"] = "2026-06-20T00:00:00+00:00"
            break
    agent_directory_service.save_state(state)

    second = service.ensure_self_evolution_agent_instances()

    assert executor["agentId"] not in {agent["agentId"] for agent in second}
    assert agent_directory_service.get_agent(executor["agentId"], include_archived=True)["status"] == "archived"
    payload = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["self_evolution"]
    assert payload["slots"]["executor"] == ""
    assert "executor" in payload["excludedSlots"]
    assert executor["agentId"] not in payload["availableAgentIds"]
    skipped_events = [item for item in events if item[0][2] == "self_evolution.agent_instance.sync_skipped"]
    assert skipped_events[-1][1]["fields"]["agentId"] == executor["agentId"]
    assert skipped_events[-1][1]["fields"]["reason"] == "mode_binding_slot_excluded"


def test_self_evolution_agent_bindings_block_archived_slot_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "ROLLBACK_ROOT", tmp_path / "workspace" / "web_self_evolution")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    events = []
    monkeypatch.setattr(service, "record_runtime_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))

    service.ensure_self_evolution_agent_instances()
    replacement = agent_directory_service.create_agent_instance(
        display_name="将被归档的自进化执行 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="self_evolution",
        role_key="executor",
        prompt_template_id="prompt-self-executor",
    )
    current = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["self_evolution"]
    slots = dict(current["slots"])
    slots["executor"] = replacement["agentId"]
    agent_mode_binding_service.update_mode_binding("self_evolution", slots=slots)
    agent_directory_service.archive_agent_instance(replacement["agentId"], repair_mode_bindings=False)

    with pytest.raises(service.SelfEvolutionRunValidationError, match="executor"):
        service.self_evolution_agent_bindings()
    assert events[-1][0][2] == "agent_runtime.resolve_failed"
    assert events[-1][1]["fields"]["mode"] == "self_evolution"
    assert events[-1][1]["fields"]["slot"] == "executor"
    assert events[-1][1]["fields"]["agentId"] == replacement["agentId"]


def test_start_self_evolution_run_snapshot_includes_agent_bindings(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "ROLLBACK_ROOT", tmp_path / "workspace" / "web_self_evolution")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service, "active_session_has_write_leases", lambda: False)
    monkeypatch.setattr(service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(service, "get_active_supervised_worktree_run", lambda: None)
    monkeypatch.setattr(service, "_capture_preflight_state", lambda run_id: {"runDir": "", "backupDir": "", "manifestPath": "", "baseRev": ""})
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda *args, **kwargs: None)

    snapshot = service.start_self_evolution_run({"goal": "只读观察"})

    assert snapshot["agentBindings"]["executor"]["agentId"]
    assert snapshot["agentBindings"]["reviewer"]["role"] == "reviewer"


def test_self_evolution_turn_uses_executor_context_engine_packet(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "ROLLBACK_ROOT", tmp_path / "workspace" / "web_self_evolution")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service, "active_session_has_write_leases", lambda: False)
    monkeypatch.setattr(service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(service, "get_active_supervised_worktree_run", lambda: None)
    monkeypatch.setattr(service, "_capture_preflight_state", lambda run_id: {"runDir": "", "backupDir": "", "manifestPath": "", "baseRev": ""})
    monkeypatch.setattr(service, "_finalize_rollback_manifest", lambda run_id, preflight: None)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.model_library["self-executor-runtime-model"] = {
        "provider_id": base_config.llm.profiles["primary"].provider_id,
        "model": "self-executor-runtime",
        "streaming": False,
        "tool_calling_mode": "disabled",
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    prompt_template_service.update_prompt_template(
        "prompt-self-executor",
        name="自进化执行提示词",
        category="self_evolution",
        source_path="workspace/prompts/self/executor.md",
        content="你是自进化执行 Agent，只根据当前有界目标行动。",
    )
    captured: dict[str, object] = {}
    scene_events: list[dict[str, object]] = []

    class FakeSelfEvolvingAgent:
        def __init__(self, *, mode=None, workspace_path=None, config=None):
            captured["mode"] = str(mode or "")
            captured["workspace_path"] = str(workspace_path or "")
            captured["profile_id"] = config.llm.get_profile(role="primary").profile_id if config else ""
            captured["primary_model"] = config.llm.get_profile(role="primary").model if config else ""

        def seed_static_runtime_context(self, content):
            captured["static_runtime_context"] = str(content or "")

        def seed_runtime_context(self, content):
            captured.setdefault("runtime_contexts", []).append(str(content or ""))

        def mark_runtime_context_seeded_by_host(self):
            captured["runtime_context_seeded_by_host"] = True

        def set_turn_interrupt_checker(self, checker):
            self.checker = checker

        def run_single_turn(self, initial_prompt=None):
            captured["initial_prompt"] = str(initial_prompt or "")
            return {
                "status": "completed",
                "summary": "self done",
                "raw_output": "self done",
                "tool_call_count": 1,
                "tool_trace": [],
            }

        def export_turn_carryover(self):
            return {}

    def fake_run_agent_single_turn(request):
        captured["runtime_mode"] = request.runtime.mode if request.runtime else ""
        captured["runtime_run_kind"] = request.runtime.run_kind if request.runtime else ""
        captured["runtime_cache_scope"] = request.runtime.cache_scope if request.runtime else ""
        captured["runtime_model_id"] = request.runtime.model_id if request.runtime else ""
        captured["request_runtime_context"] = request.runtime_context
        captured["request_static_runtime_context"] = request.static_runtime_context
        captured["request_dynamic_runtime_context"] = request.dynamic_runtime_context
        runtime = prepare_agent_turn_runtime(request.runtime) if request.runtime else None
        agent = FakeSelfEvolvingAgent(
            mode=request.mode,
            workspace_path=request.workspace_path,
            config=request.config,
        )
        seeded_context = False
        if request.static_runtime_context:
            agent.seed_static_runtime_context(request.static_runtime_context)
            seeded_context = True
        if request.dynamic_runtime_context:
            agent.seed_runtime_context(request.dynamic_runtime_context)
            seeded_context = True
        if request.runtime_context and not request.static_runtime_context and not request.dynamic_runtime_context:
            agent.seed_runtime_context(request.runtime_context)
            seeded_context = True
        if seeded_context:
            agent.mark_runtime_context_seeded_by_host()
        if request.interrupt_checker:
            agent.set_turn_interrupt_checker(request.interrupt_checker)
        result = agent.run_single_turn(initial_prompt=request.initial_prompt)
        if runtime is not None:
            result = {**result, "turn_runtime": dict(runtime.metadata)}
        return SimpleNamespace(result=result, carryover=agent.export_turn_carryover(), runtime=runtime)

    monkeypatch.setattr(service, "run_agent_single_turn", fake_run_agent_single_turn)
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: fn(context))
    monkeypatch.setattr(
        service,
        "_record_self_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append(
            {"phase": phase, "eventCode": event_code, **kwargs}
        ),
    )

    bindings = service.self_evolution_agent_bindings()
    agent_directory_service.update_agent_instance(
        bindings["executor"]["agentId"],
        llm_bindings={"dialogue": {"modelId": "self-executor-runtime-model"}},
    )
    snapshot = service.start_self_evolution_run({"goal": "只读观察"})
    executor = snapshot["agentBindings"]["executor"]
    event_path = tmp_path / executor["workspacePath"] / "events" / "agent_turn_results.jsonl"
    records = [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert snapshot["status"] == "done"
    assert captured["mode"] == "self_evolution"
    assert captured["workspace_path"] == executor["workspacePath"]
    assert captured["profile_id"] == "primary"
    assert captured["primary_model"] == "self-executor-runtime"
    assert captured["runtime_mode"] == "self_evolution"
    assert captured["runtime_run_kind"] == "self_evolution"
    assert captured["runtime_cache_scope"] == "executor"
    assert captured["runtime_model_id"] == "self-executor-runtime-model"
    assert "Agent Runtime Context" in captured["static_runtime_context"]
    assert "Agent Prompt Template" in captured["static_runtime_context"]
    assert "自进化执行 Agent" in captured["static_runtime_context"]
    assert captured["request_runtime_context"]
    assert captured["request_static_runtime_context"] == captured["static_runtime_context"]
    assert captured["runtime_context_seeded_by_host"] is True
    assert records[-1]["agentId"] == executor["agentId"]
    assert records[-1]["sessionId"] == executor["directSessionId"]
    assert records[-1]["status"] == "completed"
    assert records[-1]["toolCallCount"] == 1
    completed_event = next(
        item for item in scene_events if item["eventCode"] == "self_evolution_run.turn.completed"
    )
    turn_runtime = completed_event["fields"]["turnRuntime"]
    assert turn_runtime["runKind"] == "self_evolution"
    assert turn_runtime["cacheScope"] == "executor"
    assert turn_runtime["promptCachePartitionHash"]


def test_local_start_self_evolution_rejects_risky_write_goal_before_main_worktree(monkeypatch):
    submitted: list[object] = []

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(
        service,
        "get_workbench_contract",
        lambda: {"modeAvailability": {"self_evolution": True}},
    )
    monkeypatch.setattr(service, "active_session_has_write_leases", lambda: False)
    monkeypatch.setattr(service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(service, "get_active_supervised_worktree_run", lambda: None)
    monkeypatch.setattr(service, "_capture_preflight_state", lambda run_id: pytest.fail("preflight should not run"))
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda *args, **kwargs: submitted.append(args))

    with pytest.raises(service.SelfEvolutionRunValidationError, match="worktree"):
        service.start_self_evolution_run({"goal": "修复 self evolution 的代码并提交"})

    assert submitted == []
    assert service.get_active_self_evolution_run() is None


def test_runtime_manager_start_self_evolution_rejects_risky_write_goal_before_submit(monkeypatch):
    calls: list[object] = []

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(
        service,
        "get_workbench_contract",
        lambda: {"modeAvailability": {"self_evolution": True}},
    )
    monkeypatch.setattr(service, "active_session_has_write_leases", lambda: False)
    monkeypatch.setattr(service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(service, "_ensure_runtime_manager_daemon", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)),
    )

    with pytest.raises(service.SelfEvolutionRunValidationError, match="worktree"):
        service.start_self_evolution_run({"goal": "implement a prompt patch and commit it"})

    assert calls == []


def test_legacy_self_evolution_start_route_is_not_exposed():
    response = client.post(
        "/api/evolution/self/runs",
        json={"goal": "分析候选池回流", "writeIntent": True},
    )

    assert response.status_code in {404, 405}


def test_self_evolution_worktree_isolation_ignores_false_string_flags():
    reason = service._self_evolution_worktree_isolation_reason(
        {"writeIntent": "false", "requiresWorktreeIsolation": "0"},
        "分析候选池回流",
    )

    assert reason == ""


def test_start_self_evolution_worktree_run_delegates_risky_goal_to_supervised_review(monkeypatch):
    calls: list[dict] = []
    snapshot = {"runId": "swte-self-risk", "status": "queued"}

    monkeypatch.setattr(
        service,
        "get_workbench_contract",
        lambda: {"modeAvailability": {"self_evolution": True, "supervised_evolution": True}},
    )
    monkeypatch.setattr(
        service,
        "start_supervised_worktree_run",
        lambda payload: calls.append(copy.deepcopy(payload)) or snapshot,
    )

    result = service.start_self_evolution_worktree_run(
        {
            "goal": "修复自进化候选回流并提交",
            "bundleName": "closed_loop_v1",
            "uiRoute": "/evolution/self",
        }
    )

    assert result == snapshot
    assert calls[0]["bundleName"] == "closed_loop_v1"
    assert calls[0]["mode"] == "manual"
    assert calls[0]["keepWorktree"] is True
    assert calls[0]["requestSource"] == "api:evolution.self.worktree-runs"
    assert calls[0]["initiator"] == "self_evolution_risky_write"
    assert calls[0]["clientAction"] == "start_self_evolution_worktree_run"
    assert calls[0]["selfEvolutionGoal"] == "修复自进化候选回流并提交"
    assert calls[0]["selfEvolutionRiskReason"] == "goal_write_marker"
    assert calls[0]["requiresSupervisedReview"] is True


def test_start_self_evolution_worktree_run_routes_any_goal_to_reviewed_worktree(monkeypatch):
    calls: list[dict] = []
    snapshot = {"runId": "swte-self-default", "status": "queued"}

    monkeypatch.setattr(
        service,
        "get_workbench_contract",
        lambda: {"modeAvailability": {"self_evolution": True, "supervised_evolution": True}},
    )
    monkeypatch.setattr(
        service,
        "start_supervised_worktree_run",
        lambda payload: calls.append(copy.deepcopy(payload)) or snapshot,
    )

    result = service.start_self_evolution_worktree_run(
        {"goal": "分析候选池回流", "bundleName": "closed_loop_v1"}
    )

    assert result == snapshot
    assert calls[0]["requestSource"] == "api:evolution.self.worktree-runs"
    assert calls[0]["initiator"] == "self_evolution_risky_write"
    assert calls[0]["selfEvolutionGoal"] == "分析候选池回流"
    assert calls[0]["selfEvolutionRiskReason"] == "self_evolution_worktree_default"
    assert calls[0]["requiresSupervisedReview"] is True


def test_self_evolution_worktree_run_route_forwards_to_service(monkeypatch):
    calls: list[dict] = []
    snapshot = {"runId": "swte-route", "status": "queued"}

    monkeypatch.setattr(
        evolution_routes,
        "start_self_evolution_worktree_run",
        lambda payload: calls.append(copy.deepcopy(payload)) or snapshot,
    )

    response = client.post(
        "/api/evolution/self/worktree-runs",
        json={
            "goal": "修复自进化候选回流并提交",
            "bundleName": "closed_loop_v1",
            "mode": "manual",
        },
    )

    assert response.status_code == 202
    assert response.json() == snapshot
    assert calls[0]["goal"] == "修复自进化候选回流并提交"
    assert calls[0]["bundleName"] == "closed_loop_v1"
    assert calls[0]["mode"] == "manual"


@pytest.mark.parametrize(
    "manager_result",
    [
        {"ok": True},
        {"ok": True, "snapshot": {}},
    ],
)
def test_runtime_manager_start_self_evolution_rejects_empty_success_result(monkeypatch, manager_result):
    calls: list[object] = []

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(
        service,
        "get_workbench_contract",
        lambda: {"modeAvailability": {"self_evolution": True}},
    )
    monkeypatch.setattr(service, "active_session_has_write_leases", lambda: False)
    monkeypatch.setattr(service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(service, "_ensure_runtime_manager_daemon", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)) or {"commandId": "cmd-empty"},
    )
    monkeypatch.setattr(service, "wait_for_result", lambda command_id: manager_result)
    monkeypatch.setattr(service, "load_manager_run_snapshot", lambda kind, run_id: None)

    with pytest.raises(service.SelfEvolutionRunValidationError, match="snapshot"):
        service.start_self_evolution_run({"goal": "managed"})

    assert calls == [
        "ensure",
        (
            "start_self_evolution_run",
            {"payload": {"goal": "managed"}},
            "web_ui",
        ),
    ]


def test_runtime_manager_start_self_evolution_blocks_write_chat_session(monkeypatch):
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(
        service,
        "get_workbench_contract",
        lambda: {"modeAvailability": {"self_evolution": True}},
    )
    monkeypatch.setattr(service, "active_session_has_write_leases", lambda: True)

    with pytest.raises(service.SelfEvolutionRunBusyError):
        service.start_self_evolution_run({"goal": "managed"})


def test_self_observation_prompt_is_no_tool_contract():
    prompt = service.build_self_observation_prompt("观察自进化能力", duration_seconds=120)

    assert "无工具观察沙盒" in prompt
    assert "你没有任何工具" in prompt
    assert "不能声称已经读取" in prompt
    assert "不能请求工具授权" in prompt
    assert "无法验证" in prompt
    assert "未来需要的证据" in prompt


def test_self_observation_boundary_violation_detects_fake_execution_claims():
    assert service.detect_self_observation_boundary_violation("我已经读取了项目文件") == "claimed_file_read"
    assert service.detect_self_observation_boundary_violation("I ran pytest and verified it") == "claimed_command_execution"
    assert service.detect_self_observation_boundary_violation("当前理解：这是一个只能推理的问题") == ""


def test_start_self_observation_run_has_no_tools_no_worktree(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service, "_run_self_observation_turn", lambda context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")

    snapshot = service.start_self_observation_run({"goal": "观察规划能力", "durationSeconds": 90})

    assert snapshot["runKind"] == "self_observation_run"
    assert snapshot["selfMode"] == "observation"
    assert snapshot["allowedTools"] == []
    assert snapshot["writeLeases"] == []
    assert snapshot["worktreeCreated"] is False
    assert snapshot["durationSeconds"] == 90
    assert service.get_active_self_observation_run()["runId"] == snapshot["runId"]


@pytest.mark.parametrize(
    "field_name, field_value",
    [
        ("allowedTools", []),
        ("tools", ["git_status"]),
        ("toolRequests", [{"name": "read_file"}]),
        ("requestedTools", ["read_file"]),
        ("dynamicTools", True),
        ("temporaryAuthorization", {"tools": ["read_file"]}),
        ("temporaryToolAuthorization", {"tools": ["read_file"]}),
        ("toolPolicy", {"allowedTools": ["read_file"]}),
        ("permissions", {"filesystem": "write"}),
        ("writeLeases", ["workspace"]),
        ("readScopes", ["repo"]),
        ("writeScopes", ["repo"]),
        ("mutationAccess", "write"),
    ],
)
def test_start_self_observation_run_rejects_tool_and_authorization_fields(monkeypatch, field_name, field_value):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})

    payload = {"goal": "观察规划能力", field_name: field_value}

    with pytest.raises(service.SelfEvolutionRunValidationError, match="zero tools|工具授权|tool"):
        service.start_self_observation_run(payload)


def test_start_self_observation_run_completes_and_releases_active_slot(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(
        service._RUN_EXECUTOR,
        "submit",
        lambda fn, context: fn(context),
    )

    snapshot = service.start_self_observation_run({"goal": "观察规划能力", "durationSeconds": 90})
    final_snapshot = service.get_self_observation_run_snapshot(snapshot["runId"])

    assert final_snapshot is not None
    assert final_snapshot["status"] == "done"
    assert final_snapshot["phase"] == "done"
    assert final_snapshot["runtimeStatus"] == "done"
    assert final_snapshot["finishedAt"]
    assert "无法验证" in final_snapshot["report"]
    assert final_snapshot["latestMessage"]
    assert final_snapshot["actionStates"]["terminate"]["enabled"] is False
    assert service.get_active_self_observation_run() is None
    assert service._ACTIVE_OBSERVATION_RUN_ID == ""


@pytest.mark.parametrize(
    ("raw_value", "expected_duration"),
    [
        (None, 300),
        ("", 300),
        ("15", service.SELF_OBSERVATION_MIN_DURATION_SECONDS),
        (999999, service.SELF_OBSERVATION_MAX_DURATION_SECONDS),
    ],
)
def test_start_self_observation_run_normalizes_duration(monkeypatch, raw_value, expected_duration):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service, "_run_self_observation_turn", lambda context: None)

    snapshot = service.start_self_observation_run({"goal": "观察规划能力", "durationSeconds": raw_value})

    assert snapshot["durationSeconds"] == expected_duration


def test_execute_self_observation_action_terminates_active_run(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service, "_run_self_observation_turn", lambda context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")

    snapshot = service.start_self_observation_run({"goal": "观察规划能力", "durationSeconds": 90})
    updated = service.execute_self_observation_action(snapshot["runId"], "terminate")

    assert updated["status"] == "terminated"
    assert updated["phase"] == "terminated"
    assert updated["runtimeStatus"] == "terminated"
    assert updated["finishedAt"]
    assert updated["actionStates"]["terminate"]["enabled"] is False
    assert service.get_active_self_observation_run() is None


def test_execute_self_observation_action_rejects_unsupported_action():
    with pytest.raises(service.SelfEvolutionRunValidationError, match="Unsupported self observation action"):
        service.execute_self_observation_action("self-observe-missing", "approve")


def test_set_self_observation_terminal_state_preserves_operator_termination(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service, "_run_self_observation_turn", lambda context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")

    snapshot = service.start_self_observation_run({"goal": "观察规划能力", "durationSeconds": 90})
    service.execute_self_observation_action(snapshot["runId"], "terminate")

    service._set_self_observation_terminal_state(
        snapshot["runId"],
        status="done",
        latest_message="worker finished",
        report="worker report",
    )

    persisted = service.get_self_observation_run_snapshot(snapshot["runId"])
    assert persisted is not None
    assert persisted["status"] == "terminated"
    assert persisted["phase"] == "terminated"
    assert persisted["runtimeStatus"] == "terminated"
    assert persisted["latestMessage"] == "自主观察已由用户终止。"


def test_run_self_observation_turn_preserves_operator_termination(monkeypatch):
    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda fn, context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")

    snapshot = service.start_self_observation_run({"goal": "观察规划能力", "durationSeconds": 90})
    service.execute_self_observation_action(snapshot["runId"], "terminate")
    service._run_self_observation_turn(
        {"runId": snapshot["runId"], "goal": "观察规划能力", "durationSeconds": 90}
    )

    persisted = service.get_self_observation_run_snapshot(snapshot["runId"])
    assert persisted is not None
    assert persisted["status"] == "terminated"
    assert persisted["phase"] == "terminated"
    assert persisted["runtimeStatus"] == "terminated"
    assert persisted["latestMessage"] == "自主观察已由用户终止。"


def test_stream_self_observation_run_events_emits_snapshot_and_stops_for_terminal_run():
    snapshot = {
        "runId": "self-observe-stream",
        "status": "done",
        "phase": "done",
        "runtimeStatus": "done",
    }

    events = list(service.stream_self_observation_run_events("self-observe-stream", initial_snapshot=snapshot))

    assert len(events) == 1
    assert "event: self_observation_run" in events[0]
    assert '"runId": "self-observe-stream"' in events[0]


@pytest.mark.parametrize("status", ["queued", "running", "stopping", "paused"])
def test_supervised_run_blocks_self_evolution_for_locked_statuses(status):
    assert service._supervised_run_blocks_self_evolution({"status": status}) is True


@pytest.mark.parametrize("status", ["done", "failed", "cancelled", "", "missing"])
def test_supervised_run_does_not_block_self_evolution_for_terminal_statuses(status):
    assert service._supervised_run_blocks_self_evolution({"status": status}) is False


def test_local_start_self_evolution_blocks_paused_supervised_run(monkeypatch):
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(
        service,
        "get_workbench_contract",
        lambda: {"modeAvailability": {"self_evolution": True}},
    )
    monkeypatch.setattr(service, "active_session_has_write_leases", lambda: False)
    monkeypatch.setattr(service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(
        service,
        "get_active_supervised_run",
        lambda: {"runId": "web-supervised-paused", "status": "paused"},
    )
    monkeypatch.setattr(
        service,
        "_capture_preflight_state",
        lambda run_id: {
            "runDir": "",
            "backupDir": "",
            "manifestPath": "",
            "baseRev": "",
        },
    )
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda *args, **kwargs: None)

    with pytest.raises(service.SelfEvolutionRunBusyError):
        service.start_self_evolution_run({"goal": "local blocked"})


def test_local_resume_self_evolution_blocks_stopping_supervised_run(monkeypatch):
    run_id = "web-self-resume-blocked"
    with service._RUN_STATE_LOCK:
        service._RUN_STATES[run_id] = {
            "runId": run_id,
            "goal": "resume me",
            "status": "paused",
            "phase": "paused",
            "startedAt": "2026-05-18T12:00:00Z",
            "updatedAt": "2026-05-18T12:01:00Z",
            "finishedAt": "",
            "latestMessage": "paused",
            "currentGoal": "resume me",
            "lastToolName": "",
            "runtimeStatus": "idle",
            "toolCallCount": 0,
            "summary": "",
            "error": "",
            "cancelRequested": False,
            "cancelRequestedAt": "",
            "stopReason": "paused",
            "controlAction": "",
            "controlRequestedAt": "",
            "messages": [],
            "turnCount": 0,
            "resumeCount": 0,
            "rollback": {
                "status": "idle",
                "reason": "",
                "baseRev": "",
                "rolledBackAt": "",
                "entryCount": 0,
                "touchedFiles": [],
                "conflictFiles": [],
                "blockedHint": "",
            },
        }
        service._ACTIVE_RUN_ID = run_id
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(service, "active_session_has_write_leases", lambda: False)
    monkeypatch.setattr(service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(
        service,
        "get_active_supervised_run",
        lambda: {"runId": "web-supervised-stopping", "status": "stopping"},
    )
    monkeypatch.setattr(service._RUN_EXECUTOR, "submit", lambda *args, **kwargs: None)

    with pytest.raises(service.SelfEvolutionRunBusyError):
        service.resume_self_evolution_run(run_id)


def test_runtime_manager_start_self_evolution_ignores_cleaned_stale_supervised_lock(monkeypatch):
    calls: list[object] = []
    snapshot = {"runId": "web-self-managed", "status": "queued"}

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(
        service,
        "get_workbench_contract",
        lambda: {"modeAvailability": {"self_evolution": True}},
    )
    monkeypatch.setattr(service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(service, "_ensure_runtime_manager_daemon", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)) or {"commandId": "cmd-1"},
    )
    monkeypatch.setattr(service, "wait_for_result", lambda command_id: {"ok": True, "snapshot": snapshot})

    result = service.start_self_evolution_run({"goal": "managed"})

    assert result == snapshot
    assert calls == [
        "ensure",
        (
            "start_self_evolution_run",
            {"payload": {"goal": "managed"}},
            "web_ui",
        ),
    ]


def test_runtime_manager_live_control_requires_matching_project_root(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)

    from core.runtime_manager import daemon as runtime_daemon

    monkeypatch.setattr(
        runtime_daemon,
        "load_runtime_snapshot",
        lambda: {"daemonRunning": True, "projectRoot": str(Path.cwd())},
    )

    assert service._runtime_manager_live_control_enabled() is False


def test_self_evolution_terminate_route_is_not_exposed():
    response = client.post("/api/evolution/self/runs/web-self-stop/terminate")

    assert response.status_code in {404, 405}


def test_request_pause_self_evolution_run_marks_queued_run_paused():
    run_id = "web-self-pause"
    with service._RUN_STATE_LOCK:
        service._RUN_STATES[run_id] = {
            "runId": run_id,
            "goal": "pause me",
            "status": "queued",
            "phase": "queued",
            "startedAt": "2026-05-18T12:00:00Z",
            "updatedAt": "2026-05-18T12:00:00Z",
            "finishedAt": "",
            "latestMessage": "queued",
            "currentGoal": "pause me",
            "lastToolName": "",
            "runtimeStatus": "idle",
            "toolCallCount": 0,
            "summary": "",
            "error": "",
            "cancelRequested": False,
            "cancelRequestedAt": "",
            "stopReason": "",
            "controlAction": "",
            "controlRequestedAt": "",
            "messages": [],
            "turnCount": 0,
            "resumeCount": 0,
            "rollback": {
                "status": "idle",
                "reason": "",
                "baseRev": "",
                "rolledBackAt": "",
                "entryCount": 0,
                "touchedFiles": [],
                "conflictFiles": [],
                "blockedHint": "",
            },
        }
        service._ACTIVE_RUN_ID = run_id

    snapshot = service.request_pause_self_evolution_run(run_id)

    assert snapshot["status"] == "paused"
    assert snapshot["phase"] == "paused"
    assert snapshot["messages"][-1]["role"] == "assistant"
    assert snapshot["messages"][-1]["content"] == snapshot["latestMessage"]


def test_request_stop_self_evolution_run_closes_file_only_queued_run(monkeypatch):
    run_id = "web-self-file-only"
    persisted: dict[str, object] = {}
    stored = {
        "runId": run_id,
        "goal": "file only",
        "status": "queued",
        "phase": "queued",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
        "finishedAt": "",
        "latestMessage": "queued",
        "currentGoal": "file only",
        "lastToolName": "",
        "runtimeStatus": "working",
        "toolCallCount": 0,
        "summary": "",
        "error": "",
        "cancelRequested": False,
        "cancelRequestedAt": "",
        "stopReason": "",
        "controlAction": "",
        "controlRequestedAt": "",
        "messages": [],
        "turnCount": 0,
        "resumeCount": 0,
        "rollback": {
            "status": "unavailable",
            "reason": "",
            "baseRev": "",
            "rolledBackAt": "",
            "entryCount": 0,
            "touchedFiles": [],
            "conflictFiles": [],
            "blockedHint": "",
        },
    }

    monkeypatch.setattr(service, "load_manager_run_snapshot", lambda kind, loaded_run_id: copy.deepcopy(stored) if kind == "self" and loaded_run_id == run_id else None)

    def fake_persist(kind: str, payload: dict, *, active_run_id: str = "") -> dict:
        persisted["kind"] = kind
        persisted["payload"] = copy.deepcopy(payload)
        persisted["active_run_id"] = active_run_id
        return copy.deepcopy(payload)

    monkeypatch.setattr(service, "persist_manager_run_snapshot", fake_persist)

    snapshot = service.request_stop_self_evolution_run(run_id)

    assert snapshot["status"] == "cancelled"
    assert snapshot["phase"] == "cancelled"
    assert snapshot["runtimeStatus"] == "idle"
    assert snapshot["cancelRequested"] is True
    assert snapshot["finishedAt"]
    assert snapshot["messages"][-1]["role"] == "assistant"
    assert persisted["kind"] == "self"
    assert persisted["active_run_id"] == ""
    assert persisted["payload"]["status"] == "cancelled"


def test_finalize_terminal_self_evolution_run_records_experience(monkeypatch):
    run_id = "web-self-experience"
    calls: list[dict[str, object]] = []
    reflection_calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    with service._RUN_STATE_LOCK:
        service._RUN_STATES[run_id] = {
            "runId": run_id,
            "goal": "learn from terminal run",
            "status": "failed",
            "phase": "failed",
            "startedAt": "2026-05-18T12:00:00Z",
            "updatedAt": "2026-05-18T12:02:00Z",
            "finishedAt": "2026-05-18T12:02:00Z",
            "latestMessage": "pytest failed",
            "currentGoal": "learn from terminal run",
            "lastToolName": "pytest",
            "runtimeStatus": "failed",
            "toolCallCount": 2,
            "summary": "A bounded run failed during verification.",
            "error": "pytest failed",
            "cancelRequested": False,
            "cancelRequestedAt": "",
            "stopReason": "",
            "controlAction": "",
            "controlRequestedAt": "",
            "messages": [],
            "turnCount": 1,
            "resumeCount": 0,
            "rollback": {
                "status": "unavailable",
                "reason": "",
                "baseRev": "",
                "rolledBackAt": "",
                "entryCount": 0,
                "touchedFiles": [],
                "conflictFiles": [],
                "blockedHint": "",
            },
            "artifacts": {
                "manifestPath": "workspace/self_evolution/rollback/web-self-experience/manifest.json",
            },
        }
        service._RUN_INTERNALS[run_id] = {"preflight": {"manifestPath": ""}}

    monkeypatch.setattr(service, "_finalize_rollback_manifest", lambda loaded_run_id, preflight: None)

    def fake_record(snapshot: dict, *, rollback: dict | None = None, project_root=None):
        calls.append({"snapshot": copy.deepcopy(snapshot), "rollback": copy.deepcopy(rollback)})
        return SimpleNamespace(
            record={
                "experience_id": "exp_test",
                "source_run_id": snapshot["runId"],
                "dedupe_key": f"self_terminal:{snapshot['runId']}",
                "summary": "failed verification",
                "evidence": {"status": "failed", "tool_name": "pytest"},
                "runtime_scene_refs": ["logs/runtime_scenes/pkg/agent/self_evolution_runs/web-self-experience.jsonl"],
                "audit_refs": [],
                "supervised_required": True,
            },
            created=True,
        )

    def fake_reflection(experience: dict, *, project_root=None):
        reflection_calls.append({"experience": copy.deepcopy(experience), "project_root": project_root})
        return SimpleNamespace(
            record={"reflection_id": "refl_test", "dedupe_key": f"self_reflection:{experience['experience_id']}"},
            created=True,
        )

    monkeypatch.setattr(service, "record_terminal_self_evolution_experience", fake_record)
    monkeypatch.setattr(service, "record_bounded_self_evolution_reflection", fake_reflection)
    monkeypatch.setattr(
        service,
        "_record_self_scene_event",
        lambda phase, event_code, **kwargs: events.append(
            {"phase": phase, "event_code": event_code, **copy.deepcopy(kwargs)}
        ),
    )

    manifest = service._finalize_terminal_run_snapshot(run_id)

    assert manifest is None
    assert len(calls) == 1
    recorded = calls[0]["snapshot"]
    assert recorded["runId"] == run_id
    assert recorded["status"] == "failed"
    assert calls[0]["rollback"] is None
    assert len(reflection_calls) == 1
    assert reflection_calls[0]["experience"]["experience_id"] == "exp_test"
    assert [event["event_code"] for event in events[-2:]] == [
        "self_evolution_run.experience_recorded",
        "self_evolution_run.reflection_recorded",
    ]
    assert events[-2]["fields"]["dedupeKey"] == f"self_terminal:{run_id}"
    assert events[-1]["phase"] == "reflection"
    assert events[-1]["fields"]["dedupeKey"] == "self_reflection:exp_test"


def test_resume_self_evolution_run_requeues_paused_run(monkeypatch):
    run_id = "web-self-resume"
    submitted: list[dict[str, str]] = []
    with service._RUN_STATE_LOCK:
        service._RUN_STATES[run_id] = {
            "runId": run_id,
            "goal": "resume me",
            "status": "paused",
            "phase": "paused",
            "startedAt": "2026-05-18T12:00:00Z",
            "updatedAt": "2026-05-18T12:01:00Z",
            "finishedAt": "",
            "latestMessage": "paused",
            "currentGoal": "resume me",
            "lastToolName": "",
            "runtimeStatus": "idle",
            "toolCallCount": 0,
            "summary": "",
            "error": "",
            "cancelRequested": False,
            "cancelRequestedAt": "",
            "stopReason": "paused",
            "controlAction": "",
            "controlRequestedAt": "",
            "messages": [],
            "turnCount": 0,
            "resumeCount": 0,
            "rollback": {
                "status": "idle",
                "reason": "",
                "baseRev": "",
                "rolledBackAt": "",
                "entryCount": 0,
                "touchedFiles": [],
                "conflictFiles": [],
                "blockedHint": "",
            },
        }
        service._RUN_INTERNALS[run_id] = {
            "preflight": {},
            "carryover": {},
        }
        service._ACTIVE_RUN_ID = run_id
    monkeypatch.setattr(service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        service._RUN_EXECUTOR,
        "submit",
        lambda fn, context: submitted.append({"fn": fn.__name__, "runId": context["runId"], "goal": context["goal"]}),
    )

    snapshot = service.resume_self_evolution_run(run_id)

    assert snapshot["status"] == "queued"
    assert snapshot["resumeCount"] == 1
    assert snapshot["messages"][-1]["role"] == "user"
    assert "resume me" in snapshot["messages"][-1]["content"]
    assert submitted == [{"fn": "_run_self_evolution_turn", "runId": run_id, "goal": "resume me"}]


def test_fulfill_self_evolution_restart_intent_requeues_run(monkeypatch):
    run_id = "web-self-restart"
    submitted = []
    events = []
    with service._RUN_STATE_LOCK:
        service._RUN_STATES[run_id] = {
            "runId": run_id,
            "goal": "restart me",
            "status": "done",
            "phase": "completed",
            "startedAt": "2026-05-18T12:00:00Z",
            "updatedAt": "2026-05-18T12:00:00Z",
            "finishedAt": "2026-05-18T12:01:00Z",
            "latestMessage": "done",
            "currentGoal": "restart me",
            "lastToolName": "",
            "runtimeStatus": "idle",
            "toolCallCount": 0,
            "summary": "done",
            "error": "",
            "cancelRequested": False,
            "cancelRequestedAt": "",
            "stopReason": "",
            "controlAction": "",
            "controlRequestedAt": "",
            "messages": [],
            "turnCount": 1,
            "resumeCount": 0,
            "rollback": {
                "status": "idle",
                "reason": "",
                "baseRev": "",
                "rolledBackAt": "",
                "entryCount": 0,
                "touchedFiles": [],
                "conflictFiles": [],
                "blockedHint": "",
            },
        }
    monkeypatch.setattr(
        service._RUN_EXECUTOR,
        "submit",
        lambda fn, context: submitted.append({"fn": fn.__name__, "runId": context["runId"], "goal": context["goal"]}),
    )
    monkeypatch.setattr(
        service,
        "_record_self_scene_event",
        lambda phase, event_code, **kwargs: events.append({"phase": phase, "event": event_code, **kwargs}),
    )

    result = service._LOCAL_FULFILL_SELF_EVOLUTION_RESTART(
        {
            "intentId": "intent-self",
            "reason": "code_update",
            "sourceCommandId": run_id,
            "payload": {"runId": run_id},
        }
    )

    snapshot = result["snapshot"]
    assert snapshot["status"] == "queued"
    assert snapshot["phase"] == "queued"
    assert snapshot["resumeCount"] == 1
    assert snapshot["stopReason"] == "code_update"
    assert snapshot["messages"][-1]["role"] == "user"
    assert "code_update" in snapshot["messages"][-1]["content"]
    assert submitted == [{"fn": "_run_self_evolution_turn", "runId": run_id, "goal": "restart me"}]
    assert any(item["event"] == "self_evolution_run.restart_queued" for item in events)


def test_self_evolution_pause_route_is_not_exposed():
    response = client.post("/api/evolution/self/runs/web-self-pause/pause")

    assert response.status_code in {404, 405}


def test_self_evolution_resume_route_is_not_exposed():
    response = client.post("/api/evolution/self/runs/web-self-resume/resume")

    assert response.status_code in {404, 405}


def test_self_evolution_handoff_route_is_not_exposed():
    response = client.post("/api/evolution/self/runs/web-self-handoff/handoff")

    assert response.status_code in {404, 405}
