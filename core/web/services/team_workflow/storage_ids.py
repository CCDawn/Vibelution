"""Shared storage-path component sanitization for team workflow stores.

Every team-scoped JSONL store builds filesystem paths from caller-supplied
ids (team ids, question ids, run ids). Nine modules carried private copies
of a character filter that allowed ``.`` — so ``team_id=".."`` produced a
``teams/../<kind>`` path that escapes the team namespace, and unvalidated
``run_id``/``question_id`` values reached artifact paths raw (a write
primitive on Windows, where ``\\`` is a separator). One shared, tested
implementation closes both.
"""

from __future__ import annotations

import re

_STORAGE_CHARSET_EXTRA = "._-"
_STRICT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def safe_storage_component(value: str, *, fallback: str) -> str:
    """Team-id-shaped path component: charset-filtered, never dot-led.

    Keeps legacy ids (``research-team``, ``agent-20260722-220510``) intact
    while guaranteeing the result cannot be ``.``/``..`` or start with a
    dot, so it can only ever be a plain directory name.
    """
    filtered = "".join(
        character if character.isalnum() or character in _STORAGE_CHARSET_EXTRA else "_"
        for character in str(value or "")
    )[:96]
    if not filtered:
        return fallback
    if filtered.startswith("."):
        filtered = "_" + filtered.lstrip(".")
    return filtered or fallback


def validate_artifact_component(value: str, *, field: str) -> str:
    """Strict id used inside artifact filenames: reject anything path-shaped.

    Raises ValueError with the field name so callers surface an actionable
    message instead of writing outside the store.
    """
    normalized = str(value or "").strip()
    if not _STRICT_ID.fullmatch(normalized):
        raise ValueError(
            f"{field} must match [A-Za-z0-9_-]{{1,64}} for artifact storage: {normalized!r}"
        )
    return normalized
