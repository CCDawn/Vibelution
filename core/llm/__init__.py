# -*- coding: utf-8 -*-
"""统一 LLM 子系统。"""

from .client import LLMClient, get_llm_client, list_profiles
from .invocation import invoke_llm, stream_llm
from .invocation_context import (
    LLMInvocationContext,
    dialogue_chain_mode_for_protocol,
    prompt_purpose_cache_partition,
)
from .agent_runtime import (
    AGENT_LLM_SLOT_DIALOGUE,
    AGENT_LLM_SLOT_MENTAL_MODEL,
    AGENT_LLM_SLOT_SUBAGENT_EXECUTION,
    AGENT_LLM_SLOT_SUBAGENT_PLANNING,
    AGENT_LLM_SLOT_SUMMARY,
    AGENT_LLM_SLOT_VISION,
    AgentLlmResolutionError,
    ResolvedAgentLlm,
    resolve_agent_llm,
)
from .discovery import assert_llm_compatibility, discover_model, doctor_llm_profile
from .errors import classify_exception
from .recovery import LLMRecoveryDecision, plan_recovery
from .routing import attach_recovery_fallback, select_recovery_profile
from .types import (
    DiagnosticReport,
    LLMCapabilities,
    LLMError,
    LLMOutputTruncatedError,
    ResolvedModelSpec,
    StreamChunk,
    ToolCall,
    UsageStats,
)

__all__ = [
    "DiagnosticReport",
    "LLMCapabilities",
    "LLMClient",
    "LLMError",
    "LLMOutputTruncatedError",
    "LLMRecoveryDecision",
    "LLMInvocationContext",
    "ResolvedModelSpec",
    "StreamChunk",
    "ToolCall",
    "UsageStats",
    "AGENT_LLM_SLOT_DIALOGUE",
    "AGENT_LLM_SLOT_MENTAL_MODEL",
    "AGENT_LLM_SLOT_SUBAGENT_EXECUTION",
    "AGENT_LLM_SLOT_SUBAGENT_PLANNING",
    "AGENT_LLM_SLOT_SUMMARY",
    "AGENT_LLM_SLOT_VISION",
    "AgentLlmResolutionError",
    "ResolvedAgentLlm",
    "classify_exception",
    "assert_llm_compatibility",
    "discover_model",
    "doctor_llm_profile",
    "get_llm_client",
    "invoke_llm",
    "list_profiles",
    "plan_recovery",
    "stream_llm",
    "attach_recovery_fallback",
    "select_recovery_profile",
    "resolve_agent_llm",
    "dialogue_chain_mode_for_protocol",
    "prompt_purpose_cache_partition",
]
