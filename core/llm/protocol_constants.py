# -*- coding: utf-8 -*-
"""Single authority for LLM wire-protocol reasoning constants.

Every protocol field name, legal value set, reasoning-effort adapter name and
reasoning state field that crosses the LLM wire (request payloads, response
parsing, discovery validation) is defined here exactly once.  Consumers —
``reasoning_effort``, ``payload_builder``, ``adapters``, ``discovery`` and
``reasoning_extractor`` — import from this module; local copies are forbidden
and guarded by ``tests/test_llm_protocol_constants.py``.

The same names drifting apart across modules has produced incident-class bugs
before (recovery action keys vs error classifier categories).  Adding a raw
literal for one of these names in a consumer module is a review blocker.

This module must stay import-only: it defines constants and imports nothing
from the rest of the package, so any module can depend on it without cycles.
"""

from __future__ import annotations

# --- Request-side wire field names ------------------------------------------
# OpenAI chat-style top-level reasoning effort key.
REASONING_EFFORT_FIELD = "reasoning_effort"
# OpenAI Responses-style reasoning object and its effort sub-key.
REASONING_OBJECT_FIELD = "reasoning"
REASONING_EFFORT_OBJECT_KEY = "effort"
# Qwen/GLM-style thinking toggle (top-level or inside extra_body).
ENABLE_THINKING_FIELD = "enable_thinking"
CHAT_TEMPLATE_KWARGS_FIELD = "chat_template_kwargs"
# LiteLLM key that merges extra keys into the outbound request body.
EXTRA_BODY_FIELD = "extra_body"

# --- Response-side / state field names ---------------------------------------
# DeepSeek-style reasoning state field carried on messages.
REASONING_CONTENT_FIELD = "reasoning_content"
# Anthropic-style thinking object key on the request payload.
THINKING_FIELD = "thinking"
# Streaming delta variants and legacy thought key (response parsing only).
REASONING_CONTENT_DELTA_FIELD = "reasoning_content_delta"
REASONING_DELTA_FIELD = "reasoning_delta"
THOUGHT_FIELD = "thought"

# --- Reasoning effort value sets ----------------------------------------------
# Values exposed on GPT-5-class model pins (operator-facing contract).
GPT_REASONING_EFFORT_VALUES = ("low", "medium", "high")
# Superset accepted by normalize_reasoning_effort (config + legacy aliases).
KNOWN_REASONING_EFFORT_VALUES = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
)

# --- Reasoning effort adapter names -------------------------------------------
# Sentinel meaning "profile declares no reasoning contract".
REASONING_EFFORT_ADAPTER_NONE = "none"
REASONING_EFFORT_ADAPTER_REASONING_EFFORT = "reasoning_effort"
REASONING_EFFORT_ADAPTER_REASONING_OBJECT = "reasoning_object"
REASONING_EFFORT_ADAPTER_THINKING_TOGGLE = "thinking_toggle"
# Real wire adapters (excludes the "none" sentinel). Mirrored by
# config/model_catalog._REASONING_ADAPTERS; consistency is test-enforced
# because config must not depend on core.
REASONING_EFFORT_ADAPTERS = frozenset(
    {
        REASONING_EFFORT_ADAPTER_REASONING_EFFORT,
        REASONING_EFFORT_ADAPTER_REASONING_OBJECT,
        REASONING_EFFORT_ADAPTER_THINKING_TOGGLE,
    }
)
# thinking_toggle semantics: these effective values map to disabled.
THINKING_TOGGLE_OFF_VALUES = frozenset({"off", "none"})

# --- Reasoning state fields (discovery/validation authority) ------------------
# Only these reasoning_state_field values are supported by the reasoning_chat
# contract validation; derived from the canonical state field name.
SUPPORTED_REASONING_STATE_FIELDS = {REASONING_CONTENT_FIELD}

# --- Response-side candidate field lists ---------------------------------------
# Ordered candidate keys scanned when extracting reasoning from provider
# responses/dicts (most specific first).
REASONING_FIELD_CANDIDATES = (
    REASONING_CONTENT_DELTA_FIELD,
    REASONING_DELTA_FIELD,
    REASONING_CONTENT_FIELD,
    REASONING_OBJECT_FIELD,
    THINKING_FIELD,
    THOUGHT_FIELD,
)
REASONING_DELTA_FIELD_CANDIDATES = (
    REASONING_CONTENT_DELTA_FIELD,
    REASONING_DELTA_FIELD,
)


__all__ = [
    "CHAT_TEMPLATE_KWARGS_FIELD",
    "ENABLE_THINKING_FIELD",
    "EXTRA_BODY_FIELD",
    "GPT_REASONING_EFFORT_VALUES",
    "KNOWN_REASONING_EFFORT_VALUES",
    "REASONING_CONTENT_DELTA_FIELD",
    "REASONING_CONTENT_FIELD",
    "REASONING_DELTA_FIELD",
    "REASONING_DELTA_FIELD_CANDIDATES",
    "REASONING_EFFORT_ADAPTERS",
    "REASONING_EFFORT_ADAPTER_NONE",
    "REASONING_EFFORT_ADAPTER_REASONING_EFFORT",
    "REASONING_EFFORT_ADAPTER_REASONING_OBJECT",
    "REASONING_EFFORT_ADAPTER_THINKING_TOGGLE",
    "REASONING_EFFORT_FIELD",
    "REASONING_EFFORT_OBJECT_KEY",
    "REASONING_FIELD_CANDIDATES",
    "REASONING_OBJECT_FIELD",
    "SUPPORTED_REASONING_STATE_FIELDS",
    "THINKING_FIELD",
    "THINKING_TOGGLE_OFF_VALUES",
    "THOUGHT_FIELD",
]
