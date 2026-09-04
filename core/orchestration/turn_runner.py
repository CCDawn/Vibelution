"""Thin Agent Turn execution adapter.

This module gives web/control-plane callers a small Core First interface for
running one Agent Turn without importing the top-level ``agent.py`` entrypoint.
"""

from __future__ import annotations

import inspect
import json
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from core.llm.payload_builder import prompt_cache_partition_scope
from core.orchestration.turn_outcome import TurnOutcomeController
from core.orchestration.turn_runtime import AgentTurnRuntime, AgentTurnRuntimeRequest, prepare_agent_turn_runtime


AgentFactory = Callable[..., Any]
InterruptChecker = Callable[[], str]


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _as_mapping(value: Any) -> dict[str, Any]:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _coerce_item_list(value: Any) -> list:
    value = _maybe_json(value)
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(value, Mapping):
        nested = value.get("messages")
        if nested is None:
            nested = value.get("items")
        if nested is None:
            nested = value.get("history")
        if nested is None:
            nested = value.get("chat_history")
        if nested is None:
            nested = value.get("chatHistory")
        if nested is not None:
            return _coerce_item_list(nested)
        if any(key in value for key in ("kind", "role", "content", "type", "tool_calls", "toolCalls")):
            return [dict(value)]
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _as_single_turn_request(request: Any) -> AgentSingleTurnRequest:
    if isinstance(request, AgentSingleTurnRequest):
        return request
    values = _as_mapping(request)
    runtime = values.get("runtime")
    if runtime is None:
        runtime = values.get("turn_runtime")
    return AgentSingleTurnRequest(
        mode=_coerce_text(values.get("mode")).strip(),
        initial_prompt=_coerce_text(values.get("initial_prompt") or values.get("initialPrompt")),
        workspace_path=_coerce_text(values.get("workspace_path") or values.get("workspacePath")).strip() or None,
        config=values.get("config"),
        disable_tools=_coerce_bool(values.get("disable_tools", values.get("disableTools")), False),
        carryover=_as_mapping(values.get("carryover")) or None,
        chat_history=_coerce_item_list(values.get("chat_history") or values.get("chatHistory")) or None,
        turn_identity=_coerce_text(values.get("turn_identity") or values.get("turnIdentity")).strip(),
        runtime_context=_coerce_text(values.get("runtime_context") or values.get("runtimeContext")),
        static_runtime_context=_coerce_text(
            values.get("static_runtime_context") or values.get("staticRuntimeContext")
        ),
        dynamic_runtime_context=_coerce_text(
            values.get("dynamic_runtime_context") or values.get("dynamicRuntimeContext")
        ),
        interrupt_checker=values.get("interrupt_checker") or values.get("interruptChecker"),
        runtime=runtime,
        prompt_cache_partition=_coerce_text(
            values.get("prompt_cache_partition") or values.get("promptCachePartition")
        ).strip(),
    )


@dataclass(frozen=True)
class AgentSingleTurnRequest:
    mode: str
    initial_prompt: str
    workspace_path: str | None = None
    config: Any = None
    disable_tools: bool = False
    carryover: dict[str, Any] | None = None
    chat_history: list[dict[str, Any]] | None = None
    turn_identity: str = ""
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


def default_agent_factory(
    *,
    mode: str,
    workspace_path: str | None = None,
    config: Any = None,
    runtime_agent_binding: dict[str, Any] | None = None,
) -> Any:
    """Create the concrete runtime Agent lazily to keep imports one-way."""

    from agent import SelfEvolvingAgent

    return SelfEvolvingAgent(
        mode=mode,
        workspace_path=workspace_path,
        config=config,
        runtime_agent_binding=runtime_agent_binding,
    )


def create_agent_runtime(
    *,
    mode: str,
    workspace_path: str | None = None,
    config: Any = None,
    runtime_agent_binding: dict[str, Any] | None = None,
    agent_factory: AgentFactory = default_agent_factory,
) -> Any:
    """Create a runtime Agent through the shared Core First seam."""

    factory_kwargs: dict[str, Any] = {
        "mode": mode,
        "workspace_path": workspace_path,
        "config": config,
    }
    if runtime_agent_binding is not None:
        factory_kwargs["runtime_agent_binding"] = runtime_agent_binding
    return call_agent_factory_with_supported_kwargs(agent_factory, **factory_kwargs)


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


def _coerce_chat_history(value: Any) -> list:
    return _coerce_item_list(value)


def prepare_agent_turn(
    agent: Any,
    *,
    carryover: dict[str, Any] | None = None,
    turn_identity: str = "",
    runtime_context: str = "",
    static_runtime_context: str = "",
    dynamic_runtime_context: str = "",
    interrupt_checker: InterruptChecker | None = None,
    chat_history: list[dict[str, Any]] | None = None,
    chat_history_ledger_fingerprint: str = "",
) -> None:
    """Own preparation of history or same-turn recovery before execution."""

    normalized_turn_identity = _coerce_text(turn_identity).strip()
    history_items = _coerce_chat_history(chat_history)
    set_turn_identity = getattr(agent, "set_turn_identity", None)
    if callable(set_turn_identity) and (normalized_turn_identity or carryover):
        set_turn_identity(normalized_turn_identity)

    carryover_status = TurnOutcomeController.classify_turn_carryover(
        carryover,
        expected_turn_identity=normalized_turn_identity,
    )
    seed_turn_carryover = getattr(agent, "seed_turn_carryover", None)
    if callable(seed_turn_carryover) and carryover_status == "accepted":
        seed_turn_carryover(carryover)
    else:
        clear_active_state = getattr(agent, "clear_turn_preparation_state", None)
        if carryover_status != "absent" and callable(clear_active_state):
            clear_active_state()
        restore_chat_history = getattr(agent, "seed_chat_history", None)
        if callable(restore_chat_history) and history_items:
            restore_chat_history(history_items)
            ledger_fp = _coerce_text(chat_history_ledger_fingerprint).strip()
            seed_ledger_fp = getattr(agent, "seed_chat_history_ledger_fingerprint", None)
            if ledger_fp and callable(seed_ledger_fp):
                seed_ledger_fp(ledger_fp)

    host_seeded_runtime_context = False
    static_context_text = _coerce_text(static_runtime_context).strip()
    seed_static_runtime_context = getattr(agent, "seed_static_runtime_context", None)
    seed_runtime_context = getattr(agent, "seed_runtime_context", None)
    if static_context_text:
        if callable(seed_static_runtime_context):
            seed_static_runtime_context(static_context_text)
            host_seeded_runtime_context = True
        elif callable(seed_runtime_context):
            seed_runtime_context(static_context_text)
            host_seeded_runtime_context = True
    # Runtime context inputs are intentionally not seeded into the model message list.
    # They may still be logged or exposed through tools, but the LLM payload should
    # stay to stable system prompt + dialogue + current user.
    host_context_marker = getattr(agent, "mark_runtime_context_seeded_by_host", None)
    if callable(host_context_marker) and host_seeded_runtime_context:
        host_context_marker()

    stop_configurer = getattr(agent, "set_turn_interrupt_checker", None)
    if callable(stop_configurer) and callable(interrupt_checker):
        stop_configurer(interrupt_checker)

    record_diagnostic = getattr(agent, "record_turn_preparation_diagnostic", None)
    if callable(record_diagnostic):
        record_diagnostic(
            {
                "path": (
                    "carryover"
                    if carryover_status == "accepted"
                    else "history"
                    if history_items
                    else "fresh"
                ),
                "carryoverStatus": carryover_status,
                "historyMessageCount": len(history_items),
                "hasTurnIdentity": bool(normalized_turn_identity),
                "staticContextChars": len(static_context_text),
                "dynamicContextChars": len(_coerce_text(dynamic_runtime_context).strip()),
            }
        )


def _execute_existing_agent_single_turn(
    agent: Any,
    *,
    initial_prompt: str,
    disable_tools: bool = False,
    allowed_tool_names: list[str] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    prompt_cache_partition: str = "",
) -> Any:
    """Execute one already-prepared Agent Turn."""

    runner = getattr(agent, "run_single_turn")
    kwargs: dict[str, Any] = {"initial_prompt": _coerce_text(initial_prompt)}
    try:
        signature = inspect.signature(runner)
    except (TypeError, ValueError):
        signature = None

    supports_var_kwargs = bool(
        signature is not None
        and any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
    )
    normalized_attachments = _coerce_item_list(attachments)
    if normalized_attachments and signature is not None and (
        "attachments" in signature.parameters or supports_var_kwargs
    ):
        kwargs["attachments"] = normalized_attachments
    if _coerce_bool(disable_tools, False) and signature is not None and (
        "disable_tools" in signature.parameters or supports_var_kwargs
    ):
        kwargs["disable_tools"] = True
    if allowed_tool_names is not None and signature is not None and (
        "allowed_tool_names" in signature.parameters or supports_var_kwargs
    ):
        kwargs["allowed_tool_names"] = [
            str(item or "").strip()
            for item in allowed_tool_names
            if str(item or "").strip()
        ]
    partition = _coerce_text(prompt_cache_partition).strip()
    scope = prompt_cache_partition_scope(partition) if partition else nullcontext()
    with scope:
        return runner(**kwargs)


def run_existing_agent_single_turn(
    agent: Any,
    *,
    initial_prompt: str,
    disable_tools: bool = False,
    allowed_tool_names: list[str] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    prompt_cache_partition: str = "",
    carryover: dict[str, Any] | None = None,
    turn_identity: str = "",
    runtime_context: str = "",
    static_runtime_context: str = "",
    dynamic_runtime_context: str = "",
    interrupt_checker: InterruptChecker | None = None,
    chat_history: list[dict[str, Any]] | None = None,
    chat_history_ledger_fingerprint: str = "",
) -> Any:
    """Prepare and run one Turn on an already-created Agent."""

    prepare_agent_turn(
        agent,
        carryover=carryover,
        turn_identity=turn_identity,
        runtime_context=runtime_context,
        static_runtime_context=static_runtime_context,
        dynamic_runtime_context=dynamic_runtime_context,
        interrupt_checker=interrupt_checker,
        chat_history=chat_history,
        chat_history_ledger_fingerprint=chat_history_ledger_fingerprint,
    )
    return _execute_existing_agent_single_turn(
        agent,
        initial_prompt=initial_prompt,
        disable_tools=disable_tools,
        allowed_tool_names=allowed_tool_names,
        attachments=attachments,
        prompt_cache_partition=prompt_cache_partition,
    )


def run_agent_single_turn(
    request: AgentSingleTurnRequest,
    *,
    agent_factory: AgentFactory = default_agent_factory,
) -> AgentSingleTurnResult:
    """Run one Agent Turn and return the visible result plus next carryover."""

    request = _as_single_turn_request(request)
    runtime = prepare_agent_turn_runtime(request.runtime) if request.runtime is not None else None
    prompt_cache_partition = (
        runtime.prompt_cache_partition
        if runtime is not None
        else _coerce_text(request.prompt_cache_partition).strip()
    )
    runtime_agent_binding = None
    if runtime is not None and runtime.agent_id:
        runtime_agent_binding = {
            "agentId": runtime.agent_id,
            "llmSlot": runtime.llm_slot,
            "directSessionId": runtime.session_id,
            "workspacePath": runtime.workspace_path,
        }
        if runtime.model_id and runtime.model_id != "default":
            runtime_agent_binding["llmBindings"] = {
                runtime.llm_slot: {
                    "modelId": runtime.model_id,
                }
            }
    agent = create_agent_runtime(
        mode=_coerce_text(request.mode).strip(),
        workspace_path=_coerce_text(request.workspace_path).strip() or None,
        config=request.config,
        runtime_agent_binding=runtime_agent_binding,
        agent_factory=agent_factory,
    )
    prepare_agent_turn(
        agent,
        carryover=request.carryover,
        chat_history=request.chat_history,
        turn_identity=(
            _coerce_text(getattr(runtime, "run_id", "")).strip()
            if runtime is not None
            else _coerce_text(request.turn_identity).strip()
        ),
        runtime_context=request.runtime_context,
        static_runtime_context=request.static_runtime_context,
        dynamic_runtime_context=request.dynamic_runtime_context,
        interrupt_checker=request.interrupt_checker,
    )

    raw_result = _execute_existing_agent_single_turn(
        agent,
        initial_prompt=_coerce_text(request.initial_prompt),
        disable_tools=_coerce_bool(request.disable_tools, False),
        prompt_cache_partition=prompt_cache_partition,
    )
    result = raw_result if isinstance(raw_result, Mapping) else {}
    result = dict(result)
    if runtime is not None:
        result = {**result, "turn_runtime": dict(runtime.metadata)}

    carryover_payload: dict[str, Any] = {}
    export_turn_carryover = getattr(agent, "export_turn_carryover", None)
    if callable(export_turn_carryover):
        exported = export_turn_carryover()
        if isinstance(exported, Mapping):
            carryover_payload = dict(exported)

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
