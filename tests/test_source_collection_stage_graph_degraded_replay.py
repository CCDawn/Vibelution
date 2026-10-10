#!/usr/bin/env python3
"""存储回放回归：历史坏形状 candidateGraph.nodes 降级而非阻断 status/reconcile。

生产实锤（challenge-sci-091，run dprun-20260902163646648432-554d3206，
task stagetask-20260902171458-83a0b781 / source_relation_mapper）：已存储
result.candidateGraph.nodes 是 dict（形如 {"sources": [...]}）而非 array，
_source_collection_stage_writeback_agent_graph_payload 在
_require_object_array 处抛 evidence_relation_graph_invalid，把
get_research_stage_round_status → stage_reconcile → writeback_materialize
整条存储回放/展示路径打死。本文件锁定降级契约：

1. reconcile 投影（_reconcile_source_collection_stage_session_task_sources）
   对坏图不再抛 TeamWorkflowOrchestrationError：agent_graph 降级为空图，
   记录 source_collection.stage_session_task_agent_graph_invalid
   （level=warning / outcome=degraded，fields 带 runId/taskId/error 摘要），
   候选图物化走既有 failed-summary 路径；
2. closure summary 对同一坏数据照常产出（空图口径 relation_edge_claim_count=0），
   同样记录降级事件；
3. 同批正常 task 的候选图不受坏数据影响，照常物化 completed；
4. live 写回路径的严格守卫不动（由 tests/test_evidence_relation_feedback.py 锁定）。
"""

from __future__ import annotations

import pytest

from core.web.services.team_workflow.source_collection import stage_writeback

BAD_TASK_ID = "stagetask-20260902171458-83a0b781"
TEAM_ID = "team-sci-091"
RUN_ID = "dprun-20260902163646648432-554d3206"


def _capture(monkeypatch):
    s = stage_writeback._service()
    events: list[dict] = []

    def _record(event_code, team_id, *, fields, level="info", outcome="observed", **_kwargs):
        events.append(
            {
                "event": event_code,
                "teamId": team_id,
                "fields": dict(fields),
                "level": level,
                "outcome": outcome,
            }
        )

    monkeypatch.setattr(s, "_record_workflow_event", _record)
    return s, events


def _relation_task(task_id: str, nodes, *, edges=None) -> dict:
    return {
        "taskId": task_id,
        "teamId": TEAM_ID,
        "runId": RUN_ID,
        "workflowRunId": "wf-sci-091",
        "stageId": "relations",
        "agentRole": "source_relation_mapper",
        "agentId": "agent-source-relation-mapper",
        "status": "completed",
        "writeback": {
            "status": "completed",
            "summary": "relation mapping done",
            "result": {
                "candidateGraph": {
                    "nodes": nodes,
                    "edges": list(edges or []),
                }
            },
            # 已物化的 sources 摘要避免 reconcile 走 sources 物化分支
            "materializedSources": {"status": "completed", "sourceLeadCount": 0},
        },
    }


def _bad_graph_task() -> dict:
    return _relation_task(BAD_TASK_ID, {"sources": [{"candidateId": "cand-1"}]})


def _good_graph_task() -> dict:
    return _relation_task(
        "stagetask-good-relations",
        [
            {"candidateId": "cand-1", "title": "第一候选"},
            {"candidateId": "cand-2", "title": "第二候选"},
        ],
        edges=[{"sourceCandidateId": "cand-1", "targetCandidateId": "cand-2", "relation": "supports"}],
    )


def _invalid_events(events: list[dict]) -> list[dict]:
    return [item for item in events if item["event"] == "source_collection.stage_session_task_agent_graph_invalid"]


def test_reconcile_degrades_dict_shaped_candidate_graph_nodes(monkeypatch):
    s, events = _capture(monkeypatch)
    reconciled = s._reconcile_source_collection_stage_session_task_sources(TEAM_ID, RUN_ID, _bad_graph_task())
    # (a) 不再抛 TeamWorkflowOrchestrationError（返回即未抛）
    materialized_graph = reconciled["writeback"]["materializedCandidateGraph"]
    # (b) 降级为空图：物化走既有 failed-summary 路径
    assert materialized_graph["status"] == "failed"
    assert materialized_graph["edgeCount"] == 0
    invalid = _invalid_events(events)
    assert invalid and invalid[0]["level"] == "warning"
    assert invalid[0]["outcome"] == "degraded"
    assert invalid[0]["teamId"] == TEAM_ID
    assert invalid[0]["fields"]["runId"] == RUN_ID
    assert invalid[0]["fields"]["taskId"] == BAD_TASK_ID
    assert "evidence_relation_graph_invalid" in invalid[0]["fields"]["error"]
    assert any(
        item["event"] == "source_collection.stage_session_task_candidate_graph_materialized"
        and item["fields"]["taskId"] == BAD_TASK_ID
        for item in events
    )


def test_closure_summary_degrades_dict_shaped_candidate_graph_nodes(monkeypatch):
    s, events = _capture(monkeypatch)
    task = _bad_graph_task()
    summary = s._source_collection_stage_writeback_closure_summary(
        task,
        dict(task["writeback"]),
        coverage_summary={},
        materialized_sources={"status": "completed"},
        materialized_content_extraction={},
        materialized_source_quality={},
        materialized_candidate_graph={},
        materialized_knowledge_ingestion={},
    )
    # (a) closure summary 照常产出，不再抛错
    assert summary["stageId"] == "relations"
    assert summary["targetLabel"] == "候选关系图"
    # (b) 空图口径：无声称边 → 不误报 relation_edges_not_materialized
    assert "relation_edges_not_materialized" not in summary["artifactStatus"]
    invalid = _invalid_events(events)
    assert invalid and invalid[0]["level"] == "warning"
    assert invalid[0]["fields"]["taskId"] == BAD_TASK_ID
    assert "evidence_relation_graph_invalid" in invalid[0]["fields"]["error"]


def test_materialize_candidate_graph_failed_summary_for_invalid_stored_graph(monkeypatch):
    s, events = _capture(monkeypatch)

    def _forbidden_build(*_args, **_kwargs):
        raise AssertionError("build_candidate_graph must not run for an invalid stored graph")

    monkeypatch.setattr(s, "build_candidate_graph", _forbidden_build)
    summary = s._materialize_source_collection_stage_writeback_candidate_graph(
        TEAM_ID,
        RUN_ID,
        _bad_graph_task(),
        dict(_bad_graph_task()["writeback"]),
    )
    assert summary["status"] == "failed"
    assert summary["failedCandidateGraphCount"] == 1
    assert summary["failedCandidateGraphs"][0]["reason"] == "candidate_graph_build_failed"
    assert "evidence_relation_graph_invalid" in summary["failedCandidateGraphs"][0]["error"]
    assert any(
        item["event"] == "source_collection.stage_session_task_candidate_graph_materialized"
        and item["outcome"] == "failed"
        for item in events
    )


def test_reconcile_keeps_other_tasks_graph_intact(monkeypatch):
    s, events = _capture(monkeypatch)
    monkeypatch.setattr(
        s,
        "build_candidate_graph",
        lambda *_a, **_kw: {
            "candidateGraph": {"candidateId": "cg-good"},
            "graph": {"summary": {"nodeCount": 2, "edgeCount": 1}},
        },
    )
    monkeypatch.setattr(s, "_attach_candidate_graph_stage_writeback_metadata", lambda *_a, **_kw: None)
    reconciled = s._reconcile_source_collection_stage_session_task_sources(TEAM_ID, RUN_ID, _good_graph_task())
    materialized_graph = reconciled["writeback"]["materializedCandidateGraph"]
    assert materialized_graph["status"] == "completed"
    assert materialized_graph["candidateGraphId"] == "cg-good"
    assert materialized_graph["edgeCount"] == 1
    assert materialized_graph["nodeCount"] == 2
    # 正常 task 不产生降级事件
    assert _invalid_events(events) == []


def test_agent_graph_payload_guard_still_rejects_dict_shaped_nodes():
    # _require_object_array 本身不放松：live 写回的严格校验保持原样，
    # 降级只发生在本文件锁定的存储回放/展示包装层。
    s = stage_writeback._service()
    with pytest.raises(s.TeamWorkflowOrchestrationError, match="evidence_relation_graph_invalid.*nodes"):
        s._source_collection_stage_writeback_agent_graph_payload(
            {"candidateGraph": {"nodes": {"sources": [{"candidateId": "cand-1"}]}, "edges": []}}
        )
