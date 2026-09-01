# -*- coding: utf-8 -*-
"""Candidate hypothesis child session read gate (P1 T5).

Three faces are covered:

1. Cross-candidate direct reads are denied with a stable error code and a
   bounded scene event (identities only).
2. Same-candidate, coordination (same run), and operator/default reads are
   allowed; coordination with a foreign run fails closed.
3. Normal (non-candidate) session reads are bit-for-bit unchanged whether or
   not a requester is declared: session detail, transcript windowing, and the
   agent-facing history tools.
"""

from __future__ import annotations

import json

import pytest

from core.chat.turn_journal import (
    EVENT_USER_MESSAGE,
    append_turn_event,
)
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    data_processing_service,
    project_agent_bus_service,
    session_service,
    team_knowledge_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.runtime_scene import record as scene_record
from core.web.services.session.candidate_read_gate import (
    CANDIDATE_READ_DENIED_ERROR_CODE,
    SessionReadRequester,
    SiblingHypothesisSessionAccessDenied,
)
from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_project_agent_sessions import (
    resolve_research_project_agent_session,
)
from tools import conversation_history_tools as history_tools


def _use_tmp_project_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    for service in (
        agent_directory_service,
        chat_room_service,
        data_processing_service,
        project_agent_bus_service,
        session_service,
        team_knowledge_service,
        team_service,
        team_workflow_orchestration_service,
    ):
        monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)


def _project_and_agent(tmp_path, monkeypatch, *, agent_name: str = "资料寻找"):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name=agent_name,
        role_key="source_finder",
    )
    legacy_direct_session = session_service.ensure_agent_direct_session(
        agent_id=agent["agentId"],
        title=f"{agent_name}直连会话",
    )
    team = team_service.create_team(
        name="科研团队",
        members=[
            {
                "agentId": agent["agentId"],
                "agentName": agent_name,
                "role": "source_finder",
            }
        ],
    )
    project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": "层级反馈实验"},
    )["project"]
    team_workflow_orchestration_service.activate_research_project(
        team["teamId"],
        project["projectId"],
    )
    return team, project, agent, legacy_direct_session


def _candidate_children(tmp_path, monkeypatch):
    team, project, agent, _legacy_direct = _project_and_agent(tmp_path, monkeypatch)
    common = {
        "team_id": team["teamId"],
        "research_project_id": project["projectId"],
        "agent_id": agent["agentId"],
        "role_key": "source_finder",
        "role_label": "假设设计",
        "workflow_run_id": "run-gate-1",
        "workflow_node_id": "hypothesis_design",
        "selection_id": "selection-1",
    }
    h1 = resolve_research_project_agent_session(
        **common, candidate_id="H1", created_from_task_id="h1-task"
    )
    h2 = resolve_research_project_agent_session(
        **common, candidate_id="H2", created_from_task_id="h2-task"
    )
    assert h1["sessionId"] != h2["sessionId"]
    assert h1["sessionKind"] == "child" and h1["hiddenFromIndex"] is True
    return team, project, agent, common, h1, h2


def _h1_agent_requester(agent, h1) -> SessionReadRequester:
    return SessionReadRequester(
        channel="agent",
        agent_id=agent["agentId"],
        session_id=h1["sessionId"],
        selection_id="selection-1",
        candidate_id="H1",
        workflow_run_id="run-gate-1",
    )


def test_cross_candidate_detail_read_is_denied_with_bounded_scene_event(
    tmp_path, monkeypatch
):
    _team, _project, agent, _common, h1, h2 = _candidate_children(
        tmp_path, monkeypatch
    )
    recorded: list[dict] = []

    def _capture(component, phase, event_code, **kwargs):
        recorded.append({"component": component, "phase": phase, "code": event_code, **kwargs})
        return {"accepted": True}

    monkeypatch.setattr(
        scene_record, "record_runtime_scene_event_quietly", _capture
    )

    requester = _h1_agent_requester(agent, h1)
    with pytest.raises(SiblingHypothesisSessionAccessDenied) as exc_info:
        session_service.get_session_detail(h2["sessionId"], requester=requester)

    assert exc_info.value.code == CANDIDATE_READ_DENIED_ERROR_CODE
    assert exc_info.value.code == "sibling_hypothesis_session_access_denied"
    assert exc_info.value.target_session_id == h2["sessionId"]
    assert exc_info.value.target_candidate_id == "H2"
    assert exc_info.value.requester_candidate_id == "H1"

    assert len(recorded) == 1
    event = recorded[0]
    assert event["code"] == "sibling_hypothesis_session_access_denied"
    assert event["outcome"] == "blocked"
    fields = event["fields"]
    assert fields["targetSessionId"] == h2["sessionId"]
    assert fields["targetSelectionId"] == "selection-1"
    assert fields["targetCandidateId"] == "H2"
    assert fields["requesterSessionId"] == h1["sessionId"]
    assert fields["requesterCandidateId"] == "H1"
    assert fields["reason"] == "candidate_scope_mismatch"
    # Bounded identities only: no transcript content is recorded.
    assert "content" not in fields and "messages" not in fields


def test_same_candidate_coordination_and_operator_reads_are_allowed(
    tmp_path, monkeypatch
):
    _team, _project, agent, _common, h1, h2 = _candidate_children(
        tmp_path, monkeypatch
    )

    # Same candidate scope (e.g. the H1 agent re-reading its own candidate
    # session after a resolver recovery) is allowed.
    same_candidate = session_service.get_session_detail(
        h1["sessionId"], requester=_h1_agent_requester(agent, h1)
    )
    assert same_candidate is not None
    assert same_candidate["id"] == h1["sessionId"]
    assert same_candidate["sessionKind"] == "child"

    # Own-session reads never need a candidate scope.
    own_session = session_service.get_session_detail(
        h1["sessionId"],
        requester=SessionReadRequester(
            channel="agent",
            agent_id=agent["agentId"],
            session_id=h1["sessionId"],
        ),
    )
    assert own_session is not None
    assert own_session["id"] == h1["sessionId"]

    # Research coordination of the same run is whitelisted (fan-out lineage
    # checks; fan-in aggregation reads fragments, not transcripts).
    coordination = session_service.get_session_detail(
        h2["sessionId"],
        requester=SessionReadRequester(
            channel="coordination",
            workflow_run_id="run-gate-1",
        ),
    )
    assert coordination is not None
    assert coordination["id"] == h2["sessionId"]

    # Operator channel default (no declared requester, e.g. web workbench)
    # keeps legacy behavior.
    operator = session_service.get_session_detail(h2["sessionId"])
    assert operator is not None
    assert operator["experimentBinding"]["candidateId"] == "H2"

    # Coordination of a foreign run fails closed.
    with pytest.raises(SiblingHypothesisSessionAccessDenied):
        session_service.get_session_detail(
            h2["sessionId"],
            requester=SessionReadRequester(
                channel="coordination",
                workflow_run_id="run-other",
            ),
        )


def test_history_tool_sibling_candidate_read_denied_and_own_candidate_allowed(
    tmp_path, monkeypatch
):
    _team, _project, agent, _common, h1, h2 = _candidate_children(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(history_tools, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": agent["agentId"],
            "sessionId": h1["sessionId"],
        },
    )

    # Candidate H1's agent directly addressing sibling H2's transcript is
    # denied with the stable machine code.
    denied = history_tools.history_timeline_tool(session_id=h2["sessionId"])
    payload = json.loads(denied)
    assert payload["error"] == "sibling_hypothesis_session_access_denied"

    denied_search = history_tools.history_search_tool(
        query="假说", session_id=h2["sessionId"]
    )
    assert (
        json.loads(denied_search)["error"]
        == "sibling_hypothesis_session_access_denied"
    )

    # Reading its own candidate session keeps working.
    allowed = history_tools.history_timeline_tool(session_id=h1["sessionId"])
    assert CANDIDATE_READ_DENIED_ERROR_CODE not in allowed


def _seed_user_messages(project_root, session_id: str, contents: list[str]) -> None:
    for index, content in enumerate(contents, start=1):
        append_turn_event(
            project_root,
            session_id,
            f"turn-{index}",
            EVENT_USER_MESSAGE,
            status="completed",
            payload={"content": content},
            source="test.candidate_read_gate",
            timestamp=f"2026-08-31T01:02:0{index}Z",
        )


def test_normal_session_detail_and_transcript_reads_are_unchanged_by_gate(
    tmp_path, monkeypatch
):
    _team, _project, agent, normal_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    normal_id = normal_session["id"]
    _seed_user_messages(tmp_path, normal_id, ["第一条", "第二条", "第三条"])

    # Warm one read so repair/persist side effects settle before comparing.
    session_service.get_session_detail(normal_id, include_secondary=False)

    baseline = session_service.get_session_detail(normal_id, include_secondary=False)
    assert baseline is not None
    assert [message.get("content") for message in baseline["messages"]] == [
        "第一条",
        "第二条",
        "第三条",
    ]

    requesters = [
        _h1_agent_requester(agent, {"sessionId": "child-not-own"}),
        SessionReadRequester(channel="agent", agent_id=agent["agentId"]),
        SessionReadRequester(channel="coordination", workflow_run_id="run-x"),
        SessionReadRequester(channel="operator"),
        {
            "channel": "agent",
            "agentId": agent["agentId"],
            "sessionId": normal_id,
        },
    ]
    for requester in requesters:
        variant = session_service.get_session_detail(
            normal_id, include_secondary=False, requester=requester
        )
        assert variant == baseline

    # Transcript windowing is identical with and without a requester.
    window_baseline = session_service.get_session_detail(
        normal_id,
        message_limit=2,
        before_message_index=0,
        include_secondary=False,
    )
    window_variant = session_service.get_session_detail(
        normal_id,
        message_limit=2,
        before_message_index=0,
        include_secondary=False,
        requester=_h1_agent_requester(agent, {"sessionId": "child-not-own"}),
    )
    assert window_variant == window_baseline
    assert window_baseline is not None


def test_history_tool_normal_session_reads_are_unchanged_by_gate(
    tmp_path, monkeypatch
):
    _team, _project, agent, normal_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    normal_id = normal_session["id"]
    _seed_user_messages(tmp_path, normal_id, ["普通一", "普通二"])

    other_agent = agent_directory_service.create_agent_instance(
        display_name="其他助手",
        role_key="source_finder",
    )
    other_direct = session_service.ensure_agent_direct_session(
        agent_id=other_agent["agentId"],
        title="其他助手直连会话",
    )

    monkeypatch.setattr(history_tools, "PROJECT_ROOT", tmp_path)

    unbound = history_tools.history_timeline_tool(session_id=normal_id, limit=50)

    # A plain agent bound to a DIFFERENT normal session can still read another
    # normal session's history: the gate never changes normal reads.
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": other_agent["agentId"],
            "sessionId": other_direct["id"],
        },
    )
    bound = history_tools.history_timeline_tool(session_id=normal_id, limit=50)
    assert bound == unbound
    assert CANDIDATE_READ_DENIED_ERROR_CODE not in bound
    assert "普通一" in bound

    # Own-session history reads also stay identical.
    own = history_tools.history_timeline_tool(
        session_id=other_direct["id"], limit=50
    )
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {})
    own_unbound = history_tools.history_timeline_tool(
        session_id=other_direct["id"], limit=50
    )
    assert own == own_unbound
