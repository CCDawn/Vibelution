"""Thin Agent Turn execution adapter.

This module gives web/control-plane callers a small Core First interface for
running one Agent Turn without importing the top-level ``agent.py`` entrypoint.
"""

from __future__ import annotations

import inspect
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable

from core.llm.payload_builder import prompt_cache_partition_scope
from core.orchestration.turn_runtime import AgentTurnRuntime, AgentTurnRuntimeRequest, prepare_agent_turn_runtime


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
    static_runtime_context: str = ""
    dynamic_runtime_context: str = ""
    interrupt_checker: InterruptChecker | None = None
    runtime: AgentTurnRuntimeRequest | None = None
    prompt_cache_partition: str = ""


@dataclass(frozen=True)
class AgentSingleTurnResult:
    result: dict[str, Any]
    carryover: dict[str, Any]
    runtime: AgentTurnRuntime | None = None


def default_agent_factory(*, mode: str, workspace_path: str | None = None, config: Any = None) -> Any:
    """Create the concrete runtime Agent lazily to keep imports one-way."""

    from agent import SelfEvolvingAgent

    return SelfEvolvingAgent(mode=mode, workspace_path=workspace_path, config=config)


def create_agent_runtime(
    *,
    mode: str,
    workspace_path: str | None = None,
    config: Any = None,
    agent_factory: AgentFactory = default_agent_factory,
) -> Any:
    """Create a runtime Agent through the shared Core First seam."""

    return agent_factory(mode=mode, workspace_path=workspace_path, config=config)


def call_agent_factory_with_supported_kwargs(factory: Callable[..., Any], **kwargs: Any) -> Any:
    """Call a test/runtime Agent factory with only supported keyword arguments."""

    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        return factory(**kwargs)

    supports_var_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
    accepted_kwargs = {
        key: value
        for key, value in kwargs.items()
        if key in signature.parameters or supports_var_kwargs
    }
    if accepted_kwargs:
        return factory(**accepted_kwargs)
    return factory()


def prepare_agent_turn(
    agent: Any,
    *,
    carryover: dict[str, Any] | None = None,
    runtime_context: str = "",
    static_runtime_context: str = "",
    dynamic_runtime_context: str = "",
    interrupt_checker: InterruptChecker | None = None,
    chat_history: list[dict[str, Any]] | None = None,
) -> None:
    """Seed optional Agent turn inputs when the runtime supports them."""

    seed_turn_carryover = getattr(agent, "seed_turn_carryover", None)
    if callable(seed_turn_carryover) and carryover:
        seed_turn_carryover(carryover)

    host_seeded_runtime_context = False
    static_context_text = str(static_runtime_context or "").strip()
    dynamic_context_text = str(dynamic_runtime_context or "").strip()
    legacy_context_text = str(runtime_context or "").strip()
    seed_static_runtime_context = getattr(agent, "seed_static_runtime_context", None)
    seed_runtime_context = getattr(agent, "seed_runtime_context", None)
    if static_context_text:
        if callable(seed_static_runtime_context):
            seed_static_runtime_context(static_context_text)
            host_seeded_runtime_context = True
        elif callable(seed_runtime_context):
            seed_runtime_context(static_context_text)
            host_seeded_runtime_context = True
    if callable(seed_runtime_context) and dynamic_context_text:
        seed_runtime_context(dynamic_context_text)
        host_seeded_runtime_context = True
    if callable(seed_runtime_context) and legacy_context_text and not static_context_text and not dynamic_context_text:
        seed_runtime_context(legacy_context_text)
        host_seeded_runtime_context = True
    host_context_marker = getattr(agent, "mark_runtime_context_seeded_by_host", None)
    if callable(host_context_marker) and host_seeded_runtime_context:
        host_context_marker()

    stop_configurer = getattr(agent, "set_turn_interrupt_checker", None)
    if callable(stop_configurer) and interrupt_checker:
        stop_configurer(interrupt_checker)

    restore_chat_history = getattr(agent, "seed_chat_history", None)
    if callable(restore_chat_history) and chat_history:
        restore_chat_history(chat_history)


def run_existing_agent_single_turn(
    agent: Any,
    *,
    initial_prompt: str,
    disable_tools: bool = False,
    attachments: list[dict[str, Any]] | None = None,
    prompt_cache_partition: str = "",
) -> Any:
    """Run one Turn on an already-created Agent with optional feature probing."""

    runner = getattr(agent, "run_single_turn")
    kwargs: dict[str, Any] = {"initial_prompt": initial_prompt}
    try:
        signature = inspect.signature(runner)
    except (TypeError, ValueError):
        signature = None

    supports_var_kwargs = bool(
        signature is not None
        and any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
    )
    normalized_attachments = list(attachments or [])
    if normalized_attachments and signature is not None and (
        "attachments" in signature.parameters or supports_var_kwargs
    ):
        kwargs["attachments"] = normalized_attachments
    if disable_tools and signature is not None and "disable_tools" in signature.parameters:
        kwargs["disable_tools"] = True
    partition = str(prompt_cache_partition or "").strip()
    scope = prompt_cache_partition_scope(partition) if partition else nullcontext()
    with scope:
        return runner(**kwargs)


def run_agent_single_turn(
    request: AgentSingleTurnRequest,
    *,
    agent_factory: AgentFactory = default_agent_factory,
) -> AgentSingleTurnResult:
    """Run one Agent Turn and return the visible result plus next carryover."""

    runtime = prepare_agent_turn_runtime(request.runtime) if request.runtime is not None else None
    prompt_cache_partition = (
        runtime.prompt_cache_partition
        if runtime is not None
        else str(request.prompt_cache_partition or "").strip()
    )
    agent = create_agent_runtime(
        mode=request.mode,
        workspace_path=request.workspace_path,
        config=request.config,
        agent_factory=agent_factory,
    )
    prepare_agent_turn(
        agent,
        carryover=request.carryover,
        runtime_context=request.runtime_context,
        static_runtime_context=request.static_runtime_context,
        dynamic_runtime_context=request.dynamic_runtime_context,
        interrupt_checker=request.interrupt_checker,
    )

    raw_result = run_existing_agent_single_turn(
        agent,
        initial_prompt=request.initial_prompt,
        prompt_cache_partition=prompt_cache_partition,
    )
    result = raw_result if isinstance(raw_result, dict) else {}
    if runtime is not None:
        result = {**result, "turn_runtime": dict(runtime.metadata)}

    carryover_payload: dict[str, Any] = {}
    export_turn_carryover = getattr(agent, "export_turn_carryover", None)
    if callable(export_turn_carryover):
        exported = export_turn_carryover()
        if isinstance(exported, dict):
            carryover_payload = exported

    return AgentSingleTurnResult(result=result, carryover=carryover_payload, runtime=runtime)


__all__ = [
    "AgentFactory",
    "AgentSingleTurnRequest",
    "AgentSingleTurnResult",
    "call_agent_factory_with_supported_kwargs",
    "create_agent_runtime",
    "prepare_agent_turn",
    "run_existing_agent_single_turn",
    "run_agent_single_turn",
]
