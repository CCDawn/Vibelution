"""Session-scoped budget parameter API service (GET/PATCH budget-parameters).

Claim scope: the per-session budget override view and its CAS update. Storage
copies the session model-parameters pattern exactly: values live on the
session's bound Agent registry record, guarded by the Agent ``configRevision``
compare-and-swap; the session lifecycle lock keeps the session-to-Agent
binding stable during the edit.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

from typing import Any

from core.orchestration.session_budget_resolve import (
    SESSION_MAX_CALLS_PER_TURN_MAX,
    SESSION_MAX_CALLS_PER_TURN_MIN,
    SessionBudgetParametersValueError,
    session_budget_parameters_from_agent,
    validate_session_budget_override,
)

_UNCHANGED: Any = object()


class SessionBudgetParametersConflictError(RuntimeError):
    """Raised when the session Agent/revision changed during a budget edit."""


def _service():
    from core.web.services import session_service

    return session_service


def _session_budget_agent(session_id: str, *, source: str, sync_wait: bool = True) -> dict[str, Any]:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise s.SessionNotFoundError("Session not found")
    if not s._ensure_session_conversation_record(
        normalized_session_id,
        source=source,
        sync_wait=sync_wait,
    ):
        raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
    agent_id = s._session_agent_id_snapshot(normalized_session_id)
    agent = s.get_agent(agent_id, include_archived=True) if agent_id else None
    return _validate_budget_agent(agent)


def _validate_budget_agent(agent: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
    if isinstance(agent, dict) and str(agent.get("status") or "").strip() == "archived":
        raise s.SessionValidationError("会话所属 Agent 已归档，此会话仅供只读查看。")
    if not isinstance(agent, dict):
        raise s.SessionValidationError("当前会话没有可用的 Agent 配置。")
    return agent


def get_session_budget_parameters_view(session_id: str) -> dict[str, Any]:
    """Return the session budget override view plus the current CAS revision."""

    agent = _session_budget_agent(
        session_id,
        source="session.budget_parameters.get",
        sync_wait=False,
    )
    return _budget_parameters_view(agent)


def _budget_parameters_view(agent: dict[str, Any]) -> dict[str, Any]:
    parameters = session_budget_parameters_from_agent(agent)
    return {
        "revision": max(0, int(agent.get("configRevision") or 0)),
        "maxCallsPerTurn": parameters.maxCallsPerTurn if parameters is not None else None,
    }


def update_session_budget_parameters(
    session_id: str,
    *,
    expected_revision: int,
    max_calls_per_turn: Any = _UNCHANGED,
) -> dict[str, Any]:
    """Update the session budget overrides for subsequent accepted turns.

    Omitted fields keep their current value; ``None`` clears one override back
    to the default resolution (family/base). Running and queued turns are
    intentionally allowed; their accepted parameters were already snapshotted
    by the submit path. Legacy ``thinkingBudgetChars`` storage keys are not
    migrated — they are simply dropped from the payload on the next save.
    """
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise s.SessionNotFoundError("Session not found")
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise s.SessionValidationError("revision must be a non-negative integer.")
    if expected_revision < 0:
        raise s.SessionValidationError("revision must be a non-negative integer.")
    try:
        normalized_max_calls = (
            _UNCHANGED
            if max_calls_per_turn is _UNCHANGED
            else validate_session_budget_override(
                max_calls_per_turn,
                field="maxCallsPerTurn",
                minimum=SESSION_MAX_CALLS_PER_TURN_MIN,
                maximum=SESSION_MAX_CALLS_PER_TURN_MAX,
            )
        )
    except SessionBudgetParametersValueError as exc:
        raise s.SessionValidationError(str(exc)) from exc

    with s.session_agent_lifecycle_transaction():
        conversation = s._ensure_session_mutable(normalized_session_id)
        if not s._ensure_session_conversation_record(
            normalized_session_id,
            source="session.budget_parameters.update",
            sync_wait=False,
        ):
            raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
        bound_agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        agent = _validate_budget_agent(s.agent_directory_service.get_agent_parameter_snapshot(bound_agent_id))
        agent_id = str(agent.get("agentId") or "").strip()
        current = session_budget_parameters_from_agent(agent)
        next_max_calls = (
            normalized_max_calls
            if normalized_max_calls is not _UNCHANGED
            else (current.maxCallsPerTurn if current is not None else None)
        )
        next_payload = {
            key: value
            for key, value in (("maxCallsPerTurn", next_max_calls),)
            if value is not None
        }
        from core.llm.agent_model_parameters import AgentModelParametersError

        try:
            updated_agent = s.agent_directory_service.update_agent_budget_parameters_if_current(
                agent_id,
                expected_config_revision=int(expected_revision),
                values=next_payload,
            )
        except s.agent_directory_service.AgentStateConflictError as exc:
            raise SessionBudgetParametersConflictError(str(exc)) from exc
        except s.agent_directory_service.AgentArchivedError as exc:
            raise s.SessionValidationError(str(exc)) from exc
        except s.agent_directory_service.AgentNotFoundError as exc:
            raise s.SessionValidationError("当前会话没有可用的 Agent 配置。") from exc
        except AgentModelParametersError as exc:
            raise s.SessionValidationError(str(exc)) from exc

        return _budget_parameters_view(updated_agent)
