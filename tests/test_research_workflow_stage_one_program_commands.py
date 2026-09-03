"""HTTP wiring for the stage-one G1 closeout operator commands.

The system adapters own the semantics (covered by
``test_research_workflow_stage_one_closeout.py``); these tests pin the thin
route contract: authorization, CAS on runVersion, closure-node resolution,
error mapping and the ``apply_node_command`` hand-off.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes.team_workflows import research_runtime as research_runtime_module
from core.web.services.team_workflow.research_runtime import (
    program_candidate_handoff,
    result_package_system_adapter,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore
from tests.test_research_workflow_stage_one_closeout import _stage_one_record

TEAM_ID = "challenge-stage-one-team"
CONTROL = {CONTROL_TOKEN_HEADER: get_control_token()}


def _program_review_run(
    tmp_path: Path,
) -> tuple[TestClient, ResearchWorkflowRuntimeService, dict[str, Any]]:
    service = reset_research_workflow_runtime_service_for_tests(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    record = _stage_one_record()
    record.update(
        {
            "teamId": TEAM_ID,
            "status": "waiting_human",
            "stageOneCloseout": {
                "status": "program_review_required",
                "artifactRefs": [
                    item["artifactId"] for item in record["artifactManifests"]
                ],
            },
            "nodeRuns": [
                {
                    "nodeId": "hypothesis_design",
                    "nodeRunId": "nr-hypothesis-design",
                    "attempt": 1,
                    "status": "succeeded",
                    "inputSnapshotHash": "1" * 64,
                }
            ],
        }
    )
    stored = service._store.create_run(record)
    app = FastAPI()
    app.include_router(research_runtime_module.router, prefix="/api")
    client = TestClient(app)
    return client, service, stored


def _command_body(stored: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "teamId": TEAM_ID,
        "command": "build_stage_one_package",
        "expectedRunVersion": stored["runVersion"],
        "idempotencyKey": "stage-one-route-build",
        "payload": {},
    }
    body.update(overrides)
    return body


def _post(client: TestClient, stored: dict[str, Any], body: dict[str, Any]):
    return client.post(
        f"/api/research/workflow-runs/{stored['runId']}/stage-one/commands",
        headers=CONTROL,
        json=body,
    )


def test_stage_one_command_route_rejects_invalid_requests(
    tmp_path: Path,
) -> None:
    client, _service, stored = _program_review_run(tmp_path)

    unknown_command = _post(
        client, stored, _command_body(stored, command="do_magic")
    )
    assert unknown_command.status_code == 422, unknown_command.text

    no_key_body = _command_body(stored)
    no_key_body.pop("idempotencyKey")
    no_key = _post(client, stored, no_key_body)
    assert no_key.status_code == 422, no_key.text

    no_team = _post(client, stored, _command_body(stored, teamId=""))
    assert no_team.status_code == 422, no_team.text

    stale = _post(
        client,
        stored,
        _command_body(stored, expectedRunVersion=stored["runVersion"] + 1),
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "run_version_conflict"

    wrong_team = _post(
        client, stored, _command_body(stored, teamId="another-team")
    )
    assert wrong_team.status_code == 404, wrong_team.text
    assert wrong_team.json()["detail"]["code"] == "team_scope_mismatch"


def test_build_stage_one_package_command_succeeds_and_replays_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service, stored = _program_review_run(tmp_path)
    monkeypatch.setattr(
        result_package_system_adapter,
        "build_proposal_result_package_base",
        lambda _record: {"factChainHash": "f" * 64},
    )
    package = {
        "packageId": "rrp-v2-stage-one-route",
        "factChainHash": "f" * 64,
        "contentHash": "c" * 64,
    }
    monkeypatch.setattr(
        result_package_system_adapter,
        "build_challenge_result_package_v2",
        lambda **_kwargs: package,
    )
    from core.web.services.team_workflow.research_runtime import (
        artifact_readback_registry,
        workflow_artifact_store,
    )

    monkeypatch.setattr(
        artifact_readback_registry,
        "load_scoped_artifact_payload",
        lambda *_args, **_kwargs: {"payload": {"objective": "bounded plan"}},
    )
    monkeypatch.setattr(
        workflow_artifact_store,
        "put_workflow_artifact",
        lambda *_args, **_kwargs: {},
    )

    class _Manifest:
        artifactId = "research_result_package:stage-one-route"

        def to_dict(self):
            return {"artifactId": self.artifactId, "contentHash": "c" * 64}

    monkeypatch.setattr(
        result_package_system_adapter,
        "build_system_artifact",
        lambda **_kwargs: _Manifest(),
    )
    monkeypatch.setattr(
        program_candidate_handoff,
        "handoff_result_package_to_challenge_program",
        lambda **_kwargs: {
            "status": "registered",
            "reviewStatus": "review_required",
            "workflowRunId": stored["runId"],
        },
    )

    # nodeId omitted: the route resolves the closure node from the run policy.
    first = _post(
        client,
        stored,
        _command_body(stored, nodeId="", idempotencyKey="stage-one-route-build"),
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["command"] == "build_stage_one_package"
    assert body["idempotent"] is False
    assert body["resultPackage"]["packageId"] == package["packageId"]
    assert body["programCandidateHandoff"]["reviewStatus"] == "review_required"
    updated = service._store.get_run(stored["runId"])
    assert updated["resultPackageRef"] == "research_result_package:stage-one-route"

    replay = _post(
        client,
        updated,
        _command_body(updated, nodeId="", idempotencyKey="stage-one-route-build"),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent"] is True
    assert replay.json()["resultPackage"]["packageId"] == package["packageId"]


def test_finalize_stage_one_command_maps_program_review_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service, stored = _program_review_run(tmp_path)

    # No registered package yet: the finalize facade reports the missing
    # Challenge Program record instead of inventing acceptance.
    monkeypatch.setattr(
        program_candidate_handoff,
        "handoff_result_package_to_challenge_program",
        lambda **_kwargs: {
            "status": program_candidate_handoff.HANDOFF_STATUS_NEEDS_CONTEXT,
            "reason": "no result package registered",
        },
    )
    missing_package = _post(
        client,
        stored,
        _command_body(
            stored,
            command="finalize_stage_one",
            idempotencyKey="stage-one-route-finalize",
        ),
    )
    assert missing_package.status_code == 409, missing_package.text
    assert (
        missing_package.json()["detail"]["code"] == "stage_one_result_package_missing"
    )

    # Package registered but Program review not approved: rejected as a state
    # conflict until the review route records the approval.
    monkeypatch.setattr(
        program_candidate_handoff,
        "handoff_result_package_to_challenge_program",
        lambda **_kwargs: {
            "status": "registered",
            "reviewStatus": "review_required",
            "workflowRunId": stored["runId"],
        },
    )
    not_approved = _post(
        client,
        stored,
        _command_body(
            stored,
            command="finalize_stage_one",
            idempotencyKey="stage-one-route-finalize",
        ),
    )
    assert not_approved.status_code == 409, not_approved.text
    assert (
        not_approved.json()["detail"]["code"] == "stage_one_program_review_not_approved"
    )
    unchanged = service._store.get_run(stored["runId"])
    assert "completionState" not in unchanged
    assert unchanged["stageOneCloseout"]["status"] == "program_review_required"
