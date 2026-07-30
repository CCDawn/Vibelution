import json
import ast
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.chat.conversation_ledger import append_conversation_event
from core.agent_kernel import service as agent_kernel_service
from core.runtime_manager.work_run_store import WorkRunStore
from core.web.services import (
    agent_directory_service,
    agent_role_tool_profile_service,
    chat_room_service,
    data_processing_service,
    project_agent_bus_service,
    session_service,
    team_knowledge_service,
    team_service,
    team_workflow_orchestration_service,
)
from tools import team_knowledge_tools

pytestmark = pytest.mark.serial



class _FakeLocalResearchMessage:
    def __init__(self, content, *, reasoning_content=""):
        self.content = content
        self.additional_kwargs = {"reasoning_content": reasoning_content} if reasoning_content else {}

class _FakeLocalResearchClient:
    response = _FakeLocalResearchMessage("{}")
    captured_messages = []

    def __init__(self, *, config=None, profile_id=None):
        self.config = config
        self.profile_id = profile_id

    def invoke(self, messages, tools=None, metadata=None):
        type(self).captured_messages.append({"messages": messages, "metadata": metadata, "profile_id": self.profile_id})
        return type(self).response

class _NoopBackgroundExecutor:
    def __init__(self):
        self.submitted = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append({"fn": fn, "args": args, "kwargs": kwargs})
        future = Future()
        future.set_result(None)
        return future

def _fake_local_research_public_config(*, prompt_cache_mode="explicit_cache_control"):
    return {
        "llm": {
            "profiles": {},
            "model_library": {
                "houmo_qwen35_9b_agent": {
                    "model": "qwen3.5-9b",
                    "provider": "local",
                    "prompt_cache": {"mode": prompt_cache_mode},
                }
            },
        }
    }

def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_processing_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_kernel_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_workflow_orchestration_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_workflow_orchestration_service, "load_public_config", _fake_local_research_public_config)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", _NoopBackgroundExecutor())

def _capture_workflow_events(monkeypatch):
    events = []

    def fake_record_runtime_scene_event(*args, **kwargs):
        events.append((args, kwargs))
        return {"accepted": True, "path": kwargs.get("child_log_path", "")}

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "record_runtime_scene_event",
        fake_record_runtime_scene_event,
    )
    return events

def _append_stage_task_tool_trace(project_root: Path, task: dict, *, complete: bool = True, turn_id: str = "") -> None:
    session_id = task["sessionId"]
    turn_id = turn_id or task["turn"]["turnId"]
    tool_names = list(
        dict.fromkeys(
            str(item.get("requiredTool") or "").strip()
            for item in list(task.get("taskChecklist") or [])
            if str(item.get("requiredTool") or "").strip()
        )
    )
    if not complete:
        tool_names = [name for name in tool_names if name != "source_collection_stage_writeback_tool"]
    for tool_name in tool_names:
        append_conversation_event(
            project_root,
            session_id,
            turn_id,
            "tool_result",
            status="done",
            payload={
                "toolCall": {
                    "name": tool_name,
                    "status": "done",
                    "args": {"task_id": task.get("taskId")},
                    "result": "stage tool completed",
                }
            },
        )

def _stage_task_feedback_events(task: dict, *, complete: bool = True) -> list[dict]:
    tool_names = list(
        dict.fromkeys(
            str(item.get("requiredTool") or "").strip()
            for item in list(task.get("taskChecklist") or [])
            if str(item.get("requiredTool") or "").strip()
        )
    )
    if not complete:
        tool_names = [name for name in tool_names if name != "source_collection_stage_writeback_tool"]
    events: list[dict] = []
    for sequence, tool_name in enumerate(tool_names, start=1):
        events.append(
            {
                "sequence": sequence,
                "kind": "tool",
                "status": "done",
                "name": tool_name,
                "arguments": {"task_id": task.get("taskId")},
                "resultPreview": "stage tool completed",
            }
        )
    return events

def _workflow_scene_events_by_code(events, event_code):
    return [
        kwargs
        for args, kwargs in events
        if len(args) >= 3 and args[2] == event_code
    ]

def _stub_source_collection_search_background(monkeypatch):
    calls = []

    def fake_start(team_id, run_id, payload=None):
        calls.append({"teamId": team_id, "runId": run_id, "payload": dict(payload or {})})
        run = data_processing_service.get_processing_run(run_id)
        assignments = data_processing_service.list_collection_assignments(run_id)["assignments"]
        run_status = data_processing_service.get_processing_status(run_id)
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "runId": run_id,
            "status": "accepted",
            "executionMode": "background",
            "accepted": True,
            "provider": team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
            "executedQueryCount": 0,
            "skippedQueryCount": 0,
            "failedQueryCount": 0,
            "resultCount": 0,
            "recordCount": 0,
            "outputCount": 0,
            "importedCount": 0,
            "run": run,
            "runStatus": run_status,
            "storageArtifacts": {"runDirectory": f"workspace/teams/{team_id}/source_collection_runs/{run_id}"},
            "assignments": assignments,
            "outputs": [],
            "createdRecords": [],
            "imported": [],
            "executionEvents": [],
            "activeWorkRun": {
                "runId": run_id,
                "status": "queued",
                "currentPhase": "queued",
                "summary": "资料搜索已进入后台执行，页面可继续操作。",
                "openAssignmentCount": len(assignments),
                "recordCount": 0,
                "queryCount": 1,
                "storagePath": f"workspace/teams/{team_id}/source_collection_runs/{run_id}",
            },
            "boundaries": {
                "externalSearchTriggered": False,
                "externalSearchQueued": True,
                "metadataOnlyDownload": True,
                "writesFormalKnowledge": False,
                "writesRag": False,
                "writesOfficialGraph": False,
            },
            "nextActions": [],
        }

    monkeypatch.setattr(team_workflow_orchestration_service, "start_source_collection_search_background", fake_start)
    return calls

def _use_fake_local_research_config(monkeypatch):
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        lambda: {
            "llm": {
                "profiles": {},
                "model_library": {
                    "houmo_qwen35_9b_agent": {
                        "model": "qwen3.5-9b",
                        "provider": "local",
                        "prompt_cache": {"mode": "explicit_cache_control"},
                    }
                },
            }
        },
    )
    monkeypatch.setattr(team_workflow_orchestration_service, "build_effective_config", lambda public_config: public_config)

def _steward_pack_output(*, candidate_ids=None, confidence=0.61):
    normalized_candidate_ids = list(candidate_ids or ["hypothesis-1", "review-1"])
    return {
        "candidateType": "review_record",
        "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
        "evidenceRefs": [{"type": "review", "id": "review-1", "label": "Review 1"}],
        "claims": [{"claim": "Candidate is ready for knowledge governance.", "sourceRef": "paper-1"}],
        "candidateIds": normalized_candidate_ids,
        "targetDomain": "challenge_cup_neuro_algorithm",
        "sourceTrace": {"sourceIds": ["paper-1"], "reviewRecordIds": ["review-1"], "candidateGraphId": "graph-1"},
        "riskSummary": "Evidence is traceable, but experiment remains a smoke test.",
        "proposalPayload": {"title": "Govern context-gated routing hypothesis", "summary": "Add the hypothesis as governed knowledge."},
        "ratingSuggestion": {"importanceLevel": "high", "confidence": 0.66, "stability": "evolving", "reviewPriority": "elevated"},
        "approvalRequired": True,
        "uncertainty": ["experiment not yet validated"],
        "riskFlags": ["approval_required"],
        "confidence": confidence,
        "nextAction": "send_to_ingestion_approval_gate",
        "requiresReview": True,
    }

def _submit_steward_pack_through_source_review(team_id: str, candidate_id: str, knowledge_base_id: str, steward_agent_id: str) -> dict:
    source_pending = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team_id,
        candidate_id,
        {"knowledgeBaseId": knowledge_base_id, "proposedByAgentId": steward_agent_id},
    )
    inbox_source_id = source_pending["candidate"]["metadata"]["knowledgeIngestion"]["inboxSourceId"]
    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        team_id,
        inbox_source_id,
        decision="accepted",
        reviewed_by_agent_id=steward_agent_id,
    )
    knowledge_pending = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team_id,
        candidate_id,
        {
            "knowledgeBaseId": knowledge_base_id,
            "proposedByAgentId": steward_agent_id,
            "centralSourceId": reviewed["centralSource"]["centralSourceId"],
        },
    )
    return {"sourcePending": source_pending, "reviewedSource": reviewed, "knowledgePending": knowledge_pending}

def _fake_source_search_response(query, *, max_results, provider):
    query_text = str(query.get("query") or "neural source")
    return {
        "provider": provider,
        "searchUrl": f"https://api.example.test/search?q={query_text.replace(' ', '+')}",
        "results": [
            {
                "title": "Predictive coding cortical hierarchy",
                "sourceRef": "https://doi.org/10.0000/predictive-coding",
                "rawLocation": "https://api.example.test/works/10.0000/predictive-coding",
                "summary": "Metadata-only result for a predictive coding paper.",
                "sourceType": "paper",
                "metadata": {"doi": "10.0000/predictive-coding", "containerTitle": "Journal of Neural Computation"},
                "qualitySignals": {"providerScore": 98.7, "hasDoi": True},
            },
            {
                "title": "Cortical hierarchy dataset",
                "sourceRef": "https://doi.org/10.0000/cortical-dataset",
                "rawLocation": "https://api.example.test/works/10.0000/cortical-dataset",
                "summary": "Metadata-only result for a related dataset.",
                "sourceType": "dataset",
                "metadata": {"doi": "10.0000/cortical-dataset", "containerTitle": "Neural Data Archive"},
                "qualitySignals": {"providerScore": 87.5, "hasDoi": True},
            },
        ][:max_results],
    }

def _fake_low_quality_source_search_response(query, *, max_results, provider):
    query_text = str(query.get("query") or "neural source")
    return {
        "provider": provider,
        "searchUrl": f"https://api.example.test/search?q={query_text.replace(' ', '+')}",
        "results": [
            {
                "title": "机械设计与自动化控制中应注意的问题",
                "sourceRef": "https://doi.org/10.0000/mechanical-design",
                "rawLocation": "https://api.example.test/works/10.0000/mechanical-design",
                "summary": "高考志愿填报与专业目录页面摘录，未讨论神经预测编码、皮层层级或突触可塑性。",
                "sourceType": "paper",
                "metadata": {"doi": "10.0000/mechanical-design", "containerTitle": "Vocational Education Weekly"},
                "qualitySignals": {"providerScore": 88.1, "hasDoi": True},
            },
        ][:max_results],
    }

def _fake_mixed_excluded_source_search_response(query, *, max_results, provider):
    query_text = str(query.get("query") or "neural source")
    return {
        "provider": provider,
        "searchUrl": f"https://api.example.test/search?q={query_text.replace(' ', '+')}",
        "results": [
            {
                "title": "Empty landing page for predictive coding",
                "sourceRef": "https://doi.org/10.0000/empty-source",
                "rawLocation": "https://api.example.test/works/10.0000/empty-source",
                "summary": "Only a placeholder title was available; no abstract or usable source content.",
                "sourceType": "paper",
                "metadata": {"doi": "10.0000/empty-source", "containerTitle": "Placeholder Journal"},
                "qualitySignals": {"providerScore": 91.0, "hasDoi": True},
            },
            {
                "title": "Predictive coding useful web note",
                "sourceRef": "https://example.test/predictive-coding-useful-note",
                "rawLocation": "https://example.test/predictive-coding-useful-note",
                "summary": "A useful explanation of predictive coding hierarchy without DOI metadata.",
                "sourceType": "url",
                "metadata": {"containerTitle": "Neural Research Notes", "published": "2025"},
                "qualitySignals": {"providerScore": 74.0, "hasDoi": False},
            },
        ][:max_results],
    }

def _create_experiment_plan_with_active_baseline(team_id):
    hypothesis = team_workflow_orchestration_service.record_local_research_model_output(
        team_id,
        {
            "taskType": "algorithm_hypothesis_draft",
            "title": "Context gated routing",
            "createdByAgent": "Algorithm Hypothesis Agent",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "mapping-1", "label": "Mapping 1"}],
                "claims": [{"claim": "Context-gated routing may improve adaptation.", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["mapping-1"],
                "hypothesis": "Context-gated routing improves adaptation under shifting tasks.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better task adaptation at equal parameter count",
                "expectedComputeCost": "one small gating MLP and no extra experts",
                "experimentPlan": {
                    "dataset": "synthetic task-switch benchmark",
                    "metric": "validation accuracy and routing entropy",
                    "baseline": "standard MoE router",
                    "smokePlan": "train 200 mini-batches and compare metric direction",
                },
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.52,
                "nextAction": "send_to_research_review",
                "requiresReview": True,
            },
        },
    )["candidate"]
    team_workflow_orchestration_service.decide_research_review(
        team_id,
        {
            "candidateIds": [hypothesis["candidateId"]],
            "decision": "approve",
            "reviewedByAgent": "Research Coordination Agent",
        },
    )
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team_id,
        {"stageType": "experiment", "topic": "routing experiment plan"},
    )
    draft = team_workflow_orchestration_service.create_experiment_plan(
        team_id,
        {"stageRoundId": stage["stageRound"]["stageRoundId"], "createdByAgent": "Research Coordination Agent"},
    )
    baseline = team_workflow_orchestration_service.register_experiment_baseline_artifact(
        team_id,
        draft["plan"]["planId"],
        {
            "artifactPath": "workspace/experiments/baselines/standard-moe-router.json",
            "reproductionCommand": "python experiments/run_baseline.py --config configs/standard_moe_router.yaml",
            "evaluationCommand": "python experiments/evaluate.py --run standard-moe-router",
            "metricValue": "0.71 validation accuracy",
            "registeredByAgent": "Experiment Planning Agent",
        },
    )
    return {"stage": stage, "draft": draft, "baseline": baseline}

def _register_paper_note(team_id, *, evidence=True):
    payload = {
        "candidateType": "paper_note",
        "title": "Predictive coding note",
        "sourceUrl": "https://example.test/paper",
        "summary": "predictive coding key finding",
    }
    if evidence:
        payload["evidenceRefs"] = [{"type": "page_anchor", "id": "anchor-1"}]
    return team_workflow_orchestration_service.register_candidate_source(team_id, payload)["candidate"]["candidateId"]

def _register_typed_candidate(team_id, candidate_type, *, metadata=None):
    payload = {
        "candidateType": candidate_type,
        "title": f"{candidate_type} candidate",
        "sourceUrl": "https://example.test/c",
        "evidenceRefs": [{"type": "page_anchor", "id": "anchor-1"}],
    }
    if metadata:
        payload["metadata"] = metadata
    return team_workflow_orchestration_service.register_candidate_source(team_id, payload)["candidate"]["candidateId"]

def _mock_local_research_invoke(monkeypatch, candidate, *, valid=True):
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "invoke_local_research_model",
        lambda team_id, payload, *, llm_client_factory=None: {
            "candidate": candidate,
            "validation": {"valid": valid, "issues": []},
            "task": {"taskId": "task-x"},
        },
    )

def _seed_plan_with_smoke_run(team_id):
    store = team_workflow_orchestration_service._load_experiment_plan_store(team_id)
    plan = {
        "planId": "exp_deliverable",
        "status": "smoke_passed",
        "dataset": "synthetic",
        "metric": ["accuracy"],
        "baseline": "nearest_centroid",
        "smokePlan": {},
        "smokeRunResults": [{"smokeRunId": "sr-1", "artifactHash": "sha256:abc", "status": "passed"}],
        "updatedAt": "2026-06-25T00:00:00+00:00",
    }
    store.setdefault("plans", []).append(plan)
    store["activePlanId"] = "exp_deliverable"
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team_id), store
    )

_PRD_VALIDATE_PATHS = [
    "/teams/{team_id}/workflow-orchestration/" + endpoint
    for endpoint in (
        "knowledge-collection/extract",
        "research/mechanisms/extract",
        "research/mechanisms/map",
        "research/hypotheses/generate",
        "research/review/decide",
        "experiments/plans/{plan_id}/smoke-run",
        "iterations/propose",
        "deliverables/export",
    )
]

def _seed_experiment_plan(team_id, plan_id="exp_plan_smoke", *, baseline=True):
    store = team_workflow_orchestration_service._load_experiment_plan_store(team_id)
    plan = {
        "planId": plan_id,
        "status": "draft",
        "dataset": "synthetic_classification",
        "metric": ["accuracy", "macro_f1"],
        "smokePlan": {"seed": 42, "successThreshold": {"macro_f1_delta": 0.0}},
        "smokeResults": [],
        "updatedAt": "2026-06-25T00:00:00+00:00",
    }
    if baseline:
        plan["baseline"] = "nearest_centroid"
    store.setdefault("plans", []).append(plan)
    store["activePlanId"] = plan_id
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team_id), store
    )
    return plan_id

def _seed_formal_full_run_plan(team_id, plan_id="exp_formal_full_run"):
    from core.research import formal_runner

    store = team_workflow_orchestration_service._load_experiment_plan_store(team_id)
    plan = {
        "planId": plan_id,
        "status": "smoke_passed",
        "experimentContract": {
            "schemaVersion": 2,
            "adapterSelection": {"resolvedAdapterId": formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER},
            "methodConfig": {"seeds": [17, 42, 101]},
        },
        "contractValidation": {"valid": True},
        "readiness": {"readyForFullRun": True},
        "updatedAt": "2026-06-25T00:00:00+00:00",
    }
    store.setdefault("plans", []).append(plan)
    store["activePlanId"] = plan_id
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team_id), store
    )
    return plan_id


# Allow case modules to `from ...helpers import *` including private helpers.
__all__ = [name for name in globals() if not name.startswith("__")]
