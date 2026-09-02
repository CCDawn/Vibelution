"""HF-4 hypothesis-first orchestration chain integration tests.

End-to-end DEV fixture chain: hypothesis selection -> first review meeting
auto-opens (background wiring, room round <-> meetingRoundId two-way binding)
-> closure carrying a ``request_new_evidence`` decision with a searchEnvelope
-> stage-1 collection ``ensure`` through the existing facade (call evidence)
-> child collection handoff -> parent run ``hypothesis_design`` readiness
re-check and resume -> next review meeting auto-opens with continuous lineage.

Also covers: missing searchEnvelope never triggers collection and keeps
``source_finding`` blocked; an unconverged latest round blocks
``hypothesis_design``; the round budget forces a manual decision; interruption
recovery keeps rounds and stays idempotent.

All discussion content comes from fake runners and the collection run creation
is faked at ``source_collection.runs.start_source_collection_run``; no real
model, network, or research activity is involved.
"""

from __future__ import annotations

import json

from core.infrastructure import developer_sandbox
from concurrent.futures import Future, ThreadPoolExecutor
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from core.research.workflow.contracts import (
    ActorRef,
    CommandRequest,
    WorkflowCommandKind,
    scope_hash_for,
)
from core.research.workflow.contracts.discussion_scope import parse_discussion_scope
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    session_service,
    team_service,
)
from core.web.services.team_workflow import hypothesis_rounds as hrounds
from core.web.services.team_workflow import hypothesis_selection as selections
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow import personal_memory_candidates as memories
from core.web.services.team_workflow import research_templates as templates
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import question_launch
from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
    reset_formal_write_runtime_for_tests,
)
from core.web.services.team_workflow.research_runtime.command_service import (
    NodeNotReadyError,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)
from core.web.services.team_workflow.research_runtime.runtime_factory import (
    build_workflow_runtime,
)
from core.web.services.team_workflow.source_collection import facade
from core.web.services.team_workflow.source_collection import (
    runs as collection_runs,
)

from tests._support.team_workflow.helpers import (
    _seed_claim_belief_gate_fixture,
    _use_fake_local_research_config,
    _use_tmp_project_root,
)
from tests._support.workflow_ledger_helpers import (
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
)

_ROLES = ("coordinator", "researcher")
_QUESTION_ID = "SCI-096"
_CANDIDATE_IDS = ("hyp-a", "hyp-b", "hyp-c")
_RUN_ID = "run-hf4-parent"
_FIXED_NOW_MS = 1_750_000_000_000


class _InlineExecutor:
    """Run submitted chat-room rounds synchronously (DEV tests only)."""

    def __init__(self) -> None:
        self.submitted: list[dict] = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append({"fn": fn, "args": args, "kwargs": kwargs})
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - surfaced via future
            future.set_exception(exc)
        return future


class _DeferredExecutor:
    """Keep background room rounds running until the test releases them."""

    def __init__(self) -> None:
        self.submitted: list[dict] = []

    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        self.submitted.append(
            {"fn": fn, "args": args, "kwargs": kwargs, "future": future}
        )
        return future

    def drain(self) -> None:
        for submitted in self.submitted:
            future = submitted["future"]
            if future.done():
                continue
            future.set_result(submitted["fn"](*submitted["args"], **submitted["kwargs"]))


def test_generation_attempt_finishes_when_bound_meeting_is_fenced(monkeypatch):
    attempt = {
        "recordKind": "generation_attempt",
        "attemptId": "attempt-terminal-bridge",
        "attemptNumber": 2,
        "questionId": "SCI-002",
        "meetingRoundId": "meeting-terminal-bridge",
        "lifecycle": "running",
        "supersedesAttemptId": "attempt-1",
    }
    appended = []
    monkeypatch.setattr(chain, "_storage_path", lambda _team_id: Path("unused"))
    monkeypatch.setattr(chain, "_read_jsonl", lambda _path: [dict(attempt)])
    monkeypatch.setattr(
        chain,
        "_append_generation_attempt_state",
        lambda team_id, **kwargs: appended.append((team_id, kwargs)) or kwargs,
    )

    result = chain.fail_generation_attempt_for_meeting(
        "research-team",
        "meeting-terminal-bridge",
        reason="challenge_workflow_run_blocked",
    )

    assert result["lifecycle"] == "failed"
    assert result["error"] == "challenge_workflow_run_blocked"
    assert appended[0][1]["supersedes_attempt_id"] == "attempt-1"


def _hf_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    reset_formal_write_runtime_for_tests()
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memories, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(selections, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(templates, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    # The R2.2 claim belief gate reads the claim ledger inside chain_state;
    # pin its store root to the tmp workspace like every other store.
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service

    monkeypatch.setattr(claim_ledger_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", _InlineExecutor())
    agents: dict[str, str] = {}
    team_roles = (
        *_ROLES,
        "source_finder",
        "source_relation_mapper",
        "experiment_planner",
        "experiment_ledger",
    )
    for role in team_roles:
        agent = agent_directory_service.create_agent_instance(
            display_name=f"HF4 {role}",
            role_key=role,
            created_by="hf4-test",
        )
        session_service.ensure_agent_direct_session(
            agent_id=agent["agentId"], title=f"HF4 {role}"
        )
        agents[role] = agent["agentId"]
    team_id = team_service.create_team(
        name="HF-4 假说先行团队",
        purpose="challenge-workflow-hf4",
        members=[{"agentId": agents[role], "role": role} for role in team_roles],
    )["teamId"]
    return team_id, agents


def test_hypothesis_participants_resolve_four_roles_in_contract_order(monkeypatch):
    room = {
        "participants": [
            {"agentId": "agent-evaluator", "teamRole": "experiment_ledger"},
            {"agentId": "agent-search", "teamRole": "source_finder"},
            {
                "agentId": "agent-revision",
                "teamRole": "challenge_cup_experiment_planner",
            },
            {
                "agentId": "agent-knowledge",
                "teamRole": "source_relation_mapper",
            },
            {"agentId": "agent-coordinator", "teamRole": "research_coordination"},
        ]
    }
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        lambda room_id: room if room_id == "room-1" else None,
    )
    monkeypatch.setattr(team_service, "get_team", lambda team_id: {"members": []})

    resolved = chain._resolve_hypothesis_participants(
        "team-1", "room-1", chain.CANDIDATE_GENERATION_MEETING_TYPE
    )

    assert resolved["participantRoleIds"] == [
        "challenge_cup_search",
        "challenge_cup_knowledge_manager",
        "challenge_cup_experiment_revision",
        "challenge_cup_evaluator",
    ]
    assert resolved["participants"] == [
        "agent-search",
        "agent-knowledge",
        "agent-revision",
        "agent-evaluator",
    ]
    assert [item["roleId"] for item in resolved["participantRoleSnapshot"]] == resolved[
        "participantRoleIds"
    ]
    assert resolved["teamRoleContractVersion"] == 2
    assert resolved["participantPolicyVersion"] == 2
    assert len(resolved["resolutionHash"]) == 64


@pytest.mark.parametrize(
    "participants, expected",
    [
        (
            [
                {"agentId": "agent-search", "teamRole": "source_finder"},
                {"agentId": "agent-knowledge", "teamRole": "source_relation_mapper"},
                {"agentId": "agent-revision", "teamRole": "experiment_planner"},
            ],
            "missing required participant role",
        ),
        (
            [
                {"agentId": "agent-search-1", "teamRole": "source_finder"},
                {"agentId": "agent-search-2", "teamRole": "source_finder"},
                {"agentId": "agent-knowledge", "teamRole": "source_relation_mapper"},
                {"agentId": "agent-revision", "teamRole": "experiment_planner"},
                {"agentId": "agent-evaluator", "teamRole": "experiment_ledger"},
            ],
            "multiple agents are bound",
        ),
        (
            [
                {
                    "agentId": "agent-ambiguous",
                    "teamRole": "source_finder",
                    "teamRoleKey": "experiment_ledger",
                },
                {"agentId": "agent-knowledge", "teamRole": "source_relation_mapper"},
                {"agentId": "agent-revision", "teamRole": "experiment_planner"},
                {"agentId": "agent-evaluator", "teamRole": "experiment_ledger"},
            ],
            "ambiguous",
        ),
    ],
)
def test_hypothesis_participant_resolution_fails_closed(monkeypatch, participants, expected):
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        lambda room_id: {"participants": participants},
    )
    monkeypatch.setattr(team_service, "get_team", lambda team_id: {"members": []})

    with pytest.raises(chain.ContractValidationError, match=expected):
        chain._resolve_hypothesis_participants(
            "team-1", "room-1", chain.HYPOTHESIS_REVIEW_MEETING_TYPE
        )


def _patch_approved_question(
    monkeypatch: pytest.MonkeyPatch, *, hypotheses: list[dict] | None = None
) -> None:
    detail = {
        "teamId": "hf4",
        "questionId": _QUESTION_ID,
        "selectedRunId": "stage1-sci-096-v1",
        "record": {
            "questionId": _QUESTION_ID,
            "runId": "stage1-sci-096-v1",
            "schemaVersion": 2,
            "submissionEligible": True,
            "status": "approved",
            "humanGates": {
                "allApproved": True,
                "decisions": {
                    "H1_problem_understanding": "approved",
                    "H2_hypothesis_selection": "approved",
                    "H3_research_plan": "approved",
                    "H4_external_output": "approved",
                },
            },
            "validation": {
                "schemaValidation": "passed",
                "citationValidation": "passed",
                "officialModelCall": True,
            },
        },
        "output": {
            "schema_version": 2,
            "identity": {
                "catalog_id": "science-125-questions-2021",
                "question_id": _QUESTION_ID,
                "question_en": "Fixture question",
            },
            "hypotheses": hypotheses
            if hypotheses is not None
            else [
                {"hypothesis_id": candidate_id, "statement": f"candidate {candidate_id}"}
                for candidate_id in _CANDIDATE_IDS
            ],
            "selection": {"selected_hypothesis_id": _CANDIDATE_IDS[0]},
            "review": {"human_review_status": "passed"},
            "submission": {"eligible": True},
        },
        "artifact": {"sha256": "b" * 64, "immutable": True},
    }
    monkeypatch.setattr(
        question_launch,
        "_approved_details",
        lambda _team_id: {_QUESTION_ID.upper(): detail},
    )


def _scope_fields(agent_id: str) -> dict[str, str]:
    return {
        "program": "XH-202619",
        "theme": "cc-neuro-001",
        "campaign": "cc-campaign-neuro-001",
        "question": _QUESTION_ID,
        "branch": "main",
        "workflow": "hypothesis_first",
        "agentId": agent_id,
        "mode": "dev",
    }


def _selection_payload(agent_id: str, **overrides):
    payload = {
        **_scope_fields(agent_id),
        "questionId": _QUESTION_ID,
        "selectedCandidateIds": ["hyp-a", "hyp-b"],
        "decidedBy": agent_id,
    }
    payload.update(overrides)
    return payload


def test_formal_selection_fans_out_one_scoped_meeting_per_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_runtime
    from core.web.services.team_workflow.research_runtime import (
        meeting_receipt_authority,
    )
    from core.web.services.team_workflow import research_project_agent_sessions

    team_id = "team-formal-fanout"
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        meeting_receipt_authority,
        "resolve_active_question_authority",
        lambda *_args: {
            "workflowRunId": "run-formal-1",
            "teamId": team_id,
            "questionId": _QUESTION_ID,
        },
    )
    monkeypatch.setattr(
        research_project_agent_sessions,
        "resolve_research_project_identity",
        lambda *_args: {"projectId": "project-formal-1"},
    )
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            meetings.ResearchMeetingRoundNotFoundError("missing")
        ),
    )
    monkeypatch.setattr(
        meeting_runtime,
        "_ensure_linked_room",
        lambda value: ({"teamId": value}, "team-room"),
    )
    monkeypatch.setattr(
        chain,
        "_resolve_hypothesis_participants",
        lambda *_args: {"participants": ["agent-a"]},
    )
    monkeypatch.setattr(
        chain,
        "_build_round_candidates",
        lambda *_args, **_kwargs: [],
    )
    opened_payloads: list[dict[str, object]] = []

    def fake_open(_team_id, payload, **_kwargs):
        opened_payloads.append(dict(payload))
        meeting_id = str(payload["meetingRoundId"])
        return {
            "status": "created",
            "meetingRound": {
                "meetingRoundId": meeting_id,
                "discussionScope": dict(payload["discussionScope"]),
                "discussionScopeHash": "hash",
                "linkedChatRoomId": f"room-{payload['candidateId']}",
            },
            "roomId": f"room-{payload['candidateId']}",
            "roundId": f"round-{payload['candidateId']}",
            "chatRoomRoundIds": [f"round-{payload['candidateId']}"],
        }

    monkeypatch.setattr(meeting_runtime, "open_hypothesis_review_meeting", fake_open)
    monkeypatch.setattr(
        chain,
        "_record_review_round_link",
        lambda _team_id, **fields: dict(fields),
    )

    result = chain.open_review_meeting_for_selection(
        team_id,
        {
            **_selection_payload("agent-a"),
            "selectionId": "selection-formal-1",
        },
        background=True,
    )

    assert result["candidateCount"] == 2
    assert len(result["reviewMeetings"]) == 2
    assert [payload["selectedCandidateIds"] for payload in opened_payloads] == [
        ["hyp-a"],
        ["hyp-b"],
    ]
    assert {
        payload["discussionScope"]["candidateId"] for payload in opened_payloads
    } == {"hyp-a", "hyp-b"}
    assert len({payload["meetingRoundId"] for payload in opened_payloads}) == 2


def test_selection_fans_out_per_candidate_without_receipt_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A temporarily unreadable Ledger cannot collapse candidate reviews."""
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_runtime
    from core.web.services.team_workflow.research_runtime import (
        meeting_receipt_authority,
    )

    team_id = "team-unscoped-fanout"
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        meeting_receipt_authority,
        "resolve_active_question_authority",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            meetings.ResearchMeetingRoundNotFoundError("missing")
        ),
    )
    monkeypatch.setattr(
        meeting_runtime,
        "_ensure_linked_room",
        lambda value: ({"teamId": value}, "team-room"),
    )
    monkeypatch.setattr(
        chain,
        "_resolve_hypothesis_participants",
        lambda *_args: {"participants": ["agent-a"]},
    )
    monkeypatch.setattr(
        chain,
        "_build_round_candidates",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        chain,
        "list_hypothesis_candidates",
        lambda *_args, **_kwargs: {"candidates": []},
    )
    opened_payloads: list[dict[str, object]] = []
    recorded_links: list[dict[str, object]] = []

    def fake_open(_team_id, payload, **_kwargs):
        opened_payloads.append(dict(payload))
        candidate_id = str(payload["candidateId"])
        return {
            "status": "created",
            "meetingRound": {"meetingRoundId": payload["meetingRoundId"]},
            "roomId": f"room-{candidate_id}",
            "roundId": f"round-{candidate_id}",
            "chatRoomRoundIds": [f"round-{candidate_id}"],
        }

    monkeypatch.setattr(meeting_runtime, "open_hypothesis_review_meeting", fake_open)
    monkeypatch.setattr(
        chain,
        "_record_review_round_link",
        lambda _team_id, **fields: recorded_links.append(dict(fields)) or dict(fields),
    )

    result = chain.open_review_meeting_for_selection(
        team_id,
        {**_selection_payload("agent-a"), "selectionId": "selection-unscoped-1"},
        background=True,
    )

    assert result["candidateCount"] == 2
    assert len(result["reviewMeetings"]) == 2
    assert [payload["selectedCandidateIds"] for payload in opened_payloads] == [
        ["hyp-a"],
        ["hyp-b"],
    ]
    assert {payload["candidateId"] for payload in opened_payloads} == {"hyp-a", "hyp-b"}
    assert all("discussionScope" not in payload for payload in opened_payloads)
    assert [link["candidate_id"] for link in recorded_links] == ["hyp-a", "hyp-b"]


def test_selection_reuses_server_generation_scope_when_receipt_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run-created generation scope retains candidate room identity on retry."""
    from core.research.workflow.contracts.discussion_scope import (
        WorkflowDiscussionScopeV1,
    )
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_runtime
    from core.web.services.team_workflow.research_runtime import (
        meeting_receipt_authority,
    )

    team_id = "team-scoped-fallback"
    generation_scope = WorkflowDiscussionScopeV1.generation(
        teamId=team_id,
        researchProjectId="project-1",
        workflowRunId="run-1",
        workflowNodeId=chain.HYPOTHESIS_DESIGN_NODE_ID,
        questionId=_QUESTION_ID,
    )
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        meeting_receipt_authority,
        "resolve_active_question_authority",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        chain,
        "list_hypothesis_candidates",
        lambda *_args, **_kwargs: {
            "candidates": [
                {"candidateId": "hyp-a", "meetingRoundId": "generation-1"},
                {"candidateId": "hyp-b", "meetingRoundId": "generation-1"},
            ]
        },
    )
    monkeypatch.setattr(
        chain,
        "_question_generation_meetings",
        lambda *_args, **_kwargs: [
            {
                "meetingRoundId": "generation-1",
                "discussionScope": generation_scope.to_dict(),
            }
        ],
    )
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            meetings.ResearchMeetingRoundNotFoundError("missing")
        ),
    )
    monkeypatch.setattr(
        meeting_runtime,
        "_ensure_linked_room",
        lambda value: ({"teamId": value}, "team-room"),
    )
    monkeypatch.setattr(
        chain,
        "_resolve_hypothesis_participants",
        lambda *_args: {"participants": ["agent-a"]},
    )
    monkeypatch.setattr(
        chain,
        "_build_round_candidates",
        lambda *_args, **_kwargs: [],
    )
    opened_payloads: list[dict[str, object]] = []

    def fake_open(_team_id, payload, **_kwargs):
        opened_payloads.append(dict(payload))
        return {
            "status": "created",
            "meetingRound": {"meetingRoundId": payload["meetingRoundId"]},
            "roomId": "room",
            "roundId": "round",
            "chatRoomRoundIds": ["round"],
        }

    monkeypatch.setattr(meeting_runtime, "open_hypothesis_review_meeting", fake_open)
    monkeypatch.setattr(
        chain,
        "_record_review_round_link",
        lambda _team_id, **fields: dict(fields),
    )

    chain.open_review_meeting_for_selection(
        team_id,
        {**_selection_payload("agent-a"), "selectionId": "selection-scoped-1"},
        background=True,
    )

    scopes = [payload["discussionScope"] for payload in opened_payloads]
    assert [scope["candidateId"] for scope in scopes] == ["hyp-a", "hyp-b"]
    assert {scope["workflowRunId"] for scope in scopes} == {"run-1"}
    assert {scope["researchProjectId"] for scope in scopes} == {"project-1"}


def test_question_run_scopes_candidate_generation_before_receipt_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import run_creation

    captured: dict[str, object] = {}
    need_calls: list[tuple[str, str, str]] = []

    def fake_needs(team_id, question_id, *, workflow_run_id=""):
        need_calls.append((team_id, question_id, workflow_run_id))
        return True

    monkeypatch.setattr(chain, "needs_candidate_generation", fake_needs)

    def fake_open(_team_id, _question_id, **kwargs):
        captured.update(kwargs)
        return {"status": "opened", "meetingRound": {"meetingRoundId": "generation-1"}}

    monkeypatch.setattr(chain, "open_candidate_generation_meeting", fake_open)
    run_input = {
        "teamId": "team-created-run",
        "questionId": _QUESTION_ID,
        "projectId": "project-created-run",
        "researchObjectiveContract": {"hypothesisFirst": True},
        "modelRoutingPolicy": {"modelPolicySha256": "a" * 64},
    }
    created_run = {
        "teamId": "team-created-run",
        "runId": "run-created-1",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-created-1",
    }

    opened = run_creation._auto_open_candidate_generation(
        run_input,
        created_run=created_run,
    )

    assert opened == {"status": "opened", "meetingRoundId": "generation-1"}
    assert need_calls == [("team-created-run", _QUESTION_ID, "run-created-1")]
    assert captured["_discussion_scope"] == {
        "version": 1,
        "kind": "question_generation",
        "teamId": "team-created-run",
        "researchProjectId": "project-created-run",
        "workflowRunId": "run-created-1",
        "workflowNodeId": chain.HYPOTHESIS_DESIGN_NODE_ID,
        "questionId": _QUESTION_ID,
    }
    assert captured["_candidate_authority"] == ""


def test_stage_one_question_run_auto_opens_exploratory_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.research.competition.stage_one_completion_policy import (
        load_stage_one_completion_policy,
    )
    from core.web.services.team_workflow.research_runtime import run_creation

    captured: dict[str, object] = {}
    monkeypatch.setattr(chain, "needs_candidate_generation", lambda *_args, **_kwargs: True)

    def fake_open(_team_id, _question_id, **kwargs):
        captured.update(kwargs)
        return {"status": "opened", "meetingRound": {"meetingRoundId": "r0-1"}}

    monkeypatch.setattr(chain, "open_candidate_generation_meeting", fake_open)
    opened = run_creation._auto_open_candidate_generation(
        {
            "teamId": "team-stage-one",
            "questionId": "SCI-091",
            "projectId": "project-stage-one",
            "researchObjectiveContract": {"hypothesisFirst": True},
            "modelRoutingPolicy": {"modelPolicySha256": "a" * 64},
            "stageOneCompletionPolicy": load_stage_one_completion_policy().to_dict(),
        },
        created_run={
            "teamId": "team-stage-one",
            "runId": "run-stage-one",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "wv-stage-one",
        },
    )

    assert opened == {"status": "opened", "meetingRoundId": "r0-1"}
    assert captured["_candidate_authority"] == "exploratory_draft"


def test_review_meeting_fan_in_waits_for_every_selected_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service

    team_id = "team-fan-in"
    links = [
        {
            "meetingRoundId": "meeting-a",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-a",
            "candidateOrder": 0,
        },
        {
            "meetingRoundId": "meeting-b",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-b",
            "candidateOrder": 1,
        },
    ]
    meeting_by_id = {
        "meeting-a": {"meetingRoundId": "meeting-a", "status": "closed"},
        "meeting-b": {"meetingRoundId": "meeting-b", "status": "open"},
    }
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        chain,
        "list_review_round_links",
        lambda *_args, **_kwargs: {"links": links},
    )
    monkeypatch.setattr(
        selections,
        "get_hypothesis_selection",
        lambda *_args: {
            "selection": {"selectedCandidateIds": ["hyp-a", "hyp-b"]}
        },
    )
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda _team_id, meeting_id: {"meetingRound": meeting_by_id[meeting_id]},
    )

    waiting = chain._review_meeting_fan_in_group(
        team_id, meeting_by_id["meeting-a"]
    )
    assert waiting["status"] == "waiting_for_sibling_reviews"
    assert waiting["pendingMeetingRoundIds"] == ["meeting-b"]

    meeting_by_id["meeting-b"] = {
        "meetingRoundId": "meeting-b",
        "status": "closed",
    }
    ready = chain._review_meeting_fan_in_group(
        team_id, meeting_by_id["meeting-b"]
    )
    assert ready["status"] == "ready"
    assert [item["meetingRoundId"] for item in ready["meetings"]] == [
        "meeting-a",
        "meeting-b",
    ]


def test_fan_in_skips_superseded_attempt_and_binds_latest_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A superseded round-1 attempt with a reopened round 2 is not authority.

    The sibling candidate's close must wait on the live successor instead of
    raising on the digest-less superseded meeting; once round 2 closes the
    group binds each candidate's newest authoritative attempt across rounds
    (roundIndex = highest authoritative round for idempotent close replays).
    """
    from core.web.services import team_service

    team_id = "team-fan-in-superseded"
    links = [
        {
            "meetingRoundId": "meeting-a-r1",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-a",
            "candidateOrder": 0,
        },
        {
            "meetingRoundId": "meeting-b-r1",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-b",
            "candidateOrder": 1,
        },
        {
            "meetingRoundId": "meeting-a-r2",
            "selectionId": "selection-1",
            "roundIndex": 2,
            "candidateId": "hyp-a",
            "candidateOrder": 0,
        },
    ]
    superseded_meeting = {
        "meetingRoundId": "meeting-a-r1",
        "status": "closed",
        "recoveryReason": "discussion_has_no_completed_messages",
    }
    meeting_by_id = {
        "meeting-a-r1": superseded_meeting,
        "meeting-b-r1": {"meetingRoundId": "meeting-b-r1", "status": "closed"},
        "meeting-a-r2": {"meetingRoundId": "meeting-a-r2", "status": "open"},
    }
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        chain,
        "list_review_round_links",
        lambda *_args, **_kwargs: {"links": links},
    )
    monkeypatch.setattr(
        selections,
        "get_hypothesis_selection",
        lambda *_args: {
            "selection": {"selectedCandidateIds": ["hyp-a", "hyp-b"]}
        },
    )
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda _team_id, meeting_id: {"meetingRound": meeting_by_id[meeting_id]},
    )

    waiting = chain._review_meeting_fan_in_group(
        team_id, meeting_by_id["meeting-b-r1"]
    )
    assert waiting["status"] == "waiting_for_sibling_reviews"
    assert waiting["pendingMeetingRoundIds"] == ["meeting-a-r2"]
    assert waiting["supersededMeetingRoundIds"] == ["meeting-a-r1"]
    assert waiting["supersededCandidateIds"] == []

    meeting_by_id["meeting-a-r2"] = {
        "meetingRoundId": "meeting-a-r2",
        "status": "closed",
    }
    ready_from_sibling = chain._review_meeting_fan_in_group(
        team_id, meeting_by_id["meeting-b-r1"]
    )
    assert ready_from_sibling["status"] == "ready"
    assert [item["meetingRoundId"] for item in ready_from_sibling["meetings"]] == [
        "meeting-a-r2",
        "meeting-b-r1",
    ]
    assert ready_from_sibling["roundIndex"] == 2

    # The round-2 candidate-scoped follow-up keeps its own group membership
    # (candidate-scoped rounds only fan in that round's scoped meetings).
    ready_from_latest = chain._review_meeting_fan_in_group(
        team_id, meeting_by_id["meeting-a-r2"]
    )
    assert ready_from_latest["status"] == "ready"
    assert [item["meetingRoundId"] for item in ready_from_latest["meetings"]] == [
        "meeting-a-r2"
    ]
    assert ready_from_latest["roundIndex"] == 2


def test_fan_in_folds_retry_attempt_links_to_newest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry attempts reuse (candidateId, roundIndex) with one link per attempt.

    The append-only attempt history must fold to its newest link before the
    duplicate-binding guard, otherwise any selection that ever retried a
    review dispatch raises "duplicate candidate bindings" on every close and
    the HF-3 HypothesisRound can never converge.
    """
    from core.web.services import team_service

    team_id = "team-fan-in-retries"
    links = [
        {
            "meetingRoundId": "meeting-a-r1",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-a",
            "candidateOrder": 0,
            "createdAt": "2026-08-31T01:00:00Z",
        },
        {
            "meetingRoundId": "meeting-a-r1-a2",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-a",
            "candidateOrder": 0,
            "createdAt": "2026-08-31T02:00:00Z",
        },
        {
            "meetingRoundId": "meeting-a-r1-a3",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-a",
            "candidateOrder": 0,
            "createdAt": "2026-08-31T03:00:00Z",
        },
        {
            "meetingRoundId": "meeting-b-r1",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-b",
            "candidateOrder": 1,
            "createdAt": "2026-08-31T01:30:00Z",
        },
    ]
    meeting_by_id = {
        "meeting-a-r1": {"meetingRoundId": "meeting-a-r1", "status": "closed"},
        "meeting-a-r1-a2": {
            "meetingRoundId": "meeting-a-r1-a2",
            "status": "closed",
        },
        "meeting-a-r1-a3": {
            "meetingRoundId": "meeting-a-r1-a3",
            "status": "closed",
        },
        "meeting-b-r1": {"meetingRoundId": "meeting-b-r1", "status": "closed"},
    }
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        chain,
        "list_review_round_links",
        lambda *_args, **_kwargs: {"links": links},
    )
    monkeypatch.setattr(
        selections,
        "get_hypothesis_selection",
        lambda *_args: {
            "selection": {"selectedCandidateIds": ["hyp-a", "hyp-b"]}
        },
    )
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda _team_id, meeting_id: {"meetingRound": meeting_by_id[meeting_id]},
    )

    ready = chain._review_meeting_fan_in_group(
        team_id, meeting_by_id["meeting-a-r1-a3"]
    )
    assert ready["status"] == "ready"
    assert [item["meetingRoundId"] for item in ready["meetings"]] == [
        "meeting-a-r1-a3",
        "meeting-b-r1",
    ]
    assert ready["roundIndex"] == 1


def test_fan_in_skips_execution_stopped_review_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fenced partial review cannot become the candidate's authority."""

    from core.web.services import team_service

    team_id = "team-fan-in-stopped"
    links = [
        {
            "meetingRoundId": "meeting-a-r1",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-a",
            "candidateOrder": 0,
        },
        {
            "meetingRoundId": "meeting-b-r1",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-b",
            "candidateOrder": 1,
        },
    ]
    meeting_by_id = {
        "meeting-a-r1": {
            "meetingRoundId": "meeting-a-r1",
            "status": "closed",
            "executionStatus": "stopped",
            "recoveryReason": "challenge_workflow_run_blocked",
            "digest": {"decisions": [{"decision": "stale partial result"}]},
        },
        "meeting-b-r1": {"meetingRoundId": "meeting-b-r1", "status": "closed"},
    }
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        chain,
        "list_review_round_links",
        lambda *_args, **_kwargs: {"links": links},
    )
    monkeypatch.setattr(
        selections,
        "get_hypothesis_selection",
        lambda *_args: {
            "selection": {"selectedCandidateIds": ["hyp-a", "hyp-b"]}
        },
    )
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda _team_id, meeting_id: {"meetingRound": meeting_by_id[meeting_id]},
    )

    waiting = chain._review_meeting_fan_in_group(
        team_id, meeting_by_id["meeting-b-r1"]
    )

    assert waiting["status"] == "waiting_for_sibling_reviews"
    assert waiting["supersededCandidateIds"] == ["hyp-a"]
    assert waiting["supersededMeetingRoundIds"] == ["meeting-a-r1"]


def test_fan_in_waits_when_superseded_candidate_has_no_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A candidate whose newest attempt is superseded with no successor stays
    pending: the group must not go ready and must not treat the abandoned
    attempt as review evidence."""
    from core.web.services import team_service

    team_id = "team-fan-in-superseded-no-successor"
    links = [
        {
            "meetingRoundId": "meeting-a-r1",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-a",
            "candidateOrder": 0,
        },
        {
            "meetingRoundId": "meeting-b-r1",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-b",
            "candidateOrder": 1,
        },
    ]
    meeting_by_id = {
        "meeting-a-r1": {
            "meetingRoundId": "meeting-a-r1",
            "status": "closed",
            "recoveryReason": "discussion_has_no_completed_messages",
        },
        "meeting-b-r1": {"meetingRoundId": "meeting-b-r1", "status": "closed"},
    }
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        chain,
        "list_review_round_links",
        lambda *_args, **_kwargs: {"links": links},
    )
    monkeypatch.setattr(
        selections,
        "get_hypothesis_selection",
        lambda *_args: {
            "selection": {"selectedCandidateIds": ["hyp-a", "hyp-b"]}
        },
    )
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda _team_id, meeting_id: {"meetingRound": meeting_by_id[meeting_id]},
    )

    waiting = chain._review_meeting_fan_in_group(
        team_id, meeting_by_id["meeting-b-r1"]
    )
    assert waiting["status"] == "waiting_for_sibling_reviews"
    assert waiting["supersededCandidateIds"] == ["hyp-a"]
    assert waiting["supersededMeetingRoundIds"] == ["meeting-a-r1"]
    assert waiting["pendingMeetingRoundIds"] == []
    assert waiting["missingCandidateIds"] == []


def test_hypothesis_round_fan_in_keeps_every_meeting_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow import (
        hypothesis_review_executor,
        research_memory_context,
    )

    team_id = "team-round-fan-in"
    scope = _scope_fields("agent-coordinator")
    scope_hash = scope_hash_for(
        program=scope["program"],
        theme=scope["theme"],
        campaign=scope["campaign"],
        question=scope["question"],
        branch=scope["branch"],
        workflow=scope["workflow"],
        agent_id=scope["agentId"],
        mode=scope["mode"],
    )
    meeting_by_id = {
        candidate_id: {
            **scope,
            "scopeHash": scope_hash,
            "meetingRoundId": meeting_id,
            "meetingType": "hypothesis_review",
            "status": "closed",
            "digestId": f"digest-{candidate_id}",
            "decisionRefs": [f"decision-{candidate_id}"],
            "discussionItemRefs": [f"hypothesis_candidate:{candidate_id}"],
            "participants": ["agent-coordinator"],
            "participantRoleIds": ["coordinator"],
            "closedBy": "agent-coordinator",
        }
        for candidate_id, meeting_id in (
            ("hyp-a", "meeting-a"),
            ("hyp-b", "meeting-b"),
        )
    }
    meetings_by_id = {
        item["meetingRoundId"]: item for item in meeting_by_id.values()
    }
    digest_rows = [
        {
            "digestId": f"digest-{candidate_id}",
            "summary": candidate_id,
            "sourceMessageRefs": [f"message:{candidate_id}"],
            "contentHash": f"hash-{candidate_id}",
        }
        for candidate_id in ("hyp-a", "hyp-b")
    ]
    decision_rows = [
        {
            "decisionId": f"decision-{candidate_id}",
            "decision": "approve",
            "candidateRefs": [candidate_id],
            "evidenceRefs": [f"message:{candidate_id}"],
        }
        for candidate_id in ("hyp-a", "hyp-b")
    ]
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda _team_id, meeting_id: {"meetingRound": meetings_by_id[meeting_id]},
    )
    monkeypatch.setattr(meetings, "_digests_path", lambda _team_id: Path("digests"))
    monkeypatch.setattr(meetings, "_decisions_path", lambda _team_id: Path("decisions"))
    monkeypatch.setattr(
        meetings,
        "_read_jsonl",
        lambda path: digest_rows if str(path) == "digests" else decision_rows,
    )
    captured_context: dict[str, object] = {}

    def fake_context(**kwargs):
        captured_context.update(kwargs)
        return {"contextId": "context-fan-in"}

    monkeypatch.setattr(
        research_memory_context, "build_hypothesis_review_context", fake_context
    )
    monkeypatch.setattr(
        hypothesis_review_executor,
        "execute_hypothesis_review",
        lambda *_args, **_kwargs: {
            "candidates": [],
            "pairwiseComparisons": [],
            "pareto": {"paretoFrontCandidateIds": []},
            "metaReview": {
                "accepted": False,
                "recommendationCandidateId": "hyp-a",
            },
            "reviewContextId": "context-fan-in",
            "positionSeed": "seed",
            "roles": {},
            "executionMode": "dev",
            "modelInvocationReceipts": [{"receiptId": "review-receipt-1"}],
        },
    )
    monkeypatch.setattr(hrounds, "_read_jsonl", lambda _path: [])
    monkeypatch.setattr(
        hrounds,
        "create_hypothesis_round",
        lambda _team_id, payload: {"status": "created", "round": payload},
    )

    result = hrounds.generate_hypothesis_round_from_meeting(
        team_id,
        "meeting-a",
        {
            "meetingRoundIds": ["meeting-a", "meeting-b"],
            "candidates": [
                {
                    "candidateId": candidate_id,
                    "claim": f"claim-{candidate_id}",
                    "rationale": f"why-{candidate_id}",
                }
                for candidate_id in ("hyp-a", "hyp-b")
            ],
        },
    )

    assert [
        item["id"]
        for item in result["round"]["meetingRefs"]
        if item["kind"] == "meeting_round"
    ] == ["meeting-a", "meeting-b"]
    assert [
        item["candidateId"] for item in captured_context["candidates"]
    ] == ["hyp-a", "hyp-b"]
    assert captured_context["digest"]["sourceMessageRefs"] == [
        "message:hyp-a",
        "message:hyp-b",
    ]
    assert result["round"]["reviewContextId"] == "context-fan-in"
    assert result["round"]["executionMode"] == "dev"
    assert result["round"]["modelInvocationReceipts"] == [
        {"receiptId": "review-receipt-1"}
    ]


def test_generate_round_writes_all_three_review_authorities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow import hypothesis_rounds as hrounds
    from core.web.services.team_workflow import hypothesis_selection as selections
    from core.web.services.team_workflow.research_runtime import (
        dimension_reviews_artifact_writer,
        review_independence_artifact_writer,
    )

    team_id = "team-review-authorities"
    meeting = {
        "meetingRoundId": "meeting-authorities",
        "question": "SCI-091",
        "scopeHash": "scope-authorities",
        "discussionScope": {"workflowRunId": "workflow-authorities"},
        "modelInvocationReceiptAuthority": {
            "workflowRunId": "workflow-authorities",
            "sourceCollectionRunId": "source-authorities",
        },
        "nodeRunId": "node-authorities",
        "inputSnapshotHash": "a" * 64,
        "inputArtifactRefs": ["evidence_card_batch://team/source/hash"],
    }
    candidates = [
        {"candidateId": "H1", "claim": "claim one"},
        {"candidateId": "H2", "claim": "claim two"},
    ]
    round_record = {
        "roundId": "round-authorities",
        "reviewContextId": "context-authorities",
        "executionMode": "formal",
        "roles": {"metareview": "coordinator-1"},
        "modelInvocationReceipts": [
            {
                "receiptId": "receipt-reflection-H1",
                "evidenceLocator": {
                    "reviewStep": "reflection",
                    "identityParts": ["H1"],
                },
            }
        ],
        "candidates": candidates,
        "pairwiseComparisons": [],
        "pareto": {},
        "metaReview": {},
    }
    monkeypatch.setattr(
        chain,
        "_review_meeting_fan_in_group",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "selectionId": "selection-authorities",
            "roundIndex": 1,
            "meetings": [meeting],
        },
    )
    monkeypatch.setattr(
        selections,
        "get_hypothesis_selection",
        lambda *_args, **_kwargs: {
            "selection": {
                "scopeHash": "scope-authorities",
                "questionId": "SCI-091",
                "selectedCandidateIds": ["H1", "H2"],
            }
        },
    )
    monkeypatch.setattr(chain, "_build_round_candidates", lambda *_a, **_k: candidates)
    monkeypatch.setattr(
        hrounds,
        "generate_hypothesis_round_from_meeting",
        lambda *_args, **_kwargs: {"status": "created", "round": round_record},
    )
    calls: dict[str, dict[str, object]] = {}

    def write_dimensions(**kwargs):
        calls["dimensions"] = kwargs
        return {"status": "written"}

    def write_independence(**kwargs):
        calls["independence"] = kwargs
        return {
            "status": "written",
            "reviewIndependence": {"artifact": {}},
            "reviewDisagreement": {"artifact": {}},
        }

    monkeypatch.setattr(
        dimension_reviews_artifact_writer,
        "materialize_dimension_reviews_authority",
        write_dimensions,
    )
    monkeypatch.setattr(
        review_independence_artifact_writer,
        "write_review_independence_artifacts",
        write_independence,
    )

    result = chain._generate_hypothesis_round(team_id, meeting)

    assert result["dimensionReviewsAuthority"]["status"] == "written"
    assert result["reviewIndependenceAuthority"]["status"] == "written"
    assert calls["dimensions"]["review"] is round_record
    assert calls["independence"]["review"] is round_record
    assert calls["independence"]["receipt_contexts"] == round_record[
        "modelInvocationReceipts"
    ]


def test_dimension_reviews_persistence_failure_keeps_run_identity_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a failing dimension-reviews write must not unbind the run.

    The receipt-derived ``workflow_run_id``/``node_run_id`` are bound before
    the dimension-reviews try block.  A persistence failure (or an import
    failure) there surfaces as the real error on the blocked dimension
    authority and must never leak a ``NameError`` into the downstream
    review-independence authority.
    """
    from core.web.services.team_workflow import hypothesis_rounds as hrounds
    from core.web.services.team_workflow import hypothesis_selection as selections
    from core.web.services.team_workflow.research_runtime import (
        dimension_reviews_artifact_writer,
        review_independence_artifact_writer,
    )

    team_id = "team-review-authorities"
    meeting = {
        "meetingRoundId": "meeting-authorities",
        "question": "SCI-091",
        "scopeHash": "scope-authorities",
        "discussionScope": {"workflowRunId": "workflow-authorities"},
        "modelInvocationReceiptAuthority": {
            "workflowRunId": "workflow-authorities",
            "sourceCollectionRunId": "source-authorities",
        },
        "nodeRunId": "node-authorities",
        "inputSnapshotHash": "a" * 64,
        "inputArtifactRefs": ["evidence_card_batch://team/source/hash"],
    }
    candidates = [
        {"candidateId": "H1", "claim": "claim one"},
        {"candidateId": "H2", "claim": "claim two"},
    ]
    round_record = {
        "roundId": "round-authorities",
        "reviewContextId": "context-authorities",
        "executionMode": "formal",
        "roles": {"metareview": "coordinator-1"},
        "modelInvocationReceipts": [],
        "candidates": candidates,
        "pairwiseComparisons": [],
        "pareto": {},
        "metaReview": {},
    }
    monkeypatch.setattr(
        chain,
        "_review_meeting_fan_in_group",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "selectionId": "selection-authorities",
            "roundIndex": 1,
            "meetings": [meeting],
        },
    )
    monkeypatch.setattr(
        selections,
        "get_hypothesis_selection",
        lambda *_args, **_kwargs: {
            "selection": {
                "scopeHash": "scope-authorities",
                "questionId": "SCI-091",
                "selectedCandidateIds": ["H1", "H2"],
            }
        },
    )
    monkeypatch.setattr(chain, "_build_round_candidates", lambda *_a, **_k: candidates)
    monkeypatch.setattr(
        hrounds,
        "generate_hypothesis_round_from_meeting",
        lambda *_args, **_kwargs: {"status": "created", "round": round_record},
    )

    def explode(**_kwargs):
        raise RuntimeError("dimension artifact store unavailable")

    monkeypatch.setattr(
        dimension_reviews_artifact_writer,
        "materialize_dimension_reviews_authority",
        explode,
    )
    independence_calls: list[dict[str, object]] = []

    def write_independence(**kwargs):
        independence_calls.append(kwargs)
        return {"status": "written"}

    monkeypatch.setattr(
        review_independence_artifact_writer,
        "write_review_independence_artifacts",
        write_independence,
    )

    result = chain._generate_hypothesis_round(team_id, meeting)

    dimension_authority = result["dimensionReviewsAuthority"]
    assert dimension_authority["status"] == "blocked"
    assert (
        dimension_authority["blockerCodes"]
        == ["dimension_reviews_authority_persistence_failed"]
    )
    # The real failure surfaces verbatim; no swallowed NameError.
    assert "dimension artifact store unavailable" in str(dimension_authority["error"])
    assert "NameError" not in str(dimension_authority["error"])
    # The downstream authority still receives the bound run identity.
    assert result["reviewIndependenceAuthority"]["status"] == "written"
    assert independence_calls[0]["workflow_run_id"] == "workflow-authorities"
    assert independence_calls[0]["node_run_id"] == "node-authorities"

def test_dimension_reviews_import_failure_carries_real_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a missing dimension-reviews dependency fails truthfully.

    The audited distortion: the ``workflow_run_id`` binding used to live
    inside the dimension-reviews try block, so an import failure left it
    unbound and the downstream review-independence try surfaced a swallowed
    ``NameError`` masquerading as a persistence blocker.  The run identity is
    now bound before any authority try block, and an import failure surfaces
    as the real dependency error on the blocked dimension authority while the
    downstream authority still writes with the bound identity.
    """
    import sys

    from core.web.services.team_workflow.research_runtime import (
        review_independence_artifact_writer,
    )

    team_id = "team-review-authorities"
    meeting = {
        "meetingRoundId": "meeting-authorities",
        "question": "SCI-091",
        "scopeHash": "scope-authorities",
        "discussionScope": {"workflowRunId": "workflow-authorities"},
        "modelInvocationReceiptAuthority": {
            "workflowRunId": "workflow-authorities",
            "sourceCollectionRunId": "source-authorities",
        },
        "nodeRunId": "node-authorities",
        "inputSnapshotHash": "a" * 64,
        "inputArtifactRefs": ["evidence_card_batch://team/source/hash"],
    }
    candidates = [
        {"candidateId": "H1", "claim": "claim one"},
        {"candidateId": "H2", "claim": "claim two"},
    ]
    round_record = {
        "roundId": "round-authorities",
        "reviewContextId": "context-authorities",
        "executionMode": "formal",
        "roles": {"metareview": "coordinator-1"},
        "modelInvocationReceipts": [],
        "candidates": candidates,
        "pairwiseComparisons": [],
        "pareto": {},
        "metaReview": {},
    }
    monkeypatch.setattr(
        chain,
        "_review_meeting_fan_in_group",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "selectionId": "selection-authorities",
            "roundIndex": 1,
            "meetings": [meeting],
        },
    )
    monkeypatch.setattr(
        selections,
        "get_hypothesis_selection",
        lambda *_args, **_kwargs: {
            "selection": {
                "scopeHash": "scope-authorities",
                "questionId": "SCI-091",
                "selectedCandidateIds": ["H1", "H2"],
            }
        },
    )
    monkeypatch.setattr(chain, "_build_round_candidates", lambda *_a, **_k: candidates)
    monkeypatch.setattr(
        hrounds,
        "generate_hypothesis_round_from_meeting",
        lambda *_args, **_kwargs: {"status": "created", "round": round_record},
    )
    # Simulate the dependency being unavailable at import time (the audited
    # scenario), not just the materialization call failing.
    monkeypatch.setitem(
        sys.modules,
        "core.web.services.team_workflow.research_runtime.dimension_reviews_artifact_writer",
        None,
    )
    independence_calls: list[dict[str, object]] = []

    def write_independence(**kwargs):
        independence_calls.append(kwargs)
        return {"status": "written"}

    monkeypatch.setattr(
        review_independence_artifact_writer,
        "write_review_independence_artifacts",
        write_independence,
    )

    result = chain._generate_hypothesis_round(team_id, meeting)

    dimension_authority = result["dimensionReviewsAuthority"]
    assert dimension_authority["status"] == "blocked"
    # The real cause (the unavailable dependency) is surfaced verbatim.
    assert "dimension_reviews_artifact_writer" in str(dimension_authority["error"])
    # No NameError distortion anywhere: the run identity was never unbound.
    assert "NameError" not in str(dimension_authority["error"])
    assert "NameError" not in str(result["reviewIndependenceAuthority"])
    assert result["reviewIndependenceAuthority"]["status"] == "written"
    assert independence_calls[0]["workflow_run_id"] == "workflow-authorities"
    assert independence_calls[0]["node_run_id"] == "node-authorities"


def _canonical_stage_one_question_detail() -> dict[str, Any]:
    return {
        "record": {
            "runId": "workflow-authorities",
            "questionId": "SCI-091",
            "schemaVersion": 2,
            "status": "approved",
            "validation": {
                "schemaValidation": "passed",
                "citationValidation": "passed",
                "officialModelCall": True,
            },
        },
        "artifact": {"sha256": "f" * 64, "immutable": True},
        "output": {
            "schema_version": 2,
            "identity": {
                "catalog_id": "science-125-questions-2021",
                "question_id": "SCI-091",
                "question_en": "Canonical question",
            },
            "hypotheses": [
                {
                    "hypothesis_id": "hyp-a",
                    "statement": "Canonical selected hypothesis",
                }
            ],
            "selection": {
                "selected_hypothesis_id": "hyp-a",
                "human_gate": {"decision": "approved"},
            },
            "research_plan": {
                "proposal_only": True,
                "objective": "Test the selected hypothesis.",
                "human_gate": {"decision": "approved"},
            },
            "competition_result_view": {
                "problem_statement": "Canonical competition problem.",
                "rationale": "Why the selected hypothesis matters.",
                "technical_details": "Bounded technical approach.",
                "datasets": {"planned": ["dataset-a"], "used": ["not executed"]},
                "methods": ["planned method"],
                "experiments": ["planned experiment"],
                "results": ["not executed"],
                "references": ["source://canonical"],
                "paper_title": "Planned paper",
                "paper_abstract": "Proposal only.",
            },
        },
    }


def test_stage_one_plan_writer_projects_only_canonical_question_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        stage_one_plan_artifact_writer as writer,
    )
    from core.web.services.team_workflow.research_runtime import (
        artifact_readback_registry,
        workflow_artifact_store,
    )

    rows: list[dict[str, Any]] = []

    def fake_put(team_id: str, **kwargs):
        record = {
            "recordId": kwargs["artifact_identity"],
            "teamId": team_id,
            "kind": kwargs["kind"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": writer.canonical_sha256(kwargs["payload"]),
            "payload": kwargs["payload"],
        }
        rows.append(record)
        return record

    monkeypatch.setattr(writer, "put_workflow_artifact", fake_put)
    monkeypatch.setattr(
        writer,
        "list_workflow_artifacts",
        lambda *args, **kwargs: [],
    )
    detail = _canonical_stage_one_question_detail()

    result = writer.write_stage_one_plan_artifacts(
        team_id="team-review-authorities",
        workflow_run_id="workflow-authorities",
        node_run_id="node-authorities",
        question_id="SCI-091",
        selected_candidate_id="hyp-a",
        question_detail=detail,
        source_collection_run_id="source-authorities",
    )

    assert result["status"] == "written"
    assert "stage1_research_plan" in workflow_artifact_store._SUPPORTED_KINDS
    assert "competition_alignment" in workflow_artifact_store._SUPPORTED_KINDS
    assert "stage_one_completion_manifest" in workflow_artifact_store._SUPPORTED_KINDS
    assert artifact_readback_registry.resolve_artifact_authority(
        "stage1_research_plan"
    ) is not None
    assert artifact_readback_registry.resolve_artifact_authority(
        "competition_alignment"
    ) is not None
    assert artifact_readback_registry.resolve_artifact_authority(
        "stage_one_completion_manifest"
    ) is not None
    assert [row["kind"] for row in rows] == [
        "stage1_research_plan",
        "competition_alignment",
    ]
    assert rows[0]["payload"] == detail["output"]["research_plan"]
    alignment = rows[1]["payload"]
    assert alignment["questionIdentity"] == detail["output"]["identity"]
    assert alignment["selectedHypothesis"] == {
        "hypothesisId": "hyp-a",
        "statement": "Canonical selected hypothesis",
    }
    assert alignment["competitionResultView"] == detail["output"][
        "competition_result_view"
    ]


def test_stage_one_plan_writer_blocks_before_store_when_canonical_sections_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        stage_one_plan_artifact_writer as writer,
    )

    calls: list[str] = []
    monkeypatch.setattr(
        writer,
        "put_workflow_artifact",
        lambda *args, **kwargs: calls.append("put"),
    )
    detail = _canonical_stage_one_question_detail()
    del detail["output"]["competition_result_view"]

    result = writer.write_stage_one_plan_artifacts(
        team_id="team-review-authorities",
        workflow_run_id="workflow-authorities",
        node_run_id="node-authorities",
        question_id="SCI-091",
        selected_candidate_id="hyp-a",
        question_detail=detail,
        source_collection_run_id="source-authorities",
    )

    assert result["status"] == "blocked"
    assert "competition_alignment_source_missing" in result["blockerCodes"]
    assert calls == []


def test_round_revision_authority_requires_explicit_hash_bound_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        feedback_iterations_artifact_writer as writer,
    )

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        writer,
        "write_feedback_iterations_artifact",
        lambda **kwargs: calls.append(kwargs) or {"status": "recorded"},
    )
    missing = chain._materialize_hypothesis_revision_authority(
        team_id="team-review-authorities",
        workflow_run_id="workflow-authorities",
        node_run_id="node-authorities",
        question_id="SCI-091",
        source_collection_run_id="source-authorities",
        round_record={"metaReview": {"accepted": True}},
    )
    evidence = {
        "feedback": {
            "trigger": "Grounding changed the hypothesis.",
            "humanFeedback": "Keep the claim within the cited population.",
            "inputRefs": ["hypothesis_set://team/source/r0"],
            "inputHash": "a" * 64,
        },
        "revision": {
            "changes": ["Narrowed the claim."],
            "unresolvedIssues": ["External validity remains open."],
            "outputRefs": ["hypothesis_set://team/source/r1"],
            "outputHash": "b" * 64,
            "status": "completed",
        },
    }
    written = chain._materialize_hypothesis_revision_authority(
        team_id="team-review-authorities",
        workflow_run_id="workflow-authorities",
        node_run_id="node-authorities",
        question_id="SCI-091",
        source_collection_run_id="source-authorities",
        round_record={
            "revisionEnvelope": {"phase": "grounded_revision", **evidence}
        },
    )

    assert missing["status"] == "blocked"
    assert "hypothesis_revision_evidence_missing" in missing["blockerCodes"]
    assert written["status"] == "recorded"
    assert calls[0]["node_id"] == "hypothesis_design"
    assert calls[0]["revision_phase"] == "grounded_revision"
    assert calls[0]["iteration_round"] == 1


def test_review_revision_requires_provider_receipt_and_continuous_grounded_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow import hypothesis_review_executor
    from core.web.services.team_workflow.research_runtime import (
        feedback_iterations_artifact_writer as writer,
    )
    from core.web.services.team_workflow.research_runtime import (
        workflow_artifact_store,
    )

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        writer,
        "write_feedback_iterations_artifact",
        lambda **kwargs: calls.append(kwargs) or {"status": "recorded"},
    )
    r1_candidates = [
        {
            "candidateId": "cand-a",
            "claim": "R1 A",
            "lineageRefs": ["paper:a"],
            "testablePrediction": "Prediction A",
            "falsifier": "Falsifier A",
            "axisProfile": {"mechanism": "a"},
        },
        {
            "candidateId": "cand-b",
            "claim": "R1 B",
            "lineageRefs": ["paper:b"],
            "testablePrediction": "Prediction B",
            "falsifier": "Falsifier B",
            "axisProfile": {"mechanism": "b"},
        },
        {
            "candidateId": "cand-c",
            "claim": "R1 C",
            "lineageRefs": ["paper:c"],
            "testablePrediction": "Prediction C",
            "falsifier": "Falsifier C",
            "axisProfile": {"mechanism": "c"},
        },
    ]
    r1_snapshot = hypothesis_review_executor.canonical_hypothesis_revision_snapshot(
        r1_candidates
    )
    r1_refs = [
        f"hypothesis_candidate:{item['candidateId']}:r1" for item in r1_snapshot
    ]
    r1_hash = chain._stable_hash(r1_snapshot)
    selected_r2 = [
        {**r1_candidates[0], "claim": "R2 A narrowed"},
        r1_candidates[1],
    ]
    envelope = {
        "phase": "review_revision",
        "parentCandidateId": "cand-a",
        "revisionReceiptRef": "receipt-r2",
        "feedback": {
            "trigger": "formal_hypothesis_review",
            "humanFeedback": "Narrow the population boundary.",
            "inputRefs": [
                "hypothesis_candidate:cand-a:r1",
                "hypothesis_candidate:cand-b:r1",
            ],
            "inputHash": "f" * 64,
        },
        "revision": {
            "changes": ["Narrowed the population."],
            "unresolvedIssues": ["External validity remains open."],
            "outputRefs": [
                "hypothesis_candidate:cand-a:r2",
                "hypothesis_candidate:cand-b:r2",
            ],
            "outputHash": "e" * 64,
            "status": "completed",
            "output": {"candidates": selected_r2},
        },
    }
    round_record = {
        "revisionEnvelope": envelope,
        "modelInvocationReceipts": [
            {
                "receiptId": "receipt-r2",
                "metadata": {"outcomeKinds": ["review", "revision"]},
            }
        ],
    }
    monkeypatch.setattr(
        workflow_artifact_store,
        "list_workflow_artifacts",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        chain,
        "list_hypothesis_candidates",
        lambda *_args, **_kwargs: {"candidates": r1_candidates},
    )

    missing_parent = chain._materialize_hypothesis_revision_authority(
        team_id="team-review-authorities",
        workflow_run_id="workflow-authorities",
        node_run_id="node-authorities",
        question_id="SCI-091",
        source_collection_run_id="source-authorities",
        round_record=round_record,
    )
    assert "hypothesis_grounded_revision_authority_missing" in missing_parent[
        "blockerCodes"
    ]
    assert calls == []

    monkeypatch.setattr(
        workflow_artifact_store,
        "list_workflow_artifacts",
        lambda *_args, **_kwargs: [
            {
                "payload": {
                    "iterationRound": 1,
                    "revisionPhase": "grounded_revision",
                    "revisionEnvelope": {
                        "phase": "grounded_revision",
                        "childOutput": {
                            "refs": r1_refs,
                            "sha256": "d" * 64,
                        },
                    },
                }
            }
        ],
    )
    discontinuous = chain._materialize_hypothesis_revision_authority(
        team_id="team-review-authorities",
        workflow_run_id="workflow-authorities",
        node_run_id="node-authorities",
        question_id="SCI-091",
        source_collection_run_id="source-authorities",
        round_record=round_record,
    )
    assert "hypothesis_revision_lineage_discontinuous" in discontinuous[
        "blockerCodes"
    ]
    assert calls == []

    monkeypatch.setattr(
        workflow_artifact_store,
        "list_workflow_artifacts",
        lambda *_args, **_kwargs: [
            {
                "payload": {
                    "iterationRound": 1,
                    "revisionPhase": "grounded_revision",
                    "revisionEnvelope": {
                        "phase": "grounded_revision",
                        "childOutput": {
                            "refs": r1_refs,
                            "sha256": r1_hash,
                        },
                    },
                }
            }
        ],
    )
    written = chain._materialize_hypothesis_revision_authority(
        team_id="team-review-authorities",
        workflow_run_id="workflow-authorities",
        node_run_id="node-authorities",
        question_id="SCI-091",
        source_collection_run_id="source-authorities",
        round_record=round_record,
    )
    assert written["status"] == "recorded"
    assert calls[0]["iteration_round"] == 2
    assert calls[0]["revision_phase"] == "review_revision"
    assert calls[0]["feedback"]["inputRefs"] == r1_refs
    assert calls[0]["feedback"]["inputHash"] == r1_hash
    r2_snapshot = calls[0]["revision"]["output"]["candidates"]
    assert [item["candidateId"] for item in r2_snapshot] == [
        "cand-a",
        "cand-b",
        "cand-c",
    ]
    assert next(
        item for item in r2_snapshot if item["candidateId"] == "cand-a"
    )["claim"] == "R2 A narrowed"
    assert next(
        item for item in r2_snapshot if item["candidateId"] == "cand-c"
    )["claim"] == "R1 C"
    assert calls[0]["revision"]["outputRefs"] == [
        "hypothesis_candidate:cand-a:r2",
        "hypothesis_candidate:cand-b:r2",
        "hypothesis_candidate:cand-c:r2",
    ]
    assert calls[0]["revision"]["outputHash"] == chain._stable_hash(r2_snapshot)


def test_formal_grounded_generation_materializes_real_r0_to_r1_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow import hypothesis_review_executor
    from core.web.services.team_workflow.research_runtime import (
        feedback_iterations_artifact_writer as writer,
    )
    from core.web.services.team_workflow.research_runtime import (
        model_invocation_receipt_registry as registry,
    )

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        registry,
        "question_model_invocation_receipt_refs",
        lambda *_args, **_kwargs: [
            {
                "receiptId": "receipt-r1",
                "nodeRunId": "generation-node-r1",
                "outcomeKinds": ["candidate", "revision"],
                "evidenceLocator": {"meetingRoundId": "meeting-r1"},
            }
        ],
    )
    drafts = [
        {"draftId": "draft-a", "candidateId": "draft-a", "statement": "R0 A"},
        {"draftId": "draft-b", "candidateId": "draft-b", "statement": "R0 B"},
    ]
    monkeypatch.setattr(
        chain,
        "list_exploratory_drafts",
        lambda *_args, **_kwargs: {"drafts": drafts},
    )
    monkeypatch.setattr(
        hypothesis_review_executor,
        "_source_collection_run_id_for_formal_workflow",
        lambda _run_id: "source-r1",
    )
    monkeypatch.setattr(
        writer,
        "write_feedback_iterations_artifact",
        lambda **kwargs: calls.append(kwargs) or {"status": "recorded"},
    )
    candidates = [
        {
            "candidateId": "cand-a",
            "statement": "R1 A grounded",
            "lineageRefs": ["paper:a"],
            "testablePrediction": "Prediction A",
            "falsifier": "Falsifier A",
            "axisProfile": {"mechanism": "a"},
        },
        {
            "candidateId": "cand-b",
            "statement": "R1 B grounded",
            "lineageRefs": ["paper:b"],
            "testablePrediction": "Prediction B",
            "falsifier": "Falsifier B",
            "axisProfile": {"mechanism": "b"},
        },
    ]

    result = chain._materialize_grounded_revision_authority(
        "team-review-authorities",
        {
            "meetingRoundId": "meeting-r1",
            "mode": "formal",
            "candidateAuthority": "formal_grounded_candidate",
            "question": "SCI-091",
            "exploratoryDraftRefs": [
                "exploratory_draft:draft-a",
                "exploratory_draft:draft-b",
            ],
            "modelInvocationReceiptAuthority": {
                "workflowRunId": "workflow-authorities"
            },
        },
        candidates,
    )

    assert result["status"] == "recorded"
    assert calls[0]["iteration_round"] == 1
    assert calls[0]["node_run_id"] == "generation-node-r1"
    assert calls[0]["revision_phase"] == "grounded_revision"
    r1_snapshot = hypothesis_review_executor.canonical_hypothesis_revision_snapshot(
        candidates
    )
    assert calls[0]["revision"]["outputHash"] == chain._stable_hash(r1_snapshot)
    assert calls[0]["revision"]["outputRefs"] == [
        "hypothesis_candidate:cand-a:r1",
        "hypothesis_candidate:cand-b:r1",
    ]


def test_accepted_round_materializes_stage_one_plan_from_approved_question_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import question_launch
    from core.web.services.team_workflow.research_runtime import (
        stage_one_plan_artifact_writer as writer,
    )

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        question_launch,
        "_approved_details",
        lambda _team_id: {"SCI-091": _canonical_stage_one_question_detail()},
    )
    monkeypatch.setattr(
        writer,
        "write_stage_one_plan_artifacts",
        lambda **kwargs: calls.append(kwargs) or {"status": "written"},
    )

    result = chain._materialize_stage_one_plan_authority(
        team_id="team-review-authorities",
        workflow_run_id="workflow-authorities",
        node_run_id="node-authorities",
        question_id="SCI-091",
        source_collection_run_id="source-authorities",
        round_record={
            "metaReview": {
                "accepted": True,
                "recommendationCandidateId": "hyp-a",
            }
        },
    )

    assert result["status"] == "written"
    assert calls[0]["selected_candidate_id"] == "hyp-a"
    assert calls[0]["question_detail"] == _canonical_stage_one_question_detail()


def test_chain_state_projects_first_open_candidate_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service

    team_id = "team-anchor"
    scope_a = {
        "version": 1,
        "kind": "candidate_review",
        "teamId": team_id,
        "researchProjectId": "project-1",
        "workflowRunId": "run-1",
        "workflowNodeId": "hypothesis_design",
        "questionId": _QUESTION_ID,
        "selectionId": "selection-1",
        "candidateId": "hyp-a",
    }
    scope_b = {**scope_a, "candidateId": "hyp-b"}
    scope_hashes = {
        "room-a": parse_discussion_scope(scope_a).scope_hash,
        "room-b": parse_discussion_scope(scope_b).scope_hash,
    }
    records = [
        {
            "recordKind": chain.REVIEW_ROUND_LINK_KIND,
            "linkId": "link-a",
            "selectionId": "selection-1",
            "meetingRoundId": "meeting-a",
            "questionId": _QUESTION_ID,
            "roundIndex": 1,
            "candidateId": "hyp-a",
            "candidateOrder": 0,
        },
        {
            "recordKind": chain.REVIEW_ROUND_LINK_KIND,
            "linkId": "link-b",
            "selectionId": "selection-1",
            "meetingRoundId": "meeting-b",
            "questionId": _QUESTION_ID,
            "roundIndex": 1,
            "candidateId": "hyp-b",
            "candidateOrder": 1,
        },
    ]
    # Ledger insertion order is intentionally opposite to candidateOrder;
    # chain_state must follow the explicit ordering key, not array position.
    records.reverse()
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(chain, "_records", lambda _team_id: records)
    monkeypatch.setattr(
        chain,
        "_question_meetings",
        lambda *_args: [
            {
                "meetingRoundId": "meeting-a",
                "meetingType": chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
                "question": _QUESTION_ID,
                "status": "open",
                "discussionScope": scope_a,
                "discussionScopeHash": scope_hashes["room-a"],
                "linkedChatRoomId": "room-a",
            },
            {
                "meetingRoundId": "meeting-b",
                "meetingType": chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
                "question": _QUESTION_ID,
                "status": "open",
                "discussionScope": scope_b,
                "discussionScopeHash": scope_hashes["room-b"],
                "linkedChatRoomId": "room-b",
            },
        ],
    )
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_compact",
        lambda room_id: {
            "roomId": room_id,
            "status": "active",
            "config": {
                "discussionScope": scope_a if room_id == "room-a" else scope_b,
                "scopeHash": scope_hashes[room_id],
            },
        },
    )
    monkeypatch.setattr(chain, "_question_hypothesis_rounds", lambda *_args: [])
    monkeypatch.setattr(chain, "_question_template_baselines", lambda *_args: [])
    monkeypatch.setattr(chain, "_question_generation_meetings", lambda *_args: [])

    state = chain.chain_state(team_id, _QUESTION_ID)

    anchor = state["activeDiscussionAnchor"]
    assert anchor["status"] == "ready"
    assert anchor["scope"] == scope_a
    assert anchor["scopeHash"] == scope_hashes["room-a"]
    assert anchor["meetingRoundId"] == "meeting-a"
    assert anchor["roomId"] == "room-a"
    assert anchor["questionId"] == _QUESTION_ID
    assert anchor["selectionId"] == "selection-1"
    assert anchor["candidateId"] == "hyp-a"
    assert "returnTo=" in anchor["deepLink"]
    assert anchor["returnLabel"] == "返回科研流程"


def test_chain_state_ignores_review_artifacts_from_other_workflow_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service

    team_id = "team-run-scoped-state"

    def authority(run_id: str) -> dict[str, str]:
        return {"workflowRunId": run_id}

    meeting_rows = [
        {
            "meetingRoundId": "generation-old",
            "meetingType": chain.CANDIDATE_GENERATION_MEETING_TYPE,
            "question": _QUESTION_ID,
            "status": "closed",
            "modelInvocationReceiptAuthority": authority("run-old"),
        },
        {
            "meetingRoundId": "review-old",
            "meetingType": chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            "question": _QUESTION_ID,
            "status": "closed",
            "modelInvocationReceiptAuthority": authority("run-old"),
        },
        {
            "meetingRoundId": "generation-new",
            "meetingType": chain.CANDIDATE_GENERATION_MEETING_TYPE,
            "question": _QUESTION_ID,
            "status": "open",
            "modelInvocationReceiptAuthority": authority("run-new"),
        },
        {
            "meetingRoundId": "review-new",
            "meetingType": chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            "question": _QUESTION_ID,
            "status": "closed",
            "modelInvocationReceiptAuthority": authority("run-new"),
        },
    ]
    records = [
        {
            "recordKind": chain.REVIEW_ROUND_LINK_KIND,
            "linkId": "link-old",
            "selectionId": "selection-old",
            "meetingRoundId": "review-old",
            "questionId": _QUESTION_ID,
            "roundIndex": 1,
        },
        {
            "recordKind": chain.COLLECTION_REQUEST_KIND,
            "requestId": "request-old",
            "meetingRoundId": "review-old",
            "questionId": _QUESTION_ID,
            "status": "pending",
        },
        {
            "recordKind": chain.CANDIDATE_KIND,
            "candidateId": "candidate-old",
            "meetingRoundId": "generation-old",
            "questionId": _QUESTION_ID,
        },
        {
            "recordKind": chain.REVIEW_ROUND_LINK_KIND,
            "linkId": "link-new",
            "selectionId": "selection-new",
            "meetingRoundId": "review-new",
            "questionId": _QUESTION_ID,
            "roundIndex": 1,
        },
        {
            "recordKind": chain.COLLECTION_REQUEST_KIND,
            "requestId": "request-new",
            "meetingRoundId": "review-new",
            "questionId": _QUESTION_ID,
            "status": "pending",
        },
        {
            "recordKind": chain.CANDIDATE_KIND,
            "candidateId": "candidate-new",
            "meetingRoundId": "generation-new",
            "questionId": _QUESTION_ID,
        },
    ]
    rounds = [
        {
            "roundId": "round-old",
            "question": _QUESTION_ID,
            "status": "closed",
            "meetingRefs": [{"kind": "meeting_round", "id": "review-old"}],
        },
        {
            "roundId": "round-new",
            "question": _QUESTION_ID,
            "status": "open",
            "meetingRefs": [{"kind": "meeting_round", "id": "review-new"}],
        },
    ]

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(chain, "_records", lambda _team_id: records)
    monkeypatch.setattr(
        meetings,
        "list_meeting_rounds",
        lambda _team_id: {"meetings": meeting_rows},
    )
    monkeypatch.setattr(
        chain,
        "_question_hypothesis_rounds",
        lambda *_args: rounds,
    )
    monkeypatch.setattr(chain, "_question_template_baselines", lambda *_args: [])

    state = chain.chain_state(
        team_id,
        _QUESTION_ID,
        workflow_run_id="run-new",
    )

    assert state["selectionId"] == "selection-new"
    assert state["meetingCount"] == 1
    assert [item["requestId"] for item in state["collectionRequests"]] == [
        "request-new"
    ]
    assert state["hypothesisRoundCount"] == 1
    assert state["latestHypothesisRoundId"] == "round-new"
    assert state["candidateCount"] == 1
    assert state["generationMeetingId"] == "generation-new"


def _marker_runner(participant, prompt, context):
    """Round 1 carries the DEV fixture markers; follow-up critique rounds pass."""
    if "批评与修订" in str(prompt):
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}
    role = str(participant.get("teamRole") or "participant")
    if role in {"source_finder", "challenge_cup_search"}:
        content = "AGREE: hyp-a 的机制证据最完整，进入有界验证"
    else:
        content = (
            "DISAGREE: hyp-b 的泛化证据不足\n"
            "RISK: 数据集偏差尚未评估\n"
            "ACTION: researcher | 补充 hyp-b 的消融实验证据\n"
            "KNOWLEDGE: 预测编码层级最新综述"
        )
    return {"status": "completed", "raw_output": content, "summary": "ok"}


def _fake_collection_runs(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_start(team_id, payload=None):
        calls.append({"teamId": team_id, "payload": dict(payload or {})})
        return {"runId": f"dprun-hf4-{len(calls)}", "status": "accepted"}

    def fake_background_start(team_id, run_id, payload=None):
        return {
            "teamId": team_id,
            "runId": run_id,
            "status": "running",
            "payload": dict(payload or {}),
        }

    monkeypatch.setattr(collection_runs, "start_source_collection_run", fake_start)
    monkeypatch.setattr(
        collection_runs, "start_source_collection_search_background", fake_background_start
    )
    return calls


def _collection_decision(
    candidate_ref: str,
    evidence_ref: str,
) -> dict[str, object]:
    return {
        "decision": chain.REQUEST_EVIDENCE_DECISION,
        "candidateRefs": [candidate_ref],
        "evidenceRefs": [evidence_ref],
        "searchEnvelope": {"keywords": ["predictive coding"]},
    }


def _process_collection_decisions_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    decisions: list[dict[str, object]],
):
    meeting = {
        "meetingRoundId": "meeting-hf-start",
        "scopeHash": "scope-hf-start",
        "question": _QUESTION_ID,
    }
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        chain,
        "_scope_envelope_for_meeting",
        lambda _meeting: {"scopeHash": "scope-hf-start"},
    )
    monkeypatch.setattr(
        facade,
        "_normalize_search_envelope",
        lambda envelope, *, require_keywords: dict(envelope or {}),
    )
    monkeypatch.setattr(facade, "_normalize_requirements", lambda value: dict(value or {}))
    monkeypatch.setattr(
        facade,
        "_normalize_writeback_policy",
        lambda value: dict(value or {}),
    )
    monkeypatch.setattr(
        facade,
        "research_knowledge_collection_facade",
        lambda **_kwargs: {"locator": {"runId": "dprun-hf-start"}},
    )
    close_result = {
        "decisions": [
            {"decisionId": chain._decision_id_for(meeting, decision)}
            for decision in decisions
        ]
    }
    return meeting, close_result


def test_collection_decisions_start_one_background_search_per_reused_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decisions = [
        _collection_decision("hyp-a", "message-a"),
        _collection_decision("hyp-b", "message-b"),
    ]
    meeting, close_result = _process_collection_decisions_fixture(
        tmp_path, monkeypatch, decisions=decisions
    )
    started: list[dict[str, object]] = []

    def fake_start(team_id: str, run_id: str, payload=None) -> dict[str, object]:
        started.append(
            {"teamId": team_id, "runId": run_id, "payload": dict(payload or {})}
        )
        return {"runId": run_id, "status": "running"}

    monkeypatch.setattr(
        collection_runs, "start_source_collection_search_background", fake_start
    )

    result = chain._process_collection_decisions(
        "team-hf-start",
        meeting,
        close_result,
        {"decisions": decisions},
    )

    assert len(result["requests"]) == 2
    assert {request["collectionRunId"] for request in result["requests"]} == {
        "dprun-hf-start"
    }
    assert started == [
        {
            "teamId": "team-hf-start",
            "runId": "dprun-hf-start",
            "payload": {"backgroundExecution": True, "maxQueries": 12},
        }
    ]


def test_collection_decisions_carry_hypothesis_candidate_refs_to_request_and_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """request_new_evidence candidateRefs survive into the run's gate dimension.

    The decision's ``candidateRefs`` (hypothesis candidate ids) are normalized
    onto the collection request ledger record and passed to the facade ensure
    payload so the created collection run persists them
    (``scope.hypothesisCandidateIds``) for evidence materialization.
    """
    decisions = [
        {
            "decision": chain.REQUEST_EVIDENCE_DECISION,
            "candidateRefs": [
                "sci-mtz-1-c1a2b3c4",
                "sci-mtz-1-c1a2b3c4",
                " ",
                "sci-mtz-1-c9f8e7d6c",
            ],
            "evidenceRefs": ["message-a"],
            "searchEnvelope": {"keywords": ["predictive coding"]},
        },
    ]
    meeting, close_result = _process_collection_decisions_fixture(
        tmp_path, monkeypatch, decisions=decisions
    )
    facade_calls: list[dict[str, object]] = []

    def fake_facade(**kwargs):
        facade_calls.append(dict(kwargs))
        return {"locator": {"runId": "dprun-hf-start"}}

    monkeypatch.setattr(facade, "research_knowledge_collection_facade", fake_facade)
    monkeypatch.setattr(
        collection_runs,
        "start_source_collection_search_background",
        lambda team_id, run_id, payload=None: {"runId": run_id, "status": "running"},
    )

    result = chain._process_collection_decisions(
        "team-hf-start",
        meeting,
        close_result,
        {"decisions": decisions},
    )

    expected_refs = ["sci-mtz-1-c1a2b3c4", "sci-mtz-1-c9f8e7d6c"]
    request = result["requests"][0]
    assert request["hypothesisCandidateIds"] == expected_refs
    assert facade_calls[0]["hypothesisCandidateIds"] == expected_refs


def test_collection_decision_without_candidate_refs_is_rejected_structurally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request_new_evidence decision without candidateRefs never silently runs.

    The claim belief gate aggregates evidence on the decision's candidateRefs
    dimension, so a decision without them can only materialize an empty
    dimension and fail that gate closed at convergence.  The consumer-side
    contract check rejects it with a structured skip plus a scene event
    instead of creating a request doomed to ``claim_data_missing``.
    """
    scene_events: list[dict[str, object]] = []
    monkeypatch.setattr(
        chain,
        "_record_scene_event",
        lambda event_code, **kwargs: scene_events.append(
            {"eventCode": event_code, **kwargs}
        ),
    )
    decisions = [
        {
            "decision": chain.REQUEST_EVIDENCE_DECISION,
            "evidenceRefs": ["message-b"],
            "searchEnvelope": {"keywords": ["predictive coding"]},
        },
    ]
    meeting, close_result = _process_collection_decisions_fixture(
        tmp_path, monkeypatch, decisions=decisions
    )
    facade_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        facade,
        "research_knowledge_collection_facade",
        lambda **kwargs: facade_calls.append(dict(kwargs)) or {},
    )

    result = chain._process_collection_decisions(
        "team-hf-start",
        meeting,
        close_result,
        {"decisions": decisions},
    )

    assert result["requests"] == []
    assert len(result["skipped"]) == 1
    skipped = result["skipped"][0]
    assert skipped["decisionId"] == chain._decision_id_for(meeting, decisions[0])
    assert skipped["reason"] == "candidate_refs_missing"
    assert "candidateRefs" in str(skipped["error"])
    assert facade_calls == []
    assert len(scene_events) == 1
    assert (
        scene_events[0]["eventCode"]
        == "hypothesis_first.collection_decision_candidate_refs_missing"
    )
    assert scene_events[0]["outcome"] == "blocked"
    assert scene_events[0]["fields"]["decisionId"] == skipped["decisionId"]

    # Replays stay idempotent: the skipped decision leaves no request behind,
    # so a corrected closure (with candidateRefs) creates exactly one request.
    corrected = [dict(decisions[0], candidateRefs=["sci-mtz-1-c1a2b3c4"])]
    corrected_meeting, corrected_close = _process_collection_decisions_fixture(
        tmp_path, monkeypatch, decisions=corrected
    )
    corrected_result = chain._process_collection_decisions(
        "team-hf-start",
        corrected_meeting,
        corrected_close,
        {"decisions": corrected},
    )
    assert len(corrected_result["requests"]) == 1
    assert corrected_result["requests"][0]["hypothesisCandidateIds"] == [
        "sci-mtz-1-c1a2b3c4"
    ]


def test_collection_decisions_pin_workflow_run_and_question_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chain collection runs are scoped to the formal run and question project.

    The workflow run comes from the meeting's server-owned scope binding and
    the project is resolved from the question ownership — never from the
    meeting's own ``researchProjectId`` lineage field, which may still point
    at an older question's project (production: SCI-003 run bound to
    challenge-sci-002).
    """
    from core.web.services.team_workflow import research_projects

    decisions = [_collection_decision("hyp-a", "message-a")]
    meeting, close_result = _process_collection_decisions_fixture(
        tmp_path, monkeypatch, decisions=decisions
    )
    meeting["workflowRunId"] = "run-16cfab646d08"
    # The meeting lineage still carries the OLD question's project; the chain
    # must ignore it and resolve by questionId instead.
    meeting["researchProjectId"] = "challenge-sci-002"
    resolved: list[tuple[str, str]] = []

    def fake_question_project(_team_id: str, question_id: str):
        resolved.append((_team_id, question_id))
        return {"projectId": "challenge-sci-003", "challengeQuestionId": question_id}

    monkeypatch.setattr(
        research_projects,
        "get_research_project_for_question",
        fake_question_project,
    )
    facade_calls: list[dict[str, object]] = []

    def fake_facade(**kwargs):
        facade_calls.append(dict(kwargs))
        return {"locator": {"runId": "dprun-hf-start"}}

    monkeypatch.setattr(facade, "research_knowledge_collection_facade", fake_facade)
    monkeypatch.setattr(
        collection_runs,
        "start_source_collection_search_background",
        lambda team_id, run_id, payload=None: {"runId": run_id, "status": "running"},
    )

    result = chain._process_collection_decisions(
        "team-hf-start",
        meeting,
        close_result,
        {"decisions": decisions},
    )

    assert result["requests"][0]["collectionRunId"] == "dprun-hf-start"
    assert resolved == [("team-hf-start", _QUESTION_ID)]
    assert facade_calls[0]["workflowRunId"] == "run-16cfab646d08"
    assert facade_calls[0]["researchProjectId"] == "challenge-sci-003"


def test_collection_decisions_without_workflow_run_keep_legacy_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dev/legacy meetings (no formal run) keep the unscoped collection payload."""
    from core.web.services.team_workflow import research_projects

    decisions = [_collection_decision("hyp-a", "message-a")]
    meeting, close_result = _process_collection_decisions_fixture(
        tmp_path, monkeypatch, decisions=decisions
    )
    assert "workflowRunId" not in meeting

    def fail_question_project(*_args, **_kwargs):
        raise AssertionError("question binding must not be read without a formal run")

    monkeypatch.setattr(
        research_projects,
        "get_research_project_for_question",
        fail_question_project,
    )
    facade_calls: list[dict[str, object]] = []

    def fake_facade(**kwargs):
        facade_calls.append(dict(kwargs))
        return {"locator": {"runId": "dprun-hf-start"}}

    monkeypatch.setattr(facade, "research_knowledge_collection_facade", fake_facade)
    monkeypatch.setattr(
        collection_runs,
        "start_source_collection_search_background",
        lambda team_id, run_id, payload=None: {"runId": run_id, "status": "running"},
    )

    result = chain._process_collection_decisions(
        "team-hf-start",
        meeting,
        close_result,
        {"decisions": decisions},
    )

    assert result["requests"][0]["collectionRunId"] == "dprun-hf-start"
    assert facade_calls[0]["workflowRunId"] == ""
    assert facade_calls[0]["researchProjectId"] == ""


def test_recovery_binding_resolves_meeting_run_and_question_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request recovery re-derives the run scope from the linked meeting."""
    from core.web.services.team_workflow import research_projects

    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda _team_id, meeting_round_id: {
            "meetingRound": {
                "meetingRoundId": meeting_round_id,
                "question": _QUESTION_ID,
                "workflowRunId": "run-16cfab646d08",
            }
        },
    )
    monkeypatch.setattr(
        research_projects,
        "get_research_project_for_question",
        lambda _team_id, _question_id: {"projectId": "challenge-sci-003"},
    )

    binding = chain._recovery_workflow_run_binding(
        "team-hf-start",
        {"meetingRoundId": "meeting-hf-start", "questionId": _QUESTION_ID},
    )
    assert binding == ("run-16cfab646d08", "challenge-sci-003")


def test_recovery_binding_survives_missing_meeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing legacy meeting keeps recovery on the unscoped legacy payload."""
    from core.web.services.team_workflow import meeting_rounds as meetings_module

    def missing_meeting(_team_id: str, _meeting_round_id: str) -> dict:
        raise meetings_module.ResearchMeetingRoundNotFoundError("Meeting round not found.")

    monkeypatch.setattr(meetings, "get_meeting_round", missing_meeting)

    assert chain._recovery_workflow_run_binding(
        "team-hf-start", {"meetingRoundId": "meeting-gone"}
    ) == ("", "")
    # No meeting id at all short-circuits without any lookup.
    assert chain._recovery_workflow_run_binding("team-hf-start", {}) == ("", "")


def test_collection_decision_marks_request_failed_when_background_start_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decisions = [_collection_decision("hyp-a", "message-a")]
    meeting, close_result = _process_collection_decisions_fixture(
        tmp_path, monkeypatch, decisions=decisions
    )

    def fail_start(_team_id: str, _run_id: str, _payload=None) -> dict[str, object]:
        raise RuntimeError("source collection worker unavailable")

    monkeypatch.setattr(
        collection_runs, "start_source_collection_search_background", fail_start
    )

    result = chain._process_collection_decisions(
        "team-hf-start",
        meeting,
        close_result,
        {"decisions": decisions},
    )

    request = result["requests"][0]
    assert request["status"] == "failed"
    assert request["collectionRunStatus"] == "failed"
    assert request["startError"] == {
        "code": "search_start_failed",
        "message": "source collection worker unavailable",
    }


def test_collection_facade_accepts_nested_start_response(monkeypatch) -> None:
    scope_fields = _scope_fields("agent-nested")
    scope_hash = scope_hash_for(
        **{field: scope_fields[field] for field in chain._SCOPE_FIELDS},
        agent_id=scope_fields["agentId"],
        mode=scope_fields["mode"],
    )
    scope = {
        **scope_fields,
        "scopeHash": scope_hash,
        "artifactLocator": f"research-artifact://test/{scope_hash}",
        "ledgerRoot": f"research-ledger://test/{scope_hash}",
        "cacheKey": f"scope:{scope_hash}:main:agent-nested",
    }
    monkeypatch.setattr(facade, "_find_existing_run", lambda *_args: None)
    monkeypatch.setattr(
        facade,
        "_create_collection_run",
        lambda *_args: {"run": {"runId": "nested-child-1"}},
    )
    monkeypatch.setattr(
        facade,
        "_load_distilled_summary",
        lambda _team_id, run_id: {"status": "queued", "runId": run_id},
    )

    result = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=scope,
        searchEnvelope={"keywords": ["nested response"]},
        team_id="team-nested",
    )

    assert result["created"] is True
    assert result["locator"]["runId"] == "nested-child-1"


def test_collection_request_recovery_reuses_child_run_without_resetting_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    scope_fields = _scope_fields(agents["coordinator"])
    scope_hash = scope_hash_for(
        **{field: scope_fields[field] for field in chain._SCOPE_FIELDS},
        agent_id=scope_fields["agentId"],
        mode=scope_fields["mode"],
    )
    request_id = "hfcr-orphan-recovery"
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.COLLECTION_REQUEST_KIND,
            "requestId": request_id,
            "requestHash": "request-hash",
            "status": "failed",
            "meetingRoundId": "meeting-recovery",
            "decisionId": "decision-recovery",
            "questionId": _QUESTION_ID,
            **scope_fields,
            "scopeHash": scope_hash,
            "searchEnvelope": {"keywords": ["recovery evidence"]},
            "requirements": {"completeness": "bounded"},
            "writebackPolicy": {"networkExecution": False},
            "collectionRunId": "",
            "collectionRunStatus": "failed",
            "startError": {"code": "collection_run_missing"},
            "createdAt": "2026-08-22T00:00:00Z",
        },
    )
    facade_calls: list[dict] = []
    child_runs: set[str] = set()
    started: list[dict[str, object]] = []

    def fake_ensure(**kwargs):
        facade_calls.append(kwargs)
        child_runs.add("child-recovered")
        return {"locator": {"runId": "child-recovered"}, "created": False}

    monkeypatch.setattr(facade, "research_knowledge_collection_facade", fake_ensure)
    def fake_background(_team_id, run_id, _payload=None):
        started.append({"runId": run_id, "payload": dict(_payload or {})})
        time.sleep(0.02)
        return {"runId": run_id, "status": "running"}

    monkeypatch.setattr(collection_runs, "start_source_collection_search_background", fake_background)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(chain.recover_collection_request, team_id, request_id)
            for _ in range(2)
        ]
        first, second = (future.result() for future in futures)

    assert first["request"]["collectionRunId"] == "child-recovered"
    assert second["request"]["collectionRunId"] == "child-recovered"
    assert first["status"] == "recovered"
    assert second["status"] == "reused"
    assert child_runs == {"child-recovered"}
    assert started == [
        {
            "runId": "child-recovered",
            "payload": {"backgroundExecution": True, "maxQueries": 12},
        }
    ]
    assert [call["searchEnvelope"]["keywords"] for call in facade_calls] == [["recovery evidence"]]
    third = chain.recover_collection_request(team_id, request_id)
    assert third["status"] == "reused"
    assert started == [
        {
            "runId": "child-recovered",
            "payload": {"backgroundExecution": True, "maxQueries": 12},
        }
    ]
    records = chain._collection_requests(chain._records(team_id))
    assert len([record for record in records if record["requestId"] == request_id]) == 1


# ---------------------------------------------------------------------------
# failed collection auto-retry (bounded self-healing) and exhaustion escalation


_AUTO_RETRY_ERROR_HINT = "background worker crashed (fixture)"


def _auto_retry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Standard chain env plus a deterministic failed-run error hint.

    The hint patch keeps the auto-retry path from reading the machine-global
    work-run store, so the tests stay hermetic.
    """
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        chain, "_failed_collection_run_error_hint", lambda run_id: _AUTO_RETRY_ERROR_HINT
    )
    return team_id, agents


def _seed_auto_retry_request(
    team_id: str,
    agents: dict[str, str],
    *,
    request_id: str,
    run_id: str,
    run_status: str = "running",
) -> None:
    scope_fields = _scope_fields(agents["coordinator"])
    scope_hash = scope_hash_for(
        **{field: scope_fields[field] for field in chain._SCOPE_FIELDS},
        agent_id=scope_fields["agentId"],
        mode=scope_fields["mode"],
    )
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.COLLECTION_REQUEST_KIND,
            "requestId": request_id,
            "requestHash": f"hash-{request_id}",
            "status": "pending",
            "meetingRoundId": "meeting-auto-retry",
            "decisionId": f"decision-{request_id}",
            "questionId": _QUESTION_ID,
            **scope_fields,
            "scopeHash": scope_hash,
            "searchEnvelope": {"keywords": ["auto retry evidence"]},
            "requirements": {"completeness": "bounded"},
            "writebackPolicy": {"networkExecution": False},
            "collectionRunId": run_id,
            "collectionRunStatus": run_status,
            "startError": {},
            "createdAt": "2026-08-30T00:00:00Z",
        },
    )


def _capture_auto_retry_timer(
    monkeypatch: pytest.MonkeyPatch, *, run_inline: bool = False
) -> list[dict[str, object]]:
    """Capture the backoff scheduling seam; optionally dispatch inline."""
    scheduled: list[dict[str, object]] = []

    def fake_timer(delay_seconds: float, callback) -> None:
        scheduled.append({"delaySeconds": float(delay_seconds), "callback": callback})
        if run_inline:
            callback()

    monkeypatch.setattr(chain, "_start_collection_auto_retry_timer", fake_timer)
    return scheduled


def _patch_collection_restart(
    monkeypatch: pytest.MonkeyPatch,
    *,
    child_run_id: str = "child-auto-retry",
    fail: bool = False,
):
    """Patch the facade ensure plus background start the recover path uses."""
    ensures: list[dict[str, object]] = []
    starts: list[dict[str, object]] = []

    def fake_ensure(**kwargs):
        ensures.append(dict(kwargs))
        if fail:
            raise RuntimeError("facade unavailable (fixture)")
        return {"locator": {"runId": child_run_id}, "created": False}

    monkeypatch.setattr(facade, "research_knowledge_collection_facade", fake_ensure)

    def fake_start(team_id: str, run_id: str, payload=None):
        starts.append({"runId": run_id, "payload": dict(payload or {})})
        return {"runId": run_id, "status": "running"}

    monkeypatch.setattr(
        collection_runs, "start_source_collection_search_background", fake_start
    )
    return ensures, starts


def _latest_auto_retry_request(team_id: str, request_id: str) -> dict[str, object]:
    return chain._latest_by_id(
        chain._collection_requests(chain._records(team_id)),
        "requestId",
        request_id,
    )


def test_failed_collection_run_schedules_one_backoff_auto_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _auto_retry_env(tmp_path, monkeypatch)
    request_id, run_id = "hfcr-auto-first", "dprun-auto-first"
    _seed_auto_retry_request(team_id, agents, request_id=request_id, run_id=run_id)
    scheduled = _capture_auto_retry_timer(monkeypatch)
    ensures, starts = _patch_collection_restart(monkeypatch)

    result = chain.notify_collection_run_terminal(team_id, run_id, "failed")

    assert result["status"] == "collection_recovery"
    request = _latest_auto_retry_request(team_id, request_id)
    assert request["collectionRunStatus"] == "failed"
    auto_retry = request["autoRetry"]
    assert auto_retry["phase"] == "backoff"
    assert auto_retry["attemptCount"] == 1
    assert auto_retry["lastError"] == _AUTO_RETRY_ERROR_HINT
    assert auto_retry["nextRetryAt"]
    assert [entry["delaySeconds"] for entry in scheduled] == [30.0]
    # exponential schedule: 30s, 60s, then capped at 120s
    assert chain._collection_auto_retry_delay_seconds(0) == 30.0
    assert chain._collection_auto_retry_delay_seconds(1) == 60.0
    assert chain._collection_auto_retry_delay_seconds(2) == 120.0
    assert chain._collection_auto_retry_delay_seconds(9) == 120.0

    # the timer callback runs the same in-process recover implementation
    scheduled[0]["callback"]()
    assert len(ensures) == 1
    assert starts and starts[0]["runId"] == "child-auto-retry"
    request = _latest_auto_retry_request(team_id, request_id)
    assert request["status"] == "pending"
    assert request["collectionRunStatus"] == "running"
    assert request["autoRetry"]["phase"] == "dispatched"
    assert request["autoRetry"]["attemptCount"] == 1


def test_failed_collection_run_replay_does_not_double_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _auto_retry_env(tmp_path, monkeypatch)
    request_id, run_id = "hfcr-auto-replay", "dprun-auto-replay"
    _seed_auto_retry_request(team_id, agents, request_id=request_id, run_id=run_id)
    scheduled = _capture_auto_retry_timer(monkeypatch)
    # the idempotent facade re-binds the same child run on recover, so the
    # request stays bound to the same run id across retries
    _patch_collection_restart(monkeypatch, child_run_id=run_id)

    chain.notify_collection_run_terminal(team_id, run_id, "failed")
    # replays of the same failed terminal event while the retry is scheduled
    chain.notify_collection_run_terminal(team_id, run_id, "failed")
    chain.notify_collection_run_terminal(team_id, run_id, "failed")

    assert [entry["delaySeconds"] for entry in scheduled] == [30.0]
    request = _latest_auto_retry_request(team_id, request_id)
    assert request["autoRetry"]["attemptCount"] == 1
    assert request["autoRetry"]["phase"] == "backoff"

    # a failure after the dispatched retry is a new event: it consumes the
    # second budget slot with the next backoff step
    scheduled[0]["callback"]()
    chain.notify_collection_run_terminal(team_id, run_id, "failed")

    assert [entry["delaySeconds"] for entry in scheduled] == [30.0, 60.0]
    request = _latest_auto_retry_request(team_id, request_id)
    assert request["autoRetry"]["attemptCount"] == 2
    assert request["autoRetry"]["phase"] == "backoff"


def test_auto_retry_exhaustion_emits_inbox_and_keeps_manual_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _auto_retry_env(tmp_path, monkeypatch)
    request_id, run_id = "hfcr-auto-exhaust", "dprun-auto-exhaust"
    _seed_auto_retry_request(team_id, agents, request_id=request_id, run_id=run_id)
    scheduled = _capture_auto_retry_timer(monkeypatch, run_inline=True)
    _patch_collection_restart(monkeypatch, child_run_id=run_id)

    # failure 1 -> retry 1; failure 2 -> retry 2; failure 3 -> exhausted
    chain.notify_collection_run_terminal(team_id, run_id, "failed")
    chain.notify_collection_run_terminal(team_id, run_id, "failed")
    result = chain.notify_collection_run_terminal(team_id, run_id, "failed")

    assert [entry["delaySeconds"] for entry in scheduled] == [30.0, 60.0]
    assert [entry["escalation"]["attempts"] for entry in result["autoRetryEscalations"]] == [2]
    request = _latest_auto_retry_request(team_id, request_id)
    # the request keeps its failed recovery state (manual recover untouched)
    assert request["status"] == "pending"
    assert request["collectionRunStatus"] == "failed"
    assert request["autoRetry"]["phase"] == "exhausted"
    assert request["autoRetry"]["attemptCount"] == 2
    assert request["autoRetry"]["exhaustedAt"]

    escalation = request["anomalyEscalation"]
    assert escalation["status"] == "emitted"
    assert escalation["taxonomyCode"] == "collection_auto_retry_exhausted"
    assert escalation["requestId"] == request_id
    assert escalation["attempts"] == 2
    assert escalation["lastError"] == _AUTO_RETRY_ERROR_HINT
    items = escalation["items"]
    assert len(items) == 1
    item = items[0]
    assert item["kind"] == "blocked_run"
    assert item["recommendedAction"] == "retry_node"
    assert request_id in item["summary"]
    assert "2/2" in item["summary"]
    assert _AUTO_RETRY_ERROR_HINT in item["summary"]
    assert f"source:collection_request:{request_id}" in item["evidence"]

    # exactly-once: another exhausted terminal event does not re-emit
    chain.notify_collection_run_terminal(team_id, run_id, "failed")
    request = _latest_auto_retry_request(team_id, request_id)
    assert request["anomalyEscalation"]["emittedAt"] == escalation["emittedAt"]

    # the human recover endpoint still works and refreshes the budget
    recovered = chain.recover_collection_request(team_id, request_id)
    assert recovered["status"] in {"recovered", "reused"}
    request = _latest_auto_retry_request(team_id, request_id)
    assert request["collectionRunStatus"] == "running"
    assert request["autoRetry"] == {}


def test_needs_continue_never_triggers_auto_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _auto_retry_env(tmp_path, monkeypatch)
    request_id, run_id = "hfcr-auto-needs-continue", "dprun-auto-continue"
    _seed_auto_retry_request(team_id, agents, request_id=request_id, run_id=run_id)
    scheduled = _capture_auto_retry_timer(monkeypatch)

    result = chain.notify_collection_run_terminal(team_id, run_id, "needs_continue")

    # red line: needs_continue stays fatal and is never auto-reconciled
    assert result["status"] == "collection_recovery"
    request = _latest_auto_retry_request(team_id, request_id)
    assert request["collectionRunStatus"] == "needs_continue"
    assert "autoRetry" not in request
    assert scheduled == []

    result = chain.notify_collection_run_terminal(team_id, run_id, "cancelled")
    request = _latest_auto_retry_request(team_id, request_id)
    assert result["status"] == "collection_recovery"
    assert request["status"] == "failed"
    assert request["collectionRunStatus"] == "cancelled"
    assert scheduled == []


def test_auto_retried_collection_completes_through_normal_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _auto_retry_env(tmp_path, monkeypatch)
    request_id, run_id = "hfcr-auto-handoff", "dprun-auto-handoff"
    _seed_auto_retry_request(team_id, agents, request_id=request_id, run_id=run_id)
    _capture_auto_retry_timer(monkeypatch, run_inline=True)
    _patch_collection_restart(monkeypatch, child_run_id=run_id)
    meetings_opened: list[dict[str, object]] = []

    def fake_open_next_meeting(
        opened_team_id: str,
        *,
        previous_meeting_round_id: str,
        collection_request_id: str,
        agent_runner=None,
        background=True,
        budget=None,
        fan_out_selection=False,
    ):
        meetings_opened.append(
            {
                "teamId": opened_team_id,
                "previousMeetingRoundId": previous_meeting_round_id,
                "collectionRequestId": collection_request_id,
                "fanOutSelection": fan_out_selection,
            }
        )
        return {"meetingRoundId": "meeting-next"}

    monkeypatch.setattr(chain, "open_next_review_meeting", fake_open_next_meeting)

    # failure -> automatic retry restarts the child run
    chain.notify_collection_run_terminal(team_id, run_id, "failed")
    request = _latest_auto_retry_request(team_id, request_id)
    assert request["autoRetry"]["phase"] == "dispatched"
    assert request["collectionRunStatus"] == "running"

    # the restarted run completes: the untouched completed path hands off
    result = chain.notify_collection_run_terminal(team_id, run_id, "completed")

    assert result["status"] == "handed_off"
    request = _latest_auto_retry_request(team_id, request_id)
    assert request["status"] == "handed_off"
    assert request["collectionRunStatus"] == "completed"
    assert request["handoffRef"] == f"source_collection_run:{run_id}"
    assert meetings_opened == [
        {
            "teamId": team_id,
            "previousMeetingRoundId": "meeting-auto-retry",
            "collectionRequestId": request_id,
            "fanOutSelection": True,
        }
    ]


def test_completed_collection_handoff_path_unchanged_without_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _auto_retry_env(tmp_path, monkeypatch)
    request_id, run_id = "hfcr-auto-completed", "dprun-auto-completed"
    _seed_auto_retry_request(team_id, agents, request_id=request_id, run_id=run_id)
    scheduled = _capture_auto_retry_timer(monkeypatch)
    _patch_collection_restart(monkeypatch)
    meetings_opened: list[dict[str, object]] = []

    def fake_open_next_meeting(
        opened_team_id: str,
        *,
        previous_meeting_round_id: str,
        collection_request_id: str,
        agent_runner=None,
        background=True,
        budget=None,
        fan_out_selection=False,
    ):
        meetings_opened.append(
            {
                "collectionRequestId": collection_request_id,
                "fanOutSelection": fan_out_selection,
            }
        )
        return {"meetingRoundId": "meeting-next"}

    monkeypatch.setattr(chain, "open_next_review_meeting", fake_open_next_meeting)

    result = chain.notify_collection_run_terminal(team_id, run_id, "completed")

    # regression: the pristine completed path behaves exactly as before
    assert result["status"] == "handed_off"
    assert scheduled == []
    assert "autoRetryEscalations" not in result
    request = _latest_auto_retry_request(team_id, request_id)
    assert request["status"] == "handed_off"
    assert request["collectionRunStatus"] == "completed"
    assert request["handoffError"] == {}
    assert "autoRetry" not in request
    assert meetings_opened == [
        {"collectionRequestId": request_id, "fanOutSelection": True}
    ]


def test_auto_retry_dispatch_failure_consumes_budget_and_escalates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _auto_retry_env(tmp_path, monkeypatch)
    request_id, run_id = "hfcr-auto-dispatch-fail", "dprun-auto-dispatch-fail"
    _seed_auto_retry_request(team_id, agents, request_id=request_id, run_id=run_id)
    scheduled = _capture_auto_retry_timer(monkeypatch, run_inline=True)
    _patch_collection_restart(monkeypatch, child_run_id=run_id, fail=True)

    # each failed dispatch consumes one budget slot and chains the next
    # backoff attempt, so persistent recover failures still terminate in the
    # escalation instead of stopping silently
    chain.notify_collection_run_terminal(team_id, run_id, "failed")

    assert [entry["delaySeconds"] for entry in scheduled] == [30.0, 60.0]
    request = _latest_auto_retry_request(team_id, request_id)
    assert request["autoRetry"]["phase"] == "exhausted"
    assert request["autoRetry"]["attemptCount"] == 2
    assert request["autoRetry"]["lastError"] == "facade unavailable (fixture)"
    assert "facade unavailable (fixture)" in request["anomalyEscalation"]["lastError"]
    assert request["anomalyEscalation"]["status"] == "emitted"
    assert request["anomalyEscalation"]["items"][0]["summary"].count(
        "facade unavailable (fixture)"
    ) == 1
    assert request["collectionRunStatus"] == "failed"


def _seed_question_reset_artifacts(team_id: str, question_id: str) -> dict[str, str]:
    """Seed only the durable hypothesis-first artifacts owned by one question."""
    suffix = question_id.lower()
    meeting_id = f"meeting-{suffix}"
    selection_id = f"selection-{suffix}"
    candidate_id = f"candidate-{suffix}"
    round_id = f"round-{suffix}"
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.CANDIDATE_KIND,
            "candidateId": candidate_id,
            "questionId": question_id,
            "statement": f"{question_id} candidate",
            "meetingRoundId": meeting_id,
        },
    )
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.COLLECTION_REQUEST_KIND,
            "requestId": f"request-{suffix}",
            "questionId": question_id,
            "meetingRoundId": meeting_id,
            "status": "completed",
        },
    )
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.REVIEW_ROUND_LINK_KIND,
            "linkId": f"link-{suffix}",
            "questionId": question_id,
            "meetingRoundId": meeting_id,
            "selectionId": selection_id,
            "roundIndex": 1,
        },
    )
    selections._append_jsonl(
        selections._storage_path(team_id),
        {"schemaVersion": 1, "selectionId": selection_id, "questionId": question_id},
    )
    meetings._append_jsonl(
        meetings._rounds_path(team_id),
        {
            "schemaVersion": 2,
            "meetingRoundId": meeting_id,
            "question": question_id,
            "meetingType": "hypothesis_review",
            "status": "closed",
        },
    )
    meetings._append_jsonl(
        meetings._digests_path(team_id),
        {"schemaVersion": 2, "digestId": f"digest-{suffix}", "meetingRoundId": meeting_id},
    )
    meetings._append_jsonl(
        meetings._decisions_path(team_id),
        {"schemaVersion": 2, "decisionId": f"decision-{suffix}", "meetingRoundId": meeting_id},
    )
    hrounds._append_jsonl(
        hrounds._storage_path(team_id),
        {
            "schemaVersion": 1,
            "roundId": round_id,
            "status": "closed",
            "meetingRefs": [{"kind": "meeting_round", "id": meeting_id}],
        },
    )
    return {
        "candidateId": candidate_id,
        "meetingId": meeting_id,
        "roundId": round_id,
        "selectionId": selection_id,
    }


def test_question_reset_clears_only_the_target_questions_closed_hypothesis_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    target = _seed_question_reset_artifacts(team_id, _QUESTION_ID)
    other = _seed_question_reset_artifacts(team_id, "SCI-097")

    preview = chain.preview_question_reset(team_id, _QUESTION_ID)

    assert preview["canReset"] is True
    assert preview["impact"] == {
        "candidateCount": 1,
        "selectionCount": 1,
        "meetingCount": 1,
        "hypothesisRoundCount": 1,
        "collectionRequestCount": 1,
        "collectionRunCount": 0,
    }

    result = chain.reset_question_chain(
        team_id,
        _QUESTION_ID,
        confirmation_question_id=_QUESTION_ID,
    )

    assert result["removed"] == preview["impact"]
    assert result["nextAction"] == {
        "targetNodeId": "hf_generation",
        "label": "生成候选假说",
    }
    assert chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)["candidates"] == []
    assert selections.list_hypothesis_selections(team_id, question_id=_QUESTION_ID)["selections"] == []
    assert chain.list_collection_requests(team_id, question_id=_QUESTION_ID)["requests"] == []
    assert [item["meetingRoundId"] for item in meetings.list_meeting_rounds(team_id)["meetings"]] == [other["meetingId"]]
    assert [item["roundId"] for item in hrounds.list_hypothesis_rounds(team_id)["rounds"]] == [other["roundId"]]

    assert chain.list_hypothesis_candidates(team_id, question_id="SCI-097")["candidates"][0]["candidateId"] == other["candidateId"]
    assert selections.list_hypothesis_selections(team_id, question_id="SCI-097")["selections"][0]["selectionId"] == other["selectionId"]
    assert target["meetingId"] != other["meetingId"]
    assert target["roundId"] != other["roundId"]


def test_question_reset_refuses_active_discussion_and_mismatched_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    target = _seed_question_reset_artifacts(team_id, _QUESTION_ID)
    meetings._append_jsonl(
        meetings._rounds_path(team_id),
        {
            "schemaVersion": 2,
            "meetingRoundId": target["meetingId"],
            "question": _QUESTION_ID,
            "meetingType": "hypothesis_review",
            "status": "open",
        },
    )

    preview = chain.preview_question_reset(team_id, _QUESTION_ID)

    assert preview["canReset"] is False
    assert "进行中的讨论" in preview["blockingReason"]
    with pytest.raises(chain.HypothesisFirstChainError, match="进行中的讨论"):
        chain.reset_question_chain(
            team_id,
            _QUESTION_ID,
            confirmation_question_id=_QUESTION_ID,
        )
    with pytest.raises(chain.HypothesisFirstChainError, match="输入当前题号"):
        chain.reset_question_chain(
            team_id,
            _QUESTION_ID,
            confirmation_question_id="SCI-097",
        )
    assert chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)["candidates"]


def test_question_reset_refuses_pending_collection_request_with_child_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pending request remains protected when it still identifies child work."""

    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    _seed_question_reset_artifacts(team_id, _QUESTION_ID)
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.COLLECTION_REQUEST_KIND,
            "requestId": "request-live-child-run",
            "questionId": _QUESTION_ID,
            "status": "pending",
            "collectionRunId": "source-run-live-child",
        },
    )

    preview = chain.preview_question_reset(team_id, _QUESTION_ID)

    assert preview["canReset"] is False
    assert "资料搜集仍在进行" in preview["blockingReason"]
    with pytest.raises(chain.HypothesisFirstChainError, match="资料搜集仍在进行"):
        chain.reset_question_chain(
            team_id,
            _QUESTION_ID,
            confirmation_question_id=_QUESTION_ID,
        )


def test_question_reset_keeps_source_collection_untouched_if_ledger_rewrite_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    _seed_question_reset_artifacts(team_id, _QUESTION_ID)
    source_cleanup_calls: list[set[str]] = []

    def should_not_run_source_cleanup(_team_id: str, run_ids: set[str]) -> dict[str, object]:
        source_cleanup_calls.append(set(run_ids))
        return {}

    monkeypatch.setattr(
        collection_runs,
        "reset_source_collection_runs_for_question",
        should_not_run_source_cleanup,
    )
    monkeypatch.setattr(
        chain,
        "_rewrite_jsonl",
        lambda _path, _records: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(chain.HypothesisFirstChainError, match="原数据已尝试恢复"):
        chain.reset_question_chain(
            team_id,
            _QUESTION_ID,
            confirmation_question_id=_QUESTION_ID,
        )

    assert source_cleanup_calls == []
    assert chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)["candidates"]


def test_question_reset_restores_hypothesis_records_if_source_cleanup_late_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    _seed_question_reset_artifacts(team_id, _QUESTION_ID)

    def late_source_blocker(_team_id: str, _run_ids: set[str]) -> dict[str, object]:
        raise ValueError("资料运行状态已变化")

    monkeypatch.setattr(
        collection_runs,
        "reset_source_collection_runs_for_question",
        late_source_blocker,
    )

    with pytest.raises(ValueError, match="资料运行状态已变化"):
        chain.reset_question_chain(
            team_id,
            _QUESTION_ID,
            confirmation_question_id=_QUESTION_ID,
        )

    assert chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)["candidates"]


def _build_runtime(tmp_path: Path):
    return build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "checkpoints.sqlite",
        domain_overrides={
            "knowledge_package": lambda team_id, run_id: {
                "teamId": team_id,
                "sourceCollectionRunId": "dprun-hf4-1",
                "accepted": True,
                "knowledgeItems": [{"knowledgeItemId": "ki-1", "contentHash": "b" * 64}],
            },
        },
    )


def _seed_parent_run(runtime, team_id: str, planner_agent_id: str) -> None:
    input_snapshot = {
        "teamId": team_id,
        "projectId": "challenge-sci-096",
        "questionId": _QUESTION_ID,
        "workflowVersionId": "challenge-cup-research-v2.1.0",
        "researchBriefHash": "b" * 64,
        "datasetRefs": [],
        "metricContract": {},
        "constraintSnapshot": {},
        "competitionRuleRef": "rule",
        "competitionRuleVersion": "1",
        "trackAndRubricSnapshot": {},
        "researchObjectiveContract": {
            "question": "How do spike trains encode information?",
            "hypothesisFirst": True,
        },
        "sourcePolicy": {},
        "budgetPolicy": {
            "stageBudgets": {
                "knowledge_collection": {"tokens": 250000, "toolCalls": 300},
                "experiment_design": {"tokens": 250000, "toolCalls": 300},
            }
        },
        "stopPolicy": {},
        "environmentSnapshotRef": "env-1",
        "modelRoutingPolicy": {"modelPolicySha256": "d" * 64},
        "evaluationContract": {},
        "agentBindingSnapshot": [
            {
                "snapshotId": "snap:hf4:source_finding",
                "nodeId": "source_finding",
                "agentId": planner_agent_id,
                "roleKey": "source_finder",
            },
            {
                "snapshotId": "snap:hf4:hypothesis_design",
                "nodeId": "hypothesis_design",
                "agentId": planner_agent_id,
                "roleKey": "experiment_planner",
            },
        ],
        "createdBy": "u-1",
        "createdAt": "2026-08-18T00:00:00Z",
        "snapshotHash": "c" * 64,
    }
    # Registry-era runs must pin a registered wv-* identity: the T2
    # definition registry fails closed on the legacy non-empty literal, and
    # the meeting receipt authority requires a non-empty version id. Register
    # the built-in definition and pin the run to that identity.
    from core.research.workflow.definition import build_challenge_cup_workflow_definition
    from core.research.workflow.definition_registry import register_or_resolve

    pinned_version_id = register_or_resolve(
        build_challenge_cup_workflow_definition()
    ).workflowVersionId
    record = build_run_record(
        run_id=_RUN_ID,
        team_id=team_id,
        workflow_version_id=pinned_version_id,
        last_event_sequence=1,
        input_snapshot_hash="c" * 64,
        thread_id=_RUN_ID,
    )
    record = record.__class__(
        **{
            **record.__dict__,
            "project_id": "challenge-sci-096",
            "question_id": _QUESTION_ID,
            "input_snapshot_json": json.dumps(input_snapshot, ensure_ascii=False),
        }
    )

    def mutate(uow):
        uow.repository.insert_run(record)
        uow.repository.insert_event(
            build_event_record(
                sequence=1,
                run_id=_RUN_ID,
                event_type="run_created",
                event_id="evt-created-hf4",
            )
        )
        # The parent's own knowledge gate already completed upstream: a
        # succeeded knowledge_handoff attempt plus an accepted handoff into
        # hypothesis_design exist in the ledger.
        uow.repository.insert_command(
            build_command_record(
                "cmd-hf4-knowledge",
                run_id=_RUN_ID,
                team_id=team_id,
                node_id="knowledge_handoff",
                command_kind="resolve_human_task",
                idempotency_key="hf4:seed-knowledge",
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                "nr-hf4-knowledge_handoff-a1",
                run_id=_RUN_ID,
                node_id="knowledge_handoff",
                actor_kind="human",
                status="succeeded",
                command_id="cmd-hf4-knowledge",
            )
        )
        uow.repository.insert_handoff(
            handoff_id="ho-hf4-knowledge",
            run_id=_RUN_ID,
            edge_id="knowledge_handoff->hypothesis_design",
            from_node_run_id="nr-hf4-knowledge_handoff-a1",
            to_node_id="hypothesis_design",
            to_node_run_id=None,
            gate_kind="knowledge_package",
            input_snapshot_hash="c" * 64,
            offered_at_ms=_FIXED_NOW_MS,
        )
        uow.repository.update_handoff_status(
            "ho-hf4-knowledge", "waiting_human", _FIXED_NOW_MS + 1
        )
        uow.repository.update_handoff_status(
            "ho-hf4-knowledge", "accepted", _FIXED_NOW_MS + 2
        )

    runtime.store.submit(mutate, force_flush=True).result(timeout=10)


def _evaluate(runtime, team_id: str, node_id: str):
    return runtime.readiness.evaluate(
        team_id=team_id,
        run_id=_RUN_ID,
        node_id=node_id,
        context=runtime.readiness_context,
        use_cache=False,
    )


def _blocker_codes(readiness) -> set[str]:
    return {blocker.code for blocker in readiness.blockers}


def _envelope_decision(agent_id: str, **overrides) -> dict:
    decision = {
        "decision": "request_new_evidence",
        "rationale": "hyp-b 的泛化证据不足，需要按信封补充搜集。",
        "decidedBy": agent_id,
        "candidateRefs": ["hyp-b"],
        "evidenceRefs": ["evidence:review-matrix-1"],
        "status": "adopted",
        "searchEnvelope": {
            "keywords": ["predictive coding", "spike train coding"],
            "sourceTypes": ["paper"],
            "evidenceLevels": ["peer_reviewed"],
        },
        "requirements": {"minEvidenceLevel": "medium", "completeness": "stage-one"},
        "writebackPolicy": {},
    }
    decision.update(overrides)
    return decision


def _select_decision(agent_id: str, **overrides) -> dict:
    decision = {
        "decision": "select_candidate",
        "rationale": "hyp-a 证据最完整，收敛进入实验设计。",
        "decidedBy": agent_id,
        "candidateRefs": ["hyp-a"],
        "evidenceRefs": ["evidence:review-matrix-2"],
        "status": "adopted",
    }
    decision.update(overrides)
    return decision


def _closure_payload(agent_ids: list[str], decisions: list[dict], **overrides) -> dict:
    payload = {
        "decisions": decisions,
        "closedBy": agent_ids[0],
        "memorySummaries": {agent_id: f"{agent_id} 的评审记忆" for agent_id in agent_ids},
        "memoryClass": "lesson",
        "reusePolicy": "reusable_same_scope",
        "evidenceStatus": "reported",
    }
    payload.update(overrides)
    return payload


def _drive_to_awaiting_approval(team_id: str, meeting_round_id: str, actor: str) -> None:
    drafted = meeting_runtime.prepare_meeting_summary_draft(
        team_id, meeting_round_id, actor=actor, force=False
    )
    assert drafted["status"] == "awaiting_approval"


def _freeze_template_baseline(team_id: str, agent_id: str) -> dict:
    created = templates.create_template_baseline(
        team_id,
        {
            **_scope_fields(agent_id),
            "templateId": "hypothesis-design-template",
            "approvedBy": agent_id,
            "approvalRef": "approval:hf4-template-1",
            "content": {"sections": ["claim", "variables", "falsification"]},
        },
    )
    assert created["baseline"]["status"] == "frozen"
    return created["baseline"]


def _open_first_meeting(team_id: str, agent_ids: list[str]) -> dict:
    recorded = selections.record_hypothesis_selection(
        team_id,
        _selection_payload(agent_ids[0]),
        agent_runner=_marker_runner,
    )
    assert recorded["status"] == "created"
    review = recorded["reviewMeeting"]
    assert review["status"] in {"opened", "created", "reused"}, review
    return recorded


def _opened_review_meetings(review: dict) -> list[dict]:
    siblings = list(review.get("reviewMeetings") or [])
    if siblings:
        return [dict(item["meetingRound"]) for item in siblings]
    return [dict(review["meetingRound"])]


def _review_meetings(recorded: dict) -> list[dict]:
    return _opened_review_meetings(recorded["reviewMeeting"])


def test_selection_review_prompt_hydrates_canonical_candidate_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(
        monkeypatch,
        hypotheses=[
            {
                "hypothesis_id": "hyp-a",
                "statement": "canonical statement a",
                "mechanism": "canonical mechanism a",
            },
            {
                "hypothesis_id": "hyp-b",
                "statement": "canonical statement b",
                "mechanism": "canonical mechanism b",
            },
        ],
    )
    prompts: list[str] = []

    def capture_runner(participant, prompt, context):
        prompts.append(str(prompt))
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}

    recorded = selections.record_hypothesis_selection(
        team_id,
        _selection_payload(agents["coordinator"]),
        agent_runner=capture_runner,
    )

    assert recorded["reviewMeeting"]["status"] == "opened"
    assert prompts
    prompts_for_a = [prompt for prompt in prompts if "canonical statement a" in prompt]
    prompts_for_b = [prompt for prompt in prompts if "canonical statement b" in prompt]
    assert prompts_for_a
    assert prompts_for_b
    assert all("canonical mechanism a" in prompt for prompt in prompts_for_a)
    assert all("canonical statement b" not in prompt for prompt in prompts_for_a)
    assert all("canonical mechanism b" in prompt for prompt in prompts_for_b)
    assert all("canonical statement a" not in prompt for prompt in prompts_for_b)


def test_preformal_fanout_binds_each_candidate_before_sibling_rounds_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A busy first review room must not prevent its sibling from opening."""

    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    executor = _DeferredExecutor()
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", executor)

    try:
        recorded = selections.record_hypothesis_selection(
            team_id,
            _selection_payload(agents["coordinator"]),
            agent_runner=_marker_runner,
        )
        meetings = _review_meetings(recorded)
        links = chain.list_review_round_links(team_id, question_id=_QUESTION_ID)["links"]

        assert len(meetings) == 2
        assert len(links) == 2
        assert {link["candidateId"] for link in links} == {"hyp-a", "hyp-b"}
        assert {link["meetingRoundId"] for link in links} == {
            meeting["meetingRoundId"] for meeting in meetings
        }
        room_ids = {str(meeting["linkedChatRoomId"]) for meeting in meetings}
        assert len(room_ids) == 2
        assert all(meeting["chatRoomRoundIds"] for meeting in meetings)
        for room_id in room_ids:
            meeting_for_room = next(
                item for item in meetings if item["linkedChatRoomId"] == room_id
            )
            room = chat_room_service.get_chat_room_detail(room_id)
            assert room is not None
            assert room["config"]["source"] == "hypothesis_first_candidate_review.v1"
            assert room["config"]["teamId"] == team_id
            assert room["config"]["scopeAuthority"] == "preformal_candidate_review_scope.v1"
            assert room["config"]["discussionScope"]["kind"] == "preformal_candidate_review"
            assert room["config"]["discussionScopeHash"] == room["config"]["scopeHash"]
            opening_round = next(
                item
                for item in room["rounds"]
                if item.get("roundId") in set(meeting_for_room["chatRoomRoundIds"])
            )
            assert opening_round["config"]["scopeAuthority"] == (
                "preformal_candidate_review_scope.v1"
            )
            expected_roles = {
                str(item["agentId"]): str(item["observedRole"])
                for item in meetings[0]["participantRoleSnapshot"]
            }
            assert {
                str(participant["agentId"]): participant.get("teamRole")
                for participant in room["participants"]
            } == expected_roles
        assert all(
            meeting["discussionScope"]["kind"] == "preformal_candidate_review"
            for meeting in meetings
        )
        assert all(
            meeting["discussionScopeHash"]
            == chat_room_service.get_chat_room_detail(meeting["linkedChatRoomId"])["config"]["scopeHash"]
            for meeting in meetings
        )
        assert len(executor.submitted) == 2
    finally:
        executor.drain()


def test_preformal_fanout_persists_siblings_while_kernel_trace_is_slow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow trace may delay workers but must not hold up sibling room creation."""

    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    trace_started = threading.Event()
    release_trace = threading.Event()
    selection_finished = threading.Event()
    recorded: dict[str, object] = {}
    errors: list[BaseException] = []

    from core.agent_kernel import service as agent_kernel_service

    def slow_kernel_trace(_event_payload):
        trace_started.set()
        assert release_trace.wait(timeout=60), "test must release the background trace"
        return {"event": {}, "task": {}, "execution": {}, "outcome": {}}

    def record_selection() -> None:
        try:
            recorded["value"] = selections.record_hypothesis_selection(
                team_id,
                _selection_payload(agents["coordinator"]),
                agent_runner=_marker_runner,
            )
        except Exception as exc:  # noqa: BLE001 - surface selection errors from the worker thread
            errors.append(exc)
        finally:
            selection_finished.set()

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-slow-trace")
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", executor)
    monkeypatch.setattr(agent_kernel_service, "handle_kernel_event", slow_kernel_trace)
    selection_thread = threading.Thread(target=record_selection, name="pytest-selection", daemon=True)

    try:
        selection_thread.start()
        # The wait budgets only bound the worst case; healthy runs fire these
        # events in milliseconds.  5s was too tight for fleet-parallel xdist
        # runs on a loaded machine, where scheduling the single worker thread
        # onto the trace call can exceed 5s (registered flaky, 2026-09-02).
        assert trace_started.wait(timeout=60), "background worker did not start the trace"
        assert selection_finished.wait(timeout=60), "slow trace blocked candidate fan-out"
        assert not errors

        review_meetings = _review_meetings(recorded["value"])
        assert len(review_meetings) == 2
        assert all(meeting["chatRoomRoundIds"] for meeting in review_meetings)
    finally:
        release_trace.set()
        selection_thread.join(timeout=60)
        executor.shutdown(wait=True)


def _close_first_meeting_with_envelope(
    team_id: str, agent_ids: list[str], meeting_round_id: str, runtime
) -> dict:
    _drive_to_awaiting_approval(team_id, meeting_round_id, agent_ids[0])
    return chain.close_review_meeting(
        team_id,
        meeting_round_id,
        _closure_payload(agent_ids, [_envelope_decision(agent_ids[0])]),
        runtime=runtime,
    )


def test_hypothesis_first_chain_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    collection_calls = _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            # 0. Before any selection: both chain gates block.
            finding = _evaluate(runtime, team_id, "source_finding")
            assert not finding.ready
            assert "hypothesis_first_meeting_open" in _blocker_codes(finding)
            design = _evaluate(runtime, team_id, "hypothesis_design")
            design_codes = _blocker_codes(design)
            assert "hypothesis_round_unconverged" in design_codes
            assert "template_baseline_missing" in design_codes

            # 1. Selection persists -> first review meeting auto-opens in
            #    background mode with the room round <-> meetingRoundId binding.
            recorded = _open_first_meeting(team_id, agent_ids)
            # R2.2 claim belief gate: seed review-supported core claims for the
            # selected candidates so the final convergence can pass the gate.
            _seed_claim_belief_gate_fixture(
                monkeypatch, team_id, _QUESTION_ID, ["hyp-a", "hyp-b"]
            )
            review = recorded["reviewMeeting"]
            assert review["discussion"]["background"] is True
            first_round_meetings = _review_meetings(recorded)
            assert len(first_round_meetings) == 2
            meeting = first_round_meetings[0]
            first_meeting_id = meeting["meetingRoundId"]
            sibling_meeting_id = first_round_meetings[1]["meetingRoundId"]
            assert meeting["meetingType"] == "hypothesis_review"
            assert meeting["linkedChatRoomId"] == review["roomId"]
            assert meeting["chatRoomRoundIds"] == [review["roundId"]]
            room_detail = chat_room_service.get_chat_room_detail(review["roomId"])
            bound_round = next(
                item for item in room_detail["rounds"] if item["roundId"] == review["roundId"]
            )
            assert bound_round["config"]["meetingRoundId"] == first_meeting_id
            assert bound_round["status"] == "completed"

            # 2. The open first discussion still blocks source_finding.
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" in _blocker_codes(finding)

            # 3. Closing with a searchEnvelope decision triggers stage-1
            #    collection through the facade exactly once.
            closed_first = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            assert closed_first["meetingRound"]["status"] == "closed"
            assert (
                closed_first["hypothesisRound"]["status"]
                == "waiting_for_sibling_reviews"
            )
            requests = closed_first["collection"]["requests"]
            assert len(requests) == 1
            request = requests[0]
            assert request["status"] == "pending"
            assert request["collectionRunId"] == "dprun-hf4-1"
            assert request["meetingRoundId"] == first_meeting_id
            assert len(collection_calls) == 1
            ensure_scope = collection_calls[0]["payload"]["scope"]
            assert ensure_scope["researchScopeHash"] == meeting["scopeHash"]
            assert ensure_scope["searchEnvelope"]["keywords"] == [
                "predictive coding",
                "spike train coding",
            ]

            # One closed candidate must not make the logical round ready while
            # its sibling is still active.
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" in _blocker_codes(finding)

            # The logical round fans out to both selected candidates. Fan-in
            # happens only after the second sibling is confirmed.
            _drive_to_awaiting_approval(team_id, sibling_meeting_id, agent_ids[0])
            closed = chain.close_review_meeting(
                team_id,
                sibling_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )
            assert closed["meetingRound"]["status"] == "closed"
            assert closed["collection"]["requests"] == []
            assert len(collection_calls) == 1

            # 3b. The closure auto-generates a closed HypothesisRound through
            #     the HF-3 executor: meetingRefs point back to this meeting and
            #     the first round's lineage terminates at the question candidates.
            generated = closed["hypothesisRound"]
            assert generated["status"] == "created"
            first_round = generated["round"]
            assert first_round["status"] == "closed"
            assert first_round["metaReview"]["accepted"] is True
            assert {
                item["id"]
                for item in first_round["meetingRefs"]
                if item["kind"] == "meeting_round"
            } == {first_meeting_id, sibling_meeting_id}
            assert {
                item["id"] for item in first_round["lineage"] if item["kind"] == "candidate"
            } == {"hyp-a", "hyp-b"}
            assert not [
                item for item in first_round["lineage"] if item["kind"] == "round"
            ]

            # 4. The collection decision unblocks source_finding; the pending
            #    collection request blocks hypothesis_design as a knowledge gap.
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" not in _blocker_codes(finding)
            design = _evaluate(runtime, team_id, "hypothesis_design")
            design_codes = _blocker_codes(design)
            assert "knowledge_gap_pending" in design_codes
            assert "hypothesis_round_unconverged" in design_codes

            # The command gate enforces the same blockers (not just the probe).
            with pytest.raises(NodeNotReadyError):
                runtime.command_service.submit(
                    CommandRequest(
                        command_id="cmd-hf4-early-design",
                        run_id=_RUN_ID,
                        team_id=team_id,
                        command=WorkflowCommandKind.START_NODE,
                        node_id="hypothesis_design",
                        expected_run_version=1,
                        idempotency_key="hf4:test-early-design",
                        payload={},
                        requested_by=ActorRef("user", "u-1"),
                        requested_at_ms=_FIXED_NOW_MS,
                    )
                )

            # 5. Child collection handoff: gap clears, the parent re-checks
            #    (still unconverged) and the next review meeting auto-opens.
            handoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                handoff_ref="knowledge_package:pkg-1",
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            assert handoff["request"]["status"] == "handed_off"
            assert handoff["request"]["handoffRef"] == "knowledge_package:pkg-1"
            next_meeting = handoff["nextMeeting"]
            assert next_meeting["status"] in {"opened", "created", "reused"}
            second_round_meetings = _opened_review_meetings(next_meeting)
            assert second_round_meetings
            assert {item["meetingRoundId"] for item in second_round_meetings}.isdisjoint(
                {first_meeting_id, sibling_meeting_id}
            )
            assert next_meeting["roundIndex"] == 2

            links = chain.list_review_round_links(team_id, question_id=_QUESTION_ID)["links"]
            assert [link["roundIndex"] for link in links] == [1, 1] + [
                2
            ] * len(second_round_meetings)
            assert links[0]["meetingRoundId"] == first_meeting_id
            assert links[2]["previousMeetingRoundId"] == first_meeting_id
            assert links[2]["collectionRequestId"] == request["requestId"]

            design = _evaluate(runtime, team_id, "hypothesis_design")
            design_codes = _blocker_codes(design)
            assert "knowledge_gap_pending" not in design_codes
            assert "hypothesis_round_unconverged" in design_codes
            resume = handoff["resume"]
            assert resume["runs"][0]["runId"] == _RUN_ID
            assert resume["runs"][0]["action"] == "not_ready"
            assert "hypothesis_round_unconverged" in resume["runs"][0]["blockers"]
            assert runtime.store.latest_attempt(_RUN_ID, "hypothesis_design") is None

            # 6. Second discussion closes without new evidence requests; the
            #    closure auto-generates the next HypothesisRound whose lineage
            #    links back to the first round; a frozen baseline appears.
            closed_second = None
            for second_round_meeting in second_round_meetings:
                meeting_id = second_round_meeting["meetingRoundId"]
                _drive_to_awaiting_approval(team_id, meeting_id, agent_ids[0])
                closed_second = chain.close_review_meeting(
                    team_id,
                    meeting_id,
                    _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                    runtime=runtime,
                )
            assert closed_second is not None
            assert closed_second["collection"]["requests"] == []
            assert len(collection_calls) == 1
            generated_second = closed_second["hypothesisRound"]
            assert generated_second["status"] == "created"
            second_round = generated_second["round"]
            assert second_round["status"] == "closed"
            assert second_round["metaReview"]["accepted"] is True
            assert {
                item["id"]
                for item in second_round["meetingRefs"]
                if item["kind"] == "meeting_round"
            } == {item["meetingRoundId"] for item in second_round_meetings}
            assert [
                item["id"] for item in second_round["lineage"] if item["kind"] == "round"
            ] == [first_round["roundId"]]
            _freeze_template_baseline(team_id, agent_ids[0])

            # 7. Converged: the readiness re-check passes and the parent run
            #    dispatches hypothesis_design (writer-transaction-external).
            design = _evaluate(runtime, team_id, "hypothesis_design")
            assert design.ready, [b.code for b in design.blockers]
            resumed = chain.resume_parent_runs(
                team_id,
                question_id=_QUESTION_ID,
                runtime=runtime,
                trigger="test:converged",
            )
            assert resumed["runs"][0]["action"] == "started"
            attempt = runtime.store.latest_attempt(_RUN_ID, "hypothesis_design")
            assert attempt is not None
            assert attempt.status in {"starting", "dispatching", "running"}

            # Idempotent replay: the same trigger replays the command instead
            # of creating a second attempt.
            replayed = chain.resume_parent_runs(
                team_id,
                question_id=_QUESTION_ID,
                runtime=runtime,
                trigger="test:converged",
            )
            assert replayed["runs"][0]["action"] == "replayed"
            assert (
                runtime.store.latest_attempt(_RUN_ID, "hypothesis_design").node_run_id
                == attempt.node_run_id
            )
    finally:
        runtime.close()


def test_missing_search_envelope_never_triggers_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    collection_calls = _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            first_meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
            _drive_to_awaiting_approval(team_id, first_meeting_id, agent_ids[0])
            closed = chain.close_review_meeting(
                team_id,
                first_meeting_id,
                _closure_payload(
                    agent_ids,
                    [
                        _envelope_decision(
                            agent_ids[0], searchEnvelope={"sourceTypes": ["paper"]}
                        )
                    ],
                ),
                runtime=runtime,
            )
            assert closed["meetingRound"]["status"] == "closed"
            assert closed["collection"]["requests"] == []
            skipped = closed["collection"]["skipped"]
            assert len(skipped) == 1
            assert skipped[0]["reason"] == "search_envelope_missing"
            assert collection_calls == []

            # source_finding stays blocked: the first collection scope must
            # come from a discussion decision carrying a valid envelope.
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" in _blocker_codes(finding)
    finally:
        runtime.close()


def test_unconverged_round_blocks_hypothesis_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            first_round_meetings = _review_meetings(recorded)
            assert len(first_round_meetings) == 2
            first_meeting_id = first_round_meetings[0]["meetingRoundId"]
            sibling_meeting_id = first_round_meetings[1]["meetingRoundId"]
            closed_first = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            assert (
                closed_first["hypothesisRound"]["status"]
                == "waiting_for_sibling_reviews"
            )
            _drive_to_awaiting_approval(team_id, sibling_meeting_id, agent_ids[0])
            closed_sibling = chain.close_review_meeting(
                team_id,
                sibling_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )
            assert closed_sibling["hypothesisRound"]["status"] == "created"
            request = closed_first["collection"]["requests"][0]
            handoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            second_round_meetings = _opened_review_meetings(handoff["nextMeeting"])
            assert second_round_meetings
            # MetaReview does NOT accept: the auto-generated round stays
            # unconverged and hypothesis_design remains blocked.
            rejected_metareview = lambda context, candidates, pairwise, pareto: {
                "recommendationCandidateId": "hyp-a",
                "rationale": "证据仍不充分，暂不收敛",
                "riskNotes": "hyp-b 泛化证据待补",
                "accepted": False,
            }
            closed_second = None
            for index, second_round_meeting in enumerate(second_round_meetings):
                meeting_id = second_round_meeting["meetingRoundId"]
                _drive_to_awaiting_approval(team_id, meeting_id, agent_ids[0])
                closed_second = chain.close_review_meeting(
                    team_id,
                    meeting_id,
                    _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                    runtime=runtime,
                    metareview_runner=(
                        rejected_metareview
                        if index == len(second_round_meetings) - 1
                        else None
                    ),
                )
            assert closed_second is not None
            generated_second = closed_second["hypothesisRound"]
            assert generated_second["status"] == "created"
            assert generated_second["round"]["status"] == "closed"
            assert generated_second["round"]["metaReview"]["accepted"] is False
            _freeze_template_baseline(team_id, agent_ids[0])

            design = _evaluate(runtime, team_id, "hypothesis_design")
            design_codes = _blocker_codes(design)
            assert not design.ready
            assert "hypothesis_round_unconverged" in design_codes
            assert "knowledge_gap_pending" not in design_codes
            assert "template_baseline_missing" not in design_codes

            resumed = chain.resume_parent_runs(
                team_id,
                question_id=_QUESTION_ID,
                runtime=runtime,
                trigger="test:unconverged",
            )
            assert resumed["runs"][0]["action"] == "not_ready"
            assert runtime.store.latest_attempt(_RUN_ID, "hypothesis_design") is None
    finally:
        runtime.close()


def test_chain_state_budget_tracks_current_selection_not_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Budget exhaustion must follow the current selection's rounds; earlier
    selections and superseded rounds must not fake budget_exhausted."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    recorded = _open_first_meeting(team_id, agent_ids)
    previous_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
    for _ in range(4):
        opened = chain.open_next_review_meeting(
            team_id,
            previous_meeting_round_id=previous_id,
            agent_runner=_marker_runner,
        )
        assert opened["status"] == "opened"
        previous_id = opened["meetingRound"]["meetingRoundId"]

    exhausted_state = chain.chain_state(team_id, _QUESTION_ID)
    assert exhausted_state["budgetExhausted"] is True
    assert exhausted_state["roundBudget"] == 5

    # Re-selecting candidates starts a fresh selection: its rounds restart at 1
    # and budget exhaustion must clear even though the question keeps all old
    # review meetings.
    reselected = selections.record_hypothesis_selection(
        team_id,
        _selection_payload(agent_ids[1]),
        agent_runner=_marker_runner,
    )
    assert reselected["status"] == "created"
    refreshed_state = chain.chain_state(team_id, _QUESTION_ID)
    assert refreshed_state["budgetExhausted"] is False
    assert refreshed_state["roundBudget"] == 5


def test_round_budget_exhaustion_requires_manual_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    recorded = _open_first_meeting(team_id, agent_ids)
    first_meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]

    # The limit is server-owned: callers cannot shrink or raise it.
    with pytest.raises(ValueError, match="fixed at 5"):
        chain.open_next_review_meeting(
            team_id,
            previous_meeting_round_id=first_meeting_id,
            budget=1,
            agent_runner=_marker_runner,
        )

    previous_id = first_meeting_id
    for expected_round in range(2, 6):
        opened = chain.open_next_review_meeting(
            team_id,
            previous_meeting_round_id=previous_id,
            agent_runner=_marker_runner,
        )
        assert opened["status"] == "opened"
        assert opened["roundIndex"] == expected_round
        previous_id = opened["meetingRound"]["meetingRoundId"]

    exhausted = chain.open_next_review_meeting(
        team_id,
        previous_meeting_round_id=previous_id,
        agent_runner=_marker_runner,
    )
    assert exhausted["status"] == "budget_exhausted"
    assert exhausted["roundIndex"] == 6
    assert exhausted["budget"] == 5


def test_canonical_next_review_round_fans_out_the_full_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    recorded = _open_first_meeting(team_id, agent_ids)
    first_round = _review_meetings(recorded)
    assert len(first_round) == 2

    opened = chain.open_next_review_meeting(
        team_id,
        previous_meeting_round_id=first_round[0]["meetingRoundId"],
        fan_out_selection=True,
        agent_runner=_marker_runner,
    )

    second_round = list(opened.get("reviewMeetings") or [])
    assert len(second_round) == 2
    assert {
        str((item.get("link") or {}).get("candidateId") or "")
        for item in second_round
    } == {"hyp-a", "hyp-b"}


def test_sibling_gate_classifies_only_actionable_siblings_as_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closed and superseded siblings release the open; live ones block it.

    The gate reads the newest logical round's own links (latest attempt per
    candidate), so a superseded sibling stays on its retry recovery, a retry
    attempt that is live again blocks, and a newer logical round decides over
    any older awaiting room.
    """
    from core.web.services import team_service

    team_id = "team-sibling-gate"
    links: list[dict] = [
        {
            "meetingRoundId": "meeting-a-r1",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-a",
            "candidateOrder": 0,
            "createdAt": "2026-08-31T01:00:00Z",
        },
        {
            "meetingRoundId": "meeting-b-r1",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-b",
            "candidateOrder": 1,
            "createdAt": "2026-08-31T01:00:00Z",
        },
    ]
    meeting_by_id = {
        "meeting-a-r1": {"meetingRoundId": "meeting-a-r1", "status": "closed"},
        "meeting-b-r1": {
            "meetingRoundId": "meeting-b-r1",
            "status": "awaiting_approval",
        },
    }
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        chain,
        "list_review_round_links",
        lambda *_args, **_kwargs: {"links": [dict(item) for item in links]},
    )
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda _team_id, meeting_id: {"meetingRound": meeting_by_id[meeting_id]},
    )

    pending = chain._latest_round_sibling_gate(team_id, "selection-1")
    assert pending["roundIndex"] == 1
    assert pending["pendingMeetingRoundIds"] == ["meeting-b-r1"]
    assert pending["pendingCandidateIds"] == ["hyp-b"]

    # A superseded sibling owns its retry recovery and never blocks the open.
    meeting_by_id["meeting-b-r1"] = {
        "meetingRoundId": "meeting-b-r1",
        "status": "superseded",
    }
    released = chain._latest_round_sibling_gate(team_id, "selection-1")
    assert released["pendingMeetingRoundIds"] == []
    assert released["pendingCandidateIds"] == []

    # Retry attempts fold to the newest link: a live retry attempt blocks.
    links.append(
        {
            "meetingRoundId": "meeting-b-r1-a2",
            "selectionId": "selection-1",
            "roundIndex": 1,
            "candidateId": "hyp-b",
            "candidateOrder": 1,
            "createdAt": "2026-08-31T02:00:00Z",
        }
    )
    meeting_by_id["meeting-b-r1-a2"] = {
        "meetingRoundId": "meeting-b-r1-a2",
        "status": "open",
    }
    retry_pending = chain._latest_round_sibling_gate(team_id, "selection-1")
    assert retry_pending["roundIndex"] == 1
    assert retry_pending["pendingMeetingRoundIds"] == ["meeting-b-r1-a2"]
    assert retry_pending["pendingCandidateIds"] == ["hyp-b"]

    # The newest logical round decides the gate; an older awaiting room is
    # stale history for open-next (its approve entry stays projected).
    links.append(
        {
            "meetingRoundId": "meeting-a-r2",
            "selectionId": "selection-1",
            "roundIndex": 2,
            "candidateId": "hyp-a",
            "candidateOrder": 0,
            "createdAt": "2026-08-31T03:00:00Z",
        }
    )
    meeting_by_id["meeting-a-r2"] = {
        "meetingRoundId": "meeting-a-r2",
        "status": "closed",
    }
    latest_round = chain._latest_round_sibling_gate(team_id, "selection-1")
    assert latest_round["roundIndex"] == 2
    assert latest_round["pendingMeetingRoundIds"] == []


def test_open_next_review_meeting_reports_sibling_reviews_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The manual open-next command surfaces the blocked reason for the UI."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    recorded = _open_first_meeting(team_id, agent_ids)
    first_round = _review_meetings(recorded)
    assert len(first_round) == 2
    first_meeting_id = first_round[0]["meetingRoundId"]
    sibling_meeting_id = first_round[1]["meetingRoundId"]
    _drive_to_awaiting_approval(team_id, first_meeting_id, agent_ids[0])
    chain.close_review_meeting(
        team_id,
        first_meeting_id,
        _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
    )
    _drive_to_awaiting_approval(team_id, sibling_meeting_id, agent_ids[0])

    blocked = chain.open_next_review_meeting(
        team_id,
        previous_meeting_round_id=first_meeting_id,
        fan_out_selection=True,
        enforce_sibling_archive_gate=True,
        agent_runner=_marker_runner,
    )
    assert blocked["status"] == "sibling_reviews_pending"
    assert blocked["pendingMeetingRoundIds"] == [sibling_meeting_id]
    assert blocked["pendingCandidateIds"] == ["hyp-b"]

    # The ungated direct path keeps its legacy behaviour.
    unguarded = chain.open_next_review_meeting(
        team_id,
        previous_meeting_round_id=first_meeting_id,
        fan_out_selection=True,
        agent_runner=_marker_runner,
    )
    assert unguarded["status"] in {"opened", "created", "reused"}


def test_v2_open_next_review_command_enforces_sibling_archive_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_state_v2,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: {
            "stateVersion": "hf2-action:pending:pending",
            "allowedActions": [
                {
                    "kind": "command",
                    "actionId": "open-next-review",
                    "command": "open_next_review",
                    "payload": {"previousMeetingRoundId": "meeting-1"},
                    "enabled": True,
                    "idempotencyKey": "hf2:open-next-review:1",
                }
            ],
        },
    )
    captured: dict[str, Any] = {}

    def open_next(team_id: str, **kwargs):
        captured.update(kwargs)
        return {"status": "sibling_reviews_pending"}

    monkeypatch.setattr(chain, "open_next_review_meeting", open_next)
    result = chain.execute_v2_command(
        "team-1",
        {
            "actionId": "open-next-review",
            "idempotencyKey": "hf2:open-next-review:1",
            "expectedStateVersion": "hf2-action:pending:pending",
            "command": "open_next_review",
            "payload": {"previousMeetingRoundId": "meeting-1"},
        },
        question_id="SCI-001",
    )

    assert result["result"]["status"] == "sibling_reviews_pending"
    assert captured["previous_meeting_round_id"] == "meeting-1"
    assert captured["enforce_sibling_archive_gate"] is True


def test_sibling_archive_gate_defers_next_review_until_last_sibling_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirming one candidate must not overwrite its sibling's approval gate.

    The first handoff of a fan-out round reports ``sibling_reviews_pending``
    while the sibling digest still awaits confirmation; the last sibling's
    close re-opens the deferred round exactly once, and handoff replays
    resolve to the already-open round instead of stacking another.
    """
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            first_round = _review_meetings(recorded)
            assert len(first_round) == 2
            first_meeting_id = first_round[0]["meetingRoundId"]
            sibling_meeting_id = first_round[1]["meetingRoundId"]

            closed_first = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            request = closed_first["collection"]["requests"][0]
            assert closed_first["deferredNextReview"] is None

            # The sibling digest now waits for the operator; the handoff must
            # not open a round that would overwrite this confirmation gate.
            _drive_to_awaiting_approval(team_id, sibling_meeting_id, agent_ids[0])
            handoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                handoff_ref="knowledge_package:pkg-1",
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            deferred = handoff["nextMeeting"]
            assert deferred["status"] == "sibling_reviews_pending"
            assert deferred["pendingMeetingRoundIds"] == [sibling_meeting_id]
            assert deferred["pendingCandidateIds"] == ["hyp-b"]
            links = chain.list_review_round_links(team_id, question_id=_QUESTION_ID)[
                "links"
            ]
            assert {int(link["roundIndex"]) for link in links} == {1}

            # The handoff replay keeps reporting the deferred gate.
            replay_handoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                handoff_ref="knowledge_package:pkg-1",
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            assert replay_handoff["nextMeeting"]["status"] == "sibling_reviews_pending"

            # Confirming the last sibling archives the logical round and
            # re-opens the deferred round exactly once.
            closed_sibling = chain.close_review_meeting(
                team_id,
                sibling_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            triggered = closed_sibling["deferredNextReview"]
            assert triggered["status"] in {"opened", "created", "reused"}
            assert triggered["roundIndex"] == 2
            second_round = _opened_review_meetings(triggered)
            assert len(second_round) == 2

            # Replaying the sibling close must not stack another round.
            reclosed_sibling = chain.close_review_meeting(
                team_id,
                sibling_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )
            assert reclosed_sibling["status"] == "reused"
            assert reclosed_sibling["deferredNextReview"] is None
            links = chain.list_review_round_links(team_id, question_id=_QUESTION_ID)[
                "links"
            ]
            assert [int(link["roundIndex"]) for link in links] == [1, 1, 2, 2]

            # The replayed handoff now resolves to the already-open round.
            rehandoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                handoff_ref="knowledge_package:pkg-1",
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            assert rehandoff["nextMeeting"]["status"] == "reused"
            assert (
                rehandoff["nextMeeting"]["meetingRound"]["meetingRoundId"]
                == second_round[0]["meetingRoundId"]
            )
    finally:
        runtime.close()


def test_late_handoff_for_archived_round_does_not_stack_another_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two sibling handoffs of one logical round must share one follow-up.

    The first handoff of the fully archived round opens the next round; a
    late handoff bound to the same now-superseded round is skipped instead of
    stacking a second live round on top of it.
    """
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    recorded = _open_first_meeting(team_id, agent_ids)
    first_round = _review_meetings(recorded)
    assert len(first_round) == 2
    first_meeting_id = first_round[0]["meetingRoundId"]
    sibling_meeting_id = first_round[1]["meetingRoundId"]

    _drive_to_awaiting_approval(team_id, first_meeting_id, agent_ids[0])
    closed_first = chain.close_review_meeting(
        team_id,
        first_meeting_id,
        _closure_payload(agent_ids, [_envelope_decision(agent_ids[0])]),
    )
    first_request = closed_first["collection"]["requests"][0]

    _drive_to_awaiting_approval(team_id, sibling_meeting_id, agent_ids[0])
    closed_sibling = chain.close_review_meeting(
        team_id,
        sibling_meeting_id,
        _closure_payload(agent_ids, [_envelope_decision(agent_ids[0])]),
    )
    sibling_request = closed_sibling["collection"]["requests"][0]
    # Both siblings are archived but nothing is handed off yet, so the
    # closure trigger has no deferred open to retry.
    assert closed_sibling["deferredNextReview"] is None

    first_open = chain.record_collection_handoff(
        team_id,
        first_request["requestId"],
        handoff_ref="knowledge_package:pkg-1",
        agent_runner=_marker_runner,
    )
    assert first_open["nextMeeting"]["status"] in {"opened", "created", "reused"}
    assert first_open["nextMeeting"]["roundIndex"] == 2

    late_open = chain.record_collection_handoff(
        team_id,
        sibling_request["requestId"],
        handoff_ref="knowledge_package:pkg-2",
        agent_runner=_marker_runner,
    )
    assert late_open["nextMeeting"]["status"] == "skipped"
    assert late_open["nextMeeting"]["reason"] == "newer_review_round_already_open"
    links = chain.list_review_round_links(team_id, question_id=_QUESTION_ID)["links"]
    assert [int(link["roundIndex"]) for link in links] == [1, 1, 2, 2]


def test_interruption_recovery_preserves_rounds_and_idempotency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    collection_calls = _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            selection_id = recorded["selection"]["selectionId"]
            first_round_meetings = _review_meetings(recorded)
            assert len(first_round_meetings) == 2
            first_meeting_id = first_round_meetings[0]["meetingRoundId"]
            sibling_meeting_id = first_round_meetings[1]["meetingRoundId"]

            # Re-recording the same selection reuses everything (recovery from
            # a crash between selection persistence and meeting opening).
            replayed = selections.record_hypothesis_selection(
                team_id,
                _selection_payload(agent_ids[0]),
                agent_runner=_marker_runner,
            )
            assert replayed["status"] == "reused"
            assert replayed["reviewMeeting"]["status"] == "reused"
            assert (
                replayed["reviewMeeting"]["meetingRound"]["meetingRoundId"]
                == first_meeting_id
            )

            closed_first = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            request = closed_first["collection"]["requests"][0]
            assert (
                closed_first["hypothesisRound"]["status"]
                == "waiting_for_sibling_reviews"
            )
            _drive_to_awaiting_approval(team_id, sibling_meeting_id, agent_ids[0])
            closed_sibling = chain.close_review_meeting(
                team_id,
                sibling_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )
            first_round_id = closed_sibling["hypothesisRound"]["round"]["roundId"]
            assert closed_sibling["hypothesisRound"]["status"] == "created"

            # Re-closing with the identical payload replays the closure and
            # must not duplicate the collection request, the facade call, or
            # the generated HypothesisRound.
            reclosed = chain.close_review_meeting(
                team_id,
                first_meeting_id,
                _closure_payload(agent_ids, [_envelope_decision(agent_ids[0])]),
                runtime=runtime,
            )
            assert reclosed["status"] == "reused"
            assert len(reclosed["collection"]["requests"]) == 1
            assert reclosed["collection"]["requests"][0]["requestId"] == request["requestId"]
            assert len(collection_calls) == 1
            assert reclosed["hypothesisRound"]["status"] == "reused"
            assert reclosed["hypothesisRound"]["round"]["roundId"] == first_round_id
            assert (
                hrounds.list_hypothesis_rounds(team_id)["roundCount"] == 1
            )

            handoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                handoff_ref="knowledge_package:pkg-1",
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            second_round_meetings = _opened_review_meetings(handoff["nextMeeting"])
            assert len(second_round_meetings) == 2
            assert {
                ref.split(":", 1)[1]
                for item in second_round_meetings
                for ref in list(item.get("discussionItemRefs") or [])
                if str(ref).startswith("hypothesis_candidate:")
            } == {"hyp-a", "hyp-b"}
            second_meeting_id = second_round_meetings[0]["meetingRoundId"]

            # Repeating the handoff is a no-op: no new meeting, no new link.
            rehandoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                handoff_ref="knowledge_package:pkg-1",
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            assert rehandoff["status"] == "reused"
            assert (
                rehandoff["nextMeeting"]["meetingRound"]["meetingRoundId"]
                == second_meeting_id
            )
            links = chain.list_review_round_links(team_id, question_id=_QUESTION_ID)["links"]
            assert len(links) == 2 + len(second_round_meetings)

            # Chain state survives a fresh read (no in-memory state).
            state = chain.chain_state(team_id, _QUESTION_ID)
            assert state["selectionId"] == selection_id
            assert state["firstMeetingId"] == first_meeting_id
            assert state["firstMeetingClosed"] is True
            assert state["collectionRequestCount"] == 1
            assert state["pendingCollectionCount"] == 0
            assert state["collectionReady"] is True
            assert state["meetingCount"] == 2 + len(second_round_meetings)
            assert state["hypothesisRoundCount"] == 1
    finally:
        runtime.close()


def test_close_reports_failed_hypothesis_round_without_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate without a claim fails round generation, not the closure."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(
        monkeypatch,
        hypotheses=[
            {"hypothesis_id": "hyp-a", "statement": "hyp-a 的机制陈述"},
            {"hypothesis_id": "hyp-b", "statement": ""},
            {"hypothesis_id": "hyp-c", "statement": "hyp-c 的机制陈述"},
        ],
    )
    collection_calls = _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            sibling_meetings = _review_meetings(recorded)
            assert len(sibling_meetings) == 2
            first_meeting_id = sibling_meetings[0]["meetingRoundId"]
            second_meeting_id = sibling_meetings[1]["meetingRoundId"]
            _drive_to_awaiting_approval(team_id, first_meeting_id, agent_ids[0])
            closed_first = chain.close_review_meeting(
                team_id,
                first_meeting_id,
                _closure_payload(agent_ids, [_envelope_decision(agent_ids[0])]),
                runtime=runtime,
            )

            assert closed_first["meetingRound"]["status"] == "closed"
            assert len(closed_first["collection"]["requests"]) == 1
            assert len(collection_calls) == 1
            assert (
                closed_first["hypothesisRound"]["status"]
                == "waiting_for_sibling_reviews"
            )

            _drive_to_awaiting_approval(team_id, second_meeting_id, agent_ids[0])
            closed = chain.close_review_meeting(
                team_id,
                second_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )

            # The closure and the collection trigger stand; only the round
            # generation reports a structured failure (fail-closed via the
            # readiness layer, never a rollback of the closed fact).
            assert closed["meetingRound"]["status"] == "closed"
            assert len(collection_calls) == 1
            hypothesis_round = closed["hypothesisRound"]
            assert hypothesis_round["status"] == "failed"
            assert "hyp-b" in hypothesis_round["error"]
            assert hrounds.list_hypothesis_rounds(team_id)["roundCount"] == 0

            # hypothesis_design stays blocked on the unconverged round gate.
            design = _evaluate(runtime, team_id, "hypothesis_design")
            assert "hypothesis_round_unconverged" in _blocker_codes(design)
    finally:
        runtime.close()


def _candidate_generation_runner(participant, prompt, context):
    """Round-0 discussion fixture: one required meeting role proposes markers."""
    role = str(participant.get("teamRole") or "participant")
    if role in {"source_finder", "challenge_cup_search"}:
        content = (
            "CANDIDATE: cand-a | 睡眠剥夺通过腺苷积累损害记忆巩固 | 腺苷受体机制明确\n"
            "CANDIDATE: cand-b | 睡眠剥夺通过突触稳态失衡损害记忆巩固 | 突触稳态假说"
        )
    else:
        content = "AGREE: cand-a 的检验路径更直接"
    return {"status": "completed", "raw_output": content, "summary": "ok"}


def _grounded_candidate_generation_runner(participant, prompt, context):
    role = str(participant.get("teamRole") or "participant")
    if role in {"source_finder", "challenge_cup_search"}:
        candidates = [
            {
                "candidateId": "draft-a",
                "statement": "睡眠剥夺通过腺苷积累损害记忆巩固",
                "rationale": "A1 受体机制",
                "proposedBy": role,
                "lineageRefs": ["evidence:accepted-1", "evidence:boundary-1"],
                "testablePrediction": "阻断 A1 受体后记忆表现应恢复",
                "falsifier": "阻断 A1 受体后记忆表现仍不恢复",
                "axisProfile": {
                    "mechanism": "腺苷 A1 受体介导",
                    "intervention": "阻断 A1 受体",
                    "observable": "记忆表现",
                    "population": "睡眠剥夺受试者",
                    "boundary": "急性睡眠剥夺",
                },
            },
            {
                "candidateId": "draft-b",
                "statement": "睡眠剥夺通过突触稳态失衡损害记忆巩固",
                "rationale": "突触稳态机制",
                "proposedBy": role,
                "lineageRefs": ["evidence:accepted-2", "evidence:boundary-1"],
                "testablePrediction": "睡眠恢复后突触标志物应回归基线",
                "falsifier": "睡眠恢复后突触标志物持续偏离且记忆不受影响",
                "axisProfile": {
                    "mechanism": "突触稳态失衡",
                    "intervention": "恢复睡眠",
                    "observable": "突触标志物与记忆表现",
                    "population": "睡眠剥夺受试者",
                    "boundary": "急性睡眠剥夺",
                },
            },
        ]
        content = json.dumps(
            {
                "schemaVersion": 1,
                "display": {"conclusion": "提出两个正式候选", "sections": []},
                "protocol": {
                    "agreements": [],
                    "disagreements": [],
                    "risks": [],
                    "actionItems": [],
                    "knowledgeCandidates": [],
                    "proposedCandidates": candidates,
                    "evidenceRequests": [],
                },
            },
            ensure_ascii=False,
        )
    else:
        content = "AGREE: 两个候选都给出了可检验预测"
    return {"status": "completed", "raw_output": content, "summary": "ok"}


def _generation_receipt_authority(team_id: str, run_id: str) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": team_id,
        "questionId": _QUESTION_ID,
        "workflowRunId": run_id,
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "challenge-cup-research@1",
        "modelPolicySha256": "a" * 64,
    }


def test_candidate_generation_cold_start_registers_ledger_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog cold start: round-0 generation discussion -> ledger candidates.

    No approved v2 artifact exists, so the selection candidate source is the
    generation meeting's digest proposals recorded in the chain ledger.
    """
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )

    assert chain.needs_candidate_generation(team_id, _QUESTION_ID) is True

    with server_operator_scope("u-1", roles=("operator",)):
        opened = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )
        assert opened["status"] == "opened"
        meeting = opened["meetingRound"]
        assert meeting["meetingType"] == "hypothesis_candidate_generation"
        meeting_round_id = meeting["meetingRoundId"]
        active_attempt = chain.list_generation_attempts(
            team_id, question_id=_QUESTION_ID
        )["attempts"][-1]
        assert active_attempt["lifecycle"] == "running"
        assert active_attempt["outcome"] == "none"
        assert active_attempt["meetingRoundId"] == meeting_round_id

        # Reopening while open reuses the same discussion (deterministic id).
        reused = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )
        assert reused["meetingRound"]["meetingRoundId"] == meeting_round_id

        agent_ids = [agents[role] for role in _ROLES]
        _drive_to_awaiting_approval(team_id, meeting_round_id, agent_ids[0])
        closed = chain.close_review_meeting(
            team_id,
            meeting_round_id,
            _closure_payload(agent_ids, []),
        )
        assert closed["meetingRound"]["status"] == "closed"
        assert closed["candidateCount"] == 2
        completed_attempt = chain.list_generation_attempts(
            team_id, question_id=_QUESTION_ID
        )["attempts"][-1]
        assert completed_attempt["attemptId"] == active_attempt["attemptId"]
        assert completed_attempt["lifecycle"] == "completed"
        assert completed_attempt["outcome"] == "succeeded"
        statements = {item["statement"] for item in closed["candidates"]}
        assert "睡眠剥夺通过腺苷积累损害记忆巩固" in statements
        assert "睡眠剥夺通过突触稳态失衡损害记忆巩固" in statements

        candidates = chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)[
            "candidates"
        ]
        assert len(candidates) == 2
        assert chain.needs_candidate_generation(team_id, _QUESTION_ID) is False

        # A closed generation meeting is never reopened; replays reuse it.
        replayed = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )
        assert replayed["status"] == "reused"
        assert replayed["meetingRound"]["meetingRoundId"] == meeting_round_id

        state = chain.chain_state(team_id, _QUESTION_ID)
        assert state["candidateCount"] == 2
        assert state["generationMeetingId"] == meeting_round_id
        assert state["generationMeetingStatus"] == "closed"
        # The generation round is not a review round: it does not count into
        # the discussion-round budget.
        assert state["meetingCount"] == 0


def test_stage_one_r0_isolated_then_r1_requires_whitelisted_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )

    with server_operator_scope("u-1", roles=("operator",)):
        opened_r0 = chain.open_candidate_generation_meeting(
            team_id,
            _QUESTION_ID,
            agent_runner=_candidate_generation_runner,
            _candidate_authority="exploratory_draft",
        )
        r0_id = opened_r0["meetingRound"]["meetingRoundId"]
        agent_ids = [agents[role] for role in _ROLES]
        _drive_to_awaiting_approval(team_id, r0_id, agent_ids[0])
        closed_r0 = chain.close_review_meeting(
            team_id, r0_id, _closure_payload(agent_ids, [])
        )

        assert closed_r0["candidateCount"] == 0
        assert closed_r0["draftCount"] == 2
        assert chain.list_hypothesis_candidates(
            team_id, question_id=_QUESTION_ID
        )["candidates"] == []
        drafts = chain.list_exploratory_drafts(
            team_id, question_id=_QUESTION_ID
        )["drafts"]
        assert len(drafts) == 2
        replayed_r0 = chain.open_candidate_generation_meeting(
            team_id,
            _QUESTION_ID,
            agent_runner=_candidate_generation_runner,
            _candidate_authority="exploratory_draft",
        )
        assert replayed_r0["status"] == "reused"
        assert replayed_r0["meetingRound"]["meetingRoundId"] == r0_id

        with pytest.raises(
            chain.HypothesisFirstChainError,
            match="accepted knowledge package",
        ):
            chain.open_candidate_generation_meeting(
                team_id,
                _QUESTION_ID,
                agent_runner=_grounded_candidate_generation_runner,
                _candidate_authority="formal_grounded_candidate",
                _generation_context={
                    "status": "blocked",
                    "allowedEvidenceRefs": [],
                },
            )

        opened_r1 = chain.open_candidate_generation_meeting(
            team_id,
            _QUESTION_ID,
            agent_runner=_grounded_candidate_generation_runner,
            _candidate_authority="formal_grounded_candidate",
            _generation_context={
                "status": "ready",
                "allowedEvidenceRefs": [
                    "evidence:accepted-1",
                    "evidence:accepted-2",
                    "evidence:boundary-1",
                ],
                "evidenceClaims": [
                    {"sourceRef": "evidence:accepted-1", "claim": "腺苷支持证据"},
                    {"sourceRef": "evidence:accepted-2", "claim": "突触支持证据"},
                ],
                "knowledgePackage": {
                    "sourceArtifactIds": ["knowledge_package:pkg-1"]
                },
            },
        )
        r1_id = opened_r1["meetingRound"]["meetingRoundId"]
        _drive_to_awaiting_approval(team_id, r1_id, agent_ids[0])
        closed_r1 = chain.close_review_meeting(
            team_id, r1_id, _closure_payload(agent_ids, [])
        )

    assert closed_r1["candidateCount"] == 2
    formal = chain.list_hypothesis_candidates(
        team_id, question_id=_QUESTION_ID
    )["candidates"]
    draft_ids = {str(item["candidateId"]) for item in drafts}
    assert not draft_ids.intersection(str(item["candidateId"]) for item in formal)
    assert all(item["candidateAuthority"] == "formal_grounded_candidate" for item in formal)
    assert all(item["lineageRefs"] for item in formal)
    assert all(item["testablePrediction"] for item in formal)
    assert all(item["falsifier"] for item in formal)
    assert all(len(item["axisProfile"]) == 5 for item in formal)
    assert all(item["revisionOrdinal"] == 1 for item in formal)
    assert all(item["derivedFromDraftRefs"] for item in formal)


def test_closed_stage_one_r0_evidence_scope_unblocks_source_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R0 owns the bounded search scope before formal candidates can exist."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )

    with server_operator_scope("u-1", roles=("operator",)):
        opened = chain.open_candidate_generation_meeting(
            team_id,
            _QUESTION_ID,
            agent_runner=_candidate_generation_runner,
            _candidate_authority="exploratory_draft",
        )
        meeting_id = opened["meetingRound"]["meetingRoundId"]
        actor = agents[_ROLES[0]]
        _drive_to_awaiting_approval(team_id, meeting_id, actor)
        draft = dict(
            meetings.get_meeting_round(team_id, meeting_id)["meetingRound"][
                "digestDraft"
            ]
        )
        assert len(draft["proposedCandidates"]) == 2
        draft["evidenceRequests"] = [
            {
                "rationale": "为两个机制补充可核验来源",
                "candidateRefs": ["cand-a", "cand-b"],
                "evidenceRefs": [],
                "searchEnvelope": {
                    "keywords": [
                        "adenosine sleep deprivation",
                        "synaptic homeostasis",
                    ],
                    "sourceTypes": ["paper"],
                    "evidenceLevels": ["peer_reviewed"],
                },
                "requirements": {
                    "minEvidenceLevel": "medium",
                    "completeness": "stage-one",
                },
                "writebackPolicy": {},
            }
        ]
        meetings.reject_meeting_digest_draft(
            team_id, meeting_id, actor=actor, reason="补入已确认的搜集范围"
        )
        submitted = meetings.submit_meeting_digest_draft(team_id, meeting_id, draft)
        draft = submitted["digestDraft"]
        closed = chain.approve_meeting_digest(
            team_id,
            meeting_id,
            closed_by=actor,
            expected_digest_content_hash=draft["contentHash"],
        )

    assert closed["meetingRound"]["status"] == "closed"
    assert closed["draftCount"] == 2
    state = chain.chain_state(team_id, _QUESTION_ID)
    assert state["candidateCount"] == 0
    assert state["collectionRequestCount"] == 0
    assert state["collectionReady"] is True


def test_formal_grounded_candidates_fail_closed_on_refs_and_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    meeting = {
        "meetingRoundId": "meeting-r1",
        "question": _QUESTION_ID,
        "candidateAuthority": "formal_grounded_candidate",
        "allowedEvidenceRefs": ["evidence:accepted-1"],
        "exploratoryDraftRefs": ["exploratory_draft:r0-a"],
        "knowledgePackageRefs": ["knowledge_package:pkg-1"],
        "revisionOrdinal": 1,
    }

    with pytest.raises(
        chain.HypothesisFirstChainError,
        match="refs must match the evidence whitelist",
    ):
        chain._append_generation_candidates(
            team_id,
            meeting,
            [
                {
                    "statement": "候选一",
                    "rationale": "理由",
                    "lineageRefs": ["evidence:not-accepted"],
                    "testablePrediction": "预测一",
                }
            ],
        )

    with pytest.raises(
        chain.HypothesisFirstChainError,
        match="requires CHECK prediction",
    ):
        chain._append_generation_candidates(
            team_id,
            meeting,
            [
                {
                    "statement": "候选二",
                    "rationale": "理由",
                    "lineageRefs": ["evidence:accepted-1"],
                    "testablePrediction": "",
                }
            ],
        )


def test_candidate_generation_recovers_empty_digest_proposals_from_source_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale empty draft must not discard candidate markers at approval."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )

    with server_operator_scope("u-1", roles=("operator",)):
        opened = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )
        meeting_round_id = opened["meetingRound"]["meetingRoundId"]
        agent_ids = [agents[role] for role in _ROLES]
        _drive_to_awaiting_approval(team_id, meeting_round_id, agent_ids[0])

        stale_draft = dict(
            meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"][
                "digestDraft"
            ]
        )
        stale_draft["proposedCandidates"] = []
        meetings.reject_meeting_digest_draft(
            team_id, meeting_round_id, actor=agent_ids[0], reason="重放空草稿"
        )
        meetings.submit_meeting_digest_draft(team_id, meeting_round_id, stale_draft)

        closed = chain.close_review_meeting(
            team_id,
            meeting_round_id,
            _closure_payload(agent_ids, []),
        )
        replayed = chain.close_review_meeting(
            team_id,
            meeting_round_id,
            _closure_payload(agent_ids, []),
        )

    assert closed["meetingRound"]["status"] == "closed"
    assert closed["candidateCount"] == 2
    assert len(closed["digest"]["proposedCandidates"]) == 2
    assert replayed["status"] == "reused"
    assert replayed["candidateCount"] == 2
    assert chain.chain_state(team_id, _QUESTION_ID)["candidateCount"] == 2


def test_closed_generation_heals_candidates_from_source_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy closed empty digest can repopulate the candidate ledger."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )

    with server_operator_scope("u-1", roles=("operator",)):
        opened = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )
        meeting_round_id = opened["meetingRound"]["meetingRoundId"]
        agent_ids = [agents[role] for role in _ROLES]
        _drive_to_awaiting_approval(team_id, meeting_round_id, agent_ids[0])
        stale_draft = dict(
            meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"][
                "digestDraft"
            ]
        )
        stale_draft["proposedCandidates"] = []
        meetings.reject_meeting_digest_draft(
            team_id, meeting_round_id, actor=agent_ids[0], reason="构造旧空摘要"
        )
        meetings.submit_meeting_digest_draft(team_id, meeting_round_id, stale_draft)
        direct_closed = meetings.approve_meeting_closure(
            team_id,
            meeting_round_id,
            _closure_payload(
                agent_ids,
                [
                    {
                        "decision": "propose_candidates",
                        "rationale": "保留旧闭会事实，稍后从讨论消息恢复候选。",
                        "decidedBy": agent_ids[0],
                        "candidateRefs": [],
                        "evidenceRefs": [stale_draft["sourceMessageRefs"][0]],
                        "status": "adopted",
                    }
                ],
            ),
        )
        healed = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )

    assert direct_closed["digest"]["proposedCandidates"] == []
    assert healed["status"] == "reused"
    assert healed["meetingRound"]["meetingRoundId"] == meeting_round_id
    assert chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)[
        "candidateCount"
    ] == 2


def test_stopped_generation_does_not_heal_or_reuse_for_a_new_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Partial stopped speech is audit evidence, never candidate authority."""

    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )
    monkeypatch.setattr(
        meeting_runtime,
        "maybe_auto_draft_after_chat_round",
        lambda *_args, **_kwargs: None,
    )

    with server_operator_scope("u-1", roles=("operator",)):
        first = chain.open_candidate_generation_meeting(
            team_id,
            _QUESTION_ID,
            agent_runner=_candidate_generation_runner,
        )
        first_id = first["meetingRound"]["meetingRoundId"]
        first_meeting = meetings.get_meeting_round(team_id, first_id)["meetingRound"]
        meetings._append_round_record(
            team_id,
            {
                **first_meeting,
                "modelInvocationReceiptAuthority": _generation_receipt_authority(
                    team_id, "run-old"
                ),
            },
        )
        stopped = meetings.terminate_meeting_execution(
            team_id,
            first_id,
            reason="challenge_workflow_run_blocked",
        )["meetingRound"]
        assert len(meetings.completed_meeting_source_messages(stopped)) >= 2

        restarted = chain.open_candidate_generation_meeting(
            team_id,
            _QUESTION_ID,
            agent_runner=_empty_generation_runner,
            _model_invocation_receipt_authority=_generation_receipt_authority(
                team_id, "run-new"
            ),
        )

    assert restarted["status"] == "opened"
    assert restarted["meetingRound"]["meetingRoundId"] != first_id
    assert restarted["meetingRound"]["meetingRoundId"].endswith("-a2")
    assert restarted["meetingRound"]["modelInvocationReceiptAuthority"][
        "workflowRunId"
    ] == "run-new"
    assert chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)[
        "candidateCount"
    ] == 0


def test_active_generation_from_cancelled_run_does_not_block_new_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A same-question meeting is reusable only inside its workflow run."""

    from core.research.workflow.contracts.discussion_scope import (
        WorkflowDiscussionScopeV1,
    )
    from core.web.services.team_workflow import research_projects

    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    project_id = research_projects.create_research_project(
        team_id, {"name": "跨 run 会议隔离"}
    )["project"]["projectId"]
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )
    monkeypatch.setattr(
        selections,
        "_approved_candidate_ids",
        lambda _team_id, _question_id, *, workflow_run_id="": set(),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.meeting_receipt_authority.workflow_run_stop_reason",
        lambda _authority: "",
    )

    def generation_scope(run_id: str) -> dict[str, object]:
        return WorkflowDiscussionScopeV1.generation(
            teamId=team_id,
            researchProjectId=project_id,
            workflowRunId=run_id,
            workflowNodeId=chain.HYPOTHESIS_DESIGN_NODE_ID,
            questionId=_QUESTION_ID,
        ).to_dict()

    new_runner_calls: list[str] = []

    def new_runner(participant, prompt, context):
        new_runner_calls.append(str(participant.get("agentId") or ""))
        return _candidate_generation_runner(participant, prompt, context)

    with server_operator_scope("u-1", roles=("operator",)):
        old = chain.open_candidate_generation_meeting(
            team_id,
            _QUESTION_ID,
            agent_runner=_candidate_generation_runner,
            _model_invocation_receipt_authority=_generation_receipt_authority(
                team_id, "run-old"
            ),
            _discussion_scope=generation_scope("run-old"),
        )
        old_id = old["meetingRound"]["meetingRoundId"]
        old_meeting = meetings.get_meeting_round(team_id, old_id)["meetingRound"]
        chain._append_generation_candidates(
            team_id,
            old_meeting,
            [
                {
                    "statement": "旧运行候选不得进入新运行",
                    "rationale": "跨 run 隔离回归",
                    "proposedBy": "agent-old",
                }
            ],
        )
        old_snapshot = json.dumps(
            meetings.get_meeting_round(team_id, old_id)["meetingRound"],
            ensure_ascii=False,
            sort_keys=True,
        )

        with pytest.raises(
            chain.HypothesisFirstChainError,
            match="belong to different workflow runs",
        ):
            chain.open_candidate_generation_meeting(
                team_id,
                _QUESTION_ID,
                _model_invocation_receipt_authority=_generation_receipt_authority(
                    team_id, "run-new"
                ),
                _discussion_scope=generation_scope("run-other"),
            )

        assert chain.needs_candidate_generation(
            team_id, _QUESTION_ID, workflow_run_id="run-new"
        ) is True
        opened = chain.open_candidate_generation_meeting(
            team_id,
            _QUESTION_ID,
            agent_runner=new_runner,
            _model_invocation_receipt_authority=_generation_receipt_authority(
                team_id, "run-new"
            ),
            _discussion_scope=generation_scope("run-new"),
        )
        persisted_new = meetings.get_meeting_round(
            team_id, opened["meetingRound"]["meetingRoundId"]
        )["meetingRound"]
        assert chain._meeting_workflow_run_id(persisted_new) == "run-new"
        assert persisted_new["status"] == "awaiting_approval", persisted_new
        monkeypatch.setattr(
            meetings,
            "running_bound_round_ids",
            lambda meeting: list(meeting.get("chatRoomRoundIds") or []),
        )
        call_count_after_open = len(new_runner_calls)
        replayed = chain.open_candidate_generation_meeting(
            team_id,
            _QUESTION_ID,
            agent_runner=new_runner,
            _model_invocation_receipt_authority=_generation_receipt_authority(
                team_id, "run-new"
            ),
            _discussion_scope=generation_scope("run-new"),
        )

    new_id = opened["meetingRound"]["meetingRoundId"]
    assert opened["status"] == "opened"
    assert new_id != old_id
    assert new_id.endswith("-a2")
    assert opened["meetingRound"]["modelInvocationReceiptAuthority"][
        "workflowRunId"
    ] == "run-new"
    assert replayed["meetingRound"]["meetingRoundId"] == new_id
    assert len(new_runner_calls) == call_count_after_open
    assert json.dumps(
        meetings.get_meeting_round(team_id, old_id)["meetingRound"],
        ensure_ascii=False,
        sort_keys=True,
    ) == old_snapshot

    run_state = chain.chain_state(
        team_id, _QUESTION_ID, workflow_run_id="run-new"
    )
    assert run_state["generationMeetingId"] == new_id
    assert run_state["candidateCount"] == 0
    assert chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)[
        "candidateCount"
    ] == 1


def test_run_scoped_candidate_generation_reuses_formal_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two formal hypotheses already owned by this run skip a new meeting."""

    calls: list[tuple[str, str, str]] = []

    def approved_candidate_ids(team_id, question_id, *, workflow_run_id=""):
        calls.append((team_id, question_id, workflow_run_id))
        return {"formal-a", "formal-b"}

    monkeypatch.setattr(selections, "_approved_candidate_ids", approved_candidate_ids)
    monkeypatch.setattr(
        chain,
        "_question_generation_meetings",
        lambda _team_id, _question_id, *, workflow_run_id="": [],
    )

    assert (
        chain.needs_candidate_generation(
            "team-formal-artifact",
            _QUESTION_ID,
            workflow_run_id="run-formal-artifact",
        )
        is False
    )
    assert calls == [
        ("team-formal-artifact", _QUESTION_ID, "run-formal-artifact")
    ]


def test_review_scope_fallback_reads_candidates_from_the_same_workflow_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Ledger outage may reuse only the generation scope from this run."""

    from core.research.workflow.contracts.discussion_scope import (
        WorkflowDiscussionScopeV1,
    )

    generation_scope = WorkflowDiscussionScopeV1.generation(
        teamId="team-run-fallback",
        researchProjectId="project-run-fallback",
        workflowRunId="run-new",
        workflowNodeId=chain.HYPOTHESIS_DESIGN_NODE_ID,
        questionId=_QUESTION_ID,
    ).to_dict()
    calls: list[tuple[str, str]] = []

    def list_candidates(team_id, *, question_id="", workflow_run_id=""):
        calls.append(("candidates", workflow_run_id))
        return {
            "candidates": [
                {
                    "candidateId": "candidate-new",
                    "meetingRoundId": "generation-new",
                }
            ]
        }

    def list_generation_meetings(
        team_id, question_id, *, workflow_run_id=""
    ):
        calls.append(("meetings", workflow_run_id))
        return [
            {
                "meetingRoundId": "generation-new",
                "discussionScope": generation_scope,
            }
        ]

    monkeypatch.setattr(chain, "list_hypothesis_candidates", list_candidates)
    monkeypatch.setattr(
        chain, "_question_generation_meetings", list_generation_meetings
    )

    resolved = chain._review_discussion_scope_base(
        "team-run-fallback",
        _QUESTION_ID,
        ["candidate-new"],
        receipt_authority=None,
        workflow_run_id="run-new",
    )

    assert resolved is not None
    assert resolved.workflowRunId == "run-new"
    assert calls == [("candidates", "run-new"), ("meetings", "run-new")]


def test_human_adjudication_persists_and_checks_workflow_run_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newer round from another run cannot hide this run's current round."""

    target_round = {
        "roundId": "round-new",
        "status": "closed",
        "meetingRefs": [{"kind": "meeting_round", "id": "meeting-new"}],
    }
    other_run_round = {
        "roundId": "round-other",
        "status": "closed",
        "meetingRefs": [{"kind": "meeting_round", "id": "meeting-other"}],
    }
    monkeypatch.setattr(
        hrounds,
        "get_hypothesis_round",
        lambda _team_id, _round_id: {"round": target_round},
    )
    monkeypatch.setattr(
        chain,
        "_question_hypothesis_rounds",
        lambda _team_id, _question_id: [target_round, other_run_round],
    )

    def run_meetings(team_id, question_id, *, workflow_run_id=""):
        assert workflow_run_id == "run-new"
        return [{"meetingRoundId": "meeting-new"}]

    monkeypatch.setattr(chain, "_question_meetings", run_meetings)
    monkeypatch.setattr(
        chain,
        "_storage_path",
        lambda _team_id: tmp_path / "hypothesis_first_chain.jsonl",
    )

    result = chain.record_human_adjudication(
        "team-run-adjudication",
        question_id=_QUESTION_ID,
        hypothesis_round_id="round-new",
        decision="rejected",
        rationale="当前 run 的人工裁决",
        idempotency_key="adjudication-run-new",
        workflow_run_id="run-new",
    )

    assert result["status"] == "created"
    assert result["adjudication"]["workflowRunId"] == "run-new"
    assert result["adjudication"]["meetingRoundIds"] == ["meeting-new"]


# ---------------------------------------------------------------------------
# Convergence authority consumption: the appended human adjudication record
# must converge the latest round (with all new evidence requests handed off)
# so the readiness blocker ``hypothesis_round_unconverged`` clears.
# ---------------------------------------------------------------------------

_CONV_ROUND_ID = "hround-conv-5"
_CONV_MEETING_ID = "meeting-conv-5"
_CONV_RUN_ID = "run-conv"


def _adjudication_chain_fixture(
    *,
    decision: str | None,
    request_statuses: tuple[str, ...] = ("handed_off",),
    meta_accepted: bool = True,
    run_id: str = "",
) -> dict[str, Any]:
    return {
        "records": [
            {
                "recordKind": "review_round_link",
                "linkId": "link-conv-5",
                "selectionId": "selection-conv",
                "candidateId": "hyp-a",
                "candidateOrder": 0,
                "roundIndex": 5,
                "meetingRoundId": _CONV_MEETING_ID,
                "questionId": _QUESTION_ID,
                "workflowRunId": run_id,
                "createdAt": "2026-08-30T00:00:01Z",
            },
            *[
                {
                    "recordKind": "collection_request",
                    "requestId": f"request-conv-{index}",
                    "questionId": _QUESTION_ID,
                    "meetingRoundId": _CONV_MEETING_ID,
                    "status": status,
                    "createdAt": f"2026-08-30T00:01:{index:02d}Z",
                }
                for index, status in enumerate(request_statuses, start=1)
            ],
            *(
                []
                if decision is None
                else [
                    {
                        "recordKind": "human_adjudication",
                        "adjudicationId": f"hf-adjudication-conv-{decision}",
                        "idempotencyKey": f"conv-key-{decision}",
                        "questionId": _QUESTION_ID,
                        "hypothesisRoundId": _CONV_ROUND_ID,
                        "workflowRunId": run_id,
                        "meetingRoundIds": [_CONV_MEETING_ID],
                        "decision": decision,
                        "rationale": "challenge-cup adjudication",
                        "createdAt": "2026-08-30T00:02:00Z",
                        "updatedAt": "2026-08-30T00:02:00Z",
                    }
                ]
            ),
        ],
        "rounds": [
            {
                "roundId": _CONV_ROUND_ID,
                "question": _QUESTION_ID,
                "status": "closed",
                "roundIndex": 5,
                "metaReview": {
                    "metaReviewId": "mr-conv-5",
                    "recommendationCandidateId": "hyp-a",
                    "accepted": meta_accepted,
                },
                "meetingRefs": [{"kind": "meeting_round", "id": _CONV_MEETING_ID}],
                "createdAt": "2026-08-30T00:00:00Z",
            }
        ],
        "meetings": [{"meetingRoundId": _CONV_MEETING_ID, "status": "closed"}],
    }


def _convergence_chain_state_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    records: list[dict[str, Any]],
    rounds: list[dict[str, Any]],
    meetings: list[dict[str, Any]],
) -> None:
    monkeypatch.setattr(chain, "_records", lambda _team_id: records)
    monkeypatch.setattr(chain, "_question_meetings", lambda _t, _q, **_kw: meetings)
    monkeypatch.setattr(chain, "_question_hypothesis_rounds", lambda _t, _q: rounds)
    monkeypatch.setattr(chain, "_question_template_baselines", lambda _t, _q: [])
    monkeypatch.setattr(
        chain, "_question_generation_meetings", lambda _t, _q, **_kw: []
    )


def _allow_chain_claim_belief_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    def _allow(_team_id, _question_id, candidate_ids):
        return {
            candidate_id: {
                "status": "allowed",
                "reason": "",
                "claims": [],
                "blockedClaims": [],
            }
            for candidate_id in candidate_ids
        }

    monkeypatch.setattr(chain, "evaluate_claim_belief_gate", _allow)


def test_accepted_adjudication_converges_exhausted_round_with_handed_off_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 5/5 closed, meta review accepted, new evidence requests all
    handed off, human adjudication accepted -> chain_state converges, the
    detail names the adjudication, and budget exhaustion clears."""
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    _convergence_chain_state_env(
        monkeypatch, **_adjudication_chain_fixture(decision="accepted")
    )
    _allow_chain_claim_belief_gate(monkeypatch)

    state = chain.chain_state(team_id, _QUESTION_ID)

    assert state["hypothesisConverged"] is True
    assert "人工裁决" in state["convergenceDetail"]
    assert state["budgetExhausted"] is False
    assert state["pendingCollectionCount"] == 0
    assert state["claimBeliefGate"]["status"] == "allowed"


def test_accepted_adjudication_converges_within_workflow_run_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The formal readiness path reads chain_state scoped by runId; an
    adjudication recorded for that run must converge exactly there."""
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    _convergence_chain_state_env(
        monkeypatch,
        **_adjudication_chain_fixture(decision="accepted", run_id=_CONV_RUN_ID),
    )
    _allow_chain_claim_belief_gate(monkeypatch)

    state = chain.chain_state(team_id, _QUESTION_ID, workflow_run_id=_CONV_RUN_ID)

    assert state["hypothesisConverged"] is True
    assert "人工裁决" in state["convergenceDetail"]
    assert state["budgetExhausted"] is False


def test_accepted_adjudication_cannot_waive_pending_collection_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pending collection request blocks convergence in every case: the
    adjudication must never waive unfinished evidence handoffs."""
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    _convergence_chain_state_env(
        monkeypatch,
        **_adjudication_chain_fixture(
            decision="accepted",
            request_statuses=("handed_off", "collecting"),
        ),
    )

    state = chain.chain_state(team_id, _QUESTION_ID)

    assert state["hypothesisConverged"] is False
    assert state["convergenceDetail"] == "仍有待交接的搜集请求"
    assert state["pendingCollectionCount"] == 1


def test_unadjudicated_new_requests_keep_exhausted_round_unconverged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a human adjudication, an exhausted round whose new evidence
    requests are all handed off stays unconverged and waits for the manual
    decision (the production run-16cfab646d08 deadlock state)."""
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    _convergence_chain_state_env(
        monkeypatch, **_adjudication_chain_fixture(decision=None)
    )

    state = chain.chain_state(team_id, _QUESTION_ID)

    assert state["hypothesisConverged"] is False
    assert "产生了新的搜集决策" in state["convergenceDetail"]
    assert state["budgetExhausted"] is True


def test_rejected_adjudication_keeps_round_unconverged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected human adjudication is terminal: the round never converges
    and the budget stays exhausted."""
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    _convergence_chain_state_env(
        monkeypatch, **_adjudication_chain_fixture(decision="rejected")
    )

    state = chain.chain_state(team_id, _QUESTION_ID)

    assert state["hypothesisConverged"] is False
    assert state["convergenceDetail"] == f"最近一轮 {_CONV_ROUND_ID} 已被人工裁决拒绝"
    assert state["budgetExhausted"] is True


def _empty_generation_runner(participant, prompt, context):
    """Discussion happens but nobody proposes a CANDIDATE marker."""
    return {
        "status": "completed",
        "raw_output": "AGREE: 现有证据不足以提出可证伪候选",
        "summary": "ok",
    }


def _failed_generation_runner(participant, prompt, context):
    return {
        "status": "failed",
        "errorType": "protocol_error",
        "summary": "speaker failed before producing discussion evidence",
    }


def test_failed_generation_attempt_can_be_superseded_and_restarted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )

    with server_operator_scope("u-1", roles=("operator",)):
        failed = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_failed_generation_runner
        )
        first_id = failed["meetingRound"]["meetingRoundId"]

        restarted = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )

    second_id = restarted["meetingRound"]["meetingRoundId"]
    assert second_id != first_id
    assert second_id.endswith("-a2")
    first = meetings.get_meeting_round(team_id, first_id)["meetingRound"]
    assert first["status"] == "closed"
    assert first["recoveryReason"] == "discussion_has_no_completed_messages"
    assert first["summaryDraftError"]["code"] == "discussion_has_no_completed_messages"
    assert restarted["status"] == "opened"


def test_closed_generation_without_candidates_allows_a_fresh_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closed generation attempt with zero proposals must not deadlock the
    cold start: the next open rolls to a new per-attempt meeting id."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )

    with server_operator_scope("u-1", roles=("operator",)):
        opened = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_empty_generation_runner
        )
        first_id = opened["meetingRound"]["meetingRoundId"]
        agent_ids = [agents[role] for role in _ROLES]
        # The discussion yields no CANDIDATE markers; closing it records the
        # empty outcome as a fact (the digest carries zero proposals).
        _drive_to_awaiting_approval(team_id, first_id, agent_ids[0])
        closed = chain.close_review_meeting(
            team_id,
            first_id,
            _closure_payload(agent_ids, []),
        )
        assert closed["meetingRound"]["status"] == "closed"
        assert closed["candidateCount"] == 0
        assert chain.needs_candidate_generation(team_id, _QUESTION_ID) is False

        regenerated = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )
        assert regenerated["status"] == "opened"
        second_id = regenerated["meetingRound"]["meetingRoundId"]
        assert second_id != first_id

        _drive_to_awaiting_approval(team_id, second_id, agent_ids[0])
        closed_second = chain.close_review_meeting(
            team_id,
            second_id,
            _closure_payload(agent_ids, []),
        )
        assert closed_second["candidateCount"] == 2
        assert chain.needs_candidate_generation(team_id, _QUESTION_ID) is False


def test_failed_review_round_can_be_reopened_with_next_budgeted_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A review round whose every speaker failed restarts as the next round.

    The blocked summarize path surfaces ``重新发起讨论`` for review rounds;
    ``reopen_failed_review_meeting`` supersedes the failed attempt
    (append-only, no digest) and opens round 2 with the same selection
    lineage and the fixed candidate context in its topic."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    with server_operator_scope("u-1", roles=("operator",)):
        failed = selections.record_hypothesis_selection(
            team_id,
            _selection_payload(agent_ids[0]),
            agent_runner=_failed_generation_runner,
        )
        assert failed["reviewMeeting"]["status"] == "opened"
        first_id = failed["reviewMeeting"]["meetingRound"]["meetingRoundId"]

        reopened = chain.reopen_failed_review_meeting(
            team_id,
            first_id,
            agent_runner=_marker_runner,
        )

    assert reopened["status"] == "reopened"
    superseded = reopened["supersededMeetingRound"]
    assert superseded["status"] == "closed"
    assert superseded["recoveryReason"] == "discussion_has_no_completed_messages"
    second = reopened["meetingRound"]
    assert second["meetingRoundId"] != first_id
    assert second["meetingRoundId"].endswith("-r2")
    assert second["status"] in {"open", "summarizing"}
    assert reopened["roundIndex"] == 2

    first = meetings.get_meeting_round(team_id, first_id)["meetingRound"]
    assert first["status"] == "closed"


def _hyp_a_failed_review_runner(participant, prompt, context):
    """hyp-a's discussion all fails (zero completed messages); hyp-b speaks."""
    if "candidate hyp-b" in str(prompt):
        return _marker_runner(participant, prompt, context)
    return {
        "status": "failed",
        "errorType": "protocol_error",
        "summary": "speaker failed before producing discussion evidence",
    }


def test_sibling_close_after_supersede_reopen_generates_round_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: after supersede+reopen the sibling close must not fail.

    Candidate hyp-a's round 1 produced no successful speech and was superseded
    (append-only, no digest) then reopened as round 2.  Closing the sibling
    hyp-b round-1 review used to raise "closed meeting ... is missing digestId
    or decisionRefs" because the fan-in treated any closed meeting as
    authority.  Now the sibling close reports waiting; once hyp-a's round 2
    closes, the group binds each candidate's newest authoritative attempt and
    generates the round, and replaying hyp-b's close reuses the same round
    idempotently.
    """
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    with server_operator_scope("u-1", roles=("operator",)):
        recorded = selections.record_hypothesis_selection(
            team_id,
            _selection_payload(agent_ids[0]),
            agent_runner=_hyp_a_failed_review_runner,
        )
        assert len(_review_meetings(recorded)) == 2
        meeting_a1 = next(
            str(link["meetingRoundId"])
            for link in chain.list_review_round_links(
                team_id, question_id=_QUESTION_ID
            )["links"]
            if str(link["candidateId"]) == "hyp-a"
            and int(link["roundIndex"]) == 1
        )

        reopened = chain.reopen_failed_review_meeting(
            team_id,
            meeting_a1,
            agent_runner=_marker_runner,
        )
        assert reopened["status"] == "reopened"
        superseded = reopened["supersededMeetingRound"]
        assert superseded["status"] == "closed"
        assert superseded["recoveryReason"] == "discussion_has_no_completed_messages"
        meeting_a2 = str(reopened["meetingRound"]["meetingRoundId"])
        assert meeting_a2.endswith("-r2")

        meeting_b1 = next(
            str(link["meetingRoundId"])
            for link in chain.list_review_round_links(
                team_id, question_id=_QUESTION_ID
            )["links"]
            if str(link["candidateId"]) == "hyp-b"
            and int(link["roundIndex"]) == 1
        )

        # The sibling close lands while hyp-a's round 2 is still open: the
        # superseded round-1 attempt must not act as authority, and the close
        # must not raise on the digest-less meeting.
        _drive_to_awaiting_approval(team_id, meeting_b1, agent_ids[0])
        closed_b = chain.close_review_meeting(
            team_id,
            meeting_b1,
            _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
        )
        assert closed_b["meetingRound"]["status"] == "closed"
        assert (
            closed_b["hypothesisRound"]["status"] == "waiting_for_sibling_reviews"
        )
        assert closed_b["hypothesisRound"]["pendingMeetingRoundIds"] == [meeting_a2]
        assert closed_b["hypothesisRound"]["supersededMeetingRoundIds"] == [
            str(superseded["meetingRoundId"])
        ]

        _drive_to_awaiting_approval(team_id, meeting_a2, agent_ids[0])
        closed_a2 = chain.close_review_meeting(
            team_id,
            meeting_a2,
            _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
        )
        # The candidate-scoped round-2 follow-up generates its own round.
        assert closed_a2["hypothesisRound"]["status"] == "created"
        generated_round = closed_a2["hypothesisRound"]["round"]
        generated_meeting_ids = {
            str(ref.get("id") or "")
            for ref in list(generated_round.get("meetingRefs") or [])
            if str(ref.get("kind") or "") == "meeting_round"
        }
        assert generated_meeting_ids == {meeting_a2}

        # Replaying the previously structurally-failed close binds each
        # candidate's newest authoritative attempt across rounds (hyp-a ->
        # round 2, hyp-b -> round 1) and generates the merged round without
        # raising on the digest-less superseded meeting.
        replayed_b = chain.close_review_meeting(
            team_id,
            meeting_b1,
            _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
        )
        assert replayed_b["hypothesisRound"]["status"] == "created"
        merged_round = replayed_b["hypothesisRound"]["round"]
        merged_meeting_ids = {
            str(ref.get("id") or "")
            for ref in list(merged_round.get("meetingRefs") or [])
            if str(ref.get("kind") or "") == "meeting_round"
        }
        assert merged_meeting_ids == {meeting_a2, meeting_b1}
        assert merged_round["roundId"] != generated_round["roundId"]

        # A further replay of the same close reuses the merged round.
        replayed_again = chain.close_review_meeting(
            team_id,
            meeting_b1,
            _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
        )
        assert replayed_again["hypothesisRound"]["status"] == "reused"
        assert (
            replayed_again["hypothesisRound"]["round"]["roundId"]
            == merged_round["roundId"]
        )


def test_reopen_refuses_review_round_with_successful_speech(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rounds with citable completed messages must close through the
    four-state gate, not the failed-discussion recovery."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]

        with pytest.raises(meetings.ResearchMeetingRoundError):
            chain.reopen_failed_review_meeting(team_id, meeting_id)


def test_converged_chain_without_evidence_requests_is_collection_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A review chain that legitimately concluded "no additional collection"
    (converged, all rounds closed, zero evidence requests) must not wedge the
    first source-collection round: the closure decision itself is the scope."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            _seed_claim_belief_gate_fixture(
                monkeypatch, team_id, _QUESTION_ID, ["hyp-a", "hyp-b"]
            )
            sibling_meetings = _review_meetings(recorded)
            assert len(sibling_meetings) == 2
            for sibling in sibling_meetings:
                meeting_id = sibling["meetingRoundId"]
                _drive_to_awaiting_approval(team_id, meeting_id, agent_ids[0])
                closed = chain.close_review_meeting(
                    team_id,
                    meeting_id,
                    _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                    runtime=runtime,
                )
                assert closed["meetingRound"]["status"] == "closed"

            state = chain.chain_state(team_id, _QUESTION_ID)
            assert state["hypothesisConverged"] is True
            assert state["openMeetingIds"] == []
            assert state["collectionRequestCount"] == 0
            assert state["collectionReady"] is True

            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" not in _blocker_codes(finding)
    finally:
        runtime.close()


def test_later_review_round_supersedes_unfinished_historical_sibling_for_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sibling archive gate defers the handoff's open-next until the last
    sibling digest is confirmed; afterwards only the newest logical round can
    block collection, so a stale unfinished sibling room (historical data or a
    crash residue) can never wedge the formal source_finding node."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            first_round_meetings = _review_meetings(recorded)
            assert len(first_round_meetings) == 2
            first_meeting_id = first_round_meetings[0]["meetingRoundId"]
            historical_sibling_id = first_round_meetings[1]["meetingRoundId"]
            closed_first = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            request = closed_first["collection"]["requests"][0]

            # The sibling is still mid-review: the handoff must defer the
            # next round instead of overwriting the sibling's approval gate.
            handoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            deferred = handoff["nextMeeting"]
            assert deferred["status"] == "sibling_reviews_pending"
            assert deferred["pendingMeetingRoundIds"] == [historical_sibling_id]
            links = chain.list_review_round_links(team_id, question_id=_QUESTION_ID)[
                "links"
            ]
            assert {int(link["roundIndex"]) for link in links} == {1}
            state = chain.chain_state(team_id, _QUESTION_ID)
            assert historical_sibling_id in state["openMeetingIds"]

            # Confirming the last sibling archives the logical round and
            # re-opens the deferred round.
            _drive_to_awaiting_approval(team_id, historical_sibling_id, agent_ids[0])
            closed_sibling = chain.close_review_meeting(
                team_id,
                historical_sibling_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            triggered = closed_sibling["deferredNextReview"]
            assert triggered["status"] in {"opened", "created", "reused"}
            later_meetings = _opened_review_meetings(triggered)
            assert later_meetings
            for meeting in later_meetings:
                meeting_id = meeting["meetingRoundId"]
                _drive_to_awaiting_approval(team_id, meeting_id, agent_ids[0])
                chain.close_review_meeting(
                    team_id,
                    meeting_id,
                    _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                    runtime=runtime,
                )

            historical = meetings.get_meeting_round(
                team_id, historical_sibling_id
            )["meetingRound"]
            assert historical["status"] == "closed"
            state = chain.chain_state(team_id, _QUESTION_ID)
            assert state["openMeetingIds"] == []
            assert state["collectionReady"] is True
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" not in _blocker_codes(finding)

            # Stale residue: an unfinished historical sibling room must not
            # block collection readiness once a newer archived round supplied
            # the scope (its approve entry stays projected by the state v2
            # fallback, not by the readiness scan).
            stale_record = {
                **historical,
                "status": "open",
                "digestDraft": {},
                "digestId": "",
                "decisionRefs": [],
                "closureHash": "",
            }
            with meetings._rounds_path(team_id).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(stale_record, ensure_ascii=False) + "\n")
            state = chain.chain_state(team_id, _QUESTION_ID)
            assert historical_sibling_id not in state["openMeetingIds"]
            assert state["collectionReady"] is True
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" not in _blocker_codes(finding)
    finally:
        runtime.close()


def test_evidence_request_probe_is_scoped_per_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One question's evidence request must not block another question's
    collection-ready waiver (team-wide scans are fatal for the 125-question
    batch)."""
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    root = (
        developer_sandbox.seeded_sandbox_workspace_path(
            chain._project_root(), "teams", chain._safe_team_id(team_id)
        )
        / "research_workflow"
    )
    root.mkdir(parents=True, exist_ok=True)
    scope = _scope_fields("agent-1")
    meetings_path = root / "meeting_rounds.jsonl"
    with meetings_path.open("w", encoding="utf-8") as fh:
        for round_id, question in (
            ("mtg-sci001", "SCI-001"),
            ("mtg-sci002", "SCI-002"),
        ):
            fh.write(
                json.dumps(
                    {
                        **scope,
                        "schemaVersion": 1,
                        "meetingRoundId": round_id,
                        "meetingType": "hypothesis_review",
                        "question": question,
                        "status": "closed",
                        "participants": ["agent-1"],
                        "startedAt": "2026-08-20T01:00:00Z",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    decisions_path = root / "decision_records.jsonl"
    with decisions_path.open("w", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "decisionId": "dec-x",
                    "decision": "request_new_evidence",
                    "rationale": "SCI-002 需要补充证据",
                    "decidedBy": "agent-1",
                    "candidateRefs": [],
                    "evidenceRefs": [],
                    "status": "adopted",
                    "meetingRoundId": "mtg-sci002",
                    "scopeHash": scope["scopeHash"] if "scopeHash" in scope else "sh",
                    "createdAt": "2026-08-20T02:00:00Z",
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    assert chain._question_requested_evidence(team_id, "SCI-001") is False
    assert chain._question_requested_evidence(team_id, "SCI-002") is True
    assert chain._question_requested_evidence(team_id, "") is False


def test_candidate_evidence_trail_cites_discussion_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trail maps each ledger candidate to the speeches that cite it."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    with server_operator_scope("u-1", roles=("operator",)):
        _open_first_meeting(team_id, agent_ids)
        storage = chain._storage_path(team_id)
        with storage.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "schemaVersion": chain.SCHEMA_VERSION,
                        "recordKind": chain.CANDIDATE_KIND,
                        "candidateId": "hyp-a",
                        "questionId": _QUESTION_ID,
                        "statement": "hyp-a 陈述",
                        "rationale": "机制",
                        "proposedBy": "agent",
                        "meetingRoundId": "",
                        "createdAt": "2026-08-20T00:00:00Z",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        result = chain.candidate_evidence_trail(team_id, _QUESTION_ID)

    by_id = {
        trail["candidateId"]: trail["entries"] for trail in result["trails"]
    }
    assert "hyp-a" in by_id
    entries = by_id["hyp-a"]
    assert entries, "review speeches citing cand-a must appear in the trail"
    assert all("hyp-a" in entry["excerpt"] for entry in entries)
    assert all(entry["meetingLabel"].startswith("评审") for entry in entries)
    assert all(entry["messageId"] for entry in entries)

    empty = chain.candidate_evidence_trail(team_id, "SCI-999")
    assert empty["trails"] == []


# ---------------------------------------------------------------------------
# close_review_meeting: the meeting's server-owned scope mode fences the
# auto-injected review runners (formal -> provider-bound receipts required,
# and without real runners the closure fails closed instead of sliding onto
# the DEV fixtures; dev -> receipt-free fixture fallback unchanged)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "expected_receipts"),
    [("formal", True), ("dev", False)],
)
def test_close_review_meeting_fences_auto_injected_runners_by_meeting_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str, expected_receipts: bool
) -> None:
    from core.web.services.team_workflow import llm_review_runners

    team_id = f"team-fence-{mode}"
    meeting_round_id = f"meeting-fence-{mode}"
    build_calls: list[dict[str, object]] = []
    closure_calls: list[dict[str, object]] = []

    def fake_get_meeting_round(_team_id, round_id):
        assert round_id == meeting_round_id
        return {
            "meetingRound": {
                "meetingRoundId": meeting_round_id,
                "meetingType": chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
                "question": _QUESTION_ID,
                "mode": mode,
            }
        }

    def fake_approve_meeting_closure(_team_id, _round_id, _request):
        closure_calls.append({"roundId": _round_id})
        return {
            "meetingRound": {
                "meetingRoundId": meeting_round_id,
                "meetingType": chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
                "question": _QUESTION_ID,
                "mode": mode,
            }
        }

    def fake_build_runners(llm=None, *, require_provider_receipts=False):
        build_calls.append({"require_provider_receipts": require_provider_receipts})
        return None

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(meetings, "get_meeting_round", fake_get_meeting_round)
    monkeypatch.setattr(
        meetings, "approve_meeting_closure", fake_approve_meeting_closure
    )
    monkeypatch.setattr(
        llm_review_runners, "build_hypothesis_review_runners", fake_build_runners
    )
    monkeypatch.setattr(
        chain,
        "_process_collection_decisions",
        lambda *_args, **_kwargs: {"status": "ignored"},
    )
    monkeypatch.setattr(
        chain,
        "_generate_hypothesis_round",
        lambda _team_id, closed_record, **_kwargs: {
            "status": "created",
            "roundId": "hround-fence",
            "round": {"roundId": "hround-fence", "mode": closed_record.get("mode")},
        },
    )

    if mode == chain.HYPOTHESIS_REVIEW_FORMAL_MODE:
        # Formal fence: without real receipt-bound runners a formal review
        # meeting must never close onto the deterministic DEV fixtures; the
        # closure fails fast with an actionable structured error.
        with pytest.raises(chain.HypothesisFirstChainError) as excinfo:
            chain.close_review_meeting(team_id, meeting_round_id)

        assert build_calls == [{"require_provider_receipts": expected_receipts}]
        assert closure_calls == []
        message = str(excinfo.value)
        assert meeting_round_id in message
        assert "receipt-bound review runners" in message
        assert "dev/platform scope" in message
        return

    result = chain.close_review_meeting(team_id, meeting_round_id)

    assert build_calls == [{"require_provider_receipts": expected_receipts}]
    assert closure_calls
    assert result["hypothesisRound"]["status"] == "created"


# ---------------------------------------------------------------------------
# review dispatch retry: terminated meetings must never satisfy a retry
# (regression for the reused-no-op deadlock on retry_review_dispatch)


def _retry_dispatch_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selection_id: str,
):
    """Real chain/attempt/link storage with meeting side effects in memory."""

    from core.web.services.team_workflow.research_runtime import (
        meeting_receipt_authority,
    )

    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        meeting_receipt_authority,
        "resolve_active_question_authority",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        chain,
        "list_hypothesis_candidates",
        lambda *_args, **_kwargs: {"candidates": []},
    )
    meetings_store: dict[str, dict[str, object]] = {}

    def fake_get_meeting_round(_team_id: str, meeting_round_id: str):
        record = meetings_store.get(str(meeting_round_id))
        if record is None:
            raise meetings.ResearchMeetingRoundNotFoundError("missing")
        return {
            "schemaVersion": meetings.SCHEMA_VERSION,
            "teamId": _team_id,
            "meetingRound": record,
        }

    opened_ids: list[str] = []

    def fake_open(_team_id: str, payload, **_kwargs):
        meeting_round_id = str(payload["meetingRoundId"])
        opened_ids.append(meeting_round_id)
        record = {
            "meetingRoundId": meeting_round_id,
            "meetingType": chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            "status": "open",
            "question": _QUESTION_ID,
            "linkedChatRoomId": f"room-{meeting_round_id}",
            "chatRoomRoundIds": [f"room-round-{meeting_round_id}"],
        }
        meetings_store[meeting_round_id] = record
        return {
            "schemaVersion": meetings.SCHEMA_VERSION,
            "status": "created",
            "teamId": _team_id,
            "meetingRound": dict(record),
            "roomId": record["linkedChatRoomId"],
            "roundId": record["chatRoomRoundIds"][-1],
            "chatRoomRoundIds": list(record["chatRoomRoundIds"]),
        }

    monkeypatch.setattr(meetings, "get_meeting_round", fake_get_meeting_round)
    monkeypatch.setattr(meeting_runtime, "open_hypothesis_review_meeting", fake_open)

    driver_calls: list[str] = []

    def fake_schedule(_team_id: str, meeting_round_id: str):
        driver_calls.append(str(meeting_round_id))
        return {"status": "scheduled", "meetingRoundId": str(meeting_round_id)}

    monkeypatch.setattr(meeting_runtime, "schedule_meeting_discussion", fake_schedule)

    selection = {
        **_selection_payload("agent-a"),
        "selectionId": selection_id,
    }
    monkeypatch.setattr(
        selections,
        "get_hypothesis_selection",
        lambda _team_id, _selection_id: {"selection": dict(selection)},
    )
    return team_id, selection, meetings_store, opened_ids, driver_calls


def _attempts_for(attempts: list[dict], candidate_id: str) -> list[dict]:
    return [
        item
        for item in attempts
        if str(item.get("candidateId") or "") == candidate_id
    ]


def test_retry_review_dispatch_reopens_fresh_meeting_after_terminal_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A terminated review never satisfies a retry: a fresh attempt opens."""

    selection_id = "selection-retry-terminal"
    team_id, selection, meetings_store, opened_ids, driver_calls = (
        _retry_dispatch_env(tmp_path, monkeypatch, selection_id)
    )

    first = chain.open_review_meeting_for_selection(
        team_id, selection, background=True
    )
    assert first["candidateCount"] == 2
    base_meeting_id = chain._candidate_review_meeting_id(selection_id, "hyp-a", 1)
    sibling_meeting_id = chain._candidate_review_meeting_id(selection_id, "hyp-b", 1)
    assert opened_ids == [base_meeting_id, sibling_meeting_id]
    assert driver_calls == [base_meeting_id, sibling_meeting_id]

    terminated = meetings_store[base_meeting_id]
    terminated["status"] = "closed"
    terminated["terminalReason"] = "review_rejected"

    retried = chain.retry_review_dispatch(team_id, selection_id, ["hyp-a"])

    fresh_meeting_id = f"{base_meeting_id}-a2"
    assert retried["status"] == "created"
    assert retried["meetingRound"]["meetingRoundId"] == fresh_meeting_id
    assert opened_ids[-1] == fresh_meeting_id
    assert driver_calls == [base_meeting_id, sibling_meeting_id, fresh_meeting_id]
    assert meetings_store[fresh_meeting_id]["status"] == "open"

    attempts = chain.list_review_dispatch_attempts(
        team_id, selection_id=selection_id
    )["attempts"]
    hyp_a_attempts = _attempts_for(attempts, "hyp-a")
    assert [int(item.get("attemptNumber") or 0) for item in hyp_a_attempts] == [1, 2]
    assert hyp_a_attempts[-1]["lifecycle"] == "completed"
    assert hyp_a_attempts[-1]["meetingRoundId"] == fresh_meeting_id
    # Only the requested candidate retries; the sibling attempt never advances.
    assert [
        int(item.get("attemptNumber") or 0) for item in _attempts_for(attempts, "hyp-b")
    ] == [1]


def test_retry_review_dispatch_reuses_live_meeting_without_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An in-flight review stays idempotent under repeated dispatch."""

    selection_id = "selection-retry-live"
    team_id, selection, _meetings_store, opened_ids, _driver_calls = (
        _retry_dispatch_env(tmp_path, monkeypatch, selection_id)
    )

    chain.open_review_meeting_for_selection(team_id, selection, background=True)
    assert len(opened_ids) == 2
    base_meeting_id = chain._candidate_review_meeting_id(selection_id, "hyp-a", 1)

    retried = chain.retry_review_dispatch(
        team_id, selection_id, ["hyp-a", "hyp-b"]
    )

    assert retried["status"] == "reused"
    assert retried["meetingRound"]["meetingRoundId"] == base_meeting_id
    assert retried["meetingRound"]["status"] == "open"
    assert len(opened_ids) == 2

    attempts = chain.list_review_dispatch_attempts(
        team_id, selection_id=selection_id
    )["attempts"]
    for candidate_id in ("hyp-a", "hyp-b"):
        candidate_attempts = _attempts_for(attempts, candidate_id)
        assert [int(item.get("attemptNumber") or 0) for item in candidate_attempts] == [1]
        assert (
            len({str(item.get("attemptId") or "") for item in candidate_attempts}) == 1
        )


def test_retry_review_dispatch_rebinds_review_link_to_fresh_meeting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a retry the review round binds the candidate to the new meeting."""

    selection_id = "selection-retry-link"
    team_id, selection, meetings_store, _opened_ids, _driver_calls = (
        _retry_dispatch_env(tmp_path, monkeypatch, selection_id)
    )

    chain.open_review_meeting_for_selection(team_id, selection, background=True)
    base_meeting_id = chain._candidate_review_meeting_id(selection_id, "hyp-a", 1)
    terminated = meetings_store[base_meeting_id]
    terminated["status"] = "closed"
    terminated["terminalReason"] = "review_rejected"

    chain.retry_review_dispatch(team_id, selection_id, ["hyp-a"])

    links = [
        item
        for item in chain._review_round_links(chain._records(team_id))
        if str(item.get("selectionId") or "") == selection_id
        and str(item.get("candidateId") or "") == "hyp-a"
    ]
    assert [str(item.get("meetingRoundId") or "") for item in links] == [
        base_meeting_id,
        f"{base_meeting_id}-a2",
    ]
    # The newest durable link is the resolution target: the candidate is no
    # longer bound to the terminated meeting, and history stays append-only.
    assert links[-1]["meetingRoundId"] == f"{base_meeting_id}-a2"
    assert int(links[-1]["roundIndex"] or 0) == 1
    assert links[0]["meetingRoundId"] == base_meeting_id


def _hold_open_window_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selection_id: str,
):
    """``_retry_dispatch_env`` plus an observable, holdable open window.

    The first ``open_hypothesis_review_meeting`` caller blocks inside the
    open window (exactly the TOCTOU gap C3 closes) until the test releases
    it, while recording how many callers reached the open at all.
    """

    team_id, selection, meetings_store, opened_ids, driver_calls = (
        _retry_dispatch_env(tmp_path, monkeypatch, selection_id)
    )
    guarded_open = meeting_runtime.open_hypothesis_review_meeting
    guard = threading.Lock()
    state = {"openCalls": 0}
    first_entered = threading.Event()
    release_open = threading.Event()

    def slow_open(_team_id: str, payload, **kwargs):
        with guard:
            state["openCalls"] += 1
            call_index = state["openCalls"]
        if call_index == 1:
            first_entered.set()
            release_open.wait(timeout=10)
        return guarded_open(_team_id, payload, **kwargs)

    monkeypatch.setattr(meeting_runtime, "open_hypothesis_review_meeting", slow_open)
    return (
        team_id,
        selection,
        meetings_store,
        opened_ids,
        state,
        first_entered,
        release_open,
    )


def test_concurrent_same_candidate_dispatch_opens_meeting_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two dispatches racing one candidate converge on a single open (C3)."""

    selection_id = "selection-concurrent-dispatch"
    (
        team_id,
        selection,
        _meetings_store,
        opened_ids,
        state,
        first_entered,
        release_open,
    ) = _hold_open_window_env(tmp_path, monkeypatch, selection_id)

    barrier = threading.Barrier(2)
    results: list[Any] = [None, None]

    def worker(index: int) -> None:
        barrier.wait(timeout=5)
        results[index] = chain.open_review_meeting_for_selection(
            team_id, selection, background=True
        )

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    assert first_entered.wait(timeout=5)
    # While the first dispatch is still inside the open window, give the
    # second one time to reach the guarded sequence: before the C3 lock it
    # would start a duplicate discussion round for the same meeting.
    time.sleep(0.2)
    assert state["openCalls"] == 1
    release_open.set()
    for thread in threads:
        thread.join(timeout=30)

    # Exactly one open per candidate meeting; the loser replays as reused.
    assert state["openCalls"] == 2
    assert len(opened_ids) == 2
    assert len(set(opened_ids)) == 2
    statuses = sorted(item["status"] for item in results)
    assert statuses == ["created", "reused"]
    for item in results:
        assert item["candidateCount"] == 2
        assert item["meetingRound"]["status"] == "open"
    attempts = chain.list_review_dispatch_attempts(
        team_id, selection_id=selection_id
    )["attempts"]
    for candidate_id in ("hyp-a", "hyp-b"):
        candidate_attempts = _attempts_for(attempts, candidate_id)
        assert [int(item.get("attemptNumber") or 0) for item in candidate_attempts] == [1]
        assert (
            len({str(item.get("attemptId") or "") for item in candidate_attempts}) == 1
        )


def test_retry_and_auto_dispatch_converge_on_one_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A human RETRY racing the automatic dispatch never doubles the open (C3)."""

    selection_id = "selection-retry-race"
    (
        team_id,
        selection,
        _meetings_store,
        opened_ids,
        state,
        first_entered,
        release_open,
    ) = _hold_open_window_env(tmp_path, monkeypatch, selection_id)

    barrier = threading.Barrier(2)
    results: list[Any] = [None, None]

    def auto_dispatch() -> None:
        barrier.wait(timeout=5)
        results[0] = chain.open_review_meeting_for_selection(
            team_id, selection, background=True
        )

    def human_retry() -> None:
        barrier.wait(timeout=5)
        results[1] = chain.retry_review_dispatch(
            team_id, selection_id, ["hyp-a", "hyp-b"]
        )

    threads = [
        threading.Thread(target=auto_dispatch),
        threading.Thread(target=human_retry),
    ]
    for thread in threads:
        thread.start()
    assert first_entered.wait(timeout=5)
    time.sleep(0.2)
    assert state["openCalls"] == 1
    release_open.set()
    for thread in threads:
        thread.join(timeout=30)

    assert state["openCalls"] == 2
    assert len(opened_ids) == 2
    assert len(set(opened_ids)) == 2
    for item in results:
        assert item["status"] in {"created", "reused"}
        assert item["candidateCount"] == 2
        assert item["meetingRound"]["status"] == "open"
    attempts = chain.list_review_dispatch_attempts(
        team_id, selection_id=selection_id
    )["attempts"]
    for candidate_id in ("hyp-a", "hyp-b"):
        candidate_attempts = _attempts_for(attempts, candidate_id)
        assert [int(item.get("attemptNumber") or 0) for item in candidate_attempts] == [1]
        assert (
            len({str(item.get("attemptId") or "") for item in candidate_attempts}) == 1
        )


def test_stage_one_run_consumes_origin_drafts_and_skips_second_r0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SCI-091 field shape: origin-layer R0 drafts feed a run-scoped R1.

    The origin R0 round closed with drafts before any run existed.  When the
    stage-one run appears, its grounded R1 must consume the same-question
    origin drafts (lineage keeps the origin meeting id), and a further run
    creation must not open a second exploratory round on top of them.
    """
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    from core.research.workflow.contracts.discussion_scope import (
        WorkflowDiscussionScopeV1,
    )
    from core.web.services.team_workflow.research_projects import (
        ensure_challenge_question_project,
    )

    project_id = str(
        ensure_challenge_question_project(
            team_id,
            question_id=_QUESTION_ID,
            title="SCI-096 深度实验",
            topic="sleep",
        )["project"]["projectId"]
    )
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )
    run_id = "run-stage-one-origin-drafts"

    with server_operator_scope("u-1", roles=("operator",)):
        # Origin-layer R0 (no run binding) closes with two drafts.
        opened_r0 = chain.open_candidate_generation_meeting(
            team_id,
            _QUESTION_ID,
            agent_runner=_candidate_generation_runner,
            _candidate_authority="exploratory_draft",
        )
        r0_id = opened_r0["meetingRound"]["meetingRoundId"]
        agent_ids = [agents[role] for role in _ROLES]
        _drive_to_awaiting_approval(team_id, r0_id, agent_ids[0])
        closed_r0 = chain.close_review_meeting(
            team_id, r0_id, _closure_payload(agent_ids, [])
        )
        assert closed_r0["draftCount"] == 2
        drafts = chain.list_exploratory_drafts(
            team_id, question_id=_QUESTION_ID
        )["drafts"]
        draft_ids = {
            str(item.get("draftId") or item.get("candidateId") or "")
            for item in drafts
        }
        # Run-scoped draft lookup finds nothing: the drafts are origin-layer.
        assert (
            chain.list_exploratory_drafts(
                team_id, question_id=_QUESTION_ID, workflow_run_id=run_id
            )["drafts"]
            == []
        )

        # A further run creation would see the consumable draft floor and
        # must not open a second exploratory round.  The run-scoped approved
        # candidate read verifies the run in the canonical ledger; this test
        # focuses on the draft floor, so stub the empty candidate set.
        monkeypatch.setattr(
            selections,
            "_approved_candidate_ids",
            lambda _team_id, _question_id, workflow_run_id="": [],
        )
        assert (
            chain.needs_candidate_generation(
                team_id, _QUESTION_ID, workflow_run_id=run_id
            )
            is False
        )

        opened_r1 = chain.open_candidate_generation_meeting(
            team_id,
            _QUESTION_ID,
            agent_runner=_grounded_candidate_generation_runner,
            _candidate_authority="formal_grounded_candidate",
            _model_invocation_receipt_authority=_generation_receipt_authority(
                team_id, run_id
            ),
            _discussion_scope=(
                WorkflowDiscussionScopeV1.generation(
                    teamId=team_id,
                    researchProjectId=project_id,
                    workflowRunId=run_id,
                    workflowNodeId=chain.HYPOTHESIS_DESIGN_NODE_ID,
                    questionId=_QUESTION_ID,
                ).to_dict()
            ),
            _generation_context={
                "status": "ready",
                "allowedEvidenceRefs": [
                    "evidence:accepted-1",
                    "evidence:accepted-2",
                    "evidence:boundary-1",
                ],
                "evidenceClaims": [
                    {"sourceRef": "evidence:accepted-1", "claim": "腺苷支持证据"},
                    {"sourceRef": "evidence:accepted-2", "claim": "突触支持证据"},
                ],
                "knowledgePackage": {
                    "sourceArtifactIds": ["knowledge_package:pkg-1"]
                },
            },
        )
        r1_meeting = opened_r1["meetingRound"]
        assert {
            ref.split(":", 1)[-1]
            for ref in r1_meeting["exploratoryDraftRefs"]
        } == draft_ids
        # Lineage keeps the producing round: every consumed draft still
        # points at the origin-layer R0 meeting id.
        assert all(
            str(item.get("meetingRoundId") or "") == r0_id for item in drafts
        )
        # The knowledge package rides along so the REFS agenda rules accept
        # the grounded candidate lineage built on top of the origin drafts.
        assert r1_meeting["knowledgePackageRefs"] == ["knowledge_package:pkg-1"]
        assert r1_meeting["allowedEvidenceRefs"] == [
            "evidence:accepted-1",
            "evidence:accepted-2",
            "evidence:boundary-1",
        ]
        assert r1_meeting["revisionOrdinal"] == 1
        # The closure-time lineage registration (R1 candidates deriving from
        # the consumed drafts) is covered by
        # test_stage_one_r0_isolated_then_r1_requires_whitelisted_evidence;
        # this test pins the run-scoped consumption of origin drafts itself,
        # including the origin meeting id surviving on every consumed draft.


def test_waiting_fan_in_persists_blocked_trace(tmp_path, monkeypatch):
    """A pending fan-in appends a resolvable blocked trace, not silence."""
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        chain,
        "_review_meeting_fan_in_group",
        lambda *_args, **_kwargs: {
            "status": "waiting_for_sibling_reviews",
            "selectionId": "selection-wait-1",
            "roundIndex": 1,
            "closed": False,
            "missingCandidateIds": [],
            "pendingMeetingRoundIds": ["meeting-b"],
            "supersededCandidateIds": [],
            "supersededMeetingRoundIds": [],
            "closedMeetingRoundIds": ["meeting-a"],
        },
    )

    result = chain._generate_hypothesis_round(
        "team-wait", {"meetingRoundId": "meeting-a", "question": "SCI-096"}
    )

    assert result["status"] == "waiting_for_sibling_reviews"
    assert result["failureRecordId"].startswith("hrfail-")
    failures = hrounds.list_hypothesis_round_failures("team-wait")
    assert failures["failureCount"] == 1
    assert failures["openFailureCount"] == 1
    trace = failures["failures"][0]
    assert trace["status"] == "blocked"
    assert trace["failureCode"] == "fan_in_waiting_for_sibling_reviews"
    assert trace["selectionId"] == "selection-wait-1"
    assert trace["roundIndex"] == 1
    assert trace["meetingRoundIds"] == ["meeting-a"]
    assert trace["context"]["pendingMeetingRoundIds"] == ["meeting-b"]
    assert trace["context"]["closedMeetingRoundIds"] == ["meeting-a"]
    # Waiting traces never fabricate a round record.
    assert hrounds.list_hypothesis_rounds("team-wait")["roundCount"] == 0


def test_failed_generation_persists_classified_trace(tmp_path, monkeypatch):
    """Generation failures persist a classified trace; trace failures degrade visibly."""
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)
    meeting = {
        "meetingRoundId": "meeting-conflict",
        "question": "SCI-096",
        "scopeHash": "scope-x",
        "discussionScope": {"workflowRunId": "run-1"},
    }
    monkeypatch.setattr(
        chain,
        "_review_meeting_fan_in_group",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "selectionId": "selection-9",
            "roundIndex": 1,
            "meetings": [meeting],
        },
    )
    monkeypatch.setattr(
        selections,
        "get_hypothesis_selection",
        lambda *_args, **_kwargs: {
            "selection": {
                "scopeHash": "scope-x",
                "questionId": "SCI-096",
                "selectedCandidateIds": ["H1", "H2"],
            }
        },
    )
    monkeypatch.setattr(
        chain,
        "_build_round_candidates",
        lambda *_args, **_kwargs: [
            {"candidateId": "H1", "claim": "c1"},
            {"candidateId": "H2", "claim": "c2"},
        ],
    )
    monkeypatch.setattr(
        hrounds,
        "generate_hypothesis_round_from_meeting",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            hrounds.ResearchHypothesisRoundError(
                "hypothesis round id is already bound to different content"
            )
        ),
    )

    result = chain._generate_hypothesis_round("team-conflict", meeting)

    assert result["status"] == "failed"
    assert result["errorType"] == "ResearchHypothesisRoundError"
    assert result["failureRecordId"].startswith("hrfail-")
    trace = hrounds.list_hypothesis_round_failures("team-conflict")["failures"][0]
    assert trace["status"] == "failed"
    assert trace["failureCode"] == "hypothesis_round_content_conflict"
    assert trace["errorType"] == "ResearchHypothesisRoundError"
    assert trace["selectionId"] == "selection-9"
    assert trace["roundIndex"] == 1
    assert trace["questionId"] == "SCI-096"
    assert trace["workflowRunId"] == "run-1"
    assert trace["meetingRoundIds"] == ["meeting-conflict"]
    assert "regenerate_hypothesis_round" in trace["retryHint"]

    # A failing trace write must surface diagnostically, never mask the outcome.
    monkeypatch.setattr(
        hrounds,
        "record_hypothesis_round_failure",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("ledger unavailable")
        ),
    )
    degraded = chain._generate_hypothesis_round("team-conflict", meeting)
    assert degraded["status"] == "failed"
    assert degraded["failureRecordError"] == "ledger unavailable"


def test_concurrent_fan_in_triggers_spend_review_budget_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two aligned triggers for one fan-in group run the review exactly once.

    The loser trigger either reuses the stored round or reports the
    structured in-progress rejection; it never double-spends the review
    executor and never leaves a hypothesis_round_content_conflict ghost
    failure trace.
    """
    import threading

    from core.research.workflow.contracts import SCORE_DIMENSIONS
    from core.web.services.team_workflow import (
        hypothesis_review_executor,
        research_memory_context,
    )
    from core.web.services.team_workflow.research_runtime import (
        dimension_reviews_artifact_writer,
        review_independence_artifact_writer,
    )

    team_id = "team-fan-in-race"
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)

    scope = _scope_fields("agent-coordinator")
    scope_hash = scope_hash_for(
        program=scope["program"],
        theme=scope["theme"],
        campaign=scope["campaign"],
        question=scope["question"],
        branch=scope["branch"],
        workflow=scope["workflow"],
        agent_id=scope["agentId"],
        mode=scope["mode"],
    )
    meetings_by_id = {}
    for candidate_id, meeting_id in (
        ("hyp-a", "meeting-a"),
        ("hyp-b", "meeting-b"),
    ):
        meetings_by_id[meeting_id] = {
            **scope,
            "scopeHash": scope_hash,
            "meetingRoundId": meeting_id,
            "meetingType": "hypothesis_review",
            "status": "closed",
            "digestId": f"digest-{candidate_id}",
            "decisionRefs": [f"decision-{candidate_id}"],
            "discussionItemRefs": [f"hypothesis_candidate:{candidate_id}"],
            "participants": ["agent-coordinator"],
            "participantRoleIds": ["coordinator"],
            "closedBy": "agent-coordinator",
        }
    digest_rows = [
        {
            "digestId": f"digest-{candidate_id}",
            "summary": candidate_id,
            "sourceMessageRefs": [f"message:{candidate_id}"],
            "contentHash": f"hash-{candidate_id}",
        }
        for candidate_id in ("hyp-a", "hyp-b")
    ]
    decision_rows = [
        {
            "decisionId": f"decision-{candidate_id}",
            "decision": "approve",
            "candidateRefs": [candidate_id],
            "evidenceRefs": [f"message:{candidate_id}"],
        }
        for candidate_id in ("hyp-a", "hyp-b")
    ]
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda _team_id, meeting_id: {"meetingRound": meetings_by_id[meeting_id]},
    )
    monkeypatch.setattr(meetings, "_digests_path", lambda _team_id: Path("digests"))
    monkeypatch.setattr(meetings, "_decisions_path", lambda _team_id: Path("decisions"))
    monkeypatch.setattr(
        meetings,
        "_read_jsonl",
        lambda path: digest_rows if str(path) == "digests" else decision_rows,
    )
    monkeypatch.setattr(
        chain,
        "_review_meeting_fan_in_group",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "selectionId": "selection-race",
            "roundIndex": 1,
            "meetings": [meetings_by_id["meeting-a"], meetings_by_id["meeting-b"]],
        },
    )
    monkeypatch.setattr(
        selections,
        "get_hypothesis_selection",
        lambda *_args, **_kwargs: {
            "selection": {
                "scopeHash": scope_hash,
                "questionId": _QUESTION_ID,
                "selectedCandidateIds": ["hyp-a", "hyp-b"],
            }
        },
    )
    candidate_inputs = [
        {
            "candidateId": "hyp-a",
            "claim": "hyp-a 的机制陈述",
            "rationale": "r-a",
            "differenceFromAlternatives": "hyp-a 走代理路径",
        },
        {
            "candidateId": "hyp-b",
            "claim": "hyp-b 的机制陈述",
            "rationale": "r-b",
            "differenceFromAlternatives": "hyp-b 走容量路径",
        },
    ]
    monkeypatch.setattr(
        chain, "_build_round_candidates", lambda *_args, **_kwargs: candidate_inputs
    )
    monkeypatch.setattr(
        research_memory_context,
        "build_hypothesis_review_context",
        lambda **_kwargs: {"contextId": "ctx-race"},
    )

    review_calls: list[str] = []
    executor_entered = threading.Event()
    finish_review = threading.Event()

    def fake_review(context, **kwargs):
        review_calls.append(str(kwargs.get("round_id")))
        executor_entered.set()
        finish_review.wait(timeout=10)
        return {
            "candidates": [
                {
                    "candidateId": "hyp-a",
                    "claim": "hyp-a 的机制陈述",
                    "rationale": "r-a",
                    "differenceFromAlternatives": "hyp-a 走代理路径",
                    "lineageRefs": [],
                    "scores": {dim: 0.8 for dim in SCORE_DIMENSIONS},
                    "reviewedBy": "agent-coordinator",
                    "status": "proposed",
                },
                {
                    "candidateId": "hyp-b",
                    "claim": "hyp-b 的机制陈述",
                    "rationale": "r-b",
                    "differenceFromAlternatives": "hyp-b 走容量路径",
                    "lineageRefs": [],
                    "scores": {dim: 0.6 for dim in SCORE_DIMENSIONS},
                    "reviewedBy": "agent-coordinator",
                    "status": "proposed",
                },
            ],
            "pairwiseComparisons": [
                {
                    "comparisonId": "cmp-hyp-a-hyp-b",
                    "leftCandidateId": "hyp-a",
                    "rightCandidateId": "hyp-b",
                    "reviewerAgentId": "agent-coordinator",
                    "outcome": "left_wins",
                    "justification": "hyp-a 更完整",
                }
            ],
            "pareto": {
                "paretoFrontCandidateIds": ["hyp-a"],
                "dominatedCandidateIds": ["hyp-b"],
                "analystAgentId": "agent-coordinator",
                "notes": "",
            },
            "metaReview": {
                "metaReviewId": "meta-race-1",
                "reviewerAgentId": "agent-coordinator",
                "recommendationCandidateId": "hyp-a",
                "rationale": "hyp-a 收敛",
                "riskNotes": "",
                "accepted": True,
            },
            "reviewContextId": "ctx-race",
            "executionMode": "dev",
            "positionSeed": "seed",
            "roles": {"metareview": "agent-coordinator"},
            "modelInvocationReceipts": [],
        }

    monkeypatch.setattr(
        hypothesis_review_executor, "execute_hypothesis_review", fake_review
    )
    # The authority writers are not under test here; pin them so the racing
    # threads never touch the real repo-root team workspace.
    monkeypatch.setattr(
        dimension_reviews_artifact_writer,
        "materialize_dimension_reviews_authority",
        lambda **_kwargs: {"status": "written"},
    )
    monkeypatch.setattr(
        review_independence_artifact_writer,
        "write_review_independence_artifacts",
        lambda **_kwargs: {"status": "written"},
    )
    monkeypatch.setattr(
        chain,
        "_materialize_hypothesis_revision_authority",
        lambda **_kwargs: {"status": "written"},
    )
    monkeypatch.setattr(
        chain,
        "_materialize_stage_one_plan_authority",
        lambda **_kwargs: {"status": "written"},
    )

    barrier = threading.Barrier(2)
    results: list[dict] = []

    def trigger():
        barrier.wait(timeout=10)
        results.append(
            chain._generate_hypothesis_round(team_id, meetings_by_id["meeting-a"])
        )

    threads = [threading.Thread(target=trigger) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert executor_entered.wait(timeout=10)
    finish_review.set()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    assert len(results) == 2

    statuses = [str(item.get("status")) for item in results]
    assert statuses.count("created") == 1
    assert set(statuses) <= {"created", "reused", "generation_in_progress"}
    assert len(review_calls) == 1
    assert hrounds.list_hypothesis_rounds(team_id)["roundCount"] == 1
    failures = hrounds.list_hypothesis_round_failures(team_id)
    assert failures["failureCount"] == 0
    assert failures["openFailureCount"] == 0


def test_in_progress_generation_reports_structured_rejection_without_failure_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected concurrent trigger is structured, never a ghost failure."""
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)
    meeting = {
        "meetingRoundId": "meeting-inflight",
        "question": _QUESTION_ID,
        "scopeHash": "scope-x",
        "discussionScope": {"workflowRunId": "run-1"},
    }
    monkeypatch.setattr(
        chain,
        "_review_meeting_fan_in_group",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "selectionId": "selection-inflight",
            "roundIndex": 1,
            "meetings": [meeting],
        },
    )
    monkeypatch.setattr(
        selections,
        "get_hypothesis_selection",
        lambda *_args, **_kwargs: {
            "selection": {
                "scopeHash": "scope-x",
                "questionId": _QUESTION_ID,
                "selectedCandidateIds": ["H1", "H2"],
            }
        },
    )
    monkeypatch.setattr(
        chain,
        "_build_round_candidates",
        lambda *_args, **_kwargs: [
            {"candidateId": "H1", "claim": "c1"},
            {"candidateId": "H2", "claim": "c2"},
        ],
    )

    def raise_in_progress(*_args, **_kwargs):
        raise hrounds.ResearchHypothesisRoundGenerationInProgressError(
            "team-inflight", "hround-inflight-1"
        )

    monkeypatch.setattr(
        hrounds, "generate_hypothesis_round_from_meeting", raise_in_progress
    )

    result = chain._generate_hypothesis_round("team-inflight", meeting)

    assert result["status"] == "generation_in_progress"
    assert result["roundId"] == "hround-inflight-1"
    assert result["selectionId"] == "selection-inflight"
    assert "failureRecordId" not in result
    assert "reuse" in result["retryHint"]
    # No budget was spent by the rejected trigger, so the failure ledger must
    # stay empty instead of gaining a phantom content-conflict record.
    failures = hrounds.list_hypothesis_round_failures("team-inflight")
    assert failures["failureCount"] == 0
    assert failures["openFailureCount"] == 0


def test_regenerate_hypothesis_round_requires_closed_review_meeting(monkeypatch):
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda _team_id, meeting_id: {
            "meetingRound": {
                "meetingRoundId": meeting_id,
                "meetingType": "hypothesis_review",
                "status": "awaiting_approval",
            }
        },
    )
    with pytest.raises(chain.HypothesisFirstChainError, match="not closed"):
        chain.regenerate_hypothesis_round("team-regen", "meeting-1")
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda _team_id, meeting_id: {
            "meetingRound": {
                "meetingRoundId": meeting_id,
                "meetingType": "candidate_generation",
                "status": "closed",
            }
        },
    )
    with pytest.raises(chain.HypothesisFirstChainError, match="hypothesis_review"):
        chain.regenerate_hypothesis_round("team-regen", "meeting-1")


def test_round_failure_traces_persist_and_backfill_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sibling wait and failed generation both leave traces the retry resolves."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(
        monkeypatch,
        hypotheses=[
            {"hypothesis_id": "hyp-a", "statement": "hyp-a 的机制陈述"},
            {"hypothesis_id": "hyp-b", "statement": ""},
            {"hypothesis_id": "hyp-c", "statement": "hyp-c 的机制陈述"},
        ],
    )
    _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            sibling_meetings = _review_meetings(recorded)
            assert len(sibling_meetings) == 2
            first_meeting_id = sibling_meetings[0]["meetingRoundId"]
            second_meeting_id = sibling_meetings[1]["meetingRoundId"]

            # 1) Sibling still open: a blocked trace is appended.
            _drive_to_awaiting_approval(team_id, first_meeting_id, agent_ids[0])
            closed_first = chain.close_review_meeting(
                team_id,
                first_meeting_id,
                _closure_payload(agent_ids, [_envelope_decision(agent_ids[0])]),
                runtime=runtime,
            )
            waiting = closed_first["hypothesisRound"]
            assert waiting["status"] == "waiting_for_sibling_reviews"
            assert waiting["failureRecordId"].startswith("hrfail-")
            blocked_list = hrounds.list_hypothesis_round_failures(team_id)
            assert blocked_list["failureCount"] == 1
            assert blocked_list["openFailureCount"] == 1
            blocked = blocked_list["failures"][0]
            assert blocked["status"] == "blocked"
            assert blocked["failureCode"] == "fan_in_waiting_for_sibling_reviews"
            assert blocked["selectionId"]
            assert blocked["roundIndex"] == 1
            assert blocked["meetingRoundIds"] == [first_meeting_id]
            assert hrounds.list_hypothesis_rounds(team_id)["roundCount"] == 0

            # 2) Fan-in ready but generation fails: a classified failed trace.
            _drive_to_awaiting_approval(team_id, second_meeting_id, agent_ids[0])
            closed = chain.close_review_meeting(
                team_id,
                second_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )
            failed_round = closed["hypothesisRound"]
            assert failed_round["status"] == "failed"
            assert "hyp-b" in failed_round["error"]
            assert failed_round["failureRecordId"].startswith("hrfail-")
            failures = hrounds.list_hypothesis_round_failures(team_id)
            assert failures["failureCount"] == 2
            assert failures["openFailureCount"] == 2
            failed_trace = next(
                item
                for item in failures["failures"]
                if item["failureCode"] != "fan_in_waiting_for_sibling_reviews"
            )
            assert failed_trace["failureCode"] == (
                "hypothesis_round_precondition_failed"
            )
            assert failed_trace["status"] == "failed"
            assert first_meeting_id in failed_trace["meetingRoundIds"]
            assert second_meeting_id in failed_trace["meetingRoundIds"]
            assert hrounds.list_hypothesis_rounds(team_id)["roundCount"] == 0

            # 3) Failure cause removed: the regenerate command rebuilds the
            # round and resolves every open trace.
            _patch_approved_question(
                monkeypatch,
                hypotheses=[
                    {"hypothesis_id": "hyp-a", "statement": "hyp-a 的机制陈述"},
                    {"hypothesis_id": "hyp-b", "statement": "hyp-b 的机制陈述"},
                    {"hypothesis_id": "hyp-c", "statement": "hyp-c 的机制陈述"},
                ],
            )
            regenerated = chain.regenerate_hypothesis_round(
                team_id, second_meeting_id
            )
            assert regenerated["status"] == "created"
            round_id = regenerated["roundId"]
            assert round_id
            assert regenerated["round"]["roundId"] == round_id
            assert regenerated["round"]["status"] == "closed"
            assert hrounds.list_hypothesis_rounds(team_id)["roundCount"] == 1
            after = hrounds.list_hypothesis_round_failures(team_id)
            assert after["failureCount"] == 2
            assert after["openFailureCount"] == 0
            assert all(
                item["resolvedByRoundId"] == round_id
                for item in after["failures"]
            )
    finally:
        runtime.close()
# ---------------------------------------------------------------------------
# V2 operator stop semantics: a stalled meeting that already produced
# completed messages must terminate through a real stopped-execution close
# instead of raising "cannot be superseded"; an empty attempt keeps the
# superseded recovery semantics.
# ---------------------------------------------------------------------------


def _stage_stopped_v2_meeting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Create one open review meeting bound to a room round with one
    completed, citable message; project the exact V2 stop offer."""

    from core.web.services.team_workflow.research_runtime import hypothesis_first_state_v2

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    meetings.create_meeting_round(
        "team-1",
        {
            "program": "XH-202619",
            "theme": "cc-gpu-operator-001",
            "campaign": "cc-campaign-gpu-operator-001",
            "question": "SCI-091",
            "branch": "main",
            "workflow": "hypothesis_and_plan",
            "agentId": "agent-coordinator",
            "mode": "formal",
            "meetingRoundId": "meeting-v2-stop",
            "meetingType": "hypothesis_review",
            "participants": ["agent-alpha", "agent-beta"],
            "discussionItemRefs": ["hypothesis_round:hround-demo-1"],
        },
    )
    meetings.bind_meeting_chat_room_round(
        "team-1", "meeting-v2-stop", "room-stop-1", "round-stop-1"
    )
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        lambda room_id: (
            {
                "roomId": "room-stop-1",
                "rounds": [
                    {
                        "roundId": "round-stop-1",
                        "status": "completed",
                        "messages": [
                            {
                                "status": "completed",
                                "speakerTitle": "研究员",
                                "content": "DISAGREE: hyp-b 的泛化证据不足",
                            }
                        ],
                    }
                ],
            }
            if room_id == "room-stop-1"
            else None
        ),
    )
    snapshot = {
        "stateVersion": "hf2-action:pending:pending",
        "allowedActions": [
            {
                "kind": "command",
                "actionId": "stop-discussion:meeting-v2-stop",
                "command": "stop_discussion",
                "payload": {"meetingRoundId": "meeting-v2-stop"},
                "enabled": True,
                "idempotencyKey": "hf2:stop-discussion:meeting-v2-stop:k1",
            }
        ],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    return "team-1"


def test_v2_stop_discussion_terminates_stalled_meeting_with_completed_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id = _stage_stopped_v2_meeting(tmp_path, monkeypatch)

    envelope = chain.execute_v2_command(
        team_id,
        {
            "actionId": "stop-discussion:meeting-v2-stop",
            "idempotencyKey": "hf2:stop-discussion:meeting-v2-stop:k1",
            "expectedStateVersion": "hf2-action:pending:pending",
            "command": "stop_discussion",
            "payload": {"meetingRoundId": "meeting-v2-stop"},
        },
        question_id="SCI-091",
    )

    assert envelope["result"]["status"] == "stopped"
    meeting = meetings.get_meeting_round(team_id, "meeting-v2-stop")["meetingRound"]
    assert meeting["status"] == "closed"
    assert meeting["executionStatus"] == "stopped"
    assert meeting["recoveryReason"] == "operator_stop_discussion"
    assert meeting["closedBy"] == "operator:v2-stop-discussion"
    # The transcript and any produced draft survive the stop; only the digest
    # promotion is withheld.
    assert len(meetings.completed_meeting_source_messages(meeting)) == 1
    assert not meeting.get("digestId")

    # Replaying the same command idempotently reuses the stopped record.
    replay = chain.execute_v2_command(
        team_id,
        {
            "actionId": "stop-discussion:meeting-v2-stop",
            "idempotencyKey": "hf2:stop-discussion:meeting-v2-stop:k1",
            "expectedStateVersion": "hf2-action:pending:pending",
            "command": "stop_discussion",
            "payload": {"meetingRoundId": "meeting-v2-stop"},
        },
        question_id="SCI-091",
    )
    assert replay["result"]["status"] == "reused"


def test_v2_stop_discussion_keeps_supersede_semantics_for_empty_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id = _stage_stopped_v2_meeting(tmp_path, monkeypatch)
    # Empty attempt: the bound room round carries no citable message.
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        lambda room_id: (
            {
                "roomId": "room-stop-1",
                "rounds": [
                    {"roundId": "round-stop-1", "status": "completed", "messages": []}
                ],
            }
            if room_id == "room-stop-1"
            else None
        ),
    )

    envelope = chain.execute_v2_command(
        team_id,
        {
            "actionId": "stop-discussion:meeting-v2-stop",
            "idempotencyKey": "hf2:stop-discussion:meeting-v2-stop:k1",
            "expectedStateVersion": "hf2-action:pending:pending",
            "command": "stop_discussion",
            "payload": {"meetingRoundId": "meeting-v2-stop"},
        },
        question_id="SCI-091",
    )

    assert envelope["result"]["status"] == "superseded"
    meeting = meetings.get_meeting_round(team_id, "meeting-v2-stop")["meetingRound"]
    assert meeting["status"] == "closed"
    assert meeting["recoveryReason"] == "discussion_has_no_completed_messages"
    assert (
        meeting["summaryDraftError"]["code"] == "discussion_has_no_completed_messages"
    )
    assert not meeting.get("executionStatus")

# ---------------------------------------------------------------------------
# Budget-exhaustion auto-advance closure (adjudication -> formal run)
# ---------------------------------------------------------------------------

_AUTO_ROUND_ID = "hround-auto-5"
_AUTO_MEETING_ID = "meeting-auto-5"
_AUTO_CANDIDATE_ID = "hyp-auto-a"
_AUTO_ADJUDICATION_KEY = f"hf2:auto-adjudication:{_AUTO_ROUND_ID}"
_AUTO_RATIONALE = (
    "auto-advance: review round budget exhausted (5/5); "
    "auto-advanced per budget-exhaustion policy"
)


def _auto_advance_round_record(question_id: str) -> dict[str, Any]:
    return {
        "roundId": _AUTO_ROUND_ID,
        "question": question_id,
        "status": "closed",
        "roundIndex": 5,
        "metaReview": {
            "metaReviewId": "mr-auto-5",
            "recommendationCandidateId": _AUTO_CANDIDATE_ID,
            "accepted": False,
        },
        "meetingRefs": [{"kind": "meeting_round", "id": _AUTO_MEETING_ID}],
        "createdAt": "2026-09-01T00:00:00Z",
    }


def _auto_advance_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    question_id: str = _QUESTION_ID,
    request_status: str = "handed_off",
    existing_adjudication: dict[str, Any] | None = None,
):
    """Env for the auto-advance helpers: closed round 5/5 plus ledger records."""
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    round_record = _auto_advance_round_record(question_id)
    monkeypatch.setattr(
        hrounds,
        "get_hypothesis_round",
        lambda _team_id, _round_id: {"round": round_record},
    )
    monkeypatch.setattr(
        chain,
        "_question_hypothesis_rounds",
        lambda _team_id, _round_question: [round_record]
        if str(_round_question).upper() == question_id.upper()
        else [],
    )
    ledger_path = tmp_path / "hypothesis_first_chain.jsonl"
    monkeypatch.setattr(chain, "_storage_path", lambda _team_id: ledger_path)
    if request_status:
        chain._append_jsonl(
            ledger_path,
            {
                "recordKind": "collection_request",
                "requestId": "request-auto-1",
                "questionId": question_id,
                "meetingRoundId": _AUTO_MEETING_ID,
                "status": request_status,
                "createdAt": "2026-09-01T00:01:00Z",
            },
        )
    if existing_adjudication is not None:
        chain._append_jsonl(ledger_path, dict(existing_adjudication))
    scene_events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        chain,
        "_record_scene_event",
        lambda event_code, **kwargs: scene_events.append((event_code, dict(kwargs))),
    )
    return team_id, ledger_path, scene_events


def _auto_adjudication_records(ledger_path: Path) -> list[dict[str, Any]]:
    return [
        item
        for item in chain._read_jsonl(ledger_path)
        if str(item.get("recordKind") or "") == chain.HUMAN_ADJUDICATION_KIND
    ]


def test_auto_adjudicate_exhausted_round_records_accepted_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, ledger_path, scene_events = _auto_advance_env(tmp_path, monkeypatch)
    _allow_chain_claim_belief_gate(monkeypatch)

    result = chain.auto_adjudicate_exhausted_round(
        team_id, question_id=_QUESTION_ID
    )

    assert result["status"] == "created"
    assert result["roundId"] == _AUTO_ROUND_ID
    assert result["decision"] == "accepted"
    adjudications = _auto_adjudication_records(ledger_path)
    assert len(adjudications) == 1
    adjudication = adjudications[0]
    assert adjudication["decision"] == "accepted"
    assert adjudication["decidedBy"] == "system:auto-advance:budget-exhausted"
    assert adjudication["idempotencyKey"] == _AUTO_ADJUDICATION_KEY
    assert adjudication["rationale"] == _AUTO_RATIONALE
    events = [
        fields
        for event, fields in scene_events
        if event == "hypothesis_first.auto_adjudication"
    ]
    assert len(events) == 1
    assert events[0]["outcome"] == "created"
    assert events[0]["fields"]["questionId"] == _QUESTION_ID
    assert events[0]["fields"]["roundId"] == _AUTO_ROUND_ID


def test_auto_adjudicate_exhausted_round_replays_as_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deterministic auto key + rationale make every replay a reuse."""
    team_id, ledger_path, _events = _auto_advance_env(tmp_path, monkeypatch)
    _allow_chain_claim_belief_gate(monkeypatch)

    first = chain.auto_adjudicate_exhausted_round(team_id, question_id=_QUESTION_ID)
    second = chain.auto_adjudicate_exhausted_round(team_id, question_id=_QUESTION_ID)

    assert (first["status"], second["status"]) == ("created", "reused")
    assert second["roundId"] == _AUTO_ROUND_ID
    assert len(_auto_adjudication_records(ledger_path)) == 1


def test_auto_adjudicate_skips_while_collection_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, ledger_path, scene_events = _auto_advance_env(
        tmp_path, monkeypatch, request_status="collecting"
    )

    result = chain.auto_adjudicate_exhausted_round(
        team_id, question_id=_QUESTION_ID
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "pending_collection"
    assert _auto_adjudication_records(ledger_path) == []
    assert not [
        fields
        for event, fields in scene_events
        if event == "hypothesis_first.auto_adjudication"
    ]


def test_auto_adjudicate_skips_when_human_already_decided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    human_record = {
        "recordKind": chain.HUMAN_ADJUDICATION_KIND,
        "adjudicationId": "hf-adjudication-human-1",
        "idempotencyKey": "hf2:human-adjudication:manual-1",
        "questionId": _QUESTION_ID,
        "hypothesisRoundId": _AUTO_ROUND_ID,
        "workflowRunId": "",
        "meetingRoundIds": [_AUTO_MEETING_ID],
        "decision": "rejected",
        "rationale": "operator rejected after review",
        "decidedBy": "operator",
        "createdAt": "2026-09-01T00:02:00Z",
        "updatedAt": "2026-09-01T00:02:00Z",
    }
    team_id, ledger_path, _events = _auto_advance_env(
        tmp_path, monkeypatch, existing_adjudication=human_record
    )

    result = chain.auto_adjudicate_exhausted_round(
        team_id, question_id=_QUESTION_ID
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "adjudication_exists"
    assert result["decision"] == "rejected"
    # The human authority is untouched and nothing new was appended.
    assert _auto_adjudication_records(ledger_path) == [human_record]


def test_auto_adjudicate_gate_blocked_records_rejected_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate blocked is a final verdict: the rejected outcome is recorded as
    the formal failure result (challenge-cup retention policy), so the chain
    lands in a queryable terminal state instead of a dangling human wait."""
    team_id, ledger_path, scene_events = _auto_advance_env(tmp_path, monkeypatch)

    def _blocked(_team_id, _question_id, candidate_ids):
        return {
            candidate_id: {
                "status": "blocked",
                "reason": "claim_data_missing",
                "claims": [],
                "blockedClaims": [],
            }
            for candidate_id in candidate_ids
        }

    monkeypatch.setattr(chain, "evaluate_claim_belief_gate", _blocked)

    result = chain.auto_adjudicate_exhausted_round(
        team_id, question_id=_QUESTION_ID
    )

    assert result["status"] == "rejected"
    assert result["reason"] == "claim_belief_gate_blocked"
    assert result["roundId"] == _AUTO_ROUND_ID
    assert result["decision"] == "rejected"
    adjudications = _auto_adjudication_records(ledger_path)
    assert len(adjudications) == 1
    adjudication = adjudications[0]
    assert adjudication["decision"] == "rejected"
    assert adjudication["decidedBy"] == "system:auto-advance:gate-blocked"
    assert adjudication["idempotencyKey"] == (
        f"hf2:auto-adjudication-rejected:{_AUTO_ROUND_ID}"
    )
    assert "(claim_data_missing)" in adjudication["rationale"]
    assert "budget exhausted (5/5)" in adjudication["rationale"]
    assert "challenge-cup retention policy" in adjudication["rationale"]
    events = [
        fields
        for event, fields in scene_events
        if event == "hypothesis_first.auto_adjudication"
    ]
    assert [fields["outcome"] for fields in events] == [
        "blocked_by_claim_gate",
        "created",
    ]


def test_auto_adjudicate_gate_blocked_rejection_replays_as_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rerunning after the rejected outcome is idempotent: reused, and the
    terminal verdict is never flipped to accepted."""
    team_id, ledger_path, _events = _auto_advance_env(tmp_path, monkeypatch)

    def _blocked(_team_id, _question_id, candidate_ids):
        return {
            candidate_id: {
                "status": "blocked",
                "reason": "claim_data_missing",
                "claims": [],
                "blockedClaims": [],
            }
            for candidate_id in candidate_ids
        }

    monkeypatch.setattr(chain, "evaluate_claim_belief_gate", _blocked)

    first = chain.auto_adjudicate_exhausted_round(team_id, question_id=_QUESTION_ID)
    second = chain.auto_adjudicate_exhausted_round(team_id, question_id=_QUESTION_ID)

    assert (first["status"], second["status"]) == ("rejected", "reused")
    assert second["decision"] == "rejected"
    records = _auto_adjudication_records(ledger_path)
    assert len(records) == 1
    assert records[0]["decision"] == "rejected"


def test_auto_adjudicate_transient_failure_stays_failed_without_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A storage-style transient error keeps the structured failed outcome
    with NO adjudication record so the maintenance sweep can retry."""
    team_id, ledger_path, scene_events = _auto_advance_env(tmp_path, monkeypatch)

    def _storage_broken(*_args, **_kwargs):
        raise RuntimeError("simulated ledger io failure")

    monkeypatch.setattr(chain, "record_human_adjudication", _storage_broken)

    result = chain.auto_adjudicate_exhausted_round(
        team_id, question_id=_QUESTION_ID
    )

    assert result["status"] == "failed"
    assert result["reason"] == "RuntimeError"
    assert _auto_adjudication_records(ledger_path) == []
    events = [
        fields
        for event, fields in scene_events
        if event == "hypothesis_first.auto_adjudication"
    ]
    assert [fields["outcome"] for fields in events] == ["failed"]


def _auto_create_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    question_id: str = _QUESTION_ID,
):
    """Env with an accepted (auto) adjudication already on the ledger."""
    adjudication = {
        "recordKind": chain.HUMAN_ADJUDICATION_KIND,
        "adjudicationId": "hf-adjudication-auto-1",
        "idempotencyKey": _AUTO_ADJUDICATION_KEY,
        "questionId": question_id,
        "hypothesisRoundId": _AUTO_ROUND_ID,
        "workflowRunId": "",
        "meetingRoundIds": [_AUTO_MEETING_ID],
        "decision": "accepted",
        "rationale": _AUTO_RATIONALE,
        "decidedBy": "system:auto-advance:budget-exhausted",
        "createdAt": "2026-09-01T00:02:00Z",
        "updatedAt": "2026-09-01T00:02:00Z",
    }
    team_id, ledger_path, scene_events = _auto_advance_env(
        tmp_path, monkeypatch, question_id=question_id,
        existing_adjudication=adjudication,
    )
    _allow_chain_claim_belief_gate(monkeypatch)
    monkeypatch.setattr(
        chain, "_question_non_archived_formal_run_exists", lambda _t, _q: False
    )
    return team_id, ledger_path, scene_events


def test_auto_create_formal_run_creates_and_auto_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import run_creation

    team_id, _ledger_path, scene_events = _auto_create_env(
        tmp_path, monkeypatch
    )
    create_calls: list[dict] = []
    monkeypatch.setattr(
        run_creation,
        "create_question_run",
        lambda *_args, **kwargs: (create_calls.append(kwargs) or {"runId": "run-auto-1"}),
    )
    start_calls: list[dict] = []
    monkeypatch.setattr(
        chain,
        "_auto_start_created_formal_run",
        lambda _team_id, *, run, idempotency_key: (
            start_calls.append(
                {"runId": str(run.get("runId") or ""), "idempotencyKey": idempotency_key}
            )
            or {"status": "accepted"}
        ),
    )

    result = chain.auto_create_formal_run_after_convergence(
        team_id, question_id=_QUESTION_ID
    )

    assert result["status"] == "created"
    assert result["roundId"] == _AUTO_ROUND_ID
    assert result["runId"] == "run-auto-1"
    assert len(create_calls) == 1
    call = create_calls[0]
    assert call["team_id"] == team_id
    assert call["question_id"] == _QUESTION_ID
    assert call["idempotency_key"] == (
        f"hf2:auto-formal-run:{_QUESTION_ID}:{_AUTO_ROUND_ID}"
    )
    assert call["formal_hypothesis_round_id"] == _AUTO_ROUND_ID
    # Uncovered question: no catalog authorization required.
    assert call["catalog_run_authorization"] is None
    assert start_calls == [
        {
            "runId": "run-auto-1",
            "idempotencyKey": f"hf2:auto-formal-run:{_QUESTION_ID}:{_AUTO_ROUND_ID}",
        }
    ]
    events = [
        fields
        for event, fields in scene_events
        if event == "hypothesis_first.auto_formal_run"
    ]
    assert len(events) == 1
    assert events[0]["outcome"] == "created"
    assert events[0]["fields"]["runId"] == "run-auto-1"


def test_auto_create_skips_when_already_created_or_unconverged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import run_creation

    team_id, _ledger_path, _events = _auto_create_env(tmp_path, monkeypatch)
    create_calls: list[dict] = []
    monkeypatch.setattr(
        run_creation,
        "create_question_run",
        lambda *_args, **kwargs: (create_calls.append(kwargs) or {"runId": "run-auto-1"}),
    )

    # A live formal run already owns the next phase: skip before any create.
    monkeypatch.setattr(
        chain, "_question_non_archived_formal_run_exists", lambda _t, _q: True
    )
    skipped_run = chain.auto_create_formal_run_after_convergence(
        team_id, question_id=_QUESTION_ID
    )
    assert skipped_run == {
        "status": "skipped",
        "reason": "formal_run_exists",
        "roundId": _AUTO_ROUND_ID,
    }

    # Without an accepted adjudication the offer is not on the projection.
    monkeypatch.setattr(
        chain, "_question_non_archived_formal_run_exists", lambda _t, _q: False
    )
    monkeypatch.setattr(
        chain,
        "_latest_round_adjudication",
        lambda *_args, **_kwargs: None,
    )
    skipped_no_adjudication = chain.auto_create_formal_run_after_convergence(
        team_id, question_id=_QUESTION_ID
    )
    assert skipped_no_adjudication == {
        "status": "skipped",
        "reason": "no_accepted_adjudication",
    }
    assert create_calls == []


def test_auto_create_stage_one_question_passes_catalog_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SCI-091: the real create_question_run receives the durable catalog
    authorization resolved by _current_catalog_run_authorization."""
    from core.research.competition.stage_one_completion_policy import (
        load_stage_one_completion_policy,
    )
    from core.web.services.team_workflow import challenge_cup_real_batch
    from core.web.services.team_workflow.research_runtime import run_creation

    team_id, _ledger_path, _events = _auto_create_env(
        tmp_path, monkeypatch, question_id="SCI-091"
    )
    authorization_payload = {
        "authorizationId": "auth-real-1",
        "planId": "real-1",
        "batchScope": {
            "stageOneCompletionPolicy": load_stage_one_completion_policy().to_dict()
        },
    }
    auth_plan_ids: list[str] = []
    monkeypatch.setattr(
        challenge_cup_real_batch,
        "_current_catalog_run_authorization",
        lambda _team_id, plan_id: (
            auth_plan_ids.append(plan_id) or dict(authorization_payload)
        ),
    )
    monkeypatch.setattr(
        run_creation, "assert_writes_allowed", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(run_creation, "get_write_store", lambda: object())
    monkeypatch.setattr(
        run_creation,
        "build_question_run_input",
        lambda *_args, **_kwargs: {
            "teamId": team_id,
            "questionId": "SCI-091",
            "researchScopeEnvelope": {},
            "catalogScope": {},
            "stageOneCompletionPolicy": load_stage_one_completion_policy().to_dict(),
        },
    )
    monkeypatch.setattr(
        run_creation,
        "_formal_hypothesis_handoff",
        lambda *_args, **_kwargs: {"hypothesisSelection": {"selectionId": "s-auto"}},
    )
    create_run_calls: list[dict] = []
    monkeypatch.setattr(
        run_creation,
        "create_run",
        lambda *_args, **kwargs: (
            create_run_calls.append(kwargs) or {"runId": "run-auto-s1"}
        ),
    )
    monkeypatch.setattr(
        chain, "_auto_start_created_formal_run", lambda *_args, **_kwargs: None
    )

    result = chain.auto_create_formal_run_after_convergence(
        team_id, question_id="SCI-091"
    )

    assert result["status"] == "created"
    assert result["runId"] == "run-auto-s1"
    assert auth_plan_ids == ["real-1"]
    assert len(create_run_calls) == 1
    # The authorization reached the real create_question_run unchanged...
    assert create_run_calls[0]["catalog_run_authorization"] == authorization_payload
    # ...and the frozen run input carries the stage-one policy it authorizes.
    assert create_run_calls[0]["run_input"][
        "stageOneCompletionPolicy"
    ] == load_stage_one_completion_policy().to_dict()


def test_auto_create_stage_one_without_authorization_fails_structured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing durable authorization is a structured failure, never a raise."""
    from core.web.services.team_workflow import challenge_cup_real_batch
    from core.web.services.team_workflow.challenge_cup_real_batch import (
        ChallengeCupRealBatchError,
    )
    from core.web.services.team_workflow.research_runtime import run_creation

    team_id, _ledger_path, scene_events = _auto_create_env(
        tmp_path, monkeypatch, question_id="SCI-091"
    )

    def _missing_authorization(_team_id, _plan_id):
        raise ChallengeCupRealBatchError(
            "A durable CatalogRunAuthorization record is required before a real "
            "batch can start.",
            code="catalog_run_authorization_required",
        )

    monkeypatch.setattr(
        challenge_cup_real_batch,
        "_current_catalog_run_authorization",
        _missing_authorization,
    )
    create_calls: list[dict] = []
    monkeypatch.setattr(
        run_creation,
        "create_question_run",
        lambda *_args, **kwargs: (create_calls.append(kwargs) or {"runId": "run-x"}),
    )

    result = chain.auto_create_formal_run_after_convergence(
        team_id, question_id="SCI-091"
    )

    assert result["status"] == "failed"
    assert result["reason"] == "catalog_run_authorization_required"
    assert create_calls == []
    events = [
        fields
        for event, fields in scene_events
        if event == "hypothesis_first.auto_formal_run"
    ]
    assert len(events) == 1
    assert events[0]["outcome"] == "failed"
    assert events[0]["fields"]["reason"] == "catalog_run_authorization_required"


def test_auto_create_skips_rejected_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gate-blocked rejected round is terminal: the formal-run creation
    must skip it (no accepted convergence authority), never fork a run."""
    from core.web.services.team_workflow.research_runtime import run_creation

    rejected_adjudication = {
        "recordKind": chain.HUMAN_ADJUDICATION_KIND,
        "adjudicationId": "hf-adjudication-rejected-1",
        "idempotencyKey": f"hf2:auto-adjudication-rejected:{_AUTO_ROUND_ID}",
        "questionId": _QUESTION_ID,
        "hypothesisRoundId": _AUTO_ROUND_ID,
        "workflowRunId": "",
        "meetingRoundIds": [_AUTO_MEETING_ID],
        "decision": "rejected",
        "rationale": (
            "auto-advance: claim belief gate blocked (claim_data_missing); "
            "review round budget exhausted (5/5); unconverged outcome recorded "
            "per challenge-cup retention policy"
        ),
        "decidedBy": "system:auto-advance:gate-blocked",
        "createdAt": "2026-09-01T00:02:00Z",
        "updatedAt": "2026-09-01T00:02:00Z",
    }
    team_id, _ledger_path, _events = _auto_advance_env(
        tmp_path, monkeypatch, existing_adjudication=rejected_adjudication
    )
    create_calls: list[dict] = []
    monkeypatch.setattr(
        run_creation,
        "create_question_run",
        lambda *_args, **kwargs: (create_calls.append(kwargs) or {"runId": "run-x"}),
    )

    result = chain.auto_create_formal_run_after_convergence(
        team_id, question_id=_QUESTION_ID
    )

    assert result == {"status": "skipped", "reason": "no_accepted_adjudication"}
    assert create_calls == []


def _close_review_meeting_auto_advance_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    question_id: str = _QUESTION_ID,
    round_index: int = 1,
):
    """close_review_meeting seam env: closure machinery faked at the edges."""
    from core.web.services.team_workflow import meeting_rounds

    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    closed_meeting = {
        "meetingRoundId": _AUTO_MEETING_ID,
        "meetingType": chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
        "question": question_id,
        "status": "closed",
    }
    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda _team_id, _meeting_id: {"meetingRound": dict(closed_meeting)},
    )
    monkeypatch.setattr(
        meeting_rounds,
        "approve_meeting_closure",
        lambda _team_id, _meeting_id, _request: {
            "status": "created",
            "meetingRound": dict(closed_meeting),
            "decisions": [],
        },
    )
    monkeypatch.setattr(
        chain,
        "_resolve_review_runners",
        lambda *_args, **_kwargs: {
            "reflection_runner": None,
            "pairwise_runner": None,
            "pareto_runner": None,
            "metareview_runner": None,
            "revision_runner": None,
        },
    )
    monkeypatch.setattr(
        chain,
        "_process_collection_decisions",
        lambda _team_id, _meeting, _result, _request: {
            "requests": [],
            "skipped": [],
        },
    )
    round_record = _auto_advance_round_record(question_id)
    round_record["roundIndex"] = round_index
    monkeypatch.setattr(
        chain,
        "_generate_hypothesis_round",
        lambda _team_id, _meeting, **_kwargs: {
            "roundId": round_record["roundId"],
            "status": round_record["status"],
            "round": round_record,
        },
    )
    monkeypatch.setattr(
        hrounds,
        "get_hypothesis_round",
        lambda _team_id, _round_id: {"round": round_record},
    )
    monkeypatch.setattr(
        chain,
        "_question_hypothesis_rounds",
        lambda _team_id, _round_question: [round_record]
        if str(_round_question).upper() == question_id.upper()
        else [],
    )
    monkeypatch.setattr(
        chain, "_storage_path", lambda _team_id: tmp_path / "chain.jsonl"
    )
    monkeypatch.setattr(
        chain, "_trigger_deferred_next_review", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        chain, "_auto_advance_converge_tick", lambda *_args, **_kwargs: None
    )
    return team_id


def test_close_review_meeting_reports_skipped_auto_advance_within_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id = _close_review_meeting_auto_advance_env(
        tmp_path, monkeypatch, round_index=1
    )

    result = chain.close_review_meeting(team_id, _AUTO_MEETING_ID, {"decisions": []})

    # Budget not spent: the closure result stands and the auto-advance keys
    # report the structural skip only.
    assert result["status"] == "created"
    assert result["autoAdjudication"]["status"] == "skipped"
    assert result["autoAdjudication"]["reason"] == "round_not_exhausted"
    assert result["autoFormalRun"] is None
    assert result["deferredNextReview"] is None


def test_close_review_meeting_auto_advances_exhausted_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import run_creation

    team_id = _close_review_meeting_auto_advance_env(
        tmp_path, monkeypatch, round_index=5
    )
    _allow_chain_claim_belief_gate(monkeypatch)
    monkeypatch.setattr(
        chain, "_question_non_archived_formal_run_exists", lambda _t, _q: False
    )
    create_calls: list[dict] = []
    monkeypatch.setattr(
        run_creation,
        "create_question_run",
        lambda *_args, **kwargs: (
            create_calls.append(kwargs) or {"runId": "run-close-1"}
        ),
    )
    monkeypatch.setattr(
        chain, "_auto_start_created_formal_run", lambda *_args, **_kwargs: None
    )

    result = chain.close_review_meeting(team_id, _AUTO_MEETING_ID, {"decisions": []})

    # Round 5/5 closed in place: adjudicated accepted and the formal run
    # created without any human step, without touching the closure result.
    assert result["status"] == "created"
    assert result["autoAdjudication"]["status"] == "created"
    assert result["autoFormalRun"]["status"] == "created"
    assert result["autoFormalRun"]["runId"] == "run-close-1"
    assert len(create_calls) == 1
    assert create_calls[0]["idempotency_key"] == (
        f"hf2:auto-formal-run:{_QUESTION_ID}:{_AUTO_ROUND_ID}"
    )
    adjudications = _auto_adjudication_records(tmp_path / "chain.jsonl")
    assert [item["decidedBy"] for item in adjudications] == [
        "system:auto-advance:budget-exhausted"
    ]


def test_close_review_meeting_records_rejected_outcome_when_gate_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing the 5/5 round into a blocked claim gate records the rejected
    outcome in place; no formal run is created for a rejected chain."""
    team_id = _close_review_meeting_auto_advance_env(
        tmp_path, monkeypatch, round_index=5
    )

    def _blocked(_team_id, _question_id, candidate_ids):
        return {
            candidate_id: {
                "status": "blocked",
                "reason": "claim_data_missing",
                "claims": [],
                "blockedClaims": [],
            }
            for candidate_id in candidate_ids
        }

    monkeypatch.setattr(chain, "evaluate_claim_belief_gate", _blocked)
    from core.web.services.team_workflow.research_runtime import run_creation

    create_calls: list[dict] = []
    monkeypatch.setattr(
        run_creation,
        "create_question_run",
        lambda *_args, **kwargs: (create_calls.append(kwargs) or {"runId": "run-x"}),
    )

    result = chain.close_review_meeting(team_id, _AUTO_MEETING_ID, {"decisions": []})

    assert result["status"] == "created"
    assert result["autoAdjudication"]["status"] == "rejected"
    assert result["autoAdjudication"]["decision"] == "rejected"
    # A rejected chain owns no formal-run transition.
    assert result["autoFormalRun"] is None
    assert create_calls == []
    adjudications = _auto_adjudication_records(tmp_path / "chain.jsonl")
    assert [item["decidedBy"] for item in adjudications] == [
        "system:auto-advance:gate-blocked"
    ]
