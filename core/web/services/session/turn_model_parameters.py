"""Server-owned model parameters frozen when a user submission is accepted.

Queue entries and user journal metadata carry only the bounded scalar snapshot;
Agent configuration remains the sole writer of defaults for future submissions.
"""

from __future__ import annotations

import copy
from contextlib import nullcontext
from typing import Any


def capture_model_parameters(service: Any, conversation: dict[str, Any], *, agent: dict[str, Any] | None = None) -> dict[str, Any] | None:
    agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
    if not agent_id:
        return None
    directory = getattr(service, "agent_directory_service", None)
    lock = getattr(directory, "_STATE_LOCK", None)
    with lock if lock is not None else nullcontext():
        # A submit already freezes its whole Agent. Derive both parameters from
        # that same revision; queues take a fresh private snapshot under the lock.
        selected_agent = copy.deepcopy(agent if agent is not None else service.get_agent(agent_id, include_archived=False))
        if not isinstance(selected_agent, dict):
            return None
        if str(selected_agent.get("agentId") or "") != agent_id:
            raise service.SessionValidationError("Model parameter snapshot belongs to another Agent.")
        resolved = service._resolve_session_agent_llm(selected_agent, "dialogue")
        limit = service._session_context_limit_payload({**conversation, "_agent": selected_agent})
        context_window = int(limit.get("limit") or 0)
        if context_window <= 0:
            raise service.SessionValidationError(str(limit.get("error") or "Model context window is missing."))
        return {
            "agentId": agent_id,
            "modelRef": str(resolved.model_ref),
            "configRevision": int(selected_agent.get("configRevision") or 0),
            "contextWindow": context_window,
            "reasoningEffort": str(resolved.reasoning_effort_requested or ""),
        }


def pin_agent_model_parameters(agent: dict[str, Any] | None, snapshot: Any) -> dict[str, Any] | None:
    """Apply the accepted parameters to a private Agent copy, never the registry."""
    if not isinstance(agent, dict) or not isinstance(snapshot, dict) or not snapshot:
        return agent
    if str(agent.get("agentId") or "") != str(snapshot.get("agentId") or ""):
        raise ValueError("Accepted model parameters belong to another Agent.")
    model_ref = str(snapshot.get("modelRef") or "").strip()
    context_window = int(snapshot.get("contextWindow") or 0)
    if not model_ref or context_window <= 0:
        raise ValueError("Accepted model parameter snapshot is invalid.")
    pinned = copy.deepcopy(agent)
    bindings = pinned.setdefault("llmBindings", {})
    bindings["dialogue"] = {"modelId": model_ref}
    metadata = pinned.setdefault("metadata", {})
    parameters = metadata.setdefault("llmModelParameters", {})
    parameters[model_ref] = {
        "contextWindow": context_window,
        "reasoningEffort": str(snapshot.get("reasoningEffort") or ""),
    }
    metadata.setdefault("llmReasoningEffort", {})["dialogue"] = str(snapshot.get("reasoningEffort") or "")
    return pinned
