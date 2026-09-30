#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具结果 resultBudget：按工具声明的模型可见预算。

借鉴 ZCode ``tool/executor/result-serialization`` 的语义（只借策略，不引代码）：

- 每个工具可声明 ``ToolResultBudget``：``max_inline_chars``（收口点打包上限）、
  ``max_model_chars``（模型可见 Result 段硬上限，``[Tool Result Facts]`` 事实头
  为固定协议开销，不计入预算）、``strategy``（truncate | artifact）、
  ``preview``（head | tail）。
- 未声明的工具保持现状行为：原始结果原样进入既有打包/渲染路径，逐字节等价。
- 超预算且 strategy=artifact：全文落盘（``tool_result_artifact``），模型拿到
  引用 + sha256 + 预览 + 结构化后缀；落盘失败静默回退截断档（成功调用不因
  落盘失败变失败），回退原因记入 outcome 供审计。
- 截断档统一结构化后缀：``original_chars / model_chars / strategy``。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from core.infrastructure.tool_result_artifact import (
    write_tool_result_artifact,
)
from core.logging import debug as _debug_logger

STRATEGY_TRUNCATE = "truncate"
STRATEGY_ARTIFACT = "artifact"

PREVIEW_HEAD = "head"
PREVIEW_TAIL = "tail"

# model_chars 的下限：保证结构化后缀与至少一小段预览能放进预算内。
MIN_MODEL_CHARS = 200

# 工具名 -> 预算声明。缺省为空：未声明工具保持现状行为（逐字节等价）。
_TOOL_RESULT_BUDGETS: dict[str, "ToolResultBudget"] = {}
_REGISTRY_LOCK = threading.Lock()


@dataclass(frozen=True)
class ToolResultBudget:
    """单工具的结果预算声明。"""

    max_model_chars: int
    max_inline_chars: int = 0  # 0 = 跟随 max_model_chars
    strategy: str = STRATEGY_TRUNCATE
    preview: str = PREVIEW_HEAD

    def __post_init__(self) -> None:
        model = max(MIN_MODEL_CHARS, int(self.max_model_chars or 0))
        inline = int(self.max_inline_chars or 0) or model
        inline = max(model, inline)
        strategy = str(self.strategy or STRATEGY_TRUNCATE).strip().lower()
        if strategy not in {STRATEGY_TRUNCATE, STRATEGY_ARTIFACT}:
            strategy = STRATEGY_TRUNCATE
        preview = str(self.preview or PREVIEW_HEAD).strip().lower()
        if preview not in {PREVIEW_HEAD, PREVIEW_TAIL}:
            preview = PREVIEW_HEAD
        object.__setattr__(self, "max_model_chars", model)
        object.__setattr__(self, "max_inline_chars", inline)
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(self, "preview", preview)

    @property
    def packaging_max_chars(self) -> int:
        """声明工具在收口点打包/渲染层使用的限长（与 DEFAULT_MAX_CHARS 取大）。"""
        return max(self.max_inline_chars, self.max_model_chars)


@dataclass
class ToolResultBudgetOutcome:
    """一次预算执行的审计结果；content 为模型可见的预算化文本。"""

    content: str
    strategy: str
    original_chars: int
    model_chars: int
    artifact_ref: str = ""
    artifact_sha256: str = ""
    artifact_path: str = ""
    fallback_reason: str = ""
    preview_direction: str = PREVIEW_HEAD
    extra: dict[str, Any] = field(default_factory=dict)


def register_tool_result_budget(tool_name: str, budget: ToolResultBudget) -> None:
    """声明/覆盖单工具预算（工具注册与测试使用）。"""
    name = str(tool_name or "").strip()
    if not name:
        return
    with _REGISTRY_LOCK:
        _TOOL_RESULT_BUDGETS[name] = budget


def get_tool_result_budget(tool_name: str) -> Optional[ToolResultBudget]:
    name = str(tool_name or "").strip()
    if not name:
        return None
    with _REGISTRY_LOCK:
        return _TOOL_RESULT_BUDGETS.get(name)


def clear_tool_result_budgets() -> None:
    """清空全部声明（测试隔离用）。"""
    with _REGISTRY_LOCK:
        _TOOL_RESULT_BUDGETS.clear()


def serialize_tool_result(result: Any) -> str:
    """与 ``package_tool_result`` 相同口径的序列化，保证预算判定与打包一致。"""
    if isinstance(result, (bytes, bytearray)):
        try:
            return result.decode("utf-8", errors="replace")
        except Exception:
            return str(result)
    if isinstance(result, (dict, list)):
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(result)
    return str(result)


def apply_tool_result_budget(
    result: Any,
    *,
    tool_name: str,
    tool_call_id: str = "",
) -> tuple[Any, Optional[ToolResultBudgetOutcome]]:
    """在收口点对单条工具结果执行预算；返回 ``(进入打包的结果, 审计 outcome)``。

    - 未声明预算或未超预算：原样返回 result（不重新序列化，逐字节等价），
      outcome 为 ``None``。
    - 超预算：按声明 strategy 落盘或截断，返回预算化字符串与 outcome；
      artifact 落盘失败回退截断并在 outcome 记录原因。
    """
    budget = get_tool_result_budget(tool_name)
    if budget is None:
        return result, None

    content = serialize_tool_result(result)
    original_chars = len(content)
    if original_chars <= budget.max_model_chars:
        return result, None

    if budget.strategy == STRATEGY_ARTIFACT:
        try:
            artifact = write_tool_result_artifact(
                content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
            )
        except Exception as exc:
            # 落盘失败不把成功工具调用变成失败：静默回退截断档并记审计字段。
            _debug_logger.warning(
                f"[工具结果预算] artifact 落盘失败，回退截断: "
                f"tool={tool_name} {type(exc).__name__}: {exc}",
                tag="TOOL_RESULT",
            )
            budgeted = _truncate_with_suffix(content, budget, original_chars, fallback_reason=type(exc).__name__)
            return budgeted, ToolResultBudgetOutcome(
                content=budgeted,
                strategy="artifact_fallback_truncate",
                original_chars=original_chars,
                model_chars=budget.max_model_chars,
                fallback_reason=f"{type(exc).__name__}: {exc}"[:200],
                preview_direction=budget.preview,
            )
        budgeted = _artifact_placeholder_content(content, budget, original_chars, artifact)
        outcome = ToolResultBudgetOutcome(
            content=budgeted,
            strategy=STRATEGY_ARTIFACT,
            original_chars=original_chars,
            model_chars=budget.max_model_chars,
            artifact_ref=str(artifact.get("artifactRef") or ""),
            artifact_sha256=str(artifact.get("sha256") or ""),
            artifact_path=str(artifact.get("path") or ""),
            preview_direction=budget.preview,
        )
        return budgeted, outcome

    budgeted = _truncate_with_suffix(content, budget, original_chars)
    return budgeted, ToolResultBudgetOutcome(
        content=budgeted,
        strategy=STRATEGY_TRUNCATE,
        original_chars=original_chars,
        model_chars=budget.max_model_chars,
        preview_direction=budget.preview,
    )


def _budget_suffix(
    budget: ToolResultBudget,
    original_chars: int,
    *,
    strategy: str,
    artifact_ref: str = "",
    artifact_sha256: str = "",
    fallback_reason: str = "",
) -> str:
    parts = [
        f"strategy={strategy}",
        f"original_chars={original_chars}",
        f"model_chars={budget.max_model_chars}",
    ]
    if artifact_ref:
        parts.append(f"artifact_ref={artifact_ref}")
    if artifact_sha256:
        parts.append(f"sha256={artifact_sha256}")
    if fallback_reason:
        parts.append(f"fallback={fallback_reason}")
    return "[工具结果预算] " + ", ".join(parts)


def _truncate_with_suffix(
    content: str,
    budget: ToolResultBudget,
    original_chars: int,
    *,
    fallback_reason: str = "",
) -> str:
    strategy = "artifact_fallback_truncate" if fallback_reason else STRATEGY_TRUNCATE
    suffix = _budget_suffix(
        budget,
        original_chars,
        strategy=strategy,
        fallback_reason=fallback_reason,
    )
    body_budget = budget.max_model_chars - len(suffix) - 1
    if body_budget <= 0:
        return suffix[: budget.max_model_chars]
    if budget.preview == PREVIEW_TAIL:
        body = content[-body_budget:]
    else:
        body = content[:body_budget]
    return f"{body}\n{suffix}"


def _artifact_placeholder_content(
    content: str,
    budget: ToolResultBudget,
    original_chars: int,
    artifact: dict[str, Any],
) -> str:
    artifact_ref = str(artifact.get("artifactRef") or "")
    digest = str(artifact.get("sha256") or "")
    suffix = _budget_suffix(
        budget,
        original_chars,
        strategy=STRATEGY_ARTIFACT,
        artifact_ref=artifact_ref,
        artifact_sha256=digest,
    )
    frame_lines = [
        "[工具结果已落盘] 原始结果全文已保存为本地 artifact，以下仅含引用与预览。",
        f"artifact_ref: {artifact_ref}",
        f"sha256: {digest}",
        "原始全文需完整内容时按 artifact_ref 或 tool_call_id 检索本地 artifact。",
    ]
    frame = "\n".join(frame_lines)
    preview_open = "--- 预览 ---"
    preview_close = "--- 预览结束 ---"
    frame_budget = len(frame) + len(suffix) + len(preview_open) + len(preview_close) + 5
    preview_budget = max(0, budget.max_model_chars - frame_budget)
    if preview_budget <= 0:
        return f"{frame}\n{suffix}"[: budget.max_model_chars]
    if budget.preview == PREVIEW_TAIL:
        preview = content[-preview_budget:]
    else:
        preview = content[:preview_budget]
    placeholder = f"{frame}\n{preview_open}\n{preview}\n{preview_close}\n{suffix}"
    if len(placeholder) > budget.max_model_chars:
        placeholder = f"{frame}\n{suffix}"
    return placeholder


__all__ = [
    "MIN_MODEL_CHARS",
    "PREVIEW_HEAD",
    "PREVIEW_TAIL",
    "STRATEGY_ARTIFACT",
    "STRATEGY_TRUNCATE",
    "ToolResultBudget",
    "ToolResultBudgetOutcome",
    "apply_tool_result_budget",
    "clear_tool_result_budgets",
    "get_tool_result_budget",
    "register_tool_result_budget",
    "serialize_tool_result",
]
