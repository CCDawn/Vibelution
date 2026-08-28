# -*- coding: utf-8 -*-
"""Writeback 工具空参防护：全默认参数签名不得放行空 arguments 调用。

流式 tool arguments 丢失时调用可能以 ``{}`` 到达执行层；writeback 签名所有
参数都有默认值，executor 的 signature.bind 无法拦截，因此工具自身必须对
空回写目标 fail closed。
"""

from __future__ import annotations

import json

from tools.source_collection_stage_tools import source_collection_stage_writeback_tool


def test_writeback_empty_arguments_fail_closed_without_calling_service():
    response = json.loads(source_collection_stage_writeback_tool())

    assert response["status"] == "error"
    assert response["errorType"] == "missing_writeback_target"
    assert "[工具参数错误]" in response["message"]
    assert "recovery" in response


def test_writeback_blank_strings_fail_closed_like_empty_arguments():
    response = json.loads(source_collection_stage_writeback_tool(team_id="   ", task_id=""))

    assert response["status"] == "error"
    assert response["errorType"] == "missing_writeback_target"


def test_writeback_with_task_id_only_passes_guard_into_resolution(monkeypatch):
    """仅缺 team_id 时仍走原有恢复/服务路径，不受空参防护影响。"""

    captured = {}

    def fake_writeback(team_id, task_id, payload):
        captured["team_id"] = team_id
        captured["task_id"] = task_id
        return {"runId": "run-1", "stageId": "stage-1", "task": {"taskId": task_id}, "writeback": {}}

    import core.web.services.team_workflow_orchestration_service as workflow_service

    monkeypatch.setattr(workflow_service, "writeback_source_collection_stage_session_task", fake_writeback)

    response = json.loads(source_collection_stage_writeback_tool(task_id="task-123"))

    assert captured["task_id"] == "task-123"
    assert response.get("errorType") != "missing_writeback_target"
