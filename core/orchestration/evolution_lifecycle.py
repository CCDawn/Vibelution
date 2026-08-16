# -*- coding: utf-8 -*-
"""演化事务的生命周期目标识别，不参与对话 Agent 的任务路由或委派。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


_GOAL_KEYS = ("goal", "text", "message", "content", "goalText", "goal_text")


def _decode_binary(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return value


def _maybe_json(value: Any) -> Any:
    value = _decode_binary(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _mapping_get(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _coerce_goal_text(value: Any) -> str:
    if value is None:
        return ""
    value = _maybe_json(_decode_binary(value))
    if isinstance(value, Mapping):
        extracted = _mapping_get(value, *_GOAL_KEYS)
        if extracted is None:
            return ""
        return _coerce_goal_text(extracted)
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, Sequence):
        parts = [_coerce_goal_text(item) for item in value]
        return " ".join(part for part in parts if part)
    return str(value).strip().lower()


def _contains_restart_marker(text: str, marker: str) -> bool:
    haystack = _coerce_goal_text(text)
    needle = _coerce_goal_text(marker)
    if not haystack or not needle:
        return False
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            return False
        # "未完成重启" contains "完成重启" but is a status check, not a restart order.
        if needle == "完成重启" and index > 0 and haystack[index - 1] == "未":
            start = index + 1
            continue
        return True


def is_restart_focused_goal(goal: str) -> bool:
    """识别显式要求自我重启、且未被否定的目标。"""
    text = _coerce_goal_text(goal)
    if not text:
        return False
    negative_markers = (
        "不要调用 trigger_self_restart_tool",
        "不调用 trigger_self_restart_tool",
        "禁止调用 trigger_self_restart_tool",
        "不要触发重启",
        "不触发重启",
        "禁止重启",
        "不要重启",
        "不重启",
        "do not call trigger_self_restart_tool",
        "don't call trigger_self_restart_tool",
        "do not restart",
        "don't restart",
        "without restart",
        "non-restart",
    )
    if any(marker in text for marker in negative_markers):
        return False
    restart_markers = (
        "trigger_self_restart_tool",
        "重启你自己",
        "重启自己",
        "完成重启",
        "触发重启",
        "执行重启",
        "restart yourself",
        "self restart",
        "self-restart",
    )
    return any(_contains_restart_marker(text, marker) for marker in restart_markers)


def is_full_evolution_goal(goal: str) -> bool:
    """识别需要关账成功后继续触发自我重启的完整进化闭环目标。"""
    text = _coerce_goal_text(goal)
    if not text or not is_restart_focused_goal(text):
        return False
    close_markers = (
        "close_evolution_transaction_tool",
        "关账",
        "关闭演化事务",
        "close transaction",
        "close evolution transaction",
    )
    return any(marker in text for marker in close_markers)
