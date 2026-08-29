"""Bounded loader for the trusted first-party virtual-human prompt pack."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_PACK_FILES = (
    "01_identity_invariants.md",
    "02_life_autonomy.md",
    "03_schedule_protocol.md",
    "04_mood_and_expression.md",
    "05_tool_boundaries.md",
    "06_diary_memory_rules.md",
    "07_relationship_rules.md",
    "08_proactive_message_rules.md",
    "09_reflection_and_environment.md",
    "10_full_life_continuity.md",
)
MAX_PROMPT_PACK_CHARS = 12_000


@lru_cache(maxsize=1)
def load_prompt_pack() -> str:
    root = Path(__file__).with_name("prompts")
    sections: list[str] = []
    for filename in PROMPT_PACK_FILES:
        text = (root / filename).read_text(encoding="utf-8").strip()
        if text:
            sections.append(text)
    block = "\n\n".join(sections)
    if not block or len(block) > MAX_PROMPT_PACK_CHARS:
        raise RuntimeError("virtual-human-life prompt pack is missing or exceeds its budget")
    return block


__all__ = ["PROMPT_PACK_FILES", "load_prompt_pack"]
