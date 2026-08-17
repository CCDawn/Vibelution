"""T1/T6 public scope, optimistic concurrency, and lease event contracts."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore
from tests.test_research_workflow_v21_runtime_lifecycle import run_input_request

TEAM_ID = "acceptance-research-team"
SOURCE_BINDING = AgentBindingLayers(
    workflowDefaults={"source_finder": "agent-source-finder"}
)


def _runtime(tmp_path: Path) -> tuple[ResearchWorkflowRuntimeService, TestClient]:
    service = reset_research_workflow_runtime_service_for_tests(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    client = TestClient(
        create_app(),
        headers={CONTROL_TOKEN_HEADER: get_control_token()},
    )
    return service, client


def _run(service: ResearchWorkflowRuntimeService) -> dict:
    return service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=run_input_request(team_id=TEAM_ID),
        binding_layers=SOURCE_BINDING,
        idempotency_key="create-team-scope-version",
    )


def test_effective_bindings_include_canonical_agent_display_name(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service, _client = _runtime(tmp_path)
    monkeypatch.setattr(
        service,
        "_effective_binding_layers",
        lambda _workflow_id, _team_id: SOURCE_BINDING,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.service._agent_display_name_map",
        lambda: {"agent-source-finder": "资料寻找 Agent"},
    )

    def boom_get_agent(*_args, **_kwargs):
        raise AssertionError("full get_agent must not run")

    monkeypatch.setattr("core.web.services.agent_directory_service.get_agent", boom_get_agent)

    payload = service.get_effective_agent_bindings(
        CHALLENGE_CUP_WORKFLOW_ID,
        team_id=TEAM_ID,
    )
    source_binding = next(
        item for item in payload["bindings"] if item["nodeId"] == "source_finding"
    )

    assert source_binding["agentId"] == "agent-source-finder"
    assert source_binding["displayName"] == "资料寻找 Agent"


def test_run_queries_require_exact_team_scope(tmp_path: Path, monkeypatch) -> None:
    from core.web.services.team_workflow.research_runtime.run_creation import create_run
    from tests._support.workflow_ledger_http import ledger_http_client

    with ledger_http_client(tmp_path, monkeypatch) as (client, _runtime):
        run = create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=run_input_request(team_id=TEAM_ID),
            binding_layers=SOURCE_BINDING,
            idempotency_key="create-team-scope-version",
        )
        base = f"/api/research/workflow-runs/{run['runId']}"

        snapshot = client.get(f"{base}/snapshot?teamId={TEAM_ID}")
        assert snapshot.status_code == 200, snapshot.text
        assert snapshot.json()["run"]["teamId"] == TEAM_ID
        assert snapshot.json()["run"]["runVersion"] == run["runVersion"]

        for path in (
            f"{base}/snapshot",
            f"{base}/nodes/source_finding",
            f"{base}/handoffs",
            f"{base}/research-ledger",
            f"{base}/budget",
            f"{base}/hypotheses",
            f"{base}/experiment-campaigns",
            f"{base}/evaluation",
            f"{base}/events",
            f"{base}/stream",
        ):
            missing = client.get(path)
            assert missing.status_code == 422, (path, missing.text)

        mismatch = client.get(f"{base}/snapshot?teamId=another-team")
        assert mismatch.status_code == 404, mismatch.text
        assert mismatch.json()["detail"]["code"] == "team_scope_mismatch"

        for suffix in ("budget", "hypotheses", "experiment-campaigns", "evaluation"):
            response = client.get(f"{base}/{suffix}?teamId={TEAM_ID}")
            assert response.status_code == 200, (suffix, response.text)
            assert response.json()["teamId"] == TEAM_ID
            assert response.json()["runVersion"] == run["runVersion"]


def test_commands_require_team_id_idempotency_and_expected_run_version(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from core.web.services.team_workflow.research_runtime.run_creation import create_run
    from tests._support.workflow_ledger_http import ledger_http_client

    with ledger_http_client(tmp_path, monkeypatch) as (client, _runtime):
        run = create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=run_input_request(team_id=TEAM_ID),
            binding_layers=SOURCE_BINDING,
            idempotency_key="create-team-scope-commands",
        )
        assert run["runVersion"] == 1
        endpoint = f"/api/research/workflow-runs/{run['runId']}/commands"
        valid = {
            "teamId": TEAM_ID,
            "command": "cancel_run",
            "idempotencyKey": "cancel-v1",
            "expectedRunVersion": run["runVersion"],
            "payload": {},
        }

        for missing_key in ("teamId", "idempotencyKey", "expectedRunVersion"):
            body = {key: value for key, value in valid.items() if key != missing_key}
            rejected = client.post(endpoint, json=body)
            assert rejected.status_code == 422, (missing_key, rejected.text)

        wrong_team = client.post(
            endpoint,
            headers={CONTROL_TOKEN_HEADER: get_control_token()},
            json={**valid, "teamId": "another-team"},
        )
        assert wrong_team.status_code == 404, wrong_team.text
        assert wrong_team.json()["detail"]["code"] == "team_scope_mismatch"

        stale = client.post(
            endpoint,
            headers={CONTROL_TOKEN_HEADER: get_control_token()},
            json={**valid, "expectedRunVersion": run["runVersion"] + 1},
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "run_version_conflict"

        accepted = client.post(
            endpoint,
            headers={CONTROL_TOKEN_HEADER: get_control_token()},
            json=valid,
        )
        assert accepted.status_code == 202, accepted.text
        assert accepted.json()["status"] == "accepted"
        assert accepted.json()["acceptedRunVersion"] > run["runVersion"]


def test_heartbeat_persists_typed_event_and_advances_run_version(
    tmp_path: Path,
) -> None:
    service, _client = _runtime(tmp_path)
    run = _run(service)
    started = service.apply_node_command(
        run["runId"],
        "source_finding",
        "start_execution",
        payload={
            "idempotencyKey": "source-lease-1",
            "leaseOwner": "worker-source-1",
            "taskId": "task-source-1",
            "sessionId": "session-source-1",
        },
    )
    heartbeat = service.apply_node_command(
        run["runId"],
        "source_finding",
        "heartbeat_execution",
        payload={
            "idempotencyKey": "source-heartbeat-1",
            "leaseOwner": "worker-source-1",
            "leaseSeconds": 90,
        },
    )
    repeated = service.apply_node_command(
        run["runId"],
        "source_finding",
        "heartbeat_execution",
        payload={
            "idempotencyKey": "source-heartbeat-1",
            "leaseOwner": "worker-source-1",
            "leaseSeconds": 90,
        },
    )

    assert heartbeat["runVersion"] > started["runVersion"]
    event = heartbeat["events"][-1]
    assert event["type"] == "LeaseHeartbeat"
    assert event["nodeId"] == "source_finding"
    assert event["summary"]["leaseOwner"] == "worker-source-1"
    assert event["summary"]["heartbeatAt"]
    assert event["summary"]["leaseExpiresAt"]
    assert repeated["runVersion"] == heartbeat["runVersion"]
    assert len(repeated["events"]) == len(heartbeat["events"])
