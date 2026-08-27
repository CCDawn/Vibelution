"""P0 RED: no fake turn materializer; forged cross-team/run read-back rejected."""

from __future__ import annotations

import json
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
from core.web.services.team_workflow.research_runtime.domain_ports import (
    AgentTaskHandle,
)
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
    from core.infrastructure import path_containment

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
    with (
        patch(
            "core.web.services.session.turn_diagnostics.get_session_turn_completion_snapshot",
            return_value={
                "terminal": False,
                "isRunning": True,
                "terminalStatus": "",
            },
        ),
        pytest.raises(TurnNotReadyError),
    ):
        wait_for_agent_turn_terminal(
            "session-x", "turn-x", timeout_ms=300, poll_ms=50
        )


def test_wait_for_project_reconcilable_needs_continue_turn() -> None:
    snapshot = {
        "terminal": True,
        "isRunning": False,
        "terminalStatus": "needs_continue",
    }
    with patch(
        "core.web.services.session.turn_diagnostics.get_session_turn_completion_snapshot",
        return_value=snapshot,
    ):
        with pytest.raises(RuntimeError, match="agent_turn_terminal_failed"):
            wait_for_agent_turn_terminal("session-x", "turn-x")
        assert wait_for_agent_turn_terminal(
            "session-x",
            "turn-x",
            reconcilable_terminal_statuses=frozenset({"needs_continue"}),
        ) == snapshot


def test_project_needs_continue_without_canonical_result_stays_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
        lambda *_args, **_kwargs: {
            "terminal": True,
            "terminalStatus": "needs_continue",
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.collect_required_artifact_refs",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks.get_research_project_agent_task_status",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks._read_research_project_agent_task_record",
        lambda *_args, **_kwargs: {
            "taskId": "task-p0",
            "status": "incomplete",
            "resultRefs": [],
            "failureCode": "task_result_not_recorded",
        },
    )

    with pytest.raises(RuntimeError, match="project_agent_task_terminal_failed"):
        complete_agent_turn_outputs(
            action=PendingAction(
                action_id="act-p0",
                run_id="run-p0",
                node_run_id="nr-p0",
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
                session_id="session-p0",
                session_attempt=1,
                task_id="task-p0",
                turn_id="turn-p0",
            ),
            input_snapshot={
                "teamId": "team-p0",
                "projectId": "project-p0",
                "sourceCollectionRunId": "source-run-p0",
            },
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


def test_source_collection_turn_receives_continuable_not_project_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source-collection turns get the continuable set, never the project one.

    ``needs_continue``/``paused_limit`` are resumable protocol states, so the
    source-collection adapter waits with the continuable reconcilable set and
    continues the turn itself; the project-task reconcilable set stays
    reserved for research_project turns.
    """
    captured_kwargs: list[dict[str, object]] = []

    def record_wait(*_args: object, **kwargs: object) -> dict[str, object]:
        captured_kwargs.append(dict(kwargs))
        return {"terminal": True, "isRunning": False, "terminalStatus": "ready"}

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
        record_wait,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.collect_required_artifact_refs",
        lambda *_a, **_k: [],
    )
    reconciles: list[dict[str, object]] = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_writeback.reconcile_source_collection_stage_session_task_after_turn",
        lambda *_a, **_k: reconciles.append({"called": True}),
    )
    submits: list[dict[str, object]] = []

    def fail_submit(*_args: object, **kwargs: object) -> dict[str, object]:
        submits.append(dict(kwargs))
        raise AssertionError("continuation must not fire for a ready terminal")

    monkeypatch.setattr(
        "core.web.services.session.submit.submit_session_message",
        fail_submit,
    )

    refs = complete_agent_turn_outputs(
        action=PendingAction(
            action_id="act-sc-gate",
            run_id="run-sc-gate",
            node_run_id="nr-sc-gate",
            node_id="source_finding",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="",
        ),
        handle=AgentTaskHandle(
            session_id="session-sc-gate",
            session_attempt=1,
            task_id="task-sc-gate",
            turn_id="turn-sc-gate",
        ),
        input_snapshot={
            "teamId": "team-sc-gate",
            "projectId": "project-sc-gate",
            "sourceCollectionRunId": "sc-gate",
        },
    )

    assert refs == []
    assert reconciles == [{"called": True}]
    assert submits == []
    assert len(captured_kwargs) == 1
    # A source_collection turn must never receive the project-task
    # reconcilable set; it gets the protocol continuable set instead.
    from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
        AGENT_TURN_CONTINUABLE_TERMINAL_STATUSES,
    )

    assert (
        captured_kwargs[0].get("reconcilable_terminal_statuses")
        == AGENT_TURN_CONTINUABLE_TERMINAL_STATUSES
    )
    assert "needs_continue" in captured_kwargs[0].get(
        "reconcilable_terminal_statuses"
    )
    assert "paused_limit" in captured_kwargs[0].get(
        "reconcilable_terminal_statuses"
    )


def test_source_collection_needs_continue_turn_is_continued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parked needs_continue turn is continued on the same session.

    The node must not fail: the adapter submits the canonical continue
    request, keeps waiting on the new turn, and downstream SC reconciliation
    anchors to the final continuation turn.
    """
    wait_calls: list[tuple[object, dict[str, object]]] = []

    def scripted_wait(session_id, turn_id, **kwargs):
        wait_calls.append((turn_id, dict(kwargs)))
        if turn_id == "turn-sc-park":
            assert kwargs["reconcilable_terminal_statuses"] == frozenset(
                {"needs_continue", "paused_limit"}
            )
            return {
                "terminal": True,
                "isRunning": False,
                "terminalStatus": "needs_continue",
            }
        return {"terminal": True, "isRunning": False, "terminalStatus": "ready"}

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
        scripted_wait,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.collect_required_artifact_refs",
        lambda *_a, **_k: [],
    )
    reconciles: list[dict[str, object]] = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_writeback.reconcile_source_collection_stage_session_task_after_turn",
        lambda *_a, **kwargs: reconciles.append(dict(kwargs)),
    )
    audit_events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event_quietly",
        lambda component, phase, event_code, **kwargs: audit_events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **kwargs,
            }
        ),
    )
    submits: list[dict[str, object]] = []

    def fake_submit(session_id, content, **kwargs):
        submits.append(
            {
                "sessionId": session_id,
                "content": content,
                **kwargs,
            }
        )
        return {"accepted": True, "turnId": "turn-sc-continued", "status": "running"}

    monkeypatch.setattr(
        "core.web.services.session.submit.submit_session_message",
        fake_submit,
    )

    refs = complete_agent_turn_outputs(
        action=PendingAction(
            action_id="act-sc-cont",
            run_id="run-sc-cont",
            node_run_id="nr-sc-cont",
            node_id="source_finding",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="",
        ),
        handle=AgentTaskHandle(
            session_id="session-sc-cont",
            session_attempt=1,
            task_id="task-sc-cont",
            turn_id="turn-sc-park",
        ),
        input_snapshot={
            "teamId": "team-sc-cont",
            "projectId": "project-sc-cont",
            "sourceCollectionRunId": "sc-cont",
        },
    )

    assert refs == []
    assert [turn for turn, _ in wait_calls] == [
        "turn-sc-park",
        "turn-sc-continued",
    ]
    assert len(submits) == 1
    submit = submits[0]
    assert submit["sessionId"] == "session-sc-cont"
    assert submit["content"] == "继续"
    assert submit["message_source"] == "agent_inbox"
    metadata = submit["message_metadata"]
    assert metadata["continuationAttempt"] == 1
    assert metadata["continuationOfTurnId"] == "turn-sc-park"
    assert metadata["continuationPausedStatus"] == "needs_continue"
    assert metadata["workflowRunId"] == "run-sc-cont"
    assert "kind" not in metadata
    assert len(reconciles) == 1
    assert reconciles[0]["turn_id"] == "turn-sc-continued"
    # Every continuation is an auditable protocol step: requested + submitted
    # scene events carry who/attempt/turn chain.
    audit_codes = [event["eventCode"] for event in audit_events]
    assert audit_codes == [
        "agent_turn.continuation_requested",
        "agent_turn.continuation_submitted",
    ]
    submitted_event = next(
        event
        for event in audit_events
        if event["eventCode"] == "agent_turn.continuation_submitted"
    )
    assert submitted_event["component"] == "team_workflow_orchestration"
    assert submitted_event["phase"] == "agent_turn_completion"
    assert submitted_event["fields"]["continuationAttempt"] == 1
    assert submitted_event["fields"]["fromTurnId"] == "turn-sc-park"
    assert submitted_event["fields"]["toTurnId"] == "turn-sc-continued"


def test_source_collection_turn_continuation_exhaustion_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Beyond the bounded budget the node fails with a readable problem code."""
    from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
        MAX_AGENT_TURN_CONTINUATIONS,
    )

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
        lambda _s, turn_id, **_k: {
            "terminal": True,
            "isRunning": False,
            "terminalStatus": "paused_limit",
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.collect_required_artifact_refs",
        lambda *_a, **_k: [],
    )
    submits: list[str] = []

    def fake_submit(_session_id, _content, **_kwargs):
        submits.append(_content)
        next_turn = f"turn-sc-exhausted-{len(submits)}"
        return {"accepted": True, "turnId": next_turn, "status": "running"}

    monkeypatch.setattr(
        "core.web.services.session.submit.submit_session_message",
        fake_submit,
    )

    with pytest.raises(RuntimeError) as excinfo:
        complete_agent_turn_outputs(
            action=PendingAction(
                action_id="act-sc-exh",
                run_id="run-sc-exh",
                node_run_id="nr-sc-exh",
                node_id="source_finding",
                attempt=1,
                actor_kind=ActorKind.AGENT,
                action_kind="start_agent_task",
                input_snapshot_hash="a" * 64,
                input_artifact_refs=(),
                binding_snapshot_id=None,
                budget_policy_hash="",
            ),
            handle=AgentTaskHandle(
                session_id="session-sc-exh",
                session_attempt=1,
                task_id="task-sc-exh",
                turn_id="turn-sc-exhausted-0",
            ),
            input_snapshot={
                "teamId": "team-sc-exh",
                "projectId": "project-sc-exh",
                "sourceCollectionRunId": "sc-exh",
            },
        )

    problem = json.loads(str(excinfo.value))
    assert problem["code"] == "agent_turn_continuation_exhausted"
    assert problem["terminalStatus"] == "paused_limit"
    assert problem["continuationsUsed"] == MAX_AGENT_TURN_CONTINUATIONS
    assert problem["maxContinuations"] == MAX_AGENT_TURN_CONTINUATIONS
    assert problem["turnChain"] == [
        "turn-sc-exhausted-0",
        "turn-sc-exhausted-1",
        "turn-sc-exhausted-2",
        "turn-sc-exhausted-3",
    ]
    assert len(submits) == MAX_AGENT_TURN_CONTINUATIONS


def test_source_collection_turn_continuation_not_accepted_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected continuation submission is a loud failure, not a retry loop."""
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
        lambda _s, _t, **_k: {
            "terminal": True,
            "isRunning": False,
            "terminalStatus": "needs_continue",
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.collect_required_artifact_refs",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "core.web.services.session.submit.submit_session_message",
        lambda *_a, **_k: {"accepted": False, "turnId": "", "status": "rejected"},
    )

    with pytest.raises(RuntimeError) as excinfo:
        complete_agent_turn_outputs(
            action=PendingAction(
                action_id="act-sc-rej",
                run_id="run-sc-rej",
                node_run_id="nr-sc-rej",
                node_id="source_finding",
                attempt=1,
                actor_kind=ActorKind.AGENT,
                action_kind="start_agent_task",
                input_snapshot_hash="a" * 64,
                input_artifact_refs=(),
                binding_snapshot_id=None,
                budget_policy_hash="",
            ),
            handle=AgentTaskHandle(
                session_id="session-sc-rej",
                session_attempt=1,
                task_id="task-sc-rej",
                turn_id="turn-sc-rej",
            ),
            input_snapshot={
                "teamId": "team-sc-rej",
                "projectId": "project-sc-rej",
                "sourceCollectionRunId": "sc-rej",
            },
        )

    problem = json.loads(str(excinfo.value))
    assert problem["code"] == "agent_turn_continuation_not_accepted"
    assert problem["continuationAttempt"] == 1


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

    def wait_for_project_turn(*_args, **kwargs):
        assert kwargs["reconcilable_terminal_statuses"] == frozenset(
            {"needs_continue"}
        )
        return {"terminal": True, "terminalStatus": "needs_continue"}

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
        wait_for_project_turn,
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
