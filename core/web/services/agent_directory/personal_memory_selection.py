"""Pure selection rules for generic Agent personal-memory context and search."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

FINANCIAL_VALIDATION_REF_PREFIX = "financial-validation:"
PROMPT_PREFERENCE_LIMIT = 8
PROMPT_ORDINARY_LIMIT = 8
PROMPT_EPISODE_LIMIT = PROMPT_PREFERENCE_LIMIT + PROMPT_ORDINARY_LIMIT


def is_financial_validation_lesson(event: object) -> bool:
    """Return whether an episodic event belongs to scoped finance reflection."""
    if not isinstance(event, dict):
        return False
    # New lessons carry service-owned provenance; keep legacy reference
    # detection too so existing lessons cannot re-enter the generic context.
    if isinstance(event.get("financialLesson"), dict):
        return True
    refs = event.get("refs")
    if not isinstance(refs, list):
        return False
    return any(
        isinstance(ref, dict)
        and ref.get("type") == "item"
        and str(ref.get("id") or "").startswith(FINANCIAL_VALIDATION_REF_PREFIX)
        for ref in refs
    )


def select_searchable_personal_episodes(
    events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep current general personal events; finance lessons use scoped reads."""
    return [
        event
        for event in events
        if isinstance(event, dict)
        and not str(event.get("validUntil") or "").strip()
        and not is_financial_validation_lesson(event)
    ]


def select_prompt_personal_episodes(
    events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reserve separate bounded prompt slots for preferences and other events.

    Input is the episodic store's newest-first projection. A preference's age
    therefore cannot let newer ordinary notes push it out of its own budget.
    The combined prompt budget is 16 events: at most 8 preferences and 8 other
    current personal episodes.
    """
    preferences: list[dict[str, Any]] = []
    ordinary: list[dict[str, Any]] = []
    for event in select_searchable_personal_episodes(events):
        kind = str(event.get("kind") or "note").strip().casefold()
        if kind == "preference":
            if len(preferences) < PROMPT_PREFERENCE_LIMIT:
                preferences.append(event)
        elif len(ordinary) < PROMPT_ORDINARY_LIMIT:
            ordinary.append(event)
        if (
            len(preferences) >= PROMPT_PREFERENCE_LIMIT
            and len(ordinary) >= PROMPT_ORDINARY_LIMIT
        ):
            break
    return [*preferences, *ordinary]
