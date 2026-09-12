"""Apply the formal run's existing per-Agent model route to meeting calls."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Callable, Mapping

from .meeting_receipt_authority import MeetingReceiptAuthorityError
from .model_routing import _formal_policy_snapshot, _formal_route


def resolve_meeting_speaker_llm(
    agent: dict[str, Any], context: Mapping[str, Any], resolver: Callable[[dict[str, Any]], Any],
) -> Any:
    authority = context.get("_modelInvocationReceiptAuthority")
    if not isinstance(authority, Mapping):
        return resolver(agent)
    if authority.get("authorityKind") == "operator_discussion":
        from ..operator_optimization.discussion_authority import resolve_speaker_llm
        return resolve_speaker_llm(agent, context, resolver)
    from .formal_write_runtime import get_write_store

    run = get_write_store().get_run(str(authority.get("workflowRunId") or ""))
    if run is None or run.team_id != authority.get("teamId"):
        raise MeetingReceiptAuthorityError("formal meeting model route run scope is invalid")
    snapshot = json.loads(run.input_snapshot_json)
    policy = snapshot.get("modelRoutingPolicy") or {}
    required, routes = _formal_policy_snapshot(policy)
    if not required or policy.get("modelPolicySha256") != authority.get("modelPolicySha256"):
        raise MeetingReceiptAuthorityError("formal meeting model policy differs from its run")
    agent_id = str(agent.get("agentId") or "")
    matches = []
    for purpose, purpose_routes in routes.items():
        for role, route in (purpose_routes.get("byProductRole") or {}).items():
            if route.get("agentId") == agent_id:
                matches.append(_formal_route(routes=routes, purpose=purpose, product_role=role, required=required))
    model_routes = {(route["modelRef"], route["providerId"], route["modelId"]) for route in matches}
    if len(model_routes) != 1:
        raise MeetingReceiptAuthorityError("formal meeting speaker has no unique frozen model route")
    model_ref, provider_id, model_id = model_routes.pop()
    frozen_agent = deepcopy(agent)
    bindings = frozen_agent.setdefault("llmBindings", {})
    bindings["dialogue"] = {**bindings.get("dialogue", {}), "modelId": model_ref}
    resolved = resolver(frozen_agent)
    actual = (resolved.model_ref, resolved.provider_id, resolved.model)
    if actual != (model_ref, provider_id, model_id):
        raise MeetingReceiptAuthorityError("resolved meeting model differs from the frozen model route")
    return resolved
