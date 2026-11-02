"""Preserve the original closed runtime wire shape for existing SDKs."""
from copy import deepcopy
from pydantic import Field, create_model
from .runtime_contracts import (RuntimeClosed, RuntimeUntrusted, RuntimeOperation,
    RuntimeOperationsQuery, RuntimeOperationsResponse, RuntimeOperationResponse)


def _fields(model, exclude=()):
    return {name: (field.annotation, deepcopy(field)) for name, field in model.model_fields.items() if name not in exclude}


LegacyRuntimeOperation = create_model("LegacyRuntimeOperation", __base__=RuntimeClosed,
    **_fields(RuntimeOperation, {"progressFingerprint"}))
LegacyRuntimeOperationsQuery = create_model("LegacyRuntimeOperationsQuery", __base__=RuntimeClosed,
    **_fields(RuntimeOperationsQuery, {"expected_snapshot"}))
LegacyRuntimeOperationsResponse = create_model("LegacyRuntimeOperationsResponse", __base__=RuntimeUntrusted,
    **{**_fields(RuntimeOperationsResponse, {"snapshot", "operations"}), "operations": (list[LegacyRuntimeOperation], Field(max_length=3))})
LegacyRuntimeOperationResponse = create_model("LegacyRuntimeOperationResponse", __base__=RuntimeUntrusted,
    **{**_fields(RuntimeOperationResponse, {"operation"}), "operation": (LegacyRuntimeOperation, ...)})


def legacy_runtime_result(raw, operation):
    result = deepcopy(raw)
    result.pop("snapshot", None)
    for item in result.get("operations", []) if operation == "list" else [result["operation"]]:
        item.pop("progressFingerprint", None)
    model = LegacyRuntimeOperationsResponse if operation == "list" else LegacyRuntimeOperationResponse
    return model.model_validate(result).model_dump()
