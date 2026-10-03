# -*- coding: utf-8 -*-
"""协议族规则表（protocol family rule table）。

模型条目只需写身份（model/provider/label）+ 差异；协议默认值由族表统一供给。
协议翻译是 DATA（表驱动），不是代码分支；合成语义为稀疏 overlay：

    builtin family defaults  <  model_library 条目显式字段

条目字段为空（空串/空列表/None）或缺失时才落族默认；条目显式写了非空值
（哪怕与族默认不同）以条目为准。未知 model_protocol 一律不改写（返回空
dict），由 Wave1 校验闸（core/llm/discovery.llm_model_entry_issues）继续把关。

族划分从活配置（Documents/Vibelution/config/config.toml，21 provider / 66 条目）
与既有协议词表（core/llm/protocols.py ModelProtocol）归纳，不引入新协议名：

- ``deepseek_reasoning``：deepseek-v4* 条目（opencode_go / command_code / deepseek
  三个 provider）。reasoning_content 回放合同；deepseek provider 条目显式写了
  reasoning_state_field=reasoning_content，opencode_go/command_code 条目漏写
  ——正是族表要收敛的字段漂移。reasoning_effort_adapter=reasoning_effort 与
  values=[low,medium,high]/default=high 来自条目 defaults 的主流声明；adapter
  与 values 必须成对声明（Wave1：adapter 已声明但 values 为空即 error），
  所以族默认同时供给两者。
- ``openai_reasoning``：openai_responses / relay_responses 协议（Responses 线
  思考模型，如 gpt-5.6-*）。adapter=reasoning_object + values=[low,medium,high]
  + default=medium 与 llm_projection._default_v2_reasoning_effort_defaults 的
  既有先例一致；transport=responses 与 WIRE_SHAPED_MODEL_PROTOCOL_ALIASES 的
  协议→线映射一致。
- ``anthropic_thinking``：anthropic_thinking 协议。thinking_type=adaptive 驱动
  anthropic adapter 的 ``thinking: {"type": ...}`` 参数（adapters.py）。
- ``qwen_thinking``：qwen_thinking_no_prefill / llamacpp_qwen_thinking 协议。
  thinking_type 非空即 enable_thinking（payload_builder._payload_thinking_parameters
  与 protocol_resolver._thinking_enabled 的既有语义）。
- ``plain_chat``：无思考的常规 chat 工具协议（openai_chat_tools / minimax_chat /
  xiaomi_mimo_* / qwen_openai_compat / anthropic_chat）。basic/tool_chat 默认，
  无 reasoning_state_field、无 thinking、无 effort adapter。

不含 basic_chat_no_tools / llamacpp_basic（其合同默认是 basic_chat +
tool_calling_mode=disabled，与 plain_chat 的 tool_chat 默认不同族；活配置暂无
条目声明这两个协议，留给配置迁移波次）。
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

# 族名 -> 条目字段默认值。键是 runtime model_library 条目（config/llm_projection.
# project_v2_llm_for_runtime 投影后）的字段名；值为空串/空表的字段是显式的
# 「本族无此物」声明，落进条目后与缺省等价，仅为完整表达族的协议形状。
FAMILY_DEFAULTS: dict[str, dict[str, Any]] = {
    # deepseek reasoning_content 回放：chat_completions wire + reasoning_chat 合同。
    "deepseek_reasoning": {
        "transport": "chat_completions",
        "contract": "reasoning_chat",
        "reasoning_state_field": "reasoning_content",
        "thinking_type": "",
        "reasoning_effort_adapter": "reasoning_effort",
        "reasoning_effort_values": ["low", "medium", "high"],
        "default_reasoning_effort": "high",
        "tool_calling_mode": "auto",
    },
    # OpenAI Responses 思考线：reasoning_object 载荷，无独立 state 字段。
    "openai_reasoning": {
        "transport": "responses",
        "contract": "tool_chat",
        "reasoning_state_field": "",
        "thinking_type": "",
        "reasoning_effort_adapter": "reasoning_object",
        "reasoning_effort_values": ["low", "medium", "high"],
        "default_reasoning_effort": "medium",
        "tool_calling_mode": "auto",
    },
    # Anthropic thinking：thinking_type=adaptive -> thinking 参数（无 effort 梯度）。
    "anthropic_thinking": {
        "transport": "chat_completions",
        "contract": "tool_chat",
        "reasoning_state_field": "",
        "thinking_type": "adaptive",
        "reasoning_effort_adapter": "",
        "tool_calling_mode": "auto",
    },
    # Qwen thinking：thinking_type 非空即 enable_thinking=true（payload_builder）。
    "qwen_thinking": {
        "transport": "chat_completions",
        "contract": "tool_chat",
        "reasoning_state_field": "",
        "thinking_type": "adaptive",
        "reasoning_effort_adapter": "",
        "tool_calling_mode": "auto",
    },
    # 无思考常规 chat：basic/tool_chat 默认，协议翻译全走通用路径。
    "plain_chat": {
        "transport": "chat_completions",
        "contract": "tool_chat",
        "reasoning_state_field": "",
        "thinking_type": "",
        "reasoning_effort_adapter": "",
        "tool_calling_mode": "auto",
    },
}

# 族名 -> 该族覆盖的 model_protocol 词表（core/llm/protocols.py ModelProtocol 的子集）。
PROTOCOL_FAMILY_VOCABULARY: dict[str, tuple[str, ...]] = {
    "deepseek_reasoning": ("deepseek_reasoning",),
    "openai_reasoning": ("openai_responses", "relay_responses"),
    "anthropic_thinking": ("anthropic_thinking",),
    "qwen_thinking": ("qwen_thinking_no_prefill", "llamacpp_qwen_thinking"),
    "plain_chat": (
        "openai_chat_tools",
        "minimax_chat",
        "xiaomi_mimo_multimodal_openai_compat",
        "xiaomi_mimo_token_plan_openai_compat",
        "qwen_openai_compat",
        "anthropic_chat",
    ),
}

_PROTOCOL_FAMILY_BY_PROTOCOL: dict[str, str] = {
    protocol: family
    for family, protocols in PROTOCOL_FAMILY_VOCABULARY.items()
    for protocol in protocols
}

__all__ = [
    "FAMILY_DEFAULTS",
    "PROTOCOL_FAMILY_VOCABULARY",
    "apply_model_entry_family_defaults",
    "protocol_family_for_entry",
    "resolve_model_entry_family_defaults",
]


def protocol_family_for_entry(entry: Any) -> str:
    """返回条目所属协议族名；未知/缺失协议返回空串。"""
    if not isinstance(entry, Mapping):
        return ""
    # runtime 条目用 protocol（llm_projection 投影自 model_protocol）；
    # canonical 输入侧条目保留 model_protocol 原名，两处都认。
    protocol = str(entry.get("protocol") or entry.get("model_protocol") or "").strip().lower()
    return _PROTOCOL_FAMILY_BY_PROTOCOL.get(protocol, "")


def _entry_value_blank(value: Any) -> bool:
    """条目字段「为空」判定：缺失/None/空白串/空容器都算空，落族默认。"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def resolve_model_entry_family_defaults(entry: Any) -> dict[str, Any]:
    """给定 model_library 条目，返回需要落下去的族默认值（稀疏 dict）。

    只包含条目当前为空/缺失、且族默认值本身非空的字段（族表里的空串/空表
    声明只表达「本族无此物」的形状，不产生落默认动作）；条目显式写了非空值
    的字段不出现在结果里（operator 显式声明永远赢）。未知协议族返回空 dict
    （不改写）。
    """
    family = protocol_family_for_entry(entry)
    if not family:
        return {}
    defaults = FAMILY_DEFAULTS.get(family)
    if not defaults:
        return {}
    resolved: dict[str, Any] = {}
    for key, value in defaults.items():
        if _entry_value_blank(value):
            continue
        if _entry_value_blank(entry.get(key)):
            resolved[key] = copy.deepcopy(value)
    return resolved


def apply_model_entry_family_defaults(entry: Any) -> dict[str, Any]:
    """返回合成后的条目视图：族默认填进空/缺失字段，条目显式值原样保留。

    合成层唯一入口（build_llm_profile_from_model_entry 调用）；结果不回写
    配置存储，只影响运行档案构造。
    """
    if not isinstance(entry, Mapping):
        return {}
    merged = dict(entry)
    for key, value in resolve_model_entry_family_defaults(entry).items():
        merged[key] = value
    return merged
