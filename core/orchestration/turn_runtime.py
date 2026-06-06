"""Shared Agent turn runtime metadata and cache partition helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


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


def _clean(value: Any, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _short_hash(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:12]


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


def prepare_agent_turn_runtime(request: AgentTurnRuntimeRequest) -> AgentTurnRuntime:
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


def runtime_metadata_env(runtime: AgentTurnRuntime) -> dict[str, str]:
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
