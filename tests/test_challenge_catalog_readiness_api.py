"""Focused tests for the independent formal catalog readiness endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from core.research.competition.real_control_batch import new_real_batch_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes.team_workflows import experiment as experiment_routes
from core.web.services.team_workflow import (
    challenge_catalog_readiness as readiness_service,
)


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_catalog_readiness_missing_real_envelope_is_typed_not_ready(monkeypatch) -> None:
    monkeypatch.setattr(readiness_service, "_server_readiness_snapshot", lambda _team_id: None)
    monkeypatch.setattr(
        readiness_service,
        "get_real_batch_catalog_state",
        lambda *_args, **_kwargs: None,
    )

    report = readiness_service.get_catalog_hypothesis_flow_readiness("team-readiness")

    assert report["status"] == "NOT_READY"
    assert report["realCampaignAllowed"] is False
    assert report["researchAuthorizationRequired"] is True
    assert "real_batch_missing" in report["blockers"]
    assert set(report["evidence"]) == {"r0", "r1", "api", "frontend", "browser"}
    assert all(item["status"] == "MISSING" for item in report["evidence"].values())
    assert len(report["readinessReportSha256"]) == 64


def test_catalog_readiness_uses_real_state_and_durable_policy_hash(monkeypatch) -> None:
    state = new_real_batch_state("real-125")
    monkeypatch.setattr(
        readiness_service,
        "_server_readiness_snapshot",
        lambda _team_id: {
            "report": {
                "sourceCommit": "a" * 40,
                "programContract": {"version": "2.2.0", "coreBehaviorHash": "b" * 64},
                "catalogPolicy": {"version": "1.2.0", "corePolicyHash": "c" * 64},
                "evidence": {
                    "r0": {"status": "PASS", "locator": "server://r0"},
                    "r1": {"status": "PASS", "locator": "server://r1"},
                    "api": {"status": "MISSING", "locator": ""},
                    "frontend": {"status": "MISSING", "locator": ""},
                    "browser": {"status": "MISSING", "locator": ""},
                },
            }
        },
    )
    monkeypatch.setattr(
        readiness_service,
        "get_real_batch_catalog_state",
        lambda *_args, **_kwargs: (state, "d" * 64),
    )

    report = readiness_service.get_catalog_hypothesis_flow_readiness("team-readiness")

    assert report["modelPolicySha256"] == "d" * 64
    assert report["sourceCommit"] == "a" * 40
    assert report["catalogResultSet"]["counts"]["required_question_count"] == 125
    assert report["catalogResultSet"]["counts"]["present_count"] == 0
    assert report["status"] == "NOT_READY"
    assert report["realCampaignAllowed"] is False


def test_catalog_readiness_route_is_separate_from_submission_readiness(monkeypatch) -> None:
    monkeypatch.setattr(
        experiment_routes,
        "get_catalog_hypothesis_flow_readiness",
        lambda team_id: {
            "schemaVersion": 1,
            "reportKind": "CatalogHypothesisFlowReadinessReport",
            "status": "NOT_READY",
            "researchAuthorizationRequired": True,
            "realCampaignAllowed": False,
            "nextLegalAction": "repair_catalog_hypothesis_flow_readiness",
            "sourceCommit": "",
            "programContract": {},
            "catalogPolicy": {},
            "modelPolicySha256": "",
            "catalogResultSet": {},
            "evidence": {
                key: {"status": "MISSING", "locator": ""}
                for key in ("r0", "r1", "api", "frontend", "browser")
            },
            "blockers": ["real_batch_missing"],
            "readinessReportSha256": "e" * 64,
            "generatedAt": "2026-08-23T00:00:00Z",
            "teamId": team_id,
        },
    )

    response = _client().get(
        "/api/teams/research-team/workflow-orchestration/challenge-program/catalog-readiness"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reportKind"] == "CatalogHypothesisFlowReadinessReport"
    assert payload["status"] == "NOT_READY"
    assert "teamId" not in payload
