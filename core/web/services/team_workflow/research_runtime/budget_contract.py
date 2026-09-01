"""Pure formal-workflow budget capacity contract.

Token capacity is an accounting and planning envelope.  Runtime loop safety
and terminal behavior are owned by the session/challenge turn policies, not
by copied launch defaults in individual services.
"""

from __future__ import annotations

from typing import Any

FORMAL_STAGE_IDS = (
    "knowledge_collection",
    "experiment_design",
    "execution_iteration",
)

# A real formal node can consume roughly 300K input+output tokens.  The 2M
# capacity is the existing calibrated conservative envelope; it is shared by
# launch, reservation, and missing-contract behavior so no smaller copied
# default can silently override it.
DEFAULT_FORMAL_TOKEN_BUDGET = 2_000_000
DEFAULT_STAGE_TOKENS = DEFAULT_FORMAL_TOKEN_BUDGET
DEFAULT_TOOL_CALLS = 600
DEFAULT_WALL_CLOCK_SECONDS = 4 * 60 * 60
DEFAULT_MAX_RETRIES = 3


def default_safety_limits() -> dict[str, Any]:
    """Return one fresh launch-shaped capacity contract."""

    return {
        "stageTokens": {
            stage_id: DEFAULT_STAGE_TOKENS for stage_id in FORMAL_STAGE_IDS
        },
        "toolCalls": DEFAULT_TOOL_CALLS,
        "wallClockSeconds": DEFAULT_WALL_CLOCK_SECONDS,
        "maxRetries": DEFAULT_MAX_RETRIES,
    }


__all__ = [
    "DEFAULT_FORMAL_TOKEN_BUDGET",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_STAGE_TOKENS",
    "DEFAULT_TOOL_CALLS",
    "DEFAULT_WALL_CLOCK_SECONDS",
    "FORMAL_STAGE_IDS",
    "default_safety_limits",
]
