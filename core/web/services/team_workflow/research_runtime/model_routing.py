"""Select and freeze an explicit model route for one Agent NodeRun."""

from __future__ import annotations

import hashlib
from typing import Any

NODE_MODEL_PURPOSE: dict[str, str] = {
    "source_finding": "source_discovery",
    "source_extraction": "extraction",
    "evidence_relations": "extraction",
    "knowledge_ingestion": "extraction",
    "hypothesis_design": "reasoning",
    "protocol_design": "reasoning",
    "protocol_review": "review",
    "result_evaluation": "review",
    "iteration_decision": "reasoning",
    "version_governance": "governance",
}


class ModelRoutingError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def select_model_route(
    record: dict[str, Any],
    node_run: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    node_id = str(node_run.get("nodeId") or "")
    purpose = NODE_MODEL_PURPOSE.get(node_id)
    if not purpose:
        raise ModelRoutingError(
            f"Agent node has no model purpose: {node_id}",
            code="model_purpose_missing",
        )
    policy = dict((record.get("inputSnapshot") or {}).get("modelRoutingPolicy") or {})
    route = policy.get(purpose)
    max_estimated_cost: float | None = None
    if isinstance(route, str):
        model_ref = route.strip()
    elif isinstance(route, dict):
        model_ref = str(route.get("modelRef") or "").strip()
        if route.get("maxEstimatedCost") is not None:
            max_estimated_cost = float(route["maxEstimatedCost"])
    else:
        model_ref = ""
    if not model_ref:
        raise ModelRoutingError(
            f"modelRoutingPolicy is missing purpose {purpose}",
            code="model_route_missing",
        )
    requested_model = str(payload.get("modelRef") or model_ref).strip()
    if requested_model != model_ref:
        raise ModelRoutingError(
            "requested modelRef differs from the frozen modelRoutingPolicy",
            code="model_route_mismatch",
        )
    estimated_cost = float(payload.get("estimatedCost") or 0)
    if estimated_cost < 0:
        raise ModelRoutingError(
            "estimatedCost must be non-negative",
            code="invalid_model_cost",
        )
    if max_estimated_cost is not None and estimated_cost > max_estimated_cost:
        raise ModelRoutingError(
            "estimatedCost exceeds the frozen model route limit",
            code="model_cost_exceeded",
        )
    decision_identity = (
        f"{record['runId']}:{node_run['nodeRunId']}:{purpose}:{model_ref}"
    ).encode()
    return {
        "decisionId": f"model-route-{hashlib.sha256(decision_identity).hexdigest()[:16]}",
        "runId": record["runId"],
        "nodeRunId": node_run["nodeRunId"],
        "nodeId": node_id,
        "purpose": purpose,
        "modelRef": model_ref,
        "estimatedCost": estimated_cost,
        "escalationReason": str(payload.get("escalationReason") or "").strip(),
        "policySnapshotHash": str(
            (record.get("inputSnapshot") or {}).get("snapshotHash") or ""
        ),
    }
