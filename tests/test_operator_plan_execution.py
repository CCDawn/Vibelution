"""Frozen plan to real trial receipts, without starting a GPU process."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.research.operator_optimization.candidate import source_hash
from core.research.operator_optimization.evaluation import workload_hash
from core.research.operator_optimization.measurement import OperatorMeasurement
from core.research.workflow.contracts._canonical import sha256_hex
from core.web.services.team_workflow.operator_optimization import (
    dispatch,
    execution,
    planning_output,
)
from core.web.services.team_workflow.operator_optimization.store import (
    CampaignConflict,
    read_campaign,
)
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    _execute_real_system_action,
)
from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
    read_domain_artifact,
)
from tests import test_operator_planning as fixtures
from tests._support.workflow_ledger_helpers import (
    build_attempt_record,
    build_command_record,
)

activity = fixtures.activity
baseline_ready = fixtures.baseline_ready
ready = fixtures.ready
discussion_case = fixtures.discussion_case
handoff = fixtures.handoff
proposal = fixtures.proposal


@pytest.fixture
def prepared(activity, proposal, handoff, monkeypatch):
    run_id, output = proposal
    _, _, store = handoff
    planning_output.materialize_optimization_plan(
        activity[0], run_id, output.model_copy(update={"trialCount": 2})
    )
    store.submit(
        lambda u: u.repository.insert_command(
            build_command_record(run_id=run_id, command_id="execution-command")
        ),
        force_flush=True,
    ).result()
    store.submit(
        lambda u: u.repository.insert_attempt(
            build_attempt_record(
                "execution-one",
                run_id=run_id,
                node_id="operator_execution",
                status="running",
                command_id="execution-command",
            )
        ),
        force_flush=True,
    ).result()
    monkeypatch.setattr(execution, "get_write_store", lambda: store)
    action = SimpleNamespace(
        run_id=run_id,
        node_run_id="execution-one",
        node_id="operator_execution",
        action_id="execute",
    )
    snapshot = json.loads(store.get_run(run_id).input_snapshot_json)
    calls = []

    def execute(request, **kwargs):
        calls.append(request)
        return OperatorMeasurement(
            measurementId=request.measurement_id,
            optimizationCampaignId=request.campaign_id,
            runId=request.run_id,
            protocolHash=sha256_hex(request.protocol.model_dump(mode="json")),
            workloadHash=workload_hash(request.protocol),
            environmentHash=request.expected_environment_hash,
            baselineSourceHash=source_hash(request.baseline),
            parentSourceHash=source_hash(request.parent),
            candidateSourceHash=source_hash(request.candidate),
            deviceName="fixture",
            status="failed",
            failureReason="controlled compilation failure",
            gpuSeconds=2,
        )

    monkeypatch.setattr(dispatch, "execute_cuda_trial", execute)
    return action, snapshot, calls, store


def test_real_system_dispatch_returns_all_receipts_and_replays_once(activity, prepared):
    action, snapshot, calls, _ = prepared
    refs, meta = _execute_real_system_action(
        action, input_snapshot=snapshot, required_kinds=("operator_measurement",)
    )
    assert len(refs) == len(calls) == 2
    assert meta["runnerId"] == "operator_cuda_v1"
    assert len({r["sha256"] for r in refs}) == 2
    assert all(read_domain_artifact(r["canonicalRef"]) is not None for r in refs)
    assert all(c.candidate.numWarps == 8 and c.max_seconds == 30 for c in calls)
    assert execution.execute_plan(action, snapshot) == refs
    assert len(calls) == 2
    reservations = read_campaign(*activity).gpuReservations
    assert len(reservations) == 2
    assert all(r.outcome == "failed" and r.consumedSeconds == 2 for r in reservations)


def test_partial_delivery_recovers_completed_trials(activity, prepared, monkeypatch):
    action, snapshot, calls, _ = prepared
    real = execution.dispatch_trial
    attempts = []

    def interrupted(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 2:
            raise RuntimeError("before second admission")
        return real(*args, **kwargs)

    monkeypatch.setattr(execution, "dispatch_trial", interrupted)
    with pytest.raises(RuntimeError, match="second admission"):
        execution.execute_plan(action, snapshot)
    assert len(calls) == 1
    monkeypatch.setattr(execution, "dispatch_trial", real)
    assert len(execution.execute_plan(action, snapshot)) == 2
    assert len(calls) == 2


def test_stale_attempt_and_wrong_scope_do_not_execute(prepared):
    action, snapshot, calls, store = prepared
    with pytest.raises(CampaignConflict, match="locator"):
        execution.execute_plan(action, snapshot | {"projectId": "other"})
    store.submit(
        lambda u: u.repository.execute(
            "UPDATE node_attempts SET finished_at_ms=123 WHERE node_run_id=?",
            (action.node_run_id,),
        ),
        force_flush=True,
    ).result()
    with pytest.raises(CampaignConflict, match="active operator"):
        execution.execute_plan(action, snapshot)
    assert calls == []


def test_missing_environment_does_not_admit_trial(prepared, monkeypatch):
    action, snapshot, calls, _ = prepared
    monkeypatch.setattr(execution, "load_scoped_artifact_payload", lambda *a, **k: None)
    with pytest.raises(CampaignConflict, match="environment"):
        execution.execute_plan(action, snapshot)
    assert calls == []


def test_native_system_adapter_verifies_all_trial_receipts(prepared):
    from core.research.workflow.models import ActorKind
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        SystemActionAdapter,
    )
    from core.web.services.team_workflow.research_runtime.real_domain_ports import (
        RealDomainPorts,
    )
    from tests.test_research_workflow_agent_anchor import _agent_action

    simple, _, calls, store = prepared
    action = replace(
        _agent_action(),
        run_id=simple.run_id,
        node_run_id=simple.node_run_id,
        node_id="operator_execution",
        actor_kind=ActorKind.SYSTEM,
        input_snapshot_hash="",
    )
    adapter = SystemActionAdapter(RealDomainPorts(store))
    result = adapter.execute(action)
    assert len(result.materialized_refs) == len(calls) == 2
    assert adapter.verify(action, result).outcome == "succeeded"
