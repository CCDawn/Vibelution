"""Preserve the original closed runtime wire shape for existing SDKs."""
from copy import deepcopy
from typing import Literal, get_args
from pydantic import Field, create_model
from .runtime_contracts import (RuntimeClosed, RuntimeUntrusted, RuntimeOperation,
    RuntimeOperationsQuery, RuntimeOperationsResponse, RuntimeOperationQuery, RuntimeOperationResponse)

LegacyRuntimeKind = Literal["session_turn", "runtime_task", "external_task", "team_run",
                            "supervised_run", "self_evolution_run", "research_run"]
LEGACY_RUNTIME_KINDS = get_args(LegacyRuntimeKind)


def _fields(model, exclude=()):
    return {name: (field.annotation, deepcopy(field)) for name, field in model.model_fields.items() if name not in exclude}


LegacyRuntimeOperation = create_model("LegacyRuntimeOperation", __base__=RuntimeClosed,
    **{**_fields(RuntimeOperation, {"progressFingerprint", "queue", "kind"}), "kind": (LegacyRuntimeKind, ...)})
LegacyRuntimeOperationsQuery = create_model("LegacyRuntimeOperationsQuery", __base__=RuntimeClosed,
    **{**_fields(RuntimeOperationsQuery, {"expected_snapshot", "kind"}), "kind": (LegacyRuntimeKind | None, None)})
LegacyRuntimeOperationQuery = create_model("LegacyRuntimeOperationQuery", __base__=RuntimeOperationQuery,
    kind=(LegacyRuntimeKind, ...))
LegacyRuntimeCoverage = create_model("LegacyRuntimeCoverage", __base__=RuntimeClosed,
    source=(LegacyRuntimeKind, ...), state=(Literal["available", "unavailable", "partial"], ...), complete=(bool, ...))
LegacyRuntimeOperationsResponse = create_model("LegacyRuntimeOperationsResponse", __base__=RuntimeUntrusted,
    **{**_fields(RuntimeOperationsResponse, {"snapshot", "operations", "coverage"}),
       "operations": (list[LegacyRuntimeOperation], Field(max_length=3)),
       "coverage": (list[LegacyRuntimeCoverage], Field(min_length=1, max_length=7))})
LegacyRuntimeOperationResponse = create_model("LegacyRuntimeOperationResponse", __base__=RuntimeUntrusted,
    **{**_fields(RuntimeOperationResponse, {"operation"}), "operation": (LegacyRuntimeOperation, ...)})


def legacy_runtime_result(raw, operation):
    result = deepcopy(raw)
    result.pop("snapshot", None)
    for item in result.get("operations", []) if operation == "list" else [result["operation"]]:
        item.pop("progressFingerprint", None)
        item.pop("queue", None)
    for coverage in result.get("coverage", []):
        coverage.pop("details", None)
    model = LegacyRuntimeOperationsResponse if operation == "list" else LegacyRuntimeOperationResponse
    return model.model_validate(result).model_dump()
