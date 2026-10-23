"""LLM public API without loading execution clients for leaf helpers."""

from __future__ import annotations

from importlib import import_module as _import_module
from typing import Any as _Any


_EXPORT_GROUPS = {
    '.client': (
        'LLMClient', 'get_llm_client', 'list_profiles',
    ),
    '.invocation': (
        'invoke_llm', 'stream_llm',
    ),
    '.invocation_context': (
        'LLMInvocationContext', 'dialogue_chain_mode_for_protocol', 'prompt_purpose_cache_partition',
    ),
    '.agent_runtime': (
        'AGENT_LLM_SLOT_DIALOGUE', 'AGENT_LLM_SLOT_MENTAL_MODEL', 'AGENT_LLM_SLOT_SUBAGENT_EXECUTION',
        'AGENT_LLM_SLOT_SUBAGENT_PLANNING', 'AGENT_LLM_SLOT_SUMMARY', 'AGENT_LLM_SLOT_VISION',
        'AgentLlmResolutionError', 'ResolvedAgentLlm', 'resolve_agent_llm',
    ),
    '.discovery': (
        'assert_llm_compatibility', 'discover_model', 'doctor_llm_profile',
        'doctor_model_library', 'llm_model_entry_issues', 'llm_profile_entry_issues',
    ),
    '.errors': (
        'classify_exception',
    ),
    '.recovery': (
        'LLMRecoveryDecision', 'plan_recovery',
    ),
    '.types': (
        'DiagnosticReport', 'LLMCapabilities', 'LLMError',
        'LLMOutputTruncatedError', 'ResolvedModelSpec', 'StreamChunk',
        'ToolCall', 'UsageStats',
    ),
}
_EXPORTS = {name: module for module, names in _EXPORT_GROUPS.items() for name in names}
__all__ = [
    'DiagnosticReport',
    'LLMCapabilities',
    'LLMClient',
    'LLMError',
    'LLMOutputTruncatedError',
    'LLMRecoveryDecision',
    'LLMInvocationContext',
    'ResolvedModelSpec',
    'StreamChunk',
    'ToolCall',
    'UsageStats',
    'AGENT_LLM_SLOT_DIALOGUE',
    'AGENT_LLM_SLOT_MENTAL_MODEL',
    'AGENT_LLM_SLOT_SUBAGENT_EXECUTION',
    'AGENT_LLM_SLOT_SUBAGENT_PLANNING',
    'AGENT_LLM_SLOT_SUMMARY',
    'AGENT_LLM_SLOT_VISION',
    'AgentLlmResolutionError',
    'ResolvedAgentLlm',
    'classify_exception',
    'assert_llm_compatibility',
    'discover_model',
    'doctor_llm_profile',
    'doctor_model_library',
    'llm_model_entry_issues',
    'llm_profile_entry_issues',
    'get_llm_client',
    'invoke_llm',
    'list_profiles',
    'plan_recovery',
    'stream_llm',
    'resolve_agent_llm',
    'dialogue_chain_mode_for_protocol',
    'prompt_purpose_cache_partition',
]


def __getattr__(name: str) -> _Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        # Let Python resolve real submodules through its normal import fallback.
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()).union(_EXPORTS))
