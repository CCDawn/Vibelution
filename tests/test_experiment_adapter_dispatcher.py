"""Dispatcher-layer tests for the D06 fail-closed experiment dispatcher.

Covers the explicit registry, the static fail-closed rejection of unknown
adapters / unsafe locators / executable contract fields, the scopeHash-based
idempotency key with reuse and conflict rejection, and the offline fake
adapter lifecycle (completed / partial / failed / unavailable) without any
process, GPU or network usage.
"""

from __future__ import annotations

import pytest

from core.research.experiment_adapters import (
    AdapterContractError,
    BoundedEvidenceReceipt,
    ControlledLocator,
    DispatcherError,
    ExperimentContract,
    ExperimentDispatcher,
    ExperimentOutcome,
    ExperimentResult,
    LocatorValidationError,
    OfflineFakeExperimentAdapter,
    idempotency_key,
    scan_for_executable_fields,
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


def _scope(scope_hash: str = "a" * 64) -> ResearchScopeEnvelope:
    return ResearchScopeEnvelope.from_dict({**VALID_ENVELOPE, "scopeHash": scope_hash})


def _contract(**overrides) -> ExperimentContract:
    payload = {
        "schemaVersion": 2,
        "planId": "plan-1",
        "teamId": "team-1",
        "experimentMethod": "model_training_inference",
        "researchQuestion": "offline fake question",
        "methodConfig": {"dataset": "synthetic", "seeds": [1, 2, 3]},
        "metricContract": {"primaryMetric": "macro_f1", "metrics": [{"name": "macro_f1"}]},
    }
    payload.update(overrides)
    return ExperimentContract.from_payload(payload)


def _locator(relative_path: str = "offline/seed-1") -> ControlledLocator:
    return ControlledLocator(kind="offline", relativePath=relative_path)


def test_unknown_adapter_fails_closed() -> None:
    dispatcher = ExperimentDispatcher()
    result = dispatcher.dispatch(
        scope=_scope(), contract=_contract(), locator=_locator(), adapter_id="no_such_adapter"
    )
    assert result.outcome is ExperimentOutcome.REJECTED
    assert result.phases == ()
    assert result.stage == "rejected"
    assert result.receipt.artifactCount == 0
    assert dict(result.receipt.payload)["reason"] == "unknown_adapter"


def test_duplicate_and_invalid_registrations_fail_closed() -> None:
    dispatcher = ExperimentDispatcher()
    with pytest.raises(DispatcherError, match="duplicate"):
        dispatcher.register(OfflineFakeExperimentAdapter())

    with pytest.raises(DispatcherError, match="adapter id"):
        dispatcher.register(object())

    class MissingMethods:
        adapterId = "broken"
        adapterVersion = "1.0.0"

    with pytest.raises(DispatcherError, match="lifecycle"):
        dispatcher.register(MissingMethods())


def test_unsafe_locator_is_rejected_at_construction() -> None:
    for unsafe in ("C:\\Users\\evil\\run", "/abs/run", "sub/../../escape", "dir; rm -rf", "dir|cmd"):
        with pytest.raises(LocatorValidationError):
            ControlledLocator(kind="offline", relativePath=unsafe)


def test_contract_executable_fields_fail_closed() -> None:
    assert scan_for_executable_fields({"command": "run.sh"})
    assert scan_for_executable_fields({"methodConfig": {"pythonExecutable": "python"}})
    assert scan_for_executable_fields({"methodConfig": {"seedCommands": ["a", "b"]}})
    assert not scan_for_executable_fields(
        {"methodConfig": {"dataset": "synthetic", "seeds": [1, 2, 3]}}
    )

    dispatcher = ExperimentDispatcher()
    rejected = dispatcher.dispatch(
        scope=_scope(),
        contract=_contract(methodConfig={"command": "rm -rf /"}),
        locator=_locator(),
        adapter_id="offline_fake",
    )
    assert rejected.outcome is ExperimentOutcome.REJECTED
    assert "fails closed" in rejected.message


def test_contract_absolute_path_and_traversal_fail_closed() -> None:
    dispatcher = ExperimentDispatcher()
    absolute = dispatcher.dispatch(
        scope=_scope(),
        contract=_contract(methodConfig={"dataset": "C:\\Users\\evil\\data"}),
        locator=_locator(),
        adapter_id="offline_fake",
    )
    assert absolute.outcome is ExperimentOutcome.REJECTED
    assert "absolute path" in absolute.message

    traversal = dispatcher.dispatch(
        scope=_scope(),
        contract=_contract(methodConfig={"dataset": "../etc/passwd"}),
        locator=_locator(),
        adapter_id="offline_fake",
    )
    assert traversal.outcome is ExperimentOutcome.REJECTED
    assert "traversal" in traversal.message


def test_full_scope_hash_participates_in_idempotency_key() -> None:
    same = idempotency_key(_scope("b" * 64), _locator())
    assert same == idempotency_key(_scope("b" * 64), _locator())
    different_scope = idempotency_key(_scope("c" * 64), _locator())
    different_locator = idempotency_key(_scope("b" * 64), _locator("offline/seed-9"))
    assert same != different_scope
    assert same != different_locator


def test_same_key_same_contract_is_reused_stably() -> None:
    fake = OfflineFakeExperimentAdapter()
    dispatcher = ExperimentDispatcher(adapters=[fake])
    first = dispatcher.dispatch(
        scope=_scope(), contract=_contract(), locator=_locator(), adapter_id="offline_fake"
    )
    second = dispatcher.dispatch(
        scope=_scope(), contract=_contract(), locator=_locator(), adapter_id="offline_fake"
    )
    assert first.outcome is ExperimentOutcome.COMPLETED
    assert second.reused is True
    assert second.resultId == first.resultId
    assert second.idempotencyKey == first.idempotencyKey
    assert fake.calls == list(("prepare", "validate", "execute", "collect", "evaluate", "emit_receipt"))


def test_conflicting_payload_on_same_key_is_rejected() -> None:
    dispatcher = ExperimentDispatcher()
    dispatcher.dispatch(scope=_scope(), contract=_contract(), locator=_locator(), adapter_id="offline_fake")
    conflict = dispatcher.dispatch(
        scope=_scope(),
        contract=_contract(researchQuestion="conflicting payload"),
        locator=_locator(),
        adapter_id="offline_fake",
    )
    assert conflict.outcome is ExperimentOutcome.REJECTED
    assert dict(conflict.receipt.payload)["reason"] == "idempotency_conflict"


@pytest.mark.parametrize(
    ("mode", "expected", "expected_phases"),
    [
        ("completed", ExperimentOutcome.COMPLETED, ("prepare", "validate", "execute", "collect", "evaluate", "emit_receipt")),
        ("partial", ExperimentOutcome.PARTIAL, ("prepare", "validate", "execute", "collect", "evaluate", "emit_receipt")),
        ("failed", ExperimentOutcome.FAILED, ("prepare", "validate")),
        ("unavailable", ExperimentOutcome.UNAVAILABLE, ("prepare",)),
    ],
)
def test_fake_adapter_outcomes_and_lifecycle_order(mode, expected, expected_phases) -> None:
    fake = OfflineFakeExperimentAdapter(mode=mode, failed_units=1 if mode == "partial" else 0)
    dispatcher = ExperimentDispatcher(adapters=[fake])
    result = dispatcher.dispatch(
        scope=_scope(), contract=_contract(), locator=_locator(), adapter_id="offline_fake"
    )
    assert result.outcome is expected
    assert result.phases == expected_phases
    assert tuple(fake.calls) == expected_phases
    assert set(result.receipt.boundaries) >= {"no_process", "no_gpu", "no_network"}
    assert result.receipt.artifactCount <= result.receipt.maxArtifacts
    assert result.receipt.logBytes <= result.receipt.maxLogBytes
    assert "no_process" in result.boundaries


def test_fake_adapter_partial_reports_failed_units() -> None:
    fake = OfflineFakeExperimentAdapter(mode="partial", unit_count=4, failed_units=2)
    dispatcher = ExperimentDispatcher(adapters=[fake])
    result = dispatcher.dispatch(
        scope=_scope(), contract=_contract(), locator=_locator(), adapter_id="offline_fake"
    )
    assert result.outcome is ExperimentOutcome.PARTIAL
    metrics = dict(result.metrics)
    assert metrics["failedUnits"] == 2
    assert metrics["okUnits"] == 2


def test_fake_adapter_never_starts_process_gpu_or_network() -> None:
    fake = OfflineFakeExperimentAdapter()
    dispatcher = ExperimentDispatcher(adapters=[fake])
    result = dispatcher.dispatch(
        scope=_scope(), contract=_contract(), locator=_locator(), adapter_id="offline_fake"
    )
    assert isinstance(result.receipt, BoundedEvidenceReceipt)
    assert {"no_process", "no_gpu", "no_network"} <= set(result.receipt.boundaries)
    assert {"no_process", "no_gpu", "no_network"} <= set(result.boundaries)


def test_receipt_bounds_are_enforced_by_dispatcher() -> None:
    dispatcher = ExperimentDispatcher(max_log_bytes=16, max_artifacts=2, max_receipt_items=1)
    result = dispatcher.dispatch(
        scope=_scope(), contract=_contract(), locator=_locator(), adapter_id="offline_fake"
    )
    assert result.receipt.maxLogBytes == 16
    assert result.receipt.logBytes <= 16
    assert result.receipt.maxArtifacts == 2
    assert result.receipt.artifactCount <= 2
    assert len(result.receipt.payload) <= 1