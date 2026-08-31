from __future__ import annotations

import json

import pytest

from core.web.services import team_workflow_orchestration_service
from core.web.services.team_workflow.research_project_agent_tasks import (
    TASK_KIND_CONTRACTS,
)
from core.web.services.team_workflow.research_project_hypothesis_context import (
    build_hypothesis_input_context,
    build_stage_one_grounded_generation_context,
)
from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.artifact_quality_gate import (
    ArtifactQualityError,
    validate_artifact_quality,
)
from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
    load_scoped_artifact_payload,
)
from core.web.services.team_workflow.research_runtime.task_adapter_registry import (
    resolve_agent_task_adapter,
)
from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
    list_workflow_artifacts,
    put_workflow_artifact,
)
from tools.challenge_cup_operations_tools import (
    challenge_cup_experiment_writeback_tool,
)


def _portfolio(*, run_id: str, counter_ref: str) -> dict[str, object]:
    return {
        "portfolioId": "portfolio-sci-096-a5",
        "runId": run_id,
        "maxCandidates": 3,
        "maxEvolutionRounds": 2,
        "currentEvolutionRound": 1,
        "candidates": [
            {
                "candidateId": "hypothesis-rate-temporal-1",
                "claim": (
                    "在相同平均放电率下，提高群体同步将改善时间编码判别，"
                    "但不会同等改善纯 rate-code 基线。"
                ),
                "scores": {
                    "novelty": 0.7,
                    "competitionFit": 0.9,
                    "falsifiability": 0.9,
                    "evidenceSupport": 0.7,
                    "feasibility": 0.8,
                },
                "counterEvidenceRefs": [counter_ref],
                "derivedFromCandidateIds": [],
                "status": "ranked",
                "reviewRef": "knowledge-package-review",
            }
        ],
    }


def _task_context(*, run_id: str, counter_ref: str) -> dict[str, object]:
    return {
        "teamId": "research-team",
        "researchProjectId": "challenge-sci-096",
        "task": {
            "taskId": "task-hypothesis-a5",
            "taskKind": "hypothesis_design",
            "agentId": "agent-planner",
            "researchProjectId": "challenge-sci-096",
            "workflowRunId": run_id,
            "workflowNodeId": "hypothesis_design",
            "sourceCollectionRunId": "dprun-sci-096",
            "sessionId": "session-hypothesis-a5",
            "turn": {"turnId": "turn-hypothesis-a5"},
        },
        "hypothesisInput": {
            "status": "ready",
            "allowedEvidenceRefs": [counter_ref],
        },
    }


def test_hypothesis_node_has_a_dedicated_task_contract() -> None:
    spec = resolve_agent_task_adapter("hypothesis_design")

    assert spec is not None
    assert spec.task_key == "hypothesis_design"
    contract = TASK_KIND_CONTRACTS["hypothesis_design"]
    assert "hypothesis_set" in str(contract)
    assert "dataset" not in str(contract).lower()
    assert "baseline" not in str(contract).lower()


def test_hypothesis_context_uses_the_accepted_candidate_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.human_acceptance_artifact.load_accepted_knowledge_package_from_receipt",
        lambda _store, **_kwargs: {
            "candidateId": "accepted-package",
            "knowledgeBaseId": "team:research-team:kb-1",
            "knowledgeItems": [{"knowledgeItemId": "item-1"}],
            "sourceArtifactIds": ["source-package-1"],
            "approval": {"reviewedByAgentId": "reviewer-1"},
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.candidates.list_candidate_store",
        lambda *_args, **_kwargs: {
            "candidates": [
                {
                    "candidateId": "accepted-package",
                    "metadata": {
                        "output": {
                            "claims": [
                                {
                                    "claim": "Rate and temporal codes have opposing adaptation responses.",
                                    "sourceRef": "candidate-counter-1",
                                }
                            ]
                        }
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_knowledge_service.list_knowledge_items",
        lambda *_args, **_kwargs: {
            "items": [
                {
                    "knowledgeItemId": "item-1",
                    "title": "Accepted package",
                    "summary": "Reviewed",
                    "content": '{"claims":[',
                }
            ]
        },
    )

    context = build_hypothesis_input_context(
        "research-team",
        {
            "workflowRunId": "run-sci-096",
            "sourceCollectionRunId": "dprun-sci-096",
        },
        store=object(),
    )

    assert context["status"] == "ready"
    assert context["allowedEvidenceRefs"] == [
        "candidate-counter-1",
        "source-package-1",
    ]
    assert context["evidenceClaims"] == [
        {
            "claim": "Rate and temporal codes have opposing adaptation responses.",
            "sourceRef": "candidate-counter-1",
        }
    ]


def test_stage_one_grounded_context_uses_the_run_pinned_source_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from core.research.competition.stage_one_completion_policy import (
        load_stage_one_completion_policy,
    )
    from core.web.services.team_workflow import research_project_hypothesis_context

    captured: dict[str, object] = {}

    def fake_build(team_id, task, store=None):
        captured.update({"teamId": team_id, "task": task, "store": store})
        return {"status": "ready", "allowedEvidenceRefs": ["evidence:accepted-1"]}

    monkeypatch.setattr(
        research_project_hypothesis_context,
        "build_hypothesis_input_context",
        fake_build,
    )
    run = SimpleNamespace(
        team_id="research-team",
        question_id="SCI-091",
        input_snapshot_json=json.dumps(
            {
                "stageOneCompletionPolicy": load_stage_one_completion_policy().to_dict(),
                "sourceCollectionRunId": "source-stage-one",
            }
        ),
    )
    store = SimpleNamespace(get_run=lambda _run_id: run)

    context = build_stage_one_grounded_generation_context(
        "research-team",
        "run-stage-one",
        question_id="SCI-091",
        store=store,
    )

    assert context == {
        "status": "ready",
        "allowedEvidenceRefs": ["evidence:accepted-1"],
    }
    assert captured["task"] == {
        "workflowRunId": "run-stage-one",
        "sourceCollectionRunId": "source-stage-one",
    }


def test_hypothesis_writeback_uses_scoped_formal_artifact_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    context = _task_context(
        run_id="run-sci-096",
        counter_ref="candidate-counter-rate-code",
    )
    updates: list[dict[str, object]] = []
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_context",
        lambda *_args, **_kwargs: context,
        raising=False,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        lambda _team_id, _project_id, _task_id, **kwargs: updates.append(kwargs)
        or {"status": kwargs["status"]},
        raising=False,
    )

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="challenge-sci-096",
            task_id="task-hypothesis-a5",
            operation="record_hypothesis_set",
            payload_json=json.dumps(
                _portfolio(
                    run_id="run-sci-096",
                    counter_ref="candidate-counter-rate-code",
                ),
                ensure_ascii=False,
            ),
            recorded_by_agent="agent-planner",
        )
    )

    assert result["status"] == "ok", result
    assert result["operation"] == "record_hypothesis_set"
    rows = list_workflow_artifacts(
        "research-team",
        kind="hypothesis_set",
        workflow_run_id="run-sci-096",
        source_collection_run_id="dprun-sci-096",
    )
    assert len(rows) == 1
    assert rows[0]["payload"]["candidates"][0]["candidateId"] == (
        "hypothesis-rate-temporal-1"
    )
    assert updates == [
        {"status": "running", "result_refs": ["portfolio-sci-096-a5"]}
    ]

    read_back = load_scoped_artifact_payload(
        "hypothesis_set",
        team_id="research-team",
        authority_run_id="dprun-sci-096",
        workflow_run_id="run-sci-096",
    )
    assert read_back is not None
    assert read_back["payload"]["portfolioId"] == "portfolio-sci-096-a5"
    assert read_back["payload"]["hypothesis_count"] == 1


def test_candidate_writeback_routes_to_fragment_and_fan_in_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _task_context(run_id="run-sci-096", counter_ref="counter-1")
    context["task"].update(
        {
            "nodeRunId": "node-run-1",
            "selectionId": "selection-1",
            "candidateId": "H1",
            "subtaskId": "node-run-1:selection-1:H1",
        }
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_context",
        lambda *_args, **_kwargs: context,
        raising=False,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.hypothesis_scoped_execution.record_candidate_fragment_and_maybe_aggregate",
        lambda **kwargs: calls.append(kwargs)
        or {
            "status": "fragment_recorded",
            "fragment": {"artifact": {"recordId": "fragment-H1"}},
            "hypothesisSetRef": "",
        },
    )
    updates: list[dict[str, object]] = []
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        lambda *_args, **kwargs: updates.append(kwargs)
        or {"status": kwargs["status"]},
        raising=False,
    )

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="challenge-sci-096",
            task_id="task-hypothesis-a5",
            operation="record_hypothesis_fragment",
            payload_json=json.dumps(
                {
                    "statement": "claim H1",
                    "mechanism": "mechanism H1",
                    "predictions": ["prediction H1"],
                    "falsificationCriteria": ["falsify H1"],
                    "evidenceRefs": ["counter-1"],
                    "counterEvidenceRefs": ["counter-1"],
                    "scores": {
                        "novelty": 0.8,
                        "competitionFit": 0.8,
                        "falsifiability": 0.8,
                        "evidenceSupport": 0.8,
                        "feasibility": 0.8,
                    },
                }
            ),
            recorded_by_agent="agent-planner",
        )
    )

    assert result["status"] == "ok"
    assert result["operation"] == "record_hypothesis_fragment"
    assert calls[0]["task_context"] == context
    assert updates == [{"status": "running", "result_refs": ["fragment-H1"]}]


@pytest.mark.parametrize("untrusted_run_id", ["", "node-run:nr-run-sci-096-hypothesis-a5"])
def test_hypothesis_writeback_binds_run_id_from_the_formal_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    untrusted_run_id: str,
) -> None:
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    context = _task_context(
        run_id="run-sci-096",
        counter_ref="candidate-counter-rate-code",
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_context",
        lambda *_args, **_kwargs: context,
        raising=False,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        lambda *_args, **kwargs: {"status": kwargs["status"]},
        raising=False,
    )
    payload = _portfolio(
        run_id=untrusted_run_id,
        counter_ref="candidate-counter-rate-code",
    )
    if not untrusted_run_id:
        payload.pop("runId")

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="challenge-sci-096",
            task_id="task-hypothesis-a5",
            operation="record_hypothesis_set",
            payload_json=json.dumps(payload, ensure_ascii=False),
            recorded_by_agent="agent-planner",
        )
    )

    assert result["status"] == "ok", result
    assert result["response"]["scopeBinding"] == {
        "workflowRunId": "run-sci-096",
        "source": "bound_hypothesis_task",
    }
    rows = list_workflow_artifacts(
        "research-team",
        kind="hypothesis_set",
        workflow_run_id="run-sci-096",
        source_collection_run_id="dprun-sci-096",
    )
    assert len(rows) == 1
    assert rows[0]["payload"]["runId"] == "run-sci-096"


def test_hypothesis_writeback_rejects_unbound_counter_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    context = _task_context(
        run_id="run-sci-096",
        counter_ref="candidate-counter-rate-code",
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_context",
        lambda *_args, **_kwargs: context,
        raising=False,
    )

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="challenge-sci-096",
            task_id="task-hypothesis-a5",
            operation="record_hypothesis_set",
            payload_json=json.dumps(
                _portfolio(
                    run_id="run-sci-096",
                    counter_ref="invented-counter-evidence",
                ),
                ensure_ascii=False,
            ),
            recorded_by_agent="agent-planner",
        )
    )

    assert result["status"] == "error"
    assert "counter-evidence" in result["message"]
    assert list_workflow_artifacts(
        "research-team",
        kind="hypothesis_set",
        workflow_run_id="run-sci-096",
    ) == []


def test_hypothesis_quality_gate_rejects_an_empty_portfolio() -> None:
    manifest = {"artifactId": "hypothesis_set:empty"}
    payload = {
        "portfolioId": "portfolio-empty",
        "runId": "run-sci-096",
        "maxCandidates": 3,
        "maxEvolutionRounds": 2,
        "currentEvolutionRound": 1,
        "candidates": [],
    }

    with pytest.raises(ArtifactQualityError, match="at least one"):
        validate_artifact_quality(
            {"runId": "run-sci-096", "inputSnapshot": {}},
            node_id="hypothesis_design",
            manifests=[manifest],
            payloads={manifest["artifactId"]: payload},
        )
