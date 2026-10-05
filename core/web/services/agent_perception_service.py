"""Stable web-service facade for Agent perception configuration and runtime."""

from __future__ import annotations

from typing import Any

from core.web.services.agent_perception import service as _perception

AgentPerceptionError = _perception.AgentPerceptionError
AgentPerceptionDenied = _perception.AgentPerceptionDenied


class AgentPerceptionRuntimeUnavailable(RuntimeError):
    """The native perception runtime has not been attached to the web service."""


def _require_operator(command: str) -> None:
    from core.web.services.team_workflow.research_runtime.operator_authorization import (
        require_privileged_server_operator,
    )

    require_privileged_server_operator(command=command)


def get_agent_perception_configuration(agent_id: str) -> dict[str, Any]:
    _require_operator("read_agent_perception_configuration")
    return _perception.get_perception_configuration(agent_id)


def save_agent_perception_configuration(
    agent_id: str,
    policy: dict[str, Any],
    *,
    expected_agent_updated_at: str,
) -> dict[str, Any]:
    _require_operator("configure_agent_perception")
    return _perception.save_perception_configuration(
        agent_id,
        policy,
        expected_agent_updated_at=expected_agent_updated_at,
    )


def get_agent_perception_runtime(agent_id: str) -> dict[str, Any]:
    _require_operator("read_agent_perception_runtime")
    try:
        from core.web.services.agent_perception.runtime import get_agent_perception_runtime as get_runtime
    except (ImportError, AttributeError) as exc:
        raise AgentPerceptionRuntimeUnavailable("Agent perception runtime is unavailable.") from exc

    return get_runtime(agent_id)


def cancel_agent_perception(agent_id: str, *, run_id: str = "") -> dict[str, Any]:
    _require_operator("cancel_agent_perception_run")
    try:
        from core.web.services.agent_perception.runtime import cancel_agent_perception as cancel_runtime
    except (ImportError, AttributeError) as exc:
        raise AgentPerceptionRuntimeUnavailable("Agent perception runtime is unavailable.") from exc

    return cancel_runtime(agent_id, run_id=run_id, reason="operator")


def begin_knowledge_item_read(agent_id: str, base_id: str) -> dict[str, Any] | None:
    """Begin a source-budgeted, revocation-aware formal knowledge read."""
    return _perception.begin_knowledge_item_read(agent_id, base_id)


def finish_knowledge_item_read(
    ticket: dict[str, Any] | None,
    *,
    result_count: int,
    result_chars: int = 0,
) -> bool:
    """Validate current scope after the formal knowledge read completes."""
    return _perception.finish_knowledge_item_read(
        ticket,
        result_count=result_count,
        result_chars=result_chars,
    )
