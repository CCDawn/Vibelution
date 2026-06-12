"""Shared volatile context classification.

Volatile context is current-turn or near-current-turn material that must not be
carried as stable history or merged into the cacheable system prefix.
"""

from __future__ import annotations

SYSTEM_DYNAMIC_CONTEXT_HEADER = "## Dynamic System Context"

VOLATILE_CONTEXT_HEADERS: tuple[str, ...] = (
    "## Agent Runtime Context",
    "## Runtime Context",
    SYSTEM_DYNAMIC_CONTEXT_HEADER,
    "## Recent Operator Guidance",
    "## Slash Skill Context",
)


def is_volatile_context_text(text: object) -> bool:
    normalized = str(text or "").strip()
    return normalized.startswith(VOLATILE_CONTEXT_HEADERS)
