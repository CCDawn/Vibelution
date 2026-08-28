"""HTTP surface for the knowledge-collection command facade.

The dedicated ensure route (typed payload) and the generic command route
(inspect) both reach the same single write entry; team-authorized sessions
may ensure/inspect regardless of operator role, while operator-only
commands keep their role gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

from tests._support.workflow_ledger_http import ledger_http_client

_TEAM_ID = "acceptance-research-team"
_QUESTION_ID = "question-energy-anomaly-gate-v1"


def _baseline_run_input() -> dict:
    fixture_path = (
        Path(__file__).parent / "fixtures" / "research_workflow_v21_baseline_case.json"
    )
    return json.loads(fixture_path.read_text(encoding="utf-8"))["runInput"]


def _headers() -> dict:
    return {CONTROL_TOKEN_HEADER: get_control_token()}


def _config_with_sideflow_mode(monkeypatch, mode: str) -> None:
    """Patch get_config with a full AppConfig whose sideflow mode is set."""
    from config.models import AppConfig

    config = AppConfig()
    config.research.knowledge_sideflow.mode = mode
    monkeypatch.setattr("config.settings.get_config", lambda: config)


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    from core.research.workflow.definition_registry import reset_registry_for_tests

    reset_registry_for_tests()
    # The ensure route creates a real child run, which is rollout-gated to
    # mode "on"; these HTTP tests exercise the route surface itself.
    _config_with_sideflow_mode(monkeypatch, "on")
    yield
    reset_registry_for_tests()


def test_knowledge_collection_route_ensures_replays_and_inspects(
    tmp_path: Path, monkeypatch
) -> None:
    from core.web.services.team_workflow.research_runtime.run_creation import create_run

    with ledger_http_client(tmp_path, monkeypatch) as (client, _runtime):
        run = create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=_baseline_run_input(),
            idempotency_key="kc-route-create-1",
        )
        run_id = str(run["runId"])
        body = {
            "teamId": _TEAM_ID,
            "idempotencyKey": "kc-route-ensure-1",
            "expectedRunVersion": int(run.get("runVersion") or 1),
            "questionId": _QUESTION_ID,
            "nodeId": "hypothesis_design",
            "searchEnvelope": {
                "keywords": ["evaporation"],
                "evidenceTypes": ["dataset"],
                "timeWindow": {"from": "2024-01-01"},
            },
            "requirements": {"minSources": 2},
            "sourcePolicyVersion": "1",
            "managedSourceRootIds": ["Root-A"],
        }
        first = client.post(
            f"/api/research/workflow-runs/{run_id}/knowledge-collection",
            headers=_headers(),
            json=body,
        )
        assert first.status_code == 202, first.text
        result = first.json()["result"]
        assert result["replayed"] is False
        assert result["childRunId"]
        assert result["managedSourceRootIds"] == ["root-a"]

        second = client.post(
            f"/api/research/workflow-runs/{run_id}/knowledge-collection",
            headers=_headers(),
            json=body,
        )
        assert second.status_code == 202, second.text
        assert second.json()["result"]["replayed"] is True
        assert second.json()["result"]["invocationId"] == result["invocationId"]

        inspected = client.post(
            f"/api/research/workflow-runs/{run_id}/commands",
            headers=_headers(),
            json={
                "teamId": _TEAM_ID,
                "idempotencyKey": "kc-route-inspect-1",
                "expectedRunVersion": int(run.get("runVersion") or 1),
                "command": "inspect_knowledge_collection",
                "payload": {"invocationId": result["invocationId"]},
            },
        )
        assert inspected.status_code == 202, inspected.text
        inspect_result = inspected.json()["result"]
        assert inspect_result["invocations"][0]["invocationId"] == result["invocationId"]
        assert inspect_result["childRun"]["runId"] == result["childRunId"]


def test_knowledge_commands_authorized_without_privileged_roles(
    tmp_path: Path, monkeypatch
) -> None:
    from core.web.services.team_workflow.research_runtime.operator_authorization import (
        CONTROL_OPERATOR_ROLES_ENV,
    )
    from core.web.services.team_workflow.research_runtime.run_creation import create_run

    monkeypatch.setenv(CONTROL_OPERATOR_ROLES_ENV, "viewer")
    with ledger_http_client(tmp_path, monkeypatch) as (client, _runtime):
        run = create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=_baseline_run_input(),
            idempotency_key="kc-route-create-2",
        )
        run_id = str(run["runId"])
        ensured = client.post(
            f"/api/research/workflow-runs/{run_id}/knowledge-collection",
            headers=_headers(),
            json={
                "teamId": _TEAM_ID,
                "idempotencyKey": "kc-route-ensure-viewer",
                "expectedRunVersion": int(run.get("runVersion") or 1),
                "questionId": _QUESTION_ID,
                "nodeId": "hypothesis_design",
            },
        )
        assert ensured.status_code == 202, ensured.text

        cancelled = client.post(
            f"/api/research/workflow-runs/{run_id}/commands",
            headers=_headers(),
            json={
                "teamId": _TEAM_ID,
                "idempotencyKey": "kc-route-cancel-viewer",
                "expectedRunVersion": int(run.get("runVersion") or 1),
                "command": "cancel_run",
                "payload": {"reason": "should not pass"},
            },
        )
        assert cancelled.status_code == 403
        assert cancelled.json()["detail"]["code"] == "command_forbidden"


def test_knowledge_collection_route_rejects_unknown_run(tmp_path: Path, monkeypatch) -> None:
    with ledger_http_client(tmp_path, monkeypatch) as (client, _runtime):
        missing = client.post(
            "/api/research/workflow-runs/run-missing/knowledge-collection",
            headers=_headers(),
            json={
                "teamId": _TEAM_ID,
                "idempotencyKey": "kc-route-missing",
                "expectedRunVersion": 1,
                "questionId": _QUESTION_ID,
            },
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "run_not_found"
