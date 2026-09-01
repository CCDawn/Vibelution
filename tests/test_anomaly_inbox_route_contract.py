"""Anomaly-inbox route contract regressions (R4.3 panel base).

HTTP 路由契约：URL 注册、questionId 归一化、state-v2 快照原样交给
``build_anomaly_inbox``、响应携带合同投影原样透传，以及 scope/source
错误映射（422/404）。投影语义由 ``tests/test_research_anomaly_inbox.py``
的合同与服务侧测试覆盖；这里只证明 route 保持薄层。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes.team_workflows import hypothesis_first as hf_routes
from core.web.services.team_workflow.research_runtime import (
    anomaly_inbox_service,
    hypothesis_first_state_v2,
)

_TEAM = "team-1"
_ROUTE = (
    f"/api/teams/{_TEAM}/workflow-orchestration"
    "/hypothesis-first/chain/anomaly-inbox"
)


def _client() -> TestClient:
    return TestClient(
        create_app(),
        headers={CONTROL_TOKEN_HEADER: get_control_token()},
    )


def _inbox_payload() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "ruleId": "anomaly_inbox_rule.v1",
        "generatedAt": "2026-08-28T01:00:00Z",
        "items": [
            {
                "kind": "blocked_run",
                "scope": {
                    "teamId": _TEAM,
                    "questionId": "SCI-001",
                    "runId": "run-9",
                    "nodeId": "",
                    "meetingRoundId": "",
                },
                "severity": "critical",
                "firstSeenAt": "2026-08-28T00:30:00Z",
                "lastSeenAt": "2026-08-28T00:30:00Z",
                "summary": "collection_run_needs_continue",
                "recommendedAction": "reconcile_run",
                "evidence": ["problem:collection_run_needs_continue"],
            }
        ],
    }


def test_anomaly_inbox_route_passes_snapshot_through_and_returns_projection(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_project(team_id: str, question_id: str, **kwargs: Any) -> dict[str, Any]:
        captured["team_id"] = team_id
        captured["question_id"] = question_id
        captured["kwargs"] = kwargs
        return {
            "schemaVersion": 2,
            "teamId": team_id,
            "questionId": question_id,
            "computedAt": "2026-08-28T01:00:00Z",
            "awaitingHumanCount": 0,
            "problems": [],
        }

    seen_inputs: dict[str, Any] = {}

    def fake_build(state: Any = None, **kwargs: Any) -> Any:
        seen_inputs["state"] = state
        seen_inputs["kwargs"] = kwargs

        class _FakeInbox:
            def to_dict(self) -> dict[str, Any]:
                return _inbox_payload()

        return _FakeInbox()

    # Route-owned read-only collectors stay hermetic here: the pure
    # build/attach contract is covered in test_research_anomaly_inbox.py.
    monkeypatch.setattr(
        hf_routes, "_collect_digest_ttl_overdues", lambda team_id, question_id: []
    )
    monkeypatch.setattr(
        hf_routes,
        "_collect_budget_precheck_blocks",
        lambda team_id, snapshot: [],
    )
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        fake_project,
    )
    monkeypatch.setattr(anomaly_inbox_service, "build_anomaly_inbox", fake_build)

    response = _client().get(_ROUTE, params={"questionId": "sci-001"})
    assert response.status_code == 200
    body = response.json()
    assert captured == {
        "team_id": _TEAM,
        "question_id": "SCI-001",
        "kwargs": {},
    }
    # The canonical V2 snapshot is forwarded verbatim; the companion inputs
    # (digest TTL / gate waits / budget precheck blocks) are explicit kwargs.
    assert seen_inputs["state"]["questionId"] == "SCI-001"
    assert seen_inputs["kwargs"]["digest_ttl_overdues"] == []
    assert seen_inputs["kwargs"]["gate_waits"] == []
    assert seen_inputs["kwargs"]["budget_precheck_blocks"] == []
    assert (
        isinstance(seen_inputs["kwargs"]["gate_wait_threshold_ms"], int)
        and seen_inputs["kwargs"]["gate_wait_threshold_ms"] > 0
    )
    assert body["schemaVersion"] == 1
    assert body["teamId"] == _TEAM
    assert body["questionId"] == "SCI-001"
    assert body["inbox"] == _inbox_payload()


def test_anomaly_inbox_route_without_question_id_returns_empty_inbox(
    monkeypatch,
) -> None:
    def fail_project(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("state-v2 projection must not run without a question")

    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        fail_project,
    )
    response = _client().get(_ROUTE)
    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == 1
    assert body["questionId"] == ""
    assert body["inbox"]["schemaVersion"] == 1
    assert body["inbox"]["ruleId"] == "anomaly_inbox_rule.v1"
    assert body["inbox"]["items"] == []


def test_anomaly_inbox_route_end_to_end_projection_from_problems(
    monkeypatch,
) -> None:
    """No service stub: the real build_anomaly_inbox runs over the snapshot."""

    snapshot = {
        "schemaVersion": 2,
        "teamId": _TEAM,
        "questionId": "SCI-001",
        "computedAt": "2026-08-28T01:00:00Z",
        "awaitingHumanCount": 2,
        "problems": [
            {
                "code": "generation_heartbeat_stale",
                "category": "stale",
                "severity": "error",
                "message": "生成心跳超时",
                "recoverable": True,
                "sourceKind": "formal_run",
                "sourceId": "run-9",
                "detectedAt": "2026-08-28T00:30:00Z",
                "lastHeartbeatAt": "2026-08-28T00:45:00Z",
            }
        ],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda team_id, question_id, **kwargs: snapshot,
    )
    response = _client().get(_ROUTE, params={"questionId": "SCI-001"})
    assert response.status_code == 200
    inbox = response.json()["inbox"]
    kinds = [item["kind"] for item in inbox["items"]]
    # Same severity ranks by lastSeenAt desc: the gate item (01:00) precedes
    # the heartbeat item (00:45).
    assert kinds == ["needs_human_gate", "heartbeat_stale"]
    assert inbox["items"][1]["recommendedAction"] == "retry_node"
    assert inbox["items"][1]["scope"]["runId"] == ""
    assert inbox["items"][0]["summary"] == "2 处等待人工处理"


def test_anomaly_inbox_route_maps_scope_errors(monkeypatch) -> None:
    from core.web.services.team_workflow.research_runtime.hypothesis_first_state_v2 import (
        HypothesisFirstStateScopeError,
    )

    def raise_scope(team_id: str, question_id: str, **kwargs: Any) -> None:
        raise HypothesisFirstStateScopeError(
            "question_id_invalid",
            "questionId 必须使用 SCI-001 形式",
            status_code=422,
        )

    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        raise_scope,
    )
    response = _client().get(_ROUTE, params={"questionId": "BAD"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "question_id_invalid"

    def raise_unknown(team_id: str, question_id: str, **kwargs: Any) -> None:
        raise HypothesisFirstStateScopeError(
            "catalog_question_unknown",
            "题号不在官方挑战杯目录中",
            status_code=404,
        )

    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        raise_unknown,
    )
    response = _client().get(_ROUTE, params={"questionId": "SCI-999"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "catalog_question_unknown"


def test_anomaly_inbox_route_is_registered_on_the_router() -> None:
    paths = {
        route.path
        for route in hf_routes.router.routes
        if getattr(route, "methods", None) and "GET" in route.methods
    }
    assert (
        "/teams/{team_id}/workflow-orchestration"
        "/hypothesis-first/chain/anomaly-inbox"
    ) in paths


# -- one-click extend CTA execution (误触防护 closes server-side) -------------


_ACTION_ROUTE = (
    f"/api/teams/{_TEAM}/workflow-orchestration"
    "/hypothesis-first/chain/anomaly-inbox/actions/extend-budget"
)


def _extend_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "questionId": "SCI-001",
        "runId": "run-7",
        "nodeId": "hf_hypothesis",
        "stageId": "hypothesis",
        "stageLimitTokens": 300_000,
        "suggestedExtensionTokens": 260_000,
        "confirmed": True,
    }
    payload.update(overrides)
    return payload


def test_extend_budget_action_refuses_missing_confirmation(monkeypatch) -> None:
    submitted: list[Any] = []

    def fail_submit(**kwargs: Any) -> dict[str, Any]:
        submitted.append(kwargs)
        return {}

    monkeypatch.setattr(hf_routes, "_submit_workflow_command", fail_submit)
    response = _client().post(_ACTION_ROUTE, json=_extend_payload(confirmed=False))
    assert response.status_code == 428
    assert (
        response.json()["detail"]["code"] == "inbox_action_confirmation_required"
    )
    assert submitted == []


def test_extend_budget_action_executes_confirmed_contract(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_submit(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"status": "accepted", "commandId": "cmd-1"}

    monkeypatch.setattr(hf_routes, "_submit_workflow_command", fake_submit)
    monkeypatch.setattr(hf_routes, "_resolve_run_version", lambda team, run: 7)
    response = _client().post(_ACTION_ROUTE, json=_extend_payload())
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert captured["run_id"] == "run-7"
    assert captured["team_id"] == _TEAM
    assert captured["node_id"] == "hf_hypothesis"
    assert captured["expected_run_version"] == 7
    assert str(captured["kind"].value) == "extend_budget"
    # New stage total is computed server-side from the CTA amounts.
    assert captured["payload"]["limits"] == {"stageTokens": {"hypothesis": 560_000}}
    assert captured["payload"]["recovery"] == {
        "command": "extend_budget",
        "then": "retry_node",
    }
    # The idempotency key is derived from the confirmed amounts, so a repeated
    # identical confirmation replays instead of double-extending.
    assert captured["idempotency_key"] == (
        "inbox-extend-budget:run-7:hypothesis:300000:260000"
    )


def test_extend_budget_action_without_resolvable_run_version_returns_404(
    monkeypatch,
) -> None:
    def fail_submit(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("command must not be submitted for an unknown run")

    monkeypatch.setattr(hf_routes, "_submit_workflow_command", fail_submit)
    monkeypatch.setattr(hf_routes, "_resolve_run_version", lambda team, run: 0)
    response = _client().post(
        _ACTION_ROUTE, json=_extend_payload(expectedRunVersion=0)
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "run_not_found"


def test_extend_budget_action_is_registered_on_the_router() -> None:
    posted = {
        route.path
        for route in hf_routes.router.routes
        if getattr(route, "methods", None) and "POST" in route.methods
    }
    assert (
        "/teams/{team_id}/workflow-orchestration"
        "/hypothesis-first/chain/anomaly-inbox/actions/extend-budget"
    ) in posted
