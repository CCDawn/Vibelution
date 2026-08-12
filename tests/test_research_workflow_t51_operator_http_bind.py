"""P0: HTTP must not trust client Operator-Id/Roles headers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes.team_workflows import research_runtime as research_runtime_routes
from core.web.services.team_workflow.research_runtime.durable_index import DurableWorkflowIndex
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    CONTROL_OPERATOR_ROLES_ENV,
    OPERATOR_ID_HEADER,
    OPERATOR_ROLES_HEADER,
    server_operator_scope,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def _baseline_run_input() -> dict:
    fixture_path = (
        Path(__file__).parent / "fixtures" / "research_workflow_v21_baseline_case.json"
    )
    return json.loads(fixture_path.read_text(encoding="utf-8"))["runInput"]


def _service(tmp_path: Path):
    return reset_research_workflow_runtime_service_for_tests(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "ckpt.sqlite"),
        durable_index=DurableWorkflowIndex(tmp_path / "runs" / "_index"),
    )


def _client_for(svc) -> tuple[TestClient, object]:
    app = FastAPI()
    app.include_router(research_runtime_routes.router, prefix="/api")
    mock_svc = MagicMock(wraps=svc)
    mock_svc.authorize_run_access.side_effect = svc.authorize_run_access
    original = research_runtime_routes._svc
    research_runtime_routes._svc = lambda: mock_svc  # type: ignore[assignment]
    return TestClient(app), original


def test_legacy_cancel_without_operator_context_is_forbidden(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_baseline_run_input(),
        idempotency_key="idem-http-1",
    )
    with pytest.raises(ResearchWorkflowError) as exc_info:
        svc.apply_command(run["runId"], "cancel", idempotency_key="cancel-1")
    assert exc_info.value.code == "command_forbidden"


def test_legacy_cancel_viewer_role_is_forbidden(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_baseline_run_input(),
        idempotency_key="idem-http-2",
    )
    with server_operator_scope("op-1", roles=("viewer",)):
        with pytest.raises(ResearchWorkflowError) as exc_info:
            svc.apply_command(run["runId"], "cancel", idempotency_key="cancel-2")
    assert exc_info.value.code == "command_forbidden"


def test_legacy_cancel_operator_role_is_allowed(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_baseline_run_input(),
        idempotency_key="idem-http-3",
    )
    with server_operator_scope("op-1", roles=("operator",)):
        updated = svc.apply_command(run["runId"], "cancel", idempotency_key="cancel-3")
    assert updated["status"] == "cancelled"


def test_http_client_operator_headers_alone_cannot_authorize(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_baseline_run_input(),
        idempotency_key="idem-http-4",
    )
    team_id = str(run.get("teamId") or _baseline_run_input().get("teamId") or "")
    client, original = _client_for(svc)
    try:
        forged = client.post(
            f"/api/research/workflow-runs/{run['runId']}/commands",
            headers={
                OPERATOR_ID_HEADER: "forged-op",
                OPERATOR_ROLES_HEADER: "operator,admin",
            },
            json={
                "teamId": team_id,
                "idempotencyKey": "http-cancel-forged",
                "expectedRunVersion": int(run.get("runVersion") or 1),
                "command": "cancel",
                "payload": {},
            },
        )
        assert forged.status_code == 403
        assert forged.json()["detail"]["code"] == "command_forbidden"
        assert svc.get_run(run["runId"])["status"] != "cancelled"
    finally:
        research_runtime_routes._svc = original  # type: ignore[assignment]


def test_http_control_token_binds_server_operator_not_client_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONTROL_OPERATOR_ROLES_ENV, "viewer")
    svc = _service(tmp_path)
    run = svc.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_baseline_run_input(),
        idempotency_key="idem-http-5",
    )
    team_id = str(run.get("teamId") or _baseline_run_input().get("teamId") or "")
    client, original = _client_for(svc)
    try:
        denied = client.post(
            f"/api/research/workflow-runs/{run['runId']}/commands",
            headers={
                CONTROL_TOKEN_HEADER: get_control_token(),
                # Client claims operator, but server env roles are viewer-only.
                OPERATOR_ID_HEADER: "forged-op",
                OPERATOR_ROLES_HEADER: "operator,admin",
            },
            json={
                "teamId": team_id,
                "idempotencyKey": "http-cancel-viewer-server",
                "expectedRunVersion": int(run.get("runVersion") or 1),
                "command": "cancel",
                "payload": {},
            },
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "command_forbidden"
    finally:
        research_runtime_routes._svc = original  # type: ignore[assignment]


def test_http_control_token_with_server_operator_role_allows_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONTROL_OPERATOR_ROLES_ENV, "operator")
    svc = _service(tmp_path)
    run = svc.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_baseline_run_input(),
        idempotency_key="idem-http-6",
    )
    team_id = str(run.get("teamId") or _baseline_run_input().get("teamId") or "")
    client, original = _client_for(svc)
    try:
        allowed = client.post(
            f"/api/research/workflow-runs/{run['runId']}/commands",
            headers={CONTROL_TOKEN_HEADER: get_control_token()},
            json={
                "teamId": team_id,
                "idempotencyKey": "http-cancel-ok",
                "expectedRunVersion": int(run.get("runVersion") or 1),
                "command": "cancel",
                "payload": {},
            },
        )
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "cancelled"
    finally:
        research_runtime_routes._svc = original  # type: ignore[assignment]


def test_http_human_resolve_binds_server_principal_resolved_by(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.operator_authorization import (
        CONTROL_OPERATOR_ID_ENV,
    )

    monkeypatch.setenv(CONTROL_OPERATOR_ID_ENV, "principal-op-42")
    monkeypatch.setenv(CONTROL_OPERATOR_ROLES_ENV, "operator")
    svc = _service(tmp_path)
    run = svc.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_baseline_run_input(),
        idempotency_key="idem-http-resolve-1",
    )
    team_id = str(run.get("teamId") or _baseline_run_input().get("teamId") or "")
    client, original = _client_for(svc)
    try:
        mock_svc = research_runtime_routes._svc()
        mock_svc.resolve_human_task.return_value = {"runId": run["runId"], "ok": True}
        response = client.post(
            f"/api/research/workflow-runs/{run['runId']}/human-tasks/ht-1/resolve",
            headers={
                CONTROL_TOKEN_HEADER: get_control_token(),
                OPERATOR_ID_HEADER: "forged-client-op",
            },
            json={
                "teamId": team_id,
                "idempotencyKey": "http-resolve-1",
                "expectedRunVersion": int(run.get("runVersion") or 1),
                "decision": "accept",
            },
        )
        assert response.status_code == 200
        kwargs = mock_svc.resolve_human_task.call_args.kwargs
        assert kwargs["resolved_by"] == "principal-op-42"
        assert kwargs["resolved_by"] != "forged-client-op"
        assert kwargs["resolved_by"] != "operator"
    finally:
        research_runtime_routes._svc = original  # type: ignore[assignment]
