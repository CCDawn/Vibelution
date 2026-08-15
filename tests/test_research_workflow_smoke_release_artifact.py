"""Smoke human decisions require passed evidence and one canonical release."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.web.services.team_workflow.research_runtime.command_service import (
    WorkflowCommandError,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
)


def _seed_smoke_gate(
    harness: CommandHarness,
    *,
    historical_accept: bool = False,
) -> None:
    run = replace(
        build_run_record(
            last_event_sequence=1,
            status="blocked" if historical_accept else "running",
        ),
        active_node_id="controlled_run" if historical_accept else "smoke_gate",
        input_snapshot_json=json.dumps(
            {
                "snapshotHash": "a" * 64,
                "sourceCollectionRunId": "sc-run-1",
            }
        ),
        blocked_problem_json=(
            json.dumps({"code": "formal_run_not_released"})
            if historical_accept
            else None
        ),
    )
    smoke_attempt = replace(
        build_attempt_record(
            node_run_id="nr-run-test-smoke_gate-a1",
            node_id="smoke_gate",
            actor_kind="human",
            status="succeeded" if historical_accept else "waiting_human",
            command_id="cmd-smoke-a1",
        ),
        pending_action_id="act-smoke-human",
        finished_at_ms=FIXED_NOW_MS if historical_accept else None,
    )

    def mutate(uow):
        uow.repository.insert_run(run)
        uow.repository.insert_event(
            build_event_record(sequence=1, event_id="evt-created-run-test")
        )
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-smoke-a1",
                command_kind="start_node",
                node_id="smoke_gate",
            )
        )
        uow.repository.insert_attempt(smoke_attempt)
        uow.repository.insert_handoff(
            handoff_id="ho-smoke-controlled",
            run_id="run-test",
            edge_id="e-smoke-controlled",
            from_node_run_id=smoke_attempt.node_run_id,
            to_node_id="controlled_run",
            to_node_run_id=None,
            gate_kind="human",
            input_snapshot_hash="a" * 64,
            offered_at_ms=FIXED_NOW_MS,
        )
        uow.repository.update_handoff_status(
            "ho-smoke-controlled",
            "waiting_human",
            FIXED_NOW_MS,
        )
        if historical_accept:
            uow.repository.update_handoff_status(
                "ho-smoke-controlled",
                "accepted",
                FIXED_NOW_MS,
            )
        uow.repository.insert_human_task(
            task_id="ht-smoke",
            run_id="run-test",
            node_run_id=smoke_attempt.node_run_id,
            handoff_id="ho-smoke-controlled",
            task_kind="gate:smoke_gate",
            prompt_json='{"nodeId":"smoke_gate"}',
            created_at_ms=FIXED_NOW_MS,
        )
        if historical_accept:
            uow.repository.update_human_task_decision(
                "ht-smoke",
                "accepted",
                FIXED_NOW_MS,
                decision_json='{"decision":"accept"}',
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-controlled-a1",
                    command_kind="start_node",
                    node_id="controlled_run",
                    idempotency_key="seed-controlled",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-run-test-controlled_run-a1",
                    node_id="controlled_run",
                    actor_kind="system",
                    status="blocked",
                    command_id="cmd-controlled-a1",
                    problem_json=json.dumps({"code": "formal_run_not_released"}),
                )
            )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _authority_state() -> dict[str, dict[str, object] | None]:
    return {
        "frozen_protocol": {
            "teamId": "research-team",
            "kind": "frozen_protocol",
            "workflowRunId": "run-test",
            "sourceCollectionRunId": "sc-run-1",
            "payload": {
                "planId": "exp-plan-1",
                "protocolId": "exp-plan-1",
                "status": "frozen",
            },
        },
        "smoke_evidence": None,
    }


def _install_smoke_authority(
    monkeypatch: pytest.MonkeyPatch,
    state: dict[str, dict[str, object] | None],
) -> tuple[list[dict[str, object]], list[str]]:
    writes: list[dict[str, object]] = []
    executions: list[str] = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime."
        "smoke_release_artifact.load_scoped_artifact_payload",
        lambda kind, **kwargs: state.get(kind),
    )

    def execute_smoke(*, store, run, plan_id, handoff_id):
        executions.append(plan_id)
        state["smoke_evidence"] = {
            "teamId": run.team_id,
            "kind": "smoke_evidence",
            "workflowRunId": run.run_id,
            "sourceCollectionRunId": "sc-run-1",
            "payload": {
                "planId": plan_id,
                "smokeRunId": "smoke-1",
                "status": "passed",
                "artifactHash": "f" * 64,
            },
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime."
        "smoke_release_artifact._execute_smoke_observation",
        execute_smoke,
    )

    def capture_put(team_id: str, **kwargs):
        writes.append({"teamId": team_id, **kwargs})
        return {"recordId": kwargs["artifact_identity"], "payload": kwargs["payload"]}

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime."
        "smoke_release_artifact.put_workflow_artifact",
        capture_put,
    )
    return writes, executions


def test_smoke_accept_executes_observation_then_binds_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_smoke_gate(harness)
        state = _authority_state()
        writes, executions = _install_smoke_authority(monkeypatch, state)

        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                node_id="smoke_gate",
                expected_run_version=1,
                idempotency_key="ui:accept-smoke",
                payload={"taskId": "ht-smoke", "decision": "accept"},
            )
        )

        assert receipt.status == "accepted"
        assert executions == ["exp-plan-1"]
        assert len(writes) == 1 and writes[0]["kind"] == "smoke_release"
        release = writes[0]["payload"]
        assert isinstance(release, dict)
        assert release["planId"] == "exp-plan-1"
        assert release["smokeRunId"] == "smoke-1"
        assert release["decision"] == "accept"
        assert release["resolvedBy"] == "u-1"
        refs = harness.store.read(
            lambda repo: repo.list_handoff_artifact_refs_for_run("run-test")
        )
        assert len(refs) == 1 and refs[0][2] == "smoke_release"
    finally:
        harness.close()


def test_smoke_failure_keeps_human_task_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_smoke_gate(harness)
        state = _authority_state()
        writes, _ = _install_smoke_authority(monkeypatch, state)

        def failed_smoke(**kwargs):
            state["smoke_evidence"] = {
                "payload": {
                    "planId": "exp-plan-1",
                    "smokeRunId": "smoke-failed",
                    "status": "failed",
                }
            }

        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime."
            "smoke_release_artifact._execute_smoke_observation",
            failed_smoke,
        )

        with pytest.raises(WorkflowCommandError, match="smoke_evidence_not_passed"):
            harness.service.submit(
                harness.request(
                    command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                    node_id="smoke_gate",
                    expected_run_version=1,
                    idempotency_key="ui:accept-failed-smoke",
                    payload={"taskId": "ht-smoke", "decision": "accept"},
                )
            )

        assert writes == []
        task = harness.store.read(lambda repo: repo.get_human_task("ht-smoke"))
        assert task is not None and task[6] == "pending"
    finally:
        harness.close()


def test_smoke_accept_releases_needs_review_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_smoke_gate(harness)
        state = _authority_state()
        state["smoke_evidence"] = {
            "teamId": "research-team",
            "kind": "smoke_evidence",
            "workflowRunId": "run-test",
            "sourceCollectionRunId": "sc-run-1",
            "payload": {
                "planId": "exp-plan-1",
                "smokeRunId": "smoke-1",
                "status": "needs_review",
                "artifactHash": "f" * 64,
            },
        }
        writes, executions = _install_smoke_authority(monkeypatch, state)

        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                node_id="smoke_gate",
                expected_run_version=1,
                idempotency_key="ui:accept-needs-review-smoke",
                payload={"taskId": "ht-smoke", "decision": "accept"},
            )
        )

        assert receipt.status == "accepted"
        assert executions == []
        assert len(writes) == 1 and writes[0]["kind"] == "smoke_release"
        assert writes[0]["payload"]["smokeRunId"] == "smoke-1"
    finally:
        harness.close()


def test_smoke_accept_fails_closed_without_release_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_smoke_gate(harness)
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime."
            "command_service.prepare_command_human_acceptance_artifact",
            lambda **kwargs: None,
        )

        with pytest.raises(
            WorkflowCommandError,
            match="gate:smoke_gate accept requires a materialized artifact receipt",
        ):
            harness.service.submit(
                harness.request(
                    command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                    node_id="smoke_gate",
                    expected_run_version=1,
                    idempotency_key="ui:accept-missing-smoke-release",
                    payload={"taskId": "ht-smoke", "decision": "accept"},
                )
            )

        task = harness.store.read(lambda repo: repo.get_human_task("ht-smoke"))
        assert task is not None and task[6] == "pending"
        refs = harness.store.read(
            lambda repo: repo.list_handoff_artifact_refs_for_run("run-test")
        )
        assert refs == []
    finally:
        harness.close()


def test_controlled_retry_recovers_historical_smoke_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_smoke_gate(harness, historical_accept=True)
        state = _authority_state()
        writes, executions = _install_smoke_authority(monkeypatch, state)

        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RETRY_NODE,
                node_id="controlled_run",
                expected_run_version=1,
                idempotency_key="ui:retry-controlled-with-smoke-release",
            )
        )

        assert receipt.status == "accepted"
        assert executions == ["exp-plan-1"]
        assert len(writes) == 1 and writes[0]["kind"] == "smoke_release"
        latest = harness.store.latest_attempt("run-test", "controlled_run")
        assert latest is not None and latest.attempt == 2
        assert latest.status == "starting"
    finally:
        harness.close()


def _frozen_protocol_body() -> dict[str, object]:
    return {
        "planId": "exp-plan-20260813211108-fdb104ea",
        "protocolId": "exp-plan-20260813211108-fdb104ea",
        "status": "frozen",
        "protocol": {
            "dataset": "dataset-sci-096-v1",
            "metric": "stimulus decoding accuracy",
            "baseline": "two-layer decoder",
            "smoke_plan": {
                "phase": "smoke_gate",
                "required": ["subset 1000 trials"],
            },
        },
    }


def test_bind_frozen_protocol_creates_plan_in_empty_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_workflow_orchestration_service as twos
    from core.web.services.team_workflow.experiment_api.plan import (
        bind_frozen_protocol_to_experiment_plan,
    )

    store_path = tmp_path / "experiment_plans" / "index.json"
    monkeypatch.setattr(twos, "_experiment_plan_store_path", lambda team_id: store_path)

    bound = bind_frozen_protocol_to_experiment_plan(
        "research-team",
        _frozen_protocol_body(),
    )
    assert bound["planId"] == "exp-plan-20260813211108-fdb104ea"
    assert bound["designGate"]["status"] == "frozen"
    assert bound["experimentPlan"]["smokePlan"]["phase"] == "smoke_gate"

    reloaded = twos._load_experiment_plan_store("research-team")
    plan = next(
        item
        for item in reloaded["plans"]
        if item["planId"] == "exp-plan-20260813211108-fdb104ea"
    )
    twos._require_explicit_experiment_design_frozen(plan)
    experiment_plan = plan["experimentPlan"]
    for field in twos.EXPERIMENT_PLAN_REQUIRED_FIELDS:
        assert twos._has_value(experiment_plan.get(field)), field
    selection = plan["experimentContract"]["adapterSelection"]
    assert (
        selection["resolvedAdapterId"]
        == twos.formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER
    )
    assert plan["contractValidation"]["valid"] is True


def test_bind_frozen_protocol_freezes_draft_and_fills_smoke_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_workflow_orchestration_service as twos
    from core.web.services.team_workflow.experiment_api.plan import (
        bind_frozen_protocol_to_experiment_plan,
    )

    store_path = tmp_path / "experiment_plans" / "index.json"
    monkeypatch.setattr(twos, "_experiment_plan_store_path", lambda team_id: store_path)
    twos._write_json(
        store_path,
        {
            "schemaVersion": twos.SCHEMA_VERSION,
            "teamId": "research-team",
            "storeKind": twos.EXPERIMENT_PLAN_STORE_KIND,
            "activePlanId": "exp-plan-20260813211108-fdb104ea",
            "plans": [
                {
                    "planId": "exp-plan-20260813211108-fdb104ea",
                    "teamId": "research-team",
                    "status": "draft",
                    "experimentPlan": {
                        "dataset": "",
                        "metric": "",
                        "baseline": "",
                        "smokePlan": "",
                    },
                    "designGate": {"status": "draft"},
                }
            ],
            "createdAt": "2026-08-13T00:00:00+00:00",
            "updatedAt": "2026-08-13T00:00:00+00:00",
        },
    )

    bind_frozen_protocol_to_experiment_plan("research-team", _frozen_protocol_body())
    plan = twos._find_experiment_plan(
        twos._load_experiment_plan_store("research-team"),
        "exp-plan-20260813211108-fdb104ea",
    )
    assert plan is not None
    twos._require_explicit_experiment_design_frozen(plan)
    assert plan["status"] == "design_frozen"
    assert plan["experimentPlan"]["smokePlan"]["required"] == ["subset 1000 trials"]
    assert plan["experimentPlan"]["dataset"] == "dataset-sci-096-v1"
    assert (
        plan["experimentContract"]["adapterSelection"]["resolvedAdapterId"]
        == twos.formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER
    )
    assert plan["contractValidation"]["valid"] is True


def test_execute_smoke_observation_binds_plan_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_workflow_orchestration_service as twos
    from core.web.services.team_workflow.research_runtime import smoke_release_artifact as sra

    store_path = tmp_path / "experiment_plans" / "index.json"
    monkeypatch.setattr(twos, "_experiment_plan_store_path", lambda team_id: store_path)
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime."
        "smoke_release_artifact.load_scoped_artifact_payload",
        lambda kind, **kwargs: {
            "frozen_protocol": {
                "payload": _frozen_protocol_body(),
            }
        }.get(kind),
    )

    seen: list[dict[str, object]] = []

    class FakePorts:
        def __init__(self, store: object) -> None:
            self.store = store

        def execute_run_smoke(self, **kwargs: object) -> None:
            plan = twos._find_experiment_plan(
                twos._load_experiment_plan_store("research-team"),
                "exp-plan-20260813211108-fdb104ea",
            )
            assert plan is not None
            twos._require_explicit_experiment_design_frozen(plan)
            assert twos._has_value(plan["experimentPlan"].get("smokePlan"))
            seen.append(kwargs)

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.real_domain_ports.RealDomainPorts",
        FakePorts,
    )
    run = replace(
        build_run_record(),
        input_snapshot_json=json.dumps({"sourceCollectionRunId": "sc-run-1"}),
    )
    sra._execute_smoke_observation(
        store=object(),
        run=run,
        plan_id="exp-plan-20260813211108-fdb104ea",
        handoff_id="ho-1",
    )
    assert seen and seen[0]["plan_id"] == "exp-plan-20260813211108-fdb104ea"
