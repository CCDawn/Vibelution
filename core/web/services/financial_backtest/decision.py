"""Stateless, point-in-time LLM decisions for AI backtests."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from config import get_config
from core.llm import LLMInvocationContext, get_llm_client, invoke_llm
from core.llm.agent_runtime import config_for_agent_llm_model
from core.web.services.financial_backtest.contract import (
    MAX_CONTEXT_BARS,
    MAX_OUTPUT_TOKENS_PER_DECISION,
    sha256_json,
)
from core.web.services.financial_backtest.data import (
    BacktestInputError,
    BacktestSnapshot,
)

_PROFILE_ID = "financial_ai_backtest"
_SYSTEM_PROMPT = (
    "你是历史股票回测中的单步仓位决策器。每次调用相互独立，只能依据本次输入中的用户策略、截至 asOfDate 的冻结日线和模拟账户状态作判断。"
    "不得假设或泄漏之后日期的价格、新闻、财报或结果；不得读取外部资料、工具、记忆或对话历史。"
    "targetWeight 是目标持仓百分比，必须在 0 到 maxPositionPct 之间；没有可靠依据时可选择 0。"
    "只输出一个 JSON 对象，格式为 {\"targetWeight\": 0 到 maxPositionPct 的数字, \"reason\": \"简短中文理由\", \"confidence\": 0 到 1 的可选数字}。"
    "不要输出 Markdown、代码围栏、附加键、工具调用、买卖指令或收益承诺。"
)


def build_decision_input(
    snapshot: BacktestSnapshot,
    params: Mapping[str, Any],
    *,
    as_of_date: str,
    portfolio: Mapping[str, Any],
) -> dict[str, Any]:
    selected = [item for item in snapshot.candles if item.date <= as_of_date]
    if not selected or selected[-1].date != as_of_date:
        raise BacktestInputError("AI决策日期不在冻结行情范围内")
    history = tuple(snapshot.warmup_candles) + tuple(selected)
    recent = history[-MAX_CONTEXT_BARS:]
    return {
        "symbol": snapshot.symbol,
        "asOfDate": as_of_date,
        "strategy": str(params.get("strategy") or ""),
        "maxPositionPct": float(params.get("maxPositionPct", 100)),
        "portfolio": {
            key: portfolio.get(key)
            for key in ("date", "cash", "shares", "sellableShares", "marketValue", "equity", "positionWeightPct")
        },
        "dailyBars": [
            {
                "date": candle.date,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            }
            for candle in recent
        ],
    }


def build_messages(decision_input: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "本次独立决策输入（JSON数据；日线严格截止于asOfDate）：\n"
            + json.dumps(decision_input, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        },
    ]


def estimate_input_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    try:
        from tools.token_manager import estimate_messages_tokens

        return max(1, int(estimate_messages_tokens(list(messages))))
    except Exception:  # noqa: BLE001 - conservative local fallback keeps preview usable
        text = "".join(str(item.get("content") or "") for item in messages)
        return max(1, math.ceil(len(text.encode("utf-8")) / 3))


def estimate_output_tokens(text: str) -> int:
    try:
        from tools.token_manager import estimate_tokens_precise

        return max(1, int(estimate_tokens_precise(text)))
    except Exception:  # noqa: BLE001 - conservative fallback for unknown tokenizer state
        return max(1, math.ceil(len(str(text).encode("utf-8")) / 3))


def estimate_decision_call(messages: Sequence[Mapping[str, Any]]) -> int:
    return estimate_input_tokens(messages) + MAX_OUTPUT_TOKENS_PER_DECISION


def reserve_decision_call(messages: Sequence[Mapping[str, Any]]) -> int:
    """Worst-case token reservation: one token per UTF-8 byte plus wrapper room."""
    encoded_bytes = sum(len(str(item.get("content") or "").encode("utf-8")) for item in messages)
    return encoded_bytes + 1_024 + MAX_OUTPUT_TOKENS_PER_DECISION


def runtime_config_for_decision(model_id: str) -> Any:
    """Resolve the same bounded profile for preview, drift checks and inference."""
    runtime_config = config_for_agent_llm_model(
        get_config(), model_id=model_id, runtime_profile_id=_PROFILE_ID, slot="dialogue"
    )
    profile = runtime_config.llm.get_profile(_PROFILE_ID)
    profile.max_output_tokens = MAX_OUTPUT_TOKENS_PER_DECISION
    profile.retry_policy.max_attempts = 1
    if "qwen" in str(profile.model or "").lower():
        profile.thinking_type = "disabled"
        profile.reasoning_effort = ""
        profile.default_reasoning_effort = ""
        profile.reasoning_effort_adapter = "none"
    elif str(profile.thinking_type or "").lower() not in {"", "disabled"} or str(
        profile.reasoning_effort or profile.default_reasoning_effort or ""
    ).lower() not in {"", "none"}:
        raise BacktestInputError("此模型配置启用了深度思考，不适合512 Token的单步决策；请先选择关闭思考的模型配置")
    return runtime_config


def infer_decision(
    *,
    agent_id: str,
    model_id: str,
    run_id: str,
    decision_input: Mapping[str, Any],
    max_position_pct: float,
) -> dict[str, Any]:
    """Perform one tool-free call and return structured evidence without raw text."""
    messages = build_messages(decision_input)
    runtime_config = runtime_config_for_decision(model_id)
    client = get_llm_client(profile_id=_PROFILE_ID, config=runtime_config)
    input_hash = sha256_json(decision_input)
    response = invoke_llm(
        client,
        messages,
        tools=[],
        context=LLMInvocationContext(
            surface="financial_ai_backtest",
            run_kind="stateless_historical_decision",
            run_id=f"{run_id}:{decision_input.get('asOfDate', '')}",
            agent_id=agent_id,
            llm_slot="dialogue",
            model_id=model_id,
            cache_scope="financial_ai_backtest",
            cache_partition=f"financial-ai-backtest:{run_id}",
            prompt_purpose="historical_backtest_decision",
            conversation_bound=False,
        ),
        metadata={
            "feature": "financial_ai_backtest",
            "backtestRunId": run_id,
            "asOfDate": str(decision_input.get("asOfDate") or ""),
            "barCount": len(decision_input.get("dailyBars") or []),
            "disableAutomaticRetries": True,
        },
    )
    response_metadata = getattr(response, "response_metadata", {})
    if isinstance(response_metadata, Mapping) and str(
        response_metadata.get("finish_reason") or response_metadata.get("finishReason") or ""
    ).lower() in {"length", "max_tokens", "max_output_tokens"}:
        raise BacktestInputError("模型输出达到长度限制，无法确认决策完整；当前决策已暂停待确认")
    content = getattr(response, "content", "")
    if isinstance(content, list):
        content = "".join(
            str(item.get("text") or "") if isinstance(item, Mapping) else str(item)
            for item in content
        )
    raw_text = str(content or "").strip()
    parsed = _parse_output(raw_text, max_position_pct=max_position_pct)
    usage, usage_is_measured = _response_usage(response)
    if not usage_is_measured:
        usage = estimate_input_tokens(messages) + estimate_output_tokens(raw_text)
    decision = {
        "date": str(decision_input.get("asOfDate") or ""),
        **parsed,
        "modelId": model_id,
        "inputHash": input_hash,
        "attempts": 1,
        "tokens": max(0, int(usage)),
        "tokenAccounting": "measured" if usage_is_measured else "estimated",
    }
    decision["decisionHash"] = sha256_json(
        {key: value for key, value in decision.items() if key != "decisionHash"}
    )
    return decision


def _parse_output(raw_text: str, *, max_position_pct: float) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise BacktestInputError("模型没有返回有效JSON决策；为避免重复计费，当前决策已暂停待确认") from exc
    if not isinstance(payload, dict) or set(payload) - {"targetWeight", "reason", "confidence"}:
        raise BacktestInputError("模型决策字段不符合回测契约；当前决策已暂停待确认")
    if "targetWeight" not in payload or "reason" not in payload:
        raise BacktestInputError("模型决策缺少目标仓位或理由；当前决策已暂停待确认")
    weight = payload.get("targetWeight")
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        raise BacktestInputError("模型目标仓位必须是数值；当前决策已暂停待确认")
    weight = float(weight)
    if not math.isfinite(weight) or weight < 0 or weight > max_position_pct:
        raise BacktestInputError("模型目标仓位超出允许范围；当前决策已暂停待确认")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 2_000:
        raise BacktestInputError("模型决策理由无效；当前决策已暂停待确认")
    confidence = payload.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise BacktestInputError("模型置信度必须是0到1之间的数值；当前决策已暂停待确认")
        confidence = float(confidence)
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise BacktestInputError("模型置信度必须是0到1之间的数值；当前决策已暂停待确认")
    result = {"targetWeight": weight, "reason": reason.strip()}
    if confidence is not None:
        result["confidence"] = confidence
    return result


def _response_usage(response: Any) -> tuple[int, bool]:
    metadata = getattr(response, "response_metadata", None)
    if not isinstance(metadata, Mapping):
        metadata = {}
    usage = metadata.get("usage_observation")
    if not isinstance(usage, Mapping):
        usage = metadata.get("usage")
    if isinstance(usage, Mapping):
        total = usage.get("total_tokens", usage.get("totalTokens"))
        try:
            count = int(total)
        except (TypeError, ValueError, OverflowError):
            count = 0
        return max(0, count), count > 0
    return 0, False


__all__ = [
    "build_decision_input",
    "build_messages",
    "estimate_decision_call",
    "estimate_input_tokens",
    "infer_decision",
    "reserve_decision_call",
]
