"""Session-scoped budget parameter resolution for the execution layer.

One per-session budget override exists today:

* ``maxCallsPerTurn`` — per-turn tool-call quota; installed by the tool
  authorization layer with priority session override > model-family
  resolution > policy base.

Thinking budgets are intentionally *not* session-configurable: the hard
thinking-budget instruction is reserved for research workflow node sessions
(see ``core.web.services.session.research_thinking_budget``), which always
resolve through the env/default path. Stored payloads may still carry a
legacy ``thinkingBudgetChars`` key; the read path ignores it, and the next
PATCH save drops it from the stored payload.

Storage follows the session model-parameters pattern: values live on the
session's bound Agent registry record under one metadata key, guarded by the
Agent ``configRevision`` compare-and-swap. Because chat sessions bind one
direct Agent each, the Agent-scoped block stays session-private in practice.

This module is the single read path shared by the authorization layer and
the web service; it must stay import-cheap and late-bind web services inside
functions only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

SESSION_BUDGET_PARAMETERS_METADATA_KEY = "sessionBudgetParameters"

SESSION_MAX_CALLS_PER_TURN_MIN = 1
SESSION_MAX_CALLS_PER_TURN_MAX = 200
# 0 is a sentinel, not a quota: it disables the per-turn cap entirely
# and matches ``resolve_max_calls_per_turn``'s unlimited return value.
SESSION_MAX_CALLS_PER_TURN_UNLIMITED = 0


@dataclass(frozen=True, slots=True)
class SessionBudgetParameters:
    """Per-session budget overrides; ``None`` fields fall back to defaults."""

    maxCallsPerTurn: int | None = None

    def as_storage_payload(self) -> dict[str, int]:
        return {
            key: value
            for key, value in (("maxCallsPerTurn", self.maxCallsPerTurn),)
            if value is not None
        }


class SessionBudgetParametersValueError(ValueError):
    """Raised when a budget override value is outside its allowed range."""


def _coerce_override_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    """Coerce one stored override value; out-of-range or junk means unset."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            value = bytes(value).decode("utf-8", errors="replace").strip()
        except Exception:  # noqa: BLE001 - defensive decode only
            return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < minimum or parsed > maximum:
        return None
    return parsed


def normalize_session_budget_parameters(raw: Any) -> SessionBudgetParameters | None:
    """Normalize a stored override block; ``None`` when nothing is configured."""

    if not isinstance(raw, Mapping):
        return None
    max_calls = _coerce_override_int(
        raw.get("maxCallsPerTurn"),
        minimum=SESSION_MAX_CALLS_PER_TURN_UNLIMITED,
        maximum=SESSION_MAX_CALLS_PER_TURN_MAX,
    )
    # Legacy payloads may still carry a ``thinkingBudgetChars`` key; it is
    # deliberately ignored here and dropped on the next PATCH save.
    if max_calls is None:
        return None
    return SessionBudgetParameters(maxCallsPerTurn=max_calls)


def session_budget_parameters_from_agent(agent: Any) -> SessionBudgetParameters | None:
    """Extract the override block from one Agent registry projection."""

    if not isinstance(agent, Mapping):
        return None
    metadata = agent.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    return normalize_session_budget_parameters(metadata.get(SESSION_BUDGET_PARAMETERS_METADATA_KEY))


def validate_session_budget_override(
    value: Any,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> int | None:
    """Validate one incoming override value (``None`` clears it back to default)."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SessionBudgetParametersValueError(
            f"{field} must be an integer between {minimum} and {maximum}, or null."
        )
    if value < minimum or value > maximum:
        raise SessionBudgetParametersValueError(
            f"{field} must be between {minimum} and {maximum}, or null."
        )
    return int(value)


def get_session_budget_parameters(session_id: str) -> SessionBudgetParameters | None:
    """Resolve the session's budget overrides for the execution layer.

    Returns ``None`` when the session is unknown, unbound, or has no configured
    override; read failures never break the caller's turn.
    """

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    try:
        from core.web.services import session_service

        with session_service._CHAT_STATE_LOCK:
            conversation = session_service.load_session_chat_state(
                session_service.PROJECT_ROOT,
                normalized_session_id,
            )
        if not isinstance(conversation, dict):
            return None
        agent_id = str(
            conversation.get("agent_id") or conversation.get("agentId") or ""
        ).strip()
        if not agent_id:
            return None
        agent = session_service.get_agent(agent_id, include_archived=False)
        return session_budget_parameters_from_agent(agent)
    except Exception:  # noqa: BLE001 - resolution must stay best-effort
        return None


__all__ = [
    "SESSION_BUDGET_PARAMETERS_METADATA_KEY",
    "SESSION_MAX_CALLS_PER_TURN_MAX",
    "SESSION_MAX_CALLS_PER_TURN_MIN",
    "SESSION_MAX_CALLS_PER_TURN_UNLIMITED",
    "SessionBudgetParameters",
    "SessionBudgetParametersValueError",
    "get_session_budget_parameters",
    "normalize_session_budget_parameters",
    "session_budget_parameters_from_agent",
    "validate_session_budget_override",
]
