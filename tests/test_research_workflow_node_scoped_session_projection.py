from __future__ import annotations

from typing import Any

from core.web.services.team_workflow.research_runtime.node_scoped_session_projection import (
    project_node_scoped_sessions,
)


def _record(*, root_task: str = "root-task", root_turn: str = "root-turn") -> dict[str, Any]:
    latest_node_run = {
        "nodeRunId": "node-run-hypothesis-a2",
        "nodeId": "hypothesis_design",
        "attempt": 2,
        "status": "running",
        "sessionId": "root-session",
        "taskId": root_task,
        "turnId": root_turn,
    }
    return {
        "runId": "run-1",
        "teamId": "team-1",
        "projectId": "project-1",
        "status": "running",
        "nodeRuns": [
            {
                **latest_node_run,
                "nodeRunId": "node-run-hypothesis-a1",
                "attempt": 1,
                "sessionId": "root-session-old",
            },
            latest_node_run,
        ],
        "taskBundles": [
            {
                "bundleId": "bundle-current",
                "parentNodeRunId": latest_node_run["nodeRunId"],
                "subtasks": [
                    {
                        "subtaskId": "subtask-H2",
                        "scope": {
                            "selectionId": "selection-1",
                            "candidateId": "H2",
                        },
                        "attempt": 3,
                        "status": "running",
                        "taskId": "task-H2",
                        "sessionId": "child-H2",
                        "turnId": "turn-H2",
                        "outputArtifactRefs": ["fragment:H2"],
                    },
                    {
                        "subtaskId": "subtask-H1",
                        "scope": {
                            "selectionId": "selection-1",
                            "candidateId": "H1",
                        },
                        "attempt": 1,
                        "status": "succeeded",
                        "taskId": "task-H1",
                        "sessionId": "child-H1",
                        "turnId": "turn-H1",
                        "outputArtifactRefs": ["fragment:H1", "evidence:H1"],
                    },
                ],
            },
            {
                "bundleId": "bundle-old",
                "parentNodeRunId": "node-run-hypothesis-a1",
                "subtasks": [],
            },
        ],
    }


def _child_detail(session_id: str, candidate_id: str) -> dict[str, Any]:
    return {
        "id": session_id,
        "sessionKind": "child",
        "hiddenFromIndex": True,
        "agentId": "agent-1",
        "parentSessionId": "root-session",
        "rootSessionId": "root-session",
        "experimentBinding": {
            "teamId": "team-1",
            "researchProjectId": "project-1",
            "agentId": "agent-1",
            "workflowRunId": "run-1",
            "workflowNodeId": "hypothesis_design",
            "selectionId": "selection-1",
            "candidateId": candidate_id,
            "scope": {
                "version": 3,
                "kind": "workflow_candidate",
                "teamId": "team-1",
                "researchProjectId": "project-1",
                "agentId": "agent-1",
                "workflowRunId": "run-1",
                "workflowNodeId": "hypothesis_design",
                "selectionId": "selection-1",
                "candidateId": candidate_id,
            },
        },
    }


def test_projection_uses_latest_bundle_order_and_canonical_child_lineage(monkeypatch) -> None:
    from core.web.services import session_service

    details = {
        "root-session": {
            "id": "root-session",
            "parentSessionId": "",
            "rootSessionId": "root-session",
        },
        "child-H2": _child_detail("child-H2", "H2"),
        "child-H1": _child_detail("child-H1", "H1"),
    }
    calls: list[str] = []

    def get_detail(session_id: str, **_kwargs: Any) -> dict[str, Any] | None:
        calls.append(session_id)
        return details.get(session_id)

    monkeypatch.setattr(session_service, "get_session_detail", get_detail)

    projected = project_node_scoped_sessions(
        _record(),
        node_id="hypothesis_design",
    )

    root = projected["rootSession"]
    assert root["sessionId"] == "root-session"
    assert root["taskId"] == "root-task"
    assert root["turnId"] == "root-turn"
    assert root["attempt"] == 2
    assert root["rootSessionId"] == "root-session"
    assert root["chatDeepLink"]
    assert "focusTask=root-task" in root["chatDeepLink"]
    assert [item["candidateId"] for item in projected["scopedSessions"]] == [
        "H2",
        "H1",
    ]
    h2, h1 = projected["scopedSessions"]
    assert h2["selectionId"] == "selection-1"
    assert h2["subtaskId"] == "subtask-H2"
    assert h2["taskId"] == "task-H2"
    assert h2["sessionId"] == "child-H2"
    assert h2["turnId"] == "turn-H2"
    assert h2["attempt"] == 3
    assert h2["status"] == "running"
    assert h2["parentSessionId"] == "root-session"
    assert h2["rootSessionId"] == "root-session"
    assert h2["fragmentRefs"] == ["fragment:H2"]
    assert h2["chatDeepLink"]
    assert "focusTurn=turn-H2" in h2["chatDeepLink"]
    assert h1["fragmentRefs"] == ["fragment:H1", "evidence:H1"]
    assert calls == ["root-session", "child-H2", "child-H1"]

    legacy_record = _record()
    legacy_record["nodeRuns"][-1].update(
        {
            "sessionId": "child-H2",
            "taskId": "task-H2",
            "turnId": "turn-H2",
        }
    )
    legacy_root = project_node_scoped_sessions(
        legacy_record,
        node_id="hypothesis_design",
    )["rootSession"]
    assert legacy_root["sessionId"] == "root-session"
    assert legacy_root["taskId"] is None
    assert legacy_root["turnId"] is None
    assert "session=root-session" in legacy_root["chatDeepLink"]
    assert "focusTask" not in legacy_root["chatDeepLink"]
    assert legacy_root["sessionAnchorDegraded"] is False


def test_projection_does_not_fabricate_root_task_or_turn_and_degrades_missing_child(
    monkeypatch,
) -> None:
    from core.web.services import session_service

    def get_detail(session_id: str, **_kwargs: Any) -> dict[str, Any] | None:
        if session_id == "root-session":
            return {"id": session_id, "rootSessionId": session_id}
        return None

    monkeypatch.setattr(session_service, "get_session_detail", get_detail)

    projected = project_node_scoped_sessions(
        _record(root_task="", root_turn=""),
        node_id="hypothesis_design",
    )

    root = projected["rootSession"]
    assert root["sessionId"] == "root-session"
    assert root["taskId"] is None
    assert root["turnId"] is None
    assert "session=root-session" in root["chatDeepLink"]
    assert "focusTurn" not in root["chatDeepLink"]
    assert root["sessionAnchorDegraded"] is False
    h2 = projected["scopedSessions"][0]
    assert h2["parentSessionId"] is None
    assert h2["rootSessionId"] is None
    assert h2["chatDeepLink"] is None
    assert h2["sessionAnchorDegraded"] is True


def test_projection_fail_closes_all_children_when_root_anchor_is_degraded() -> None:
    details = {
        "child-H2": _child_detail("child-H2", "H2"),
        "child-H1": _child_detail("child-H1", "H1"),
    }

    projected = project_node_scoped_sessions(
        _record(),
        node_id="hypothesis_design",
        session_detail_reader=lambda session_id: details.get(session_id),
    )

    root = projected["rootSession"]
    assert root["sessionId"] == "root-session"
    assert root["chatDeepLink"] is None
    assert root["sessionAnchorDegraded"] is True
    assert root["sessionAnchorDegradedReason"] == "session_not_found"
    assert projected["scopedSessions"]
    assert all(item["chatDeepLink"] is None for item in projected["scopedSessions"])
    assert all(
        item["sessionAnchorDegraded"] is True
        and item["sessionAnchorDegradedReason"] == "root_session_degraded"
        for item in projected["scopedSessions"]
    )


def test_projection_requires_hidden_child_kind_and_exact_scope_binding() -> None:
    invalid_details = []
    hidden_false = _child_detail("child-H2", "H2")
    hidden_false["hiddenFromIndex"] = False
    invalid_details.append(hidden_false)
    wrong_kind = _child_detail("child-H2", "H2")
    wrong_kind["sessionKind"] = "main"
    invalid_details.append(wrong_kind)
    wrong_scope = _child_detail("child-H2", "H2")
    wrong_scope["experimentBinding"]["candidateId"] = "H1"
    invalid_details.append(wrong_scope)

    for detail in invalid_details:
        projected = project_node_scoped_sessions(
            _record(),
            node_id="hypothesis_design",
            session_detail_reader=lambda session_id, detail=detail: (
                {"root-session": {"id": "root-session", "rootSessionId": "root-session"}}
                .get(session_id)
                if session_id == "root-session"
                else detail
            ),
        )
        child = projected["scopedSessions"][0]
        assert child["chatDeepLink"] is None
        assert child["sessionAnchorDegraded"] is True
        assert child["sessionAnchorDegradedReason"] == "candidate_scope_mismatch"


def test_runtime_node_detail_exposes_the_scoped_projection(tmp_path, monkeypatch) -> None:
    from core.web.services import session_service
    from core.web.services.team_workflow.research_runtime.service import (
        ResearchWorkflowRuntimeService,
    )
    from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore

    details = {
        "root-session": {
            "id": "root-session",
            "parentSessionId": "",
            "rootSessionId": "root-session",
        },
        "child-H2": _child_detail("child-H2", "H2"),
        "child-H1": _child_detail("child-H1", "H1"),
    }
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda session_id, **_kwargs: details.get(session_id),
    )
    record = {
        **_record(),
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "2.1.0",
        "runVersion": 1,
        "threadId": "thread-1",
        "bindingSnapshots": [
            {
                "nodeId": "hypothesis_design",
                "agentId": "agent-hypothesis",
                "roleKey": "hypothesis_designer",
            }
        ],
    }
    store = WorkflowRunStore(tmp_path / "runs")
    store.create_run(record)
    service = ResearchWorkflowRuntimeService(
        run_store=store,
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    monkeypatch.setattr(service, "get_run", lambda _run_id: record)

    detail = service.get_node_detail("run-1", "hypothesis_design")

    assert detail["rootSession"]["sessionId"] == "root-session"
    assert [item["candidateId"] for item in detail["scopedSessions"]] == [
        "H2",
        "H1",
    ]
