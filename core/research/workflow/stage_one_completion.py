"""Shared checkpoint routing contract for an authorized stage-one terminal."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.graph import END

STAGE_ONE_ACCEPTED_STATE = "STAGE1_G1_ACCEPTED"
STAGE_ONE_CHECKPOINT_FIELD = "stage_one_completion_state"


def route_after_stage_one_closure(
    default_target: str,
) -> Callable[[Mapping[str, Any]], str]:
    """Route to END only when server validation wrote the accepted marker."""

    def route(state: Mapping[str, Any]) -> str:
        if str(state.get(STAGE_ONE_CHECKPOINT_FIELD) or "") == STAGE_ONE_ACCEPTED_STATE:
            return END
        return default_target

    route.__name__ = "route_after_stage_one_closure"
    return route


__all__ = [
    "STAGE_ONE_ACCEPTED_STATE",
    "STAGE_ONE_CHECKPOINT_FIELD",
    "route_after_stage_one_closure",
]
