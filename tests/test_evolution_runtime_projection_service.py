from core.web.services.evolution_runtime_projection_service import (
    build_runtime_projection,
    build_workspace_runtime_projection,
)


def test_build_runtime_projection_preserves_supervised_workflow_and_actions():
    snapshot = {
        "runId": "swte-supervised-1",
        "status": "running",
        "phase": "candidate_modify",
        "latestMessage": "candidate is editing",
        "workflowSteps": [
            {
                "id": "baseline_eval",
                "label": "基线评测",
                "status": "done",
                "current": False,
                "summary": "baseline passed 1/2",
                "livePreview": "baseline done",
                "conversationSessionId": "session-baseline",
                "chatRoute": "/chat?session=session-baseline",
                "metrics": {"score": 50},
            },
            {
                "id": "improve",
                "label": "提出建议与改良",
                "status": "running",
                "current": True,
                "summary": "editing candidate",
                "livePreview": "candidate is editing",
                "conversationSessionId": "session-candidate",
                "chatRoute": "/chat?session=session-candidate",
                "metrics": {"changedFileCount": 2},
            },
        ],
        "actionStates": {
            "terminate": {"enabled": True, "reason": ""},
            "merge": {"enabled": False, "reason": "still running"},
        },
        "decision": {"baselineScore": 50, "candidateScore": 0, "scoreDelta": -50},
        "candidateWorktree": {"changedFiles": [{"path": "agent.py"}]},
    }

    projection = build_runtime_projection(snapshot, kind="supervised")

    assert projection["runId"] == "swte-supervised-1"
    assert projection["kind"] == "supervised"
    assert projection["currentStepId"] == "improve"
    assert projection["primaryConversationSessionId"] == "session-candidate"
    assert projection["workflowSteps"][1]["id"] == "improve"
    assert projection["governanceActions"][0]["id"] == "terminate"
    assert projection["governanceActions"][0]["enabled"] is True
    assert {item["summary"] for item in projection["trajectoryPreview"]} >= {
        "baseline done",
        "candidate is editing",
    }
    assert projection["approvalEvidence"]["changedFiles"] == [{"path": "agent.py"}]


def test_build_workspace_runtime_projection_indexes_self_worktree_and_observation():
    self_worktree = {
        "runId": "swte-self-1",
        "status": "done",
        "phase": "complete",
        "workflowSteps": [
            {
                "id": "self_evolution",
                "label": "自进化",
                "status": "done",
                "current": False,
                "summary": "candidate finished",
                "livePreview": "candidate finished",
                "conversationSessionId": "session-self",
                "chatRoute": "/chat?session=session-self",
                "metrics": {"changedFileCount": 1},
            },
            {
                "id": "approval",
                "label": "审批",
                "status": "pending",
                "current": True,
                "summary": "waiting review",
                "livePreview": "waiting review",
                "conversationSessionId": "",
                "chatRoute": "",
                "metrics": {"changedFileCount": 1},
            },
        ],
        "actionStates": {"merge": {"enabled": True, "reason": ""}},
    }
    observation = {
        "runId": "observe-1",
        "runKind": "self_observation_run",
        "status": "running",
        "phase": "running",
        "goal": "观察规划能力",
        "latestMessage": "正在观察",
        "conversationSessionId": "session-observe",
        "messages": ["第一条观察", "第二条观察"],
        "actionStates": {"terminate": {"enabled": True, "reason": ""}},
    }

    projection = build_workspace_runtime_projection(
        self_worktree_active_run=self_worktree,
        self_observation_active_run=observation,
    )

    assert [item["kind"] for item in projection["activeRuns"]] == ["self_worktree", "self_observation"]
    assert projection["active"]["kind"] == "self_observation"
    assert projection["byKind"]["self_worktree"]["currentStepId"] == "approval"
    assert projection["byKind"]["self_observation"]["workflowSteps"][0]["id"] == "self_observation"
    assert projection["byKind"]["self_observation"]["primaryConversationSessionId"] == "session-observe"
    assert projection["byKind"]["self_observation"]["trajectoryPreview"][-1]["summary"] == "第二条观察"
