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
