"""D06 FashionMNIST compatibility adapter tests.

The trusted script stays unexecuted.  GPU-operator scope is rejected so the
compatibility adapter cannot leak into the independent operator experiment.
"""

from __future__ import annotations

from core.research.experiment_adapters import (
    ControlledLocator,
    ExperimentContract,
    ExperimentOutcome,
    challenge_cup_dispatcher,
)
from core.research.workflow.contracts import ResearchScopeEnvelope

COMPAT_ENVELOPE = {
    "program": "XH-202619",
    "theme": "cc-fashion-mnist-001",
    "campaign": "cc-campaign-fashion-mnist-001",
    "question": "SCI-031",
    "branch": "main",
    "workflow": "hypothesis_and_plan",
    "agentId": "agent-alpha",
    "mode": "dev",
    "scopeHash": "c" * 64,
    "artifactLocator": f"research-artifact://XH-202619/{'c' * 64}",
    "ledgerRoot": f"research-ledger://XH-202619/{'c' * 64}",
    "cacheKey": f"scope:{'c' * 64}:main:agent-alpha",
}

GPU_ENVELOPE = {
    **COMPAT_ENVELOPE,
    "theme": "cc-gpu-operator-001",
    "campaign": "cc-campaign-gpu-operator-001",
    "question": "SCI-091",
    "scopeHash": "a" * 64,
}


def _scope(payload: dict) -> ResearchScopeEnvelope:
    return ResearchScopeEnvelope.from_dict(payload)


def _contract(**overrides) -> ExperimentContract:
    payload = {
        "schemaVersion": 2,
        "planId": "plan-fashion",
        "teamId": "team-1",
        "experimentMethod": "model_training_inference",
        "researchQuestion": "fashion mnist fixture",
        "methodConfig": {"runMode": "dev_fixture", "dataset": "synthetic"},
        "metricContract": {"primaryMetric": "mse", "metrics": [{"name": "mse"}]},
    }
    payload.update(overrides)
    return ExperimentContract.from_payload(payload)


def _locator(relative_path: str = "offline/fashion-fixture") -> ControlledLocator:
    return ControlledLocator(kind="offline", relativePath=relative_path)


def test_fashion_mnist_fixture_does_not_train() -> None:
    dispatcher = challenge_cup_dispatcher()
    result = dispatcher.dispatch(
        scope=_scope(COMPAT_ENVELOPE),
        contract=_contract(),
        locator=_locator(),
        adapter_id="fashion_mnist_predictive_coding_multi_seed",
    )
    assert result.outcome is ExperimentOutcome.COMPLETED
    assert dict(result.metrics)["trained"] is False
    assert "no_training" in result.receipt.boundaries


def test_fashion_mnist_training_flag_is_unavailable() -> None:
    dispatcher = challenge_cup_dispatcher()
    result = dispatcher.dispatch(
        scope=_scope(COMPAT_ENVELOPE),
        contract=_contract(methodConfig={"runMode": "dev_fixture", "requireTraining": True, "dataset": "synthetic"}),
        locator=_locator("offline/fashion-train"),
        adapter_id="fashion_mnist_predictive_coding_multi_seed",
    )
    assert result.outcome is ExperimentOutcome.UNAVAILABLE


def test_fashion_mnist_rejects_gpu_operator_scope() -> None:
    dispatcher = challenge_cup_dispatcher()
    result = dispatcher.dispatch(
        scope=_scope(GPU_ENVELOPE),
        contract=_contract(),
        locator=_locator("offline/fashion-cross"),
        adapter_id="fashion_mnist_predictive_coding_multi_seed",
    )
    assert result.outcome is ExperimentOutcome.FAILED
    assert "scope_mismatch" in result.message
