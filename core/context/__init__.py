"""Context lifecycle helpers for cache-aware prompt assembly."""

from .segments import (
    CONTEXT_MANIFEST_SCHEMA_VERSION,
    ContextSegment,
    build_context_manifest,
    build_context_segment,
    normalize_context_manifest,
    normalize_context_segment,
)
from .skill_contract import (
    ACTIVE_SKILL_CONTEXT_HEADER,
    build_active_skill_contract,
    build_active_skill_runtime_context,
    normalize_active_skill_contract,
    refresh_active_skill_contract_status,
)
from .volatility import (
    SYSTEM_DYNAMIC_CONTEXT_HEADER,
    VOLATILE_CONTEXT_HEADERS,
    is_volatile_context_text,
)

__all__ = [
    "CONTEXT_MANIFEST_SCHEMA_VERSION",
    "ACTIVE_SKILL_CONTEXT_HEADER",
    "ContextSegment",
    "SYSTEM_DYNAMIC_CONTEXT_HEADER",
    "VOLATILE_CONTEXT_HEADERS",
    "build_active_skill_contract",
    "build_active_skill_runtime_context",
    "build_context_manifest",
    "build_context_segment",
    "is_volatile_context_text",
    "normalize_active_skill_contract",
    "normalize_context_manifest",
    "normalize_context_segment",
    "refresh_active_skill_contract_status",
]
