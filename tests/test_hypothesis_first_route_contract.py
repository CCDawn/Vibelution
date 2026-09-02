"""Hypothesis-first route contract regressions (HF-5).

两层契约：
1. DTO 模型契约——响应模型发布稳定字段、保留未知键、不填默认；payload
   模型在边界拒绝缺字段请求。
2. HTTP 路由契约——URL 注册、payload 原样透传到 service、响应形状与
   错误映射（404/422）。service 一律 monkeypatch，业务语义由 service 侧
   测试与 HF-7 端到端覆盖。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes.team_workflows import hypothesis_first as hf_routes
from core.web.routes.team_workflows.hypothesis_first_models import (
    ChainStateResponse,
    CloseReviewMeetingResponse,
    CollectionHandoffResponse,
    CollectionRequestListResponse,
    HypothesisRoundListResponse,
    HypothesisRoundResponse,
    HypothesisSelectionListResponse,
    HypothesisSelectionRecordPayload,
    HypothesisSelectionRecordResponse,
    HypothesisSelectionResponse,
    MeetingApproveDigestPayload,
    MeetingClosureApprovePayload,
    MeetingDecisionPayload,
    MeetingDigestDraftPayload,
    MeetingRoundListResponse,
    MeetingRoundMutationResponse,
    MeetingRoundResponse,
    MeetingSourceMessagesResponse,
    MeetingSummaryDraftRequest,
    ReviewRoundLinkListResponse,
    SelectionContextResponse,
)
from core.web.services.team_service import TeamNotFoundError
from core.web.services.team_workflow import (
    hypothesis_rounds,
    hypothesis_selection,
    meeting_rounds,
    meeting_runtime,
    research_project_agent_sessions,
    research_project_hypothesis_context,
)
from core.web.services.team_workflow.research_runtime import hypothesis_first_chain


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


# ---------------------------------------------------------------------------
# DTO model contract
# ---------------------------------------------------------------------------


def test_hypothesis_first_models_publish_known_schema_fields() -> None:
    expected_properties = {
        HypothesisSelectionRecordResponse: {
            "schemaVersion",
            "teamId",
            "status",
            "selection",
            "reviewMeeting",
            "storagePath",
        },
        HypothesisSelectionResponse: {"schemaVersion", "teamId", "selection", "storagePath"},
        HypothesisSelectionListResponse: {
            "schemaVersion",
            "teamId",
            "selectionCount",
            "selections",
            "storagePath",
        },
        SelectionContextResponse: {
            "schemaVersion",
            "teamId",
            "questionId",
            "scope",
            "mode",
            "candidates",
            "defaultSelectedCandidateIds",
            "latestSelection",
        },
        MeetingRoundResponse: {"schemaVersion", "teamId", "meetingRound", "storagePath"},
        MeetingRoundMutationResponse: {
            "schemaVersion",
            "teamId",
            "status",
            "meetingRound",
            "digestDraft",
            "storagePath",
        },
        MeetingRoundListResponse: {
            "schemaVersion",
            "teamId",
            "meetingCount",
            "meetings",
            "storagePath",
        },
        MeetingSourceMessagesResponse: {
            "schemaVersion",
            "teamId",
            "meetingRoundId",
            "messageCount",
            "messages",
        },
        HypothesisRoundResponse: {"schemaVersion", "teamId", "round", "storagePath"},
        HypothesisRoundListResponse: {
            "schemaVersion",
            "teamId",
            "roundCount",
            "rounds",
            "storagePath",
        },
        CollectionRequestListResponse: {
            "schemaVersion",
            "teamId",
            "requestCount",
            "requests",
            "storagePath",
        },
        ReviewRoundLinkListResponse: {
            "schemaVersion",
            "teamId",
            "linkCount",
            "links",
            "storagePath",
        },
        ChainStateResponse: {
            "schemaVersion",
            "teamId",
            "questionId",
            "selectionId",
            "meetingCount",
            "firstMeetingId",
            "firstMeetingClosed",
            "openMeetingIds",
            "collectionRequests",
            "collectionRequestCount",
            "pendingCollectionCount",
            "collectionReady",
            "hypothesisRoundCount",
            "latestHypothesisRoundId",
            "hypothesisConverged",
            "convergenceDetail",
            "roundBudget",
            "budgetExhausted",
            "templateBaselineExists",
            "templateBaselineIds",
        },
        CloseReviewMeetingResponse: {
            "schemaVersion",
            "teamId",
            "status",
            "closed",
            "meetingRound",
            "digest",
            "decisions",
            "collection",
            "hypothesisRound",
            "resume",
            "storagePath",
        },
        CollectionHandoffResponse: {
            "schemaVersion",
            "teamId",
            "status",
            "request",
            "nextMeeting",
            "resume",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_hypothesis_first_responses_keep_unknown_fields_without_injecting_defaults() -> None:
    payload = ChainStateResponse.model_validate(
        {
            "teamId": "team-1",
            "questionId": "SCI-096",
            "hypothesisConverged": True,
            "futureHint": {"owner": "hypothesis_first"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "teamId": "team-1",
        "questionId": "SCI-096",
        "hypothesisConverged": True,
        "futureHint": {"owner": "hypothesis_first"},
    }


def test_selection_payload_requires_scope_and_candidates() -> None:
    with pytest.raises(ValidationError):
        HypothesisSelectionRecordPayload.model_validate({"questionId": "SCI-096"})

    payload = HypothesisSelectionRecordPayload.model_validate(
        {
            "program": "XH-202619",
            "theme": "cc-neuro-001",
            "campaign": "cc-campaign-neuro-001",
            "question": "SCI-096",
            "agentId": "operator",
            "questionId": "SCI-096",
            "selectedCandidateIds": ["hyp-a", "hyp-b"],
            "decidedBy": "operator",
        }
    )
    assert payload.branch == "main"
    assert payload.workflow == "hypothesis_first"
    assert payload.mode == "formal"


def test_digest_draft_payload_requires_summary_and_source_refs() -> None:
    with pytest.raises(ValidationError):
        MeetingDigestDraftPayload.model_validate({"sourceMessageRefs": ["m-1"]})
    with pytest.raises(ValidationError):
        MeetingDigestDraftPayload.model_validate({"summary": "s", "sourceMessageRefs": []})


def test_digest_draft_payload_keeps_candidates_and_evidence_requests() -> None:
    payload = MeetingDigestDraftPayload.model_validate(
        {
            "summary": "讨论收敛",
            "sourceMessageRefs": ["m-1"],
            "proposedCandidates": [
                {"candidateId": "c1", "statement": "腺苷假说", "rationale": "机制"}
            ],
            "evidenceRequests": [
                {
                    "rationale": "需要更多论文",
                    "candidateRefs": ["hyp-a"],
                    "searchEnvelope": {"keywords": ["nslb"]},
                }
            ],
        }
    )
    dumped = payload.model_dump()
    assert dumped["proposedCandidates"][0]["candidateId"] == "c1"
    assert dumped["evidenceRequests"][0]["searchEnvelope"]["keywords"] == ["nslb"]


def test_decision_payload_requirements_are_object() -> None:
    payload = MeetingDecisionPayload.model_validate(
        {
            "decision": "request_new_evidence",
            "rationale": "need more evidence",
            "decidedBy": "operator",
            "requirements": {"minEvidenceLevel": "medium"},
        }
    )
    assert payload.requirements == {"minEvidenceLevel": "medium"}


def test_summary_draft_and_approve_digest_payloads_are_minimal() -> None:
    draft_req = MeetingSummaryDraftRequest.model_validate({"actor": "operator"})
    assert draft_req.force is False
    approve = MeetingApproveDigestPayload.model_validate(
        {"closedBy": "operator", "expectedDigestContentHash": "abc"}
    )
    assert approve.expectedDigestContentHash == "abc"


def test_closure_payload_requires_at_least_one_decision() -> None:
    with pytest.raises(ValidationError):
        MeetingClosureApprovePayload.model_validate({"decisions": []})
    with pytest.raises(ValidationError):
        MeetingClosureApprovePayload.model_validate(
            {"decisions": [{"decision": "advance", "rationale": "", "decidedBy": "op"}]}
        )

    payload = MeetingClosureApprovePayload.model_validate(
        {
            "decisions": [
                {
                    "decision": "request_new_evidence",
                    "rationale": "need more evidence",
                    "decidedBy": "operator",
                    "searchEnvelope": {"keywords": ["nslb"]},
                }
            ],
            "closedBy": "operator",
        }
    )
    dumped = payload.model_dump()
    assert dumped["decisions"][0]["searchEnvelope"] == {"keywords": ["nslb"]}
    assert dumped["decisions"][0]["status"] == "adopted"


# ---------------------------------------------------------------------------
# HTTP route contract
# ---------------------------------------------------------------------------


def _expected_routes() -> set[tuple[str, str]]:
    prefix = "/api/teams/{team_id}/workflow-orchestration"
    return {
        ("POST", f"{prefix}/hypothesis-first/selections"),
        ("GET", f"{prefix}/hypothesis-first/selections"),
        ("GET", f"{prefix}/hypothesis-first/selections/latest"),
        ("GET", f"{prefix}/hypothesis-first/selections/{{selection_id}}"),
        (
            "GET",
            f"{prefix}/hypothesis-first/questions/{{question_id}}/selection-context",
        ),
        (
            "GET",
            f"{prefix}/hypothesis-first/questions/{{question_id}}/candidates/evidence-trail",
        ),
        ("POST", f"{prefix}/hypothesis-first/candidate-generation"),
        ("GET", f"{prefix}/meeting-rounds"),
        ("GET", f"{prefix}/meeting-rounds/{{meeting_round_id}}"),
        ("GET", f"{prefix}/meeting-rounds/{{meeting_round_id}}/source-messages"),
        ("POST", f"{prefix}/meeting-rounds/{{meeting_round_id}}/summary"),
        ("POST", f"{prefix}/meeting-rounds/{{meeting_round_id}}/summary-draft"),
        ("POST", f"{prefix}/meeting-rounds/{{meeting_round_id}}/digest-draft"),
        ("POST", f"{prefix}/meeting-rounds/{{meeting_round_id}}/digest-reject"),
        ("POST", f"{prefix}/meeting-rounds/{{meeting_round_id}}/closure"),
        ("GET", f"{prefix}/hypothesis-rounds"),
        ("GET", f"{prefix}/hypothesis-rounds/{{round_id}}"),
        ("GET", f"{prefix}/hypothesis-first/chain/state"),
        ("GET", f"{prefix}/hypothesis-first/chain/collection-requests"),
        ("GET", f"{prefix}/hypothesis-first/chain/review-round-links"),
        (
            "POST",
            f"{prefix}/hypothesis-first/chain/review-meetings/{{meeting_round_id}}/close",
        ),
        (
            "POST",
            f"{prefix}/hypothesis-first/chain/meetings/{{meeting_round_id}}/approve-digest",
        ),
        (
            "POST",
            f"{prefix}/hypothesis-first/chain/collection-requests/{{request_id}}/handoff",
        ),
        (
            "POST",
            f"{prefix}/hypothesis-first/chain/collection-requests/{{request_id}}/recover",
        ),
    }


def test_hypothesis_first_routes_are_registered() -> None:
    """The domain router exposes the expected hypothesis-first paths.

    FastAPI 0.141 mounts routers lazily (``_IncludedRouter``), so app-level
    inspection cannot see expanded paths; the shared team_workflows router is
    the authoritative registration surface, and the TestClient cases below
    prove request-time resolution through the ``/api`` mount.
    """
    from core.web.routes.team_workflows import router as domain_router

    registered = {
        (method, route.path)
        for route in domain_router.routes
        for method in (getattr(route, "methods", None) or set())
        if "workflow-orchestration" in getattr(route, "path", "")
    }
    missing = {
        (method, path.removeprefix("/api"))
        for method, path in _expected_routes()
    } - registered
    assert not missing, f"missing routes: {sorted(missing)}"


def test_selection_record_route_passes_payload_through(monkeypatch) -> None:
    calls = []

    def fake_record(team_id, payload=None, **kwargs):
        calls.append({"teamId": team_id, "payload": dict(payload or {}), "kwargs": kwargs})
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "status": "created",
            "selection": {"selectionId": "hsel-1", "questionId": "SCI-096"},
            "reviewMeeting": {"meetingRoundId": "mr-1"},
            "storagePath": "x",
        }

    monkeypatch.setattr(hypothesis_selection, "record_hypothesis_selection", fake_record)
    client = _client()
    body = {
        "program": "XH-202619",
        "theme": "cc-neuro-001",
        "campaign": "cc-campaign-neuro-001",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_first",
        "agentId": "operator",
        "mode": "dev",
        "questionId": "SCI-096",
        "selectedCandidateIds": ["hyp-a", "hyp-b"],
        "decidedBy": "operator",
    }
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/selections",
        json=body,
    )

    assert response.status_code == 201, response.text
    assert calls[0]["teamId"] == "team-1"
    assert (
        calls[0]["payload"]
        == HypothesisSelectionRecordPayload.model_validate(body).model_dump()
    )
    data = response.json()
    assert data["status"] == "created"
    assert data["selection"]["selectionId"] == "hsel-1"


def test_selection_record_route_rejects_incomplete_payload() -> None:
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/selections",
        json={"questionId": "SCI-096"},
    )
    assert response.status_code == 422


def test_selection_query_routes(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        hf_routes,
        "_selection_read_scope",
        lambda team_id, question_id: {
            "program": "test-program",
            "theme": "test-theme",
            "campaign": "test-campaign",
            "question": question_id,
            "branch": "main",
            "workflow": "hypothesis_first",
            "agentId": "operator",
            "mode": "dev",
            "scopeHash": "test-scope-hash",
        },
    )
    monkeypatch.setattr(
        hypothesis_selection,
        "list_hypothesis_selections",
        lambda team_id, question_id="", *, workflow_run_id="": calls.append(
            {
                "kind": "list",
                "questionId": question_id,
                "workflowRunId": workflow_run_id,
            }
        )
        or {
            "schemaVersion": 1,
            "teamId": team_id,
            "selectionCount": 1,
            "selections": [{"selectionId": "hsel-1", "questionId": question_id}],
            "storagePath": "x",
        },
    )
    monkeypatch.setattr(
        hypothesis_selection,
        "get_latest_hypothesis_selection",
        lambda team_id, question_id, *, scope=None, workflow_run_id="": calls.append(
            {
                "kind": "latest",
                "questionId": question_id,
                "workflowRunId": workflow_run_id,
            }
        )
        or {
            "schemaVersion": 1,
            "teamId": team_id,
            "selection": {"selectionId": "hsel-2", "questionId": question_id},
            "storagePath": "x",
        },
    )
    monkeypatch.setattr(
        hypothesis_selection,
        "get_hypothesis_selection",
        lambda team_id, selection_id: {
            "schemaVersion": 1,
            "teamId": team_id,
            "selection": {"selectionId": selection_id},
            "storagePath": "x",
        },
    )
    client = _client()

    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/selections",
        params={"questionId": "SCI-096", "runId": "run-096"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["selections"][0]["questionId"] == "SCI-096"

    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/selections/latest",
        params={"questionId": "SCI-096", "runId": "run-096"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["selection"]["selectionId"] == "hsel-2"
    assert calls == [
        {"kind": "list", "questionId": "SCI-096", "workflowRunId": "run-096"},
        {"kind": "latest", "questionId": "SCI-096", "workflowRunId": "run-096"},
    ]

    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/selections/hsel-9",
    )
    assert response.status_code == 200, response.text
    assert response.json()["selection"]["selectionId"] == "hsel-9"


def test_selection_latest_maps_not_found_to_404(monkeypatch) -> None:
    def fake_latest(team_id, question_id, *, scope=None, workflow_run_id=""):
        raise hypothesis_selection.ResearchHypothesisSelectionNotFoundError(
            "No hypothesis selection recorded for this question."
        )

    monkeypatch.setattr(
        hypothesis_selection, "get_latest_hypothesis_selection", fake_latest
    )
    client = _client()
    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/selections/latest",
        params={"questionId": "SCI-096"},
    )
    assert response.status_code == 404


def test_selection_routes_map_domain_error_to_422(monkeypatch) -> None:
    def fake_record(team_id, payload=None, **kwargs):
        raise hypothesis_selection.ResearchHypothesisSelectionError(
            "re-selection for a scoped question requires previousSelectionId"
        )

    monkeypatch.setattr(hypothesis_selection, "record_hypothesis_selection", fake_record)
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/selections",
        json={
            "program": "XH-202619",
            "theme": "cc-neuro-001",
            "campaign": "cc-campaign-neuro-001",
            "question": "SCI-096",
            "agentId": "operator",
            "questionId": "SCI-096",
            "selectedCandidateIds": ["hyp-a", "hyp-b"],
            "decidedBy": "operator",
        },
    )
    assert response.status_code == 422


def _retry_command_body() -> dict[str, object]:
    return {
        "actionId": "retry-formal-node:run-d02722658d8b:source_extraction",
        "idempotencyKey": "offer:run-d02722658d8b:source_extraction:retry_node:a2:v3",
        "expectedStateVersion": "hf2-action:before-retry",
        "payload": {
            "runId": "run-d02722658d8b",
            "nodeId": "source_extraction",
        },
    }


def test_chain_commands_keep_structured_readiness_rejection(monkeypatch) -> None:
    """A readiness-blocked formal retry must return 412 with blocker details."""

    def fake_execute(team_id, payload, *, question_id="", workflow_run_id=""):
        raise hypothesis_first_chain.FormalCommandRejectedError(
            "节点尚未就绪，无法开始新的尝试。",
            code="node_not_ready",
            status_code=412,
            blockers=[{
                "code": "auto_advance_not_ready",
                "title": "缺少来源候选",
                "detail": "auto_advance_not_ready/source_candidates_missing",
                "category": "dependency",
            }],
        )

    monkeypatch.setattr(hypothesis_first_chain, "execute_v2_command", fake_execute)
    client = _client()
    response = client.post(
        "/api/teams/research-team/workflow-orchestration/hypothesis-first/chain/commands",
        params={"questionId": "SCI-003"},
        json=_retry_command_body(),
    )
    assert response.status_code == 412, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "node_not_ready"
    assert detail["message"] == "节点尚未就绪，无法开始新的尝试。"
    assert detail["blockers"][0]["code"] == "auto_advance_not_ready"
    assert (
        detail["blockers"][0]["detail"]
        == "auto_advance_not_ready/source_candidates_missing"
    )


def test_chain_commands_map_runtime_guard_rejection_to_409(monkeypatch) -> None:
    def fake_execute(team_id, payload, *, question_id="", workflow_run_id=""):
        raise hypothesis_first_chain.FormalCommandRejectedError(
            "attempt running 不可重试",
            code="command_not_allowed",
            status_code=409,
        )

    monkeypatch.setattr(hypothesis_first_chain, "execute_v2_command", fake_execute)
    client = _client()
    response = client.post(
        "/api/teams/research-team/workflow-orchestration/hypothesis-first/chain/commands",
        params={"questionId": "SCI-003"},
        json=_retry_command_body(),
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "command_not_allowed"
    assert detail["message"] == "attempt running 不可重试"
    assert "blockers" not in detail


# ---------------------------------------------------------------------------
# chain/commands wire round-trip: ``_find_allowed_command`` re-authorizes by
# strict payload equality against the projected offer, so the route must not
# let wire-model defaults (RecordSelectionPayload.previousSelectionId,
# OpenGenerationPayload.runId) materialize inside a verbatim offer echo.
# Regression for the live 422 "command is no longer allowed" that killed every
# plain record-selection/open_generation click after those defaults landed.
# ---------------------------------------------------------------------------


def _captured_execute(capture: list[dict[str, object]]):
    def fake_execute(team_id, payload, *, question_id="", workflow_run_id=""):
        capture.append(
            {
                "teamId": team_id,
                "questionId": question_id,
                "workflowRunId": workflow_run_id,
                "request": dict(payload),
            }
        )
        return {"schemaVersion": 2, "status": "executed"}

    return fake_execute


def test_chain_commands_round_trip_plain_record_selection_payload(
    monkeypatch,
) -> None:
    capture: list[dict[str, object]] = []
    monkeypatch.setattr(
        hypothesis_first_chain, "execute_v2_command", _captured_execute(capture)
    )
    client = _client()
    response = client.post(
        "/api/teams/research-team/workflow-orchestration/hypothesis-first/chain/commands",
        params={"questionId": "SCI-001", "runId": "run-2e157e016745"},
        json={
            "actionId": "record-selection",
            "idempotencyKey": "hf2:record-selection:3a3f495a8fe91f64",
            "expectedStateVersion": "hf2-action:hf-reset-b5c1898fe76a516f:e0b73e7ad7d48ae8",
            "payload": {
                "questionId": "SCI-001",
                "generationAttemptId": "hf-candgen-80e9711246ab2b0c-a2",
            },
            "input": {
                "candidateIds": ["sci-001-c2cf3fdbf", "sci-001-c36554759"]
            },
        },
    )
    assert response.status_code == 200, response.text
    assert len(capture) == 1
    request = capture[0]["request"]
    # The plain offer payload carries exactly these two keys; a model-injected
    # ``previousSelectionId: ""`` would break strict re-authorization.
    assert request["payload"] == {
        "questionId": "SCI-001",
        "generationAttemptId": "hf-candgen-80e9711246ab2b0c-a2",
    }
    assert request["input"] == {
        "candidateIds": ["sci-001-c2cf3fdbf", "sci-001-c36554759"]
    }
    assert capture[0]["workflowRunId"] == "run-2e157e016745"


def test_chain_commands_round_trip_explicit_previous_selection_id(
    monkeypatch,
) -> None:
    """The rejected-adjudication re-selection offer keeps its rooted chain."""

    capture: list[dict[str, object]] = []
    monkeypatch.setattr(
        hypothesis_first_chain, "execute_v2_command", _captured_execute(capture)
    )
    client = _client()
    response = client.post(
        "/api/teams/research-team/workflow-orchestration/hypothesis-first/chain/commands",
        params={"questionId": "SCI-001"},
        json={
            "actionId": "record-selection",
            "idempotencyKey": "hf2:record-selection:reselect-1",
            "expectedStateVersion": "hf2-action:hf-reset-x:reselect",
            "payload": {
                "questionId": "SCI-001",
                "generationAttemptId": "hf-candgen-80e9711246ab2b0c-a2",
                "previousSelectionId": "hsel-3e278e50b271d28b",
            },
        },
    )
    assert response.status_code == 200, response.text
    request = capture[0]["request"]
    assert request["payload"]["previousSelectionId"] == "hsel-3e278e50b271d28b"


def test_chain_commands_round_trip_plain_open_generation_payload(
    monkeypatch,
) -> None:
    capture: list[dict[str, object]] = []
    monkeypatch.setattr(
        hypothesis_first_chain, "execute_v2_command", _captured_execute(capture)
    )
    client = _client()
    response = client.post(
        "/api/teams/research-team/workflow-orchestration/hypothesis-first/chain/commands",
        params={"questionId": "SCI-096"},
        json={
            "actionId": "open-generation",
            "idempotencyKey": "hf2:open-generation:1",
            "expectedStateVersion": "hf2-action:hf-reset-y:open",
            "payload": {"questionId": "SCI-096"},
        },
    )
    assert response.status_code == 200, response.text
    request = capture[0]["request"]
    # The bare origin-level offer payload has no runId; injecting an empty
    # default would break re-authorization for non-stage-one questions.
    assert request["payload"] == {"questionId": "SCI-096"}


def test_selection_context_derives_scope_from_frozen_registry(monkeypatch) -> None:
    monkeypatch.setattr(
        hf_routes,
        "get_challenge_question_run_detail",
        lambda team_id, question_id, *, run_id="": {
            "teamId": team_id,
            "questionId": question_id,
            "output": {
                "hypotheses": [
                    {"hypothesis_id": "hyp-a", "statement": "A"},
                    {"hypothesis_id": "hyp-b", "statement": "B"},
                    {"statement": "no id is dropped"},
                ],
                "selection": {"selected_hypothesis_id": "hyp-b"},
            },
        },
    )
    monkeypatch.setattr(
        hf_routes,
        "frozen_theme_registry",
        lambda: {
            "cc-neuro-001": {
                "themeId": "cc-neuro-001",
                "campaignId": "cc-campaign-neuro-001",
                "questionId": "SCI-096",
            }
        },
    )

    class _Contract:
        programId = "XH-202619"
        themeId = "cc-neuro-001"
        campaignId = "cc-campaign-neuro-001"

        def is_dev_theme(self):
            return False

        def is_activated(self):
            return True

    monkeypatch.setattr(
        hf_routes,
        "resolve_theme_contract",
        lambda team_id, *, theme_id, campaign_id="": _Contract(),
    )
    monkeypatch.setattr(
        hypothesis_selection,
        "get_latest_hypothesis_selection",
        lambda team_id, question_id, *, scope=None, workflow_run_id="": {
            "schemaVersion": 1,
            "teamId": team_id,
            "selection": {"selectionId": "hsel-1"},
            "storagePath": "x",
        },
    )
    monkeypatch.setattr(
        meeting_rounds,
        "list_meeting_rounds",
        lambda team_id: {
            "schemaVersion": 1,
            "teamId": team_id,
            "meetingCount": 3,
            "meetings": [
                {
                    "meetingRoundId": "mr-other-question",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "status": "closed",
                },
                {
                    "meetingRoundId": "mr-not-review",
                    "meetingType": "kickoff",
                    "question": "SCI-096",
                    "status": "closed",
                },
                {
                    "meetingRoundId": "mr-review-1",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-096",
                    "status": "awaiting_approval",
                },
            ],
            "storagePath": "x",
        },
    )

    client = _client()
    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/questions/SCI-096/selection-context"
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["scope"] == {
        "program": "XH-202619",
        "theme": "cc-neuro-001",
        "campaign": "cc-campaign-neuro-001",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_first",
        "agentId": "operator",
    }
    assert data["mode"] == "formal"
    assert [item["hypothesis_id"] for item in data["candidates"]] == ["hyp-a", "hyp-b"]
    assert data["defaultSelectedCandidateIds"] == ["hyp-b"]
    assert data["latestSelection"]["selectionId"] == "hsel-1"
    assert data["reviewMeeting"]["meetingRoundId"] == "mr-review-1"
    assert data["reviewMeeting"]["status"] == "awaiting_approval"


def test_selection_context_falls_back_to_dev_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        hf_routes,
        "get_challenge_question_run_detail",
        lambda team_id, question_id, *, run_id="": {
            "teamId": team_id,
            "questionId": question_id,
            "output": {"hypotheses": [], "selection": {}},
        },
    )
    monkeypatch.setattr(hf_routes, "frozen_theme_registry", dict)

    class _DevContract:
        programId = "dev-program"
        themeId = "dev-sci-999"
        campaignId = "dev-campaign"

        def is_dev_theme(self):
            return True

        def is_activated(self):
            return False

    monkeypatch.setattr(
        hf_routes,
        "resolve_theme_contract",
        lambda team_id, *, theme_id, campaign_id="": _DevContract(),
    )

    def fake_latest(team_id, question_id, *, scope=None, workflow_run_id=""):
        raise hypothesis_selection.ResearchHypothesisSelectionNotFoundError("none")

    monkeypatch.setattr(
        hypothesis_selection, "get_latest_hypothesis_selection", fake_latest
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "list_hypothesis_candidates",
        lambda team_id, question_id="", *, workflow_run_id="": {
            "schemaVersion": 1,
            "teamId": team_id,
            "candidates": [],
        },
    )

    client = _client()
    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/questions/SCI-999/selection-context"
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == "dev"
    assert data["scope"]["theme"] == "dev-sci-999"
    assert data["latestSelection"] is None
    assert data["defaultSelectedCandidateIds"] == []
    assert data["reviewMeeting"] is None


def test_selection_context_cold_start_uses_ledger_candidates(monkeypatch) -> None:
    """Catalog question without an approved artifact: no 404, ledger candidates."""

    def fake_detail(team_id, question_id, *, run_id=""):
        raise ValueError("challenge_question_run_not_found")

    monkeypatch.setattr(hf_routes, "get_challenge_question_run_detail", fake_detail)
    monkeypatch.setattr(hf_routes, "frozen_theme_registry", dict)

    class _DevContract:
        programId = "dev-program"
        themeId = "dev-sci-002"
        campaignId = "dev-campaign"

        def is_dev_theme(self):
            return True

        def is_activated(self):
            return False

    monkeypatch.setattr(
        hf_routes,
        "resolve_theme_contract",
        lambda team_id, *, theme_id, campaign_id="": _DevContract(),
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "list_hypothesis_candidates",
        lambda team_id, question_id="", *, workflow_run_id="": {
            "schemaVersion": 1,
            "teamId": team_id,
            "candidates": [
                {
                    "candidateId": "cand-1",
                    "statement": "睡眠剥夺通过腺苷积累损害记忆巩固",
                    "rationale": "腺苷假说",
                },
            ],
        },
    )

    def fake_latest(team_id, question_id, *, scope=None, workflow_run_id=""):
        raise hypothesis_selection.ResearchHypothesisSelectionNotFoundError("none")

    monkeypatch.setattr(
        hypothesis_selection, "get_latest_hypothesis_selection", fake_latest
    )
    monkeypatch.setattr(
        meeting_rounds,
        "list_meeting_rounds",
        lambda team_id: {
            "schemaVersion": 1,
            "teamId": team_id,
            "meetingCount": 1,
            "meetings": [
                {
                    "meetingRoundId": "mr-gen-1",
                    "meetingType": "hypothesis_candidate_generation",
                    "question": "SCI-002",
                    "status": "closed",
                },
            ],
            "storagePath": "x",
        },
    )

    client = _client()
    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/questions/SCI-002/selection-context"
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert [item["hypothesis_id"] for item in data["candidates"]] == ["cand-1"]
    assert data["candidates"][0]["statement"] == "睡眠剥夺通过腺苷积累损害记忆巩固"
    assert data["generationMeeting"]["meetingRoundId"] == "mr-gen-1"
    assert data["reviewMeeting"] is None


def test_selection_context_unknown_question_falls_back_to_dev_mode(monkeypatch) -> None:
    """Unknown/catalog-cold-start questions no longer 404: dev-mode context."""

    def fake_detail(team_id, question_id, *, run_id=""):
        raise ValueError("challenge_question_run_not_found")

    monkeypatch.setattr(hf_routes, "get_challenge_question_run_detail", fake_detail)
    monkeypatch.setattr(hf_routes, "frozen_theme_registry", dict)

    class _DevContract:
        programId = "dev-program"
        themeId = "dev-sci-404"
        campaignId = "dev-campaign"

        def is_dev_theme(self):
            return True

        def is_activated(self):
            return False

    monkeypatch.setattr(
        hf_routes,
        "resolve_theme_contract",
        lambda team_id, *, theme_id, campaign_id="": _DevContract(),
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "list_hypothesis_candidates",
        lambda team_id, question_id="", *, workflow_run_id="": {
            "schemaVersion": 1,
            "teamId": team_id,
            "candidates": [],
        },
    )

    def fake_latest(team_id, question_id, *, scope=None, workflow_run_id=""):
        raise hypothesis_selection.ResearchHypothesisSelectionNotFoundError("none")

    monkeypatch.setattr(
        hypothesis_selection, "get_latest_hypothesis_selection", fake_latest
    )

    client = _client()
    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/questions/SCI-404/selection-context"
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == "dev"
    assert data["candidates"] == []
    assert data["generationMeeting"] is None


def test_meeting_round_read_routes(monkeypatch) -> None:
    monkeypatch.setattr(
        meeting_rounds,
        "list_meeting_rounds",
        lambda team_id: {
            "schemaVersion": 1,
            "teamId": team_id,
            "meetingCount": 1,
            "meetings": [{"meetingRoundId": "mr-1", "status": "open"}],
            "storagePath": "x",
        },
    )
    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda team_id, meeting_round_id: {
            "schemaVersion": 1,
            "teamId": team_id,
            "meetingRound": {"meetingRoundId": meeting_round_id, "status": "open"},
            "storagePath": "x",
        },
    )
    monkeypatch.setattr(
        meeting_rounds,
        "meeting_source_messages",
        lambda record: [{"messageId": "m-1", "roundId": "r-1"}],
    )
    client = _client()

    response = client.get("/api/teams/team-1/workflow-orchestration/meeting-rounds")
    assert response.status_code == 200, response.text
    assert response.json()["meetings"][0]["meetingRoundId"] == "mr-1"

    response = client.get("/api/teams/team-1/workflow-orchestration/meeting-rounds/mr-1")
    assert response.status_code == 200, response.text
    assert response.json()["meetingRound"]["status"] == "open"

    response = client.get(
        "/api/teams/team-1/workflow-orchestration/meeting-rounds/mr-1/source-messages"
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["messageCount"] == 1
    assert data["messages"][0]["messageId"] == "m-1"


def test_meeting_round_transition_routes_pass_arguments(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        meeting_rounds,
        "begin_meeting_summary",
        lambda team_id, meeting_round_id, *, actor="", human_triggered=False: calls.append(
            {"kind": "summary", "actor": actor, "humanTriggered": human_triggered}
        )
        or {
            "schemaVersion": 1,
            "teamId": team_id,
            "status": "summarizing",
            "meetingRound": {"meetingRoundId": meeting_round_id},
            "storagePath": "x",
        },
    )
    monkeypatch.setattr(
        meeting_rounds,
        "submit_meeting_digest_draft",
        lambda team_id, meeting_round_id, draft=None: calls.append(
            {"kind": "draft", "draft": dict(draft or {})}
        )
        or {
            "schemaVersion": 1,
            "teamId": team_id,
            "status": "awaiting_approval",
            "meetingRound": {"meetingRoundId": meeting_round_id},
            "digestDraft": dict(draft or {}),
            "storagePath": "x",
        },
    )
    monkeypatch.setattr(
        meeting_rounds,
        "reject_meeting_digest_draft",
        lambda team_id, meeting_round_id, *, actor="", reason="": calls.append(
            {"kind": "reject", "actor": actor, "reason": reason}
        )
        or {
            "schemaVersion": 1,
            "teamId": team_id,
            "status": "summarizing",
            "meetingRound": {"meetingRoundId": meeting_round_id},
            "storagePath": "x",
        },
    )
    monkeypatch.setattr(
        meeting_rounds,
        "approve_meeting_closure",
        lambda team_id, meeting_round_id, payload=None: calls.append(
            {"kind": "closure", "payload": dict(payload or {})}
        )
        or {
            "schemaVersion": 1,
            "teamId": team_id,
            "status": "created",
            "closed": True,
            "meetingRound": {"meetingRoundId": meeting_round_id, "status": "closed"},
            "digest": {"digestId": "d-1"},
            "decisions": [{"decisionId": "dec-1"}],
            "storagePath": "x",
        },
    )
    client = _client()

    response = client.post(
        "/api/teams/team-1/workflow-orchestration/meeting-rounds/mr-1/summary",
        json={"actor": "operator", "humanTriggered": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "summarizing"
    assert calls[-1] == {"kind": "summary", "actor": "operator", "humanTriggered": True}

    draft = {
        "summary": "讨论收敛",
        "sourceMessageRefs": ["m-1"],
        "agreements": ["同意 A"],
        "disagreements": [],
        "actionItems": [],
        "risks": [],
        "knowledgeCandidates": [],
    }
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/meeting-rounds/mr-1/digest-draft",
        json=draft,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "awaiting_approval"
    assert calls[-1]["draft"]["summary"] == "讨论收敛"

    response = client.post(
        "/api/teams/team-1/workflow-orchestration/meeting-rounds/mr-1/digest-reject",
        json={"actor": "operator", "reason": "缺少风险节"},
    )
    assert response.status_code == 200, response.text
    assert calls[-1] == {"kind": "reject", "actor": "operator", "reason": "缺少风险节"}

    response = client.post(
        "/api/teams/team-1/workflow-orchestration/meeting-rounds/mr-1/closure",
        json={
            "decisions": [
                {
                    "decision": "advance",
                    "rationale": "证据充分",
                    "decidedBy": "operator",
                }
            ],
            "closedBy": "operator",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["closed"] is True
    assert data["digest"]["digestId"] == "d-1"
    assert calls[-1]["payload"]["decisions"][0]["decision"] == "advance"


def test_meeting_round_transition_conflict_maps_to_422(monkeypatch) -> None:
    def fake_begin(team_id, meeting_round_id, *, actor="", human_triggered=False):
        raise meeting_rounds.ResearchMeetingRoundError(
            "meeting round status must be open to begin summary"
        )

    monkeypatch.setattr(meeting_rounds, "begin_meeting_summary", fake_begin)
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/meeting-rounds/mr-1/summary",
        json={"actor": "operator"},
    )
    assert response.status_code == 422


def test_meeting_round_not_found_maps_to_404(monkeypatch) -> None:
    def fake_get(team_id, meeting_round_id):
        raise meeting_rounds.ResearchMeetingRoundNotFoundError("not found")

    monkeypatch.setattr(meeting_rounds, "get_meeting_round", fake_get)
    client = _client()
    response = client.get("/api/teams/team-1/workflow-orchestration/meeting-rounds/mr-x")
    assert response.status_code == 404


def test_hypothesis_round_read_routes(monkeypatch) -> None:
    monkeypatch.setattr(
        hypothesis_rounds,
        "list_hypothesis_rounds",
        lambda team_id: {
            "schemaVersion": 1,
            "teamId": team_id,
            "roundCount": 1,
            "rounds": [{"roundId": "hr-1"}],
            "storagePath": "x",
        },
    )
    monkeypatch.setattr(
        hypothesis_rounds,
        "get_hypothesis_round",
        lambda team_id, round_id: {
            "schemaVersion": 1,
            "teamId": team_id,
            "round": {"roundId": round_id},
            "storagePath": "x",
        },
    )
    client = _client()

    response = client.get("/api/teams/team-1/workflow-orchestration/hypothesis-rounds")
    assert response.status_code == 200, response.text
    assert response.json()["rounds"][0]["roundId"] == "hr-1"

    response = client.get("/api/teams/team-1/workflow-orchestration/hypothesis-rounds/hr-1")
    assert response.status_code == 200, response.text
    assert response.json()["round"]["roundId"] == "hr-1"


def test_chain_query_routes(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(
        hypothesis_first_chain,
        "chain_state",
        lambda team_id, question_id, *, workflow_run_id="": calls.append(
            {
                "kind": "state",
                "questionId": question_id,
                "workflowRunId": workflow_run_id,
            }
        )
        or {
            "schemaVersion": 1,
            "teamId": team_id,
            "questionId": question_id,
            "hypothesisConverged": False,
            "convergenceDetail": "converged",
        },
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "list_collection_requests",
        lambda team_id, question_id="", *, workflow_run_id="": calls.append(
            {
                "kind": "collection",
                "questionId": question_id,
                "workflowRunId": workflow_run_id,
            }
        )
        or {
            "schemaVersion": 1,
            "teamId": team_id,
            "requestCount": 1,
            "requests": [{"requestId": "cr-1", "questionId": question_id}],
            "storagePath": "x",
        },
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "list_review_round_links",
        lambda team_id, question_id="", *, workflow_run_id="": calls.append(
            {
                "kind": "links",
                "questionId": question_id,
                "workflowRunId": workflow_run_id,
            }
        )
        or {
            "schemaVersion": 1,
            "teamId": team_id,
            "linkCount": 1,
            "links": [{"meetingRoundId": "mr-1", "questionId": question_id}],
            "storagePath": "x",
        },
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "candidate_evidence_trail",
        lambda team_id, question_id, *, workflow_run_id="": calls.append(
            {
                "kind": "trail",
                "questionId": question_id,
                "workflowRunId": workflow_run_id,
            }
        )
        or {
            "schemaVersion": 1,
            "teamId": team_id,
            "questionId": question_id,
            "trails": [{"candidateId": "cand-1", "entries": []}],
            "storagePath": "x",
        },
    )
    client = _client()

    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/state",
        params={"questionId": "SCI-096", "runId": "run-096"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["questionId"] == "SCI-096"

    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/collection-requests",
        params={"questionId": "SCI-096", "runId": "run-096"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["requests"][0]["requestId"] == "cr-1"

    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/review-round-links",
        params={"questionId": "SCI-096", "runId": "run-096"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["links"][0]["meetingRoundId"] == "mr-1"

    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/questions/SCI-096/candidates/evidence-trail",
        params={"runId": "run-096"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["trails"][0]["candidateId"] == "cand-1"
    assert calls == [
        {"kind": "state", "questionId": "SCI-096", "workflowRunId": "run-096"},
        {
            "kind": "collection",
            "questionId": "SCI-096",
            "workflowRunId": "run-096",
        },
        {"kind": "links", "questionId": "SCI-096", "workflowRunId": "run-096"},
        {"kind": "trail", "questionId": "SCI-096", "workflowRunId": "run-096"},
    ]


def test_selection_context_invalid_run_authority_maps_to_422(monkeypatch) -> None:
    calls = []

    def fake_resolve(team_id, question_id, workflow_run_id):
        calls.append((team_id, question_id, workflow_run_id))

    monkeypatch.setattr(
        hf_routes.meeting_receipt_authority,
        "resolve_active_question_authority",
        fake_resolve,
    )
    client = _client()
    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/questions/SCI-002/selection-context",
        params={"runId": "run-missing"},
    )
    assert response.status_code == 422, response.text
    assert calls == [("team-1", "SCI-002", "run-missing")]
    assert "workflowRunId cannot be verified" in str(response.json()["detail"])


def test_candidate_generation_route_builds_verified_generation_scope(monkeypatch) -> None:
    run_id = "run-sci-002"
    authority = {
        "teamId": "team-1",
        "questionId": "SCI-002",
        "workflowRunId": run_id,
        "receiptId": "receipt-1",
    }
    authority_calls = []
    project_calls = []
    open_calls = []

    def fake_resolve(team_id, question_id, workflow_run_id):
        authority_calls.append((team_id, question_id, workflow_run_id))
        return authority

    def fake_project(team_id):
        project_calls.append(team_id)
        return {"projectId": "research-project-1"}

    def fake_open(team_id, question_id, **kwargs):
        open_calls.append(
            {"teamId": team_id, "questionId": question_id, "kwargs": kwargs}
        )
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "status": "created",
            "meetingRound": {"meetingRoundId": "mr-gen-1"},
            "storagePath": "x",
        }

    # SCI-002's run is not pinned to the stage-one policy, so the shared
    # launch resolver must come back with no grounded context and the plain
    # (non-formal) candidate authority.
    monkeypatch.setattr(
        research_project_hypothesis_context,
        "build_stage_one_grounded_generation_context",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        hf_routes.meeting_receipt_authority,
        "resolve_active_question_authority",
        fake_resolve,
    )
    monkeypatch.setattr(
        research_project_agent_sessions,
        "resolve_research_project_identity",
        fake_project,
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "open_candidate_generation_meeting",
        fake_open,
    )

    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/candidate-generation",
        json={"questionId": "SCI-002", "workflowRunId": run_id},
    )

    assert response.status_code == 201, response.text
    assert authority_calls == [("team-1", "SCI-002", run_id)]
    assert project_calls == ["team-1"]
    assert open_calls[0]["kwargs"]["_model_invocation_receipt_authority"] is authority
    assert open_calls[0]["kwargs"]["_candidate_authority"] == ""
    assert open_calls[0]["kwargs"]["_generation_context"] is None
    discussion_scope = open_calls[0]["kwargs"]["_discussion_scope"]
    assert discussion_scope["kind"] == "question_generation"
    assert discussion_scope["teamId"] == "team-1"
    assert discussion_scope["researchProjectId"] == "research-project-1"
    assert discussion_scope["workflowRunId"] == run_id
    assert discussion_scope["questionId"] == "SCI-002"
    assert discussion_scope["workflowNodeId"] == hypothesis_first_chain.HYPOTHESIS_DESIGN_NODE_ID


def test_chain_close_review_meeting_passes_runtime_and_payload(monkeypatch) -> None:
    calls = []
    sentinel_runtime = object()
    monkeypatch.setattr(hf_routes, "production_workflow_runtime", lambda: sentinel_runtime)

    def fake_close(team_id, meeting_round_id, payload=None, **kwargs):
        calls.append(
            {
                "teamId": team_id,
                "meetingRoundId": meeting_round_id,
                "payload": dict(payload or {}),
                "kwargs": kwargs,
            }
        )
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "status": "created",
            "closed": True,
            "meetingRound": {"meetingRoundId": meeting_round_id, "status": "closed"},
            "digest": {"digestId": "d-1"},
            "decisions": [{"decisionId": "dec-1"}],
            "collection": {"started": [], "skipped": []},
            "hypothesisRound": {"roundId": "hr-1"},
            "resume": None,
            "storagePath": "x",
        }

    monkeypatch.setattr(hypothesis_first_chain, "close_review_meeting", fake_close)
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/review-meetings/mr-1/close",
        json={
            "decisions": [
                {
                    "decision": "request_new_evidence",
                    "rationale": "需要更多证据",
                    "decidedBy": "operator",
                    "searchEnvelope": {"keywords": ["nslb", "load balance"]},
                }
            ],
            "closedBy": "operator",
        },
    )

    assert response.status_code == 200, response.text
    assert calls[0]["meetingRoundId"] == "mr-1"
    assert calls[0]["kwargs"]["runtime"] is sentinel_runtime
    assert calls[0]["payload"]["decisions"][0]["searchEnvelope"] == {
        "keywords": ["nslb", "load balance"]
    }
    data = response.json()
    assert data["closed"] is True
    assert data["hypothesisRound"]["roundId"] == "hr-1"


def test_chain_collection_handoff_passes_arguments(monkeypatch) -> None:
    calls = []
    sentinel_runtime = object()
    monkeypatch.setattr(hf_routes, "production_workflow_runtime", lambda: sentinel_runtime)

    def fake_handoff(team_id, request_id, **kwargs):
        calls.append({"teamId": team_id, "requestId": request_id, "kwargs": kwargs})
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "status": "handed_off",
            "request": {"requestId": request_id, "status": "handed_off"},
            "nextMeeting": {"meetingRoundId": "mr-2"},
            "resume": None,
        }

    monkeypatch.setattr(hypothesis_first_chain, "record_collection_handoff", fake_handoff)
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/collection-requests/cr-1/handoff",
        json={"handoffRef": "run-123"},
    )

    assert response.status_code == 200, response.text
    assert calls[0]["requestId"] == "cr-1"
    assert calls[0]["kwargs"]["handoff_ref"] == "run-123"
    assert calls[0]["kwargs"]["runtime"] is sentinel_runtime
    assert response.json()["request"]["status"] == "handed_off"


def test_summary_draft_route_passes_actor_and_force(monkeypatch) -> None:
    calls = []

    def fake_prepare(team_id, meeting_round_id, *, actor="", force=False):
        calls.append(
            {
                "teamId": team_id,
                "meetingRoundId": meeting_round_id,
                "actor": actor,
                "force": force,
            }
        )
        return {
            "schemaVersion": 2,
            "teamId": team_id,
            "status": "awaiting_approval",
            "meetingRound": {"meetingRoundId": meeting_round_id},
            "digestDraft": {"summary": "draft", "contentHash": "h1"},
            "storagePath": "x",
        }

    monkeypatch.setattr(meeting_runtime, "prepare_meeting_summary_draft", fake_prepare)
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/meeting-rounds/mr-1/summary-draft",
        json={"actor": "operator", "force": False},
    )
    assert response.status_code == 200, response.text
    assert calls[0] == {
        "teamId": "team-1",
        "meetingRoundId": "mr-1",
        "actor": "operator",
        "force": False,
    }
    assert response.json()["digestDraft"]["contentHash"] == "h1"


def test_approve_digest_route_passes_hash_and_maps_stale(monkeypatch) -> None:
    calls = []
    sentinel_runtime = object()
    monkeypatch.setattr(hf_routes, "production_workflow_runtime", lambda: sentinel_runtime)

    def fake_approve(team_id, meeting_round_id, *, closed_by, expected_digest_content_hash, runtime=None):
        calls.append(
            {
                "teamId": team_id,
                "meetingRoundId": meeting_round_id,
                "closedBy": closed_by,
                "expectedDigestContentHash": expected_digest_content_hash,
                "runtime": runtime,
            }
        )
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "status": "created",
            "closed": True,
            "meetingRound": {"meetingRoundId": meeting_round_id, "status": "closed"},
            "digest": {"digestId": "d-1"},
            "decisions": [{"decisionId": "dec-1"}],
            "collection": {"requests": []},
            "storagePath": "x",
        }

    monkeypatch.setattr(hypothesis_first_chain, "approve_meeting_digest", fake_approve)
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/meetings/mr-1/approve-digest",
        json={"closedBy": "operator", "expectedDigestContentHash": "hash-1"},
    )
    assert response.status_code == 200, response.text
    assert calls[0]["expectedDigestContentHash"] == "hash-1"
    assert calls[0]["runtime"] is sentinel_runtime

    def stale_approve(*_args, **_kwargs):
        raise hypothesis_first_chain.StaleDigestError(
            "digest content hash is stale",
            expected="hash-1",
            actual="hash-2",
        )

    monkeypatch.setattr(hypothesis_first_chain, "approve_meeting_digest", stale_approve)
    stale = client.post(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/meetings/mr-1/approve-digest",
        json={"closedBy": "operator", "expectedDigestContentHash": "hash-2"},
    )
    assert stale.status_code == 409


def test_routes_map_team_not_found_to_404(monkeypatch) -> None:
    def fake_list(team_id):
        raise TeamNotFoundError("team missing")

    monkeypatch.setattr(meeting_rounds, "list_meeting_rounds", fake_list)
    client = _client()
    response = client.get("/api/teams/team-x/workflow-orchestration/meeting-rounds")
    assert response.status_code == 404


def test_next_review_round_route_ignores_retired_budget_and_maps_domain_error(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_open(team_id, *, previous_meeting_round_id, budget=None, **_kwargs):
        calls.append(
            {
                "teamId": team_id,
                "previousMeetingRoundId": previous_meeting_round_id,
                "budget": budget,
            }
        )
        return {
            "schemaVersion": 2,
            "teamId": team_id,
            "status": "opened",
            "selectionId": "hsel-1",
            "previousMeetingRoundId": previous_meeting_round_id,
            "roundIndex": 2,
            "budget": 5,
            "meetingRound": {"meetingRoundId": "mr-next"},
        }

    monkeypatch.setattr(hypothesis_first_chain, "open_next_review_meeting", fake_open)
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/review-meetings/mr-1/next-round",
        json={"budget": 4},
    )
    assert response.status_code == 200, response.text
    assert calls == [
        {"teamId": "team-1", "previousMeetingRoundId": "mr-1", "budget": None}
    ]
    body = response.json()
    assert body["status"] == "opened"
    assert body["roundIndex"] == 2

    no_body = client.post(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/review-meetings/mr-1/next-round",
    )
    assert no_body.status_code == 200
    assert calls[-1]["budget"] is None

    def failing_open(*_args, **_kwargs):
        raise hypothesis_first_chain.HypothesisFirstChainError(
            "previous meeting round is still open"
        )

    monkeypatch.setattr(hypothesis_first_chain, "open_next_review_meeting", failing_open)
    blocked = client.post(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/review-meetings/mr-1/next-round",
        json={"budget": 2},
    )
    assert blocked.status_code == 422


def test_collection_recovery_route_calls_idempotent_service(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_recover(team_id: str, request_id: str) -> dict:
        calls.append((team_id, request_id))
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "status": "recovered",
            "request": {
                "requestId": request_id,
                "collectionRunId": "child-1",
                "status": "pending",
            },
            "reused": False,
        }

    monkeypatch.setattr(hypothesis_first_chain, "recover_collection_request", fake_recover)
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/collection-requests/req-1/recover",
    )
    assert response.status_code == 200, response.text
    assert calls == [("team-1", "req-1")]
    assert response.json()["request"]["collectionRunId"] == "child-1"


# ---------------------------------------------------------------------------
# state-v2 route serialization contract: the batch-A stage-one offers exist
# only as dicts in service-layer tests; the FastAPI response model must
# serialize them (regression for the live 500: payload.runId extra_forbidden).
# ---------------------------------------------------------------------------


def _stage_one_route_snapshot(**overrides):
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_state_v2,
    )

    drafts = [
        {
            "recordKind": "hypothesis_exploratory_draft",
            "draftId": f"draft-{index}",
            "candidateId": f"draft-{index}",
            "questionId": "SCI-091",
            "statement": f"draft statement {index}",
            "meetingRoundId": "hf-candgen-run-r0",
            "candidateAuthority": "exploratory_draft",
            "createdAt": f"2026-08-25T00:0{index}:00Z",
        }
        for index in range(2)
    ]
    payload = {
        "team_id": "team-1",
        "question_id": "SCI-091",
        "reset_boundary": None,
        "chain_records": drafts,
        "selection_records": [],
        "meeting_records": [],
        "digest_records": [],
        "decision_records": [],
        "hypothesis_round_records": [],
    }
    payload.update(overrides)
    return hypothesis_first_state_v2.project_state_from_records(**payload)


def test_state_v2_route_serializes_grounded_r1_offer_with_run_id(
    monkeypatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_state_v2,
    )

    snapshot = _stage_one_route_snapshot(
        formal_runs=[
            {
                "runId": "run-882610596ddb",
                "status": "queued",
                "questionId": "SCI-091",
                "createdAt": "2026-08-25T00:00:00Z",
            }
        ],
    )
    assert any(
        action.get("actionId") == "open-stage-one-generation"
        for action in snapshot["allowedActions"]
    )
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    client = _client()

    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/state-v2",
        params={"questionId": "SCI-091"},
    )

    assert response.status_code == 200, response.text
    offer = next(
        action
        for action in response.json()["allowedActions"]
        if action["actionId"] == "open-stage-one-generation"
    )
    assert offer["command"] == "open_generation"
    assert offer["payload"]["runId"] == "run-882610596ddb"
    assert offer["payload"]["questionId"] == "SCI-091"


def test_state_v2_route_serializes_create_stage_one_run_offer(monkeypatch) -> None:
    """A fresh policy-covered question offers run creation through the wire."""

    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_state_v2,
    )

    snapshot = _stage_one_route_snapshot()
    assert any(
        action.get("actionId") == "create-stage-one-run"
        for action in snapshot["allowedActions"]
    )
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    client = _client()

    response = client.get(
        "/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/state-v2",
        params={"questionId": "SCI-091"},
    )

    assert response.status_code == 200, response.text
    offer = next(
        action
        for action in response.json()["allowedActions"]
        if action["actionId"] == "create-stage-one-run"
    )
    assert offer["command"] == "create_stage_one_run"
    assert offer["payload"] == {"questionId": "SCI-091"}


def test_digest_draft_route_maps_lock_timeout_to_structured_503() -> None:
    """A bounded meeting-rounds lock wait that expires is a retryable 503.

    2026-09 ghost-lock incident: digest submit/read threads used to block on
    the module lock forever while the user's retry POST queued behind them;
    the route must convert the structured timeout into a 503 with code and
    wait evidence instead of hanging or reading as a 500 fault.
    """

    exc = meeting_rounds.MeetingRoundsLockTimeoutError(
        caller="submit_meeting_digest_draft", timeout_seconds=60.0
    )
    with pytest.raises(HTTPException) as raised:
        hf_routes._map_domain_error(
            "meeting_round.submit_digest_draft",
            "team-1",
            exc,
        )
    assert raised.value.status_code == 503
    detail = raised.value.detail
    assert detail["code"] == "meeting_rounds_lock_timeout"
    assert detail["caller"] == "submit_meeting_digest_draft"
    assert detail["waitedSeconds"] == 60.0
