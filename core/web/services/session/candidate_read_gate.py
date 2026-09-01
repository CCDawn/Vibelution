"""Machine read gate for candidate hypothesis child sessions (P1 T5).

Candidate hypothesis child sessions carry a ``workflow_candidate`` v3 scope
(``selectionId`` + ``candidateId``) in their ``experimentBinding``.  Prompt
isolation and ``hiddenFromIndex`` alone do not stop a holder of a sibling
``sessionId`` from reading that candidate's transcript, so server-side read
entries evaluate this gate before serving detail/transcript/messages.

Scope of the gate (deliberately narrow):

- Read path only.  Session admission, submit, journal, worker, persist,
  projection/SSE and ConversationStore are not touched.
- Only candidate child sessions are gated.  A target without a candidate
  binding short-circuits to allow, so normal sessions are bit-for-bit
  unchanged.
- No requester declared (the default) means the operator channel: the web
  workbench, control-plane surfaces and plain internal service reads keep the
  legacy behavior and are allowed.  Agent-initiated reads must declare a
  requester explicitly.

Whitelist:

- Operator channel (web UI / console): always allowed.  Undeclared reads -
  including plain internal service reads and the coordination lineage check
  in ``formal_hypothesis_fanout.scoped_handle_from_started`` - keep this
  legacy default.
- Research coordination (fan-out lineage check, fan-in aggregation):
  declaring ``channel="coordination"`` allows the same workflow run and
  fails closed on a foreign run.  Fan-in aggregation itself reads
  ``hypothesis_fragment`` task results rather than candidate transcripts
  (``formal_hypothesis_fanout.load_formal_hypothesis_fragment``), so no
  transcript grant is needed there.
- Same-candidate agent: the requester's bound scope must match the target's
  ``workflowRunId``/``selectionId``/``candidateId``, or the requester must be
  reading its own session.

Denials raise :class:`SiblingHypothesisSessionAccessDenied` carrying the
``sibling_hypothesis_session_access_denied`` error code, and record one
bounded runtime scene event (identities only, never transcript content).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

CANDIDATE_READ_DENIED_ERROR_CODE = "sibling_hypothesis_session_access_denied"

_REQUESTER_CHANNELS = frozenset({"operator", "coordination", "agent"})


class SiblingHypothesisSessionAccessDenied(PermissionError):
    """Raised when a requester may not read a sibling candidate session."""

    def __init__(
        self,
        message: str,
        *,
        target_session_id: str = "",
        target_selection_id: str = "",
        target_candidate_id: str = "",
        target_workflow_run_id: str = "",
        requester_channel: str = "",
        requester_session_id: str = "",
        requester_agent_id: str = "",
        requester_selection_id: str = "",
        requester_candidate_id: str = "",
        reason: str = "",
    ) -> None:
        super().__init__(message)
        self.code = CANDIDATE_READ_DENIED_ERROR_CODE
        self.target_session_id = target_session_id
        self.target_selection_id = target_selection_id
        self.target_candidate_id = target_candidate_id
        self.target_workflow_run_id = target_workflow_run_id
        self.requester_channel = requester_channel
        self.requester_session_id = requester_session_id
        self.requester_agent_id = requester_agent_id
        self.requester_selection_id = requester_selection_id
        self.requester_candidate_id = requester_candidate_id
        self.reason = reason

    def to_payload(self) -> dict[str, Any]:
        """Bounded machine-readable payload; never includes transcript content."""

        return {
            "code": self.code,
            "targetSessionId": self.target_session_id,
            "requesterChannel": self.requester_channel,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SessionReadRequester:
    """Server-resolved identity of one session read request.

    ``channel`` is one of ``operator`` / ``coordination`` / ``agent``.  Agent
    channel requesters carry the scope bound to their own session; the scope
    is resolved server-side from the requester session's ``experimentBinding``
    and never from client-claimed arguments.
    """

    channel: str = "operator"
    agent_id: str = ""
    session_id: str = ""
    selection_id: str = ""
    candidate_id: str = ""
    workflow_run_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel", str(self.channel or "operator").strip() or "operator")
        object.__setattr__(self, "agent_id", str(self.agent_id or "").strip())
        object.__setattr__(self, "session_id", str(self.session_id or "").strip())
        object.__setattr__(self, "selection_id", str(self.selection_id or "").strip())
        object.__setattr__(self, "candidate_id", str(self.candidate_id or "").strip())
        object.__setattr__(self, "workflow_run_id", str(self.workflow_run_id or "").strip())


def normalize_session_read_requester(value: Any) -> SessionReadRequester | None:
    """Coerce a mapping into a requester; ``None``/empty stays operator default."""

    if value is None:
        return None
    if isinstance(value, SessionReadRequester):
        return value
    if isinstance(value, Mapping):
        return SessionReadRequester(
            channel=str(value.get("channel") or "operator"),
            agent_id=str(value.get("agentId") or value.get("agent_id") or ""),
            session_id=str(value.get("sessionId") or value.get("session_id") or ""),
            selection_id=str(value.get("selectionId") or value.get("selection_id") or ""),
            candidate_id=str(value.get("candidateId") or value.get("candidate_id") or ""),
            workflow_run_id=str(
                value.get("workflowRunId") or value.get("workflow_run_id") or ""
            ),
        )
    raise TypeError("requester must be a SessionReadRequester, a mapping, or None")


def _text(value: Any, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


def candidate_binding_from_conversation(conversation: Any) -> dict[str, str] | None:
    """Return the candidate scope of a conversation, or ``None`` when not one.

    A candidate child session requires ``selectionId`` + ``candidateId`` (and
    the enclosing workflow run identity) in its durable experiment binding.
    Anything else - flat sessions, node roots, discussion children, plain
    agent sessions - is not gated.
    """

    if not isinstance(conversation, Mapping):
        return None
    binding = conversation.get("experimentBinding") or conversation.get("experiment_binding")
    if not isinstance(binding, Mapping):
        return None
    selection_id = _text(binding.get("selectionId"))
    candidate_id = _text(binding.get("candidateId"))
    workflow_run_id = _text(binding.get("workflowRunId"))
    # The durable writer nests the v3 scope under ``binding["scope"]``; the
    # run identity (and legacy fallbacks) may only exist there.
    scope = binding.get("scope")
    if isinstance(scope, Mapping):
        workflow_run_id = workflow_run_id or _text(scope.get("workflowRunId"))
        selection_id = selection_id or _text(scope.get("selectionId"))
        candidate_id = candidate_id or _text(scope.get("candidateId"))
    if not selection_id or not candidate_id or not workflow_run_id:
        return None
    return {
        "selectionId": selection_id,
        "candidateId": candidate_id,
        "workflowRunId": workflow_run_id,
    }


def evaluate_candidate_session_read(
    conversation: Any,
    requester: Any = None,
) -> dict[str, Any]:
    """Decide whether ``requester`` may read this conversation.

    Returns a bounded decision dict on allow and raises
    :class:`SiblingHypothesisSessionAccessDenied` on deny.
    """

    target_binding = candidate_binding_from_conversation(conversation)
    if target_binding is None:
        return {"allowed": True, "reason": "not_candidate_child"}
    normalized = normalize_session_read_requester(requester)
    if normalized is None:
        # No declared requester: operator channel (web workbench, control
        # plane) and plain internal service reads keep legacy behavior.
        return {"allowed": True, "reason": "operator_channel_default"}
    target_session_id = ""
    if isinstance(conversation, Mapping):
        target_session_id = _text(
            conversation.get("conversation_id")
            or conversation.get("conversationId")
            or conversation.get("id")
        )

    def _deny(reason: str) -> SiblingHypothesisSessionAccessDenied:
        """Record the bounded scene event and raise the deny error."""
        record_candidate_read_denial(
            target_session_id=target_session_id,
            target_binding=target_binding,
            requester=normalized,
            reason=reason,
        )
        raise SiblingHypothesisSessionAccessDenied(
            "sibling hypothesis session access denied",
            target_session_id=target_session_id,
            target_selection_id=target_binding["selectionId"],
            target_candidate_id=target_binding["candidateId"],
            target_workflow_run_id=target_binding["workflowRunId"],
            requester_channel=normalized.channel,
            requester_session_id=normalized.session_id,
            requester_agent_id=normalized.agent_id,
            requester_selection_id=normalized.selection_id,
            requester_candidate_id=normalized.candidate_id,
            reason=reason,
        )

    if normalized.channel not in _REQUESTER_CHANNELS:
        return _deny("unknown_requester_channel")
    if normalized.channel == "operator":
        return {"allowed": True, "reason": "operator_channel"}
    if normalized.channel == "coordination":
        if (
            normalized.workflow_run_id
            and normalized.workflow_run_id != target_binding["workflowRunId"]
        ):
            return _deny("coordination_run_mismatch")
        return {"allowed": True, "reason": "coordination_channel"}
    # Agent channel.
    if normalized.session_id and normalized.session_id == target_session_id:
        return {"allowed": True, "reason": "own_session"}
    if (
        normalized.selection_id == target_binding["selectionId"]
        and normalized.candidate_id == target_binding["candidateId"]
        and (
            not normalized.workflow_run_id
            or normalized.workflow_run_id == target_binding["workflowRunId"]
        )
    ):
        return {"allowed": True, "reason": "same_candidate_scope"}
    return _deny("candidate_scope_mismatch")


def assert_candidate_session_read(conversation: Any, requester: Any = None) -> None:
    """Gate helper for read entries; raises on deny."""

    evaluate_candidate_session_read(conversation, requester)


def record_candidate_read_denial(
    *,
    target_session_id: str,
    target_binding: Mapping[str, str],
    requester: SessionReadRequester,
    reason: str,
) -> None:
    """Best-effort bounded scene event for one denial (identities only)."""

    try:
        from core.web.services.runtime_scene.record import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "session",
            "candidate_read_gate",
            CANDIDATE_READ_DENIED_ERROR_CODE,
            level="warning",
            outcome="blocked",
            message="candidate hypothesis session read denied to sibling requester",
            fields={
                "targetSessionId": _text(target_session_id),
                "targetSelectionId": _text(target_binding.get("selectionId")),
                "targetCandidateId": _text(target_binding.get("candidateId")),
                "targetWorkflowRunId": _text(target_binding.get("workflowRunId")),
                "requesterChannel": _text(requester.channel, limit=40),
                "requesterSessionId": _text(requester.session_id),
                "requesterAgentId": _text(requester.agent_id),
                "requesterSelectionId": _text(requester.selection_id),
                "requesterCandidateId": _text(requester.candidate_id),
                "requesterWorkflowRunId": _text(requester.workflow_run_id),
                "reason": _text(reason, limit=80),
            },
        )
    except Exception:
        # The gate must never turn a scene-record failure into a read failure.
        return


__all__ = [
    "CANDIDATE_READ_DENIED_ERROR_CODE",
    "SessionReadRequester",
    "SiblingHypothesisSessionAccessDenied",
    "assert_candidate_session_read",
    "candidate_binding_from_conversation",
    "evaluate_candidate_session_read",
    "normalize_session_read_requester",
    "record_candidate_read_denial",
]
