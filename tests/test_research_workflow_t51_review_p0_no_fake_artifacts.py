"""P0 RED: no fake turn materializer; forged cross-team/run read-back rejected."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
    TurnNotReadyError,
    complete_agent_turn_outputs,
    wait_for_agent_turn_terminal,
)
from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
    build_canonical_ref,
    load_scoped_artifact_payload,
    materialize_domain_artifact,
    read_domain_artifact,
)
from core.web.services.team_workflow.research_runtime.domain_ports import AgentTaskHandle
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)


def test_parallel_domain_artifact_materialize_is_forbidden() -> None:
    with pytest.raises(RuntimeError, match="parallel domain_artifacts"):
        materialize_domain_artifact(
            kind="source_candidate_batch",
            payload={"candidates": []},
            team_id="team-a",
            authority_run_id="run-a",
        )


def test_forged_cross_team_readback_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests._support.team_workflow.helpers import _use_tmp_project_root

    _use_tmp_project_root(tmp_path, monkeypatch)
    import core.infrastructure.path_containment as path_containment

    monkeypatch.setattr(path_containment, "PROJECT_ROOT", tmp_path)

    from core.web.services import agent_directory_service, team_service
    from core.web.services.team_workflow.source_collection.candidates import (
        register_candidate_source,
    )

    agent = agent_directory_service.create_agent_instance(
        display_name="P0 Agent", role_key="source_finder", created_by="p0"
    )
    team = team_service.create_team(
        name="P0 Team A",
        members=[{"agentId": agent["agentId"], "role": "source_finder"}],
    )
    team_a = str(team["teamId"])
    register_candidate_source(
        team_a,
        {
            "title": "Scoped paper",
            "sourceUrl": "https://doi.org/10.0/p0",
            "candidateType": "source_manifest",
            "sourceKind": "paper",
            "metadata": {
                "sourceCollectionRunId": "sc-run-a",
                "workflowRunId": "wf-run-a",
            },
        },
    )

    payload = load_scoped_artifact_payload(
        "source_candidate_batch",
        team_id=team_a,
        authority_run_id="sc-run-a",
        workflow_run_id="wf-run-a",
    )
    assert payload is not None
    assert int(payload.get("candidateCount") or 0) >= 1
    content_hash = canonical_sha256(payload)
    real_ref = build_canonical_ref(
        kind="source_candidate_batch",
        team_id=team_a,
        authority_run_id="sc-run-a",
        content_hash=content_hash,
    )
    # read_domain_artifact hashes with workflow_run_id="" — rebuild matching payload
    payload_for_read = load_scoped_artifact_payload(
        "source_candidate_batch",
        team_id=team_a,
        authority_run_id="sc-run-a",
        workflow_run_id="",
    )
    assert payload_for_read is not None
    read_hash = canonical_sha256(payload_for_read)
    real_ref = build_canonical_ref(
        kind="source_candidate_batch",
        team_id=team_a,
        authority_run_id="sc-run-a",
        content_hash=read_hash,
    )
    assert read_domain_artifact(real_ref) is not None

    forged = build_canonical_ref(
        kind="source_candidate_batch",
        team_id="team-b",
        authority_run_id="sc-run-b",
        content_hash=read_hash,
    )
    assert read_domain_artifact(forged) is None


def test_wait_for_non_terminal_turn_raises_not_ready() -> None:
    with patch(
        "core.web.services.session.turn_diagnostics.get_session_turn_completion_snapshot",
        return_value={
            "terminal": False,
            "isRunning": True,
            "terminalStatus": "",
        },
    ):
        with pytest.raises(TurnNotReadyError):
            wait_for_agent_turn_terminal(
                "session-x", "turn-x", timeout_ms=300, poll_ms=50
            )


def test_complete_turn_does_not_invent_example_local_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production collector must not synthesize example.local sources."""
    calls: list[str] = []

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
        lambda *a, **k: {
            "terminal": True,
            "terminalStatus": "ready",
            "isRunning": False,
        },
    )

    def fake_reconcile(*_a, **_k):
        calls.append("reconcile")
        return {}

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_writeback.reconcile_source_collection_stage_session_task_after_turn",
        fake_reconcile,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.artifact_readback_registry.load_scoped_artifact_payload",
        lambda *a, **k: {
            "teamId": "team-p0",
            "sourceCollectionRunId": "sc-p0",
            "workflowRunId": "run-p0",
            "candidates": [],
            "candidateCount": 0,
        },
    )

    action = PendingAction(
        action_id="act-p0",
        run_id="run-p0",
        node_run_id="nr-p0",
        node_id="source_finding",
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="",
    )
    handle = AgentTaskHandle(
        session_id="session-p0",
        session_attempt=1,
        task_id="task-p0",
        turn_id="turn-p0",
    )
    refs = complete_agent_turn_outputs(
        action=action,
        handle=handle,
        input_snapshot={
            "teamId": "team-p0",
            "sourceCollectionRunId": "sc-p0",
            "projectId": "proj-p0",
        },
    )
    assert len(refs) == 1
    assert refs[0]["kind"] == "source_candidate_batch"
    assert "example.local" not in str(refs)
    assert calls == ["reconcile"]
    with pytest.raises(ModuleNotFoundError):
        __import__(
            "core.web.services.team_workflow.research_runtime.agent_turn_materializer"
        )


def test_completed_project_agent_task_is_closed_before_successor_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests._support.team_workflow.helpers import _use_tmp_project_root

    _use_tmp_project_root(tmp_path, monkeypatch)

    from core.web.services import (
        agent_directory_service,
        session_service,
        team_service,
        team_workflow_orchestration_service,
    )
    from core.web.services.team_workflow.research_project_agent_tasks import (
        start_research_project_agent_task,
        update_research_project_agent_task_status,
    )

    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda *_args, **_kwargs: {
            "accepted": True,
            "turnId": "turn-p0",
            "status": "running",
            "acceptedAt": "2026-08-26T00:00:00+00:00",
        },
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="P0 假设设计 Agent",
        role_key="challenge_cup_experiment_planner",
    )
    team = team_service.create_team(
        name="P0 假设设计团队",
        members=[
            {
                "agentId": agent["agentId"],
                "agentName": agent["displayName"],
                "role": "experiment_planner",
            }
        ],
    )
    project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": "P0 假设设计项目"},
    )["project"]
    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "hypothesis_design",
            "idempotencyKey": "hypothesis-p0",
            "workflowRunId": "run-p0",
            "workflowNodeId": "hypothesis_design",
            "nodeRunId": "nr-hypothesis-p0",
            "sourceCollectionRunId": "sc-p0",
        },
    )
    task = started["task"]
    completed = update_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
        task["taskId"],
        status="completed",
        result_refs=["challenge-sci-096"],
    )
    assert completed["status"] == "completed"

    calls: list[object] = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
        lambda *_a, **_k: {"terminal": True, "terminalStatus": "completed"},
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.collect_required_artifact_refs",
        lambda *_a, **_k: calls.append("collect")
        or [
            {
                "canonicalRef": "hypothesis_set://team-p0/run-p0/hash-p0",
                "kind": "hypothesis_set",
                "sha256": "a" * 64,
                "version": "1.0.0",
            }
        ],
    )

    def reconcile_project_tasks(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "tasks": [
                {
                    "taskId": task["taskId"],
                    "status": "completed",
                    "resultRefs": ["challenge-sci-096"],
                }
            ]
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks.get_research_project_agent_task_status",
        reconcile_project_tasks,
    )

    refs = complete_agent_turn_outputs(
        action=PendingAction(
            action_id="act-hypothesis-p0",
            run_id="run-p0",
            node_run_id="nr-hypothesis-p0",
            node_id="hypothesis_design",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="",
        ),
        handle=AgentTaskHandle(
            session_id=task["sessionId"],
            session_attempt=task["sessionAttempt"],
            task_id=task["taskId"],
            turn_id=task["turn"]["turnId"],
        ),
        input_snapshot={
            "teamId": team["teamId"],
            "projectId": project["projectId"],
            "sourceCollectionRunId": "sc-p0",
        },
    )

    assert refs[0]["kind"] == "hypothesis_set"
    assert calls[0] == "collect"
    assert calls[1] == (
        (team["teamId"], project["projectId"]),
        {},
    )
