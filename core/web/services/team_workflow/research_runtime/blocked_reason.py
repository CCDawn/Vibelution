"""User-readable workflow block reasons from ledger problem JSON."""

from __future__ import annotations

import json
from typing import Any


def parse_problem_json(raw: str | None) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return {"code": "workflow_blocked", "detail": text}
    if not isinstance(payload, dict):
        return {"code": "workflow_blocked", "detail": text}
    nested = payload.get("detail")
    if isinstance(nested, str):
        stripped = nested.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                inner = json.loads(stripped)
            except (TypeError, ValueError):
                inner = None
            if isinstance(inner, dict):
                code = str(inner.get("code") or payload.get("code") or "").strip()
                detail = str(inner.get("detail") or nested)
                result: dict[str, Any] = {
                    "code": code or "workflow_blocked",
                    "detail": detail,
                }
                if "retryable" in inner:
                    result["retryable"] = bool(inner.get("retryable"))
                elif "retryable" in payload:
                    result["retryable"] = bool(payload.get("retryable"))
                _copy_explicit_problem_fields(result, payload, inner)
                return result
    code = str(payload.get("code") or "").strip()
    detail = payload.get("detail")
    result = {
        "code": code or "workflow_blocked",
        "detail": "" if detail is None else str(detail),
    }
    if "retryable" in payload:
        result["retryable"] = bool(payload.get("retryable"))
    _copy_explicit_problem_fields(result, payload)
    return result


def _copy_explicit_problem_fields(
    target: dict[str, Any],
    *sources: dict[str, Any],
) -> None:
    for source in sources:
        for key in ("failureClass", "message", "blockerIds"):
            if key in source:
                target[key] = source.get(key)


def problem_from_graph_error(detail: str) -> dict[str, str]:
    message = str(detail or "").strip()
    if "中断于" in message and "dispatch 目标是" in message:
        return {"code": "checkpoint_node_mismatch", "detail": message}
    lowered = message.lower()
    if "unknown iteration decision" in lowered or "unknown governed decision" in lowered:
        return {"code": "iteration_decision_invalid", "detail": message}
    return {"code": "graph_dispatch_invalid", "detail": message}


def format_blocked_reason(
    problem: dict[str, Any] | None,
    *,
    fallback: str | None = None,
) -> str:
    if not problem:
        return str(fallback or "").strip()
    code = str(problem.get("code") or "").strip()
    detail = str(problem.get("detail") or "").strip()
    if code == "checkpoint_node_mismatch":
        return detail or "检查点仍停留在前驱节点，无法从当前节点恢复。"
    if code == "required_artifact_missing":
        return f"缺少必需产物：{detail}" if detail else "缺少必需产物"
    if code == "iteration_decision_invalid":
        return f"迭代决策无效：{detail}" if detail else "迭代决策无效"
    if code == "auto_advance_not_ready":
        return f"自动推进未就绪：{detail}" if detail else "自动推进未就绪"
    if code == "graph_dispatch_invalid":
        return detail or "图调度失败"
    if detail:
        return detail
    return code or str(fallback or "").strip()
