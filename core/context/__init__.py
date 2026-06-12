"""Context lifecycle helpers for cache-aware prompt assembly."""

from .segments import (
    CONTEXT_MANIFEST_SCHEMA_VERSION,
    ContextSegment,
    build_context_manifest,
    build_context_segment,
    normalize_context_manifest,
    normalize_context_segment,
)
from .volatility import (
    SYSTEM_DYNAMIC_CONTEXT_HEADER,
    VOLATILE_CONTEXT_HEADERS,
    is_volatile_context_text,
)

__all__ = [
    "CONTEXT_MANIFEST_SCHEMA_VERSION",
    "ContextSegment",
    "SYSTEM_DYNAMIC_CONTEXT_HEADER",
    "VOLATILE_CONTEXT_HEADERS",
    "build_context_manifest",
    "build_context_segment",
    "is_volatile_context_text",
    "normalize_context_manifest",
    "normalize_context_segment",
]
