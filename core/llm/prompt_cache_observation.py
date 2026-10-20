# -*- coding: utf-8 -*-
"""Per-turn prompt cache hit observation.

每一轮 LLM 调用的 usage 归一完成（usage ledger 写入点，见
``core.llm.client._record_usage_ledger_event``）后：

1. 发一条 ``llm.prompt_cache.observed`` 场景事件（component=llm，
   phase=cache），字段：sessionId/turnId/profileId/model +
   cacheHitTokens/cacheMissTokens/hitRatio/inputTokens（及
   cacheUsageObserved / cacheUsageMissingReason 语义位）；
2. 落一行人读摘要到 conversation debug jsonl（tag=LLM，对齐
   ``LLM TTFT breakdown`` 的落盘链路：core.logging.debug ->
   ConversationLogger.log_debug -> conversations/*.jsonl）；
3. 对同一会话（key = sessionId+profileId+model）相邻两次带真实 cache 遥测
   的调用做对比：上一次 hitRatio > 0.5 且本次 == 0 时补一条 warning 级
   ``llm.prompt_cache.hit_ratio_drop`` 观测，提示 prompt 前缀漂移，供归因。

纯观测，不改任何调用行为；合成流量不进入观测——startup warmup
（``llmWarmup`` 标记，与 ledger 的过滤同源）与显式探测
（``promptPurpose`` 标记，如 qwen inflight cache keepalive probe）都会被跳过，
否则探测流量会以高命中率混入相邻轮对比基线。无 session 上下文的调用
（后台工具/无会话探测）字段留空但事件照发：它们的 cache 遥测仍有观测价值，
只是不参与「相邻两轮」骤降对比（无会话连续性可言）。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Dict, Mapping, Optional

from .usage import cache_usage_observation_from_payload

PROMPT_CACHE_OBSERVED_EVENT_CODE = "llm.prompt_cache.observed"
PROMPT_CACHE_HIT_DROP_EVENT_CODE = "llm.prompt_cache.hit_ratio_drop"

#: 骤降告警阈值：上一次（同会话相邻）hitRatio 严格大于该值且本次 == 0 触发。
PROMPT_CACHE_DROP_PREVIOUS_RATIO_MIN = 0.5

#: 会话基线容量：每个 (sessionId, profileId, model) 只保留最近一次观测，
#: FIFO 防止长进程里键无界增长。
_SESSION_BASELINE_MAX_KEYS = 1024

# 注意与 core.llm.client.LLM_WARMUP_METADATA_KEY 保持同值；此处不 import
# client 以避免顶层互相依赖（client 顶层 import 本模块）。
_WARMUP_METADATA_KEY = "llmWarmup"

_SESSION_BASELINES: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()
_SESSION_BASELINES_LOCK = threading.Lock()


def reset_prompt_cache_baselines_for_tests() -> None:
    """Clear per-session baselines so tests start from a clean slate."""

    with _SESSION_BASELINES_LOCK:
        _SESSION_BASELINES.clear()


def _meta_str(metadata: Mapping[str, Any], camel_key: str, snake_key: str) -> str:
    if not isinstance(metadata, Mapping):
        return ""
    return str(metadata.get(camel_key) or metadata.get(snake_key) or "").strip()


def _is_synthetic_traffic(meta: Mapping[str, Any]) -> bool:
    """Warmup probes and explicit-purpose probes never enter observation."""

    if not isinstance(meta, Mapping):
        return False
    if meta.get(_WARMUP_METADATA_KEY):
        return True
    return bool(str(meta.get("promptPurpose") or "").strip())


def _record_scene_event(
    phase: str,
    event_code: str,
    *,
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: Dict[str, Any] | None = None,
) -> None:
    """Best-effort scene record; observation must never raise to the caller."""

    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "llm",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=False,
        )
    except Exception:  # noqa: BLE001 - diagnostics about diagnostics stay silent
        return


def _log_human_line(message: str, *, level: str = "info") -> None:
    """Mirror the ``LLM TTFT breakdown`` sink: debug(tag=LLM) -> conversation jsonl."""

    try:
        from core.logging import debug as _debug_logger

        if level == "warning":
            _debug_logger.warning(message, tag="LLM")
        else:
            _debug_logger.info(message, tag="LLM")
    except Exception:  # noqa: BLE001
        return


def _register_and_detect_drop(
    *,
    session_id: str,
    profile_id: str,
    model: str,
    turn_id: str,
    hit_tokens: int,
    hit_ratio: float,
    input_tokens: int,
    cache_observed: bool,
) -> Optional[Dict[str, Any]]:
    """Update the per-session baseline; return warning fields on a sharp drop.

    Baselines only advance on calls with real cache telemetry: a round where
    the provider omitted cache counters (``cacheUsageObserved`` False) keeps
    the previous baseline instead of overwriting it with a meaningless 0.0.
    """

    if not session_id:
        # 无会话上下文（后台工具/探测调用）没有「相邻两轮」连续性，不参与对比。
        return None
    key = (session_id, profile_id, model)
    drop: Optional[Dict[str, Any]] = None
    with _SESSION_BASELINES_LOCK:
        previous = _SESSION_BASELINES.get(key)
        if (
            previous is not None
            and bool(previous.get("cacheUsageObserved"))
            and cache_observed
            and int(previous.get("inputTokens", 0) or 0) > 0
            and input_tokens > 0
            and float(previous.get("hitRatio", 0.0) or 0.0)
            > PROMPT_CACHE_DROP_PREVIOUS_RATIO_MIN
            and hit_ratio == 0.0
        ):
            drop = {
                "previousTurnId": str(previous.get("turnId", "") or ""),
                "previousHitRatio": float(previous.get("hitRatio", 0.0) or 0.0),
                "previousCacheHitTokens": int(previous.get("cacheHitTokens", 0) or 0),
                "dropTrigger": (
                    f"previousHitRatio>{PROMPT_CACHE_DROP_PREVIOUS_RATIO_MIN} "
                    "and currentHitRatio==0"
                ),
            }
        if cache_observed:
            _SESSION_BASELINES[key] = {
                "turnId": turn_id,
                "hitRatio": hit_ratio,
                "cacheHitTokens": hit_tokens,
                "inputTokens": input_tokens,
                "cacheUsageObserved": True,
            }
            _SESSION_BASELINES.move_to_end(key)
            while len(_SESSION_BASELINES) > _SESSION_BASELINE_MAX_KEYS:
                _SESSION_BASELINES.popitem(last=False)
    return drop


def observe_prompt_cache_usage(
    *,
    usage: Any,
    metadata: Optional[Mapping[str, Any]],
    provider: str = "",
    model: str = "",
    profile_id: str = "",
) -> None:
    """Emit one per-call prompt cache observation plus the drop warning.

    Called from the usage-ledger finalize point (after the warmup filter), so
    every completed invoke/stream that reaches the ledger also gets exactly
    one observation. Values come from the normalized ``UsageStats``: provider
    estimates never fabricate a cache ratio.
    """

    if usage is None:
        return
    meta = metadata if isinstance(metadata, Mapping) else {}
    if _is_synthetic_traffic(meta):
        return

    session_id = _meta_str(meta, "sessionId", "session_id")
    turn_id = _meta_str(meta, "turnId", "turn_id")
    invocation_id = _meta_str(meta, "invocationId", "invocation_id")
    agent_id = _meta_str(meta, "agentId", "agent_id")
    profile = str(profile_id or "").strip()
    model_name = str(model or "").strip()

    input_tokens = max(0, int(getattr(usage, "input_tokens", 0) or 0))
    output_tokens = max(0, int(getattr(usage, "output_tokens", 0) or 0))
    hit_tokens = max(0, int(getattr(usage, "cached_input_tokens", 0) or 0))
    if input_tokens:
        hit_tokens = min(hit_tokens, input_tokens)
    raw_usage = getattr(usage, "provider_raw_usage", {})
    cache_observed, missing_reason = cache_usage_observation_from_payload(raw_usage)
    hit_ratio = (
        round(hit_tokens / input_tokens, 4) if cache_observed and input_tokens > 0 else 0.0
    )
    miss_tokens = max(0, input_tokens - hit_tokens) if cache_observed else 0

    # Identity fields lead: scene telemetry keeps only the first 24 field keys.
    fields: Dict[str, Any] = {
        "sessionId": session_id,
        "turnId": turn_id,
        "profileId": profile,
        "model": model_name,
        "provider": str(provider or "").strip(),
        "cacheHitTokens": hit_tokens,
        "cacheMissTokens": miss_tokens,
        "hitRatio": hit_ratio,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "cacheUsageObserved": cache_observed,
    }
    if invocation_id:
        fields["invocationId"] = invocation_id
    if agent_id:
        fields["agentId"] = agent_id
    if not cache_observed and missing_reason:
        fields["cacheUsageMissingReason"] = missing_reason

    _record_scene_event(
        "cache",
        PROMPT_CACHE_OBSERVED_EVENT_CODE,
        message="LLM prompt cache hit observation for one completed call.",
        level="info",
        outcome="observed",
        fields=fields,
    )
    _log_human_line(
        "LLM prompt cache: "
        f"session={session_id or '-'} turn={turn_id or '-'} "
        f"profile={profile or '-'} model={model_name or '-'} "
        f"hit={hit_tokens} miss={miss_tokens} ratio={hit_ratio} input={input_tokens}"
        + ("" if cache_observed else f" cacheUsageMissing={missing_reason}")
    )

    drop = _register_and_detect_drop(
        session_id=session_id,
        profile_id=profile,
        model=model_name,
        turn_id=turn_id,
        hit_tokens=hit_tokens,
        hit_ratio=hit_ratio,
        input_tokens=input_tokens,
        cache_observed=cache_observed,
    )
    if drop is not None:
        _record_scene_event(
            "cache",
            PROMPT_CACHE_HIT_DROP_EVENT_CODE,
            message=(
                "LLM prompt cache hit ratio dropped to 0 between adjacent "
                "calls of one session; likely prompt prefix drift."
            ),
            level="warning",
            outcome="observed",
            fields={**fields, **drop},
        )
        _log_human_line(
            "LLM prompt cache hit ratio drop: "
            f"session={session_id} turn={turn_id or '-'} model={model_name or '-'} "
            f"previousTurn={drop['previousTurnId'] or '-'} "
            f"previousRatio={drop['previousHitRatio']} currentRatio=0 "
            "(possible prompt prefix drift)",
            level="warning",
        )


__all__ = [
    "PROMPT_CACHE_DROP_PREVIOUS_RATIO_MIN",
    "PROMPT_CACHE_HIT_DROP_EVENT_CODE",
    "PROMPT_CACHE_OBSERVED_EVENT_CODE",
    "observe_prompt_cache_usage",
    "reset_prompt_cache_baselines_for_tests",
]
