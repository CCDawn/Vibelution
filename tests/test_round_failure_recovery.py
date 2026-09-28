"""Manual round-failure recovery: route contract + worker semantics.

HTTP 契约：列表默认只返回 open 失败、``unresolvedOnly`` 透传；重试端点缺
``confirmed=true`` 拒绝（428），未知/已解决 404，纯 fan-in 等待 409，成功
接受原样返回。服务语义：确认后异步执行与自动推进同一条
``regenerate_hypothesis_round`` 路径（``trigger="manual_recovery"``），
superseded 等待回落手动重派发；inflight 去重保证同一 trace 只跑一次。
"""

from __future__ import annotations

import threading
import time
from contextlib import nullcontext
from typing import Any

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes.team_workflows import hypothesis_first as hf_routes
from core.web.services import team_service
from core.web.services.team_workflow import (
    hypothesis_rounds as hypothesis_rounds_service,
)
from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

_TEAM = "team-1"
_LIST_ROUTE = (
    f"/api/teams/{_TEAM}/workflow-orchestration"
    "/hypothesis-first/chain/round-failures"
)


def _client() -> TestClient:
    return TestClient(
        create_app(),
        headers={CONTROL_TOKEN_HEADER: get_control_token()},
    )


def _team(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(hypothesis_rounds_service, "PROJECT_ROOT", tmp_path)
    return team_service.create_team(name="round failure recovery team")["teamId"]


def _seed_failure(
    team_id: str,
    *,
    status: str = "failed",
    failure_code: str = "hypothesis_round_precondition_failed",
) -> dict[str, Any]:
    recorded = hypothesis_rounds_service.record_hypothesis_round_failure(
        team_id,
        {
            "status": status,
            "failureCode": failure_code,
            "reason": "candidate requires a non-empty claim",
            "meetingRoundIds": ["meeting-a", "meeting-b"],
            "selectionId": "selection-1",
            "roundIndex": 1,
            "questionId": "SCI-091",
            "retryHint": "re-generate the round",
        },
    )
    return recorded["failure"]


def _wait_not_inflight(failure_id: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while failure_id in hypothesis_first_chain._MANUAL_RECOVERY_INFLIGHT:
        if time.time() >= deadline:
            break
        time.sleep(0.01)


def teardown_function() -> None:
    hypothesis_first_chain._MANUAL_RECOVERY_INFLIGHT.clear()


# ---------------------------------------------------------------------------
# route contract
# ---------------------------------------------------------------------------


def test_round_failure_list_forwards_unresolved_only(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_list(team_id: str, *, unresolved_only: bool = False) -> dict[str, Any]:
        captured["team_id"] = team_id
        captured["unresolved_only"] = unresolved_only
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "failureCount": 1,
            "openFailureCount": 1,
            "failures": [{"failureId": "hrfail-1", "status": "failed"}],
        }

    monkeypatch.setattr(
        hf_routes.hypothesis_rounds, "list_hypothesis_round_failures", fake_list
    )
    client = _client()

    response = client.get(_LIST_ROUTE)
    assert response.status_code == 200
    assert captured == {"team_id": _TEAM, "unresolved_only": True}
    assert response.json()["failures"][0]["failureId"] == "hrfail-1"

    response = client.get(_LIST_ROUTE, params={"unresolvedOnly": "false"})
    assert response.status_code == 200
    assert captured["unresolved_only"] is False


def test_round_failure_retry_requires_confirmation(monkeypatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        hf_routes.hypothesis_first_chain,
        "request_round_failure_recovery",
        lambda team_id, failure_id: called.append(failure_id) or {"status": "accepted"},
    )
    monkeypatch.setattr(
        hf_routes, "server_operator_scope_from_http", lambda request: nullcontext()
    )
    response = _client().post(
        f"{_LIST_ROUTE}/hrfail-1/retry", json={"confirmed": False}
    )
    assert response.status_code == 428
    assert response.json()["detail"]["code"] == "confirmation_required"
    assert called == []


def test_round_failure_retry_maps_service_statuses(monkeypatch) -> None:
    monkeypatch.setattr(
        hf_routes, "server_operator_scope_from_http", lambda request: nullcontext()
    )
    client = _client()
    retry_route = f"{_LIST_ROUTE}/hrfail-1/retry"

    monkeypatch.setattr(
        hf_routes.hypothesis_first_chain,
        "request_round_failure_recovery",
        lambda team_id, failure_id: {"status": "not_found", "failureId": failure_id},
    )
    response = client.post(retry_route, json={"confirmed": True})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "round_failure_not_found"

    monkeypatch.setattr(
        hf_routes.hypothesis_first_chain,
        "request_round_failure_recovery",
        lambda team_id, failure_id: {
            "status": "not_retryable",
            "failureId": failure_id,
            "reasonCode": "fan_in_waiting",
        },
    )
    response = client.post(retry_route, json={"confirmed": True})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "fan_in_waiting"

    accepted = {
        "status": "accepted",
        "failureId": "hrfail-1",
        "questionId": "SCI-091",
        "meetingRoundId": "meeting-a",
    }
    monkeypatch.setattr(
        hf_routes.hypothesis_first_chain,
        "request_round_failure_recovery",
        lambda team_id, failure_id: dict(accepted),
    )
    response = client.post(retry_route, json={"confirmed": True})
    assert response.status_code == 200
    assert response.json() == accepted


# ---------------------------------------------------------------------------
# service semantics
# ---------------------------------------------------------------------------


def test_request_recovery_unknown_and_waiting_traces(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)

    missing = hypothesis_first_chain.request_round_failure_recovery(
        team_id, "hrfail-missing"
    )
    assert missing["status"] == "not_found"

    blocked = _seed_failure(team_id, status="blocked")
    waiting = hypothesis_first_chain.request_round_failure_recovery(
        team_id, blocked["failureId"]
    )
    assert waiting["status"] == "not_retryable"
    assert waiting["reasonCode"] == "fan_in_waiting"
    assert blocked["failureId"] not in hypothesis_first_chain._MANUAL_RECOVERY_INFLIGHT


def test_request_recovery_runs_regeneration_on_worker(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    record = _seed_failure(team_id)
    calls: dict[str, Any] = {}

    def fake_regen(team: str, meeting_round_id: str, *, trigger: str = "command"):
        calls["team"] = team
        calls["meeting_round_id"] = meeting_round_id
        calls["trigger"] = trigger
        return {"status": "created", "round": {"roundId": "hround-new"}}

    monkeypatch.setattr(hypothesis_first_chain, "regenerate_hypothesis_round", fake_regen)

    accepted = hypothesis_first_chain.request_round_failure_recovery(
        team_id, record["failureId"]
    )
    assert accepted["status"] == "accepted"
    assert accepted["meetingRoundId"] == "meeting-a"

    _wait_not_inflight(record["failureId"])
    assert calls == {
        "team": team_id,
        "meeting_round_id": "meeting-a",
        "trigger": "manual_recovery",
    }


def test_request_recovery_deduplicates_in_flight(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    record = _seed_failure(team_id)
    entered = threading.Event()
    release = threading.Event()

    def blocking_regen(team: str, meeting_round_id: str, *, trigger: str = "command"):
        entered.set()
        release.wait(5)
        return {"status": "created", "round": {"roundId": "hround-new"}}

    monkeypatch.setattr(
        hypothesis_first_chain, "regenerate_hypothesis_round", blocking_regen
    )

    first = hypothesis_first_chain.request_round_failure_recovery(
        team_id, record["failureId"]
    )
    assert first["status"] == "accepted"
    assert entered.wait(5)
    second = hypothesis_first_chain.request_round_failure_recovery(
        team_id, record["failureId"]
    )
    assert second["status"] == "in_flight"
    release.set()
    _wait_not_inflight(record["failureId"])
    assert record["failureId"] not in hypothesis_first_chain._MANUAL_RECOVERY_INFLIGHT


def test_manual_recovery_redispatches_superseded_candidates(
    tmp_path, monkeypatch
) -> None:
    team_id = _team(tmp_path, monkeypatch)
    record = _seed_failure(
        team_id, failure_code="fan_in_waiting_for_sibling_reviews"
    )
    calls: dict[str, Any] = {}

    monkeypatch.setattr(
        hypothesis_first_chain,
        "regenerate_hypothesis_round",
        lambda team, meeting_round_id, *, trigger="command": {
            "status": "waiting_for_sibling_reviews",
            "selectionId": "selection-1",
            "supersededCandidateIds": ["cand-a"],
        },
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "retry_review_dispatch",
        lambda team, selection_id, candidate_ids: calls.update(
            {
                "team": team,
                "selection_id": selection_id,
                "candidate_ids": list(candidate_ids),
            }
        ),
    )

    token = object()
    hypothesis_first_chain._MANUAL_RECOVERY_INFLIGHT[record["failureId"]] = token
    hypothesis_first_chain._run_round_failure_recovery(team_id, record, token)
    assert calls == {
        "team": team_id,
        "selection_id": "selection-1",
        "candidate_ids": ["cand-a"],
    }
    assert record["failureId"] not in hypothesis_first_chain._MANUAL_RECOVERY_INFLIGHT


# ---------------------------------------------------------------------------
# legacy ledger compaction
# ---------------------------------------------------------------------------


def _legacy_wait_row(
    *,
    failure_id: str,
    created_at: str,
    selection_id: str = "selection-1",
    meeting_ids: tuple[str, ...] = ("meeting-a", "meeting-b"),
) -> dict[str, Any]:
    """One pre-idempotence wait observation: one row per sweep tick."""

    return {
        "schemaVersion": hypothesis_rounds_service.FAILURE_SCHEMA_VERSION,
        "recordKind": hypothesis_rounds_service.FAILURE_RECORD_KIND,
        "failureId": failure_id,
        "status": "blocked",
        "failureCode": "fan_in_waiting_for_sibling_reviews",
        "reason": "review fan-in is not ready",
        "errorType": "",
        "roundId": "",
        "meetingRoundIds": list(meeting_ids),
        "selectionId": selection_id,
        "roundIndex": 2,
        "questionId": "SCI-117",
        "workflowRunId": "",
        "scopeHash": "",
        "retryHint": "wait",
        "trigger": "auto_advance_sweep",
        "context": {},
        "createdAt": created_at,
        "resolvedAt": "",
        "resolvedByRoundId": "",
    }


def test_compact_collapses_duplicate_open_wait_rows(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    path = hypothesis_rounds_service._failure_storage_path(team_id)
    rows = [
        # Three ticks of the same wait episode (identical scope key) ...
        _legacy_wait_row(failure_id="hrfail-legacy-1", created_at="2026-09-10T01:00:00Z"),
        _legacy_wait_row(failure_id="hrfail-legacy-2", created_at="2026-09-10T01:01:00Z"),
        _legacy_wait_row(failure_id="hrfail-legacy-3", created_at="2026-09-10T01:02:00Z"),
        # ... a different wait episode (different meeting set) stays open ...
        _legacy_wait_row(
            failure_id="hrfail-legacy-4",
            created_at="2026-09-10T01:03:00Z",
            meeting_ids=("meeting-c",),
        ),
        # ... and one real failed attempt trace.
        {
            **_legacy_wait_row(failure_id="hrfail-real-1", created_at="2026-09-10T00:59:00Z"),
            "status": "failed",
            "failureCode": "hypothesis_round_generation_error",
        },
    ]
    for row in rows:
        hypothesis_rounds_service._append_jsonl(path, row)

    result = hypothesis_rounds_service.compact_hypothesis_round_failures(
        team_id, min_size_bytes=0
    )

    assert result["compacted"] is True
    assert result["droppedDuplicateWaitRows"] == 2
    assert result["recordsAfter"] == 3
    kept = hypothesis_rounds_service._read_jsonl(path)
    kept_ids = {row["failureId"] for row in kept}
    # Newest duplicate wins; distinct episode and the failed trace survive.
    assert kept_ids == {"hrfail-legacy-3", "hrfail-legacy-4", "hrfail-real-1"}
    newest = next(row for row in kept if row["failureId"] == "hrfail-legacy-3")
    assert newest["resolvedAt"] == ""


def test_compact_collapses_superseded_resolution_copies(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    path = hypothesis_rounds_service._failure_storage_path(team_id)
    original = _legacy_wait_row(failure_id="hrfail-fix-1", created_at="2026-09-10T01:00:00Z")
    resolved_copy = {**original, "status": "resolved", "resolvedAt": "2026-09-10T02:00:00Z"}
    for row in (original, resolved_copy):
        hypothesis_rounds_service._append_jsonl(path, row)

    result = hypothesis_rounds_service.compact_hypothesis_round_failures(
        team_id, min_size_bytes=0
    )
    assert result["compacted"] is True
    assert result["collapsedSupersededCopies"] == 1
    kept = hypothesis_rounds_service._read_jsonl(path)
    assert len(kept) == 1
    assert kept[0]["failureId"] == "hrfail-fix-1"
    assert kept[0]["status"] == "resolved"
    assert kept[0]["resolvedAt"] == "2026-09-10T02:00:00Z"


def test_compact_is_idempotent_and_threshold_gated(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    path = hypothesis_rounds_service._failure_storage_path(team_id)
    for index in range(3):
        hypothesis_rounds_service._append_jsonl(
            path,
            _legacy_wait_row(
                failure_id=f"hrfail-idem-{index}",
                created_at=f"2026-09-10T01:0{index}:00Z",
            ),
        )

    # Default threshold: the tiny fixture stays untouched.
    assert hypothesis_rounds_service.compact_hypothesis_round_failures(team_id) == {
        "compacted": False,
        "reason": "below_threshold"
    }
    # After one real pass the ledger is duplicate-free: a second pass no-ops.
    first = hypothesis_rounds_service.compact_hypothesis_round_failures(
        team_id, min_size_bytes=0
    )
    assert first["compacted"] is True
    second = hypothesis_rounds_service.compact_hypothesis_round_failures(
        team_id, min_size_bytes=0
    )
    assert second == {"compacted": False, "reason": "no_duplicates", "records": 1}
