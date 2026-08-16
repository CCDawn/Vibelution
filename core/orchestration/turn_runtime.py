"""Shared Agent turn runtime metadata and cache partition helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class AgentTurnRuntimeRequest:
    mode: str
    run_kind: str
    run_id: str = ""
    session_id: str = ""
    agent_id: str = ""
    llm_slot: str = ""
    model_id: str = ""
    cache_scope: str = ""
    workspace_path: str = ""


@dataclass(frozen=True)
class AgentTurnRuntime:
    mode: str
    run_kind: str
    run_id: str
    session_id: str
    agent_id: str
    llm_slot: str
    model_id: str
    cache_scope: str
    workspace_path: str
    prompt_cache_partition: str
    metadata: dict[str, Any]


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _clean(value: Any, *, fallback: str = "") -> str:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    value = _maybe_json(value)
    if isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
        return fallback
    if isinstance(value, bool) or value is None:
        text = ""
    else:
        text = str(value)
    text = " ".join(text.split())
    return text or fallback


def _short_hash(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _as_request(request: Any) -> AgentTurnRuntimeRequest:
    if isinstance(request, AgentTurnRuntimeRequest):
        return request
    if isinstance(request, (bytes, bytearray, memoryview)):
        request = bytes(request).decode("utf-8", errors="replace")
    if isinstance(request, str):
        text = request.strip()
        if not text:
            request = {}
        else:
            try:
                request = json.loads(text)
            except json.JSONDecodeError:
                request = {}
    if not isinstance(request, Mapping):
        request = {}

    def pick(*keys: str) -> Any:
        for key in keys:
            if key in request:
                return request.get(key)
        return ""

    return AgentTurnRuntimeRequest(
        mode=pick("mode"),
        run_kind=pick("run_kind", "runKind"),
        run_id=pick("run_id", "runId"),
        session_id=pick("session_id", "sessionId"),
        agent_id=pick("agent_id", "agentId"),
        llm_slot=pick("llm_slot", "llmSlot"),
        model_id=pick("model_id", "modelId"),
        cache_scope=pick("cache_scope", "cacheScope"),
        workspace_path=pick("workspace_path", "workspacePath"),
    )


def build_prompt_cache_partition(
    *,
    mode: str,
    run_kind: str,
    session_id: str = "",
    agent_id: str = "",
    llm_slot: str = "",
    model_id: str = "",
    cache_scope: str = "",
) -> str:
    """Build a stable prompt-cache partition shared by chat/evolution callers.

    ``run_id`` is deliberately excluded so repeated turns in the same logical
    stream can hit cache. ``run_kind`` and ``cache_scope`` keep chat, self
    evolution, and supervised baseline/candidate runs from sharing shards.
    """

    parts = [
        f"mode:{_clean(mode, fallback='unknown')}",
        f"kind:{_clean(run_kind, fallback='turn')}",
        f"agent:{_clean(agent_id, fallback='direct')}",
        f"session:{_clean(session_id, fallback='none')}",
        f"slot:{_clean(llm_slot, fallback='dialogue')}",
        f"model:{_clean(model_id, fallback='default')}",
    ]
    scope = _clean(cache_scope)
    if scope:
        parts.append(f"scope:{scope}")
    return "|".join(parts)


def prepare_agent_turn_runtime(request: AgentTurnRuntimeRequest | Mapping[str, Any] | str | bytes | None) -> AgentTurnRuntime:
    request = _as_request(request)
    mode = _clean(request.mode, fallback="self_evolution")
    run_kind = _clean(request.run_kind, fallback=mode)
    run_id = _clean(request.run_id)
    session_id = _clean(request.session_id)
    agent_id = _clean(request.agent_id)
    llm_slot = _clean(request.llm_slot, fallback="dialogue")
    model_id = _clean(request.model_id, fallback="default")
    cache_scope = _clean(request.cache_scope)
    workspace_path = _clean(request.workspace_path)
    partition = build_prompt_cache_partition(
        mode=mode,
        run_kind=run_kind,
        session_id=session_id,
        agent_id=agent_id,
        llm_slot=llm_slot,
        model_id=model_id,
        cache_scope=cache_scope,
    )
    metadata = {
        "mode": mode,
        "runKind": run_kind,
        "runId": run_id,
        "sessionId": session_id,
        "agentId": agent_id,
        "llmSlot": llm_slot,
        "modelId": model_id,
        "cacheScope": cache_scope,
        "workspacePath": workspace_path,
        "promptCachePartitionHash": _short_hash(partition),
        "promptCachePartitionChars": len(partition),
    }
    return AgentTurnRuntime(
        mode=mode,
        run_kind=run_kind,
        run_id=run_id,
        session_id=session_id,
        agent_id=agent_id,
        llm_slot=llm_slot,
        model_id=model_id,
        cache_scope=cache_scope,
        workspace_path=workspace_path,
        prompt_cache_partition=partition,
        metadata=metadata,
    )


def runtime_metadata_env(runtime: AgentTurnRuntime | Mapping[str, Any] | None) -> dict[str, str]:
    if runtime is None:
        return {}
    if not isinstance(runtime, AgentTurnRuntime):
        runtime = prepare_agent_turn_runtime(runtime)
    env = {
        "VIBELUTION_TURN_MODE": runtime.mode,
        "VIBELUTION_TURN_RUN_KIND": runtime.run_kind,
        "VIBELUTION_TURN_RUN_ID": runtime.run_id,
        "VIBELUTION_TURN_SESSION_ID": runtime.session_id,
        "VIBELUTION_TURN_AGENT_ID": runtime.agent_id,
        "VIBELUTION_TURN_LLM_SLOT": runtime.llm_slot,
        "VIBELUTION_TURN_MODEL_ID": runtime.model_id,
        "VIBELUTION_TURN_CACHE_SCOPE": runtime.cache_scope,
        "VIBELUTION_TURN_PROMPT_CACHE_PARTITION": runtime.prompt_cache_partition,
    }
    return {key: value for key, value in env.items() if value}


__all__ = [
    "AgentTurnRuntime",
    "AgentTurnRuntimeRequest",
    "build_prompt_cache_partition",
    "prepare_agent_turn_runtime",
    "runtime_metadata_env",
]
