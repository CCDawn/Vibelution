"""Core ExperimentAdapter protocol, dispatcher and Challenge Cup DEV adapters.

Unified lifecycle: ``prepare -> validate -> execute -> collect -> evaluate
-> emit_receipt``.  The default dispatcher still ships only the offline fake
adapter; ``challenge_cup_dispatcher()`` registers FashionMNIST, GPU operator
and neural spike DEV fixtures without starting real experiments.
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
from .fashion_mnist import FashionMnistFixtureAdapter
from .gpu_operator import GpuOperatorFixtureAdapter
from .neural_spike import NeuralSpikeFixtureAdapter
from .registry import challenge_cup_adapters, challenge_cup_dispatcher
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
    "FashionMnistFixtureAdapter",
    "GpuOperatorFixtureAdapter",
    "NeuralSpikeFixtureAdapter",
    "challenge_cup_adapters",
    "challenge_cup_dispatcher",
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