# -*- coding: utf-8 -*-
"""系统团队 roster directSessionId 丢失的自愈回归。

2026-10-17 E2E：search Agent 的 roster 条目 directSessionId 历史丢失后，阶段派发
读取 Agent 时没有任何产品内重建路径。回归契约：
- directSessionId 空/失效 → 派发路径在读取点用 ``ensure_agent_direct_session``
  重建绑定并记 workflow event；
- 正常条目 → no-op，行为不变；
- 重建失败 → 记失败 event，派发继续用原 Agent 记录。
"""

from __future__ import annotations

import pytest

import core.web.services.agent_directory_service as agent_directory_service
import core.web.services.session_service as session_service
import core.web.services.team_service as team_service
import core.web.services.team_workflow_orchestration_service as workflow_service
from core.web.services.team_workflow.source_collection.stage_session import (
    _heal_source_collection_stage_agent_direct_session,
    start_source_collection_stage_session_task,
)

_EMPTY_SESSION_AGENT = {
    "agentId": "agent-search",
    "displayName": "资料寻找",
    "roleKey": "source_finder",
    "directSessionId": "",
    "status": "active",
}


def _events_recorder(monkeypatch):
    events: list[tuple[str, dict]] = []

    def record_event(event_code, team_id, fields=None):
        events.append((event_code, dict(fields or {})))

    monkeypatch.setattr(workflow_service, "_record_workflow_event", record_event)
    return events


def test_heal_rebinds_empty_direct_session_and_records_event(monkeypatch):
    events = _events_recorder(monkeypatch)
    ensure_calls: list[dict] = []

    monkeypatch.setattr(
        team_service,
        "_agent_direct_session_available",
        lambda agent, *, session_service=None: bool(str(agent.get("directSessionId") or "").strip()),
    )
    monkeypatch.setattr(
        team_service,
        "_member_direct_session_kind",
        lambda agent: agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
    )

    def fake_ensure(**kwargs):
        ensure_calls.append(kwargs)
        return {"id": "sess-rebound", "agentId": "agent-search"}

    monkeypatch.setattr(session_service, "ensure_agent_direct_session", fake_ensure)
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **kwargs: {**_EMPTY_SESSION_AGENT, "directSessionId": "sess-rebound"},
    )

    healed = _heal_source_collection_stage_agent_direct_session(
        "team-1",
        dict(_EMPTY_SESSION_AGENT),
        run_id="run-1",
        stage_id="finding",
    )

    assert len(ensure_calls) == 1
    assert ensure_calls[0]["agent_id"] == "agent-search"
    assert ensure_calls[0]["conversation_index_kind"] == agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT
    assert healed["directSessionId"] == "sess-rebound"
    assert events == [
        (
            "source_collection.stage_agent_direct_session_rebound",
            {
                "runId": "run-1",
                "stageId": "finding",
                "agentId": "agent-search",
                "agentRole": "source_finder",
                "previousDirectSessionId": "",
                "purpose": "stage_session_task",
                "directSessionId": "sess-rebound",
            },
        )
    ]


def test_heal_is_noop_for_healthy_roster_entry(monkeypatch):
    events = _events_recorder(monkeypatch)
    healthy = {**_EMPTY_SESSION_AGENT, "directSessionId": "sess-healthy"}

    monkeypatch.setattr(
        team_service,
        "_agent_direct_session_available",
        lambda agent, *, session_service=None: True,
    )
    monkeypatch.setattr(
        session_service,
        "ensure_agent_direct_session",
        lambda **kwargs: pytest.fail("healthy binding must not be rebound"),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **kwargs: pytest.fail("healthy binding must not reload the Agent"),
    )

    unchanged = _heal_source_collection_stage_agent_direct_session(
        "team-1", dict(healthy), run_id="run-1", stage_id="finding",
    )

    assert unchanged == healthy
    assert events == []


def test_heal_records_failure_and_returns_original_agent(monkeypatch):
    events = _events_recorder(monkeypatch)

    monkeypatch.setattr(
        team_service,
        "_agent_direct_session_available",
        lambda agent, *, session_service=None: False,
    )
    monkeypatch.setattr(
        team_service,
        "_member_direct_session_kind",
        lambda agent: agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
    )

    def failing_ensure(**kwargs):
        raise RuntimeError("session store unavailable")

    monkeypatch.setattr(session_service, "ensure_agent_direct_session", failing_ensure)

    original = dict(_EMPTY_SESSION_AGENT)
    returned = _heal_source_collection_stage_agent_direct_session(
        "team-1", original, run_id="run-1", stage_id="finding",
    )

    assert returned == original
    assert len(events) == 1
    event_code, fields = events[0]
    assert event_code == "source_collection.stage_agent_direct_session_rebind_failed"
    assert fields["agentId"] == "agent-search"
    assert fields["errorType"] == "RuntimeError"


def test_dispatch_start_heals_roster_agent_before_continuing(monkeypatch):
    """阶段任务派发入口在读取 Agent 处发现失效绑定即重建（E2E 主路径）。"""

    events = _events_recorder(monkeypatch)
    ensure_calls: list[dict] = []

    monkeypatch.setattr(team_service, "get_team", lambda team_id: {"teamId": team_id, "members": []})
    monkeypatch.setattr(
        team_service,
        "_agent_direct_session_available",
        lambda agent, *, session_service=None: bool(str(agent.get("directSessionId") or "").strip()),
    )
    monkeypatch.setattr(
        team_service,
        "_member_direct_session_kind",
        lambda agent: agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
    )
    agent_state = {"record": dict(_EMPTY_SESSION_AGENT)}

    def fake_ensure(**kwargs):
        ensure_calls.append(kwargs)
        agent_state["record"] = {**_EMPTY_SESSION_AGENT, "directSessionId": "sess-rebound"}
        return {"id": "sess-rebound", "agentId": "agent-search"}

    monkeypatch.setattr(session_service, "ensure_agent_direct_session", fake_ensure)
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **kwargs: dict(agent_state["record"]),
    )

    def sentinel_dialogue_model(agent):
        raise SentinelReached("dispatch continued past the heal")

    monkeypatch.setattr(
        agent_directory_service,
        "agent_dialogue_model_id",
        sentinel_dialogue_model,
    )

    monkeypatch.setattr(
        workflow_service,
        "_source_collection_run_context_bundle",
        lambda team_id, run_id: {
            "run": {"runId": run_id, "scope": {"teamId": team_id}, "metadata": {}},
            "assignments": [],
            "records": [{"recordId": "rec-1", "status": "active"}],
            "sourceCandidates": [],
            "runStatus": {},
            "activeWorkRun": {},
        },
    )
    monkeypatch.setattr(
        workflow_service,
        "resolve_research_project_identity_from_record",
        lambda team_id, run: {"projectId": "proj-1", "name": "Proj"},
    )
    monkeypatch.setattr(
        workflow_service,
        "_source_collection_stage_session_tasks",
        lambda team_id, run_id: [],
    )
    monkeypatch.setattr(
        workflow_service,
        "_latest_source_collection_stage_task",
        lambda tasks: {},
    )
    monkeypatch.setattr(
        workflow_service,
        "_source_collection_stage_task_context_mode",
        lambda **kwargs: "standard",
    )
    monkeypatch.setattr(
        workflow_service,
        "_source_collection_storage_artifacts",
        lambda team_id, run_id: {},
    )

    from core.web.services.team_workflow.source_collection import stage_session as stage_session_module

    monkeypatch.setattr(
        stage_session_module,
        "_source_collection_run_graph_metrics",
        lambda team_id, run_id, source_candidates: {
            "nodeCount": 0,
            "edgeCount": 0,
            "missingLinkCount": 0,
        },
    )

    with pytest.raises(SentinelReached):
        start_source_collection_stage_session_task(
            "team-1",
            "run-1",
            {"stageId": "extraction", "agentId": "agent-search", "agentRole": "source_extractor"},
        )

    assert len(ensure_calls) == 1
    assert ensure_calls[0]["agent_id"] == "agent-search"
    assert [event_code for event_code, _ in events] == [
        "source_collection.stage_agent_direct_session_rebound",
    ]


def test_dispatch_start_skips_heal_for_healthy_roster_entry(monkeypatch):
    events = _events_recorder(monkeypatch)

    monkeypatch.setattr(team_service, "get_team", lambda team_id: {"teamId": team_id, "members": []})
    monkeypatch.setattr(
        team_service,
        "_agent_direct_session_available",
        lambda agent, *, session_service=None: True,
    )
    monkeypatch.setattr(
        session_service,
        "ensure_agent_direct_session",
        lambda **kwargs: pytest.fail("healthy binding must not be rebound"),
    )
    healthy = {**_EMPTY_SESSION_AGENT, "directSessionId": "sess-healthy"}
    monkeypatch.setattr(agent_directory_service, "get_agent", lambda agent_id, **kwargs: healthy)

    def sentinel_dialogue_model(agent):
        raise SentinelReached("dispatch continued without heal")

    monkeypatch.setattr(
        agent_directory_service,
        "agent_dialogue_model_id",
        sentinel_dialogue_model,
    )
    monkeypatch.setattr(
        workflow_service,
        "_source_collection_run_context_bundle",
        lambda team_id, run_id: {
            "run": {"runId": run_id, "scope": {"teamId": team_id}, "metadata": {}},
            "assignments": [],
            "records": [{"recordId": "rec-1", "status": "active"}],
            "sourceCandidates": [],
            "runStatus": {},
            "activeWorkRun": {},
        },
    )
    monkeypatch.setattr(
        workflow_service,
        "resolve_research_project_identity_from_record",
        lambda team_id, run: {"projectId": "proj-1", "name": "Proj"},
    )
    monkeypatch.setattr(
        workflow_service,
        "_source_collection_stage_session_tasks",
        lambda team_id, run_id: [],
    )
    monkeypatch.setattr(
        workflow_service,
        "_latest_source_collection_stage_task",
        lambda tasks: {},
    )
    monkeypatch.setattr(
        workflow_service,
        "_source_collection_stage_task_context_mode",
        lambda **kwargs: "standard",
    )
    monkeypatch.setattr(
        workflow_service,
        "_source_collection_storage_artifacts",
        lambda team_id, run_id: {},
    )

    from core.web.services.team_workflow.source_collection import stage_session as stage_session_module

    monkeypatch.setattr(
        stage_session_module,
        "_source_collection_run_graph_metrics",
        lambda team_id, run_id, source_candidates: {
            "nodeCount": 0,
            "edgeCount": 0,
            "missingLinkCount": 0,
        },
    )

    with pytest.raises(SentinelReached):
        start_source_collection_stage_session_task(
            "team-1",
            "run-1",
            {"stageId": "extraction", "agentId": "agent-search", "agentRole": "source_extractor"},
        )

    assert events == []


class SentinelReached(Exception):
    pass
