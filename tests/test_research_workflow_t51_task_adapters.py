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


def test_ledger_ports_result_package_execute_system_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
