"""T5.1-1 RED: default Agent task adapters + adapter-worker exception containment.

Production RealDomainPorts must map every Agent node (including source_*) onto a
canonical task adapter. AdapterDispatchWorker must never leave Attempt in
dispatching / Outbox in leased when execute/preflight/read-back/verify raises.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.workflow.contracts import PendingAction
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.action_registry import ActionRegistry
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
    AdapterDispatchWorker,
)
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
    AgentActionAdapter,
)
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    RealDomainPorts,
    _task_kind_for,
)
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


AGENT_NODE_IDS = tuple(
    node.nodeId
    for node in build_challenge_cup_workflow_definition().nodes
    if node.actorKind == ActorKind.AGENT
)


def test_task_adapter_registry_covers_every_agent_node() -> None:
    from core.web.services.team_workflow.research_runtime.task_adapter_registry import (
        resolve_agent_task_adapter,
    )

    missing = [node_id for node_id in AGENT_NODE_IDS if resolve_agent_task_adapter(node_id) is None]
    assert missing == [], f"Agent nodes missing task adapters: {missing}"


def test_real_domain_ports_task_kind_covers_source_finding() -> None:
    # Legacy helper must not reject the production first node.
    assert _task_kind_for("source_finding") is not None
    assert _task_kind_for("source_extraction") is not None
    assert _task_kind_for("evidence_relations") is not None
    assert _task_kind_for("knowledge_ingestion") is not None


def test_real_ports_create_agent_task_rejects_unknown_with_stable_code(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-unknown",
            run_id="run-test",
            node_run_id="nr-run-test-unknown-a1",
            node_id="not_a_real_node",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        with pytest.raises(RuntimeError, match="has no task adapter"):
            ports.create_agent_task(action=action)
    finally:
        harness.close()


def _seed_dispatching(harness: CommandHarness, action: PendingAction) -> None:
    from core.research.workflow.ledger import OutboxRecord
    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_command_record,
        build_event_record,
        build_run_record,
    )

    def mutate(uow):
        if uow.repository.get_run(action.run_id) is None:
            uow.repository.insert_run(build_run_record(run_id=action.run_id, last_event_sequence=1))
            uow.repository.insert_event(
                build_event_record(
                    sequence=1,
                    run_id=action.run_id,
                    event_type="run_created",
                    event_id=f"evt-created-{action.run_id}",
                )
            )
        if uow.repository.get_command("cmd-driver") is None:
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-driver",
                    run_id=action.run_id,
                    idempotency_key="cmd-driver",
                )
            )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=action.node_run_id,
                run_id=action.run_id,
                node_id=action.node_id,
                attempt=1,
                status="dispatching",
                command_id="cmd-driver",
                started_at_ms=FIXED_NOW_MS,
            )
        )
        uow.repository.insert_outbox(
            OutboxRecord(
                action_id=f"adapter-outbox-{action.action_id}",
                run_id=action.run_id,
                command_id="cmd-driver",
                node_run_id=action.node_run_id,
                action_kind="adapter_dispatch",
                idempotency_key=f"adapter:{action.action_id}",
                payload_json=json.dumps(action.to_dict()),
                status="pending",
                attempt_count=0,
                available_at_ms=FIXED_NOW_MS,
                lease_owner=None,
                lease_expires_at_ms=None,
                last_problem_json=None,
                created_at_ms=FIXED_NOW_MS,
                updated_at_ms=FIXED_NOW_MS,
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


@pytest.mark.parametrize(
    "boom_phase",
    ("read_back_input", "preflight", "execute", "verify"),
)
def test_adapter_worker_contains_phase_exceptions(tmp_path: Path, boom_phase: str) -> None:
    harness = CommandHarness(tmp_path / f"ledger-{boom_phase}.sqlite3")
    try:
        action = PendingAction(
            action_id="act-boom",
            run_id="run-test",
            node_run_id="nr-run-test-source_finding-a1",
            node_id="source_finding",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        _seed_dispatching(harness, action)

        class BoomPorts(FakeDomainPorts):
            def read_back_input(self, action):  # type: ignore[override]
                if boom_phase == "read_back_input":
                    raise RuntimeError("boom-readback")
                return super().read_back_input(action)

            def create_agent_task(self, *, action):  # type: ignore[override]
                if boom_phase == "execute":
                    raise RuntimeError("boom-execute")
                return super().create_agent_task(action=action)

            def read_back_artifact(self, canonical_ref: str):  # type: ignore[override]
                if boom_phase == "verify":
                    raise RuntimeError("boom-verify")
                return super().read_back_artifact(canonical_ref)

        ports = BoomPorts()
        registry = ActionRegistry()
        adapter = AgentActionAdapter(ports)

        if boom_phase == "preflight":
            original_preflight = adapter.preflight

            def exploding_preflight(action):
                raise RuntimeError("boom-preflight")

            adapter.preflight = exploding_preflight  # type: ignore[method-assign]
            _ = original_preflight

        registry.register(adapter)
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda _node: (),
        )
        # Must not raise out of the worker.
        worker.run_once()

        attempt = harness.store.latest_attempt(action.run_id, action.node_id)
        assert attempt is not None
        assert attempt.status in {"failed", "blocked", "reconciliation_required"}
        assert attempt.status != "dispatching"
        run = harness.store.get_run(action.run_id)
        assert run is not None
        assert run.status == "blocked"
        event_types = [item.event_type for item in harness.store.list_events(action.run_id)]
        assert "run_blocked" in event_types
        if attempt.status == "failed":
            assert "node_failed" in event_types

        outbox_rows = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM outbox_actions WHERE action_id = ?",
                (f"adapter-outbox-{action.action_id}",),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert outbox_rows is not None
        assert outbox_rows[0] != "leased"
    finally:
        harness.close()


def _seed_run_with_snapshot(harness: CommandHarness, *, run_id: str, snapshot: dict) -> None:
    import json

    from tests._support.workflow_ledger_helpers import build_event_record, build_run_record

    record = build_run_record(run_id=run_id, last_event_sequence=1)
    snapshot_json = json.dumps(snapshot, ensure_ascii=False)

    def mutate(uow):
        uow.repository.insert_run(record)
        uow.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
            (snapshot_json, run_id),
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


def _controlled_run_campaign(*, run_id: str) -> dict:
    return {
        "campaignId": "campaign-ledger-1",
        "runId": run_id,
        "hypothesisCandidateId": "hypothesis-1",
        "protocolHash": "3" * 64,
        "environmentSnapshotHash": "6" * 64,
        "datasetSnapshotRefs": ["fixture://dataset/ledger"],
        "baselineRefs": ["baseline:control"],
        "metricContractRef": "metric:score",
        "stage": "ablation_replication",
        "seedSet": [11, 29, 47],
        "replicationCount": 3,
        "budgetLedgerRef": "budget-ledger-1",
        "stopCriteria": {"maxNoImprovementRounds": 2},
        "experimentRunRefs": [],
        "resultArtifactRefs": [],
        "decision": "completed",
    }


def test_ledger_ports_controlled_run_execute_system_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ledger RealDomainPorts must call formal full-run (not only UI node_command)."""
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        SystemActionAdapter,
    )

    harness = CommandHarness(tmp_path / "ledger-controlled.sqlite3")
    try:
        run_id = "run-controlled"
        calls: list[tuple[str, str]] = []

        def fake_full_run(team_id: str, plan_id: str, _payload: dict) -> dict:
            calls.append((team_id, plan_id))
            return {
                "execution": {
                    "executionId": "execution-ledger-1",
                    "status": "completed",
                    "adapterId": "formal_runner_v1",
                }
            }

        monkeypatch.setattr(
            "core.web.services.team_workflow.experiment_api.full_run.execute_experiment_full_run",
            fake_full_run,
        )
        _seed_run_with_snapshot(
            harness,
            run_id=run_id,
            snapshot={
                "snapshotHash": "a" * 64,
                "teamId": "team-ledger-sys",
                "sourceCollectionRunId": "sc-ledger-1",
                "controlledRun": {
                    "planId": "plan-ledger-v1",
                    "campaign": _controlled_run_campaign(run_id=run_id),
                },
            },
        )
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-controlled",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-controlled_run-a1",
            node_id="controlled_run",
            attempt=1,
            actor_kind=ActorKind.SYSTEM,
            action_kind="system_action:controlled_run",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        refs, meta = ports.execute_system_action(action=action)
        assert calls == [("team-ledger-sys", "plan-ledger-v1")]
        assert meta.get("runnerId")
        assert meta.get("executionId") == "execution-ledger-1"
        assert refs and refs[0]["kind"] == "run_artifacts"

        from core.web.services.team_workflow.research_runtime.action_registry import (
            AdapterResult,
        )

        adapter = SystemActionAdapter(ports, node_id="controlled_run")
        # Prove verify against Ledger ports (reserve needs attempt FK; skip execute()).
        result = AdapterResult(
            action_id=action.action_id,
            outcome="succeeded",
            materialized_refs=tuple(refs),
            anchor={
                "systemActionId": str(meta.get("systemActionId") or action.action_id),
                "actionId": action.action_id,
            },
            usage={"compute": str(meta.get("runnerId") or "")},
            reserved={"reservationId": "res-test", "stageId": "execution_iteration"},
        )
        verified = adapter.verify(action, result)
        assert verified.outcome == "succeeded"
        assert verified.artifact_receipts
    finally:
        harness.close()


def test_ledger_ports_controlled_run_reads_plan_from_smoke_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SCI-096 snapshot has no planId/campaign; frozen_protocol + smoke_release do."""
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        put_workflow_artifact,
    )

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    harness = CommandHarness(tmp_path / "ledger-controlled-artifact.sqlite3")
    try:
        run_id = "run-controlled-artifact"
        calls: list[tuple[str, str]] = []

        def fake_full_run(team_id: str, plan_id: str, _payload: dict) -> dict:
            calls.append((team_id, plan_id))
            return {
                "execution": {
                    "executionId": "execution-from-artifact",
                    "status": "completed",
                    "adapterId": "formal_runner_v1",
                }
            }

        monkeypatch.setattr(
            "core.web.services.team_workflow.experiment_api.full_run.execute_experiment_full_run",
            fake_full_run,
        )
        _seed_run_with_snapshot(
            harness,
            run_id=run_id,
            snapshot={
                "snapshotHash": "a" * 64,
                "teamId": "team-ledger-sys",
                "sourceCollectionRunId": "sc-ledger-1",
            },
        )
        put_workflow_artifact(
            "team-ledger-sys",
            kind="frozen_protocol",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="human-gate:ht-freeze",
            payload={
                "teamId": "team-ledger-sys",
                "workflowRunId": run_id,
                "sourceCollectionRunId": "sc-ledger-1",
                "protocolId": "plan-from-artifact",
                "planId": "plan-from-artifact",
                "status": "frozen",
                "protocolDraftHash": "3" * 64,
                "protocolReviewHash": "4" * 64,
                "protocol": {
                    "planId": "plan-from-artifact",
                    "dataset": "ds",
                    "baseline": "bl",
                    "metric": "macro_f1",
                    "seed": [42, 2026],
                    "stop_condition": "max rounds",
                    "hypothesisPortfolioId": "challenge-sci-096",
                    "hypothesisRefs": ["H1"],
                },
            },
        )
        put_workflow_artifact(
            "team-ledger-sys",
            kind="smoke_release",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="human-gate:ht-smoke",
            payload={
                "teamId": "team-ledger-sys",
                "workflowRunId": run_id,
                "sourceCollectionRunId": "sc-ledger-1",
                "planId": "plan-from-artifact",
                "smokeRunId": "smoke-1",
                "status": "released",
                "frozenProtocolHash": "b" * 64,
                "smokeEvidenceHash": "c" * 64,
            },
        )
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-controlled-artifact",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-controlled_run-a1",
            node_id="controlled_run",
            attempt=1,
            actor_kind=ActorKind.SYSTEM,
            action_kind="system_action:controlled_run",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        refs, meta = ports.execute_system_action(action=action)
        assert calls == [("team-ledger-sys", "plan-from-artifact")]
        assert meta.get("planId") == "plan-from-artifact"
        assert meta.get("executionId") == "execution-from-artifact"
        assert refs and refs[0]["kind"] == "run_artifacts"
    finally:
        harness.close()


def test_ledger_ports_controlled_run_uses_bounded_runner_when_formal_adapter_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SCI-096 smoke_release is accepted but FashionMNIST is not selected."""
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        put_workflow_artifact,
    )
    from core.web.services.team_workflow_orchestration_service import (
        TeamWorkflowOrchestrationError,
    )

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)

    def reject_formal(team_id: str, plan_id: str, _payload: dict) -> dict:
        raise TeamWorkflowOrchestrationError(
            "Experiment plan does not select the formal FashionMNIST multi-seed adapter."
        )

    monkeypatch.setattr(
        "core.web.services.team_workflow.experiment_api.full_run.execute_experiment_full_run",
        reject_formal,
    )
    harness = CommandHarness(tmp_path / "ledger-controlled-bounded.sqlite3")
    try:
        run_id = "run-controlled-bounded"
        _seed_run_with_snapshot(
            harness,
            run_id=run_id,
            snapshot={
                "snapshotHash": "a" * 64,
                "teamId": "team-ledger-sys",
                "sourceCollectionRunId": "sc-ledger-1",
            },
        )
        put_workflow_artifact(
            "team-ledger-sys",
            kind="frozen_protocol",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="human-gate:ht-freeze",
            payload={
                "teamId": "team-ledger-sys",
                "workflowRunId": run_id,
                "sourceCollectionRunId": "sc-ledger-1",
                "protocolId": "plan-from-artifact",
                "planId": "plan-from-artifact",
                "status": "frozen",
                "protocolDraftHash": "3" * 64,
                "protocolReviewHash": "4" * 64,
                "protocol": {
                    "planId": "plan-from-artifact",
                    "dataset": "ds",
                    "baseline": "bl",
                    "metric": "macro_f1",
                    "seed": 42,
                    "stop_condition": "max rounds",
                    "hypothesisPortfolioId": "challenge-sci-096",
                    "hypothesisRefs": ["H1"],
                },
            },
        )
        put_workflow_artifact(
            "team-ledger-sys",
            kind="smoke_release",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="human-gate:ht-smoke",
            payload={
                "teamId": "team-ledger-sys",
                "workflowRunId": run_id,
                "sourceCollectionRunId": "sc-ledger-1",
                "planId": "plan-from-artifact",
                "smokeRunId": "smoke-1",
                "status": "released",
                "frozenProtocolHash": "b" * 64,
                "smokeEvidenceHash": "c" * 64,
            },
        )
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-controlled-bounded",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-controlled_run-a1",
            node_id="controlled_run",
            attempt=1,
            actor_kind=ActorKind.SYSTEM,
            action_kind="system_action:controlled_run",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        refs, meta = ports.execute_system_action(action=action)
        assert meta.get("planId") == "plan-from-artifact"
        assert str(meta.get("executionId") or "").startswith("exec-")
        assert meta.get("runnerId") == "synthetic_classification_baseline_vs_variant"
        assert refs and refs[0]["kind"] == "run_artifacts"
    finally:
        harness.close()


def test_ledger_ports_controlled_run_still_requires_plan_id_without_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    harness = CommandHarness(tmp_path / "ledger-controlled-missing.sqlite3")
    try:
        run_id = "run-controlled-missing"
        _seed_run_with_snapshot(
            harness,
            run_id=run_id,
            snapshot={
                "snapshotHash": "a" * 64,
                "teamId": "team-ledger-sys",
                "sourceCollectionRunId": "sc-ledger-1",
            },
        )
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-controlled-missing",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-controlled_run-a1",
            node_id="controlled_run",
            attempt=1,
            actor_kind=ActorKind.SYSTEM,
            action_kind="system_action:controlled_run",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        with pytest.raises(RuntimeError, match="controlled_run requires planId"):
            ports.execute_system_action(action=action)
    finally:
        harness.close()


def test_ledger_ports_result_package_execute_system_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    harness = CommandHarness(tmp_path / "ledger-package.sqlite3")
    try:
        run_id = "run-package"
        calls: list[str] = []

        def fake_build_package(record: dict, *, research_ledger: dict) -> dict:
            calls.append(str(record.get("runId") or ""))
            assert research_ledger.get("officialVersion")
            return {
                "packageId": "pkg-ledger-1",
                "factChainHash": "f" * 64,
                "officialVersion": {"versionId": "v-1"},
            }

        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.result_package.build_result_package",
            fake_build_package,
        )
        _seed_run_with_snapshot(
            harness,
            run_id=run_id,
            snapshot={
                "snapshotHash": "a" * 64,
                "teamId": "team-ledger-pkg",
                "resultPackage": {
                    "workflowRecord": {"runId": run_id, "status": "succeeded"},
                    "researchLedger": {"officialVersion": {"versionId": "v-1"}},
                },
            },
        )
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-package",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-result_package-a1",
            node_id="result_package",
            attempt=1,
            actor_kind=ActorKind.SYSTEM,
            action_kind="system_action:result_package",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        refs, meta = ports.execute_system_action(action=action)
        assert calls == [run_id]
        assert meta["runnerId"] == "package_builder"
        assert meta["packageId"] == "pkg-ledger-1"
        assert refs and refs[0]["kind"] == "research_result_package"

        from core.web.services.team_workflow.research_runtime.action_registry import (
            AdapterResult,
        )
        from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
            SystemActionAdapter,
        )

        adapter = SystemActionAdapter(ports, node_id="result_package")
        result = AdapterResult(
            action_id=action.action_id,
            outcome="succeeded",
            materialized_refs=tuple(refs),
            anchor={
                "systemActionId": str(meta.get("systemActionId") or action.action_id),
                "actionId": action.action_id,
            },
            usage={"compute": str(meta.get("runnerId") or "")},
            reserved={"reservationId": "res-test", "stageId": "execution_iteration"},
        )
        verified = adapter.verify(action, result)
        assert verified.outcome == "succeeded"
    finally:
        harness.close()


def test_ledger_ports_result_package_bounded_without_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        load_workflow_artifact_payload,
        put_workflow_artifact,
    )

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    harness = CommandHarness(tmp_path / "ledger-package-bounded.sqlite3")
    try:
        run_id = "run-package-bounded"
        _seed_run_with_snapshot(
            harness,
            run_id=run_id,
            snapshot={
                "snapshotHash": "a" * 64,
                "teamId": "team-ledger-sys",
                "sourceCollectionRunId": "sc-ledger-1",
            },
        )
        put_workflow_artifact(
            "team-ledger-sys",
            kind="run_artifacts",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="nr-bounded",
            payload={
                "execution": {
                    "status": "completed",
                    "adapterId": "synthetic_classification_baseline_vs_variant",
                    "runnerMode": "v1_cpu_smoke",
                    "metrics": {"delta": {"macro_f1": 0.02}},
                    "artifactHash": "e" * 64,
                    "formalRunnerUnavailable": (
                        "Experiment plan does not select the formal FashionMNIST multi-seed adapter."
                    ),
                }
            },
        )
        put_workflow_artifact(
            "team-ledger-sys",
            kind="iteration_decision",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="nr-iter",
            payload={
                "decisionId": "decision-stop-1",
                "decisionKind": "stop",
                "kind": "stop",
                "terminalReason": "formal_runner_unavailable",
                "reason": "Formal FashionMNIST runner unavailable after bounded V1 CPU observation.",
                "selectedCandidateRef": "H1",
            },
        )
        put_workflow_artifact(
            "team-ledger-sys",
            kind="version_governance_record",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="nr-gov",
            payload={
                "operation": "stop",
                "status": "official",
                "terminalReason": "formal_runner_unavailable",
                "candidateRef": "H1",
                "versionId": "bounded-v1-cpu",
                "decisionId": "decision-stop-1",
            },
        )
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-package-bounded",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-result_package-a1",
            node_id="result_package",
            attempt=1,
            actor_kind=ActorKind.SYSTEM,
            action_kind="system_action:result_package",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        refs, meta = ports.execute_system_action(action=action)
        assert meta["runnerId"] == "bounded_package_builder"
        assert str(meta["packageId"]).startswith(f"rrp-bounded:{run_id}:")
        assert refs and refs[0]["kind"] == "research_result_package"
        loaded = load_workflow_artifact_payload(
            "research_result_package",
            team_id="team-ledger-sys",
            authority_run_id="sc-ledger-1",
            workflow_run_id=run_id,
        )
        assert loaded is not None
        body = loaded.get("payload") if isinstance(loaded.get("payload"), dict) else loaded
        package = body.get("package") if isinstance(body.get("package"), dict) else body
        assert package["bounded"] is True
        assert package["terminalReason"] == "formal_runner_unavailable"
        assert package["source"] == "bounded_result_package"
        assert "not_a_fashionmnist_scientific_result" in (
            package["deliverables"]["limitations"]["sections"]
        )
    finally:
        harness.close()


def test_ledger_ports_unknown_system_node_still_refuses(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger-unknown-sys.sqlite3")
    try:
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-unknown-sys",
            run_id="run-test",
            node_run_id="nr-run-test-unknown_sys-a1",
            node_id="not_a_system_node",
            attempt=1,
            actor_kind=ActorKind.SYSTEM,
            action_kind="system_action:not_a_system_node",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        with pytest.raises(RuntimeError, match="no system executor wired"):
            ports.execute_system_action(action=action)
    finally:
        harness.close()


def test_ledger_ports_run_smoke_persists_smoke_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """System run_smoke writes smoke_evidence; smoke_gate stays a Human adapter."""
    harness = CommandHarness(tmp_path / "ledger-smoke.sqlite3")
    try:
        run_id = "run-smoke"
        calls: list[tuple[str, str]] = []

        def fake_smoke(team_id: str, plan_id: str, _payload: dict) -> dict:
            calls.append((team_id, plan_id))
            return {
                "status": "passed",
                "smokeRun": {"smokeRunId": "smoke-ledger-1", "status": "passed"},
            }

        monkeypatch.setattr(
            "core.web.services.team_workflow.experiment_api.smoke.run_experiment_smoke_run",
            fake_smoke,
        )
        _seed_run_with_snapshot(
            harness,
            run_id=run_id,
            snapshot={
                "snapshotHash": "a" * 64,
                "teamId": "team-ledger-smoke",
                "smokeGate": {"planId": "plan-smoke-v1"},
            },
        )
        ports = RealDomainPorts(harness.store)

        # Production registry must not register a System adapter for smoke_gate.
        from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
            HumanActionAdapter,
            SystemActionAdapter,
            register_default_adapters,
        )
        from core.web.services.team_workflow.research_runtime.action_registry import (
            ActionRegistry,
        )

        registry = register_default_adapters(ActionRegistry(), ports)
        human = registry.get("human_task:smoke_gate")
        assert isinstance(human, HumanActionAdapter)
        assert registry.get("system_action:smoke_gate") is None

        with pytest.raises(RuntimeError, match="Human gate"):
            ports.execute_system_action(
                action=PendingAction(
                    action_id="act-smoke-forbidden",
                    run_id=run_id,
                    node_run_id=f"nr-{run_id}-smoke_gate-a1",
                    node_id="smoke_gate",
                    attempt=1,
                    actor_kind=ActorKind.SYSTEM,
                    action_kind="system_action:smoke_gate",
                    input_snapshot_hash="a" * 64,
                    input_artifact_refs=(),
                    binding_snapshot_id=None,
                    budget_policy_hash="p-1",
                )
            )

        refs, meta = ports.execute_run_smoke(
            run_id=run_id,
            plan_id="plan-smoke-v1",
            action_id="act-smoke",
        )
        assert calls == [("team-ledger-smoke", "plan-smoke-v1")]
        assert meta["runnerId"] == "smoke_runner"
        assert meta["smokeRunId"] == "smoke-ledger-1"
        assert meta["command"] == "run_smoke"
        assert refs and {item["kind"] for item in refs} == {"smoke_evidence"}
        assert "smoke_release" not in {item["kind"] for item in refs}
        _ = SystemActionAdapter  # ownership boundary documented above
    finally:
        harness.close()


def test_ledger_ports_result_evaluation_writes_bounded_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.research.workflow.contracts.competition_evaluation import (
        CompetitionEvaluationSnapshot,
    )
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        load_workflow_artifact_payload,
        put_workflow_artifact,
    )

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    harness = CommandHarness(tmp_path / "ledger-eval-bounded.sqlite3")
    try:
        run_id = "run-eval-bounded"
        _seed_run_with_snapshot(
            harness,
            run_id=run_id,
            snapshot={
                "snapshotHash": "a" * 64,
                "teamId": "team-ledger-sys",
                "sourceCollectionRunId": "sc-ledger-1",
                "evaluationContract": {"minimumClaimEvidenceCoverage": 0.9},
                "agentBindingSnapshot": [
                    {
                        "nodeId": "result_evaluation",
                        "agentId": "agent-ledger",
                        "roleKey": "experiment_ledger",
                        "snapshotId": "snap:eval",
                    }
                ],
            },
        )
        put_workflow_artifact(
            "team-ledger-sys",
            kind="run_artifacts",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="nr-bounded",
            payload={
                "execution": {
                    "status": "completed",
                    "adapterId": "synthetic_classification_baseline_vs_variant",
                    "runnerId": "synthetic_classification_baseline_vs_variant",
                    "runnerMode": "v1_cpu_smoke",
                    "metrics": {"delta": {"macro_f1": 0.02}},
                    "artifactHash": "e" * 64,
                    "formalRunnerUnavailable": (
                        "Record a passing smoke result before formal full-run preparation."
                    ),
                    "decisionHint": "needs_full_run",
                }
            },
        )
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-eval-bounded",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-result_evaluation-a1",
            node_id="result_evaluation",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id="snap:eval",
            budget_policy_hash="p-1",
        )
        handle = ports.create_agent_task(action=action)
        assert str(handle.task_id).startswith("bounded-eval")
        refs = ports.execute_agent_turn(action=action, handle=handle)
        assert refs and refs[0]["kind"] == "evaluation_report"
        loaded = load_workflow_artifact_payload(
            "evaluation_report",
            team_id="team-ledger-sys",
            authority_run_id="sc-ledger-1",
            workflow_run_id=run_id,
        )
        assert loaded is not None
        body = loaded.get("payload") if isinstance(loaded.get("payload"), dict) else loaded
        assert body["runId"] == run_id
        assert body["blockingWarnings"] == []
        assert body["baseline_comparison"]["delta"]["macro_f1"] == 0.02
        CompetitionEvaluationSnapshot.from_dict(body)
    finally:
        harness.close()


def test_ledger_ports_result_evaluation_bounded_without_agent_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        put_workflow_artifact,
    )

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    harness = CommandHarness(tmp_path / "ledger-eval-unbound.sqlite3")
    try:
        run_id = "run-eval-unbound"
        _seed_run_with_snapshot(
            harness,
            run_id=run_id,
            snapshot={
                "snapshotHash": "a" * 64,
                "teamId": "team-ledger-sys",
                "sourceCollectionRunId": "sc-ledger-1",
                "agentBindingSnapshot": [],
            },
        )
        put_workflow_artifact(
            "team-ledger-sys",
            kind="run_artifacts",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="nr-bounded",
            payload={
                "execution": {
                    "status": "completed",
                    "adapterId": "synthetic_classification_baseline_vs_variant",
                    "runnerMode": "v1_cpu_smoke",
                    "metrics": {"baseline": {"accuracy": 1.0}},
                    "artifactHash": "e" * 64,
                    "formalRunnerUnavailable": (
                        "Experiment plan does not select the formal FashionMNIST multi-seed adapter."
                    ),
                }
            },
        )
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-eval-unbound",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-result_evaluation-a1",
            node_id="result_evaluation",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        handle = ports.create_agent_task(action=action)
        assert str(handle.task_id).startswith("bounded-eval")
        refs = ports.execute_agent_turn(action=action, handle=handle)
        assert refs and refs[0]["kind"] == "evaluation_report"
    finally:
        harness.close()


def test_ledger_ports_result_evaluation_fashion_mnist_formal_without_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        load_workflow_artifact_payload,
        put_workflow_artifact,
    )

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    harness = CommandHarness(tmp_path / "ledger-eval-formal.sqlite3")
    try:
        run_id = "run-eval-formal"
        _seed_run_with_snapshot(
            harness,
            run_id=run_id,
            snapshot={
                "snapshotHash": "a" * 64,
                "teamId": "team-ledger-sys",
                "sourceCollectionRunId": "sc-ledger-1",
                "agentBindingSnapshot": [],
            },
        )
        put_workflow_artifact(
            "team-ledger-sys",
            kind="run_artifacts",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="nr-formal",
            payload={
                "execution": {
                    "status": "completed",
                    "adapterId": "fashion_mnist_predictive_coding_multi_seed",
                    "automaticPromotion": False,
                    "result": {
                        "status": "completed",
                        "aggregate": {"meanAccuracy": 0.41},
                        "logRef": "/tmp/sci096-canvas/out/formal-run-log.json",
                        "boundaries": [
                            "does_not_validate_neural_realism",
                            "not_an_official_competition_submission",
                        ],
                        "automaticPromotion": False,
                    },
                }
            },
        )
        ports = RealDomainPorts(harness.store)
        eval_action = PendingAction(
            action_id="act-eval-formal",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-result_evaluation-a1",
            node_id="result_evaluation",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        handle = ports.create_agent_task(action=eval_action)
        assert str(handle.task_id).startswith("bounded-eval")
        refs = ports.execute_agent_turn(action=eval_action, handle=handle)
        assert refs and refs[0]["kind"] == "evaluation_report"
        report = load_workflow_artifact_payload(
            "evaluation_report",
            team_id="team-ledger-sys",
            authority_run_id="sc-ledger-1",
            workflow_run_id=run_id,
        )
        assert report is not None
        body = report.get("payload") if isinstance(report.get("payload"), dict) else report
        assert body["baseline_comparison"]["meanAccuracy"] == 0.41
        assert "does_not_validate_neural_realism" in body["confidence_bounds"]["boundaries"]
        assert body["confidence_bounds"]["automaticPromotion"] is False

        decision_action = PendingAction(
            action_id="act-iter-formal",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-iteration_decision-a1",
            node_id="iteration_decision",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        decision_handle = ports.create_agent_task(action=decision_action)
        assert str(decision_handle.task_id).startswith("bounded-iter")
        decision_refs = ports.execute_agent_turn(
            action=decision_action, handle=decision_handle
        )
        assert decision_refs and decision_refs[0]["kind"] == "iteration_decision"
        decision = load_workflow_artifact_payload(
            "iteration_decision",
            team_id="team-ledger-sys",
            authority_run_id="sc-ledger-1",
            workflow_run_id=run_id,
        )
        assert decision is not None
        decision_body = (
            decision.get("payload") if isinstance(decision.get("payload"), dict) else decision
        )
        assert decision_body["decisionKind"] == "stop"
        assert decision_body["terminalReason"] == "claim_boundary_no_promotion"
        assert "do not promote" in decision_body["reason"]
    finally:
        harness.close()


def test_result_evaluation_binding_heals_from_sibling_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.real_readiness_context import (
        RealDomainReadinessContext,
    )

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.team_role_source.resolve_team_role_bindings",
        lambda team_id: {},
    )
    harness = CommandHarness(tmp_path / "ledger-eval-sibling.sqlite3")
    try:
        run_id = "run-eval-sibling"
        _seed_run_with_snapshot(
            harness,
            run_id=run_id,
            snapshot={
                "snapshotHash": "a" * 64,
                "teamId": "research-team",
                "agentBindingSnapshot": [
                    {
                        "nodeId": "source_finding",
                        "agentId": "agent-unrelated-search",
                        "roleKey": "source_finder",
                        "snapshotId": "snap:unrelated",
                    },
                    {
                        "nodeId": "source_finding",
                        "agentId": "agent-conflicting-owner",
                        "roleKey": "experiment_ledger",
                        "snapshotId": "snap:conflicting-owner",
                    },
                    {
                        "nodeId": "protocol_review",
                        "agentId": "agent-from-freeze",
                        "roleKey": "protocol_reviewer",
                        "snapshotId": "snap:review",
                    },
                    {
                        "nodeId": "result_evaluation",
                        "agentId": "",
                        "roleKey": "experiment_ledger",
                        "snapshotId": "snap:empty",
                    },
                ],
            },
        )
        context = RealDomainReadinessContext(harness.store)
        binding = context.binding_snapshot(run_id, "result_evaluation")
        assert binding is not None
        assert binding["agentId"] == "agent-from-freeze"
        assert binding["resolvedFrom"] == "sibling_freeze"
        ports = RealDomainPorts(harness.store)
        resolved = ports.resolve_binding(
            PendingAction(
                action_id="act-sibling",
                run_id=run_id,
                node_run_id=f"nr-{run_id}-result_evaluation-a1",
                node_id="result_evaluation",
                attempt=1,
                actor_kind=ActorKind.AGENT,
                action_kind="start_agent_task",
                input_snapshot_hash="a" * 64,
                input_artifact_refs=(),
                binding_snapshot_id=None,
                budget_policy_hash="p-1",
            )
        )
        assert resolved.agent_id == "agent-from-freeze"
    finally:
        harness.close()


def test_system_capability_binding_does_not_heal_from_product_sibling() -> None:
    from core.web.services.team_workflow.research_runtime.team_role_source import (
        heal_agent_binding_from_sibling_freeze,
    )

    snapshot = {
        "agentBindingSnapshot": [
            {
                "nodeId": "source_finding",
                "agentId": "agent-search",
                "roleKey": "source_finder",
                "snapshotId": "snap:search",
            }
        ]
    }

    assert (
        heal_agent_binding_from_sibling_freeze(snapshot, "version_governance")
        is None
    )


def test_result_evaluation_binding_heals_empty_freeze_from_team_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.real_readiness_context import (
        RealDomainReadinessContext,
    )

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.team_role_source.resolve_team_role_bindings",
        lambda team_id: {"experiment_ledger": "agent-from-canvas"},
    )
    harness = CommandHarness(tmp_path / "ledger-eval-heal.sqlite3")
    try:
        run_id = "run-eval-heal"
        _seed_run_with_snapshot(
            harness,
            run_id=run_id,
            snapshot={
                "snapshotHash": "a" * 64,
                "teamId": "research-team",
                "agentBindingSnapshot": [
                    {
                        "nodeId": "result_evaluation",
                        "agentId": "",
                        "roleKey": "experiment_ledger",
                        "snapshotId": "snap:empty",
                    }
                ],
            },
        )
        context = RealDomainReadinessContext(harness.store)
        binding = context.binding_snapshot(run_id, "result_evaluation")
        assert binding is not None
        assert binding["agentId"] == "agent-from-canvas"
        ports = RealDomainPorts(harness.store)
        resolved = ports.resolve_binding(
            PendingAction(
                action_id="act-heal",
                run_id=run_id,
                node_run_id=f"nr-{run_id}-result_evaluation-a1",
                node_id="result_evaluation",
                attempt=1,
                actor_kind=ActorKind.AGENT,
                action_kind="start_agent_task",
                input_snapshot_hash="a" * 64,
                input_artifact_refs=(),
                binding_snapshot_id=None,
                budget_policy_hash="p-1",
            )
        )
        assert resolved.agent_id == "agent-from-canvas"
    finally:
        harness.close()


def test_ledger_ports_iteration_decision_writes_stop_from_bounded_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.research.workflow.iteration_decisions import validate_decision_payload
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        load_workflow_artifact_payload,
        put_workflow_artifact,
    )

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    harness = CommandHarness(tmp_path / "ledger-iter-bounded.sqlite3")
    try:
        run_id = "run-iter-bounded"
        snapshot = {
            "snapshotHash": "a" * 64,
            "teamId": "team-ledger-sys",
            "sourceCollectionRunId": "sc-ledger-1",
            "questionId": "SCI-096",
            "evaluationContract": {"minimumClaimEvidenceCoverage": 0.9},
            "agentBindingSnapshot": [
                {
                    "nodeId": "result_evaluation",
                    "agentId": "agent-ledger",
                    "roleKey": "experiment_ledger",
                    "snapshotId": "snap:eval",
                },
                {
                    "nodeId": "iteration_decision",
                    "agentId": "agent-iter",
                    "roleKey": "iteration_planner",
                    "snapshotId": "snap:iter",
                },
                {
                    "nodeId": "version_governance",
                    "agentId": "agent-gov",
                    "roleKey": "version_governor",
                    "snapshotId": "snap:gov",
                },
            ],
        }
        _seed_run_with_snapshot(harness, run_id=run_id, snapshot=snapshot)
        put_workflow_artifact(
            "team-ledger-sys",
            kind="run_artifacts",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="nr-bounded",
            payload={
                "execution": {
                    "status": "completed",
                    "adapterId": "synthetic_classification_baseline_vs_variant",
                    "runnerMode": "v1_cpu_smoke",
                    "metrics": {"delta": {"macro_f1": 0.02}},
                    "artifactHash": "e" * 64,
                    "formalRunnerUnavailable": (
                        "Record a passing smoke result before formal full-run preparation."
                    ),
                    "decisionHint": "needs_full_run",
                }
            },
        )
        put_workflow_artifact(
            "team-ledger-sys",
            kind="frozen_protocol",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="ht-freeze",
            payload={
                "protocolId": "exp-plan-1",
                "planId": "exp-plan-1",
                "protocol": {"planId": "exp-plan-1", "hypothesisRefs": ["H1"]},
            },
        )
        ports = RealDomainPorts(harness.store)
        eval_action = PendingAction(
            action_id="act-eval-then-iter",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-result_evaluation-a1",
            node_id="result_evaluation",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id="snap:eval",
            budget_policy_hash="p-1",
        )
        ports.execute_agent_turn(
            action=eval_action,
            handle=ports.create_agent_task(action=eval_action),
        )
        action = PendingAction(
            action_id="act-iter-bounded",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-iteration_decision-a1",
            node_id="iteration_decision",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id="snap:iter",
            budget_policy_hash="p-1",
        )
        handle = ports.create_agent_task(action=action)
        assert str(handle.task_id).startswith("bounded-iter")
        refs = ports.execute_agent_turn(action=action, handle=handle)
        assert refs and refs[0]["kind"] == "iteration_decision"
        loaded = load_workflow_artifact_payload(
            "iteration_decision",
            team_id="team-ledger-sys",
            authority_run_id="sc-ledger-1",
            workflow_run_id=run_id,
        )
        assert loaded is not None
        body = loaded.get("payload") if isinstance(loaded.get("payload"), dict) else loaded
        assert body["decisionKind"] == "stop"
        assert body["selectedCandidateRef"] == "H1"
        validate_decision_payload(body)
        gov_action = PendingAction(
            action_id="act-gov-bounded",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-version_governance-a1",
            node_id="version_governance",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id="snap:gov",
            budget_policy_hash="p-1",
        )
        gov_handle = ports.create_agent_task(action=gov_action)
        assert str(gov_handle.task_id).startswith("bounded-gov")
        gov_refs = ports.execute_agent_turn(action=gov_action, handle=gov_handle)
        assert gov_refs and gov_refs[0]["kind"] == "version_governance_record"
        gov_loaded = load_workflow_artifact_payload(
            "version_governance_record",
            team_id="team-ledger-sys",
            authority_run_id="sc-ledger-1",
            workflow_run_id=run_id,
        )
        assert gov_loaded is not None
        gov_body = (
            gov_loaded.get("payload")
            if isinstance(gov_loaded.get("payload"), dict)
            else gov_loaded
        )
        assert gov_body["operation"] == "stop"
        assert gov_body["status"] == "official"
        assert gov_body["candidateRef"] == "H1"
        assert gov_body["decisionId"] == body["decisionId"]
        again = ports.execute_agent_turn(action=action, handle=handle)
        assert again and again[0]["kind"] == "iteration_decision"
        replayed = load_workflow_artifact_payload(
            "iteration_decision",
            team_id="team-ledger-sys",
            authority_run_id="sc-ledger-1",
            workflow_run_id=run_id,
        )
        replayed_body = (
            replayed.get("payload")
            if isinstance(replayed, dict) and isinstance(replayed.get("payload"), dict)
            else replayed
        )
        assert replayed_body["decidedAt"] == body["decidedAt"]
        assert replayed_body["decisionId"] == body["decisionId"]
    finally:
        harness.close()


def test_bounded_version_governance_without_decision_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        put_workflow_artifact,
    )

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    harness = CommandHarness(tmp_path / "ledger-gov-empty.sqlite3")
    try:
        run_id = "run-gov-empty"
        snapshot = {
            "snapshotHash": "a" * 64,
            "teamId": "team-ledger-sys",
            "sourceCollectionRunId": "sc-ledger-1",
            "questionId": "SCI-096",
        }
        _seed_run_with_snapshot(harness, run_id=run_id, snapshot=snapshot)
        put_workflow_artifact(
            "team-ledger-sys",
            kind="run_artifacts",
            workflow_run_id=run_id,
            source_collection_run_id="sc-ledger-1",
            artifact_identity="nr-bounded",
            payload={
                "execution": {
                    "status": "completed",
                    "adapterId": "synthetic_classification_baseline_vs_variant",
                    "runnerMode": "v1_cpu_smoke",
                    "formalRunnerUnavailable": "Record a passing smoke result first.",
                }
            },
        )
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-gov-empty",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-version_governance-a1",
            node_id="version_governance",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id="snap:gov",
            budget_policy_hash="p-1",
        )
        handle = ports.create_agent_task(action=action)
        assert str(handle.task_id).startswith("bounded-gov")
        with pytest.raises(RuntimeError, match="produced no artifact refs"):
            ports.execute_agent_turn(action=action, handle=handle)
    finally:
        harness.close()
