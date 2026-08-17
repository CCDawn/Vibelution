"""D08 neural spike DEV fixture adapter tests.

Tracked scripts must be present; DANDI downloads, ignored imports and real
neural claims are forbidden.  GPU-operator scope must not be accepted.
"""

from __future__ import annotations

from core.research.experiment_adapters import (
    ControlledLocator,
    ExperimentContract,
    ExperimentOutcome,
    challenge_cup_dispatcher,
)
from core.research.workflow.contracts import ResearchScopeEnvelope

NEURAL_ENVELOPE = {
    "program": "XH-202619",
    "theme": "cc-neural-information-001",
    "campaign": "cc-campaign-neural-spike-001",
    "question": "SCI-096",
    "branch": "main",
    "workflow": "hypothesis_and_plan",
    "agentId": "agent-alpha",
    "mode": "dev",
    "scopeHash": "b" * 64,
    "artifactLocator": f"research-artifact://XH-202619/{'b' * 64}",
    "ledgerRoot": f"research-ledger://XH-202619/{'b' * 64}",
    "cacheKey": f"scope:{'b' * 64}:main:agent-alpha",
}

GPU_ENVELOPE = {
    **NEURAL_ENVELOPE,
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
        "planId": "plan-neural",
        "teamId": "team-1",
        "experimentMethod": "dataset_analysis_benchmark",
        "researchQuestion": "SCI-096 fixture",
        "methodConfig": {"runMode": "dev_fixture", "dataset": "synthetic"},
        "metricContract": {"primaryMetric": "fixture_score", "metrics": [{"name": "fixture_score"}]},
    }
    payload.update(overrides)
    return ExperimentContract.from_payload(payload)


def _locator(relative_path: str = "offline/neural-fixture") -> ControlledLocator:
    return ControlledLocator(kind="offline", relativePath=relative_path)


def test_neural_fixture_completes_without_dandi_or_scientific_claim() -> None:
    dispatcher = challenge_cup_dispatcher()
    result = dispatcher.dispatch(
        scope=_scope(NEURAL_ENVELOPE),
        contract=_contract(),
        locator=_locator(),
        adapter_id="neural_spike_coding",
    )
    assert result.outcome is ExperimentOutcome.COMPLETED
    assert dict(result.metrics)["scientificClaim"] is False
    assert dict(result.metrics)["dandiDownloaded"] is False
    assert "no_dandi_download" in result.receipt.boundaries
    assert dict(result.receipt.payload)["ignoredImport"] is False


def test_neural_require_dandi_is_unavailable() -> None:
    dispatcher = challenge_cup_dispatcher()
    result = dispatcher.dispatch(
        scope=_scope(NEURAL_ENVELOPE),
        contract=_contract(methodConfig={"runMode": "dev_fixture", "requireDandiAsset": True, "dataset": "synthetic"}),
        locator=_locator("offline/neural-dandi"),
        adapter_id="neural_spike_coding",
    )
    assert result.outcome is ExperimentOutcome.UNAVAILABLE


def test_neural_adapter_rejects_gpu_scope() -> None:
    dispatcher = challenge_cup_dispatcher()
    result = dispatcher.dispatch(
        scope=_scope(GPU_ENVELOPE),
        contract=_contract(),
        locator=_locator("offline/neural-cross"),
        adapter_id="neural_spike_coding",
    )
    assert result.outcome is ExperimentOutcome.FAILED
    assert "scope_mismatch" in result.message
