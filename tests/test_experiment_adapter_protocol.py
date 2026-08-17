"""Protocol-layer tests for the D06 ExperimentAdapter surface.

Covers the five-state outcome, the canonical lifecycle order, the explicit
scope/contract/locator binding, the fail-closed controlled locator and the
bounded evidence receipt / result round trips.
"""

from __future__ import annotations

import pytest

from core.research.experiment_adapters import (
    AdapterContractError,
    AdapterError,
    BoundedEvidenceReceipt,
    ControlledLocator,
    ExperimentAdapter,
    ExperimentContract,
    ExperimentOutcome,
    ExperimentResult,
    LIFECYCLE_STAGES,
    LocatorValidationError,
    OfflineFakeExperimentAdapter,
    phase_result,
)
from core.research.workflow.contracts import ResearchScopeEnvelope

VALID_ENVELOPE = {
    "program": "XH-202619",
    "theme": "cc-gpu-operator-001",
    "campaign": "cc-campaign-gpu-operator-001",
    "question": "SCI-091",
    "branch": "main",
    "workflow": "hypothesis_and_plan",
    "agentId": "agent-alpha",
    "mode": "formal",
    "scopeHash": "a" * 64,
    "artifactLocator": f"research-artifact://XH-202619/{'a' * 64}",
    "ledgerRoot": f"research-ledger://XH-202619/{'a' * 64}",
    "cacheKey": f"scope:{'a' * 64}:main:agent-alpha",
}


def _scope() -> ResearchScopeEnvelope:
    return ResearchScopeEnvelope.from_dict(VALID_ENVELOPE)


def test_five_terminal_outcomes_are_defined() -> None:
    values = {outcome.value for outcome in ExperimentOutcome}
    assert values == {"completed", "partial", "failed", "unavailable", "rejected"}


def test_lifecycle_order_is_canonical() -> None:
    assert LIFECYCLE_STAGES == (
        "prepare",
        "validate",
        "execute",
        "collect",
        "evaluate",
        "emit_receipt",
    )


def test_adapter_is_a_runtime_checkable_protocol() -> None:
    assert isinstance(OfflineFakeExperimentAdapter(), ExperimentAdapter)
    assert isinstance(_scope(), ExperimentAdapter) is False


def test_phase_result_normalizes_status_and_rejects_unknown() -> None:
    assert phase_result("OK", value=1) == {"status": "ok", "value": 1}
    assert phase_result("partial") == {"status": "partial"}
    with pytest.raises(AdapterError):
        phase_result("boom")


def test_contract_requires_identity_fields_and_hashes_payload() -> None:
    payload = {
        "schemaVersion": 2,
        "planId": "plan-1",
        "teamId": "team-1",
        "experimentMethod": "model_training_inference",
        "researchQuestion": "question",
    }
    contract = ExperimentContract.from_payload(payload)
    assert contract.planId == "plan-1"
    assert contract.teamId == "team-1"
    assert contract.methodId == "model_training_inference"
    assert len(contract.contentHash) == 64

    repeated = ExperimentContract.from_payload(payload)
    assert repeated.contentHash == contract.contentHash
    changed = ExperimentContract.from_payload({**payload, "researchQuestion": "other"})
    assert changed.contentHash != contract.contentHash

    for missing in ("planId", "teamId", "experimentMethod"):
        with pytest.raises(AdapterContractError):
            ExperimentContract.from_payload({key: value for key, value in payload.items() if key != missing})


@pytest.mark.parametrize(
    "unsafe",
    [
        "/abs/path",
        "C:\\Users\\evil\\run",
        "\\\\server\\share\\run",
        "..",
        "sub/../../escape",
        "sub\\..\\escape",
        "dir/$HOME/x",
        "dir/%VAR%/x",
        "dir; rm -rf /",
        "dir|cmd",
        "dir`cmd`",
        "dir & cmd",
        "dir$(cmd)",
        "sub//double",
        "trailing/",
        "bad:chars",
    ],
)
def test_controlled_locator_fails_closed_on_unsafe_paths(unsafe: str) -> None:
    with pytest.raises(LocatorValidationError):
        ControlledLocator(kind="offline", relativePath=unsafe)


def test_controlled_locator_kind_is_bounded() -> None:
    assert ControlledLocator(kind="offline", relativePath="seed-1").kind == "offline"
    assert ControlledLocator(kind="workspace_relative", relativePath="a/b/result.json").relativePath == "a/b/result.json"
    with pytest.raises(LocatorValidationError):
        ControlledLocator(kind="arbitrary", relativePath="seed-1")
    with pytest.raises(LocatorValidationError):
        ControlledLocator.from_dict({"kind": "offline", "relativePath": "../../etc/passwd"})


def test_controlled_locator_detects_max_depth_exceeded() -> None:
    with pytest.raises(LocatorValidationError):
        ControlledLocator(kind="offline", relativePath="a/b/c/d", maxDepth=2)


def test_receipt_and_result_round_trip() -> None:
    receipt = BoundedEvidenceReceipt(
        receiptId="r1",
        outcome=ExperimentOutcome.COMPLETED,
        stage="emit_receipt",
        evidenceHash="e" * 64,
        artifactCount=3,
        logBytes=128,
        maxArtifacts=64,
        maxLogBytes=8192,
        boundaries=("no_process", "no_gpu", "no_network", "offline_only"),
        payload=(("evidenceHash", "e" * 64),),
    )
    result = ExperimentResult(
        resultId="res-1",
        idempotencyKey="key-1",
        scopeHash="a" * 64,
        contractHash="b" * 64,
        adapterId="offline_fake",
        adapterVersion="1.0.0",
        outcome=ExperimentOutcome.COMPLETED,
        stages=LIFECYCLE_STAGES,
        stage="emit_receipt",
        phases=LIFECYCLE_STAGES,
        message="",
        metrics=(("units", 3),),
        receipt=receipt,
        boundaries=("no_process", "no_gpu", "no_network"),
        reused=False,
    )
    round_tripped = ExperimentResult(
        **{key: value for key, value in result.to_dict().items() if key != "receipt"},
        receipt=receipt,
    )
    assert round_tripped.to_dict() == result.to_dict()
    assert receipt.to_dict()["outcome"] == "completed"