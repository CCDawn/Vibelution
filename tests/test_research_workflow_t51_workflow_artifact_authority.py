from __future__ import annotations

import json

import pytest

from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
    build_canonical_ref,
    read_domain_artifact,
)
from core.web.services.team_workflow.research_runtime.atomic_fs import (
    CorruptWorkflowStoreError,
)
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)
from core.web.services.team_workflow.research_runtime.real_readiness_context import (
    RealDomainReadinessContext,
)
from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
    WorkflowArtifactConflictError,
    list_workflow_artifacts,
    load_workflow_artifact_payload,
    put_workflow_artifact,
)

from tests._support.command_helpers import CommandHarness


def _use_artifact_root(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)


def test_dual_scope_requires_workflow_and_authority_match(monkeypatch, tmp_path) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    put_workflow_artifact(
        "research-team",
        kind="run_artifacts",
        workflow_run_id="run-a",
        source_collection_run_id="sc-shared",
        artifact_identity="attempt-a",
        payload={"value": "a"},
    )
    put_workflow_artifact(
        "research-team",
        kind="run_artifacts",
        workflow_run_id="run-b",
        source_collection_run_id="sc-shared",
        artifact_identity="attempt-b",
        payload={"value": "b"},
    )

    loaded = load_workflow_artifact_payload(
        "run_artifacts",
        team_id="research-team",
        authority_run_id="sc-shared",
        workflow_run_id="run-a",
    )

    assert loaded is not None
    assert loaded["workflowRunId"] == "run-a"
    assert loaded["payload"] == {"value": "a"}


def test_artifact_lineage_is_append_only_and_old_ref_remains_addressable(
    monkeypatch, tmp_path
) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    for identity, value in (("attempt-1", "first"), ("attempt-2", "second")):
        put_workflow_artifact(
            "research-team",
            kind="run_artifacts",
            workflow_run_id="run-lineage",
            source_collection_run_id="sc-lineage",
            artifact_identity=identity,
            payload={"value": value},
        )
    first = load_workflow_artifact_payload(
        "run_artifacts",
        team_id="research-team",
        authority_run_id="sc-lineage",
        workflow_run_id="run-lineage",
        content_hash=canonical_sha256(
            {
                "teamId": "research-team",
                "kind": "run_artifacts",
                "workflowRunId": "run-lineage",
                "sourceCollectionRunId": "sc-lineage",
                "payload": {"value": "first"},
            }
        ),
    )
    assert first is not None
    first_hash = canonical_sha256(first)
    first_ref = build_canonical_ref(
        kind="run_artifacts",
        team_id="research-team",
        authority_run_id="sc-lineage",
        content_hash=first_hash,
    )

    assert len(
        list_workflow_artifacts(
            "research-team",
            kind="run_artifacts",
            workflow_run_id="run-lineage",
            source_collection_run_id="sc-lineage",
        )
    ) == 2
    assert read_domain_artifact(first_ref) is not None


def test_artifact_identity_replay_is_idempotent_and_conflict_fails_loudly(
    monkeypatch, tmp_path
) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    kwargs = {
        "kind": "smoke_evidence",
        "workflow_run_id": "run-replay",
        "source_collection_run_id": "run-replay",
        "artifact_identity": "node-run-1",
    }
    first = put_workflow_artifact("research-team", payload={"status": "passed"}, **kwargs)
    replay = put_workflow_artifact("research-team", payload={"status": "passed"}, **kwargs)
    assert replay == first
    assert len(list_workflow_artifacts("research-team", kind="smoke_evidence")) == 1
    with pytest.raises(WorkflowArtifactConflictError):
        put_workflow_artifact("research-team", payload={"status": "failed"}, **kwargs)


def test_corrupt_artifact_store_fails_loudly(monkeypatch, tmp_path) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    path = (
        tmp_path
        / "workspace"
        / "teams"
        / "research-team"
        / "workflow_artifacts"
        / "run_artifacts.jsonl"
    )
    path.parent.mkdir(parents=True)
    path.write_text('{"broken":', encoding="utf-8")

    with pytest.raises(CorruptWorkflowStoreError):
        list_workflow_artifacts("research-team", kind="run_artifacts")


def test_readiness_projects_typed_smoke_run_and_package_facts(
    monkeypatch, tmp_path
) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    harness.seed_run("run-facts")
    context = RealDomainReadinessContext(harness.store)
    try:
        put_workflow_artifact(
            "research-team",
            kind="smoke_evidence",
            workflow_run_id="run-facts",
            source_collection_run_id="run-facts",
            artifact_identity="smoke-attempt",
            payload={"status": "passed", "smokeRunId": "smoke-1", "planId": "plan-1"},
        )
        assert context.smoke_evidence("research-team", "run-facts")["released"] is False
        put_workflow_artifact(
            "research-team",
            kind="smoke_release",
            workflow_run_id="run-facts",
            source_collection_run_id="run-facts",
            artifact_identity="gate-task-1",
            payload={
                "decision": "accept",
                "resolvedBy": "operator-1",
                "smokeRunId": "smoke-1",
                "planId": "plan-1",
            },
        )
        assert context.smoke_evidence("research-team", "run-facts")["released"] is True

        put_workflow_artifact(
            "research-team",
            kind="run_artifacts",
            workflow_run_id="run-facts",
            source_collection_run_id="run-facts",
            artifact_identity="run-attempt",
            payload={
                "execution": {
                    "status": "completed",
                    "result": {"logs": ["ok"], "metrics": {"score": 0.9}},
                }
            },
        )
        run_state = context.controlled_run("research-team", "run-facts")
        assert run_state is not None
        assert run_state["terminal"] is True
        assert run_state["logs"] == ["ok"]
        assert run_state["metrics"] == {"score": 0.9}
        assert run_state["artifact_hash"]

        put_workflow_artifact(
            "research-team",
            kind="research_result_package",
            workflow_run_id="run-facts",
            source_collection_run_id="run-facts",
            artifact_identity="package-attempt",
            payload={
                "package": {
                    "terminalReason": "completed",
                    "traceability": {"artifactRefs": ["artifact://one"]},
                }
            },
        )
        package = context.result_package("research-team", "run-facts")
        assert package is not None
        assert package["required_artifacts"] is True
        assert package["pending_human_tasks"] == 0
        assert package["terminal_reason"] == "completed"
    finally:
        harness.close()
