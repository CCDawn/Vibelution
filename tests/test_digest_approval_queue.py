"""Batch digest approval queue: service semantics + route contract."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes.team_workflows import hypothesis_first as hf_routes
from core.web.services.team_workflow import (
    digest_approval_queue,
    meeting_rounds,
)
from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

_TEAM = "team-1"


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _awaiting_meeting(
    meeting_round_id: str,
    *,
    question: str = "SCI-091",
    started_at: str = "2026-09-01T10:00:00Z",
    content_hash: str = "hash-a",
    ttl_mute: dict | None = None,
) -> dict:
    meeting = {
        "meetingRoundId": meeting_round_id,
        "meetingType": "hypothesis_candidate_generation",
        "question": question,
        "status": "awaiting_approval",
        "startedAt": started_at,
        "digestDraft": {
            "contentHash": content_hash,
            "summary": "会议就候选假说达成共识",
            "proposedCandidates": [{"candidateId": "c1"}, {"candidateId": "c2"}],
            "risks": [{"kind": "budget"}],
        },
    }
    if ttl_mute is not None:
        meeting["_ttl_mute"] = ttl_mute
    return meeting


@pytest.fixture()
def isolated_team(monkeypatch, tmp_path):
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_runtime

    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    team_id = team_service.create_team(name="digest approval queue team")["teamId"]
    monkeypatch.setattr(
        meeting_runtime,
        "meeting_digest_ttl_mute_state",
        lambda meeting: meeting.get("_ttl_mute") or None,
    )
    return team_id


def test_list_pending_maps_fields_and_sorts_oldest_first(
    monkeypatch, isolated_team
) -> None:
    meetings = [
        _awaiting_meeting("meeting-new", started_at="2026-09-01T12:00:00Z", content_hash="h2"),
        _awaiting_meeting(
            "meeting-old",
            started_at="2026-09-01T10:00:00Z",
            content_hash="h1",
            ttl_mute={"message": "digest TTL 已超时"},
        ),
        {"meetingRoundId": "meeting-no-draft", "status": "awaiting_approval",
         "question": "SCI-092", "startedAt": "2026-09-01T11:00:00Z"},
    ]
    monkeypatch.setattr(
        meeting_rounds,
        "list_meeting_rounds",
        lambda team_id, status=None, read_only=False: {"meetings": meetings},
    )

    report = digest_approval_queue.list_pending_digest_approvals(isolated_team)
    assert report["count"] == 2
    ids = [item["meetingRoundId"] for item in report["items"]]
    assert ids == ["meeting-old", "meeting-new"]
    oldest = report["items"][0]
    assert oldest["questionId"] == "SCI-091"
    assert oldest["digestContentHash"] == "h1"
    assert oldest["proposedCandidateCount"] == 2
    assert oldest["riskCount"] == 1
    assert oldest["ttlOverdue"] is True
    assert oldest["ttlMessage"] == "digest TTL 已超时"
    assert report["items"][1]["ttlOverdue"] is False


def test_batch_approve_isolates_per_item_failures(monkeypatch, isolated_team) -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_approve(team_id, meeting_round_id, *, closed_by, expected_digest_content_hash, runtime=None):
        calls.append((team_id, meeting_round_id, expected_digest_content_hash))
        if meeting_round_id == "meeting-stale":
            raise hypothesis_first_chain.StaleDigestError(
                "digest content hash is stale",
                expected="old",
                actual="new",
            )
        return {"status": "closed"}

    monkeypatch.setattr(hypothesis_first_chain, "approve_meeting_digest", fake_approve)

    report = digest_approval_queue.batch_approve_digests(
        isolated_team,
        [
            {"meetingRoundId": "meeting-ok", "expectedDigestContentHash": "h1"},
            {"meetingRoundId": "meeting-stale", "expectedDigestContentHash": "h2"},
            {"meetingRoundId": "", "expectedDigestContentHash": "h3"},
        ],
        closed_by="operator-1",
    )
    assert report["approvedCount"] == 1
    assert report["failedCount"] == 2
    by_id = {row["meetingRoundId"]: row for row in report["results"]}
    assert by_id["meeting-ok"]["status"] == "approved"
    assert by_id["meeting-stale"]["status"] == "failed"
    assert by_id["meeting-stale"]["errorType"] == "StaleDigestError"
    assert by_id[""]["errorType"] == "invalid_request"
    # The stale row never stops the batch: all three rows reached the loop.
    assert len(calls) == 2


def test_batch_approve_requires_closed_by(monkeypatch, isolated_team) -> None:
    with pytest.raises(hypothesis_first_chain.HypothesisFirstChainError):
        digest_approval_queue.batch_approve_digests(
            isolated_team,
            [{"meetingRoundId": "m", "expectedDigestContentHash": "h"}],
            closed_by="  ",
        )


def test_route_pending_list_returns_service_projection(monkeypatch, isolated_team) -> None:
    monkeypatch.setattr(
        digest_approval_queue,
        "list_pending_digest_approvals",
        lambda team_id: {
            "items": [
                {
                    "meetingRoundId": "m1",
                    "questionId": "SCI-091",
                    "digestContentHash": "h1",
                    "ageSeconds": 120,
                }
            ],
            "count": 1,
            "fetchedAtMs": 1,
        },
    )
    response = _client().get(
        f"/api/teams/{isolated_team}/workflow-orchestration"
        "/hypothesis-first/chain/digest-approvals/pending"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["digestContentHash"] == "h1"


def test_route_batch_approve_passes_items_and_runtime(monkeypatch, isolated_team) -> None:
    captured: dict = {}

    def fake_batch(team_id, items, *, closed_by, runtime=None):
        captured["team_id"] = team_id
        captured["items"] = list(items)
        captured["closed_by"] = closed_by
        captured["runtime"] = runtime
        return {"results": [], "approvedCount": 0, "failedCount": 0, "closedBy": closed_by}

    monkeypatch.setattr(digest_approval_queue, "batch_approve_digests", fake_batch)
    response = _client().post(
        f"/api/teams/{isolated_team}/workflow-orchestration"
        "/hypothesis-first/chain/digest-approvals/batch-approve",
        json={
            "closedBy": "operator-1",
            "items": [
                {"meetingRoundId": "m1", "expectedDigestContentHash": "h1"},
                {"meetingRoundId": "m2", "expectedDigestContentHash": "h2"},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["closedBy"] == "operator-1"
    assert captured["team_id"] == isolated_team
    assert captured["closed_by"] == "operator-1"
    assert captured["items"] == [
        {"meetingRoundId": "m1", "expectedDigestContentHash": "h1"},
        {"meetingRoundId": "m2", "expectedDigestContentHash": "h2"},
    ]
    # The production runtime resolves to None in tests; the route merely
    # forwards whatever production_workflow_runtime() returns.
    assert "runtime" in captured


def test_route_batch_approve_rejects_empty_items(isolated_team) -> None:
    response = _client().post(
        f"/api/teams/{isolated_team}/workflow-orchestration"
        "/hypothesis-first/chain/digest-approvals/batch-approve",
        json={"closedBy": "operator-1", "items": []},
    )
    assert response.status_code == 422
