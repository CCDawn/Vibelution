"""Core ExperimentAdapter protocol, dispatcher and offline fake adapter (D06).

Unified lifecycle: ``prepare -> validate -> execute -> collect -> evaluate
-> emit_receipt``, bound to the immutable ``ResearchScopeEnvelope``, an explicit
``ExperimentContract`` and a fail-closed ``ControlledLocator``.  The dispatcher
is the only execution entry point; only the deterministic offline fake adapter
is shipped in this batch.
"""

from .dispatcher import (
    DEFAULT_MAX_ARTIFACTS,
    DEFAULT_MAX_LOG_BYTES,
    DEFAULT_MAX_RECEIPT_ITEMS,
    DispatcherError,
    ExperimentDispatcher,
    OfflineFakeExperimentAdapter,
    idempotency_key,
    scan_for_executable_fields,
)
from .protocol import (
    ALLOWED_LOCATOR_KINDS,
    AdapterContractError,
    AdapterError,
    AdapterUnavailableError,
    BoundedEvidenceReceipt,
    ControlledLocator,
    DEFAULT_LOCATOR_MAX_DEPTH,
    ExperimentAdapter,
    ExperimentContract,
    ExperimentOutcome,
    ExperimentResult,
    LIFECYCLE_STAGES,
    LocatorValidationError,
    phase_result,
    require_controlled_locator,
    validate_relative_path,
)

__all__ = [
    "ALLOWED_LOCATOR_KINDS",
    "AdapterContractError",
    "AdapterError",
    "AdapterUnavailableError",
    "BoundedEvidenceReceipt",
    "ControlledLocator",
    "DEFAULT_LOCATOR_MAX_DEPTH",
    "DEFAULT_MAX_ARTIFACTS",
    "DEFAULT_MAX_LOG_BYTES",
    "DEFAULT_MAX_RECEIPT_ITEMS",
    "DispatcherError",
    "ExperimentAdapter",
    "ExperimentContract",
    "ExperimentDispatcher",
    "ExperimentOutcome",
    "ExperimentResult",
    "LIFECYCLE_STAGES",
    "LocatorValidationError",
    "OfflineFakeExperimentAdapter",
    "idempotency_key",
    "phase_result",
    "require_controlled_locator",
    "scan_for_executable_fields",
    "validate_relative_path",
]