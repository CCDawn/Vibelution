from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core.web.routes.team_workflows import experiment as routes
from core.web.routes.team_workflows import stage_rounds
from core.web.routes.team_workflows._models import (
    ChallengePhaseOneApprovalPayload,
    ExperimentPlanCreatePayload,
    ResearchStageRoundStartPayload,
)
from core.web.services.team_workflow.challenge_phase_boundary import PhaseTwoLockedError
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    require_privileged_server_operator,
    server_operator_scope,
)
from core.web.services.team_workflow.research_runtime.operator_permissions import (
    HIGH_IMPACT_COMMANDS,
    require_operator_permission,
)


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def test_phase_one_approval_route_uses_server_operator_not_client_identity(monkeypatch):
    @contextmanager
    def operator_scope(_request):
        yield SimpleNamespace(
            operator_id="server-operator",
            display_name="Server Operator",
            roles=("operator",),
        )

    captured = {}
    monkeypatch.setattr(routes, "server_operator_scope_from_http", operator_scope)
    monkeypatch.setattr(
        routes,
        "require_privileged_server_operator",
        lambda *, command: SimpleNamespace(
            operator_id="server-operator",
            display_name="Server Operator",
        ),
    )
    monkeypatch.setattr(
        routes,
        "approve_and_publish_current_phase_one_manifest",
        lambda team_id, **kwargs: captured.update(teamId=team_id, **kwargs)
        or {"teamId": team_id, "phase1Approved": True},
    )

    response = routes.team_workflow_challenge_phase_one_approve(
        "team-1",
        _request(),
        ChallengePhaseOneApprovalPayload(note="reviewed as one package"),
    )

    assert response["phase1Approved"] is True
    assert captured == {
        "teamId": "team-1",
        "operator_id": "server-operator",
        "operator_display_name": "Server Operator",
        "note": "reviewed as one package",
    }


def test_finalize_stage_one_is_registered_high_impact_operator_gate():
    assert "finalize_stage_one" in HIGH_IMPACT_COMMANDS
    with pytest.raises(PermissionError) as denied:
        require_operator_permission(
            operator_id="op-1",
            roles=("viewer",),
            command="finalize_stage_one",
        )
    assert str(denied.value) == "command_forbidden"
    require_operator_permission(
        operator_id="op-1",
        roles=("operator",),
        command="finalize_stage_one",
    )


def test_privileged_server_operator_gate_rejects_viewer_for_finalize_stage_one():
    with server_operator_scope("op-viewer", roles=("viewer",)):
        with pytest.raises(PermissionError) as denied:
            require_privileged_server_operator(command="finalize_stage_one")
    assert str(denied.value) == "command_forbidden"
    with server_operator_scope("op-1", roles=("operator",)):
        context = require_privileged_server_operator(command="finalize_stage_one")
    assert context.operator_id == "op-1"


def test_phase_one_approval_rejects_non_privileged_role_before_manifest(monkeypatch):
    reached = {"manifest": False}

    def _forbidden_manifest(*_args, **_kwargs):
        reached["manifest"] = True
        raise AssertionError("manifest publish must not run without privileged role")

    monkeypatch.setattr(
        routes,
        "server_operator_scope_from_http",
        lambda _request: server_operator_scope(
            "server-operator", roles=("viewer",)
        ),
    )
    monkeypatch.setattr(
        routes, "approve_and_publish_current_phase_one_manifest", _forbidden_manifest
    )

    with pytest.raises(HTTPException) as captured:
        routes.team_workflow_challenge_phase_one_approve(
            "team-1",
            _request(),
            ChallengePhaseOneApprovalPayload(note="viewer attempt"),
        )
    assert captured.value.status_code == 403
    assert captured.value.detail["code"] == "command_forbidden"
    assert reached["manifest"] is False


def test_phase_one_approval_allows_privileged_operator_role(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        routes,
        "server_operator_scope_from_http",
        lambda _request: server_operator_scope(
            "server-operator", roles=("operator",)
        ),
    )
    monkeypatch.setattr(
        routes,
        "approve_and_publish_current_phase_one_manifest",
        lambda team_id, **kwargs: captured.update(teamId=team_id, **kwargs)
        or {"teamId": team_id, "phase1Approved": True},
    )

    response = routes.team_workflow_challenge_phase_one_approve(
        "team-1",
        _request(),
        ChallengePhaseOneApprovalPayload(note="approved by operator"),
    )

    assert response["phase1Approved"] is True
    assert captured["teamId"] == "team-1"
    assert captured["operator_id"] == "server-operator"


def test_phase_two_routes_report_locked_transition_as_conflict(monkeypatch):
    error = PhaseTwoLockedError("phase_two_locked: phase_one_approval_required")
    monkeypatch.setattr(
        stage_rounds,
        "start_research_stage_round",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        routes,
        "create_experiment_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    for call in (
        lambda: stage_rounds.team_workflow_research_stage_round_start(
            "team-1",
            ResearchStageRoundStartPayload(stageType="experiment", programPhase=2),
        ),
        lambda: routes.team_workflow_experiment_plan_create(
            "team-1",
            ExperimentPlanCreatePayload(programPhase=2),
        ),
    ):
        with pytest.raises(HTTPException) as captured:
            call()
        assert captured.value.status_code == 409
