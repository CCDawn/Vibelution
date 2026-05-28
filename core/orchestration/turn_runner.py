"""Thin Agent Turn execution adapter.

This module gives web/control-plane callers a small Core First interface for
running one Agent Turn without importing the top-level ``agent.py`` entrypoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


AgentFactory = Callable[..., Any]
InterruptChecker = Callable[[], str]


@dataclass(frozen=True)
class AgentSingleTurnRequest:
    mode: str
    initial_prompt: str
    workspace_path: str | None = None
    config: Any = None
    carryover: dict[str, Any] | None = None
    runtime_context: str = ""
    interrupt_checker: InterruptChecker | None = None


@dataclass(frozen=True)
class AgentSingleTurnResult:
    result: dict[str, Any]
    carryover: dict[str, Any]


def default_agent_factory(*, mode: str, workspace_path: str | None = None, config: Any = None) -> Any:
    """Create the concrete runtime Agent lazily to keep imports one-way."""

    from agent import SelfEvolvingAgent

    return SelfEvolvingAgent(mode=mode, workspace_path=workspace_path, config=config)


def run_agent_single_turn(
    request: AgentSingleTurnRequest,
    *,
    agent_factory: AgentFactory = default_agent_factory,
) -> AgentSingleTurnResult:
    """Run one Agent Turn and return the visible result plus next carryover."""

    agent = agent_factory(
        mode=request.mode,
        workspace_path=request.workspace_path,
        config=request.config,
    )
    seed_turn_carryover = getattr(agent, "seed_turn_carryover", None)
    if callable(seed_turn_carryover) and request.carryover:
        seed_turn_carryover(request.carryover)

    seed_runtime_context = getattr(agent, "seed_runtime_context", None)
    if callable(seed_runtime_context) and request.runtime_context:
        seed_runtime_context(request.runtime_context)

    stop_configurer = getattr(agent, "set_turn_interrupt_checker", None)
    if callable(stop_configurer) and request.interrupt_checker:
        stop_configurer(request.interrupt_checker)

    raw_result = agent.run_single_turn(initial_prompt=request.initial_prompt)
    result = raw_result if isinstance(raw_result, dict) else {}

    carryover_payload: dict[str, Any] = {}
    export_turn_carryover = getattr(agent, "export_turn_carryover", None)
    if callable(export_turn_carryover):
        exported = export_turn_carryover()
        if isinstance(exported, dict):
            carryover_payload = exported

    return AgentSingleTurnResult(result=result, carryover=carryover_payload)


__all__ = [
    "AgentFactory",
    "AgentSingleTurnRequest",
    "AgentSingleTurnResult",
    "run_agent_single_turn",
]
