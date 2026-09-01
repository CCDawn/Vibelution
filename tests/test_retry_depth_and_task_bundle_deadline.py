"""Regression coverage: stage-task formal retry depth cap and bundle deadline enforcement.

Two institutionalized run-away loops were fused:
  1. ``start_source_collection_stage_session_task`` auto-opened formal retries
     along the ``retryOfSessionId`` chain with no depth limit (13 attempts
     observed) — now capped, closing the exhausted chain as ``needs_review``.
  2. ``reconcile_task_bundles`` (task-bundle ``deadlineSeconds``) had no
     periodic caller — now driven by the resident worker tick
     (``WorkflowRuntime.run_workers_once``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.web.services import (
    agent_directory_service,
    session_service,
    team_service,
    team_workflow_orchestration_service as s,
)
from core.web.services.team_workflow import meeting_driver_work
from core.web.services.team_workflow.research_runtime import (
    service as research_runtime_service_module,
)
from core.web.services.team_workflow.research_runtime.runtime_factory import (
    build_workflow_runtime,
)
from core.web.services.team_workflow.research_runtime.service import (
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore
from core.web.services.team_workflow.research_runtime.task_bundle_lifecycle import (
    bind_agent_task_bundle,
    create_agent_task_bundle,
)
from core.web.services.team_workflow.source_collection.stage_session import (
    _source_collection_stage_task_formal_retry_depth,
)
from tests._support.team_workflow.helpers import (
    _start_source_collection_run_with_problem_understanding,
    _use_tmp_project_root,
)


@pytest.fixture
def restore_runtime_service_singleton():
    """Keep the research-runtime service singleton test-local."""
    original = research_runtime_service_module._SERVICE
    try:
        yield
    finally:
        research_runtime_service_module._SERVICE = original


def _stage_task_chain(tmp_path, monkeypatch):
    """One isolated team/run plus a helper that seeds chained stage tasks."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="资料寻找",
        role_key="source_finder",
    )
    team = team_service.create_team(
        name="科研团队",
        members=[
            {
                "agentId": agent["agentId"],
                "agentName": "资料寻找",
                "role": "source_finder",
            }
        ],
    )
    project = s.update_research_project(
        team["teamId"],
        s.LEGACY_PROJECT_ID,
        {"name": "重试深度实验"},
    )["project"]
    run = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "retry depth",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": agent["agentId"]},
            "querySeeds": ["retry depth"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )["run"]

    def seed_task(
        task_id: str,
        session_id: str,
        *,
        depth: int,
        status: str,
        retry_source_task_id: str = "",
        retry_of_session_id: str = "",
    ) -> None:
        now = s.utc_now_iso()
        s._upsert_source_collection_stage_session_task(
            team["teamId"],
            run["runId"],
            {
                "schemaVersion": 1,
                "taskKind": "source_collection_stage_session_task",
                "taskId": task_id,
                "idempotencyKey": (
                    f"stage_task:{team['teamId']}:{run['runId']}:finding:"
                    f"{agent['agentId']}:source_finder:task:{task_id}"
                ),
                "teamId": team["teamId"],
                "runId": run["runId"],
                "stageId": "finding",
                "agentId": agent["agentId"],
                "agentRole": "source_finder",
                "sessionId": session_id,
                "researchProjectId": project["projectId"],
                "experimentName": project["name"],
                "sessionTitle": project["name"],
                "sessionAttempt": depth + 1,
                "sessionCreated": False,
                "retryOfSessionId": retry_of_session_id,
                "retrySourceTaskId": retry_source_task_id,
                "formalRetryDepth": depth,
                "status": status,
                "turn": {},
                "createdAt": now,
                "updatedAt": now,
            },
        )

    return team, run, agent, project, seed_task


def test_formal_retry_depth_follows_retry_chain(tmp_path, monkeypatch):
    """Depth is computed along the chain: parent 1 -> child 2, legacy counts too."""
    parent = {"taskId": "stagetask-parent", "formalRetryDepth": 1}
    child = {"taskId": "stagetask-child", "retrySourceTaskId": "stagetask-parent"}
    assert _source_collection_stage_task_formal_retry_depth(child, [parent, child]) == 2

    legacy_root = {"taskId": "stagetask-a", "sessionId": "session-a"}
    legacy_mid = {
        "taskId": "stagetask-b",
        "sessionId": "session-b",
        "retrySourceTaskId": "stagetask-a",
    }
    legacy_leaf = {
        "taskId": "stagetask-c",
        "sessionId": "session-c",
        "retrySourceTaskId": "stagetask-b",
    }
    assert (
        _source_collection_stage_task_formal_retry_depth(
            legacy_leaf, [legacy_root, legacy_mid, legacy_leaf]
        )
        == 2
    )

    session_chain_leaf = {
        "taskId": "stagetask-child",
        "sessionId": "session-child",
        "retryOfSessionId": "session-parent",
    }
    session_chain_parent = {
        "taskId": "stagetask-parent",
        "sessionId": "session-parent",
    }
    assert (
        _source_collection_stage_task_formal_retry_depth(
            session_chain_leaf, [session_chain_parent, session_chain_leaf]
        )
        == 1
    )

    assert _source_collection_stage_task_formal_retry_depth(None, []) == 0
    orphan = {"taskId": "stagetask-orphan", "retrySourceTaskId": "stagetask-missing"}
    assert _source_collection_stage_task_formal_retry_depth(orphan, [orphan]) == 0

    cyclic_a = {"taskId": "stagetask-a", "retrySourceTaskId": "stagetask-b"}
    cyclic_b = {"taskId": "stagetask-b", "retrySourceTaskId": "stagetask-a"}
    assert (
        _source_collection_stage_task_formal_retry_depth(cyclic_a, [cyclic_a, cyclic_b])
        == 2
    )


def test_stage_task_start_rejects_formal_retry_at_depth_cap(tmp_path, monkeypatch):
    """Depth 3 chain: start refuses to open retry 4 and closes the chain as needs_review."""
    team, run, agent, _project, seed_task = _stage_task_chain(tmp_path, monkeypatch)
    seed_task("stagetask-d0", "session-d0", depth=0, status="failed")
    seed_task(
        "stagetask-d1",
        "session-d1",
        depth=1,
        status="failed",
        retry_source_task_id="stagetask-d0",
        retry_of_session_id="session-d0",
    )
    seed_task(
        "stagetask-d2",
        "session-d2",
        depth=2,
        status="failed",
        retry_source_task_id="stagetask-d1",
        retry_of_session_id="session-d1",
    )
    seed_task(
        "stagetask-d3",
        "session-d3",
        depth=3,
        status="failed",
        retry_source_task_id="stagetask-d2",
        retry_of_session_id="session-d2",
    )

    def fail_submit(session_id, _content, **_kwargs):  # pragma: no cover - must not run
        raise AssertionError("submit_session_message must not run past the depth cap")

    monkeypatch.setattr(session_service, "submit_session_message", fail_submit)

    with pytest.raises(s.TeamWorkflowOrchestrationError) as err:
        s.start_source_collection_stage_session_task(
            team["teamId"],
            run["runId"],
            {
                "stageId": "finding",
                "agentId": agent["agentId"],
                "agentRole": "source_finder",
            },
        )
    assert "已达最大重试深度" in str(err.value)

    tasks = {
        item["taskId"]: item
        for item in s._source_collection_stage_session_tasks(team["teamId"], run["runId"])
    }
    rejected = tasks["stagetask-d3"]
    assert rejected["status"] == "needs_review"
    assert rejected["formalRetryDepthExhausted"] is True
    assert rejected["formalRetryDepth"] == 3
    assert "stagetask-d4" not in tasks


def test_stage_task_start_increments_formal_retry_depth(tmp_path, monkeypatch):
    """A retry opened below the cap records parent depth + 1 on the new task."""
    team, run, agent, _project, _seed_task = _stage_task_chain(tmp_path, monkeypatch)

    def fake_submit(session_id, _content, **_kwargs):
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-depth",
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit)
    start_payload = {
        "stageId": "finding",
        "agentId": agent["agentId"],
        "agentRole": "source_finder",
    }
    first = s.start_source_collection_stage_session_task(
        team["teamId"], run["runId"], dict(start_payload)
    )
    assert first["alreadyPresent"] is False
    first_task_id = first["taskId"]

    # Simulate the inherited chain: the current task carries depth 2 from its
    # ancestors (legacy records without the field resolve to 0 the same way).
    tasks = s._source_collection_stage_session_tasks(team["teamId"], run["runId"])
    inherited = dict(tasks[0])
    inherited["status"] = "failed"
    inherited["formalRetryDepth"] = 2
    s._upsert_source_collection_stage_session_task(
        team["teamId"], run["runId"], inherited
    )

    retry = s.start_source_collection_stage_session_task(
        team["teamId"], run["runId"], dict(start_payload)
    )
    assert retry["alreadyPresent"] is False
    assert retry["taskId"] != first_task_id

    tasks_by_id = {
        item["taskId"]: item
        for item in s._source_collection_stage_session_tasks(team["teamId"], run["runId"])
    }
    retry_task = tasks_by_id[retry["taskId"]]
    assert retry_task["formalRetryDepth"] == 3
    assert retry_task["formalRetry"] is True
    assert retry_task["retrySourceTaskId"] == first_task_id
    assert retry_task["retryOfSessionId"] == first["sessionId"]


# --------------------------------------------------------------- bundle deadline

_BUNDLE_NODE_SPEC_KWARGS = {
    "nodeId": "hypothesis_design",
    "label": "假说设计",
    "primaryRoleKey": "hypothesis_designer",
    "producesArtifactKinds": ("hypothesis_fragment",),
}


def _bundle_record() -> dict:
    return {
        "runId": "run-1",
        "workflowId": "challenge_cup",
        "workflowVersionId": "v1",
        "threadId": "thread-1",
        "inputSnapshot": {
            "budgetPolicy": {"maxParallelTasks": 4},
            "researchObjectiveContract": {
                "question": "验证三个假说",
                "hypothesisFirst": True,
            },
            "workflowSessionScopeV3": {"hypothesis_design": "on"},
        },
        "taskBundles": [],
        "modelRoutingDecisions": [],
        "commandReceipts": [],
        "nodeRuns": [
            {
                "nodeRunId": "node-run-1",
                "nodeId": "hypothesis_design",
                "attempt": 1,
                "status": "running",
            }
        ],
        "events": [],
        "status": "running",
    }


def _bundle_node_run() -> dict:
    return {
        "nodeRunId": "node-run-1",
        "nodeId": "hypothesis_design",
        "inputSnapshotHash": "a" * 64,
        "artifactRefs": ["artifact-question"],
    }


def _bundle_node_spec():
    from core.research.workflow.models import ActorKind, WorkflowNodeSpec, WorkflowStageId

    return WorkflowNodeSpec(
        stageId=WorkflowStageId.EXPERIMENT_DESIGN,
        actorKind=ActorKind.AGENT,
        **_BUNDLE_NODE_SPEC_KWARGS,
    )


def _expired_bundle_in_store(run_store: WorkflowRunStore) -> dict:
    run_store.create_run(_bundle_record())
    bundle = create_agent_task_bundle(
        run_store,
        record=_bundle_record(),
        node_run=_bundle_node_run(),
        node_spec=_bundle_node_spec(),
        model_route={"decisionId": "route-1", "nodeRunId": "node-run-1", "modelRef": "model-1"},
        budget_reservation_ref="budget-1",
        idempotency_key="dispatch-1",
        deadline_seconds=3600,
        subtask_specs=[
            {
                "selectionId": "selection-1",
                "candidateId": "H1",
                "scope": {
                    "kind": "workflow_candidate",
                    "selectionId": "selection-1",
                    "candidateId": "H1",
                },
            },
            {
                "selectionId": "selection-1",
                "candidateId": "H2",
                "scope": {
                    "kind": "workflow_candidate",
                    "selectionId": "selection-1",
                    "candidateId": "H2",
                },
            },
        ],
        max_concurrency=2,
    )
    bind_agent_task_bundle(
        run_store,
        run_id="run-1",
        bundle_id=bundle["bundleId"],
        subtask_id="node-run-1:selection-1:H1",
        task_id="task-h1",
        session_id="session-h1",
        turn_id="turn-h1",
    )
    record = run_store.get_run("run-1")
    expired_at = (
        datetime.now(timezone.utc) - timedelta(minutes=2)
    ).isoformat().replace("+00:00", "Z")
    for subtask in record["taskBundles"][0]["subtasks"]:
        subtask["deadlineAt"] = expired_at
    run_store.update_run("run-1", {"taskBundles": record["taskBundles"]})
    return bundle


def test_worker_tick_reconciles_expired_task_bundles(
    tmp_path, monkeypatch, restore_runtime_service_singleton
):
    """run_workers_once (the resident tick) turns an expired bundle terminal."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    run_store = WorkflowRunStore(tmp_path / "run-store")
    reset_research_workflow_runtime_service_for_tests(
        run_store=run_store,
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "ledger-checkpoints.sqlite",
    )
    stopped: list[tuple[str, str]] = []

    def stop(session_id: str, *, expected_turn_id: str) -> dict:
        stopped.append((session_id, expected_turn_id))
        return {"sessionId": session_id, "turnId": expected_turn_id, "status": "stopped"}

    monkeypatch.setattr(
        "core.web.services.session_service.request_stop_session_turn", stop
    )
    try:
        _expired_bundle_in_store(run_store)
        runtime.run_workers_once(limit=4)
    finally:
        runtime.close()

    record = run_store.get_run("run-1")
    bundle = record["taskBundles"][0]
    assert [item["status"] for item in bundle["subtasks"]] == ["cancelled", "cancelled"]
    assert bundle["status"] == "cancelled"
    assert stopped == [("session-h1", "turn-h1")]
    expire_receipts = [
        item
        for item in record.get("commandReceipts") or []
        if item.get("command") == "cancel_task_bundle"
        and str(item.get("idempotencyKey") or "").startswith("expire:")
    ]
    assert expire_receipts


def test_maintenance_tick_hosts_stuck_digest_watchdog(
    tmp_path, monkeypatch, restore_runtime_service_singleton
):
    """run_maintenance_once is the in-process digest watchdog host.

    The 2026-09 ghost-lock incident left stuck ``run_digest`` work recoverable
    only by a restart.  The serial maintenance tick must peek the meeting
    driver watchdog (same host pattern as the task-bundle reconcile) so a
    wedged digest is fenced and given a retry entry without a restart; the
    sweep itself is owned and covered by the meeting-driver recovery tests.
    """
    _use_tmp_project_root(tmp_path, monkeypatch)
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "ledger-checkpoints.sqlite",
    )
    calls: list[dict] = []

    def _sweep(*args, **kwargs):
        calls.append(kwargs)
        return {"teams": 0, "scanned": 0, "fenced": 0, "summaryErrors": 0, "skipped": 0}

    monkeypatch.setattr(meeting_driver_work, "sweep_stuck_digest_works", _sweep)
    try:
        handled = runtime.run_maintenance_once(limit=2)
    finally:
        runtime.close()
    assert calls == [{}]
    assert handled >= 0
