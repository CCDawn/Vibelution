"""Closed budget contract for the Launcher's fixed personal assistant."""

from pydantic import BaseModel, ConfigDict, Field

from core.orchestration.session_budget_resolve import (
    SESSION_MAX_CALLS_PER_TURN_MAX,
    SESSION_MAX_CALLS_PER_TURN_UNLIMITED,
)


class AssistantBudgetParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    revision: int = Field(ge=0)
    maxCallsPerTurn: int | None = Field(
        ge=SESSION_MAX_CALLS_PER_TURN_UNLIMITED,
        le=SESSION_MAX_CALLS_PER_TURN_MAX,
    )
