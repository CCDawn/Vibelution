"""Select and freeze an explicit model route for one Agent NodeRun."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from core.research.competition.question_result_package import (
    QuestionResultPackageError,
    canonical_model_policy,
    is_qwen_model_id,
)

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

# Purpose is a workflow concern; product role is the authority for which
# Challenge Cup Agent actually owns the call.  Keep these maps independent so
# a shared purpose (for example ``extraction``) cannot silently route through
# the wrong Agent.
NODE_MODEL_PRODUCT_ROLE: dict[str, str] = {
    "source_finding": "challenge_cup_search",
    "source_extraction": "challenge_cup_extractor",
    "evidence_relations": "challenge_cup_knowledge_manager",
    "knowledge_ingestion": "challenge_cup_knowledge_manager",
    "version_governance": "challenge_cup_knowledge_manager",
    "hypothesis_design": "challenge_cup_experiment_revision",
    "protocol_design": "challenge_cup_experiment_revision",
    "iteration_decision": "challenge_cup_experiment_revision",
    "protocol_review": "challenge_cup_evaluator",
    "result_evaluation": "challenge_cup_evaluator",
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORMAL_POLICY_KEYS = frozenset(
    {"requiredModelPolicy", "modelPolicySha256", "routes"}
)
_FORMAL_ROUTE_FIELDS = (
    "agentId",
    "productRoleId",
    "modelRef",
    "providerId",
    "modelId",
)


class ModelRoutingError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def _formal_policy_snapshot(policy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the server-owned formal route snapshot.

    The launch surface is the only producer of this shape.  Treat a partially
    populated formal snapshot as invalid instead of falling back to a legacy
    string route or inventing an upstream model from a client payload.
    """

    if not _FORMAL_POLICY_KEYS.intersection(policy):
        return {}, {}
    missing = sorted(_FORMAL_POLICY_KEYS - set(policy))
    if missing:
        raise ModelRoutingError(
            "formal modelRoutingPolicy is incomplete: " + ", ".join(missing),
            code="model_policy_incomplete",
        )
    raw_required = policy.get("requiredModelPolicy")
    if not isinstance(raw_required, dict):
        raise ModelRoutingError(
            "formal modelRoutingPolicy.requiredModelPolicy is invalid",
            code="model_policy_invalid",
        )
    try:
        required = canonical_model_policy(raw_required)
    except (QuestionResultPackageError, TypeError, ValueError) as exc:
        raise ModelRoutingError(
            "formal modelRoutingPolicy.requiredModelPolicy is invalid",
            code="model_policy_invalid",
        ) from exc
    if raw_required != required:
        raise ModelRoutingError(
            "formal modelRoutingPolicy.requiredModelPolicy is not canonical",
            code="model_policy_noncanonical",
        )
    policy_hash = str(policy.get("modelPolicySha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(policy_hash) or policy_hash != required["policySha256"]:
        raise ModelRoutingError(
            "formal modelRoutingPolicy.modelPolicySha256 does not match requiredModelPolicy",
            code="model_policy_hash_mismatch",
        )
    routes = policy.get("routes")
    if not isinstance(routes, dict):
        raise ModelRoutingError(
            "formal modelRoutingPolicy.routes is invalid",
            code="model_routes_invalid",
        )
    return required, routes


def _formal_route(
    *,
    routes: dict[str, Any],
    purpose: str,
    product_role: str,
    required: dict[str, Any],
) -> dict[str, str]:
    purpose_routes = routes.get(purpose)
    if not isinstance(purpose_routes, dict):
        raise ModelRoutingError(
            f"formal model routes are missing purpose {purpose}",
            code="model_route_missing",
        )
    by_role = purpose_routes.get("byProductRole")
    if not isinstance(by_role, dict):
        raise ModelRoutingError(
            f"formal model routes are missing product-role map for {purpose}",
            code="model_route_invalid",
        )
    route = by_role.get(product_role)
    if not isinstance(route, dict):
        raise ModelRoutingError(
            f"formal model route is missing product role {product_role}",
            code="model_route_missing",
        )
    missing = [field for field in _FORMAL_ROUTE_FIELDS if not str(route.get(field) or "").strip()]
    if missing:
        raise ModelRoutingError(
            "formal model route is incomplete: " + ", ".join(missing),
            code="model_route_invalid",
        )
    normalized = {field: str(route[field]).strip() for field in _FORMAL_ROUTE_FIELDS}
    if normalized["productRoleId"] != product_role:
        raise ModelRoutingError(
            "formal model route product role does not match the NodeRun",
            code="model_role_mismatch",
        )
    if normalized["providerId"].casefold() not in {
        str(value).casefold() for value in required["providerIds"]
    }:
        raise ModelRoutingError(
            "formal model route provider is outside requiredModelPolicy",
            code="model_provider_not_allowed",
        )
    if normalized["modelId"].casefold() not in {
        str(value).casefold() for value in required["modelIds"]
    } or not is_qwen_model_id(normalized["modelId"]):
        raise ModelRoutingError(
            "formal model route upstream model is outside requiredModelPolicy",
            code="model_not_allowed",
        )
    if normalized["modelRef"].partition("/")[0].casefold() != normalized["providerId"].casefold():
        raise ModelRoutingError(
            "formal model route modelRef provider does not match providerId",
            code="model_ref_invalid",
        )
    return normalized


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
    product_role = NODE_MODEL_PRODUCT_ROLE.get(node_id)
    required_policy, formal_routes = _formal_policy_snapshot(policy)
    formal_route: dict[str, str] = {}
    if required_policy:
        if not product_role:
            raise ModelRoutingError(
                f"Agent node has no formal product role: {node_id}",
                code="model_role_missing",
            )
        formal_route = _formal_route(
            routes=formal_routes,
            purpose=purpose,
            product_role=product_role,
            required=required_policy,
        )
        frozen_agent_id = str(node_run.get("agentId") or "").strip()
        if not frozen_agent_id or frozen_agent_id != formal_route["agentId"]:
            raise ModelRoutingError(
                "formal model route Agent does not match the frozen NodeRun binding",
                code="model_agent_mismatch",
            )
        route: Any = formal_route
    else:
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
    if formal_route:
        for field, code in (
            ("providerId", "model_provider_mismatch"),
            ("modelId", "model_id_mismatch"),
        ):
            requested = str(payload.get(field) or "").strip()
            if requested and requested != formal_route[field]:
                raise ModelRoutingError(
                    f"requested {field} differs from the frozen model route",
                    code=code,
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
        f"{record['runId']}:{node_run['nodeRunId']}:{purpose}:"
        f"{product_role or ''}:{model_ref}:"
        f"{required_policy.get('policySha256', '')}"
    ).encode()
    decision = {
        "decisionId": f"model-route-{hashlib.sha256(decision_identity).hexdigest()[:16]}",
        "runId": record["runId"],
        "nodeRunId": node_run["nodeRunId"],
        "nodeId": node_id,
        "purpose": purpose,
        "modelRef": model_ref,
        "estimatedCost": estimated_cost,
        "escalationReason": str(payload.get("escalationReason") or "").strip(),
        "policySnapshotHash": str(
            required_policy.get("policySha256")
            or (record.get("inputSnapshot") or {}).get("snapshotHash")
            or ""
        ),
    }
    if formal_route:
        decision.update(
            {
                "agentId": formal_route["agentId"],
                "productRoleId": formal_route["productRoleId"],
                "providerId": formal_route["providerId"],
                "modelId": formal_route["modelId"],
                "modelPolicySha256": required_policy["policySha256"],
            }
        )
    return decision
