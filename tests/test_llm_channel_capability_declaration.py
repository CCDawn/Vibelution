"""通道能力声明：配置声明的「这条通道不吃某参数」必须早于 400 探测生效。

背景：opencode go 经 litellm 中转池访问 deepseek-v4.1-flash 时，带
``reasoning_effort`` 的请求会被池内部分节点以 400 拒绝。既有做法是收到 400
后剥参重发，再把结论缓存成 per-route 负缓存；也就是能力事实只能靠运行时
探测学习。这组测试固定新契约：operator 可以在模型条目 capabilities 里直接
声明 ``supports_reasoning_effort = false``，声明在首发前就生效。
"""

from __future__ import annotations

from core.llm import discovery
from core.llm.client import _strip_declared_unsupported_params
from core.llm.types import LLMCapabilities


def test_declared_unsupported_param_is_stripped_before_send() -> None:
    payload = {"model": "deepseek-v4.1-flash", "reasoning_effort": "high", "messages": []}
    capabilities = LLMCapabilities(supports_reasoning_effort=False)

    stripped, names = _strip_declared_unsupported_params(payload, capabilities)

    assert names == ("reasoning_effort",)
    assert "reasoning_effort" not in stripped
    assert stripped["model"] == "deepseek-v4.1-flash"
    # 原 payload 不被就地改写：调用方仍持有组装结果。
    assert payload["reasoning_effort"] == "high"


def test_capability_default_keeps_the_parameter() -> None:
    payload = {"model": "m", "reasoning_effort": "low"}
    capabilities = LLMCapabilities()

    stripped, names = _strip_declared_unsupported_params(payload, capabilities)

    assert names == ()
    assert stripped["reasoning_effort"] == "low"


def test_declaration_without_the_parameter_is_a_no_op() -> None:
    payload = {"model": "m"}
    capabilities = LLMCapabilities(supports_reasoning_effort=False)

    stripped, names = _strip_declared_unsupported_params(payload, capabilities)

    assert names == ()
    assert stripped == {"model": "m"}


def test_missing_capabilities_object_is_tolerated() -> None:
    payload = {"model": "m", "reasoning_effort": "high"}

    stripped, names = _strip_declared_unsupported_params(payload, None)

    assert names == ()
    assert stripped["reasoning_effort"] == "high"


def test_capabilities_declaration_is_read_from_the_model_entry() -> None:
    overrides, fields = discovery._declared_capability_overrides(
        {"capabilities": {"supports_reasoning_effort": False}}
    )

    assert overrides["supports_reasoning_effort"] is False
    assert "supports_reasoning_effort" in fields


def test_capabilities_declaration_accepts_camel_case_aliases() -> None:
    overrides, _fields = discovery._declared_capability_overrides(
        {"capabilities": {"reasoningEffort": False}}
    )

    assert overrides["supports_reasoning_effort"] is False


def test_contradictory_declaration_is_rejected_at_load_time() -> None:
    """声明不吃 reasoning_effort，却仍配置可选值，属于自相矛盾。"""
    model_entry = {
        "model_protocol": "deepseek_reasoning",
        "capabilities": {"supports_reasoning_effort": False},
        "defaults": {
            "reasoning_effort_values": ["low", "medium", "high"],
            "default_reasoning_effort": "high",
            "reasoning_effort_adapter": "reasoning_effort",
        },
    }

    errors, _warnings = discovery.llm_model_entry_issues(
        _profile_stub(), _provider_stub(), model_entry=model_entry
    )

    assert any("supports_reasoning_effort=false" in error for error in errors)


def _profile_stub():
    class _Profile:
        protocol = ""
        transport = ""
        model = "deepseek-v4.1-flash"

        def __getattr__(self, _name):
            return ""

    return _Profile()


def _provider_stub():
    class _Provider:
        kind = "openai_compatible"
        base_url = "https://example.invalid/v1"

        def __getattr__(self, _name):
            return ""

    return _Provider()
