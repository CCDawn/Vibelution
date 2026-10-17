# -*- coding: utf-8 -*-
"""context 工具缺 task_id 防护：不再静默返回空 assignments 的成功响应。

2026-10-17 E2E：source_finding Agent 调 ``source_collection_context_tool`` 时漏传
task_id，工具按 run 级上下文静默返回 ``assignments=[]``、agentId 为空的 "ok" 载荷，
Agent 误判「任务没派发给我」。回归契约：
- 无 task_id 且无法从调用方会话权威解析 → 显式 ``missing_task_id`` 错误；
- 无 task_id 但运行时会话绑定唯一阶段任务 → 兜底解析并照常返回上下文；
- 有 task_id → 行为不变（不触发兜底解析）。
"""

from __future__ import annotations

import json

import pytest

from tools.source_collection_stage_tools import source_collection_context_tool

import core.web.services.agent_directory_service as agent_directory_service
import core.web.services.team_workflow_orchestration_service as workflow_service


def _service_payload(**overrides):
    payload = {
        "schemaVersion": 1,
        "status": "ok",
        "teamId": "team-1",
        "runId": "run-1",
        "stageId": "extraction",
        "taskId": overrides.get("taskId", ""),
        "agentId": "agent-1",
        "assignments": [{"assignmentId": "assign-1"}],
        "records": [],
        "candidates": [],
        "counts": {},
        "recordPage": {},
        "candidatePage": {},
    }
    payload.update(overrides)
    return payload


def test_missing_task_id_fails_closed_without_service_call(monkeypatch):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {})
    monkeypatch.setattr(
        workflow_service,
        "get_source_collection_stage_task_context",
        lambda *args, **kwargs: pytest_fail_on_call(),
    )

    response = json.loads(source_collection_context_tool(team_id="team-1"))

    assert response["status"] == "error"
    assert response["errorType"] == "missing_task_id"
    assert "task_id is required; call with the stage task_id from your assignment message" in response["message"]
    assert "recovery" in response


def pytest_fail_on_call():
    raise AssertionError("service context must not be read without a task anchor")


def test_missing_task_id_resolves_from_runtime_session(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"sessionId": "sess-1", "agentId": "agent-1"},
    )
    monkeypatch.setattr(
        workflow_service,
        "_find_source_collection_stage_session_task_by_session",
        lambda team_id, session_id: (
            {"taskId": "task-9", "runId": "run-9", "sessionId": session_id},
            "run-9",
        ),
    )

    def fake_context(team_id, **kwargs):
        captured.update(kwargs)
        return _service_payload(taskId=kwargs.get("task_id") or "")

    monkeypatch.setattr(
        workflow_service,
        "get_source_collection_stage_task_context",
        fake_context,
    )

    response = json.loads(source_collection_context_tool(team_id="team-1"))

    assert captured["task_id"] == "task-9"
    assert response["status"] == "ok"
    tool_resolution = response.get("toolResolution") or {}
    assert tool_resolution.get("taskIdSource") == "agent_runtime_session"
    assert tool_resolution.get("taskId") == "task-9"


def test_ambiguous_runtime_session_match_keeps_error_path(monkeypatch):
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"sessionId": "sess-shared"},
    )
    monkeypatch.setattr(
        workflow_service,
        "_find_source_collection_stage_session_task_by_session",
        lambda team_id, session_id: (None, ""),
    )
    monkeypatch.setattr(
        workflow_service,
        "get_source_collection_stage_task_context",
        lambda *args, **kwargs: pytest_fail_on_call(),
    )

    response = json.loads(source_collection_context_tool(team_id="team-1"))

    assert response["status"] == "error"
    assert response["errorType"] == "missing_task_id"


def test_with_task_id_keeps_behavior_without_runtime_fallback(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: pytest.fail("runtime identity must not be consulted when task_id is provided"),
    )

    def fake_context(team_id, **kwargs):
        captured.update(kwargs)
        return _service_payload(taskId=kwargs.get("task_id") or "")

    monkeypatch.setattr(
        workflow_service,
        "get_source_collection_stage_task_context",
        fake_context,
    )

    response = json.loads(source_collection_context_tool(team_id="team-1", task_id="task-1"))

    assert captured["task_id"] == "task-1"
    assert response["status"] == "ok"
    assert response["taskId"] == "task-1"
