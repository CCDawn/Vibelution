from __future__ import annotations

from typing import Any

import pytest

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services import team_service, team_workflow_orchestration_service
from core.web.services.team_workflow.research_runtime.experiment_stage_bootstrap import (
    ExperimentStageBootstrapError,
)
from core.web.services.team_workflow.research_runtime.domain_ports import (
    BindingResolution,
)
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    _create_real_agent_task,
)
from core.web.services.team_workflow.research_runtime.task_adapter_registry import (
    resolve_agent_task_adapter,
)
from tests._support.team_workflow.helpers import _use_tmp_project_root


def _accepted_package() -> dict[str, Any]:
    return {
        "accepted": True,
        "knowledgeItems": [{"knowledgeItemId": "ki-1", "contentHash": "b" * 64}],
    }


def _hypothesis_action() -> PendingAction:
    return PendingAction(
        action_id="act-hypothesis",
        run_id="run-sci-096",
        node_run_id="nr-run-sci-096-hypothesis_design-a3",
        node_id="hypothesis_design",
        # First dispatch: retry attempts (attempt >= 2) require the workflow
        # Ledger for ancestry resolution and fail closed without it; this
        # test exercises bootstrap ordering, not retry lineage.
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id="snap:run-sci-096:hypothesis_design",
        budget_policy_hash="budget-policy",
    )


def test_bootstrap_ignores_nodes_outside_hypothesis_entry(monkeypatch) -> None:
    from core.web.services.team_workflow.research_runtime import (
        experiment_stage_bootstrap,
        real_domain_ports,
    )

    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        experiment_stage_bootstrap,
        "_start_research_stage_round",
        lambda team_id, payload: calls.append((team_id, payload)),
    )

    result = experiment_stage_bootstrap.ensure_experiment_stage_round_for_agent_node(
        node_id="protocol_design",
        team_id="research-team",
        project_id="challenge-sci-096",
        input_snapshot={"researchObjectiveContract": {"question": "研究问题"}},
        requested_by_agent="agent-hypothesis",
    )

    assert result is None
    assert calls == []


def test_bootstrap_blocks_hypothesis_without_accepted_package() -> None:
    from core.web.services.team_workflow.research_runtime import (
        experiment_stage_bootstrap,
        real_domain_ports,
    )

    with pytest.raises(
        ExperimentStageBootstrapError,
        match="knowledge_package_not_materialized",
    ):
        experiment_stage_bootstrap.ensure_experiment_stage_round_for_agent_node(
            node_id="hypothesis_design",
            team_id="research-team",
            project_id="challenge-sci-096",
            input_snapshot={"researchObjectiveContract": {"question": "研究问题"}},
            requested_by_agent="agent-hypothesis",
        )


def test_bootstrap_starts_idempotent_experiment_round_from_run_snapshot(
    monkeypatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        experiment_stage_bootstrap,
    )

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_start(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((team_id, payload))
        return {"created": True, "stageRound": {"stageRoundId": "stage-1"}}

    monkeypatch.setattr(
        experiment_stage_bootstrap,
        "_start_research_stage_round",
        fake_start,
    )

    result = experiment_stage_bootstrap.ensure_experiment_stage_round_for_agent_node(
        node_id="hypothesis_design",
        team_id="research-team",
        project_id="challenge-sci-096",
        input_snapshot={
            "researchObjectiveContract": {
                "question": "如何提升稀疏预测误差控制的可靠性？"
            }
        },
        requested_by_agent="agent-hypothesis",
        accepted_knowledge_package=_accepted_package(),
    )

    assert result == {"created": True, "stageRound": {"stageRoundId": "stage-1"}}
    assert calls == [
        (
            "research-team",
            {
                "stageType": "experiment",
                "researchProjectId": "challenge-sci-096",
                "topic": "如何提升稀疏预测误差控制的可靠性？",
                "requestedByAgent": "agent-hypothesis",
            },
        )
    ]


def test_bootstrap_reuses_the_active_experiment_round(tmp_path, monkeypatch) -> None:
    from core.web.services.team_workflow.research_runtime import (
        experiment_stage_bootstrap,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": "SCI-096"},
    )["project"]
    team_workflow_orchestration_service.activate_research_project(
        team["teamId"],
        project["projectId"],
    )
    kwargs = {
        "node_id": "hypothesis_design",
        "team_id": team["teamId"],
        "project_id": project["projectId"],
        "input_snapshot": {
            "researchObjectiveContract": {"question": "研究问题"}
        },
        "requested_by_agent": "agent-hypothesis",
        "accepted_knowledge_package": _accepted_package(),
    }

    first = experiment_stage_bootstrap.ensure_experiment_stage_round_for_agent_node(
        **kwargs
    )
    replay = experiment_stage_bootstrap.ensure_experiment_stage_round_for_agent_node(
        **kwargs
    )

    assert first is not None
    assert replay is not None
    assert first["created"] is True
    assert replay["created"] is False
    assert replay["continued"] is True
    assert replay["stageRound"]["stageRoundId"] == first["stageRound"]["stageRoundId"]


def test_real_agent_task_bootstraps_stage_before_starting_hypothesis_agent(
    monkeypatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        experiment_stage_bootstrap,
        real_domain_ports,
    )
    from core.web.services.team_workflow import research_project_agent_tasks

    order: list[str] = []
    authority_calls: list[dict[str, Any]] = []
    challenge_contract = {
        "workflowRunId": "run-sci-096",
        "workflowNodeId": "hypothesis_design",
        "nodeRunId": "nr-run-sci-096-hypothesis_design-a3",
    }
    receipt_binding = {
        "workflowRunId": "run-sci-096",
        "formalNodeId": "hypothesis_design",
        "formalNodeRunId": "nr-run-sci-096-hypothesis_design-a3",
    }
    monkeypatch.setattr(
        real_domain_ports,
        "_formal_task_authorities",
        lambda **_kwargs: (challenge_contract, receipt_binding),
    )

    def fake_bootstrap(**kwargs: Any) -> dict[str, Any]:
        order.append("bootstrap")
        assert kwargs["node_id"] == "hypothesis_design"
        assert kwargs["team_id"] == "research-team"
        assert kwargs["project_id"] == "challenge-sci-096"
        assert kwargs["requested_by_agent"] == "agent-hypothesis"
        return {"created": True}

    def fake_start(
        team_id: str,
        project_id: str,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        order.append("agent")
        authority_calls.append(dict(kwargs))
        assert team_id == "research-team"
        assert project_id == "challenge-sci-096"
        assert payload["taskKind"] == "hypothesis_design"
        assert payload["workflowRunId"] == "run-sci-096"
        assert payload["workflowNodeId"] == "hypothesis_design"
        assert payload["sourceCollectionRunId"] == "dprun-sci-096"
        assert payload["targetRef"] == (
            "node-run:nr-run-sci-096-hypothesis_design-a3"
        )
        return {
            "sessionId": "session-hypothesis",
            "taskId": "task-hypothesis",
            "startedTurnId": "turn-hypothesis",
        }

    monkeypatch.setattr(
        experiment_stage_bootstrap,
        "ensure_experiment_stage_round_for_agent_node",
        fake_bootstrap,
    )
    monkeypatch.setattr(
        research_project_agent_tasks,
        "start_research_project_agent_task",
        fake_start,
    )

    action = _hypothesis_action()
    spec = resolve_agent_task_adapter(action.node_id)
    assert spec is not None
    handle = _create_real_agent_task(
        action,
        BindingResolution(
            agent_id="agent-hypothesis",
            role_key="hypothesis_designer",
            binding_snapshot_id="snap:run-sci-096:hypothesis_design",
        ),
        {
            "teamId": "research-team",
            "projectId": "challenge-sci-096",
            "sourceCollectionRunId": "dprun-sci-096",
            "researchObjectiveContract": {"question": "研究问题"},
        },
        adapter_spec=spec,
    )

    assert order == ["bootstrap", "agent"]
    assert authority_calls == [
        {
            "_challenge_task_contract": challenge_contract,
            "_model_invocation_receipt_binding": receipt_binding,
        }
    ]
    assert handle.session_id == "session-hypothesis"
    assert handle.task_id == "task-hypothesis"
    assert handle.turn_id == "turn-hypothesis"
