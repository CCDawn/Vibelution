import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.evaluation import self_evolution_workbench
from core.evaluation.chat_dataset_capture import ChatDatasetCaptureService, resolve_chat_dataset_paths
from core.evaluation.chat_segmenter import ChatTurnRecord
from core.evaluation.dataset_registry import list_dataset_status
from core.evaluation.self_evolution_candidate_pool import append_candidate_record
from core.gym import run_gym_collection_episode
from core.gym.promotion import (
    activate_gym_promotion_proposal,
    apply_gym_promotion_proposal,
    rollback_gym_promotion_proposal,
)
from core.runtime_manager import constants as runtime_manager_constants
from core.runtime_manager import evolution_store
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import evolution as evolution_routes
from core.web.services import (
    agent_mode_binding_service,
    agent_directory_service,
    chat_review_service,
    evolution_service,
    runtime_scene_service,
    session_service,
    self_evolution_control_service,
    self_evolution_service,
    supervised_agent_service,
    supervised_control_service,
    supervised_worktree_evolution_service,
)
from core.runtime_manager.evolution_store import clear_evolution_store
from tests.helpers.web_runtime_scene import _seed_runtime_scene_bundle
from tests.test_gym_runner import RunnerFakeAdapter

pytestmark = pytest.mark.serial


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture(autouse=True)
def disable_runtime_manager_live_control(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)

@pytest.fixture(autouse=True)
def isolate_evolution_live_state():
    clear_evolution_store()
    try:
        evolution_store._WORK_RUN_STORE.clear()
    except Exception:
        pass
    self_evolution_service.invalidate_self_evolution_overview_cache()
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_SUBSCRIBERS_LOCK:
        self_evolution_control_service._RUN_SUBSCRIBERS.clear()
    with session_service._RUNNING_SESSIONS_LOCK:
        session_service._RUNNING_SESSION_IDS.clear()
        session_service._SESSION_ACTIVE_TURN_IDS.clear()
        session_service._SESSION_ACTIVE_TURN_LEASES.clear()
    with session_service._SESSION_STREAM_SUBSCRIBERS_LOCK:
        session_service._SESSION_STREAM_SUBSCRIBERS.clear()
    with session_service._SESSION_TURN_CONTROLS_LOCK:
        session_service._SESSION_TURN_CONTROLS.clear()
    with session_service._SESSION_LIVE_OUTPUTS_LOCK:
        session_service._SESSION_LIVE_OUTPUTS.clear()
    with session_service._SESSION_LIST_CACHE_LOCK:
        session_service._SESSION_LIST_CACHE.clear()
    with session_service._SESSION_CONVERSATION_EVENTS_CACHE_LOCK:
        session_service._SESSION_CONVERSATION_EVENTS_CACHE.clear()
    clear_evolution_store()
    try:
        evolution_store._WORK_RUN_STORE.clear()
    except Exception:
        pass
    yield
    self_evolution_service.invalidate_self_evolution_overview_cache()
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_SUBSCRIBERS_LOCK:
        self_evolution_control_service._RUN_SUBSCRIBERS.clear()
    with session_service._RUNNING_SESSIONS_LOCK:
        session_service._RUNNING_SESSION_IDS.clear()
        session_service._SESSION_ACTIVE_TURN_IDS.clear()
        session_service._SESSION_ACTIVE_TURN_LEASES.clear()
    with session_service._SESSION_STREAM_SUBSCRIBERS_LOCK:
        session_service._SESSION_STREAM_SUBSCRIBERS.clear()
    with session_service._SESSION_TURN_CONTROLS_LOCK:
        session_service._SESSION_TURN_CONTROLS.clear()
    with session_service._SESSION_LIVE_OUTPUTS_LOCK:
        session_service._SESSION_LIVE_OUTPUTS.clear()
    with session_service._SESSION_LIST_CACHE_LOCK:
        session_service._SESSION_LIST_CACHE.clear()
    with session_service._SESSION_CONVERSATION_EVENTS_CACHE_LOCK:
        session_service._SESSION_CONVERSATION_EVENTS_CACHE.clear()

def _read_first_sse_event(response):
    event_name = ""
    data_lines = []
    for line in response.iter_lines():
        if line.startswith("event: "):
            event_name = line[len("event: ") :]
            continue
        if line.startswith("data: "):
            data_lines.append(line[len("data: ") :])
            continue
        if line == "":
            if event_name or data_lines:
                return {
                    "event": event_name,
                    "data": "\n".join(data_lines),
                }
    raise AssertionError("Expected at least one SSE event")

def _real_runtime_manager_evolution_paths(kind: str, run_id: str) -> tuple[Path, Path]:
    root = runtime_manager_constants.PROJECT_ROOT / ".runtime" / "runtime-manager" / "evolution" / kind
    return root / "runs" / f"{run_id}.json", root / "index.json"

def _read_optional_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None

def _restore_real_runtime_index_if_touched(kind: str, run_id: str, original_index_text: str | None) -> None:
    run_path, index_path = _real_runtime_manager_evolution_paths(kind, run_id)
    if run_path.exists():
        run_path.unlink()
    if index_path.exists() and run_id in index_path.read_text(encoding="utf-8"):
        if original_index_text is None:
            index_path.unlink()
        else:
            index_path.write_text(original_index_text, encoding="utf-8")

def _reset_self_evolution_live_state() -> None:
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None

def test_evolution_routes_use_real_supervised_records(tmp_path, monkeypatch):
    pending_result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="web_pending_episode",
    )
    _write_supervised_decision_record(
        tmp_path,
        "web_pending_run",
        {
            "decision": "PROMOTE",
            "reason": "候选方案值得继续进入治理流程。",
            "gates": [
                {
                    "name": "gym_promotion",
                    "status": "pass",
                    "reason": "proposal created",
                    "metrics": {
                        "promotion_proposal_path": pending_result.promotion_proposal_path,
                        "decision_path": pending_result.decision_path,
                    },
                }
            ],
        },
    )

    active_result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="web_active_episode",
    )
    apply_gym_promotion_proposal(active_result.promotion_proposal_path, project_root=tmp_path)
    activation = activate_gym_promotion_proposal(active_result.promotion_proposal_path, project_root=tmp_path)
    _write_supervised_decision_record(
        tmp_path,
        "web_active_run",
        {
            "decision": "PROMOTE",
            "reason": "候选方案已成为当前建议基线。",
            "gates": [
                {
                    "name": "gym_promotion",
                    "status": "pass",
                    "reason": "proposal activated",
                    "metrics": {
                        "promotion_proposal_path": active_result.promotion_proposal_path,
                        "decision_path": active_result.decision_path,
                    },
                }
            ],
            "advisory_context": {
                "active_count": 1,
                "entries": [
                    {
                        "target_key": activation.target_key,
                        "target_label": "local_transaction_closing_v1",
                        "proposal_id": activation.proposal_id,
                        "runtime_effect": "not_applied",
                        "agent_consumption": "advisory",
                    }
                ],
            },
        },
    )
    _write_workbench_state(
        tmp_path,
        {
            "source": "dataset",
            "dataset_name": "custom_prompt_jsonl",
            "dataset_limit": 2,
            "bundle_name": "custom_prompt_jsonl_v1",
            "keep_worktree": True,
        },
    )

    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    overview_response = client.get("/api/evolution/overview")
    runs_response = client.get("/api/evolution/runs")
    library_response = client.get("/api/evolution/library")

    assert overview_response.status_code == 200
    assert runs_response.status_code == 200
    assert library_response.status_code == 200

    overview_payload = overview_response.json()
    runs_payload = runs_response.json()
    library_payload = library_response.json()

    assert overview_payload["currentStatus"]["decision"] == "PROMOTE"
    assert overview_payload["currentStatus"]["proposalStatus"] == "active"
    assert overview_payload["currentStatus"]["runtimeEffect"] == "not_applied"
    assert overview_payload["currentStatus"]["runSemantics"]["runStatus"] == "success"
    assert overview_payload["currentStatus"]["outcomeSemantics"]["proposalStatusLabel"]
    assert overview_payload["currentStatus"]["actionStates"]["delete"]["enabled"] is False
    assert overview_payload["workbench"]["source"] == "dataset"
    assert overview_payload["workbench"]["datasetName"] == "custom_prompt_jsonl"
    assert overview_payload["recentRuns"][0]["id"] == "web_active_run"
    assert runs_payload[0]["proposalStatus"] == "active"
    assert runs_payload[0]["decision"] == "PROMOTE"
    assert runs_payload[0]["runtimeEffect"] == "not_applied"
    assert runs_payload[0]["outcomeSemantics"]["runtimeEffect"] == "not_applied"
    assert runs_payload[0]["actionStates"]["delete"]["enabled"] is False
    _assert_seeded_case_diagnostic(runs_payload[0]["caseDiagnostics"][0])
    assert any(item["sourceRun"] == "web_active_run" for item in library_payload["items"])
    assert any(item["sourceRun"] == "web_pending_run" for item in library_payload["pending"])
    assert library_payload["items"][0]["proposalStatus"] == "active"
    assert library_payload["pending"][0]["proposalStatus"] == "proposed"
    assert library_payload["items"][0]["outcomeSemantics"]["proposalStatus"] == "active"

def test_evolution_runs_route_exposes_case_type_and_expected_outcome(tmp_path, monkeypatch):
    _write_supervised_decision_record(
        tmp_path,
        "web_dynamic_case_schema",
        {
            "case_summaries": [
                {
                    "case_id": "dynamic_calendar_change",
                    "case_type": "dynamic_replanning",
                    "baseline_status": "success",
                    "candidate_status": "success",
                    "decision_signal": "stable_success",
                    "difference_summary": "dynamic case stayed stable",
                    "failure_taxonomy": ["dynamic_replanning_case", "post_adaptation_verification_missing"],
                    "intake_provenance": {
                        "case_type": "dynamic_replanning",
                        "expected_final_state": {"calendar_event": "rescheduled"},
                        "dynamic_events": [{"event": "deadline_changed"}],
                    },
                },
                {
                    "case_id": "impossible_missing_permission",
                    "case_type": "impossible_task",
                    "baseline_status": "success",
                    "candidate_status": "success",
                    "decision_signal": "stable_success",
                    "difference_summary": "impossible case stayed stable",
                    "failure_taxonomy": ["impossible_task_case"],
                    "intake_provenance": {
                        "case_type": "impossible_task",
                        "expected_infeasible_outcome": {"status": "infeasible", "reason": "missing_permission"},
                    },
                },
            ],
        },
    )
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    response = client.get("/api/evolution/runs")

    assert response.status_code == 200
    diagnostics = response.json()[0]["caseDiagnostics"]
    by_case = {item["caseId"]: item for item in diagnostics}
    assert by_case["dynamic_calendar_change"]["caseType"] == "dynamic_replanning"
    assert by_case["dynamic_calendar_change"]["expectedFinalState"]["calendar_event"] == "rescheduled"
    assert by_case["dynamic_calendar_change"]["dynamicEvents"][0]["event"] == "deadline_changed"
    assert by_case["impossible_missing_permission"]["caseType"] == "impossible_task"
    assert by_case["impossible_missing_permission"]["expectedInfeasibleOutcome"]["status"] == "infeasible"

def test_evolution_runs_route_labels_inconclusive_as_complete_terminal_result(tmp_path, monkeypatch):
    _write_supervised_decision_record(
        tmp_path,
        "web_inconclusive_run",
        {
            "decision": "INCONCLUSIVE",
            "reason": "baseline 与 candidate 都存在监督边界异常，当前评测无法证明候选退化",
            "baseline_success_rate": 0.0,
            "candidate_success_rate": 0.0,
        },
    )
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/evolution/runs")

    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["id"] == "web_inconclusive_run"
    assert payload["decision"] == "INCONCLUSIVE"
    assert payload["status"] == "inconclusive"
    assert payload["runSemantics"]["runStatus"] == "inconclusive"
    assert payload["runSemantics"]["runStatusLabel"] == "评测完成 · 无结论"
    assert "等待" not in payload["runSemantics"]["runStatusLabel"]

def test_evolution_routes_handle_empty_supervised_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    overview_response = client.get("/api/evolution/overview")
    runs_response = client.get("/api/evolution/runs")
    library_response = client.get("/api/evolution/library")

    assert overview_response.status_code == 200
    assert runs_response.status_code == 200
    assert library_response.status_code == 200
    assert overview_response.json()["currentStatus"]["state"] == "idle"
    assert overview_response.json()["workbench"]["source"] == "unknown"
    assert runs_response.json() == []
    assert library_response.json() == {"items": [], "pending": []}

def test_evolution_workspace_snapshot_combines_dashboard_payloads(tmp_path, monkeypatch):
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(self_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(self_evolution_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(evolution_routes, "get_latest_self_evolution_run", lambda: pytest.fail("default snapshot should not load self latest run"))
    monkeypatch.setattr(evolution_routes, "list_self_evolution_transactions", lambda: [])
    monkeypatch.setattr(evolution_routes, "get_latest_supervised_run", lambda **kwargs: None)
    monkeypatch.setattr(
        evolution_routes,
        "current_supervised_agent_bindings_snapshot",
        lambda: {
            "agentBindings": {},
            "bindingSource": "current_agent_config",
            "status": "error",
            "issues": [],
        },
    )
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    response = client.get("/api/evolution/workspace-snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overview"]["currentStatus"]["state"] == "idle"
    assert payload["runs"] == []
    assert payload["library"] == {"items": [], "pending": []}
    assert "bundles" in payload["workbench"]
    assert payload["activeRun"] is None
    assert payload["latestRun"] is None
    assert payload["currentAgentBindings"] == {}
    assert payload["currentAgentBindingSource"] == "current_agent_config"
    assert payload["currentAgentBindingStatus"] == "error"
    assert payload["currentAgentBindingIssues"] == []
    assert payload["worktreeActiveRun"] is None
    assert payload["worktreeRuns"] == []
    assert payload["selfOverview"]["enabled"] in {True, False}
    assert payload["selfLatestRun"] is None
    assert payload["selfTransactions"] == []

def test_evolution_workspace_snapshot_keeps_current_agent_bindings_separate_from_latest_run(monkeypatch):
    monkeypatch.setattr(
        evolution_routes,
        "get_evolution_workspace_dashboard",
        lambda: {
            "overview": {"currentStatus": {"state": "idle"}, "recentRuns": []},
            "runs": [],
            "library": {"items": [], "pending": []},
        },
    )
    monkeypatch.setattr(evolution_routes, "get_supervised_workbench", lambda **kwargs: {"activeRun": None})
    monkeypatch.setattr(evolution_routes, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        evolution_routes,
        "get_latest_supervised_run",
        lambda **kwargs: {
            "runId": "old-run",
            "status": "cancelled",
            "agentBindings": {
                "baseline": {
                    "agentId": "agent-old",
                    "dialogueModelId": "xiaomi_mimo_v2_5_pro_token_plan",
                }
            },
        },
    )
    monkeypatch.setattr(
        evolution_routes,
        "current_supervised_agent_bindings_snapshot",
        lambda: {
            "agentBindings": {
                "baseline": {
                    "agentId": "agent-current",
                    "dialogueModelId": "mimo_v2_5",
                    "dialogueModelLabel": "小米 MiMo V2.5",
                }
            },
            "bindingSource": "current_agent_config",
            "status": "ready",
            "issues": [],
        },
    )
    monkeypatch.setattr(evolution_routes, "get_active_supervised_worktree_run", lambda: None)
    monkeypatch.setattr(evolution_routes, "list_supervised_worktree_runs", lambda: [])
    monkeypatch.setattr(evolution_routes, "get_self_evolution_light_overview", lambda: {"enabled": True})
    monkeypatch.setattr(evolution_routes, "get_latest_self_evolution_run", lambda: None)
    monkeypatch.setattr(evolution_routes, "list_self_evolution_transactions", lambda: [])
    monkeypatch.setattr(evolution_routes, "record_evolution_workspace_snapshot_perf", lambda **kwargs: None)

    response = client.get("/api/evolution/workspace-snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["latestRun"]["agentBindings"]["baseline"]["dialogueModelId"] == "xiaomi_mimo_v2_5_pro_token_plan"
    assert payload["currentAgentBindings"]["baseline"]["agentId"] == "agent-current"
    assert payload["currentAgentBindings"]["baseline"]["dialogueModelId"] == "mimo_v2_5"
    assert payload["currentAgentBindingStatus"] == "ready"

def test_evolution_workspace_snapshot_reuses_supervised_dashboard_scan(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(
        evolution_routes,
        "get_evolution_workspace_dashboard",
        lambda: calls.append("dashboard") or {
            "overview": {"currentStatus": {"state": "idle"}, "recentRuns": []},
            "runs": [],
            "library": {"items": [], "pending": []},
        },
    )
    def fake_get_supervised_workbench(**kwargs):
        assert kwargs == {
            "active_run": None,
            "active_run_loaded": True,
            "include_catalog": False,
            "saved_state": None,
        }
        return {"bundles": [], "datasets": [], "activeRun": {"runId": "active-1", "status": "running"}}

    monkeypatch.setattr(evolution_routes, "get_supervised_workbench", fake_get_supervised_workbench)
    monkeypatch.setattr(evolution_routes, "get_active_supervised_run", lambda: calls.append("active") or None)
    monkeypatch.setattr(evolution_routes, "get_latest_supervised_run", lambda **kwargs: kwargs.get("active_run"))
    monkeypatch.setattr(evolution_routes, "get_active_supervised_worktree_run", lambda: None)
    monkeypatch.setattr(evolution_routes, "list_supervised_worktree_runs", lambda: [])
    monkeypatch.setattr(evolution_routes, "get_self_evolution_light_overview", lambda: {"enabled": True, "goal": "light"})
    monkeypatch.setattr(evolution_routes, "get_self_evolution_overview", lambda: pytest.fail("default snapshot should be light"))
    monkeypatch.setattr(evolution_routes, "get_latest_self_evolution_run", lambda: None)
    monkeypatch.setattr(evolution_routes, "list_self_evolution_transactions", lambda: pytest.fail("default snapshot should not load transactions"))
    monkeypatch.setattr(
        evolution_routes,
        "current_supervised_agent_bindings_snapshot",
        lambda: {"agentBindings": {}, "bindingSource": "current_agent_config", "status": "error", "issues": []},
    )
    monkeypatch.setattr(evolution_routes, "record_evolution_workspace_snapshot_perf", lambda **kwargs: None)

    response = client.get("/api/evolution/workspace-snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeRun"]["runId"] == "active-1"
    assert payload["latestRun"]["runId"] == "active-1"
    assert calls == ["dashboard", "active"]

def test_evolution_workspace_snapshot_can_include_full_self_payload(monkeypatch):
    monkeypatch.setattr(
        evolution_routes,
        "get_evolution_workspace_dashboard",
        lambda: {
            "overview": {"currentStatus": {"state": "idle"}, "recentRuns": []},
            "runs": [],
            "library": {"items": [], "pending": []},
        },
    )
    monkeypatch.setattr(evolution_routes, "get_supervised_workbench", lambda **kwargs: {"activeRun": None})
    monkeypatch.setattr(evolution_routes, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(evolution_routes, "get_latest_supervised_run", lambda **kwargs: None)
    monkeypatch.setattr(evolution_routes, "get_active_supervised_worktree_run", lambda: None)
    monkeypatch.setattr(evolution_routes, "list_supervised_worktree_runs", lambda: [])
    monkeypatch.setattr(evolution_routes, "get_self_evolution_light_overview", lambda: pytest.fail("includeSelf should request full overview"))
    monkeypatch.setattr(evolution_routes, "get_self_evolution_overview", lambda: {"enabled": True, "goal": "full"})
    monkeypatch.setattr(evolution_routes, "get_latest_self_evolution_run", lambda: {"runId": "self-latest"})
    monkeypatch.setattr(evolution_routes, "list_self_evolution_transactions", lambda: [{"txnId": "txn-1"}])
    monkeypatch.setattr(
        evolution_routes,
        "current_supervised_agent_bindings_snapshot",
        lambda: {"agentBindings": {}, "bindingSource": "current_agent_config", "status": "error", "issues": []},
    )
    monkeypatch.setattr(evolution_routes, "record_evolution_workspace_snapshot_perf", lambda **kwargs: None)

    response = client.get("/api/evolution/workspace-snapshot", params={"includeSelf": "true"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["selfOverview"]["goal"] == "full"
    assert payload["selfLatestRun"]["runId"] == "self-latest"
    assert payload["selfTransactions"] == [{"txnId": "txn-1"}]

def test_evolution_workspace_snapshot_slow_event_includes_stage_timings(monkeypatch):
    recorded_events: list[dict] = []

    def fake_record_runtime_scene_event(component, phase, event_code, **kwargs):
        recorded_events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **kwargs,
            }
        )
        return {"accepted": True}

    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", fake_record_runtime_scene_event)
    monkeypatch.setattr(evolution_service, "EVOLUTION_WORKSPACE_SNAPSHOT_WAS_SLOW", False)

    evolution_service.record_evolution_workspace_snapshot_perf(
        duration_ms=1500,
        timings_ms={"dashboard": 400.4, "workbench": 700.2, "total": 1500.1},
        payload={
            "overview": {"recentRuns": [{}, {}]},
            "runs": [{}],
            "library": {"items": [{}, {}], "pending": [{}]},
            "worktreeRuns": [{}],
            "selfTransactions": [],
        },
        include_self=False,
    )

    assert recorded_events
    event = recorded_events[-1]
    assert event["component"] == "evolution_service"
    assert event["phase"] == "workspace_snapshot"
    assert event["eventCode"] == "evolution.workspace_snapshot.slow"
    assert event["fields"]["timingsMs"]["workbench"] == 700.2
    assert event["fields"]["libraryItemCount"] == 2
    assert event["fields"]["includeSelf"] is False

def test_evolution_library_exposes_self_evolution_candidates_as_pending_review_source(tmp_path, monkeypatch):
    append_candidate_record(
        {
            "candidate_id": "prompt_candidate:web-self-review",
            "candidate_type": "prompt_candidate",
            "source_experience_id": "exp-review",
            "source_reflection_id": "refl-review",
            "source_run_id": "web-self-review",
            "txn_id": "txn-review",
            "provenance": {
                "source_experience_id": "exp-review",
                "source_reflection_id": "refl-review",
                "source_run_id": "web-self-review",
                "txn_id": "txn-review",
                "evidence_refs": ["logs/runtime_scenes/pkg/agent/self_evolution_runs/web-self-review.jsonl"],
            },
            "payload": {
                "suggested_prompt_change": "Ask for the smallest bounded validation before retrying.",
            },
            "risk_level": "medium",
            "allowed_downstream_uses": ["supervised_review", "accepted_baseline", "runtime_prompt_override"],
            "blocked_downstream_uses": [],
        },
        project_root=tmp_path,
    )
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    queue_response = client.get("/api/evolution/self/candidates")
    library_response = client.get("/api/evolution/library")
    detail_response = client.get("/api/evolution/proposals/prompt_candidate:web-self-review")

    assert queue_response.status_code == 200
    assert library_response.status_code == 200
    assert detail_response.status_code == 200
    queue_payload = queue_response.json()
    library_payload = library_response.json()
    detail_payload = detail_response.json()
    item = queue_payload["items"][0]

    assert queue_payload["enabled"] is True
    assert queue_payload["pendingCount"] == 1
    assert queue_payload["counts"]["prompt_candidate"] == 1
    assert item["id"] == "prompt_candidate:web-self-review"
    assert item["sourceRun"] == item["id"]
    assert item["sourceSelfRunId"] == "web-self-review"
    assert item["ingestMode"] == "self_evolution_candidate"
    assert item["candidateType"] == "prompt_candidate"
    assert item["proposalStatus"] == "self_candidate_pending"
    assert item["reviewState"] == "pending"
    assert item["riskLevel"] == "medium"
    assert item["supervisedRequired"] is True
    assert item["candidateOnly"] is True
    assert item["autoApply"] is False
    assert item["canDelete"] is False
    assert item["availableActions"] == []
    assert item["actionStates"]["apply"]["enabled"] is False
    assert item["outcomeSemantics"]["isRuntimeApplied"] is False
    assert item["outcomeSemantics"]["decisionLabel"] == "待监督审阅"
    assert item["outcomeSemantics"]["proposalStatusLabel"] == "自进化候选待审阅"
    assert "accepted_baseline" not in item["allowedDownstreamUses"]
    assert "runtime_prompt_override" not in item["allowedDownstreamUses"]
    assert "accepted_baseline" in item["blockedDownstreamUses"]
    assert "selection_policy" in item["blockedDownstreamUses"]
    assert item["provenance"]["source_run_id"] == "web-self-review"
    assert item["evidenceRefs"] == ["logs/runtime_scenes/pkg/agent/self_evolution_runs/web-self-review.jsonl"]
    assert any(pending["id"] == item["id"] for pending in library_payload["pending"])
    assert next(pending for pending in library_payload["pending"] if pending["id"] == item["id"])["riskLevel"] == "medium"
    assert library_payload["items"] == []
    assert detail_payload["sessionId"] == item["id"]
    assert detail_payload["sourceRun"] == item["id"]
    assert detail_payload["canEdit"] is False
    assert detail_payload["canDelete"] is False
    assert detail_payload["availableActions"] == []
    assert any("web-self-review" in note for note in detail_payload["review"]["whyCreated"])
    assert not any("来源自进化运行：prompt_candidate:web-self-review" in note for note in detail_payload["review"]["whyCreated"])
    assert detail_payload["proposalStatus"] == "self_candidate_pending"
    assert detail_payload["proposal"]["status"] == "self_candidate_pending"
    assert detail_payload["outcomeSemantics"]["isRuntimeApplied"] is False
    assert detail_payload["outcomeSemantics"]["decisionLabel"] == "待监督审阅"
    assert detail_payload["supervised"]["riskLevel"] == "medium"
    assert detail_payload["paths"]["selfEvolutionCandidatePath"].endswith("prompt_candidates.jsonl")
    assert detail_payload["rawProposal"]["candidate_id"] == item["id"]

def test_self_evolution_candidate_review_route_hides_when_self_evolution_disabled(tmp_path, monkeypatch):
    append_candidate_record(
        {
            "candidate_id": "skill_candidate:hidden",
            "candidate_type": "skill_candidate",
            "source_experience_id": "exp-hidden",
            "source_reflection_id": "refl-hidden",
            "source_run_id": "web-self-hidden",
            "provenance": {
                "source_experience_id": "exp-hidden",
                "source_reflection_id": "refl-hidden",
                "source_run_id": "web-self-hidden",
                "evidence_refs": ["reflection:web-self-hidden"],
            },
        },
        project_root=tmp_path,
    )
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "modeAvailability": {
                "chat": True,
                "self_evolution": False,
                "supervised_evolution": True,
            }
        },
    )

    queue_response = client.get("/api/evolution/self/candidates")
    library_response = client.get("/api/evolution/library")

    assert queue_response.status_code == 200
    assert queue_response.json()["enabled"] is False
    assert queue_response.json()["pendingCount"] == 0
    assert queue_response.json()["items"] == []
    assert library_response.json() == {"items": [], "pending": []}

def test_self_evolution_candidate_review_route_normalizes_legacy_risk(tmp_path, monkeypatch):
    append_candidate_record(
        {
            "candidate_id": "proposal_candidate:legacy-risk",
            "candidate_type": "proposal_candidate",
            "source_experience_id": "exp-legacy-risk",
            "source_run_id": "web-self-legacy-risk",
            "risk_level": "accepted",
            "provenance": {
                "source_experience_id": "exp-legacy-risk",
                "source_run_id": "web-self-legacy-risk",
                "evidence_refs": ["reflection:web-self-legacy-risk"],
            },
        },
        project_root=tmp_path,
    )
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            }
        },
    )

    response = client.get("/api/evolution/self/candidates")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["riskLevel"] == "pending_review"

def test_evolution_workbench_route_exposes_dataset_choices_and_saved_state(tmp_path, monkeypatch):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "real_bundle_v1.json").write_text(
        json.dumps(
            {
                "bundle_name": "real_bundle_v1",
                "benchmark": "dry",
                "cases": [{"case_id": "probe", "prompt": "run"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (bundle_dir / "saved_bundle_v1.json").write_text(
        json.dumps(
            {
                "bundle_name": "saved_bundle_v1",
                "benchmark": "saved",
                "cases": [{"case_id": "saved", "prompt": "run saved"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_workbench_state(
        tmp_path,
        {
            "source": "bundle",
            "bundle_name": "saved_bundle_v1",
            "keep_worktree": False,
        },
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "core.evaluation.dataset_adapters.preflight_environment_contract",
        lambda *args, **kwargs: {
            "status": "available",
            "available": True,
            "checked": [],
            "missing": [],
            "official_verifier": {"missing": [], "available": True},
        },
    )

    response = client.get("/api/evolution/workbench")

    assert response.status_code == 200
    payload = response.json()
    assert payload["defaultBundleName"]
    assert payload["savedState"]["source"] == "bundle"
    assert payload["savedState"]["bundleName"] == "saved_bundle_v1"
    assert {
        "name": "real_bundle_v1",
        "declaredName": "real_bundle_v1",
        "path": str(bundle_dir / "real_bundle_v1.json"),
        "caseCount": 1,
        "benchmark": "dry",
    } in payload["bundles"]
    assert {item["name"] for item in payload["datasets"]} == {
        "supervised_dry_run",
        "terminal_bench_smoke",
        "terminal_bench_core",
        "terminal_bench_agent_judged",
    }
    dry_run = next(item for item in payload["datasets"] if item["name"] == "supervised_dry_run")
    assert dry_run["effective"] is True
    assert dry_run["caseCount"] >= 1
    assert dry_run["usabilityStatus"] == "ready"
    assert dry_run["visibility"] == "primary"
    assert dry_run["selectable"] is True
    terminal_smoke = next(item for item in payload["datasets"] if item["name"] == "terminal_bench_smoke")
    assert terminal_smoke["effective"] is True
    assert terminal_smoke["selectable"] is True
    assert terminal_smoke["adapterStatus"] == "ready_local_smoke"
    assert "terminal-bench" in terminal_smoke["tags"]
    terminal_core = next(item for item in payload["datasets"] if item["name"] == "terminal_bench_core")
    assert terminal_core["usabilityStatus"] == "custom_harness_ready"
    assert terminal_core["evaluationMode"] == "custom_harness"
    assert terminal_core["officialVerifierStatus"] == "harbor_pending"
    assert terminal_core["officialScoreAvailable"] is False
    assert "不是 Terminal-Bench 官方成绩" in terminal_core["usabilityReason"]
    agent_judged = next(item for item in payload["datasets"] if item["name"] == "terminal_bench_agent_judged")
    assert agent_judged["effective"] is True
    assert agent_judged["selectable"] is True
    assert agent_judged["adapterStatus"] == "agent_harness_ready"
    assert agent_judged["evaluationMode"] == "agent_judged"
    assert agent_judged["officialVerifierStatus"] == "not_required"
    assert agent_judged["officialScoreAvailable"] is False
    assert "纯 agent" in agent_judged["usabilityReason"]
    assert payload["activeRun"] is None

def test_evolution_workbench_route_falls_back_from_stale_saved_bundle(tmp_path, monkeypatch):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "real_bundle_v1.json").write_text(
        json.dumps(
            {
                "bundle_name": "real_bundle_v1",
                "benchmark": "dry",
                "cases": [{"case_id": "probe", "prompt": "run"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_workbench_state(
        tmp_path,
        {
            "source": "bundle",
            "bundle_name": "demo_bundle",
            "dataset_name": "missing_dataset",
            "keep_worktree": False,
        },
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/evolution/workbench")

    assert response.status_code == 200
    payload = response.json()
    assert payload["savedState"]["source"] == "bundle"
    assert payload["savedState"]["bundleName"] == "real_bundle_v1"
    assert payload["savedState"]["datasetName"] in {"", "supervised_dry_run"}
    assert any(item["name"] == "real_bundle_v1" for item in payload["bundles"])
    assert not any(item["name"] == "demo_bundle" for item in payload["bundles"])

@pytest.mark.slow
def test_supervised_worktree_run_routes_start_and_list_simulation(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-worktree-start", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-worktree-start",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "closed_loop_v1.json").write_text(
        json.dumps(
            {
                "bundle_name": "closed_loop_v1",
                "benchmark": "unit",
                "cases": [
                    {"case_id": "one", "prompt": "one"},
                    {"case_id": "two", "prompt": "two"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(supervised_worktree_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(
        supervised_worktree_evolution_service,
        "_raise_if_lease_conflict",
        lambda *, lang: None,
    )

    class ImmediateExecutor:
        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return None

    def fake_worktree_factory(root: Path, run_id: str) -> dict:
        candidate = tmp_path.parent / f"supervised-worktree-{run_id}"
        candidate.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=str(candidate), check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.local"], cwd=str(candidate), check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(candidate), check=True)
        for source in tmp_path.rglob("*"):
            if not source.is_file():
                continue
            rel = source.relative_to(tmp_path)
            if ".git" in rel.parts or rel.parts[0] == "candidate":
                continue
            target = candidate / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        subprocess.run(["git", "add", "."], cwd=str(candidate), check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=str(candidate), check=True, capture_output=True, text=True)
        (candidate / "agent.py").write_text("print('candidate')\n", encoding="utf-8")
        return {
            "path": str(candidate),
            "baseHead": "base",
            "checkpointCommit": "base",
            "checkpointRef": "",
            "trackedDirty": False,
            "untrackedFiles": [],
        }

    monkeypatch.setattr(supervised_worktree_evolution_service, "_RUN_EXECUTOR", ImmediateExecutor())
    monkeypatch.setattr(supervised_worktree_evolution_service, "_default_worktree_factory", fake_worktree_factory)

    start_response = client.post(
        "/api/evolution/worktree-runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "closed_loop_v1",
            "mode": "auto",
            "uiRoute": "/evolution?view=overview",
            "clientAction": "start_closed_loop_button",
        },
    )

    assert start_response.status_code == 202
    start_payload = start_response.json()
    run_id = start_payload["runId"]
    detail_response = client.get(f"/api/evolution/worktree-runs/{run_id}")
    list_response = client.get("/api/evolution/worktree-runs")

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["status"] == "done"
    assert detail_payload["decision"]["recommendedAction"] == "preserve"
    assert detail_payload["startRequest"] == {
        "requestSource": "api:evolution.worktree-runs",
        "uiRoute": "/evolution?view=overview",
        "initiator": "user",
        "clientAction": "start_closed_loop_button",
    }
    assert list_response.status_code == 200
    assert list_response.json()[0]["runId"] == run_id
    scene_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "supervised_worktree_run.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    started = next(event for event in scene_events if event["event_code"] == "supervised_worktree_run.started")
    assert started["fields"]["runId"] == run_id
    assert started["fields"]["requestSource"] == "api:evolution.worktree-runs"
    assert started["fields"]["uiRoute"] == "/evolution?view=overview"
    assert started["fields"]["clientAction"] == "start_closed_loop_button"
    assert "supervised_worktree_run.started" in (scene_dir / "lifecycle.jsonl").read_text(encoding="utf-8")

    child_log = scene_dir / "agent" / "supervised_worktree_runs" / f"{run_id}.jsonl"
    child_payloads = [
        json.loads(line)
        for line in child_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert child_payloads[0]["startRequest"]["requestSource"] == "api:evolution.worktree-runs"
    assert child_payloads[0]["startRequest"]["uiRoute"] == "/evolution?view=overview"


def test_supervised_worktree_run_route_get_run_cleanses_invalid_candidate_path(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    bad_candidate_path = tmp_path / "candidate-file.py"
    bad_candidate_path.write_text("print('legacy path')\n", encoding="utf-8")
    run_id = "swte-web-invalid-route"

    monkeypatch.setattr(supervised_worktree_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_worktree_evolution_service.work_run_store,
        "WORK_RUNS_DIR",
        tmp_path / "work_runs",
    )

    supervisor_snapshot = {
        "runId": run_id,
        "runKind": supervised_worktree_evolution_service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": {"path": str(bad_candidate_path), "preserved": True},
        "updatedAt": "2026-06-01T00:00:00+00:00",
    }
    supervised_worktree_evolution_service._persist_snapshot(supervisor_snapshot)

    response = client.get(f"/api/evolution/worktree-runs/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runId"] == run_id
    assert payload["candidateWorktree"]["pathValidationError"]
    assert "path" not in payload["candidateWorktree"]


def test_supervised_worktree_run_route_requires_real_llm_cost_confirmation(tmp_path, monkeypatch):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "closed_loop_v1.json").write_text(
        json.dumps(
            {
                "bundle_name": "closed_loop_v1",
                "benchmark": "unit",
                "cases": [{"case_id": "one", "prompt": "one"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(supervised_worktree_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_worktree_evolution_service,
        "_raise_if_lease_conflict",
        lambda *, lang: None,
    )

    response = client.post(
        "/api/evolution/worktree-runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "closed_loop_v1",
            "executionMode": "real",
            "confirmRealLlmCost": False,
        },
    )

    assert response.status_code == 422
    assert "tokens" in response.json()["detail"]

def test_chat_review_routes_list_and_approve_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)

    capture_service = ChatDatasetCaptureService(project_root=tmp_path)
    candidate = capture_service.capture_candidate(
        mode="chat",
        session_id="session-live",
        source_log_path=str(tmp_path / "log_info" / "conversation_session-live.jsonl"),
        turns=[
            ChatTurnRecord(
                turn_number=1,
                user_message="继续排查网页聊天提交链路",
                assistant_message="我先检查 session_service 里的真实提交路径。",
                tool_calls=["read_file_tool"],
                tool_call_count=1,
            ),
            ChatTurnRecord(
                turn_number=2,
                user_message="把根因和下一步说清楚",
                assistant_message="结论：网页聊天每轮都会重建 agent。下一步：把持久化消息重建成 turn 记录并接入审核。",
                tool_calls=["apply_patch_tool"],
                tool_call_count=1,
                had_explicit_conclusion=True,
                had_next_action=True,
            ),
        ],
    )

    assert candidate is not None

    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["pendingCount"] == 1
    assert queue_payload["positiveCount"] == 0
    assert queue_payload["negativeCount"] == 0
    assert queue_payload["discardCount"] == 0
    assert queue_payload["countsByStatus"] == {
        "pending": 1,
        "positive": 0,
        "negative": 0,
        "discard": 0,
    }
    assert queue_payload["lifecycle"]["rawChatDirectTrainingAllowed"] is False
    assert queue_payload["lifecycle"]["candidateStage"] == "pending_review"
    assert queue_payload["lifecycle"]["reviewedCaseStage"] == "reviewed_chat_case"
    assert queue_payload["lifecycle"]["datasetTarget"] == "chat_reviewed_multiturn"
    assert queue_payload["lifecycle"]["negativeTarget"] == "chat_negative_multiturn"
    assert "supervised_evaluation" in queue_payload["lifecycle"]["allowedDownstreamUses"]
    candidate_id = queue_payload["items"][0]["candidateId"]
    assert queue_payload["items"][0]["conversationTurns"] == []

    detail_response = client.get(f"/api/evolution/chat-review/{candidate_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["candidateId"] == candidate_id
    assert len(detail_payload["conversationTurns"]) == 2

    full_queue_response = client.get("/api/evolution/chat-review", params={"includeDetails": "true"})
    assert full_queue_response.status_code == 200
    assert len(full_queue_response.json()["items"][0]["conversationTurns"]) == 2

    decision_response = client.post(
        f"/api/evolution/chat-review/{candidate_id}/decision",
        json={
            "decision": "negative",
            "reviewerNote": "keep as an anti-pattern",
            "reasonCode": "missing_evidence",
            "errorType": "ungrounded_inference",
            "correctPrinciple": "inspect logs before concluding",
        },
    )

    assert decision_response.status_code == 200
    decision_payload = decision_response.json()
    assert decision_payload["status"] == "negative"

    paths = resolve_chat_dataset_paths(project_root=tmp_path)
    assert paths.negative_jsonl_path.exists()

    workbench_response = client.get("/api/evolution/workbench")
    assert workbench_response.status_code == 200
    assert "chat_reviewed_multiturn" not in {item["name"] for item in workbench_response.json()["datasets"]}

    reviewed_queue_response = client.get("/api/evolution/chat-review")
    assert reviewed_queue_response.status_code == 200
    reviewed_queue_payload = reviewed_queue_response.json()
    assert reviewed_queue_payload["pendingCount"] == 0
    assert reviewed_queue_payload["negativeCount"] == 1
    assert reviewed_queue_payload["negativeDatasetExists"] is True
    assert reviewed_queue_payload["negativeDatasetName"] == "chat_negative_multiturn"
    assert reviewed_queue_payload["lifecycle"]["rawChatDirectTrainingAllowed"] is False
    assert reviewed_queue_payload["lifecycle"]["negativeTarget"] == "chat_negative_multiturn"
    assert "gym_candidate_case" in reviewed_queue_payload["lifecycle"]["allowedDownstreamUses"]

    dataset_rows = list_dataset_status(tmp_path)
    dataset_entry = next(
        item for item in dataset_rows if item["name"] == "chat_reviewed_multiturn"
    )
    assert dataset_entry["available"] is True
    assert dataset_entry["review_required"] is True
    assert dataset_entry["source_track"] == "dialogue"
    assert dataset_entry["holdout_allowed"] is False
    assert dataset_entry["raw_chat_direct_training_allowed"] is False
    assert dataset_entry["visibility"] == "hidden"
    assert dataset_entry["workbench_visible"] is False
    assert "gym_candidate_case" in dataset_entry["allowed_downstream_uses"]

def test_chat_review_bulk_delete_discards_pending_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        chat_review_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    capture_service = ChatDatasetCaptureService(project_root=tmp_path)
    candidate_a = capture_service.capture_candidate(
        mode="chat",
        session_id="session-bulk-a",
        source_log_path=str(tmp_path / "log_info" / "conversation_session-bulk-a.jsonl"),
        turns=[
            ChatTurnRecord(
                turn_number=1,
                user_message="继续整理监督评审工作区",
                assistant_message="我先读取评审队列和样式文件确认现状。",
                tool_calls=["read_file_tool"],
                tool_call_count=1,
            ),
            ChatTurnRecord(
                turn_number=2,
                user_message="把批量删除做好",
                assistant_message="结论：批量删除应写成软丢弃。下一步我会补接口和测试。",
                tool_calls=["apply_patch_tool"],
                tool_call_count=1,
                had_explicit_conclusion=True,
                had_next_action=True,
            ),
        ],
    )
    candidate_b = capture_service.capture_candidate(
        mode="chat",
        session_id="session-bulk-b",
        source_log_path=str(tmp_path / "log_info" / "conversation_session-bulk-b.jsonl"),
        turns=[
            ChatTurnRecord(
                turn_number=1,
                user_message="复核一个已处理样本",
                assistant_message="我会先查队列状态再操作。",
                tool_calls=["read_file_tool"],
                tool_call_count=1,
            ),
            ChatTurnRecord(
                turn_number=2,
                user_message="这个作为正例",
                assistant_message="结论：这个样本具备稳定推进信号。下一步记录为正例。",
                tool_calls=["apply_patch_tool"],
                tool_call_count=1,
                had_explicit_conclusion=True,
                had_next_action=True,
            ),
        ],
    )
    assert candidate_a is not None
    assert candidate_b is not None

    positive_response = client.post(
        f"/api/evolution/chat-review/{candidate_b.candidate_id}/decision",
        json={"decision": "positive", "reviewerNote": "keep this handled sample"},
    )
    assert positive_response.status_code == 200

    response = client.post(
        "/api/evolution/chat-review/delete",
        json={
            "candidateIds": [
                candidate_a.candidate_id,
                candidate_a.candidate_id,
                candidate_b.candidate_id,
                "missing-candidate",
            ],
            "reviewerNote": "bulk discard from review workspace",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["requestedCount"] == 3
    assert payload["discardedCount"] == 1
    assert payload["skippedCount"] == 2
    assert payload["failedCount"] == 0
    results = {item["candidateId"]: item for item in payload["results"]}
    assert results[candidate_a.candidate_id]["status"] == "discarded"
    assert results[candidate_b.candidate_id]["status"] == "skipped"
    assert results["missing-candidate"]["status"] == "not_found"

    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["pendingCount"] == 0
    assert queue_payload["positiveCount"] == 1
    assert queue_payload["discardCount"] == 1
    statuses = {item["candidateId"]: item["status"] for item in queue_payload["items"]}
    assert statuses[candidate_a.candidate_id] == "discard"
    assert statuses[candidate_b.candidate_id] == "positive"

    paths = resolve_chat_dataset_paths(project_root=tmp_path)
    assert paths.rejected_log_path.exists()
    assert candidate_a.candidate_id in paths.rejected_log_path.read_text(encoding="utf-8")
    assert len(recorded_scene_events) == 1
    event_args, event_kwargs = recorded_scene_events[0]
    assert event_args[:3] == (
        "chat_review",
        "bulk_discard",
        "chat_review.bulk_discard.completed",
    )
    assert event_kwargs["fields"]["candidateIds"] == [
        candidate_a.candidate_id,
        candidate_b.candidate_id,
        "missing-candidate",
    ]
    assert event_kwargs["fields"]["discardedIds"] == [candidate_a.candidate_id]
    assert event_kwargs["fields"]["skippedIds"] == [candidate_b.candidate_id, "missing-candidate"]
    assert event_kwargs["fields"]["failedIds"] == []

def test_workbench_dataset_list_backfills_new_builtin_datasets(tmp_path, monkeypatch):
    registry_path = tmp_path / "workspace" / "evaluation" / "datasets" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "datasets": [
                    {
                        "name": "custom_prompt_jsonl",
                        "kind": "prompt_jsonl",
                        "bundle_name": "custom_prompt_jsonl_v1",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "core.evaluation.dataset_adapters.preflight_environment_contract",
        lambda *args, **kwargs: {
            "status": "available",
            "available": True,
            "checked": [],
            "missing": [],
            "official_verifier": {"missing": [], "available": True},
        },
    )

    response = client.get("/api/evolution/workbench")

    assert response.status_code == 200
    rows = response.json()["datasets"]
    names = {item["name"] for item in rows}
    assert names == {
        "supervised_dry_run",
        "terminal_bench_smoke",
        "terminal_bench_core",
        "terminal_bench_agent_judged",
    }
    assert not any(item["name"] == "generated_cases" for item in rows)
    assert not any(item["name"] == "chat_reviewed_multiturn" for item in rows)
    assert any(item["name"] == "terminal_bench_smoke" for item in rows)
    terminal_row = next(item for item in rows if item["name"] == "terminal_bench_smoke")
    assert terminal_row["effective"] is True
    assert terminal_row["selectable"] is True
    core_row = next(item for item in rows if item["name"] == "terminal_bench_core")
    agent_judged_row = next(item for item in rows if item["name"] == "terminal_bench_agent_judged")
    assert agent_judged_row["adapterStatus"] == "agent_harness_ready"
    assert agent_judged_row["selectable"] is True
    assert agent_judged_row["usabilityStatus"] == "agent_harness_ready"
    assert agent_judged_row["evaluationMode"] == "agent_judged"
    assert agent_judged_row["officialVerifierStatus"] == "not_required"
    assert agent_judged_row["officialScoreAvailable"] is False
    assert core_row["usabilityStatus"] == "custom_harness_ready"
    assert core_row["officialVerifierStatus"] == "harbor_pending"
    assert core_row["officialScoreAvailable"] is False

def test_start_supervised_run_from_dataset_exposes_active_snapshot_and_sse(tmp_path, monkeypatch):
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "custom_prompt_tasks.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps({"case_id": "case_1", "prompt": "fix bug"}) + "\n",
        encoding="utf-8",
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_agent_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "dataset",
            "datasetName": "custom_prompt_jsonl",
            "datasetLimit": 2,
            "keepWorktree": True,
            "mentalModelMode": "enabled",
        },
    )
    active_response = client.get("/api/evolution/active-run")
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["sourceKind"] == "dataset"
    assert payload["datasetName"] == "custom_prompt_jsonl"
    assert payload["bundleName"] == "custom_prompt_jsonl_v1_limit_2"
    assert payload["keepWorktree"] is True
    assert payload["mentalModelMode"] == "enabled"
    assert payload["mentalModelEnabled"] is True
    assert payload["agentBindings"]["baseline"]["role"] == "baseline"
    assert payload["agentBindings"]["candidate"]["role"] == "candidate"
    assert payload["agentBindings"]["baseline"]["dialogueModelId"]
    assert payload["agentBindings"]["candidate"]["dialogueModelId"]
    assert payload["agentBindings"]["baseline"]["llmBindings"]["dialogue"]["modelId"] == payload["agentBindings"]["baseline"]["dialogueModelId"]
    assert payload["agentBindings"]["candidate"]["llmBindings"]["dialogue"]["modelId"] == payload["agentBindings"]["candidate"]["dialogueModelId"]

    assert active_response.status_code == 200
    assert active_response.json()["runId"] == payload["runId"]
    assert active_response.json()["agentBindings"]["baseline"]["agentId"] == payload["agentBindings"]["baseline"]["agentId"]

    stream = supervised_control_service.stream_active_supervised_run_events(
        initial_snapshot=active_response.json()
    )
    raw_event = next(stream)
    stream.close()

    class _SingleEventResponse:
        def iter_lines(self):
            for line in str(raw_event).splitlines():
                yield line
            yield ""

    event = _read_first_sse_event(_SingleEventResponse())
    event_payload = json.loads(event["data"])
    assert event["event"] == "supervised_run"
    assert event_payload["snapshot"]["runId"] == payload["runId"]
    assert event_payload["snapshot"]["status"] == "queued"
    assert event_payload["snapshot"]["agentBindings"]["baseline"]["agentId"] == payload["agentBindings"]["baseline"]["agentId"]

    supervised_control_service._handle_progress_event(
        payload["runId"],
        {
            "event": "role_start",
            "session_id": "supervised-demo",
            "case_index": 1,
            "case_total": 1,
            "case_id": "case_1",
            "role": "baseline",
            "scenario": "transaction",
            "mode": "single_turn",
            "prompt": "fix bug",
            "agent_binding": payload["agentBindings"]["baseline"],
        },
    )
    progress_snapshot = supervised_control_service.get_supervised_run_snapshot(payload["runId"])
    assert progress_snapshot["currentAgentBinding"]["agentId"] == payload["agentBindings"]["baseline"]["agentId"]
    assert progress_snapshot["eventTail"][-1]["agentBinding"]["role"] == "baseline"
    assert progress_snapshot["eventTail"][-1]["agentBinding"]["dialogueModelId"] == payload["agentBindings"]["baseline"]["dialogueModelId"]

    state_path = tmp_path / "workspace" / "supervised_evolution" / "workbench_state.json"
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "custom_prompt_jsonl_v1_limit_2.json"
    assert state_path.exists()
    assert bundle_path.exists()

    _reset_supervised_live_state()

def test_active_supervised_run_events_is_quiet_when_no_active_run():
    _reset_supervised_live_state()

    response = client.get("/api/evolution/active-run/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

def test_latest_supervised_run_route_returns_latest_finished_snapshot():
    _reset_supervised_live_state()
    run_id = "web-supervised-latest-visible"
    _, index_path = _real_runtime_manager_evolution_paths("supervised", run_id)
    original_index_text = _read_optional_text(index_path)
    try:
        supervised_control_service.persist_manager_run_snapshot(
            "supervised",
            {
                "runId": run_id,
                "status": "done",
                "decision": "ROLLBACK",
                "decisionPath": "workspace/supervised_evolution/decisions/supervised_latest_visible.json",
                "startedAt": "2026-06-03T01:30:00Z",
                "endedAt": "2026-06-03T01:34:16Z",
                "updatedAt": "2026-06-03T01:34:16Z",
                "summary": "baseline failed; candidate failed",
                "diagnosis": "事务探针未关账",
                "eventTail": [
                    {
                        "event": "run_completed",
                        "status": "done",
                        "decision": "ROLLBACK",
                        "timestamp": "2026-06-03T01:34:16Z",
                    }
                ],
            },
            active_run_id="",
        )

        response = client.get("/api/evolution/latest-run")

        assert response.status_code == 200
        payload = response.json()
        assert payload["runId"] == run_id
        assert payload["status"] == "done"
        assert payload["decision"] == "ROLLBACK"
        assert payload["diagnosis"] == "事务探针未关账"
        assert payload["eventTail"][-1]["event"] == "run_completed"
        assert payload["actionStates"]["retry"]["enabled"] is True
        assert payload["actionStates"]["terminate"]["enabled"] is False
    finally:
        _restore_real_runtime_index_if_touched("supervised", run_id, original_index_text)
        _reset_supervised_live_state()

def test_start_supervised_run_reports_stale_agent_slot_as_validation_error(tmp_path, monkeypatch):
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "custom_prompt_tasks.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps({"case_id": "case_1", "prompt": "fix bug"}) + "\n",
        encoding="utf-8",
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_agent_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: pytest.fail("stale Agent slot must block before run submission"),
    )
    supervised_agent_service.ensure_supervised_agent_instances()
    replacement = agent_directory_service.create_agent_instance(
        display_name="已归档的基线 Agent",
        primary_mode="supervised_evolution",
        role_key="baseline",
        prompt_template_id="prompt-supervised-baseline",
    )
    current = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    slots = dict(current["slots"])
    slots["baseline"] = replacement["agentId"]
    agent_mode_binding_service.update_mode_binding("supervised_evolution", slots=slots)
    agent_directory_service.archive_agent_instance(replacement["agentId"], repair_mode_bindings=False)

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "dataset",
            "datasetName": "custom_prompt_jsonl",
            "datasetLimit": 1,
            "keepWorktree": True,
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "baseline" in detail
    assert replacement["agentId"] in detail

def test_start_supervised_run_from_web_does_not_write_real_runtime_manager_store(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}),
        encoding="utf-8",
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )
    monkeypatch.setattr(supervised_control_service, "_publish_run_snapshot", lambda run_id, terminal=False: None)

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    assert response.status_code == 202
    run_id = response.json()["runId"]
    run_path, index_path = _real_runtime_manager_evolution_paths("supervised", run_id)
    original_index_text = _read_optional_text(index_path)

    try:
        active_response = client.get("/api/evolution/active-run")

        assert active_response.status_code == 200
        assert active_response.json()["runId"] == run_id
        assert not run_path.exists()
        current_index_text = _read_optional_text(index_path)
        assert current_index_text is None or run_id not in current_index_text
    finally:
        _restore_real_runtime_index_if_touched("supervised", run_id, original_index_text)
        _reset_supervised_live_state()

def test_start_supervised_run_live_manager_route_returns_accepted_without_waiting(monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(supervised_control_service, "_ensure_runtime_manager_daemon", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        supervised_control_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)) or {"commandId": "cmd-web-start"},
    )
    monkeypatch.setattr(
        supervised_control_service,
        "wait_for_result",
        lambda command_id, *, timeout_seconds=60: pytest.fail("accepted submission must not poll for command completion"),
    )
    monkeypatch.setattr(
        supervised_control_service,
        "_load_immediate_runtime_manager_command_result",
        lambda command_id: calls.append(("immediate", command_id)) or None,
    )

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["commandId"] == "cmd-web-start"
    assert payload["commandType"] == "start_supervised_run"
    assert payload["status"] == "queued"
    assert calls[0] == "ensure"
    assert calls[1] == (
        "start_supervised_run",
        {
            "payload": {
                "sourceKind": "bundle",
                "datasetName": "",
                "datasetLimit": None,
                "bundleName": "manual_bundle",
                "keepWorktree": False,
                "mentalModelMode": "follow",
            }
        },
        "web_ui",
    )
    assert calls[2] == ("immediate", "cmd-web-start")

def test_supervised_run_command_status_surfaces_live_manager_failure(tmp_path, monkeypatch):
    results_dir = tmp_path / ".runtime" / "runtime-manager" / "results"
    results_dir.mkdir(parents=True)
    monkeypatch.setattr(supervised_control_service, "RESULTS_DIR", results_dir)
    (results_dir / "cmd-web-start.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-web-start",
                "accepted": True,
                "completed": True,
                "ok": False,
                "message": "Supervised role Agent dialogue model has no configured API key: baseline",
                "errorType": "SupervisedAgentBindingError",
            }
        ),
        encoding="utf-8",
    )

    response = client.get("/api/evolution/runs/commands/cmd-web-start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["commandId"] == "cmd-web-start"
    assert payload["completed"] is True
    assert payload["ok"] is False
    assert payload["status"] == "failed"
    assert payload["errorType"] == "SupervisedAgentBindingError"
    assert "baseline" in payload["message"]

def test_supervised_run_command_status_rejects_invalid_command_id(tmp_path, monkeypatch):
    monkeypatch.setattr(supervised_control_service, "RESULTS_DIR", tmp_path / "results")

    response = client.get("/api/evolution/runs/commands/cmd.bad")

    assert response.status_code == 422

def test_start_supervised_run_from_bundle_uses_launchable_file_stem(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "launchable_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps({"bundle_name": "declared_inside_json", "cases": [{"case_id": "case_1"}]}),
        encoding="utf-8",
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "launchable_bundle",
            "keepWorktree": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["bundleName"] == "launchable_bundle"
    state_path = tmp_path / "workspace" / "supervised_evolution" / "workbench_state.json"
    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved_state["bundle_name"] == "launchable_bundle"

    _reset_supervised_live_state()

def test_start_supervised_run_rejects_second_active_run(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    first = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    second = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )

    assert first.status_code == 202
    assert second.status_code == 409

    _reset_supervised_live_state()

def test_retry_supervised_run_route_returns_new_retry_snapshot(monkeypatch):
    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_routes, "retry_supervised_run", lambda run_id: {
        "runId": "web-supervised-retry",
        "status": "queued",
        "retryOfRunId": run_id,
    })

    response = client.post("/api/evolution/runs/web-supervised-old/retry")

    assert response.status_code == 202
    payload = response.json()
    assert payload["runId"] == "web-supervised-retry"
    assert payload["retryOfRunId"] == "web-supervised-old"

def test_start_supervised_run_rejects_when_self_evolution_lease_active(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    _reset_supervised_live_state()
    _reset_self_evolution_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    self_snapshot = {
        "runId": "web-self-active-lease",
        "runKind": "self_evolution_run",
        "status": "running",
        "leases": ["evolution_transaction", "worktree_write", "memory_write"],
        "startedAt": "2026-05-21T00:00:00",
        "updatedAt": "2026-05-21T00:00:00",
    }
    self_evolution_control_service.persist_manager_run_snapshot("self", self_snapshot, active_run_id=self_snapshot["runId"])

    run_path, index_path = _real_runtime_manager_evolution_paths("self", self_snapshot["runId"])
    original_index_text = _read_optional_text(index_path)

    try:
        response = client.post(
            "/api/evolution/runs",
            json={
                "sourceKind": "bundle",
                "bundleName": "manual_bundle",
                "keepWorktree": False,
            },
        )

        assert response.status_code == 409
        assert "resource" in response.json()["detail"].lower() or "资源" in response.json()["detail"]
    finally:
        _restore_real_runtime_index_if_touched("self", self_snapshot["runId"], original_index_text)
        _reset_supervised_live_state()
        _reset_self_evolution_live_state()

def test_supervised_run_control_routes_pause_resume_and_terminate(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    start_response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    run_id = start_response.json()["runId"]

    pause_response = client.post(f"/api/evolution/runs/{run_id}/pause")
    active_after_pause = client.get("/api/evolution/active-run")
    blocked_start = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    resume_response = client.post(f"/api/evolution/runs/{run_id}/resume")
    terminate_response = client.post(f"/api/evolution/runs/{run_id}/terminate")
    active_after_terminate = client.get("/api/evolution/active-run")

    assert start_response.status_code == 202
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"
    assert pause_response.json()["pauseRequested"] is True
    assert active_after_pause.status_code == 200
    assert active_after_pause.json()["status"] == "paused"
    assert blocked_start.status_code == 409
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "queued"
    assert resume_response.json()["pauseRequested"] is False
    assert terminate_response.status_code == 200
    assert terminate_response.json()["status"] == "cancelled"
    assert terminate_response.json()["stopRequested"] is True
    assert active_after_terminate.status_code == 200
    assert active_after_terminate.json() is None

    _reset_supervised_live_state()

def test_supervised_run_delete_route_clears_queued_run_and_unlocks_start(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    start_response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    run_id = start_response.json()["runId"]

    delete_response = client.delete(f"/api/evolution/runs/{run_id}")
    active_after_delete = client.get("/api/evolution/active-run")
    restart_response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )

    assert start_response.status_code == 202
    assert delete_response.status_code == 200, delete_response.json()
    assert delete_response.json()["deleted"] is True
    assert delete_response.json()["clearedActive"] is True
    assert active_after_delete.status_code == 200
    assert active_after_delete.json() is None
    assert restart_response.status_code == 202
    assert restart_response.json()["runId"] != run_id

    _reset_supervised_live_state()

def test_supervised_run_delete_live_manager_route_returns_accepted_without_waiting(monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(supervised_control_service, "_ensure_runtime_manager_daemon", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        supervised_control_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)) or {"commandId": "cmd-web-delete"},
    )
    monkeypatch.setattr(
        supervised_control_service,
        "wait_for_result",
        lambda command_id, *, timeout_seconds=60: pytest.fail("accepted submission must not poll for command completion"),
    )
    monkeypatch.setattr(
        supervised_control_service,
        "_load_immediate_runtime_manager_command_result",
        lambda command_id: calls.append(("immediate", command_id)) or None,
    )

    response = client.delete("/api/evolution/runs/web-supervised-old")

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["commandId"] == "cmd-web-delete"
    assert payload["commandType"] == "delete_supervised_run"
    assert payload["runId"] == "web-supervised-old"
    assert calls[0] == "ensure"
    assert calls[1] == (
        "delete_supervised_run",
        {"runId": "web-supervised-old"},
        "web_ui",
    )
    assert calls[2] == ("immediate", "cmd-web-delete")

def test_supervised_run_delete_route_rejects_running_run():
    _reset_supervised_live_state()
    context = {
        "runId": "web-supervised-running-delete",
        "lang": "en",
        "sourceKind": "bundle",
        "datasetName": "",
        "datasetLimit": None,
        "bundleName": "manual_bundle",
        "keepWorktree": False,
        "startedAt": "2026-05-18T12:00:00Z",
    }
    state = supervised_control_service._initial_run_state(context)
    state["status"] = "running"
    state["currentPhase"] = "running"
    state["runtimeStatus"] = "running"
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES[context["runId"]] = state
        supervised_control_service._RUN_CONTROLLERS[context["runId"]] = supervised_control_service._SupervisedRunController()
        supervised_control_service._ACTIVE_RUN_ID = context["runId"]
    supervised_control_service.persist_manager_run_snapshot("supervised", state, active_run_id=context["runId"])

    response = client.delete(f"/api/evolution/runs/{context['runId']}")

    assert response.status_code == 409
    assert "Terminate" in response.json()["detail"] or "终止" in response.json()["detail"]

    _reset_supervised_live_state()

def test_supervised_run_action_route_executes_and_respects_active_lock(tmp_path, monkeypatch):
    pending_result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="web_action_episode",
    )
    _write_supervised_decision_record(
        tmp_path,
        "web_action_run",
        {
            "decision": "PROMOTE",
            "reason": "候选方案进入 proposal 流程。",
            "gates": [
                {
                    "name": "gym_promotion",
                    "status": "pass",
                    "reason": "proposal created",
                    "metrics": {
                        "promotion_proposal_path": pending_result.promotion_proposal_path,
                        "decision_path": pending_result.decision_path,
                    },
                }
            ],
        },
    )

    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)

    apply_response = client.post(
        "/api/evolution/runs/web_action_run/actions",
        json={"action": "apply"},
    )

    assert apply_response.status_code == 200
    payload = apply_response.json()
    assert payload["action"] == "apply"
    assert payload["run"]["proposalStatus"] == "applied"
    assert payload["lifecycle"]["status"] == "applied"

    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )
    start_response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    blocked_response = client.post(
        "/api/evolution/runs/web_action_run/actions",
        json={"action": "activate"},
    )

    assert start_response.status_code == 202
    assert blocked_response.status_code == 409

    _reset_supervised_live_state()

def test_evolution_auto_review_mode_blocks_manual_proposal_governance(tmp_path, monkeypatch):
    seeded = _seed_supervised_proposal_record(tmp_path, "auto_mode_proposal", status="proposed")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(evolution_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(supervised_control_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/supervised-evolution",
            "intakeMode": "auto",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    _reset_supervised_live_state()

    detail_response = client.get("/api/evolution/proposals/auto_mode_proposal")
    action_response = client.post(
        "/api/evolution/runs/auto_mode_proposal/actions",
        json={"action": "apply"},
    )
    edit_response = client.patch(
        "/api/evolution/proposals/auto_mode_proposal",
        json={"summary": "manual edit should be blocked in auto mode"},
    )
    delete_response = client.delete("/api/evolution/proposals/auto_mode_proposal")
    bulk_delete_response = client.post(
        "/api/evolution/proposals/delete",
        json={"sessionIds": ["auto_mode_proposal"]},
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["availableActions"] == []
    assert detail["canDelete"] is False
    assert "自动审查" in detail["deleteBlockReason"]
    assert detail["canEdit"] is False
    assert "自动审查" in detail["editBlockReason"]
    assert detail["actionStates"]["apply"]["enabled"] is False
    assert detail["actionStates"]["activate"]["enabled"] is False
    assert detail["actionStates"]["rollback"]["enabled"] is False
    assert detail["actionStates"]["delete"]["enabled"] is False
    assert "自动审查" in detail["actionStates"]["apply"]["reason"]
    current_state_text = "\n".join(detail["review"]["currentState"])
    assert "自动审查" in current_state_text
    assert "当前可执行动作" not in current_state_text
    assert "Available actions now" not in current_state_text

    assert action_response.status_code == 409
    assert "自动审查" in action_response.json()["detail"]
    assert edit_response.status_code == 409
    assert "自动审查" in edit_response.json()["detail"]
    assert delete_response.status_code == 409
    assert "自动审查" in delete_response.json()["detail"]

    assert bulk_delete_response.status_code == 200
    bulk_payload = bulk_delete_response.json()
    assert bulk_payload["deletedCount"] == 0
    assert bulk_payload["skippedCount"] == 1
    assert bulk_payload["errorCount"] == 0
    assert bulk_payload["results"][0]["sessionId"] == "auto_mode_proposal"
    assert bulk_payload["results"][0]["status"] == "skipped"
    assert "自动审查" in bulk_payload["results"][0]["summary"]
    assert json.loads(seeded["decision_path"].read_text(encoding="utf-8")).get("hidden_from_workbench") is not True
    assert json.loads(seeded["proposal_path"].read_text(encoding="utf-8")).get("hidden_from_workbench") is not True

def test_evolution_proposal_detail_route_exposes_review_first_payload(tmp_path, monkeypatch):
    seeded = _seed_supervised_proposal_record(tmp_path, "proposal_detail_run", status="proposed")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/evolution/proposals/proposal_detail_run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sessionId"] == "proposal_detail_run"
    assert payload["proposalStatus"] == "proposed"
    assert payload["canDelete"] is True
    assert payload["review"]["headline"]
    assert payload["review"]["changeSummary"]
    assert payload["review"]["whatChanged"]
    assert payload["review"]["whyCreated"]
    assert payload["proposal"]["proposalId"]
    assert payload["proposal"]["improvementType"]
    assert payload["proposal"]["expectedEffect"]
    assert payload["canEdit"] is True
    assert payload["editBlockReason"] == ""
    _assert_seeded_case_diagnostic(payload["supervised"]["caseDiagnostics"][0])
    assert payload["paths"]["gymProposalPath"] == str(seeded["proposal_path"])
    assert payload["rawProposal"]["status"] == "proposed"
    assert payload["rawGymDecision"]["candidate_improvement"]["improvement_id"]

def test_evolution_update_proposal_persists_manual_draft_edits(tmp_path, monkeypatch):
    seeded = _seed_supervised_proposal_record(tmp_path, "proposal_edit_run", status="proposed")
    events: list[dict] = []

    def fake_record_runtime_scene_event(component, phase, event_code, **kwargs):
        events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **kwargs,
            }
        )

    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", fake_record_runtime_scene_event)

    response = client.patch(
        "/api/evolution/proposals/proposal_edit_run",
        json={
            "improvementType": "manual prompt patch",
            "expectedEffect": "Make the candidate instruction easier to audit.",
            "summary": "Manual edit from proposal library.",
            "candidatePrompt": "candidate prompt edited by user",
            "baselinePrompt": "baseline prompt retained for comparison",
            "editNote": "tighten candidate wording",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["updated"] is True
    assert set(payload["changedFields"]) == {
        "improvement_type",
        "expected_effect",
        "summary",
        "candidate_prompt",
        "baseline_prompt",
    }
    assert payload["proposal"]["proposal"]["improvementType"] == "manual prompt patch"
    assert payload["proposal"]["proposal"]["expectedEffect"] == "Make the candidate instruction easier to audit."
    assert payload["proposal"]["proposal"]["summary"] == "Manual edit from proposal library."
    assert payload["proposal"]["proposal"]["candidatePrompt"] == "candidate prompt edited by user"
    assert payload["proposal"]["canEdit"] is True

    proposal_payload = json.loads(seeded["proposal_path"].read_text(encoding="utf-8"))
    assert proposal_payload["manual_overrides"]["improvement_type"] == "manual prompt patch"
    assert proposal_payload["manual_overrides"]["candidate_prompt"] == "candidate prompt edited by user"
    assert proposal_payload["manual_edit_history"][-1]["edit_note"] == "tighten candidate wording"
    assert proposal_payload["edited_by"] == "workbench"
    assert any(event["eventCode"] == "evolution.proposal_edit.saved" for event in events)

    partial_response = client.patch(
        "/api/evolution/proposals/proposal_edit_run",
        json={"summary": "Summary-only follow-up edit."},
    )

    assert partial_response.status_code == 200
    partial_payload = partial_response.json()
    assert partial_payload["changedFields"] == ["summary"]
    proposal_payload = json.loads(seeded["proposal_path"].read_text(encoding="utf-8"))
    assert proposal_payload["manual_overrides"]["summary"] == "Summary-only follow-up edit."
    assert proposal_payload["manual_overrides"]["candidate_prompt"] == "candidate prompt edited by user"
    assert proposal_payload["manual_overrides"]["baseline_prompt"] == "baseline prompt retained for comparison"

@pytest.mark.parametrize("status", ["applied", "missing"])
def test_evolution_update_proposal_blocks_non_draft_states(tmp_path, monkeypatch, status):
    seeded = _seed_supervised_proposal_record(tmp_path, f"proposal_edit_blocked_{status}", status=status)
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.patch(
        f"/api/evolution/proposals/proposal_edit_blocked_{status}",
        json={"summary": "should not be saved"},
    )
    detail_response = client.get(f"/api/evolution/proposals/proposal_edit_blocked_{status}")

    assert response.status_code == 409
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["canEdit"] is False
    assert detail["editBlockReason"]
    decision_payload = json.loads(seeded["decision_path"].read_text(encoding="utf-8"))
    assert "manual_overrides" not in decision_payload
    if seeded["proposal_path"].exists():
        proposal_payload = json.loads(seeded["proposal_path"].read_text(encoding="utf-8"))
        assert "manual_overrides" not in proposal_payload

def test_evolution_routes_expose_supervised_policy_observing_proposal(tmp_path, monkeypatch):
    decision_path = _write_supervised_decision_record(
        tmp_path,
        "observing_policy_run",
        {
            "decision": "HOLD",
            "reason": "candidate 持平，进入观察池。",
        },
    )
    proposal_path = tmp_path / "workspace" / "evolution" / "proposals" / "demo__case_1__observing.json"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(
        json.dumps(
            {
                "proposal_id": "demo:case_1:observing",
                "session_id": "observing_policy_run",
                "bundle_name": "demo_bundle",
                "case_id": "case_1",
                "target": {"kind": "bundle_prompt_case", "bundle_name": "demo_bundle", "case_id": "case_1"},
                "candidate_prompt": "candidate prompt",
                "baseline_prompt": "baseline prompt",
                "decision_signal": "stable_success",
                "status": "observing",
                "decision": "HOLD",
                "supervised_decision": "HOLD",
                "policy_action": "HOLD",
                "proposal_status": "observing",
                "runtime_effect": "not_applied",
                "agent_consumption": "advisory",
                "supervision_boundary": {
                    "scope": "supervised_frozen_evaluator",
                    "accepted_baseline_registry_scope": "supervised_policy_artifact",
                    "promote_updates_runtime": False,
                },
                "decision_path": str(decision_path),
                "observation_count": 1,
                "observation_budget": 3,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    payload["policy_action"] = {
        "lineage_index_path": str(tmp_path / "workspace" / "evolution" / "proposals" / "lineage_index.json"),
        "proposal_paths": [str(proposal_path)],
    }
    decision_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    runs_payload = client.get("/api/evolution/runs").json()
    library_payload = client.get("/api/evolution/library").json()
    detail_response = client.get("/api/evolution/proposals/observing_policy_run")

    assert runs_payload[0]["proposalStatus"] == "observing"
    assert runs_payload[0]["runtimeEffect"] == "not_applied"
    assert runs_payload[0]["agentConsumption"] == "advisory"
    assert runs_payload[0]["sourceProposalPath"] == str(proposal_path)
    assert any(item["sourceRun"] == "observing_policy_run" for item in library_payload["pending"])
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["proposalStatus"] == "observing"
    assert detail["runtimeEffect"] == "not_applied"
    assert detail["paths"]["gymProposalPath"] == str(proposal_path)
    assert detail["rawProposal"]["proposal_id"] == "demo:case_1:observing"
    assert detail["rawProposal"]["supervision_boundary"]["scope"] == "supervised_frozen_evaluator"
    assert detail["proposal"]["proposalId"] == "demo:case_1:observing"

def test_evolution_runs_route_exposes_run_delete_state(tmp_path, monkeypatch):
    _seed_supervised_proposal_record(tmp_path, "run_delete_missing", status="missing")
    _seed_supervised_proposal_record(tmp_path, "run_delete_active", status="active")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/evolution/runs")

    assert response.status_code == 200
    payload = {item["id"]: item for item in response.json()}
    assert payload["run_delete_missing"]["canDelete"] is True
    assert payload["run_delete_missing"]["deleteBlockReason"] == ""
    assert payload["run_delete_active"]["canDelete"] is False
    assert payload["run_delete_active"]["deleteBlockReason"]

@pytest.mark.parametrize("status", ["proposed", "rolled_back", "missing", "superseded"])
def test_evolution_delete_proposal_allows_removable_states(tmp_path, monkeypatch, status):
    session_id = f"delete_{status}"
    seeded = _seed_supervised_proposal_record(tmp_path, session_id, status=status)
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.delete(f"/api/evolution/proposals/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] is True
    assert seeded["decision_path"].exists()
    if status != "missing":
        assert seeded["proposal_path"].exists()
    decision_payload = json.loads(seeded["decision_path"].read_text(encoding="utf-8"))
    assert decision_payload["hidden_from_workbench"] is True
    assert decision_payload["deletion"]["preserved_for_audit"] is True
    if status != "missing":
        proposal_payload = json.loads(seeded["proposal_path"].read_text(encoding="utf-8"))
        assert proposal_payload["hidden_from_workbench"] is True

    runs_payload = client.get("/api/evolution/runs").json()
    library_payload = client.get("/api/evolution/library").json()
    visible_source_runs = {item["sourceRun"] for item in library_payload["items"] + library_payload["pending"]}

    assert all(run["id"] != session_id for run in runs_payload)
    assert session_id not in visible_source_runs

@pytest.mark.parametrize("status", ["applied", "active"])
def test_evolution_delete_proposal_blocks_live_states(tmp_path, monkeypatch, status):
    session_id = f"blocked_{status}"
    seeded = _seed_supervised_proposal_record(tmp_path, session_id, status=status)
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.delete(f"/api/evolution/proposals/{session_id}")
    detail_response = client.get(f"/api/evolution/proposals/{session_id}")

    assert response.status_code == 409
    assert detail_response.status_code == 200
    assert detail_response.json()["canDelete"] is False
    assert seeded["decision_path"].exists()
    assert seeded["proposal_path"].exists()

def test_evolution_bulk_delete_proposals_reports_mixed_results(tmp_path, monkeypatch):
    proposed = _seed_supervised_proposal_record(tmp_path, "bulk_delete_proposed", status="proposed")
    missing = _seed_supervised_proposal_record(tmp_path, "bulk_delete_missing", status="missing")
    active = _seed_supervised_proposal_record(tmp_path, "bulk_delete_active", status="active")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/evolution/proposals/delete",
        json={
            "sessionIds": [
                "bulk_delete_proposed",
                "bulk_delete_missing",
                "bulk_delete_active",
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deletedCount"] == 2
    assert payload["skippedCount"] == 1
    assert payload["errorCount"] == 0
    result_status = {item["sessionId"]: item["status"] for item in payload["results"]}
    assert result_status["bulk_delete_proposed"] == "deleted"
    assert result_status["bulk_delete_missing"] == "deleted"
    assert result_status["bulk_delete_active"] == "skipped"
    assert proposed["decision_path"].exists()
    assert missing["decision_path"].exists()
    assert json.loads(proposed["decision_path"].read_text(encoding="utf-8"))["hidden_from_workbench"] is True
    assert json.loads(missing["decision_path"].read_text(encoding="utf-8"))["hidden_from_workbench"] is True
    assert active["decision_path"].exists()
    assert active["proposal_path"].exists()

    runs_payload = client.get("/api/evolution/runs").json()
    run_ids = {item["id"] for item in runs_payload}
    assert "bulk_delete_proposed" not in run_ids
    assert "bulk_delete_missing" not in run_ids
    assert "bulk_delete_active" in run_ids

def test_self_evolution_routes_expose_read_only_evidence(monkeypatch):
    monkeypatch.setattr(self_evolution_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(
        self_evolution_service,
        "build_self_evolution_snapshot",
        lambda project_root=None, transaction_limit=6, recent_limit=4: {
            "goal": "开始自主进化",
            "advisory": {
                "active_count": 1,
                "entries": [
                    {
                        "target_key": "target:a",
                        "target_label": "local_transaction_closing_v1",
                        "proposal_id": "proposal-1",
                        "episode_id": "episode-1",
                        "candidate_improvement_id": "cand-1",
                        "activated_at": "2026-05-18T12:00:00Z",
                        "runtime_effect": "not_applied",
                        "agent_consumption": "advisory",
                        "proposal_path": "workspace/gym/proposal-1.json",
                        "decision_path": "workspace/gym/decision-1.json",
                        "trace_index_path": "workspace/gym/trace-1.json",
                    }
                ],
            },
            "git_status": {
                "summary": json.dumps(
                    {
                        "dirty_summary": "有 unstaged 改动，共 1 个变化文件",
                        "modified_paths": ["core/evaluation/self_evolution_workbench.py"],
                        "modified_entities": [],
                        "last_validation_summary": "ruff lint 通过",
                        "recent_changes": [
                            {
                                "path": "core/evaluation/self_evolution_workbench.py",
                                "change_type": "modified",
                                "subject": "refine self evidence",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "lines": [
                    "{",
                    '  "dirty_summary": "有 unstaged 改动，共 1 个变化文件",',
                    '  "modified_paths": ["core/evaluation/self_evolution_workbench.py"],',
                ],
            },
            "recent_changes": [
                {
                    "path": "core/evaluation/self_evolution_workbench.py",
                    "change_type": "M",
                    "summary": "refine self evidence",
                }
            ],
            "fitness": {
                "transactions": {
                    "opened": 2,
                    "closed": 2,
                    "successful": 1,
                    "failed": 1,
                    "success_rate": 0.5,
                    "recent": [
                        {
                            "txn_id": "txn-1",
                            "status": "failed",
                            "validation_passed": 1,
                            "validation_failed": 1,
                            "mutations_recorded": 2,
                        }
                    ],
                },
                "validation": {"passed": 2, "failed": 1, "pass_rate": 0.66},
                "mutations": {"recorded": 3, "successful": 1, "failed": 1, "blocked": 1},
            },
            "worktree": {
                "available": True,
                "error": "",
                "snapshot_id": "snap-1",
                "created_at": "2026-05-18T12:00:00Z",
                "base_rev": "abcdef1234567890",
                "has_staged": False,
                "has_unstaged": True,
                "has_untracked": False,
                "is_dirty": True,
                "dirty_file_count": 1,
                "files": [
                    {
                        "path": "core/evaluation/self_evolution_workbench.py",
                        "status": "M",
                        "staged": False,
                        "unstaged": True,
                        "untracked": False,
                        "deleted": False,
                    }
                ],
            },
            "recent_transactions": [
                {
                    "txn_id": "txn-1",
                    "opened_at": "2026-05-18T11:55:00Z",
                    "closed_at": "2026-05-18T12:00:00Z",
                    "base_rev": "abcdef1234567890",
                    "base_rev_short": "abcdef123456",
                    "status": "failed",
                    "summary": "touch self loop",
                    "is_open": False,
                }
            ],
        },
    )
    monkeypatch.setattr(
        self_evolution_service,
        "list_recent_self_evolution_transaction_payloads",
        lambda project_root, limit=24: [
            {
                "txn_id": "txn-1",
                "opened_at": "2026-05-18T11:55:00Z",
                "closed_at": "2026-05-18T12:00:00Z",
                "base_rev": "abcdef1234567890",
                "base_rev_short": "abcdef123456",
                "status": "failed",
                "summary": "touch self loop",
                "is_open": False,
            }
        ],
    )
    monkeypatch.setattr(
        self_evolution_service,
        "load_self_evolution_audit_records",
        lambda project_root, limit=6: [
            {
                "timestamp": "2026-05-18T12:00:00Z",
                "event": "validation_completed",
                "txn_id": "txn-1",
                "status": "",
                "kind": "pytest",
                "message": "1 failed",
                "tool_name": "",
                "target_paths": ["tests/test_self_evolution_workbench.py"],
                "passed": False,
                "base_rev": "abcdef1234567890",
                "summary": "2026-05-18T12:00:00Z validation_completed txn-1 kind=pytest passed=False message=1 failed",
            }
        ],
    )

    overview_response = client.get("/api/evolution/self/overview")
    transactions_response = client.get("/api/evolution/self/transactions")
    audit_response = client.get("/api/evolution/self/audit")

    assert overview_response.status_code == 200
    assert transactions_response.status_code == 200
    assert audit_response.status_code == 200

    overview_payload = overview_response.json()
    assert overview_payload["enabled"] is True
    assert overview_payload["readiness"]["state"] == "caution"
    assert overview_payload["advisory"]["activeCount"] == 1
    assert overview_payload["metrics"]["dirtyFiles"] == 1
    assert overview_payload["gitStatus"]["summary"] == "有 unstaged 改动，共 1 个变化文件"
    assert overview_payload["gitStatus"]["lines"][1] == "最近验证: ruff lint 通过"
    assert overview_payload["worktree"]["snapshotId"] == "snap-1"
    assert overview_payload["sceneSemantics"]["sceneState"] == "caution"
    assert overview_payload["runSemantics"]["runStatus"] == "failed"
    assert overview_payload["actionStates"]["start"]["enabled"] is True
    assert overview_payload["recentTransactions"][0]["txnId"] == "txn-1"
    assert overview_payload["auditTail"][0]["event"] == "validation_completed"
    assert transactions_response.json()[0]["baseRevShort"] == "abcdef123456"
    assert audit_response.json()[0]["summary"].startswith("2026-05-18T12:00:00Z")

def test_self_evolution_snapshot_uses_worktree_status_bundle(monkeypatch, tmp_path):
    bundle_calls = {"count": 0}
    status_summary = json.dumps(
        {
            "dirty_summary": "工作区干净",
            "modified_paths": [],
            "modified_entities": [],
            "last_validation_summary": None,
            "recent_changes": [],
        },
        ensure_ascii=False,
        indent=2,
    )
    worktree_snapshot = json.dumps(
        {
            "snapshot_id": "bundle-snap",
            "created_at": "2026-06-08T00:00:00",
            "base_rev": "abcdef",
            "has_staged": False,
            "has_unstaged": False,
            "has_untracked": False,
            "files": [],
            "available": True,
            "error": None,
        },
        ensure_ascii=False,
        indent=2,
    )

    def build_bundle(limit=5):
        bundle_calls["count"] += 1
        assert limit == 5
        return json.dumps(
            {
                "git_status_summary": status_summary,
                "worktree_snapshot": worktree_snapshot,
            },
            ensure_ascii=False,
            indent=2,
        )

    monkeypatch.setattr(self_evolution_workbench, "get_worktree_status_bundle_tool", build_bundle)
    monkeypatch.setattr(
        self_evolution_workbench,
        "get_git_status_summary_tool",
        lambda limit=5: pytest.fail("snapshot should use the shared worktree status bundle"),
    )
    monkeypatch.setattr(
        self_evolution_workbench,
        "explain_current_worktree_tool",
        lambda: pytest.fail("snapshot should not load a second worktree snapshot"),
    )
    monkeypatch.setattr(self_evolution_workbench, "get_recent_changes_tool", lambda limit=3: "[]")
    monkeypatch.setattr(self_evolution_workbench, "get_evolution_fitness_tool", lambda recent_limit=3: "{}")
    monkeypatch.setattr(
        self_evolution_workbench,
        "build_active_advisory_snapshot",
        lambda project_root, limit=3: {"active_count": 0, "entries": []},
    )
    monkeypatch.setattr(
        self_evolution_workbench,
        "list_recent_self_evolution_transaction_payloads",
        lambda project_root, limit=3: [],
    )

    payload = self_evolution_workbench.build_self_evolution_snapshot(project_root=tmp_path)

    assert bundle_calls["count"] == 1
    assert payload["git_status"]["summary"] == status_summary
    assert payload["worktree"]["snapshot_id"] == "bundle-snap"

def test_self_evolution_overview_uses_short_ttl_cache(monkeypatch):
    calls = {"snapshot": 0, "audit": 0}
    now = {"monotonic": 10.0, "perf": 100.0}

    monkeypatch.setattr(self_evolution_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(self_evolution_service.time, "monotonic", lambda: now["monotonic"])
    monkeypatch.setattr(self_evolution_service.time, "perf_counter", lambda: now["perf"])
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            }
        },
    )

    def build_snapshot(project_root=None, transaction_limit=6, recent_limit=4):
        calls["snapshot"] += 1
        return {
            "goal": "cache test",
            "advisory": {"active_count": 0, "entries": []},
            "git_status": {"summary": "clean", "lines": ["clean"]},
            "recent_changes": [],
            "fitness": {},
            "worktree": {
                "available": True,
                "dirty_file_count": calls["snapshot"],
                "files": [],
            },
            "recent_transactions": [],
        }

    monkeypatch.setattr(self_evolution_service, "build_self_evolution_snapshot", build_snapshot)
    monkeypatch.setattr(
        self_evolution_service,
        "load_self_evolution_audit_records",
        lambda project_root, limit=6: calls.__setitem__("audit", calls["audit"] + 1) or [],
    )

    first = self_evolution_service.get_self_evolution_overview()
    second = self_evolution_service.get_self_evolution_overview()
    now["monotonic"] += self_evolution_service.SELF_EVOLUTION_OVERVIEW_CACHE_TTL_SECONDS + 0.1
    third = self_evolution_service.get_self_evolution_overview()

    assert calls["snapshot"] == 2
    assert calls["audit"] == 2
    assert first == second
    assert third["metrics"]["dirtyFiles"] == 2

def test_self_evolution_history_delete_invalidates_overview_cache(tmp_path, monkeypatch):
    _seed_self_evolution_history(tmp_path)
    calls = {"snapshot": 0}
    monkeypatch.setattr(self_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(self_evolution_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            }
        },
    )

    def build_snapshot(project_root=None, transaction_limit=6, recent_limit=4):
        calls["snapshot"] += 1
        return {
            "goal": "delete cache test",
            "advisory": {"active_count": 0, "entries": []},
            "git_status": {"summary": "clean", "lines": ["clean"]},
            "recent_changes": [],
            "fitness": {},
            "worktree": {
                "available": True,
                "dirty_file_count": calls["snapshot"],
                "files": [],
            },
            "recent_transactions": [
                {
                    "txn_id": "txn-delete-a",
                    "opened_at": "2026-05-18T11:55:00Z",
                    "closed_at": "2026-05-18T12:00:00Z",
                    "base_rev": "abcdef1234567890",
                    "base_rev_short": "abcdef123456",
                    "status": "success",
                    "summary": "delete me",
                    "is_open": False,
                }
            ],
        }

    monkeypatch.setattr(self_evolution_service, "build_self_evolution_snapshot", build_snapshot)
    monkeypatch.setattr(self_evolution_service, "load_self_evolution_audit_records", lambda project_root, limit=6: [])

    before = client.get("/api/evolution/self/overview")
    delete_response = client.post(
        "/api/evolution/self/history/delete",
        json={"txnIds": ["txn-delete-a"]},
    )
    after = client.get("/api/evolution/self/overview")

    assert before.status_code == 200
    assert delete_response.status_code == 200
    assert after.status_code == 200
    assert calls["snapshot"] == 2

def test_start_self_evolution_run_from_web_exposes_active_snapshot(monkeypatch):
    _reset_self_evolution_live_state()
    _use_local_self_evolution_start(monkeypatch)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        self_evolution_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )
    monkeypatch.setattr(self_evolution_control_service, "_publish_run_snapshot", lambda run_id, terminal=False, **kwargs: None)

    response = client.post("/api/evolution/self/runs", json={"goal": "网页触发一轮自进化"})
    active_response = client.get("/api/evolution/self/active-run")

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["goal"] == "网页触发一轮自进化"
    assert payload["runId"].startswith("web-self-")
    assert payload["runSemantics"]["runStatus"] == "queued"
    assert payload["actionStates"]["pause"]["enabled"] is True

    assert active_response.status_code == 200
    active_payload = active_response.json()
    assert active_payload["runId"] == payload["runId"]
    assert active_payload["status"] == "queued"
    assert active_payload["actionStates"]["resume"]["enabled"] is False

    _reset_self_evolution_live_state()

def test_start_self_evolution_run_from_web_does_not_write_real_runtime_manager_store(monkeypatch):
    _reset_self_evolution_live_state()
    _use_local_self_evolution_start(monkeypatch)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        self_evolution_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )
    assert self_evolution_control_service._runtime_manager_live_control_enabled() is False
    monkeypatch.setattr(
        self_evolution_control_service,
        "_submit_self_runtime_manager_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("runtime manager command should not be used in local-mode test")
        ),
    )
    monkeypatch.setattr(
        self_evolution_control_service,
        "persist_manager_run_snapshot",
        lambda kind, snapshot, *, active_run_id="": dict(snapshot),
    )

    response = client.post("/api/evolution/self/runs", json={"goal": "隔离真实 runtime store"})
    assert response.status_code == 202
    run_id = response.json()["runId"]
    run_path, index_path = _real_runtime_manager_evolution_paths("self", run_id)
    original_index_text = _read_optional_text(index_path)

    try:
        active_response = client.get("/api/evolution/self/active-run")

        assert active_response.status_code == 200
        assert active_response.json()["runId"] == run_id
        assert not run_path.exists()
        current_index_text = _read_optional_text(index_path)
        assert current_index_text is None or run_id not in current_index_text
    finally:
        _restore_real_runtime_index_if_touched("self", run_id, original_index_text)
        _reset_self_evolution_live_state()

def test_start_self_evolution_run_allows_readonly_chat_but_blocks_write_chat(monkeypatch):
    _reset_self_evolution_live_state()
    _use_local_self_evolution_start(monkeypatch)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        self_evolution_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    session_service._set_session_running("session-readonly", True, turn_id="chat-turn-readonly", leases=["readonly_chat"])
    try:
        response = client.post("/api/evolution/self/runs", json={"goal": "允许只读 chat 并行"})
    finally:
        session_service._set_session_running("session-readonly", False, turn_id="chat-turn-readonly")

    assert response.status_code == 202
    _reset_self_evolution_live_state()

    session_service._set_session_running("session-write", True, turn_id="chat-turn-write", leases=["worktree_write"])
    try:
        blocked = client.post("/api/evolution/self/runs", json={"goal": "阻止写入型 chat 并行"})
    finally:
        session_service._set_session_running("session-write", False, turn_id="chat-turn-write")

    assert blocked.status_code == 409
    assert "写入" in blocked.json()["detail"] or "write" in blocked.json()["detail"].lower()

    _reset_self_evolution_live_state()

def test_start_self_evolution_run_rejects_when_supervised_run_active(monkeypatch):
    _reset_self_evolution_live_state()
    _use_local_self_evolution_start(monkeypatch)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_active_supervised_run",
        lambda: {"runId": "supervised-1", "status": "running"},
    )

    response = client.post("/api/evolution/self/runs", json={"goal": "blocked"})

    assert response.status_code == 409
    assert "监督任务" in response.json()["detail"]

    _reset_self_evolution_live_state()

def test_start_self_evolution_run_rejects_when_supervised_run_paused(monkeypatch):
    _reset_self_evolution_live_state()
    _use_local_self_evolution_start(monkeypatch)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_active_supervised_run",
        lambda: {"runId": "supervised-paused", "status": "paused"},
    )

    response = client.post("/api/evolution/self/runs", json={"goal": "blocked"})

    assert response.status_code == 409
    assert "监督任务" in response.json()["detail"]

    _reset_self_evolution_live_state()

def test_self_evolution_routes_hide_data_when_mode_disabled(monkeypatch):
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": False,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    overview_response = client.get("/api/evolution/self/overview")
    transactions_response = client.get("/api/evolution/self/transactions")
    audit_response = client.get("/api/evolution/self/audit")

    assert overview_response.status_code == 200
    assert transactions_response.status_code == 200
    assert audit_response.status_code == 200
    assert overview_response.json()["enabled"] is False
    assert overview_response.json()["readiness"]["state"] == "disabled"
    assert transactions_response.json() == []
    assert audit_response.json() == []

def _seed_self_evolution_history(project_root: Path) -> Path:
    workspace_dir = project_root / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    db_path = workspace_dir / "agent_brain.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE EvolutionTransaction (
                txn_id TEXT PRIMARY KEY,
                opened_at TEXT,
                closed_at TEXT,
                base_rev TEXT,
                status TEXT,
                summary TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO EvolutionTransaction (txn_id, opened_at, closed_at, base_rev, status, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("txn-delete-a", "2026-05-18T11:00:00Z", "2026-05-18T11:10:00Z", "aaaabbbbcccc", "done", "delete me"),
                ("txn-keep-b", "2026-05-18T12:00:00Z", "2026-05-18T12:10:00Z", "ddddeeeeffff", "failed", "keep me"),
                ("txn-open-c", "2026-05-18T13:00:00Z", None, "gggghhhhiiii", "running", "still open"),
            ],
        )
        conn.commit()

    audit_dir = workspace_dir / "evolution"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "audit.jsonl"
    audit_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-18T11:05:00Z",
                        "event": "validation_completed",
                        "txn_id": "txn-delete-a",
                        "summary": "delete audit",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-18T12:05:00Z",
                        "event": "validation_completed",
                        "txn_id": "txn-keep-b",
                        "summary": "keep audit",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-18T12:06:00Z",
                        "event": "system_note",
                        "txn_id": "",
                        "summary": "ungrouped audit",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return audit_path

def test_self_evolution_history_delete_removes_transaction_groups_and_linked_audit(tmp_path, monkeypatch):
    audit_path = _seed_self_evolution_history(tmp_path)
    monkeypatch.setattr(self_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            }
        },
    )
    monkeypatch.setattr(self_evolution_service, "get_web_language", lambda: "zh")

    response = client.post(
        "/api/evolution/self/history/delete",
        json={"txnIds": ["txn-delete-a"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deletedGroupCount"] == 1
    assert payload["deletedAuditCount"] == 1
    assert payload["deletedTxnIds"] == ["txn-delete-a"]

    transactions_response = client.get("/api/evolution/self/transactions")
    remaining_txn_ids = {item["txnId"] for item in transactions_response.json()}
    assert "txn-delete-a" not in remaining_txn_ids
    assert "txn-keep-b" in remaining_txn_ids

    audit_response = client.get("/api/evolution/self/audit")
    audit_txn_ids = [item["txnId"] for item in audit_response.json()]
    assert "txn-delete-a" not in audit_txn_ids
    assert "txn-keep-b" in audit_txn_ids
    assert "" in audit_txn_ids
    assert "txn-delete-a" not in audit_path.read_text(encoding="utf-8")

def test_self_evolution_history_delete_blocks_open_transaction_groups(tmp_path, monkeypatch):
    _seed_self_evolution_history(tmp_path)
    monkeypatch.setattr(self_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            }
        },
    )
    monkeypatch.setattr(self_evolution_service, "get_web_language", lambda: "zh")

    response = client.post(
        "/api/evolution/self/history/delete",
        json={"txnIds": ["txn-open-c"]},
    )

    assert response.status_code == 422
    assert "当前现场" in response.json()["detail"]

def _seed_supervised_proposal_record(project_root: Path, session_id: str, *, status: str) -> dict[str, Path]:
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=project_root,
        adapter=RunnerFakeAdapter(),
        episode_id=f"{session_id}_episode",
    )
    proposal_path = Path(result.promotion_proposal_path)

    activation = None
    if status in {"applied", "active", "rolled_back"}:
        apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=project_root)
    if status == "active":
        activation = activate_gym_promotion_proposal(result.promotion_proposal_path, project_root=project_root)
    elif status == "rolled_back":
        rollback_gym_promotion_proposal(
            result.promotion_proposal_path,
            project_root=project_root,
            reason="manual cleanup for test",
        )
    elif status == "superseded":
        apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=project_root)
        activate_gym_promotion_proposal(result.promotion_proposal_path, project_root=project_root)
        replacement = run_gym_collection_episode(
            collection_id="foundation_local_stability",
            project_root=project_root,
            adapter=RunnerFakeAdapter(),
            episode_id=f"{session_id}_replacement",
        )
        apply_gym_promotion_proposal(replacement.promotion_proposal_path, project_root=project_root)
        activate_gym_promotion_proposal(replacement.promotion_proposal_path, project_root=project_root)
    elif status == "missing":
        proposal_path.unlink()

    advisory_context = None
    if activation is not None:
        advisory_context = {
            "active_count": 1,
            "entries": [
                {
                    "target_key": activation.target_key,
                    "target_label": "local_transaction_closing_v1",
                    "proposal_id": activation.proposal_id,
                    "runtime_effect": activation.runtime_effect,
                    "agent_consumption": activation.agent_consumption,
                }
            ],
        }

    decision_path = _write_supervised_decision_record(
        project_root,
        session_id,
        {
            "decision": "PROMOTE",
            "reason": f"{status} proposal for cleanup review.",
            "gates": [
                {
                    "name": "gym_promotion",
                    "status": "pass",
                    "reason": f"proposal {status}",
                    "metrics": {
                        "promotion_proposal_path": str(proposal_path),
                        "decision_path": result.decision_path,
                    },
                }
            ],
            "advisory_context": advisory_context,
        },
    )
    return {
        "decision_path": decision_path,
        "proposal_path": proposal_path,
    }

def _write_workbench_state(project_root: Path, payload: dict) -> None:
    state_path = project_root / "workspace" / "supervised_evolution" / "workbench_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def _write_supervised_decision_record(project_root: Path, session_id: str, overrides: dict) -> Path:
    decisions_dir = project_root / "workspace" / "supervised_evolution" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    path = decisions_dir / f"{session_id}.json"
    payload = {
        "session_id": session_id,
        "bundle_name": "demo_bundle",
        "decision": "HOLD",
        "reason": "baseline 与 candidate 持平",
        "ended_at": "2026-05-18T12:00:00Z",
        "baseline_success_rate": 1.0,
        "candidate_success_rate": 1.0,
        "score_delta": 0.0,
        "baseline_summary": {"validation_failed": 0, "total_guarded_tools": 2, "avg_wall_clock_seconds": 1.0},
        "candidate_summary": {"validation_failed": 0, "total_guarded_tools": 2, "avg_wall_clock_seconds": 2.0},
        "case_summaries": [
            {
                "case_id": "case_1",
                "baseline_status": "success",
                "candidate_status": "success",
                "decision_signal": "stable_success",
                "difference_summary": "candidate 与 baseline 同为 success，validation 持平，runtime +1.0s。",
                "difference_metrics": {"wall_clock_seconds_delta": 1.0},
                "difference_reasons": ["same_status"],
                "score_breakdown": {
                    "baseline": {"overall_score": 1.0, "final_state_score": 1.0},
                    "candidate": {"overall_score": 0.95, "final_state_score": 1.0},
                    "delta": {"overall_score": -0.05},
                },
                "failure_taxonomy": ["same_status"],
                "evidence_paths": {
                    "baseline_report_path": "workspace/supervised_evolution/sessions/demo/baseline.json",
                    "candidate_report_path": "workspace/supervised_evolution/sessions/demo/candidate.json",
                },
                "intake_provenance": {
                    "evaluation_mode": "custom_harness",
                    "score_label": "Vibelution custom score (non-official)",
                    "official_verifier_status": "harbor_pending",
                    "official_score": None,
                    "official_score_available": False,
                },
            }
        ],
        "gates": [],
        "decision_path": str(path),
        "policy_action": {"lineage_index_path": str(project_root / "workspace" / "lineage.json")},
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

def _assert_seeded_case_diagnostic(diagnostic: dict) -> None:
    assert diagnostic == {
        "caseId": "case_1",
        "caseType": "static",
        "baselineStatus": "success",
        "candidateStatus": "success",
        "decisionSignal": "stable_success",
        "summary": "candidate 与 baseline 同为 success，validation 持平，runtime +1.0s。",
        "metrics": {"wall_clock_seconds_delta": 1.0},
        "reasons": ["same_status"],
        "scoreBreakdown": {
            "baseline": {"overall_score": 1.0, "final_state_score": 1.0},
            "candidate": {"overall_score": 0.95, "final_state_score": 1.0},
            "delta": {"overall_score": -0.05},
        },
        "failureTaxonomy": ["same_status"],
        "evidencePaths": {
            "baseline_report_path": "workspace/supervised_evolution/sessions/demo/baseline.json",
            "candidate_report_path": "workspace/supervised_evolution/sessions/demo/candidate.json",
        },
        "evaluationMetadata": {
            "evaluationMode": "custom_harness",
            "scoreLabel": "Vibelution custom score (non-official)",
            "officialVerifierStatus": "harbor_pending",
            "officialScore": None,
            "officialScoreAvailable": False,
        },
    }

def _reset_supervised_live_state() -> None:
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()

def _use_local_self_evolution_start(monkeypatch) -> None:
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "get_active_supervised_worktree_run", lambda: None)
    monkeypatch.setattr(
        self_evolution_control_service,
        "_capture_preflight_state",
        lambda run_id: {
            "runDir": "",
            "backupDir": "",
            "manifestPath": "",
            "baseRev": "",
            "dirtyEntries": {},
        },
    )
    monkeypatch.setattr(
        self_evolution_control_service,
        "self_evolution_agent_bindings",
        lambda: {
            role: {
                "agentId": f"test-self-{role}",
                "displayName": f"Test self {role}",
                "profileId": "primary",
                "promptTemplateId": f"prompt-self-{role}",
                "directSessionId": f"session-self-{role}",
                "workspacePath": f"workspace/agents/test-self-{role}",
                "role": role,
                "roleLabel": role,
            }
            for role in ("executor", "reviewer", "summarizer")
        },
    )
