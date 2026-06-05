# -*- coding: utf-8 -*-
"""统一 LLM 子系统。"""

from .client import LLMClient, get_llm_client, list_profiles
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
    "LLMRecoveryDecision",
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
    "list_profiles",
    "plan_recovery",
    "attach_recovery_fallback",
    "select_recovery_profile",
    "resolve_agent_llm",
]
