"""Fail-closed ExperimentAdapter dispatcher and offline fake adapter (D06).

The dispatcher owns an explicit adapter registry.  A request is statically
rejected (outcome ``rejected``) before any adapter phase runs when:

* the adapter id is unknown, or the registry is asked to register a duplicate
  or an adapter missing lifecycle methods,
* the controlled locator is absolute, drive-qualified or contains traversal,
  environment or shell metacharacters (already rejected at construction),
* the contract payload carries an executable/command/path field, or
* a later request reuses an idempotency key with a conflicting contract.

Idempotency: the full ``scopeHash`` participates in the key together with the
controlled locator.  A repeated (key, contract) pair is served from the result
registry; a conflicting contract on the same key is rejected fail-closed.

The bundled ``OfflineFakeExperimentAdapter`` is the only adapter shipped in
this batch: deterministic, in-memory, and it never starts a process, GPU or
network connection.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from ..workflow.contracts import ResearchScopeEnvelope, sha256_hex
from .protocol import (
    AdapterContractError,
    AdapterError,
    AdapterUnavailableError,
    BoundedEvidenceReceipt,
    ControlledLocator,
    ExperimentAdapter,
    ExperimentContract,
    ExperimentOutcome,
    ExperimentResult,
    LIFECYCLE_STAGES,
    phase_result,
)

DEFAULT_MAX_LOG_BYTES = 8192
DEFAULT_MAX_ARTIFACTS = 64
DEFAULT_MAX_RECEIPT_ITEMS = 128

_ADAPTER_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_EXECUTABLE_KEYS = frozenset(
    {
        "command",
        "commands",
        "cmd",
        "shell",
        "shellcommand",
        "shellcmd",
        "executable",
        "executables",
        "pythonexecutable",
        "pythonpath",
        "interpreter",
        "script",
        "scriptpath",
        "scriptcontents",
        "binary",
        "argv",
        "args",
        "launcher",
        "entrypoint",
        "spawn",
        "subprocess",
    }
)

_EXECUTABLE_KEY_SUFFIXES = (
    "command",
    "commands",
    "cmd",
    "shell",
    "executable",
    "interpreter",
    "script",
    "binary",
    "argv",
    "args",
    "launcher",
)

_SHELL_TOKEN_RE = re.compile(r"[;&|`]")
_ABSOLUTE_PATH_RE = re.compile(r"^[/\\]|[A-Za-z]:[/\\]")
_TRAVERSAL_RE = re.compile(r"(^|[/\\])\.\.([/\\]|$)")
_ENV_REFERENCE_RE = re.compile(r"[$%]")

_FAKE_MODES = ("completed", "partial", "failed", "unavailable")


class DispatcherError(AdapterError):
    """The dispatcher registry or a dispatch request is malformed."""


def idempotency_key(scope: ResearchScopeEnvelope, locator: ControlledLocator) -> str:
    """Idempotency key over the full scopeHash and the controlled locator.

    The contract content hash is deliberately excluded so that a conflicting
    payload on the same (scope, locator) is detected and rejected instead of
    silently producing a second, unrelated result.
    """
    return sha256_hex({"scopeHash": scope.scopeHash, "locator": locator.to_dict()})


def scan_for_executable_fields(payload: Any) -> list[str]:
    """Recursively scan a payload for executable/command/path fields.

    Returns a list of human-readable violations; an empty list means the
    payload is considered safe for the offline dispatcher.  The scan is
    intentionally aggressive: anything that looks like a command, an
    executable, an absolute path, a traversal or a shell token fails closed.
    """
    violations: list[str] = []
    _scan_value(payload, "contract", violations)
    return violations


class ExperimentDispatcher:
    """Fail-closed, idempotent dispatcher over an explicit adapter registry."""

    def __init__(
        self,
        *,
        adapters: Iterable[ExperimentAdapter] | None = None,
        max_log_bytes: int = DEFAULT_MAX_LOG_BYTES,
        max_artifacts: int = DEFAULT_MAX_ARTIFACTS,
        max_receipt_items: int = DEFAULT_MAX_RECEIPT_ITEMS,
    ) -> None:
        self._registry: dict[str, ExperimentAdapter] = {}
        self._results: dict[str, dict[str, Any]] = {}
        self._max_log_bytes = int(max_log_bytes)
        self._max_artifacts = int(max_artifacts)
        self._max_receipt_items = int(max_receipt_items)
        if self._max_log_bytes < 1 or self._max_artifacts < 1 or self._max_receipt_items < 1:
            raise DispatcherError("dispatcher bounds must be positive integers.")
        sources = list(adapters) if adapters is not None else [OfflineFakeExperimentAdapter()]
        for adapter in sources:
            self.register(adapter)

    def register(self, adapter: Any) -> None:
        adapter_id = str(getattr(adapter, "adapterId", "") or "").strip()
        if not _ADAPTER_ID_RE.fullmatch(adapter_id):
            raise DispatcherError(f"invalid adapter id: {adapter_id!r}")
        if adapter_id in self._registry:
            raise DispatcherError(f"duplicate adapter registration: {adapter_id}")
        version = str(getattr(adapter, "adapterVersion", "") or "").strip()
        if not version:
            raise DispatcherError(f"adapter {adapter_id} must declare adapterVersion.")
        missing = [stage for stage in LIFECYCLE_STAGES if not callable(getattr(adapter, stage, None))]
        if missing:
            raise DispatcherError(f"adapter {adapter_id} is missing lifecycle methods: {', '.join(missing)}")
        self._registry[adapter_id] = adapter

    def adapters(self) -> tuple[str, ...]:
        return tuple(sorted(self._registry))

    def adapter_count(self) -> int:
        return len(self._registry)

    def dispatch(
        self,
        *,
        scope: ResearchScopeEnvelope,
        contract: ExperimentContract,
        locator: ControlledLocator,
        adapter_id: str,
    ) -> ExperimentResult:
        if not isinstance(scope, ResearchScopeEnvelope):
            raise DispatcherError("scope must be a ResearchScopeEnvelope.")
        if not isinstance(contract, ExperimentContract):
            raise DispatcherError("contract must be an ExperimentContract.")
        if not isinstance(locator, ControlledLocator):
            raise DispatcherError("locator must be a ControlledLocator.")

        key = idempotency_key(scope, locator)
        normalized_adapter_id = str(adapter_id or "").strip()
        adapter = self._registry.get(normalized_adapter_id)
        if adapter is None:
            return self._rejected_result(
                key=key,
                scope=scope,
                contract=contract,
                adapter_id=normalized_adapter_id,
                message=f"unknown adapter: {adapter_id!r}",
                reason="unknown_adapter",
            )

        violations = scan_for_executable_fields(contract.to_dict())
        if violations:
            return self._rejected_result(
                key=key,
                scope=scope,
                contract=contract,
                adapter_id=adapter.adapterId,
                message="contract fails closed: " + "; ".join(violations),
                reason="contract_fail_closed",
            )

        cached = self._results.get(key)
        if cached is not None:
            if cached["contractHash"] == contract.contentHash and cached["adapterId"] == adapter.adapterId:
                return replace(cached["result"], reused=True)
            return self._rejected_result(
                key=key,
                scope=scope,
                contract=contract,
                adapter_id=adapter.adapterId,
                message="idempotency key reused with a conflicting contract or adapter payload.",
                reason="idempotency_conflict",
            )

        result = self._run_pipeline(adapter, scope, contract, locator, key)
        self._results[key] = {"contractHash": contract.contentHash, "adapterId": adapter.adapterId, "result": result}
        return result

    def _run_pipeline(
        self,
        adapter: ExperimentAdapter,
        scope: ResearchScopeEnvelope,
        contract: ExperimentContract,
        locator: ControlledLocator,
        key: str,
    ) -> ExperimentResult:
        state: dict[str, dict[str, Any]] = {}
        phases: list[str] = []
        outcome = ExperimentOutcome.COMPLETED
        message = ""
        partial_seen = False
        current_stage = LIFECYCLE_STAGES[0]
        try:
            for stage in LIFECYCLE_STAGES:
                current_stage = stage
                output = _invoke_stage(adapter, stage, scope, contract, locator, state)
                status = str(output.get("status") or "ok").strip().lower()
                phases.append(stage)
                if status == "unavailable":
                    outcome = ExperimentOutcome.UNAVAILABLE
                    message = str(output.get("reason") or "adapter unavailable")
                    break
                if status == "failed":
                    outcome = ExperimentOutcome.FAILED
                    message = str(output.get("reason") or f"{stage} failed")
                    break
                if status == "partial":
                    partial_seen = True
                state[stage] = output
        except AdapterUnavailableError as exc:
            outcome = ExperimentOutcome.UNAVAILABLE
            message = str(exc)
            phases.append(current_stage)
        except (AdapterError, ValueError, TypeError) as exc:
            outcome = ExperimentOutcome.FAILED
            message = f"{current_stage} raised {type(exc).__name__}: {exc}"
            phases.append(current_stage)
        except Exception as exc:  # defensive fail-closed
            outcome = ExperimentOutcome.FAILED
            message = f"{current_stage} raised unexpected {type(exc).__name__}: {exc}"
            phases.append(current_stage)

        if outcome is ExperimentOutcome.COMPLETED and partial_seen:
            outcome = ExperimentOutcome.PARTIAL

        evaluated = state.get("emit_receipt") or {}
        metrics = evaluated.get("metrics") if isinstance(evaluated.get("metrics"), Mapping) else {}
        receipt = self._build_receipt(
            scope=scope,
            contract=contract,
            outcome=outcome,
            stage=current_stage if phases else "rejected",
            evaluated=evaluated,
            message=message,
        )
        boundaries = _result_boundaries(evaluated)
        result = ExperimentResult(
            resultId=sha256_hex(
                {"idempotencyKey": key, "outcome": outcome.value, "phases": list(phases)}
            ),
            idempotencyKey=key,
            scopeHash=scope.scopeHash,
            contractHash=contract.contentHash,
            adapterId=adapter.adapterId,
            adapterVersion=adapter.adapterVersion,
            outcome=outcome,
            stages=LIFECYCLE_STAGES,
            stage=current_stage if phases else "rejected",
            phases=tuple(phases),
            message=message,
            metrics=tuple(sorted(metrics.items())),
            receipt=receipt,
            boundaries=boundaries,
            reused=False,
        )
        return result

    def _build_receipt(
        self,
        *,
        scope: ResearchScopeEnvelope,
        contract: ExperimentContract,
        outcome: ExperimentOutcome,
        stage: str,
        evaluated: dict[str, Any],
        message: str,
    ) -> BoundedEvidenceReceipt:
        raw_artifact_count = _nonnegative_int(evaluated.get("artifactCount"), default=0)
        raw_log_bytes = _nonnegative_int(evaluated.get("logBytes"), default=0)
        artifact_count = min(raw_artifact_count, self._max_artifacts)
        log_bytes = min(raw_log_bytes, self._max_log_bytes)

        payload_items: list[tuple[str, Any]] = []
        raw_payload = evaluated.get("payload")
        if isinstance(raw_payload, Mapping):
            items = sorted(raw_payload.items())
        elif isinstance(raw_payload, Sequence) and not isinstance(raw_payload, (str, bytes)):
            items = [("item", item) for item in raw_payload]
        else:
            items = []
        for index, (name, value) in enumerate(items):
            if index >= self._max_receipt_items:
                break
            payload_items.append((str(name), copy.deepcopy(value)))
        if not payload_items and message:
            payload_items.append(("message", message))

        evidence_hash = str(evaluated.get("evidenceHash") or "").strip()
        if not evidence_hash or len(evidence_hash) < 8:
            evidence_hash = _fallback_evidence_hash(scope, contract, outcome, stage)
        receipt_id = sha256_hex(
            {
                "scopeHash": scope.scopeHash,
                "contractHash": contract.contentHash,
                "outcome": outcome.value,
                "stage": stage,
            }
        )
        return BoundedEvidenceReceipt(
            receiptId=receipt_id,
            outcome=outcome,
            stage=stage,
            evidenceHash=evidence_hash,
            artifactCount=artifact_count,
            logBytes=log_bytes,
            maxArtifacts=self._max_artifacts,
            maxLogBytes=self._max_log_bytes,
            boundaries=tuple(_result_boundaries(evaluated)),
            payload=tuple(payload_items),
        )

    def _rejected_result(
        self,
        *,
        key: str,
        scope: ResearchScopeEnvelope,
        contract: ExperimentContract,
        adapter_id: str,
        message: str,
        reason: str,
    ) -> ExperimentResult:
        outcome = ExperimentOutcome.REJECTED
        stage = "rejected"
        evidence_hash = _fallback_evidence_hash(scope, contract, outcome, stage)
        receipt = BoundedEvidenceReceipt(
            receiptId=sha256_hex(
                {
                    "scopeHash": scope.scopeHash,
                    "contractHash": contract.contentHash,
                    "outcome": outcome.value,
                    "stage": stage,
                }
            ),
            outcome=outcome,
            stage=stage,
            evidenceHash=evidence_hash,
            artifactCount=0,
            logBytes=0,
            maxArtifacts=self._max_artifacts,
            maxLogBytes=self._max_log_bytes,
            boundaries=("no_process", "no_gpu", "no_network", "rejected"),
            payload=(("reason", reason), ("message", message)),
        )
        return ExperimentResult(
            resultId=sha256_hex(
                {"scopeHash": scope.scopeHash, "contractHash": contract.contentHash, "reason": reason}
            ),
            idempotencyKey=key,
            scopeHash=scope.scopeHash,
            contractHash=contract.contentHash,
            adapterId=adapter_id,
            adapterVersion="",
            outcome=outcome,
            stages=LIFECYCLE_STAGES,
            stage=stage,
            phases=(),
            message=message,
            metrics=(),
            receipt=receipt,
            boundaries=("no_process", "no_gpu", "no_network", "rejected"),
            reused=False,
        )


class OfflineFakeExperimentAdapter:
    """Deterministic offline fake adapter that never starts a process/GPU/network.

    Demonstrates the unified lifecycle ordering and the ``partial``/``failed``/
    ``unavailable`` terminal outcomes using in-memory, CPU-free, network-free
    data.  No files are written and no subprocess is spawned.
    """

    adapterId = "offline_fake"
    adapterVersion = "1.0.0"
    methodId = "model_training_inference"

    def __init__(self, *, mode: str = "completed", unit_count: int = 3, failed_units: int = 0) -> None:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in _FAKE_MODES:
            raise AdapterContractError(f"unsupported fake mode: {mode!r}")
        try:
            units = int(unit_count)
            failures = int(failed_units)
        except (TypeError, ValueError) as exc:
            raise AdapterContractError("fake unit counts must be integers.") from exc
        if units < 1 or failures < 0 or failures > units:
            raise AdapterContractError("invalid fake unit counts.")
        if normalized_mode == "completed" and failures:
            raise AdapterContractError("completed mode requires failed_units=0.")
        if normalized_mode == "partial" and not failures:
            raise AdapterContractError("partial mode requires at least one failed unit.")
        self.mode = normalized_mode
        self.unit_count = units
        self.failed_units = failures
        self.calls: list[str] = []

    def prepare(self, scope, contract, locator):
        self.calls.append("prepare")
        if self.mode == "unavailable":
            return phase_result("unavailable", adapterId=self.adapterId, reason="offline adapter unavailable")
        return phase_result(
            "ok",
            adapterId=self.adapterId,
            mode=self.mode,
            environment={"process": False, "gpu": False, "network": False},
            units=self.unit_count,
        )

    def validate(self, scope, contract, locator, *, prepared):
        self.calls.append("validate")
        if self.mode == "failed":
            return phase_result("failed", reason="validation failed")
        return phase_result("ok", contractValid=True, adapterId=self.adapterId)

    def execute(self, scope, contract, locator, *, prepared, validated):
        self.calls.append("execute")
        units = [
            {"unit": index, "status": "failed" if index < self.failed_units else "ok"}
            for index in range(self.unit_count)
        ]
        status = "partial" if self.failed_units else "ok"
        return phase_result(
            status,
            units=units,
            okCount=self.unit_count - self.failed_units,
            failedCount=self.failed_units,
        )

    def collect(self, scope, contract, locator, *, executed):
        self.calls.append("collect")
        raw_units = executed.get("units") or []
        artifacts = [
            {"unit": item.get("unit"), "status": item.get("status")}
            for item in raw_units
            if isinstance(item, Mapping)
        ]
        return phase_result("ok", artifacts=artifacts, artifactCount=len(artifacts))

    def evaluate(self, scope, contract, locator, *, collected):
        self.calls.append("evaluate")
        artifacts = collected.get("artifacts") or []
        ok_count = sum(1 for item in artifacts if item.get("status") == "ok")
        failed_count = len(artifacts) - ok_count
        metrics = {
            "units": len(artifacts),
            "okUnits": ok_count,
            "failedUnits": failed_count,
            "partial": failed_count > 0,
        }
        status = "partial" if failed_count else "ok"
        return phase_result(status, metrics=metrics, decisionHint="review" if failed_count else "accept")

    def emit_receipt(self, scope, contract, locator, *, evaluated):
        self.calls.append("emit_receipt")
        metrics = evaluated.get("metrics") if isinstance(evaluated.get("metrics"), Mapping) else {}
        evidence = {
            "scopeHash": scope.scopeHash,
            "contractHash": contract.contentHash,
            "locator": locator.to_dict(),
            "metrics": metrics,
        }
        evidence_hash = sha256_hex(evidence)
        return phase_result(
            "ok",
            evidenceHash=evidence_hash,
            artifactCount=_nonnegative_int(evaluated.get("artifactCount"), default=0),
            logBytes=len(evidence_hash) * 2,
            metrics=metrics,
            payload={"evidenceHash": evidence_hash, "decisionHint": evaluated.get("decisionHint") or ""},
            boundaries=["no_process", "no_gpu", "no_network", "offline_only"],
        )


def _invoke_stage(
    adapter: ExperimentAdapter,
    stage: str,
    scope: ResearchScopeEnvelope,
    contract: ExperimentContract,
    locator: ControlledLocator,
    state: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    method = getattr(adapter, stage)
    if stage == "prepare":
        return method(scope, contract, locator)
    if stage == "validate":
        return method(scope, contract, locator, prepared=state["prepare"])
    if stage == "execute":
        return method(scope, contract, locator, prepared=state["prepare"], validated=state["validate"])
    if stage == "collect":
        return method(scope, contract, locator, executed=state["execute"])
    if stage == "evaluate":
        return method(scope, contract, locator, collected=state["collect"])
    return method(scope, contract, locator, evaluated=state["evaluate"])


def _scan_value(value: Any, path: str, violations: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            normalized_key = str(key or "").lower()
            if normalized_key in _EXECUTABLE_KEYS or normalized_key.endswith(_EXECUTABLE_KEY_SUFFIXES):
                violations.append(f"{child_path}: executable/command field is rejected ({key!r})")
            if isinstance(child, str):
                _scan_text(child, child_path, violations)
            else:
                _scan_value(child, child_path, violations)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _scan_value(child, f"{path}[{index}]", violations)
    elif isinstance(value, str):
        _scan_text(value, path, violations)


def _scan_text(value: str, path: str, violations: list[str]) -> None:
    if _SHELL_TOKEN_RE.search(value):
        violations.append(f"{path}: shell/command token rejected")
    if _ABSOLUTE_PATH_RE.search(value):
        violations.append(f"{path}: absolute path rejected")
    if _TRAVERSAL_RE.search(value):
        violations.append(f"{path}: path traversal '..' rejected")
    if _ENV_REFERENCE_RE.search(value):
        violations.append(f"{path}: environment reference rejected")


def _result_boundaries(evaluated: dict[str, Any]) -> tuple[str, ...]:
    raw = evaluated.get("boundaries")
    if not isinstance(raw, (list, tuple)):
        return ("no_process", "no_gpu", "no_network")
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _fallback_evidence_hash(
    scope: ResearchScopeEnvelope,
    contract: ExperimentContract,
    outcome: ExperimentOutcome,
    stage: str,
) -> str:
    return sha256_hex(
        {
            "scopeHash": scope.scopeHash,
            "contractHash": contract.contentHash,
            "outcome": outcome.value,
            "stage": stage,
        }
    )


def _nonnegative_int(value: Any, *, default: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return normalized if normalized >= 0 else default