"""D07 GPU operator DEV fixture adapter tests.

No CUDA, subprocess, or network is used.  Correctness-first fixture flow,
unavailable real-device path, and isolation from the neural campaign are
the only behaviors under test.
"""

from __future__ import annotations

from core.research.experiment_adapters import (
    ControlledLocator,
    ExperimentContract,
    ExperimentOutcome,
    GpuOperatorFixtureAdapter,
    challenge_cup_dispatcher,
)
from core.research.workflow.contracts import ResearchScopeEnvelope

GPU_ENVELOPE = {
    "program": "XH-202619",
    "theme": "cc-gpu-operator-001",
    "campaign": "cc-campaign-gpu-operator-001",
    "question": "SCI-091",
    "branch": "main",
    "workflow": "hypothesis_and_plan",
    "agentId": "agent-alpha",
    "mode": "dev",
    "scopeHash": "a" * 64,
    "artifactLocator": f"research-artifact://XH-202619/{'a' * 64}",
    "ledgerRoot": f"research-ledger://XH-202619/{'a' * 64}",
    "cacheKey": f"scope:{'a' * 64}:main:agent-alpha",
}

NEURAL_ENVELOPE = {
    **GPU_ENVELOPE,
    "theme": "cc-neural-information-001",
    "campaign": "cc-campaign-neural-spike-001",
    "question": "SCI-096",
    "scopeHash": "b" * 64,
}


def _scope(payload: dict) -> ResearchScopeEnvelope:
    return ResearchScopeEnvelope.from_dict(payload)


def _contract(**overrides) -> ExperimentContract:
    payload = {
        "schemaVersion": 2,
        "planId": "plan-gpu",
        "teamId": "team-1",
        "experimentMethod": "computational_kernel_benchmark",
        "researchQuestion": "SCI-091 fixture",
        "methodConfig": {"runMode": "dev_fixture", "dataset": "synthetic"},
        "metricContract": {"primaryMetric": "correctness", "metrics": [{"name": "correctness"}]},
    }
    payload.update(overrides)
    return ExperimentContract.from_payload(payload)


def _locator(relative_path: str = "offline/gpu-fixture") -> ControlledLocator:
    return ControlledLocator(kind="offline", relativePath=relative_path)


def test_gpu_fixture_completes_correctness_first_without_performance_claim() -> None:
    dispatcher = challenge_cup_dispatcher()
    result = dispatcher.dispatch(
        scope=_scope(GPU_ENVELOPE),
        contract=_contract(),
        locator=_locator(),
        adapter_id="gpu_operator_benchmark",
    )
    assert result.outcome is ExperimentOutcome.COMPLETED
    assert result.adapterId == "gpu_operator_benchmark"
    assert dict(result.metrics)["performanceClaimed"] is False
    assert "no_gpu" in result.boundaries
    assert "no_performance_claim" in result.receipt.boundaries
    assert dict(result.receipt.payload)["device"] == "cpu_fixture"


def test_gpu_require_cuda_is_unavailable_not_success() -> None:
    dispatcher = challenge_cup_dispatcher()
    result = dispatcher.dispatch(
        scope=_scope(GPU_ENVELOPE),
        contract=_contract(methodConfig={"runMode": "dev_fixture", "requireCuda": True, "dataset": "synthetic"}),
        locator=_locator("offline/gpu-cuda"),
        adapter_id="gpu_operator_benchmark",
    )
    assert result.outcome is ExperimentOutcome.UNAVAILABLE
    assert "research_authorization_required" in result.message or result.receipt.payload


def test_gpu_full_run_is_unavailable() -> None:
    dispatcher = challenge_cup_dispatcher()
    result = dispatcher.dispatch(
        scope=_scope(GPU_ENVELOPE),
        contract=_contract(methodConfig={"runMode": "full", "dataset": "synthetic"}),
        locator=_locator("offline/gpu-full"),
        adapter_id="gpu_operator_benchmark",
    )
    assert result.outcome is ExperimentOutcome.UNAVAILABLE


def test_gpu_adapter_rejects_neural_scope() -> None:
    dispatcher = challenge_cup_dispatcher()
    result = dispatcher.dispatch(
        scope=_scope(NEURAL_ENVELOPE),
        contract=_contract(),
        locator=_locator("offline/gpu-cross"),
        adapter_id="gpu_operator_benchmark",
    )
    assert result.outcome is ExperimentOutcome.FAILED
    assert "scope_mismatch" in result.message


def test_default_dispatcher_does_not_register_gpu_adapter() -> None:
    from core.research.experiment_adapters import ExperimentDispatcher

    dispatcher = ExperimentDispatcher()
    result = dispatcher.dispatch(
        scope=_scope(GPU_ENVELOPE),
        contract=_contract(),
        locator=_locator("offline/gpu-default"),
        adapter_id="gpu_operator_benchmark",
    )
    assert result.outcome is ExperimentOutcome.REJECTED
    assert GpuOperatorFixtureAdapter.adapterId == "gpu_operator_benchmark"
