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
            kind="run_artifacts",
            workflow_run_id="run-facts",
            source_collection_run_id="run-facts",
            artifact_identity="bounded-attempt",
            payload={
                "execution": {
                    "status": "completed",
                    "adapterId": "synthetic_classification_baseline_vs_variant",
                    "runnerMode": "v1_cpu_smoke",
                    "metrics": {"delta": {"macro_f1": 0.1}},
                    "artifactHash": "d" * 64,
                    "formalRunnerUnavailable": "Record a passing smoke result before formal full-run preparation.",
                    "decisionHint": "needs_full_run",
                }
            },
        )
        bounded = context.controlled_run("research-team", "run-facts")
        assert bounded is not None
        assert bounded["terminal"] is True
        assert bounded["metrics"]["delta"]["macro_f1"] == 0.1
        assert bounded["logs"]
        assert bounded["artifact_hash"]

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


def test_readiness_releases_needs_review_smoke_after_human_accept(
    monkeypatch, tmp_path
) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    harness.seed_run("run-needs-review")
    context = RealDomainReadinessContext(harness.store)
    try:
        put_workflow_artifact(
            "research-team",
            kind="smoke_evidence",
            workflow_run_id="run-needs-review",
            source_collection_run_id="run-needs-review",
            artifact_identity="smoke-attempt",
            payload={
                "status": "needs_review",
                "smokeRunId": "smoke-1",
                "planId": "plan-1",
            },
        )
        put_workflow_artifact(
            "research-team",
            kind="smoke_release",
            workflow_run_id="run-needs-review",
            source_collection_run_id="run-needs-review",
            artifact_identity="gate-task-1",
            payload={
                "decision": "accept",
                "resolvedBy": "operator-1",
                "smokeRunId": "smoke-1",
                "planId": "plan-1",
            },
        )
        assert context.smoke_evidence("research-team", "run-needs-review")["released"] is True
    finally:
        harness.close()


def test_readiness_loads_run_artifacts_when_authority_id_differs_from_record(
    monkeypatch, tmp_path
) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    harness = CommandHarness(tmp_path / "ledger-sc-drift.sqlite3")
    try:
        run_id = "run-317ed54cb838"
        from tests._support.workflow_ledger_helpers import build_event_record, build_run_record

        snapshot = {
            "snapshotHash": "a" * 64,
            "teamId": "research-team",
            "sourceCollectionRunId": "sc-original",
        }

        def mutate(uow):
            uow.repository.insert_run(build_run_record(run_id=run_id, last_event_sequence=1))
            uow.repository.execute(
                "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
                (json.dumps(snapshot), run_id),
            )
            uow.repository.insert_event(
                build_event_record(
                    sequence=1,
                    run_id=run_id,
                    event_type="run_created",
                    event_id=f"evt-created-{run_id}",
                )
            )

        harness.store.submit(mutate, force_flush=True).result(timeout=10)
        put_workflow_artifact(
            "research-team",
            kind="run_artifacts",
            workflow_run_id=run_id,
            source_collection_run_id=run_id,
            artifact_identity="nr-bounded",
            payload={
                "execution": {
                    "status": "completed",
                    "adapterId": "synthetic_classification_baseline_vs_variant",
                    "runnerMode": "v1_cpu_smoke",
                    "metrics": {"baseline": {"accuracy": 1.0}},
                    "artifactHash": "f" * 64,
                    "formalRunnerUnavailable": (
                        "Experiment plan does not select the formal FashionMNIST multi-seed adapter."
                    ),
                }
            },
        )
        context = RealDomainReadinessContext(harness.store)
        run_state = context.controlled_run("research-team", run_id)
        assert run_state is not None
        assert run_state["terminal"] is True
        assert run_state["metrics"]["baseline"]["accuracy"] == 1.0
        assert run_state["artifact_hash"]
    finally:
        harness.close()


def test_workflow_store_accepts_iteration_decision_and_governance_kinds(
    monkeypatch, tmp_path
) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    for kind in ("iteration_decision", "version_governance_record"):
        put_workflow_artifact(
            "research-team",
            kind=kind,
            workflow_run_id="run-kinds",
            source_collection_run_id="sc-kinds",
            artifact_identity=f"id-{kind}",
            payload={"ok": True, "recordKind": kind},
        )
        loaded = load_workflow_artifact_payload(
            kind,
            team_id="research-team",
            authority_run_id="sc-kinds",
            workflow_run_id="run-kinds",
        )
        assert loaded is not None
        body = loaded.get("payload") if isinstance(loaded.get("payload"), dict) else loaded
        assert body["recordKind"] == kind


def test_persist_workflow_artifact_keeps_first_write_on_identity_retry(
    monkeypatch, tmp_path
) -> None:
    from core.web.services.team_workflow.research_runtime.real_domain_ports import (
        _persist_workflow_artifact,
    )

    _use_artifact_root(monkeypatch, tmp_path)
    kwargs = {
        "kind": "evaluation_report",
        "team_id": "research-team",
        "workflow_run_id": "run-retry",
        "source_collection_run_id": "sc-retry",
        "artifact_identity": "nr-run-retry-result_evaluation-a1",
    }
    _persist_workflow_artifact(payload={"evaluatedAt": "t1", "status": "bounded"}, **kwargs)
    _persist_workflow_artifact(payload={"evaluatedAt": "t2", "status": "bounded"}, **kwargs)
    loaded = load_workflow_artifact_payload(
        "evaluation_report",
        team_id="research-team",
        authority_run_id="sc-retry",
        workflow_run_id="run-retry",
    )
    assert loaded is not None
    body = loaded.get("payload") if isinstance(loaded.get("payload"), dict) else loaded
    assert body["evaluatedAt"] == "t1"
    assert (
        len(
            list_workflow_artifacts(
                "research-team",
                kind="evaluation_report",
                workflow_run_id="run-retry",
                source_collection_run_id="sc-retry",
            )
        )
        == 1
    )
