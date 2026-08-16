# -*- coding: utf-8 -*-
"""子 agent 角色模型。

从全局职责上定义子 agent 的系统角色，而不是只在局部启发式里判断 task_type。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class SubagentRoleSpec:
    task_type: str
    role_name: str
    system_purpose: str
    owned_work: Tuple[str, ...]
    forbidden_work: Tuple[str, ...]
    return_shape: str


@dataclass(frozen=True)
class SubagentRoleNeed:
    task_type: str
    trigger_reason: str
    why_now: str


_ROLE_SPECS: Dict[str, SubagentRoleSpec] = {
    "diagnose": SubagentRoleSpec(
        task_type="diagnose",
        role_name="局部故障归因器",
        system_purpose="隔离高噪音的失败归因工作，为主 agent 产出可裁决的异常证据。",
        owned_work=(
            "定位重复调用、漂移、超时、验证失败、traceback 等局部异常线索",
            "把失败现象压缩成最短证据链与下一步建议",
        ),
        forbidden_work=(
            "不负责跨模块方案选择",
            "不负责直接修改代码或替主 agent 做最终裁决",
        ),
        return_shape="返回异常摘要、命中证据、局部发现与建议的下一步。",
    ),
    "inspect": SubagentRoleSpec(
        task_type="inspect",
        role_name="局部状态探针",
        system_purpose="隔离局部查阅和一致性核查，减少主 agent 在静态阅读上的工作记忆负担。",
        owned_work=(
            "对单段链路、配置、prompt、局部修改范围做静态核查",
            "把分散片段压缩成是否一致、哪里不一致、还缺什么证据",
        ),
        forbidden_work=(
            "不负责故障根因裁决",
            "不负责把局部观察直接扩大成全局方案",
        ),
        return_shape="返回局部状态摘要、一致性判断、缺口说明与建议的下一步。",
    ),
    "summarize": SubagentRoleSpec(
        task_type="summarize",
        role_name="证据压缩器",
        system_purpose="把已存在的局部证据压缩成低熵结论，帮助主 agent 收束上下文。",
        owned_work=(
            "整理已有 findings、validation、blockers、modified_paths",
            "在不新增探查链路的前提下压缩成结论草案与证据包",
        ),
        forbidden_work=(
            "不负责继续探路或扩展读取范围",
            "不负责把摘要结果当成最终决策落地",
        ),
        return_shape="返回压缩后的结论、关键证据、剩余缺口与建议的下一步。",
    ),
}

ALLOWED_SUBAGENT_TASK_TYPES = frozenset(_ROLE_SPECS.keys())


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


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    value = _decode_binary(value)
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_task_type(value: Any) -> str:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        extracted = _mapping_get(value, "task_type", "taskType", "type", "role")
        if extracted is None:
            return ""
        return _coerce_task_type(extracted)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        if len(value) == 1:
            return _coerce_task_type(value[0])
        return ""
    return _coerce_text(value)


def _coerce_prompt(value: Any) -> str:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        extracted = _mapping_get(value, "prompt", "text", "goal", "content", "message")
        if extracted is None:
            return ""
        return _coerce_prompt(extracted)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        parts = [_coerce_prompt(item) for item in value]
        return "\n".join(part for part in parts if part)
    return _coerce_text(value)


def get_subagent_role_spec(task_type: str) -> SubagentRoleSpec:
    normalized = _coerce_task_type(task_type).strip().lower().replace("-", "_").replace(" ", "_")
    normalized = normalized or "inspect"
    return _ROLE_SPECS.get(normalized, _ROLE_SPECS["inspect"])


def extract_subagent_primary_goal(prompt: str | None) -> str:
    """从子 agent 的瘦提示词中提取唯一目标，避免整段模板污染 current_goal。"""
    text = _coerce_prompt(prompt).strip()
    if not text:
        return ""

    match = re.search(r"^\-\s*当前唯一目标:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    if match:
        goal = match.group(1).strip()
        if goal:
            return goal

    return text
