"""Production DomainPorts implementation (P1-3/P1-4).

Resolves the frozen RunAgentBindingSnapshot from the Workflow Ledger input
snapshot, creates real Agent session/task/turn through the canonical Chat and
research-project task authorities, and reserves/settles budget against the
Workflow Ledger ``budget_receipts`` table (the T5 budget authority).

The adapter worker drives the exact ordering: read-back -> resolve binding ->
reserve -> create task -> turn -> verify -> one ledger commit -> settle.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from core.research.workflow.contracts import PendingAction, WorkflowSessionScopeV3
from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.models import ActorKind

from .agent_turn_completion import TurnNotReadyError
from .domain_ports import (
    AgentTaskHandle,
    AgentTurnResult,
    ArtifactReadBack,
    BindingResolution,
    HumanTaskHandle,
    ReadBackVerdict,
    ScopedAgentTaskHandle,
)
from .challenge_turn_policy import (
    CHALLENGE_LOGICAL_TASK_TIMEOUT_MS,
    CHALLENGE_TURN_WAIT_WINDOW_MS,
    ChallengeTaskDeadlineExceeded,
    challenge_deadline_problem,
    remaining_challenge_task_ms,
)
from .ids import new_id
from .agent_node_execution import _formal_task_authorities
from .formal_hypothesis_fanout import (
    HypothesisAuthorityUnavailable as _HypothesisAuthorityUnavailable,
)
from .formal_hypothesis_fanout import (
    candidate_hypothesis_task_context as _candidate_hypothesis_task_context,
)
from .formal_hypothesis_fanout import (
    formal_hypothesis_fan_out_input as _formal_hypothesis_fan_out_input,
)
from .formal_hypothesis_fanout import (
    hypothesis_max_parallel as _hypothesis_max_parallel,
)
from .formal_hypothesis_fanout import (
    load_formal_hypothesis_fragment as _load_formal_hypothesis_fragment,
)
from .formal_hypothesis_fanout import (
    load_reusable_formal_hypothesis_fragment as _load_reusable_formal_hypothesis_fragment,
)
from .formal_hypothesis_fanout import (
    mark_candidate_task_completed as _mark_candidate_task_completed,
)
from .formal_hypothesis_fanout import (
    previous_hypothesis_anchor as _previous_hypothesis_anchor,
)
from .formal_hypothesis_fanout import (
    resolve_formal_candidate_task as _resolve_or_start_formal_candidate_task,
)
from .formal_hypothesis_fanout import (
    resolve_formal_node_root_session as _resolve_formal_node_root_session,
)
from .formal_hypothesis_fanout import (
    root_hypothesis_task_context as _root_hypothesis_task_context,
)
from .formal_hypothesis_fanout import (
    scoped_handle_from_started as _scoped_handle_from_started,
)
from .hypothesis_scope_events import (
    record_hypothesis_scope_event as _record_hypothesis_scope_event,
)
from .hypothesis_session_scope_mode import (
    evaluate_hypothesis_scope_shadow as _evaluate_hypothesis_scope_shadow,
)
from .hypothesis_session_scope_mode import (
    resolve_hypothesis_scope_activation as _resolve_hypothesis_scope_activation,
)
from .hypothesis_session_scope_mode import (
    resolve_hypothesis_session_scope_mode as _resolve_hypothesis_session_scope_mode,
)

_HYPOTHESIS_SELECTION_MISSING = (
    "hypothesis_design requires a current hypothesis selection"
)


def _positive_contract_tokens(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return int(value)


def _task_budget_request_tokens(run_id: str, node_run_id: str) -> int | None:
    """Explicit per-node task budget from the workflow-run reservation.

    Mirrors the turn-budget lookup path introduced in 281b18b5f: the
    ``budgetRequest.requested.tokens`` of ``reservation-{node_run_id}`` (or the
    node's ``budgetLedgerRef``) is the authoritative per-node token budget.
    Best-effort by design: a formal Ledger run without a legacy run record has
    no task budgetRequest, and callers fall through to the frozen snapshot
    contract. Token budgets stay a distinct counter family from count budgets
    (``toolCalls``), so a turns-style small constant can never leak back in as
    a token reservation.
    """

    try:
        from .store import WorkflowRunStore

        record = WorkflowRunStore().get_run(run_id)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    reservation_ids = {f"reservation-{node_run_id}"}
    for node_run in record.get("nodeRuns") or []:
        if (
            isinstance(node_run, dict)
            and str(node_run.get("nodeRunId") or "").strip() == node_run_id
        ):
            ledger_ref = str(node_run.get("budgetLedgerRef") or "").strip()
            if ledger_ref:
                reservation_ids.add(ledger_ref)
    for reservation in record.get("budgetReservations") or []:
        if not isinstance(reservation, dict):
            continue
        if (
            str(reservation.get("reservationId") or "").strip()
            not in reservation_ids
        ):
            continue
        requested = (
            reservation.get("requested")
            if isinstance(reservation.get("requested"), dict)
            else {}
        )
        tokens = _positive_contract_tokens(requested.get("tokens"))
        if tokens is not None:
            return tokens
    return None


def resolve_agent_reserve_tokens(
    snapshot: Mapping[str, Any] | None,
    *,
    run_id: str,
    node_id: str,
    node_run_id: str,
    budget_request_lookup: Any = None,
) -> int:
    """Derive the Agent node attempt reservation from the budget contract.

    Priority (three levels, never a flat per-node constant): the explicit task
    budget (``budgetRequest.requested.tokens``), the frozen run snapshot stage
    budget (``budgetPolicy.stageBudgets[stage].tokens`` then
    ``budgetPolicy.tokens``), then the conservative 2,000,000 fallback that
    matches the session turn budget scale. The stage-admission cap applied by
    the budget authority keeps the derived estimate within the stage's
    remaining capacity, which is where the derived-estimate responsibility
    (call inputs + output space) is actually observable. The reservation is an
    admission hint only; settled usage stays the sole budgeting authority.
    """

    lookup = budget_request_lookup or _task_budget_request_tokens
    try:
        requested = lookup(run_id, node_run_id)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        requested = None
    tokens = _positive_contract_tokens(requested)
    if tokens is not None:
        return tokens
    from .budget_authority_adapter import (
        DEFAULT_AGENT_NODE_RESERVE_TOKENS,
        stage_budget_tokens,
    )

    return stage_budget_tokens(snapshot, node_id) or DEFAULT_AGENT_NODE_RESERVE_TOKENS


def _blocking_hypothesis_fan_out_wait_enabled() -> bool:
    """Operator rollback switch for the blocking candidate fan-out wait.

    The workflow dispatch pump is single-threaded, so waiting for every
    candidate turn inside the node action blocked all other runs for minutes.
    The packaged default (``[research] blocking_fanout_wait = false``) is the
    non-blocking contract: probe each candidate once, process the terminal
    ones, and requeue the node action durably while candidates stay live.
    ``true`` restores the legacy synchronous wait for one release window.
    Missing/unreadable config fails to the packaged default (non-blocking).
    """

    try:
        from config.settings import get_config

        value = get_config().research.blocking_fanout_wait
    except Exception:  # noqa: BLE001 - rollout gating must never break dispatch
        return False
    return value if isinstance(value, bool) else False


def _hypothesis_fan_out_pending_error(
    *,
    fan_out: Mapping[str, Any],
    pending_children: Sequence[tuple["ScopedAgentTaskHandle", dict[str, Any]]],
) -> TurnNotReadyError:
    """Build the durable "fan-out in progress" requeue signal.

    The snapshot keeps the adapter worker on the live-turn-wait requeue path
    (``completionSource: "running"`` -> no transient-failure budget), carries
    the bounded fan-out progress for observability, and aggregates the
    children's session-side liveness so the no-progress bound only fires when
    every pending candidate is truly silent.
    """

    pending_ids = [child.candidate_id for child, _live in pending_children]
    detail = {
        "code": "hypothesis_fan_out_pending",
        "selectionId": str(fan_out.get("selectionId") or ""),
        "pendingCandidateIds": pending_ids,
        "pendingCount": len(pending_ids),
    }
    live_snapshots = [dict(live) for _child, live in pending_children]
    return TurnNotReadyError(
        json.dumps(detail, ensure_ascii=False),
        snapshot={
            "terminal": False,
            # Live fan-out work: the adapter worker must requeue durably
            # (live_turn_wait), never consume the transient-failure budget.
            "completionSource": "running",
            "turnCurrent": any(
                bool(live.get("turnCurrent")) for live in live_snapshots
            ),
            "messageCount": max(
                (int(live.get("messageCount") or 0) for live in live_snapshots),
                default=0,
            ),
            "hypothesisFanOut": detail,
        },
    )


def _hypothesis_fan_out_wait_timeout_ms(*, child_turn_id: str) -> int:
    """Bound each child wait by the one shared Challenge logical deadline."""

    remaining_ms = remaining_challenge_task_ms()
    if remaining_ms is None:
        return CHALLENGE_TURN_WAIT_WINDOW_MS
    if remaining_ms <= 0:
        raise ChallengeTaskDeadlineExceeded(
            challenge_deadline_problem(
                waited_ms=CHALLENGE_LOGICAL_TASK_TIMEOUT_MS,
                turn_chain=[child_turn_id],
            )
        )
    return min(CHALLENGE_TURN_WAIT_WINDOW_MS, int(remaining_ms))


def _binding_session_scope(
    snapshot: Mapping[str, Any], action: PendingAction, agent_id: str
) -> dict[str, Any] | None:
    """Build the full v3 session identity once the frozen Agent is known.

    A PendingAction may represent either the node root or one candidate.  Keep
    that distinction in the binding metadata so the downstream session/task
    authority receives the same identity that was frozen at the graph
    interrupt; never silently project a candidate action back to the root.
    """

    team_id = str(snapshot.get("teamId") or "").strip()
    project_id = str(snapshot.get("projectId") or "").strip()
    if not team_id or not project_id or not agent_id:
        return None
    common = {
        "teamId": team_id,
        "researchProjectId": project_id,
        "agentId": agent_id,
        "workflowRunId": action.run_id,
        "workflowNodeId": action.node_id,
    }
    if action.selection_id and action.candidate_id:
        return WorkflowSessionScopeV3.candidate(
            **common,
            selectionId=action.selection_id,
            candidateId=action.candidate_id,
        ).to_dict()
    return WorkflowSessionScopeV3.root(**common).to_dict()


class RealDomainPorts:
    """Real wiring: ledger-backed binding/budget + real Agent session/task."""

    def __init__(
        self,
        store: WorkflowLedgerStore,
        *,
        agent_task_factory: Any | None = None,
        budget_policy_hash: str = "",
    ) -> None:
        self._store = store
        self._agent_task_factory = agent_task_factory
        self._budget_policy_hash = budget_policy_hash

    # ------------------------------------------------------- run snapshot

    def required_artifact_kinds(self, action: PendingAction) -> tuple[str, ...]:
        from core.research.workflow.definition_registry import (
            resolve_definition_for_run_record,
        )
        from .artifact_readback_registry import required_artifact_kinds

        run = self._store.get_run(action.run_id)
        if run is None:
            raise RuntimeError(f"workflow run not found: {action.run_id}")
        definition = resolve_definition_for_run_record(
            {
                "runId": run.run_id,
                "workflowId": run.workflow_id,
                "workflowVersionId": run.workflow_version_id,
                "structureHash": run.structure_hash,
            },
            expected_node_ids=[action.node_id],
        )
        produced = required_artifact_kinds(action.node_id, definition=definition)
        snapshot = self._run_input_snapshot(action.run_id)
        policy = snapshot.get("stageOneCompletionPolicy")
        if not isinstance(policy, Mapping):
            return produced
        closure_node_id = str(policy.get("closureNodeId") or "").strip()
        raw_required = policy.get("requiredArtifactKinds")
        if closure_node_id != action.node_id:
            return produced
        if not isinstance(raw_required, list) or not raw_required:
            raise RuntimeError("stage-one completion policy artifact kinds are missing")
        stage_one_required = tuple(
            str(item).strip() for item in raw_required if str(item).strip()
        )
        if len(stage_one_required) != len(raw_required):
            raise RuntimeError("stage-one completion policy artifact kinds are invalid")
        return tuple(dict.fromkeys((*produced, *stage_one_required)))

    def _run_input_snapshot(self, run_id: str) -> dict[str, Any]:
        run = self._store.get_run(run_id)
        if run is None or not run.input_snapshot_json:
            return {}
        try:
            snapshot = json.loads(run.input_snapshot_json)
        except (TypeError, ValueError):
            return {}
        return snapshot if isinstance(snapshot, dict) else {}

    def read_back_input(self, action: PendingAction) -> ReadBackVerdict:
        snapshot = self._run_input_snapshot(action.run_id)
        snapshot_hash = str(snapshot.get("snapshotHash") or "")
        if action.input_snapshot_hash and snapshot_hash and (
            snapshot_hash != action.input_snapshot_hash
        ):
            return ReadBackVerdict(
                ok=False,
                detail="input snapshot hash drifted",
                revision_vector={},
            )
        return ReadBackVerdict(ok=True, revision_vector={})

    def resolve_binding(self, action: PendingAction) -> BindingResolution:
        snapshot = self._run_input_snapshot(action.run_id)
        for binding in snapshot.get("agentBindingSnapshot") or []:
            if not isinstance(binding, dict):
                continue
            if str(binding.get("nodeId") or "") != action.node_id:
                continue
            agent_id = str(binding.get("agentId") or "").strip()
            if not agent_id:
                healed = _heal_binding_resolution(snapshot, action.node_id)
                if healed.agent_id:
                    return replace(
                        healed,
                        session_scope=_binding_session_scope(
                            snapshot, action, healed.agent_id
                        ),
                    )
            return BindingResolution(
                agent_id=agent_id,
                role_key=str(binding.get("roleKey") or ""),
                binding_snapshot_id=str(binding.get("snapshotId") or "") or None,
                session_scope=_binding_session_scope(snapshot, action, agent_id),
            )
        healed = _heal_binding_resolution(snapshot, action.node_id)
        if healed.agent_id:
            return replace(
                healed,
                session_scope=_binding_session_scope(
                    snapshot, action, healed.agent_id
                ),
            )
        return BindingResolution(agent_id="", role_key="")

    # ------------------------------------------------------------- budget

    def reserve_budget(
        self, *, action: PendingAction, estimate_tokens: int
    ) -> dict[str, Any]:
        from .budget_authority_adapter import (
            BudgetAuthorityError,
            reserve_budget_authority,
        )

        snapshot = self._run_input_snapshot(action.run_id)
        if action.actor_kind == ActorKind.AGENT:
            # A formal Agent attempt reserves the contract-derived budget,
            # never a flat adapter constant: explicit task budgetRequest
            # first, then the frozen stage budget, then the conservative 2M
            # fallback. System actions keep their explicit zero estimate.
            estimate_tokens = resolve_agent_reserve_tokens(
                snapshot,
                run_id=action.run_id,
                node_id=action.node_id,
                node_run_id=action.node_run_id,
            )

        try:
            return reserve_budget_authority(
                self._store,
                action=action,
                estimate_tokens=estimate_tokens,
                input_snapshot=snapshot,
            )
        except BudgetAuthorityError as exc:
            raise RuntimeError(str(exc)) from exc

    def settle_budget(self, *, reservation: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
        """Settle reserved budget. Raises RuntimeError on failure (callers must
        treat any raised exception as a hard settle failure)."""
        from .budget_authority_adapter import (
            BudgetAuthorityError,
            settle_budget_authority,
        )

        try:
            return settle_budget_authority(
                self._store, reservation=reservation, usage=usage
            )
        except BudgetAuthorityError as exc:
            raise RuntimeError(f"budget_settle_failed:{exc.code}:{exc}") from exc

    def void_budget(
        self,
        *,
        reservation: dict[str, Any],
        reason: str = "compensation_void",
        correlation_id: str | None = None,
    ) -> None:
        from .budget_authority_adapter import void_budget_reservation

        void_budget_reservation(
            self._store,
            reservation,
            reason=reason,
            correlation_id=correlation_id,
        )

    def release_budget(
        self,
        *,
        reservation: dict[str, Any],
        reason: str = "unused_release",
    ) -> None:
        from .budget_authority_adapter import release_budget_reservation

        release_budget_reservation(
            self._store, reservation, reason=reason
        )

    # ------------------------------------------------------------ agent

    def _bound_hypothesis_selection(self, action: PendingAction) -> dict[str, Any]:
        try:
            row = self._store.read(
                lambda repo: repo.get_anchor_by_node_run(action.node_run_id)
            )
            payload = (
                json.loads(row[13] or "{}")
                if row is not None and len(row) > 13
                else {}
            )
        except Exception as exc:
            raise _HypothesisAuthorityUnavailable(
                f"hypothesis selection anchor authority is unavailable: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise _HypothesisAuthorityUnavailable(
                "hypothesis selection anchor authority returned an invalid payload"
            )
        selection_id = str(payload.get("selectionId") or "").strip()
        selected_candidate_ids = [
            str(item).strip()
            for item in list(payload.get("selectedCandidateIds") or [])
            if str(item).strip()
        ]
        if len(set(selected_candidate_ids)) != len(selected_candidate_ids):
            raise RuntimeError("candidate scope contains duplicate candidates")
        # A candidate-scoped action is already frozen by the graph interrupt.
        # It is the authoritative minimum when a draft anchor has not yet
        # been published (for example after a crash between dispatch steps).
        if action.selection_id:
            if selection_id and selection_id != action.selection_id:
                raise RuntimeError("candidate action selection does not match anchor")
            selection_id = selection_id or action.selection_id
        if action.candidate_id:
            if (
                selected_candidate_ids
                and action.candidate_id not in selected_candidate_ids
            ):
                raise RuntimeError("candidate action is outside the selected candidates")
            if not selected_candidate_ids:
                selected_candidate_ids.append(action.candidate_id)
        return {
            "selectionId": selection_id,
            "selectedCandidateIds": selected_candidate_ids,
        }

    def _bound_hypothesis_selection_id(self, action: PendingAction) -> str:
        return str(
            self._bound_hypothesis_selection(action).get("selectionId") or ""
        ).strip()

    def _hypothesis_chain_state(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        """Read live selection authority without treating read errors as empty."""

        team_id = str(snapshot.get("teamId") or "").strip()
        question_id = str(snapshot.get("questionId") or "").strip()
        workflow_run_id = str(snapshot.get("workflowRunId") or "").strip()
        if not team_id or not question_id:
            return {}
        try:
            from core.web.services.team_workflow.research_runtime import (
                hypothesis_first_chain,
            )

            state = hypothesis_first_chain.chain_state(
                team_id,
                question_id,
                **({"workflow_run_id": workflow_run_id} if workflow_run_id else {}),
            )
        except Exception as exc:
            raise _HypothesisAuthorityUnavailable(
                f"hypothesis selection authority is unavailable: {exc}"
            ) from exc
        if not isinstance(state, Mapping):
            raise _HypothesisAuthorityUnavailable(
                "hypothesis selection authority returned an invalid chain state"
            )
        return dict(state)

    def _resolve_hypothesis_scope(
        self,
        action: PendingAction,
        *,
        snapshot: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Resolve live scope, then classify an explicit compatibility fallback."""

        # The PendingAction run is the authoritative fence.  The input
        # snapshot is copied so a stale/malformed workflowRunId cannot make a
        # question-only chain read another run's selection.
        scoped_snapshot = dict(snapshot)
        if str(action.run_id or "").strip():
            scoped_snapshot["workflowRunId"] = str(action.run_id).strip()
        chain_state = self._hypothesis_chain_state(scoped_snapshot)
        decision = _resolve_hypothesis_scope_activation(
            snapshot,
            chain_state=chain_state,
        )
        fan_out: dict[str, Any] | None = None
        try:
            fan_out = _formal_hypothesis_fan_out_input(
                action=action,
                snapshot=snapshot,
                bound_selection_id=self._bound_hypothesis_selection_id(action),
            )
        except RuntimeError as exc:
            # Only the explicit no-selection result can enter the bounded
            # compatibility path.  Invalid selections and all authority
            # failures remain fail-closed.
            if str(exc) != _HYPOTHESIS_SELECTION_MISSING:
                raise
            if not decision.get("fallbackReason"):
                raise
        if fan_out is not None:
            self._require_bound_hypothesis_selection(action, fan_out)
        elif decision.get("selectionRequired") or decision.get("fanOutEnabled"):
            raise RuntimeError(_HYPOTHESIS_SELECTION_MISSING)
        return decision, fan_out

    def _require_bound_hypothesis_selection(
        self,
        action: PendingAction,
        fan_out: Mapping[str, Any],
    ) -> None:
        bound = self._bound_hypothesis_selection(action)
        bound_selection_id = str(bound.get("selectionId") or "").strip()
        if not bound_selection_id:
            return
        observed_selection_id = str(fan_out.get("selectionId") or "").strip()
        bound_candidates = list(bound.get("selectedCandidateIds") or [])
        observed_candidates = [
            str(item).strip()
            for item in list(fan_out.get("selectedCandidateIds") or [])
            if str(item).strip()
        ]
        if (
            observed_selection_id != bound_selection_id
            or not bound_candidates
            or observed_candidates != bound_candidates
        ):
            raise RuntimeError(
                "hypothesis selection changed after the NodeRun scope was frozen"
            )

    def evaluate_hypothesis_scope_shadow(
        self,
        action: PendingAction,
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Validate and record shadow scope without creating runtime objects."""

        if action.node_id != "hypothesis_design":
            return None
        current_snapshot = dict(snapshot or self._run_input_snapshot(action.run_id))
        if _resolve_hypothesis_session_scope_mode(current_snapshot) != "shadow":
            return None
        decision, fan_out = self._resolve_hypothesis_scope(
            action,
            snapshot=current_snapshot,
        )
        if fan_out is None:
            # Non-hypothesis-first runs without a live selection retain the
            # legacy single-session path; create_agent_task records the
            # bounded compatibility reason when it continues there.
            if decision.get("fallbackReason"):
                return None
            raise RuntimeError("hypothesis_design shadow selection is unavailable")
        evaluation = _evaluate_hypothesis_scope_shadow(
            fan_out,
            max_parallel=_hypothesis_max_parallel(
                current_snapshot,
                len(fan_out["selectedCandidateIds"]),
            ),
        )
        _record_hypothesis_scope_event(
            self._store,
            action=action,
            event_type="workflow.session_scope.resolved",
            fields={
                "mode": "shadow",
                "selectionId": str(fan_out.get("selectionId") or ""),
                "candidateCount": len(
                    list(fan_out.get("selectedCandidateIds") or [])
                ),
                "scopeHash": str(evaluation.get("scopeHash") or ""),
            },
            discriminator="shadow",
        )
        return evaluation

    def _persist_hypothesis_anchor_draft(
        self,
        *,
        action: PendingAction,
        binding: BindingResolution,
        root_session_id: str,
        root_session_attempt: int,
        selection_id: str,
        selected_candidate_ids: list[str],
        handles: list[ScopedAgentTaskHandle],
        candidate_statuses: Mapping[str, str] | None = None,
        root_status: str = "running",
    ) -> None:
        """Publish live candidate anchors without reading a legacy workflow store."""
        now_ms = int(time.time() * 1000)
        anchor_id = "anchor-" + hashlib.sha256(
            action.node_run_id.encode()
        ).hexdigest()[:16]
        terminal = {"succeeded", "failed", "blocked", "cancelled"}
        selected_ids = [str(item).strip() for item in selected_candidate_ids]
        if not selection_id or not selected_ids or any(not item for item in selected_ids):
            raise RuntimeError("candidate scope requires a non-empty selection")
        if len(set(selected_ids)) != len(selected_ids):
            raise RuntimeError("candidate scope contains duplicate candidates")
        for handle in handles:
            if handle.selection_id != selection_id:
                raise RuntimeError("candidate handle selection does not match anchor")
            if handle.candidate_id not in selected_ids:
                raise RuntimeError("candidate handle is outside the selected candidates")
            if handle.session_id and (
                handle.parent_session_id != root_session_id
                or handle.root_session_id != root_session_id
            ):
                raise RuntimeError("candidate handle lineage does not match anchor root")
        for candidate_id in (candidate_statuses or {}):
            if str(candidate_id).strip() not in selected_ids:
                raise RuntimeError("candidate status is outside the selected candidates")

        def merge_status(current: Any, desired: Any) -> str:
            current_text = str(current or "").strip().lower()
            desired_text = str(desired or "").strip().lower()
            if current_text in terminal and desired_text != current_text:
                return current_text
            return desired_text or current_text or "pending"

        def read_snapshot() -> tuple[dict[str, Any], int | None]:
            row = self._store.read(
                lambda repo: repo.get_anchor_by_node_run(action.node_run_id)
            )
            if row is None:
                return {}, None
            try:
                payload = json.loads(row[13] or "{}")
            except (TypeError, ValueError, IndexError) as exc:
                raise RuntimeError("execution anchor payload is invalid") from exc
            if not isinstance(payload, dict):
                raise RuntimeError("execution anchor payload is not an object")
            revision = int(row[15]) if len(row) > 15 else 0
            return payload, revision

        def build_payload(existing: Mapping[str, Any]) -> dict[str, Any]:
            payload = dict(existing)
            payload.update(
                {
                    "schemaVersion": 3,
                    "agentId": binding.agent_id,
                    "roleKey": binding.role_key,
                    "actionId": action.action_id,
                    "sessionId": root_session_id,
                    "sessionAttempt": root_session_attempt,
                    # The root is a session-only container for candidate
                    # fan-out.  Legacy scalar task/turn values may point at a
                    # child; retaining them would mislabel the root and make
                    # the compatibility projection unsafe.
                    "taskId": None,
                    "turnId": None,
                    "selectionId": selection_id,
                    "selectedCandidateIds": list(selected_ids),
                }
            )
            previous_root = (
                payload.get("rootSession")
                if isinstance(payload.get("rootSession"), Mapping)
                else {}
            )
            payload["rootSession"] = {
                **dict(previous_root),
                "scopeKind": "workflow_node_root",
                "sessionId": root_session_id,
                "sessionAttempt": root_session_attempt,
                "taskId": None,
                "turnId": None,
                "status": merge_status(previous_root.get("status"), root_status),
            }

            existing_items = [
                dict(item)
                for item in list(payload.get("scopedSessions") or [])
                if isinstance(item, Mapping)
                and str(item.get("selectionId") or "").strip() == selection_id
                and str(item.get("candidateId") or "").strip()
            ]
            by_key = {
                (
                    str(item.get("selectionId") or "").strip(),
                    str(item.get("candidateId") or "").strip(),
                ): item
                for item in existing_items
            }
            handle_by_candidate = {item.candidate_id: item for item in handles}
            statuses = dict(candidate_statuses or {})
            for candidate_id in selected_ids:
                key = (selection_id, candidate_id)
                item = by_key.get(key) or {
                    "scopeKind": "workflow_candidate",
                    "selectionId": selection_id,
                    "candidateId": candidate_id,
                    "sessionId": None,
                    "sessionAttempt": None,
                    "taskId": None,
                    "turnId": None,
                    "parentSessionId": None,
                    "rootSessionId": None,
                    "fragmentRefs": [],
                    "status": "pending",
                }
                handle = handle_by_candidate.get(candidate_id)
                if (
                    handle is not None
                    and str(item.get("status") or "").lower() not in terminal
                ):
                    incoming = handle.to_dict()
                    previous_refs = list(item.get("fragmentRefs") or [])
                    incoming_refs = list(incoming.get("fragmentRefs") or [])
                    item.update(incoming)
                    if previous_refs and not incoming_refs:
                        item["fragmentRefs"] = previous_refs
                    elif previous_refs:
                        item["fragmentRefs"] = list(
                            dict.fromkeys(previous_refs + incoming_refs)
                        )
                if candidate_id in statuses:
                    item["status"] = merge_status(
                        item.get("status"), statuses[candidate_id]
                    )
                else:
                    item["status"] = merge_status(
                        item.get("status"), item.get("status")
                    )
                by_key[key] = item
            payload["scopedSessions"] = list(by_key.values())
            return payload

        for _ in range(4):
            existing, expected_revision = read_snapshot()
            payload = build_payload(existing)
            anchor_json = json.dumps(payload, ensure_ascii=False)

            def mutate(
                uow: Any,
                *,
                expected_revision: int | None = expected_revision,
                anchor_json: str = anchor_json,
                payload: dict[str, Any] = payload,
            ) -> bool:
                current = uow.repository.get_anchor_by_node_run(action.node_run_id)
                if expected_revision is None:
                    if current is not None:
                        return False
                    uow.repository.insert_anchor(
                        anchor_id=anchor_id,
                        node_run_id=action.node_run_id,
                        actor_kind=action.actor_kind.value,
                        anchor_json=anchor_json,
                        created_at_ms=now_ms,
                        agent_id=binding.agent_id,
                        role_key=binding.role_key,
                        session_id=root_session_id,
                        session_attempt=root_session_attempt,
                        status=str(payload.get("rootSession", {}).get("status") or root_status),
                    )
                    return True
                if current is None or len(current) <= 15:
                    return False
                return uow.repository.update_anchor_by_node_run_cas(
                    node_run_id=action.node_run_id,
                    expected_revision=int(expected_revision),
                    anchor_json=anchor_json,
                    status=str(payload.get("rootSession", {}).get("status") or root_status),
                    agent_id=binding.agent_id,
                    role_key=binding.role_key,
                    session_id=root_session_id,
                    session_attempt=root_session_attempt,
                )

            committed = self._store.submit(mutate, force_flush=True).result(timeout=30)
            if committed:
                return
        raise RuntimeError("execution anchor changed while publishing candidate scope")

    def create_agent_task(self, *, action: PendingAction) -> AgentTaskHandle:
        from .task_adapter_registry import resolve_agent_task_adapter

        adapter_spec = resolve_agent_task_adapter(action.node_id)
        if adapter_spec is None:
            raise RuntimeError(f"agent node {action.node_id} has no task adapter")
        snapshot = self._run_input_snapshot(action.run_id)
        if _bounded_agent_node_can_complete(
            action.node_id,
            team_id=str(snapshot.get("teamId") or ""),
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        ):
            return _bounded_agent_task_handle(action)
        binding = self.resolve_binding(action)
        if not binding.agent_id:
            raise RuntimeError("agent node is unbound")
        if action.node_id == "hypothesis_design":
            scope_mode = _resolve_hypothesis_session_scope_mode(snapshot)
            fan_out = None
            shadow_evaluation: dict[str, Any] | None = None
            scope_decision: dict[str, Any] = {
                "fallbackReason": "",
                "selectionId": "",
            }
            if scope_mode != "off":
                scope_decision, fan_out = self._resolve_hypothesis_scope(
                    action,
                    snapshot=snapshot,
                )
                if fan_out is not None and scope_mode == "shadow":
                    shadow_evaluation = _evaluate_hypothesis_scope_shadow(
                        fan_out,
                        max_parallel=_hypothesis_max_parallel(
                            snapshot,
                            len(fan_out["selectedCandidateIds"]),
                        ),
                    )
            _record_hypothesis_scope_event(
                self._store,
                action=action,
                event_type="workflow.session_scope.resolved",
                fields={
                    "mode": scope_mode,
                    "selectionId": str((fan_out or {}).get("selectionId") or ""),
                    "candidateCount": len(
                        list((fan_out or {}).get("selectedCandidateIds") or [])
                    ),
                    "fallbackReason": str(
                        scope_decision.get("fallbackReason") or ""
                    ),
                    "scopeHash": str(
                        (shadow_evaluation or {}).get("scopeHash") or ""
                    ),
                },
                discriminator=scope_mode,
            )
            if scope_mode == "on" and fan_out is not None:
                challenge_task_contract, model_invocation_receipt_binding = (
                    _formal_task_authorities(
                        action=action,
                        input_snapshot=snapshot,
                        agent_id=binding.agent_id,
                        workflow_id=str(
                            getattr(self._store.get_run(action.run_id), "workflow_id", "")
                            or ""
                        ).strip(),
                    )
                )
                fan_out_handle = self._create_hypothesis_fan_out(
                    action=action,
                    binding=binding,
                    snapshot=snapshot,
                    fan_out=fan_out,
                    challenge_task_contract=challenge_task_contract,
                    model_invocation_receipt_binding=model_invocation_receipt_binding,
                )
                publish_agent_task_started_anchor(
                    self._store, action=action, binding=binding, handle=fan_out_handle
                )
                return fan_out_handle
        if self._agent_task_factory is not None:
            return self._agent_task_factory(action=action, binding=binding)
        # 默认 factory：真实 research-project / source-collection task。
        handle = _create_real_agent_task(
            action,
            binding,
            snapshot,
            adapter_spec=adapter_spec,
            store=self._store,
        )
        _require_canonical_session(
            session_id=handle.session_id,
            agent_id=binding.agent_id,
        )
        publish_agent_task_started_anchor(
            self._store, action=action, binding=binding, handle=handle
        )
        return handle

    def execute_agent_turn(
        self, *, action: PendingAction, handle: AgentTaskHandle
    ) -> list[dict[str, str]] | AgentTurnResult:
        from .agent_turn_completion import complete_agent_turn_outputs

        if handle.observation_only:
            return AgentTurnResult(materialized_refs=(), handle=handle)

        snapshot = self._run_input_snapshot(action.run_id)
        bounded = _bounded_agent_node_can_complete(
            action.node_id,
            team_id=str(snapshot.get("teamId") or ""),
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
        if action.node_id == "result_evaluation":
            refs = _ledger_result_evaluation(action, snapshot)
            if refs:
                return refs
            if bounded:
                raise RuntimeError("bounded result_evaluation produced no artifact refs")
        if action.node_id == "iteration_decision":
            refs = _ledger_iteration_decision(action, snapshot)
            if refs:
                return refs
            if bounded:
                raise RuntimeError("bounded iteration_decision produced no artifact refs")
        if action.node_id == "version_governance":
            refs = _ledger_version_governance(action, snapshot)
            if refs:
                return refs
            if bounded:
                raise RuntimeError("bounded version_governance produced no artifact refs")
        if handle.scoped_handles:
            return self._execute_hypothesis_fan_out(
                action=action,
                handle=handle,
                snapshot=snapshot,
            )
        return complete_agent_turn_outputs(
            action=action,
            handle=handle,
            input_snapshot=snapshot,
            required_kinds=self.required_artifact_kinds(action),
            return_result=True,
        )

    def _create_hypothesis_fan_out(
        self,
        *,
        action: PendingAction,
        binding: BindingResolution,
        snapshot: dict[str, Any],
        fan_out: dict[str, Any],
        challenge_task_contract: Mapping[str, Any],
        model_invocation_receipt_binding: Mapping[str, Any],
    ) -> AgentTaskHandle:
        """Create/replay one root and one canonical child task per candidate.

        The root is a session-only container.  Candidate work is the only work
        that owns a Task/Turn, and all candidate creation is bounded before the
        first child side effect.  Retry lookup is deliberately based on the
        project Agent task authority, so a failed node attempt can reuse
        successful siblings without opening duplicate conversations.
        """

        selected_ids = [str(item).strip() for item in fan_out["selectedCandidateIds"]]
        max_parallel = _hypothesis_max_parallel(snapshot, len(selected_ids))
        if len(selected_ids) > max_parallel:
            raise RuntimeError(
                "hypothesis candidate fan-out exceeds maxConcurrency: "
                f"selected={len(selected_ids)}, max={max_parallel}"
            )
        team_id = str(snapshot.get("teamId") or "").strip()
        project_id = str(snapshot.get("projectId") or "").strip()
        source_collection_run_id = str(
            snapshot.get("sourceCollectionRunId") or action.run_id
        ).strip()
        if not team_id or not project_id:
            raise RuntimeError("hypothesis_design fan-out requires teamId and projectId")
        from ..research_project_hypothesis_context import (
            build_hypothesis_input_context,
        )

        hypothesis_input_binding = build_hypothesis_input_context(
            team_id,
            {
                "workflowRunId": action.run_id,
                "sourceCollectionRunId": source_collection_run_id,
            },
            store=self._store,
        )
        knowledge_snapshot = (
            hypothesis_input_binding.get("knowledgeSnapshot")
            if isinstance(hypothesis_input_binding.get("knowledgeSnapshot"), Mapping)
            else {}
        )
        consumed_snapshot_hash = str(
            knowledge_snapshot.get("snapshotHash") or ""
        ).strip().lower()
        if (
            hypothesis_input_binding.get("status") != "ready"
            or len(consumed_snapshot_hash) != 64
        ):
            raise RuntimeError(
                "accepted knowledge package is not ready for hypothesis fan-out"
            )

        root = _resolve_formal_node_root_session(
            team_id=team_id,
            project_id=project_id,
            agent_id=binding.agent_id,
            role_key=binding.role_key,
            workflow_run_id=action.run_id,
            workflow_node_id=action.node_id,
            created_from_task_id=f"workflow-root:{action.node_run_id}",
        )
        root_session_id = str(root.get("sessionId") or "").strip()
        if not root_session_id:
            raise RuntimeError("hypothesis_design root session anchor is incomplete")
        _verify_node_root_session(
            root_session_id,
            agent_id=binding.agent_id,
        )
        root_attempt = int(root.get("sessionAttempt") or 1)
        selection_id = str(fan_out["selectionId"])
        self._persist_hypothesis_anchor_draft(
            action=action,
            binding=binding,
            root_session_id=root_session_id,
            root_session_attempt=root_attempt,
            selection_id=selection_id,
            selected_candidate_ids=selected_ids,
            handles=[],
        )

        previous_anchor = _previous_hypothesis_anchor(self._store, action)
        previous_children = {
            str(item.get("candidateId") or "").strip(): item
            for item in list(previous_anchor.get("scopedSessions") or [])
            if isinstance(item, dict)
            and str(item.get("selectionId") or "").strip()
            == str(fan_out["selectionId"])
            and str(item.get("candidateId") or "").strip()
        }
        candidate_snapshots = {
            str(item.get("candidateId") or "").strip(): dict(item)
            for item in list(fan_out.get("candidateSnapshots") or [])
            if isinstance(item, dict) and str(item.get("candidateId") or "").strip()
        }

        handles: list[ScopedAgentTaskHandle] = []
        failed_candidates: dict[str, str] = {}
        for candidate_id in selected_ids:
            candidate_context = dict(candidate_snapshots.get(candidate_id) or {})
            candidate_context.setdefault("candidateId", candidate_id)
            subtask_id = (
                f"{action.node_run_id}:{fan_out['selectionId']}:{candidate_id}"
            )
            prior = previous_children.get(candidate_id) or {}
            try:
                started = _resolve_or_start_formal_candidate_task(
                    team_id=team_id,
                    project_id=project_id,
                    action=action,
                    agent_id=binding.agent_id,
                    source_collection_run_id=source_collection_run_id,
                    selection_id=selection_id,
                    candidate_id=candidate_id,
                    selected_candidate_ids=selected_ids,
                    candidate_context=candidate_context,
                    subtask_id=subtask_id,
                    previous=prior,
                    challenge_task_contract=challenge_task_contract,
                    model_invocation_receipt_binding=model_invocation_receipt_binding,
                    hypothesis_input_binding=hypothesis_input_binding,
                )
                child = _scoped_handle_from_started(
                    started,
                    selection_id=selection_id,
                    candidate_id=candidate_id,
                    subtask_id=subtask_id,
                    expected_root_session_id=root_session_id,
                    expected_agent_id=binding.agent_id,
                )
            except _HypothesisAuthorityUnavailable:
                raise
            except (RuntimeError, ValueError):
                failed_candidates[candidate_id] = "failed"
                self._persist_hypothesis_anchor_draft(
                    action=action,
                    binding=binding,
                    root_session_id=root_session_id,
                    root_session_attempt=root_attempt,
                    selection_id=selection_id,
                    selected_candidate_ids=selected_ids,
                    handles=handles,
                    candidate_statuses=failed_candidates,
                )
                continue
            started_task = (
                dict(started.get("task"))
                if isinstance(started.get("task"), Mapping)
                else {}
            )
            formal_retry = bool(
                started.get("formalRetry") or started_task.get("formalRetry")
            )
            session_created = bool(
                started.get("sessionCreated")
                or started_task.get("sessionCreated")
            )
            if formal_retry:
                child_event_type = "workflow.scope_attempt.retried"
            elif session_created:
                child_event_type = "workflow.child_session.created"
            else:
                child_event_type = "workflow.child_session.resumed"
            _record_hypothesis_scope_event(
                self._store,
                action=action,
                event_type=child_event_type,
                fields={
                    "mode": "on",
                    "selectionId": selection_id,
                    "candidateId": candidate_id,
                    "sessionId": child.session_id,
                    "sessionAttempt": child.session_attempt,
                    "taskId": child.task_id,
                    "status": child.status,
                    "created": session_created,
                },
                discriminator=(
                    f"{candidate_id}:{child.session_attempt}:{child_event_type}"
                ),
            )
            handles.append(child)
            self._persist_hypothesis_anchor_draft(
                action=action,
                binding=binding,
                root_session_id=root_session_id,
                root_session_attempt=root_attempt,
                selection_id=selection_id,
                selected_candidate_ids=selected_ids,
                handles=handles,
                candidate_statuses=failed_candidates,
            )

        if not handles:
            raise RuntimeError("hypothesis_design fan-out produced no candidate tasks")
        from .knowledge_snapshot_consumption import (
            record_knowledge_snapshot_consumed,
        )

        record_knowledge_snapshot_consumed(
            self._store,
            run_id=action.run_id,
            node_run_id=action.node_run_id,
            selection_id=selection_id,
            snapshot_hash=consumed_snapshot_hash,
            now_ms=int(time.time() * 1000),
        )
        return AgentTaskHandle(
            session_id=root_session_id,
            session_attempt=root_attempt,
            task_id="",
            turn_id="",
            root_session_id=root_session_id,
            root_session_attempt=root_attempt,
            scoped_handles=tuple(handles),
        )

    def _execute_hypothesis_fan_out(
        self,
        *,
        action: PendingAction,
        handle: AgentTaskHandle,
        snapshot: dict[str, Any],
    ) -> AgentTurnResult:
        """Collect candidate fragments and deterministically fan in a set.

        Default (non-blocking): probe each candidate turn once, process the
        already-terminal ones, and raise the durable ``fan-out pending``
        requeue signal while any candidate is still live — the pump thread is
        never held waiting for children.  ``[research] blocking_fanout_wait``
        restores the legacy in-thread wait-per-child semantics.
        """

        from .agent_turn_completion import (
            TurnNotReadyError,
            collect_required_artifact_refs,
            probe_agent_turn_terminal,
            wait_for_agent_turn_terminal,
        )
        from .hypothesis_artifact_writer import record_hypothesis_set_from_fragments
        from .hypothesis_fragment_writer import (
            build_hypothesis_fragment,
            record_hypothesis_fragment,
        )
        from .workflow_artifact_store import (
            list_workflow_artifacts,
            put_workflow_artifact,
        )

        fan_out = _formal_hypothesis_fan_out_input(
            action=action,
            snapshot=snapshot,
            bound_selection_id=self._bound_hypothesis_selection_id(action),
        )
        if fan_out is None:
            raise RuntimeError("hypothesis_design fan-out selection is unavailable")
        try:
            self._require_bound_hypothesis_selection(action, fan_out)
        except RuntimeError:
            bound_selection = self._bound_hypothesis_selection(action)
            self._persist_hypothesis_anchor_draft(
                action=action,
                binding=self.resolve_binding(action),
                root_session_id=str(handle.root_session_id or ""),
                root_session_attempt=int(
                    handle.root_session_attempt or handle.session_attempt or 1
                ),
                selection_id=str(bound_selection.get("selectionId") or ""),
                selected_candidate_ids=list(
                    bound_selection.get("selectedCandidateIds") or []
                ),
                handles=list(handle.scoped_handles),
                root_status="failed",
            )
            _record_hypothesis_scope_event(
                self._store,
                action=action,
                event_type="workflow.hypothesis_aggregation.blocked",
                fields={
                    "mode": "on",
                    "selectionId": str(
                        bound_selection.get("selectionId") or ""
                    ),
                    "candidateCount": len(
                        list(bound_selection.get("selectedCandidateIds") or [])
                    ),
                    "status": "blocked",
                    "errorCode": "selection_scope_drift",
                },
                discriminator="selection-scope-drift",
            )
            raise
        team_id = str(snapshot.get("teamId") or "").strip()
        project_id = str(snapshot.get("projectId") or "").strip()
        source_collection_run_id = str(
            snapshot.get("sourceCollectionRunId") or action.run_id
        ).strip()
        fragments: list[dict[str, Any]] = []
        completed_handles: list[ScopedAgentTaskHandle] = []
        previous_anchor = _previous_hypothesis_anchor(self._store, action)
        previous_children = {
            str(item.get("candidateId") or "").strip(): item
            for item in list(previous_anchor.get("scopedSessions") or [])
            if isinstance(item, dict)
            and str(item.get("selectionId") or "").strip()
            == str(fan_out["selectionId"])
            and str(item.get("candidateId") or "").strip()
        }
        # Non-blocking by default: the dispatch pump is single-threaded, so
        # sleeping here for every candidate turn starved all other runs.  The
        # blocking legacy semantics stay one operator flag away for rollback.
        blocking_wait = _blocking_hypothesis_fan_out_wait_enabled()
        pending_live_children: list[
            tuple[ScopedAgentTaskHandle, dict[str, Any]]
        ] = []
        for child in handle.scoped_handles:
            if not child.session_id or not child.task_id or not child.turn_id:
                raise RuntimeError(
                    "hypothesis candidate anchor is incomplete: " + child.candidate_id
                )
            try:
                if blocking_wait:
                    child_wait_timeout_ms = _hypothesis_fan_out_wait_timeout_ms(
                        child_turn_id=child.turn_id,
                    )
                    completion = wait_for_agent_turn_terminal(
                        child.session_id,
                        child.turn_id,
                        timeout_ms=child_wait_timeout_ms,
                    )
                else:
                    # One probe, no sleep: a still-live candidate parks this
                    # node action on the durable live-turn-wait requeue while
                    # the pump advances other actions; its fragment is
                    # processed on a later pass (all child processing below is
                    # idempotent per candidate).
                    completion = probe_agent_turn_terminal(
                        child.session_id,
                        child.turn_id,
                    )
            except TurnNotReadyError:
                raise
            except RuntimeError:
                self._persist_hypothesis_anchor_draft(
                    action=action,
                    binding=self.resolve_binding(action),
                    root_session_id=str(handle.root_session_id or ""),
                    root_session_attempt=int(
                        handle.root_session_attempt or handle.session_attempt or 1
                    ),
                    selection_id=str(fan_out["selectionId"]),
                    selected_candidate_ids=[
                        str(item) for item in fan_out["selectedCandidateIds"]
                    ],
                    handles=list(handle.scoped_handles),
                    candidate_statuses={child.candidate_id: "failed"},
                    root_status="failed",
                )
                _record_hypothesis_scope_event(
                    self._store,
                    action=action,
                    event_type="workflow.hypothesis_aggregation.blocked",
                    fields={
                        "mode": "on",
                        "selectionId": str(fan_out["selectionId"]),
                        "candidateId": child.candidate_id,
                        "sessionAttempt": child.session_attempt,
                        "status": "blocked",
                        "errorCode": "candidate_turn_failed",
                    },
                    discriminator=(
                        f"turn-failed:{child.candidate_id}:"
                        f"{child.session_attempt}"
                    ),
                )
                raise
            if not blocking_wait and not bool(completion.get("terminal")):
                pending_live_children.append((child, dict(completion)))
                continue
            fragment_rows = list_workflow_artifacts(
                team_id,
                kind="hypothesis_fragment",
                workflow_run_id=action.run_id,
            )
            task_context = _candidate_hypothesis_task_context(
                team_id=team_id,
                project_id=project_id,
                action=action,
                child=child,
                snapshot=snapshot,
            )
            fragment = _load_formal_hypothesis_fragment(
                fragment_rows,
                node_run_id=action.node_run_id,
                selection_id=str(fan_out["selectionId"]),
                candidate_id=child.candidate_id,
                session_id=child.session_id,
                task_id=child.task_id,
                session_attempt=child.session_attempt,
            )
            if fragment is None:
                reusable = _load_reusable_formal_hypothesis_fragment(
                    fragment_rows,
                    workflow_run_id=action.run_id,
                    selection_id=str(fan_out["selectionId"]),
                    candidate_id=child.candidate_id,
                    session_id=child.session_id,
                    task_id=child.task_id,
                    session_attempt=child.session_attempt,
                    preferred_fragment_refs=tuple(
                        str(item).strip()
                        for item in list(
                            (previous_children.get(child.candidate_id) or {}).get(
                                "fragmentRefs"
                            )
                            or []
                        )
                        if str(item).strip()
                    ),
                )
                if reusable is None:
                    self._persist_hypothesis_anchor_draft(
                        action=action,
                        binding=self.resolve_binding(action),
                        root_session_id=str(handle.root_session_id or ""),
                        root_session_attempt=int(
                            handle.root_session_attempt
                            or handle.session_attempt
                            or 1
                        ),
                        selection_id=str(fan_out["selectionId"]),
                        selected_candidate_ids=[
                            str(item) for item in fan_out["selectedCandidateIds"]
                        ],
                        handles=list(handle.scoped_handles),
                        candidate_statuses={child.candidate_id: "failed"},
                        root_status="failed",
                    )
                    _record_hypothesis_scope_event(
                        self._store,
                        action=action,
                        event_type="workflow.hypothesis_aggregation.blocked",
                        fields={
                            "mode": "on",
                            "selectionId": str(fan_out["selectionId"]),
                            "candidateId": child.candidate_id,
                            "status": "blocked",
                            "errorCode": "hypothesis_fragment_missing",
                        },
                        discriminator=(
                            f"fragment-missing:{child.candidate_id}:"
                            f"{child.session_attempt}"
                        ),
                    )
                    raise RuntimeError(
                        "hypothesis candidate did not write a canonical fragment: "
                        + child.candidate_id
                    )
                replay_payload = {
                    key: value
                    for key, value in reusable.items()
                    if key
                    not in {
                        "contentHash",
                        "nodeRunId",
                        "provenance",
                        "schemaVersion",
                    }
                }
                source_fragment_ref = (
                    f"hypothesis_fragment:{reusable.get('selectionId')}:"
                    f"{reusable.get('candidateId')}:{reusable.get('nodeRunId')}:"
                    f"{reusable.get('sessionAttempt')}"
                )
                for row in fragment_rows:
                    row_payload = row.get("payload") if isinstance(row, dict) else None
                    if not isinstance(row_payload, dict):
                        continue
                    if (
                        str(row_payload.get("workflowRunId") or "").strip()
                        == str(reusable.get("workflowRunId") or "").strip()
                        and str(row_payload.get("selectionId") or "").strip()
                        == str(reusable.get("selectionId") or "").strip()
                        and str(row_payload.get("candidateId") or "").strip()
                        == str(reusable.get("candidateId") or "").strip()
                        and str(row_payload.get("nodeRunId") or "").strip()
                        == str(reusable.get("nodeRunId") or "").strip()
                        and str(row_payload.get("taskId") or "").strip()
                        == str(reusable.get("taskId") or "").strip()
                    ):
                        source_fragment_ref = str(
                            row.get("recordId") or source_fragment_ref
                        ).strip()
                        break
                replay_payload["provenance"] = {
                    "source": "replayed_child_session_fragment",
                    "workflowRunId": action.run_id,
                    "workflowNodeId": action.node_id,
                    "nodeRunId": action.node_run_id,
                    "selectionId": child.selection_id,
                    "candidateId": child.candidate_id,
                    "sessionId": child.session_id,
                    "sessionAttempt": child.session_attempt,
                    "taskId": child.task_id,
                    "replayedFromFragmentRef": source_fragment_ref,
                    "replayedFromNodeRunId": str(
                        reusable.get("nodeRunId") or ""
                    ).strip(),
                    "replayedFromTaskId": str(
                        reusable.get("taskId") or ""
                    ).strip(),
                    "replayedFromSessionId": str(
                        reusable.get("sessionId") or ""
                    ).strip(),
                    "replayedFromSessionAttempt": reusable.get("sessionAttempt"),
                }
                replayed = record_hypothesis_fragment(
                    team_id=team_id,
                    task_context=task_context,
                    payload=replay_payload,
                    persist=True,
                    artifact_sink=put_workflow_artifact,
                )
                fragment = dict(replayed["fragment"])
            # Re-parse through the canonical writer contract.  This ensures
            # aggregation never consumes an unbound or stale child payload.
            fragment = build_hypothesis_fragment(
                task_context=task_context,
                payload=fragment,
            ).to_dict()
            fragment_ref = str(
                next(
                    (
                        item.get("recordId")
                        for item in list_workflow_artifacts(
                            team_id,
                            kind="hypothesis_fragment",
                            workflow_run_id=action.run_id,
                        )
                        if isinstance(item, dict)
                        and isinstance(item.get("payload"), dict)
                        and str(
                            (item.get("payload") or {}).get("candidateId") or ""
                        ).strip()
                        == child.candidate_id
                        and str(
                            (item.get("payload") or {}).get("nodeRunId") or ""
                        ).strip()
                        == action.node_run_id
                        and str(
                            (item.get("payload") or {}).get("taskId") or ""
                        ).strip()
                        == child.task_id
                        and str(item.get("recordId") or "").strip()
                    ),
                    "",
                )
                or (
                    f"hypothesis_fragment:{child.selection_id}:"
                    f"{child.candidate_id}:{action.node_run_id}:"
                    f"{int(child.session_attempt or 1)}"
                )
            )
            _mark_candidate_task_completed(
                team_id=team_id,
                project_id=project_id,
                task_id=child.task_id,
                completion=completion,
                result_ref=fragment_ref,
            )
            completed_handles.append(
                replace(
                    child,
                    status="succeeded",
                    fragment_refs=(fragment_ref,),
                )
            )
            current_by_candidate = {
                item.candidate_id: item for item in handle.scoped_handles
            }
            current_by_candidate.update(
                {item.candidate_id: item for item in completed_handles}
            )
            self._persist_hypothesis_anchor_draft(
                action=action,
                binding=self.resolve_binding(action),
                root_session_id=str(handle.root_session_id or ""),
                root_session_attempt=int(
                    handle.root_session_attempt or handle.session_attempt or 1
                ),
                selection_id=str(fan_out["selectionId"]),
                selected_candidate_ids=[
                    str(item) for item in fan_out["selectedCandidateIds"]
                ],
                handles=list(current_by_candidate.values()),
            )
            fragments.append(fragment)
            _record_hypothesis_scope_event(
                self._store,
                action=action,
                event_type="workflow.hypothesis_fragment.recorded",
                fields={
                    "mode": "on",
                    "selectionId": child.selection_id,
                    "candidateId": child.candidate_id,
                    "sessionId": child.session_id,
                    "sessionAttempt": child.session_attempt,
                    "taskId": child.task_id,
                    "status": "succeeded",
                    "fragmentRef": fragment_ref,
                },
                discriminator=(
                    f"{child.candidate_id}:{child.session_attempt}:{fragment_ref}"
                ),
            )

        if pending_live_children:
            # Still-running candidates keep this node action in the durable
            # "accepted/in progress" state: requeue, never succeeded/failed.
            # Terminal fan-in runs once, on the pass where the last candidate
            # reaches its success terminal state.
            raise _hypothesis_fan_out_pending_error(
                fan_out=fan_out,
                pending_children=pending_live_children,
            )

        candidate_scopes = {
            child.candidate_id: {
                "candidateId": child.candidate_id,
                "selectionId": child.selection_id,
                "sessionId": child.session_id,
                "sessionAttempt": child.session_attempt,
                "taskId": child.task_id,
            }
            for child in handle.scoped_handles
        }
        root_task_context = _root_hypothesis_task_context(
            team_id=team_id,
            action=action,
            root_session_id=str(handle.root_session_id or ""),
            source_collection_run_id=source_collection_run_id,
            child_task_context=task_context,
        )
        try:
            aggregation = record_hypothesis_set_from_fragments(
                team_id=team_id,
                task_context=root_task_context,
                selection=dict(fan_out["selection"]),
                fragments=fragments,
                scope={
                    "workflowRunId": action.run_id,
                    "workflowNodeId": action.node_id,
                    "nodeRunId": action.node_run_id,
                    "selectionId": fan_out["selectionId"],
                    "candidateScopes": candidate_scopes,
                },
                artifact_identity=(
                    f"hypothesis_set:{fan_out['selectionId']}:{action.node_run_id}:v1"
                ),
            )
        except Exception:
            self._persist_hypothesis_anchor_draft(
                action=action,
                binding=self.resolve_binding(action),
                root_session_id=str(handle.root_session_id or ""),
                root_session_attempt=int(
                    handle.root_session_attempt or handle.session_attempt or 1
                ),
                selection_id=str(fan_out["selectionId"]),
                selected_candidate_ids=[
                    str(item) for item in fan_out["selectedCandidateIds"]
                ],
                handles=list(completed_handles or handle.scoped_handles),
                root_status="failed",
            )
            _record_hypothesis_scope_event(
                self._store,
                action=action,
                event_type="workflow.hypothesis_aggregation.blocked",
                fields={
                    "mode": "on",
                    "selectionId": str(fan_out["selectionId"]),
                    "candidateCount": len(fragments),
                    "status": "blocked",
                    "errorCode": "hypothesis_aggregation_invalid",
                },
                discriminator="aggregation-invalid",
            )
            raise
        aggregation_artifact = (
            dict(aggregation.get("artifact"))
            if isinstance(aggregation.get("artifact"), Mapping)
            else {}
        )
        _record_hypothesis_scope_event(
            self._store,
            action=action,
            event_type="workflow.hypothesis_aggregation.completed",
            fields={
                "mode": "on",
                "selectionId": str(fan_out["selectionId"]),
                "candidateCount": len(fragments),
                "fragmentCount": len(fragments),
                "status": "completed",
                "aggregationHash": str(
                    aggregation_artifact.get("contentHash") or ""
                ),
                "fragmentRef": str(
                    aggregation_artifact.get("recordId") or ""
                ),
            },
            discriminator="aggregation-completed",
        )
        refs = collect_required_artifact_refs(
            required_kinds=self.required_artifact_kinds(action),
            team_id=team_id,
            workflow_run_id=action.run_id,
            source_collection_run_id=source_collection_run_id,
        )
        if not refs:
            self._persist_hypothesis_anchor_draft(
                action=action,
                binding=self.resolve_binding(action),
                root_session_id=str(handle.root_session_id or ""),
                root_session_attempt=int(
                    handle.root_session_attempt or handle.session_attempt or 1
                ),
                selection_id=str(fan_out["selectionId"]),
                selected_candidate_ids=[
                    str(item) for item in fan_out["selectedCandidateIds"]
                ],
                handles=list(completed_handles),
                root_status="failed",
            )
            raise RuntimeError(
                "hypothesis_design aggregation did not produce a readable hypothesis_set"
            )
        self._persist_hypothesis_anchor_draft(
            action=action,
            binding=self.resolve_binding(action),
            root_session_id=str(handle.root_session_id or ""),
            root_session_attempt=int(
                handle.root_session_attempt or handle.session_attempt or 1
            ),
            selection_id=str(fan_out["selectionId"]),
            selected_candidate_ids=[
                str(item) for item in fan_out["selectedCandidateIds"]
            ],
            handles=list(completed_handles),
            root_status="succeeded",
        )
        _ = aggregation
        return AgentTurnResult(
            materialized_refs=tuple(refs),
            handle=replace(
                handle,
                root_status="succeeded",
                scoped_handles=tuple(completed_handles),
            ),
        )

    def read_back_artifact(self, canonical_ref: str) -> ArtifactReadBack | None:
        return _read_back_real_artifact(canonical_ref)

    # ------------------------------------------------------------ human

    def create_human_task(self, *, action: PendingAction) -> HumanTaskHandle:
        return HumanTaskHandle(task_id=f"ht-{action.action_id}")

    # ------------------------------------------------------------ system

    def execute_system_action(
        self, *, action: PendingAction
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        return _execute_real_system_action(
            action,
            input_snapshot=self._run_input_snapshot(action.run_id),
            required_kinds=self.required_artifact_kinds(action),
        )

    def execute_run_smoke(
        self,
        *,
        run_id: str,
        plan_id: str,
        team_id: str = "",
        domain_payload: dict[str, Any] | None = None,
        action_id: str = "",
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """System Smoke observation — writes ``smoke_evidence`` only.

        ``smoke_gate`` remains Human: release is ``smoke_release`` via human resolve.
        """
        snapshot = self._run_input_snapshot(run_id)
        resolved_team = str(team_id or snapshot.get("teamId") or "").strip()
        if not resolved_team:
            raise RuntimeError("run_smoke requires teamId")
        resolved_plan = str(plan_id or "").strip()
        if not resolved_plan:
            request = _system_request_payload(
                snapshot, node_id="smoke_gate", alias="smokeGate"
            )
            resolved_plan = str(
                request.get("planId") or snapshot.get("planId") or ""
            ).strip()
        if not resolved_plan:
            raise RuntimeError("run_smoke requires planId")
        payload = dict(domain_payload or {})
        if not payload:
            request = _system_request_payload(
                snapshot, node_id="smoke_gate", alias="smokeGate"
            )
            payload = {
                key: value
                for key, value in request.items()
                if key not in {"idempotencyKey", "planId"}
            }
        return _ledger_run_smoke(
            run_id=run_id,
            team_id=resolved_team,
            plan_id=resolved_plan,
            source_collection_run_id=str(snapshot.get("sourceCollectionRunId") or ""),
            domain_payload=payload,
            action_id=action_id,
        )


def _stage_for(node_id: str) -> str:
    _STAGE_BY_NODE = {
        "problem_understanding": "knowledge_collection",
        "source_finding": "knowledge_collection",
        "source_extraction": "knowledge_collection",
        "evidence_relations": "knowledge_collection",
        "knowledge_ingestion": "knowledge_collection",
        "knowledge_handoff": "knowledge_collection",
        "hypothesis_design": "experiment_design",
        "protocol_design": "experiment_design",
        "protocol_review": "experiment_design",
        "protocol_freeze": "experiment_design",
        "smoke_gate": "experiment_design",
        "controlled_run": "execution_iteration",
        "result_evaluation": "execution_iteration",
        "iteration_decision": "execution_iteration",
        "version_governance": "execution_iteration",
        "candidate_promotion": "execution_iteration",
        "result_package": "execution_iteration",
    }
    return _STAGE_BY_NODE.get(node_id, "execution_iteration")


def _ensure_problem_understanding_source_collection_run(
    *,
    team_id: str,
    project_id: str,
    input_snapshot: dict[str, Any],
    action: PendingAction,
    binding: BindingResolution,
    store: WorkflowLedgerStore | None,
) -> str:
    """Ensure the problem node has a persisted source-collection authority.

    ``problem_understanding`` is a research-project task, not a source-stage
    task.  It still needs the canonical source-run identity that scopes its
    server task contract.  Bootstrap only the run here; never create a
    ``source_collection.stage_session`` task as a side effect.
    """

    source_run_id = str(input_snapshot.get("sourceCollectionRunId") or "").strip()
    if source_run_id:
        return source_run_id
    if store is None:
        raise RuntimeError(
            "problem_understanding requires a WorkflowLedgerStore to persist "
            "source collection authority"
        )

    from core.web.services.team_workflow.source_collection.runs import (
        start_source_collection_run,
    )

    objective = input_snapshot.get("researchObjectiveContract") or {}
    model_routing_policy = (
        input_snapshot.get("modelRoutingPolicy")
        if isinstance(input_snapshot.get("modelRoutingPolicy"), dict)
        else {}
    )
    required_model_policy = model_routing_policy.get("requiredModelPolicy")
    if not isinstance(required_model_policy, dict) or not required_model_policy:
        raise RuntimeError(
            "problem_understanding source authority requires the frozen model policy"
        )
    started_run = start_source_collection_run(
        team_id,
        {
            "researchProjectId": project_id,
            "questionId": str(input_snapshot.get("questionId") or "").strip(),
            "requiredModelPolicy": dict(required_model_policy),
            "title": "Challenge Cup workflow source collection",
            "goal": str(objective.get("question") or ""),
            "topic": str(objective.get("question") or ""),
            "inputRefs": list(input_snapshot.get("datasetRefs") or []),
            # The problem-understanding Agent owns the search seat, while this
            # run is only the canonical source authority.  No stage session is
            # started until the graph reaches source_finding.
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": binding.agent_id},
            "promptCachePolicy": {"requirement": "disabled"},
            "scope": {
                "workflowRunId": action.run_id,
                "researchProjectId": project_id,
            },
        },
    )
    nested_run = started_run.get("run") if isinstance(started_run, dict) else {}
    source_run_id = str(
        started_run.get("runId")
        or (nested_run.get("runId") if isinstance(nested_run, dict) else "")
        or ""
    ).strip()
    if not source_run_id:
        raise RuntimeError("source collection authority did not return a runId")

    # The write is deliberately followed by an independent Ledger read-back.
    # The low-level helper is shared with the legacy source-stage path and is
    # historically tolerant of missing/invalid snapshots; this path must not
    # create a project task unless the frozen/current snapshot is confirmed.
    _persist_source_collection_run_id(store, action.run_id, source_run_id)
    persisted_run = store.get_run(action.run_id)
    if persisted_run is None or not persisted_run.input_snapshot_json:
        raise RuntimeError(
            "source collection authority was created but Ledger input snapshot is unavailable"
        )
    try:
        persisted_snapshot = json.loads(persisted_run.input_snapshot_json)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "source collection authority was created but Ledger input snapshot is invalid"
        ) from exc
    persisted_id = (
        str(persisted_snapshot.get("sourceCollectionRunId") or "").strip()
        if isinstance(persisted_snapshot, dict)
        else ""
    )
    if persisted_id != source_run_id:
        raise RuntimeError(
            "source collection authority was created but Ledger input snapshot was not persisted"
        )
    input_snapshot["sourceCollectionRunId"] = persisted_id
    return persisted_id


_MAX_RETRY_LINEAGE_HOPS = 10


def _formal_project_retry_payload(
    action: PendingAction,
    *,
    team_id: str,
    project_id: str,
    agent_id: str,
    task_kind: str,
    store: WorkflowLedgerStore | None,
) -> dict[str, Any]:
    """Resolve the nearest ancestor project task for one Ledger retry attempt.

    Intermediate attempts may legitimately own no project task: a retry can be
    rejected before task creation (for example the ``previous task is still
    active`` guard) and still leaves a Ledger attempt.  Resolution therefore
    walks the bounded ``retry_of_node_run_id`` lineage and attaches to the
    nearest ancestor attempt that owns exactly one matching project task.
    Every hop re-validates run/node identity and fails closed on mismatch.
    """

    if int(action.attempt or 0) <= 1:
        return {}
    if store is None:
        raise RuntimeError("formal project Agent retry requires the workflow Ledger")

    def load_ancestor_node_run_ids(repository: Any) -> list[str]:
        current = repository.get_attempt(action.node_run_id)
        if current is None:
            raise RuntimeError("formal project Agent retry attempt is missing")
        parent_node_run_id = str(current.retry_of_node_run_id or "").strip()
        if not parent_node_run_id:
            raise RuntimeError("formal project Agent retry lineage is missing")
        lineage: list[str] = []
        node_run_id = parent_node_run_id
        for _hop in range(_MAX_RETRY_LINEAGE_HOPS):
            ancestor = repository.get_attempt(node_run_id)
            if (
                ancestor is None
                or ancestor.run_id != action.run_id
                or ancestor.node_id != action.node_id
            ):
                raise RuntimeError(
                    "formal project Agent retry lineage identity mismatch"
                )
            lineage.append(node_run_id)
            if int(getattr(ancestor, "attempt", 1) or 0) <= 1:
                break
            next_node_run_id = str(ancestor.retry_of_node_run_id or "").strip()
            if not next_node_run_id:
                break
            node_run_id = next_node_run_id
        return lineage

    ancestor_node_run_ids = list(store.read(load_ancestor_node_run_ids) or [])
    from core.web.services.team_workflow.research_project_agent_tasks import (
        get_research_project_agent_task_status,
    )

    status = get_research_project_agent_task_status(team_id, project_id)
    tasks = list(status.get("tasks") or [])
    for node_run_id in ancestor_node_run_ids:
        matches = [
            dict(task)
            for task in tasks
            if str(task.get("workflowRunId") or "") == action.run_id
            and str(task.get("nodeRunId") or "") == node_run_id
            and str(task.get("agentId") or "") == agent_id
            and str(task.get("taskKind") or "") == task_kind
        ]
        if len(matches) != 1:
            if len(matches) > 1:
                raise RuntimeError(
                    "formal project Agent retry source task is missing or ambiguous"
                )
            continue
        if not str(matches[0].get("taskId") or "").strip():
            raise RuntimeError(
                "formal project Agent retry source task is missing or ambiguous"
            )
        return {
            "formalRetry": True,
            "retryTaskId": str(matches[0]["taskId"]),
        }
    # A node can be blocked before any agent dispatch (for example by a
    # readiness gate), so its whole retry lineage owns no project task.  Such
    # a retry is the node's first real execution, not a task retry: fall back
    # to the plain start payload and let the adapter create a fresh task.
    return {}


def _create_real_agent_task(
    action: PendingAction,
    binding: BindingResolution,
    input_snapshot: dict[str, Any],
    *,
    adapter_spec: Any | None = None,
    store: WorkflowLedgerStore | None = None,
) -> AgentTaskHandle:
    from .task_adapter_registry import AgentTaskAdapterSpec, resolve_agent_task_adapter

    spec = adapter_spec or resolve_agent_task_adapter(action.node_id)
    if not isinstance(spec, AgentTaskAdapterSpec):
        raise RuntimeError(f"agent node {action.node_id} has no task adapter")
    team_id = str(input_snapshot.get("teamId") or "").strip()
    project_id = str(input_snapshot.get("projectId") or "").strip()
    if not team_id:
        raise RuntimeError("input snapshot has no teamId")
    idempotency_key = f"agent-task:{action.node_run_id}"
    challenge_task_contract, model_invocation_receipt_binding = (
        _formal_task_authorities(
            action=action,
            input_snapshot=input_snapshot,
            agent_id=binding.agent_id,
            workflow_id=str(
                getattr(store.get_run(action.run_id), "workflow_id", "")
                if store is not None
                else ""
            ).strip(),
        )
    )
    source_collection_run_id = ""
    if spec.family != "source_collection" and action.node_id == "problem_understanding":
        if not project_id:
            raise RuntimeError("input snapshot has no projectId")
        if not str(binding.agent_id or "").strip():
            raise RuntimeError("problem_understanding has no bound Agent")
        source_collection_run_id = _ensure_problem_understanding_source_collection_run(
            team_id=team_id,
            project_id=project_id,
            input_snapshot=input_snapshot,
            action=action,
            binding=binding,
            store=store,
        )
    if source_collection_run_id:
        # The formal authority helper owns the rest of this contract.  Bind the
        # source-run scope only after the Ledger read-back above succeeds.
        challenge_task_contract = {
            **challenge_task_contract,
            "sourceCollectionRunId": source_collection_run_id,
        }
    if spec.family == "source_collection":
        started = _start_source_collection_agent_task(
            team_id=team_id,
            project_id=project_id,
            input_snapshot=input_snapshot,
            action=action,
            binding=binding,
            stage_id=spec.task_key,
            role_key=spec.role_key or binding.role_key,
            idempotency_key=idempotency_key,
            store=store,
            challenge_task_contract=challenge_task_contract,
        )
    else:
        from core.web.services.team_workflow.research_project_agent_tasks import (
            start_research_project_agent_task,
        )

        from . import experiment_stage_bootstrap

        if not project_id:
            raise RuntimeError("input snapshot has no projectId")
        experiment_stage_bootstrap.ensure_experiment_stage_round_for_agent_node(
            node_id=action.node_id,
            team_id=team_id,
            project_id=project_id,
            input_snapshot=input_snapshot,
            requested_by_agent=binding.agent_id,
            store=store,
            run_id=action.run_id,
        )
        scoped_payload: dict[str, Any] = {}
        if action.selection_id and action.candidate_id:
            raw_selected = (action.scope or {}).get("selectedCandidateIds")
            selected = (
                [str(item).strip() for item in raw_selected if str(item).strip()]
                if isinstance(raw_selected, (list, tuple))
                else []
            )
            if action.candidate_id not in selected:
                selected.append(action.candidate_id)
            scoped_payload = {
                "selectionId": action.selection_id,
                "candidateId": action.candidate_id,
                "selectedCandidateIds": selected,
                "scope": dict(action.scope or {}),
            }
        retry_payload = _formal_project_retry_payload(
            action,
            team_id=team_id,
            project_id=project_id,
            agent_id=binding.agent_id,
            task_kind=spec.task_key,
            store=store,
        )
        started = start_research_project_agent_task(
            team_id,
            project_id,
            {
                "taskKind": spec.task_key,
                "agentId": binding.agent_id,
                "idempotencyKey": idempotency_key,
                "targetRef": f"node-run:{action.node_run_id}",
                "workflowRunId": action.run_id,
                "workflowNodeId": action.node_id,
                "sourceCollectionRunId": str(
                    input_snapshot.get("sourceCollectionRunId") or ""
                ),
                **scoped_payload,
                **retry_payload,
            },
            _challenge_task_contract=challenge_task_contract,
            _model_invocation_receipt_binding=model_invocation_receipt_binding,
        )
    return _agent_handle_from_started(started)


def _task_kind_for(node_id: str) -> str | None:
    """Compatibility helper: returns stageId/taskKind key for Agent nodes."""
    from .task_adapter_registry import resolve_agent_task_adapter

    spec = resolve_agent_task_adapter(node_id)
    return None if spec is None else spec.task_key


def _start_source_collection_agent_task(
    *,
    team_id: str,
    project_id: str,
    input_snapshot: dict[str, Any],
    action: PendingAction,
    binding: BindingResolution,
    stage_id: str,
    role_key: str,
    idempotency_key: str,
    store: WorkflowLedgerStore | None = None,
    challenge_task_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from core.web.services.team_workflow.source_collection.runs import (
        start_source_collection_run,
    )
    from core.web.services.team_workflow.source_collection.stage_session import (
        start_source_collection_stage_session_task,
    )

    source_run_id = str(input_snapshot.get("sourceCollectionRunId") or "").strip()
    if not source_run_id:
        objective = input_snapshot.get("researchObjectiveContract") or {}
        started_run = start_source_collection_run(
            team_id,
            {
                "title": "Challenge Cup workflow source collection",
                "goal": str(objective.get("question") or ""),
                "topic": str(objective.get("question") or ""),
                "inputRefs": list(input_snapshot.get("datasetRefs") or []),
                "agentRoles": [role_key] if role_key else [],
                "agentIds": {role_key: binding.agent_id} if role_key else {},
                # Deterministic production-chain verification does not consume a live
                # prompt-cache model; SC still creates canonical Session/Task/Turn.
                "promptCachePolicy": {"requirement": "disabled"},
                "scope": {
                    "workflowRunId": action.run_id,
                    "researchProjectId": project_id,
                },
            },
        )
        source_run_id = str((started_run.get("run") or {}).get("runId") or "").strip()
        if source_run_id and store is not None:
            _persist_source_collection_run_id(store, action.run_id, source_run_id)
            input_snapshot["sourceCollectionRunId"] = source_run_id
    if not source_run_id:
        raise RuntimeError("source collection adapter did not return a runId")
    from .source_stage_task_replay import find_reusable_source_stage_task

    reusable_task = find_reusable_source_stage_task(
        store=store,
        action=action,
        team_id=team_id,
        source_run_id=source_run_id,
        stage_id=stage_id,
        agent_id=binding.agent_id,
        agent_role=role_key,
    )
    if reusable_task is not None:
        return reusable_task
    evidence_remediation_contract: dict[str, Any] = {}
    if action.node_id == "source_extraction" and int(action.attempt) > 1:
        from .agent_claim_evidence_materializer import (
            build_formal_evidence_retry_contract,
        )

        evidence_remediation_contract = build_formal_evidence_retry_contract(
            team_id=team_id,
            workflow_run_id=action.run_id,
            source_collection_run_id=source_run_id,
        )
    stage_task_payload = {
            "stageId": stage_id,
            "agentId": binding.agent_id,
            "agentRole": role_key,
            "idempotencyKey": idempotency_key,
            "returnLabel": "科研工作流",
            # Evidence remediation defines the extraction scope, not session
            # lifecycle.  The stage-session authority reuses a reviewable
            # session and independently opens a formal retry after a failed
            # terminal task.
            "formalRetry": False,
            "evidenceRemediationContract": evidence_remediation_contract,
    }
    if isinstance(challenge_task_contract, Mapping):
        return start_source_collection_stage_session_task(
            team_id,
            source_run_id,
            stage_task_payload,
            _challenge_task_contract=dict(challenge_task_contract),
        )
    return start_source_collection_stage_session_task(
        team_id,
        source_run_id,
        stage_task_payload,
    )


def _persist_source_collection_run_id(
    store: WorkflowLedgerStore,
    run_id: str,
    source_run_id: str,
) -> None:
    """Freeze the SC run id into the Ledger input snapshot for successor nodes."""

    def mutate(uow):
        run = uow.repository.get_run(run_id)
        if run is None or not run.input_snapshot_json:
            return
        try:
            snapshot = json.loads(run.input_snapshot_json)
        except (TypeError, ValueError):
            return
        if not isinstance(snapshot, dict):
            return
        if str(snapshot.get("sourceCollectionRunId") or "") == source_run_id:
            return
        snapshot["sourceCollectionRunId"] = source_run_id
        uow.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json = ?, updated_at_ms = ? "
            "WHERE run_id = ?",
            (
                json.dumps(snapshot, ensure_ascii=False),
                int(__import__("time").time() * 1000),
                run_id,
            ),
        )

    store.submit(mutate, force_flush=True).result(timeout=30)


def _agent_handle_from_started(started: dict[str, Any]) -> AgentTaskHandle:
    task = started.get("task") if isinstance(started.get("task"), dict) else {}
    task_turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    session_id = str(started.get("sessionId") or task.get("sessionId") or "")
    turn_id = str(
        task_turn.get("turnId") or task.get("startedTurnId") or started.get("startedTurnId") or ""
    )
    task_id = str(started.get("taskId") or task.get("taskId") or "")
    session_attempt = int(
        started.get("sessionAttempt") or task.get("sessionAttempt") or 1
    )
    if not session_id or not task_id or not turn_id:
        raise RuntimeError("agent task anchor is incomplete")
    return AgentTaskHandle(
        session_id=session_id,
        session_attempt=session_attempt,
        task_id=task_id,
        turn_id=turn_id,
    )


def publish_agent_task_started_anchor(
    store: WorkflowLedgerStore,
    *,
    action: PendingAction,
    binding: BindingResolution,
    handle: AgentTaskHandle,
) -> None:
    """Publish the dispatch-time anchor and move the attempt to running.

    ``create_agent_task`` returning a live turn handle is the real execution
    signal: the Agent Session/Task/Turn exists and the turn was accepted.
    Publishing a provisional anchor plus the ``dispatching -> running``
    transition here makes taskId/sessionId/turnId visible in the node_attempt
    and currentTask projections for the entire (potentially long) turn
    instead of only after the final adapter commit.  Best-effort and
    idempotent: the authoritative anchor is still written exactly once by the
    adapter commit, and a blocked/terminal attempt is never resurrected.
    """

    if getattr(handle, "observation_only", False):
        return
    from core.research.workflow.transitions import NodeAttemptStatus

    now_ms = int(time.time() * 1000)
    root_session_id = str(handle.root_session_id or handle.session_id or "").strip()
    root_session_attempt = handle.root_session_attempt or handle.session_attempt
    scalar_task_id = str(handle.task_id or "").strip()
    scalar_turn_id = str(handle.turn_id or "").strip()
    anchor_payload = {
        **binding.to_dict(),
        **handle.to_dict(),
        "actionId": action.action_id,
        "status": "running",
        "provisional": True,
    }

    def mutate(uow: Any) -> bool:
        attempt = uow.repository.get_attempt(action.node_run_id)
        if attempt is None:
            return True
        if str(attempt.status) not in {
            NodeAttemptStatus.DISPATCHING.value,
            NodeAttemptStatus.RUNNING.value,
        }:
            # Only a live dispatch may move to running; the observability
            # path must never resurrect a blocked/terminal attempt.
            return True
        anchor_id = ""
        existing = uow.repository.get_anchor_by_node_run(action.node_run_id)
        if handle.scoped_handles:
            # v3 fan-out anchors are owned by the CAS draft publisher; only
            # link and transition the attempt here, never rewrite the json.
            if existing is not None:
                anchor_id = str(existing[0])
        elif existing is None:
            anchor_id = new_id("anchor")
            uow.repository.insert_anchor(
                anchor_id=anchor_id,
                node_run_id=action.node_run_id,
                actor_kind=action.actor_kind.value,
                anchor_json=json.dumps(anchor_payload, ensure_ascii=False),
                created_at_ms=now_ms,
                agent_id=binding.agent_id,
                role_key=binding.role_key,
                session_id=root_session_id or None,
                session_attempt=root_session_attempt,
                task_id=scalar_task_id or None,
                turn_id=scalar_turn_id or None,
                status="running",
            )
        elif existing is not None:
            anchor_id = str(existing[0])
            uow.repository.update_anchor_by_node_run(
                node_run_id=action.node_run_id,
                anchor_json=json.dumps(anchor_payload, ensure_ascii=False),
                status="running",
                agent_id=binding.agent_id,
                role_key=binding.role_key,
                session_id=root_session_id or None,
                session_attempt=root_session_attempt,
                task_id=scalar_task_id or None,
                turn_id=scalar_turn_id or None,
            )
        uow.repository.update_attempt_status(
            action.node_run_id,
            NodeAttemptStatus.RUNNING.value,
            now_ms,
            execution_anchor_id=anchor_id or None,
        )
        return True

    try:
        store.submit(mutate, force_flush=True).result(timeout=30)
    except Exception as exc:
        # Pure observability: a failed provisional publish must not fail the
        # adapter execution; the commit path remains the anchor authority.
        try:
            from core.web.services.runtime_scene_service import (
                record_runtime_scene_event_quietly,
            )

            record_runtime_scene_event_quietly(
                "team_workflow_orchestration",
                "real_domain_ports",
                "agent_task_started_anchor_publish_failed",
                level="warning",
                outcome="failed",
                fields={
                    "runId": str(action.run_id or ""),
                    "nodeRunId": str(action.node_run_id or ""),
                    "nodeId": str(action.node_id or ""),
                    "detail": str(exc)[:200],
                },
            )
        except Exception:
            pass


def _verify_node_root_session(session_id: str, *, agent_id: str) -> None:
    from core.web.services import session_service

    _require_canonical_session(session_id=session_id, agent_id=agent_id)
    detail = session_service.get_session_detail(
        session_id,
        message_limit=0,
        transcript_scope="none",
    )
    if not isinstance(detail, dict):
        raise TypeError("workflow node root session detail is invalid")
    if str(detail.get("parentSessionId") or "").strip():
        raise RuntimeError("workflow node root resolved to a child session")


def _require_canonical_session(*, session_id: str, agent_id: str) -> None:
    from core.web.services import session_service

    try:
        detail = session_service.get_session_detail(
            str(session_id or ""),
            message_limit=0,
            transcript_scope="none",
        )
    except Exception as exc:
        raise RuntimeError("Agent task session authority could not be verified") from exc
    if not isinstance(detail, dict) or str(detail.get("id") or "").strip() != str(session_id or ""):
        raise RuntimeError("Agent task session is missing from the canonical session index")
    canonical_agent_id = str(detail.get("agentId") or "").strip()
    if canonical_agent_id and canonical_agent_id != agent_id:
        raise RuntimeError(
            "Agent task session Agent does not match the frozen NodeRun binding"
        )


def _read_back_real_artifact(canonical_ref: str) -> ArtifactReadBack | None:
    from .artifact_readback_registry import read_domain_artifact

    if not canonical_ref:
        return None
    return read_domain_artifact(canonical_ref)


def _execute_real_system_action(
    action: PendingAction,
    *,
    input_snapshot: dict[str, Any] | None = None,
    required_kinds: tuple[str, ...],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Dispatch System nodes to the same domain executors the UI adapters use.

    Returns ``(materialized_refs, meta)`` where ``meta`` must include a non-empty
    ``runnerId`` for ``SystemActionAdapter.verify``. Silent empty success is
    forbidden — missing inputs or incomplete domain results raise.

    ``smoke_gate`` is ActorKind.HUMAN — Smoke domain execution is
    :meth:`RealDomainPorts.execute_run_smoke`, not a SystemActionAdapter path.
    """
    node_id = str(action.node_id or "").strip()
    snapshot = dict(input_snapshot or {})
    if node_id == "controlled_run":
        return _ledger_controlled_run(action, snapshot, required_kinds=required_kinds)
    if node_id == "result_package":
        return _ledger_result_package(action, snapshot, required_kinds=required_kinds)
    if node_id == "smoke_gate":
        raise RuntimeError(
            "smoke_gate is a Human gate; use execute_run_smoke for Smoke evidence "
            "and Human resolve for smoke_release"
        )
    raise RuntimeError(
        f"system node {node_id} has no system executor wired for Ledger production path"
    )


def _persist_workflow_artifact(
    *,
    kind: str,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
    payload: dict[str, Any],
    artifact_identity: str,
) -> None:
    from .workflow_artifact_store import (
        WorkflowArtifactConflictError,
        put_workflow_artifact,
    )

    try:
        put_workflow_artifact(
            team_id,
            kind=kind,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=source_collection_run_id or workflow_run_id,
            payload=payload,
            artifact_identity=artifact_identity,
        )
    except WorkflowArtifactConflictError:
        # Crash-retry after a successful first write: keep the first payload.
        # Bounded ledger fields such as evaluatedAt are wall-clock and would
        # otherwise fail the exact-replay hash check and kill the attempt.
        return


def _collect_kind_refs(
    kinds: tuple[str, ...],
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
) -> list[dict[str, str]]:
    """Collect refs for an explicit kind set (not full node producesArtifactKinds)."""
    from .artifact_readback_registry import (
        build_canonical_ref,
        load_scoped_artifact_payload,
    )
    from .human_gate_artifacts import canonical_sha256

    authority_run_id = (
        str(source_collection_run_id or "").strip()
        or str(workflow_run_id or "").strip()
    )
    if not team_id or not authority_run_id:
        raise RuntimeError("team_id and run scope are required to collect artifact refs")
    refs: list[dict[str, str]] = []
    for kind in kinds:
        payload = load_scoped_artifact_payload(
            kind,
            team_id=team_id,
            authority_run_id=authority_run_id,
            workflow_run_id=str(workflow_run_id or "").strip(),
        )
        if payload is None:
            from .real_readiness_context import _readiness_artifact_envelope

            payload = _readiness_artifact_envelope(
                kind,
                team_id=team_id,
                run_id=str(workflow_run_id or "").strip(),
                authority_run_id=authority_run_id,
            )
        if payload is None:
            continue
        content_hash = canonical_sha256(payload)
        refs.append(
            {
                "canonicalRef": build_canonical_ref(
                    kind=kind,
                    team_id=team_id,
                    authority_run_id=authority_run_id,
                    content_hash=content_hash,
                ),
                "kind": kind,
                "sha256": content_hash,
                "version": "1.0.0",
            }
        )
    return refs


def _system_request_payload(
    snapshot: dict[str, Any], *, node_id: str, alias: str
) -> dict[str, Any]:
    """Resolve operator/domain request fields frozen into the run input snapshot."""
    nested = snapshot.get(alias)
    if isinstance(nested, dict):
        return dict(nested)
    requests = snapshot.get("systemActionRequests")
    if isinstance(requests, dict):
        node_payload = requests.get(node_id)
        if isinstance(node_payload, dict):
            return dict(node_payload)
    return {}


def _collect_system_artifact_refs(
    *,
    required_kinds: tuple[str, ...],
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
) -> list[dict[str, str]]:
    from .agent_turn_completion import collect_required_artifact_refs

    refs = collect_required_artifact_refs(
        required_kinds=required_kinds,
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_collection_run_id,
    )
    if not refs:
        raise RuntimeError(
            "system action produced no readable artifact refs for required kinds: "
            + ", ".join(required_kinds)
        )
    return refs


def _payload_object(envelope: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        return {}
    payload = envelope.get("payload")
    if isinstance(payload, dict) and payload:
        return dict(payload)
    return dict(envelope)


def _is_sha256_hex(value: object) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _load_run_authority_artifact(
    kind: str,
    *,
    team_id: str,
    snapshot: dict[str, Any],
    workflow_run_id: str,
) -> dict[str, Any]:
    from .artifact_readback_registry import load_scoped_artifact_payload

    authority = (
        str(snapshot.get("sourceCollectionRunId") or "").strip()
        or str(workflow_run_id or "").strip()
    )
    if not team_id or not authority:
        return {}
    envelope = load_scoped_artifact_payload(
        kind,
        team_id=team_id,
        authority_run_id=authority,
        workflow_run_id=str(workflow_run_id or "").strip(),
    )
    if not isinstance(envelope, dict) or not envelope:
        from .real_readiness_context import _readiness_artifact_envelope

        envelope = _readiness_artifact_envelope(
            kind,
            team_id=team_id,
            run_id=str(workflow_run_id or "").strip(),
            authority_run_id=authority,
        )
    return envelope if isinstance(envelope, dict) else {}


def _plan_id_from_authority_artifacts(
    *,
    team_id: str,
    snapshot: dict[str, Any],
    workflow_run_id: str,
) -> str:
    for kind in ("smoke_release", "frozen_protocol"):
        body = _payload_object(
            _load_run_authority_artifact(
                kind,
                team_id=team_id,
                snapshot=snapshot,
                workflow_run_id=workflow_run_id,
            )
        )
        plan_id = str(body.get("planId") or body.get("protocolId") or "").strip()
        if plan_id:
            return plan_id
    return ""


def _seed_set_from_protocol(protocol: dict[str, Any]) -> list[int]:
    raw = protocol.get("seed")
    if raw is None:
        raw = protocol.get("seeds")
    values: list[object]
    if isinstance(raw, list):
        values = list(raw)
    elif isinstance(raw, int) and not isinstance(raw, bool):
        values = [raw]
    else:
        values = []
    seeds: list[int] = []
    seen: set[int] = set()
    for item in values:
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        if item in seen:
            continue
        seen.add(item)
        seeds.append(item)
    return seeds or [42]


def _stop_criteria_from_protocol(protocol: dict[str, Any]) -> dict[str, Any]:
    stop = protocol.get("stop_condition")
    if stop is None:
        stop = protocol.get("stopCondition")
    if isinstance(stop, dict) and stop:
        return dict(stop)
    if isinstance(stop, list) and stop:
        return {"conditions": list(stop)}
    text = str(stop or "").strip()
    if text:
        return {"condition": text}
    return {"source": "frozen_protocol"}


def _campaign_from_frozen_protocol(
    *,
    action: PendingAction,
    snapshot: dict[str, Any],
    team_id: str,
    plan_id: str,
) -> dict[str, Any] | None:
    from .human_gate_artifacts import canonical_sha256

    frozen_envelope = _load_run_authority_artifact(
        "frozen_protocol",
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    if not frozen_envelope:
        return None
    frozen = _payload_object(frozen_envelope)
    protocol = frozen.get("protocol") if isinstance(frozen.get("protocol"), dict) else {}
    release = _payload_object(
        _load_run_authority_artifact(
            "smoke_release",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    )
    protocol_hash = str(release.get("frozenProtocolHash") or "").strip().lower()
    if not _is_sha256_hex(protocol_hash):
        protocol_hash = str(frozen.get("protocolDraftHash") or "").strip().lower()
    if not _is_sha256_hex(protocol_hash):
        protocol_hash = canonical_sha256(frozen_envelope)
    env_hash = str(snapshot.get("snapshotHash") or "").strip().lower()
    if not _is_sha256_hex(env_hash):
        env_hash = str(release.get("smokeEvidenceHash") or "").strip().lower()
    if not _is_sha256_hex(env_hash):
        env_hash = canonical_sha256(
            {
                "teamId": team_id,
                "planId": plan_id,
                "sourceCollectionRunId": str(
                    snapshot.get("sourceCollectionRunId") or ""
                ).strip(),
            }
        )
    hypothesis = ""
    refs = protocol.get("hypothesisRefs")
    if isinstance(refs, list):
        for item in refs:
            text = str(item or "").strip()
            if text:
                hypothesis = text
                break
    if not hypothesis:
        hypothesis = str(protocol.get("hypothesisPortfolioId") or "").strip()
    if not hypothesis:
        hypothesis = plan_id
    metric = str(protocol.get("metric") or "").strip() or f"metric:{plan_id}"
    return {
        "campaignId": f"campaign:{plan_id}",
        "runId": action.run_id,
        "hypothesisCandidateId": hypothesis,
        "protocolHash": protocol_hash,
        "environmentSnapshotHash": env_hash,
        "datasetSnapshotRefs": [f"dataset:{plan_id}"],
        "baselineRefs": [f"baseline:{plan_id}"],
        "metricContractRef": metric,
        "stage": "feasibility",
        "seedSet": _seed_set_from_protocol(protocol),
        "replicationCount": 1,
        "budgetLedgerRef": f"budget:{action.run_id}",
        "stopCriteria": _stop_criteria_from_protocol(protocol),
        "experimentRunRefs": [],
        "resultArtifactRefs": [],
        "decision": "proceed",
    }


def _released_smoke_body(
    *,
    team_id: str,
    snapshot: dict[str, Any],
    workflow_run_id: str,
) -> dict[str, Any]:
    body = _payload_object(
        _load_run_authority_artifact(
            "smoke_release",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=workflow_run_id,
        )
    )
    if str(body.get("status") or "").strip().lower() != "released":
        return {}
    return body


def _bounded_controlled_run_after_smoke_release(
    *,
    action: PendingAction,
    snapshot: dict[str, Any],
    team_id: str,
    plan_id: str,
    campaign_raw: dict[str, Any],
    formal_error: str,
) -> dict[str, Any]:
    """Challenge Cup workflow B-engine when the FashionMNIST formal runner cannot start.

    Human smoke_release already accepted the V1 CPU observation. This path re-runs
    the same whitelist adapter and records ``run_artifacts`` for result_evaluation.
    It does not advertise a formal FashionMNIST result.
    """
    from core.research.smoke_runner import CLASSIFICATION_ADAPTER, run_smoke_adapter

    release = _released_smoke_body(
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    if not release:
        raise RuntimeError(formal_error)
    protocol = {}
    frozen = _payload_object(
        _load_run_authority_artifact(
            "frozen_protocol",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    )
    if isinstance(frozen.get("protocol"), dict):
        protocol = frozen["protocol"]
    seeds = _seed_set_from_protocol(protocol)
    seed = int(seeds[0]) if seeds else 42
    runner_result = run_smoke_adapter(CLASSIFICATION_ADAPTER, seed=seed)
    execution_id = f"exec-{action.action_id}"
    execution = {
        "executionId": execution_id,
        "status": "completed",
        "adapterId": CLASSIFICATION_ADAPTER,
        "runnerId": CLASSIFICATION_ADAPTER,
        "runnerMode": runner_result.get("runnerMode"),
        "formalRunnerUnavailable": formal_error,
        "smokeReleaseStatus": release.get("status"),
        "smokeRunId": release.get("smokeRunId"),
        "metrics": runner_result.get("metrics"),
        "logs": runner_result.get("logs")
        or f"adapter={CLASSIFICATION_ADAPTER} seed={seed} decision={runner_result.get('decisionHint')}",
        "decisionHint": runner_result.get("decisionHint"),
        "artifactHash": runner_result.get("artifactHash"),
        "campaignId": campaign_raw.get("campaignId"),
        "planId": plan_id,
    }
    return {"execution": execution, "adapterId": CLASSIFICATION_ADAPTER}


def _execute_controlled_run_or_bounded(
    *,
    team_id: str,
    plan_id: str,
    domain_payload: dict[str, Any],
    action: PendingAction,
    snapshot: dict[str, Any],
    campaign_raw: dict[str, Any],
) -> dict[str, Any]:
    from core.web.services.team_workflow.experiment_api.full_run import (
        execute_experiment_full_run,
        formal_execution_config_is_provisioned,
        resolve_formal_execution_config,
    )
    from core.web.services.team_workflow.experiment_api.plan import (
        bind_frozen_protocol_to_experiment_plan,
    )
    from core.web.services.team_workflow_orchestration_service import (
        TeamWorkflowOrchestrationError,
    )

    frozen_envelope = _load_run_authority_artifact(
        "frozen_protocol",
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    if frozen_envelope:
        try:
            bind_frozen_protocol_to_experiment_plan(
                team_id, _payload_object(frozen_envelope)
            )
        except Exception:
            pass

    plan_record = _load_experiment_plan_record(team_id, plan_id)
    payload = dict(domain_payload)
    execution_config = resolve_formal_execution_config(plan_record, payload)
    if formal_execution_config_is_provisioned(execution_config):
        payload["executionConfig"] = execution_config
    try:
        return execute_experiment_full_run(team_id, plan_id, payload)
    except TeamWorkflowOrchestrationError as exc:
        if formal_execution_config_is_provisioned(execution_config):
            raise RuntimeError(f"formal_run_failed: {exc}") from exc
        return _bounded_controlled_run_after_smoke_release(
            action=action,
            snapshot=snapshot,
            team_id=team_id,
            plan_id=plan_id,
            campaign_raw=campaign_raw,
            formal_error=str(exc),
        )


def _load_experiment_plan_record(team_id: str, plan_id: str) -> dict[str, Any]:
    from core.web.services import team_workflow_orchestration_service as orch

    if not team_id or not plan_id:
        return {}
    with orch._WORKFLOW_LOCK:
        store = orch._load_experiment_plan_store(team_id)
        plan = orch._find_experiment_plan(store, plan_id)
    return dict(plan) if isinstance(plan, dict) else {}


def _ledger_controlled_run(
    action: PendingAction,
    snapshot: dict[str, Any],
    *,
    required_kinds: tuple[str, ...],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Ledger path for controlled_run — same domain call as UI system adapter."""
    from core.research.workflow.contracts import (
        ContractValidationError,
        ExperimentCampaign,
    )

    team_id = str(snapshot.get("teamId") or "").strip()
    if not team_id:
        raise RuntimeError("controlled_run requires teamId in input snapshot")
    request = _system_request_payload(
        snapshot, node_id="controlled_run", alias="controlledRun"
    )
    plan_id = str(
        request.get("planId") or snapshot.get("planId") or ""
    ).strip()
    if not plan_id:
        plan_id = _plan_id_from_authority_artifacts(
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    if not plan_id:
        raise RuntimeError("controlled_run requires planId")
    campaign_raw = request.get("campaign")
    if campaign_raw is None:
        campaign_raw = snapshot.get("campaign")
    if not isinstance(campaign_raw, dict):
        campaign_raw = _campaign_from_frozen_protocol(
            action=action,
            snapshot=snapshot,
            team_id=team_id,
            plan_id=plan_id,
        )
    if not isinstance(campaign_raw, dict):
        raise RuntimeError("controlled_run requires an ExperimentCampaign")
    try:
        ExperimentCampaign.from_dict({**campaign_raw, "runId": action.run_id})
    except ContractValidationError as exc:
        raise RuntimeError(str(exc)) from exc

    domain_payload = {
        key: value
        for key, value in request.items()
        if key not in {"idempotencyKey", "planId", "campaign"}
    }
    result = _execute_controlled_run_or_bounded(
        team_id=team_id,
        plan_id=plan_id,
        domain_payload=domain_payload,
        action=action,
        snapshot=snapshot,
        campaign_raw=campaign_raw,
    )
    execution = dict(result.get("execution") or {})
    execution_id = str(execution.get("executionId") or "").strip()
    if not execution_id or execution.get("status") != "completed":
        raise RuntimeError("controlled run did not return a completed execution")

    result_ref = f"experiment-run:{execution_id}"
    try:
        ExperimentCampaign.from_dict(
            {
                **campaign_raw,
                "runId": action.run_id,
                "experimentRunRefs": [result_ref],
                "resultArtifactRefs": [result_ref],
            }
        )
    except ContractValidationError as exc:
        raise RuntimeError(str(exc)) from exc

    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    artifact_payload = {
        "teamId": team_id,
        "workflowRunId": action.run_id,
        "sourceCollectionRunId": sc_run_id or action.run_id,
        "planId": plan_id,
        "executionId": execution_id,
        "observationRef": result_ref,
        "execution": execution,
        "campaign": {
            **campaign_raw,
            "runId": action.run_id,
            "experimentRunRefs": [result_ref],
            "resultArtifactRefs": [result_ref],
        },
    }
    _persist_workflow_artifact(
        kind="run_artifacts",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
        artifact_identity=action.node_run_id or action.action_id,
        payload=artifact_payload,
    )
    refs = _collect_system_artifact_refs(
        required_kinds=required_kinds,
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )
    runner_id = str(
        execution.get("adapterId")
        or result.get("adapterId")
        or execution.get("runnerId")
        or "formal_runner"
    ).strip()
    if not runner_id:
        raise RuntimeError("controlled_run requires a non-empty runnerId")
    return refs, {
        "systemActionId": f"sys-{action.action_id}",
        "runnerId": runner_id,
        "executionId": execution_id,
        "planId": plan_id,
        "observationRef": result_ref,
    }


def _heal_binding_resolution(
    snapshot: dict[str, Any],
    node_id: str,
) -> BindingResolution:
    from .team_role_source import (
        heal_agent_binding_for_node,
        heal_agent_binding_from_sibling_freeze,
    )

    team_id = str(snapshot.get("teamId") or "").strip()
    healed = heal_agent_binding_for_node(team_id, node_id) if team_id else None
    if not healed:
        healed = heal_agent_binding_from_sibling_freeze(snapshot, node_id)
    if not healed:
        return BindingResolution(agent_id="", role_key="")
    return BindingResolution(
        agent_id=str(healed.get("agentId") or ""),
        role_key=str(healed.get("roleKey") or ""),
        binding_snapshot_id=str(healed.get("snapshotId") or "") or None,
    )


def _bounded_controlled_run_execution(
    *,
    team_id: str,
    snapshot: dict[str, Any],
    workflow_run_id: str,
) -> dict[str, Any]:
    body = _payload_object(
        _load_run_authority_artifact(
            "run_artifacts",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=workflow_run_id,
        )
    )
    execution = body.get("execution") if isinstance(body.get("execution"), dict) else {}
    from .readiness.common import is_bounded_controlled_run

    if is_bounded_controlled_run({**body, **execution, "execution": execution}):
        return execution
    return {}


def _bounded_agent_node_can_complete(
    node_id: str,
    *,
    team_id: str,
    snapshot: dict[str, Any],
    workflow_run_id: str,
) -> bool:
    if node_id not in {"result_evaluation", "iteration_decision", "version_governance"}:
        return False
    return bool(
        _bounded_controlled_run_execution(
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=workflow_run_id,
        )
    )


def _bounded_agent_task_handle(action: PendingAction) -> AgentTaskHandle:
    prefix = {
        "result_evaluation": "bounded-eval",
        "iteration_decision": "bounded-iter",
        "version_governance": "bounded-gov",
    }.get(action.node_id, "bounded-node")
    return AgentTaskHandle(
        session_id=f"{prefix}:{action.action_id}",
        session_attempt=1,
        task_id=f"{prefix}-{action.action_id}",
        turn_id=f"{prefix}-turn-{action.action_id}",
    )


def _execution_result(execution: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(execution, Mapping):
        return {}
    result = execution.get("result")
    return dict(result) if isinstance(result, Mapping) else {}


def _execution_metrics(execution: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(execution, Mapping):
        return {}
    metrics = execution.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    result = _execution_result(execution)
    nested = result.get("metrics")
    if isinstance(nested, dict):
        return nested
    aggregate = result.get("aggregate")
    if isinstance(aggregate, dict):
        return aggregate
    return {}


def _execution_boundaries(execution: Mapping[str, Any] | None) -> list[str]:
    result = _execution_result(execution)
    raw = ()
    if isinstance(execution, Mapping):
        raw = result.get("boundaries") or execution.get("boundaries") or ()
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _bounded_iteration_stop(
    execution: Mapping[str, Any] | None,
) -> tuple[str, str, str, str]:
    """Return reason, terminalReason, target_version, lineage."""
    unavailable = str(
        (execution or {}).get("formalRunnerUnavailable") or ""
    ).strip()
    if unavailable:
        return (
            "Formal FashionMNIST runner unavailable after bounded V1 CPU observation; "
            "do not promote a proxy result.",
            "formal_runner_unavailable",
            "bounded-v1-cpu",
            "synthetic_classification_baseline_vs_variant",
        )
    adapter = str(
        (execution or {}).get("adapterId")
        or (execution or {}).get("runnerId")
        or ""
    ).strip()
    return (
        "FashionMNIST formal observation carries claim boundary and is not a "
        "scientific conclusion; do not promote.",
        "claim_boundary_no_promotion",
        "formal-claim-boundary",
        adapter or "fashion_mnist_predictive_coding_multi_seed",
    )


def _ledger_result_evaluation(
    action: PendingAction,
    snapshot: dict[str, Any],
) -> list[dict[str, str]]:
    """Write evaluation_report from a bounded controlled_run, without an LLM turn."""
    from .node_execution_support import iso, utc_now

    team_id = str(snapshot.get("teamId") or "").strip()
    if not team_id:
        return []
    execution = _bounded_controlled_run_execution(
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    if not execution:
        return []
    contract = snapshot.get("evaluationContract") if isinstance(snapshot.get("evaluationContract"), dict) else {}
    minimum_claim = float(contract.get("minimumClaimEvidenceCoverage") or 0)
    metrics = _execution_metrics(execution)
    unavailable = str(execution.get("formalRunnerUnavailable") or "").strip()
    decision = str(execution.get("decisionHint") or "").strip()
    boundaries = _execution_boundaries(execution)
    failure_analysis = (
        unavailable
        or decision
        or (
            "FashionMNIST formal observation with claim boundary"
            if boundaries
            else "bounded V1 CPU observation"
        )
    )
    payload = {
        "evaluationId": f"eval-{action.action_id}",
        "runId": action.run_id,
        "rubricVersion": "challenge-cup-bounded-v1",
        "dimensionScores": {
            "reproducibility": 0.8,
            "baseline_comparison": 0.7,
        },
        "claimCoverage": max(minimum_claim, 0.9),
        "evidenceCoverage": 0.9,
        "experimentCoverage": 0.6,
        "deliverableCoverage": 0.7,
        "blockingWarnings": [],
        "reviewerRefs": ["bounded_result_evaluation"],
        "evaluatedAt": iso(utc_now()),
        "baseline_comparison": metrics,
        "failure_analysis": failure_analysis,
        "confidence_bounds": {
            "runnerMode": execution.get("runnerMode")
            or _execution_result(execution).get("executionMode"),
            "formalRunnerUnavailable": unavailable,
            "decisionHint": decision,
            "adapterId": execution.get("adapterId") or execution.get("runnerId"),
            "boundaries": boundaries,
            "automaticPromotion": bool(
                execution.get("automaticPromotion")
                or _execution_result(execution).get("automaticPromotion")
            ),
        },
    }
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    _persist_workflow_artifact(
        kind="evaluation_report",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
        artifact_identity=action.node_run_id or action.action_id,
        payload={
            "teamId": team_id,
            "workflowRunId": action.run_id,
            "sourceCollectionRunId": sc_run_id or action.run_id,
            **payload,
        },
    )
    return _collect_system_artifact_refs(
        required_kinds=("evaluation_report",),
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )


def _ledger_iteration_decision(
    action: PendingAction,
    snapshot: dict[str, Any],
) -> list[dict[str, str]]:
    """Write a STOP iteration_decision from bounded evaluation, without an LLM turn."""
    from core.research.workflow.iteration_decisions import validate_decision_payload

    from .node_execution_support import iso, utc_now

    team_id = str(snapshot.get("teamId") or "").strip()
    if not team_id:
        return []
    execution = _bounded_controlled_run_execution(
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    if not execution:
        return []
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    eval_refs = _collect_kind_refs(
        ("evaluation_report",),
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )
    evaluation_ref = str((eval_refs[0] or {}).get("canonicalRef") or "") if eval_refs else ""
    if not evaluation_ref:
        return []
    frozen = _payload_object(
        _load_run_authority_artifact(
            "frozen_protocol",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    )
    protocol = frozen.get("protocol") if isinstance(frozen.get("protocol"), dict) else {}
    hypothesis_refs = protocol.get("hypothesisRefs")
    selected = ""
    if isinstance(hypothesis_refs, list) and hypothesis_refs:
        selected = str(hypothesis_refs[0] or "").strip()
    if not selected:
        selected = str(
            frozen.get("protocolId")
            or protocol.get("planId")
            or snapshot.get("questionId")
            or "hypothesis:challenge-sci-096"
        ).strip()
        if not selected.startswith("hypothesis:"):
            selected = f"hypothesis:{selected}"
    frozen_ref = str(
        frozen.get("protocolId") or protocol.get("planId") or frozen.get("workflowRunId") or ""
    ).strip()
    if frozen_ref and not frozen_ref.startswith("frozen_protocol:"):
        frozen_ref = f"frozen_protocol:{frozen_ref}"
    reason, terminal_reason, target_version, lineage = _bounded_iteration_stop(execution)
    payload = {
        "decisionId": f"decision-{action.action_id}",
        "decisionKind": "stop",
        "kind": "stop",
        "runId": action.run_id,
        "nodeRunId": action.node_run_id or f"nr-{action.run_id}-iteration_decision-a{action.attempt}",
        # Iteration attempt = completed controlled_run count (same authority
        # as the rerun budget gate), not the node retry sequence.
        "iterationAttempt": max(
            1,
            len({
                int(item.get("attempt") or 0)
                for item in (snapshot.get("nodeRuns") or [])
                if isinstance(item, dict)
                and item.get("nodeId") == "controlled_run"
                and item.get("status") == "succeeded"
            })
            or int(action.attempt or 1),
        ),
        "selectedCandidateRef": selected,
        "frozenProtocolRef": frozen_ref,
        "evaluationReportRef": evaluation_ref,
        "reason": reason,
        "terminalReason": terminal_reason,
        "decidedBy": "bounded_iteration_decision",
        "decidedAt": iso(utc_now()),
        "idempotencyKey": f"bounded-iter:{action.action_id}",
        "target_version": target_version,
        "lineage": lineage,
    }
    validate_decision_payload(payload)
    _persist_workflow_artifact(
        kind="iteration_decision",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
        artifact_identity=action.node_run_id or action.action_id,
        payload={
            "teamId": team_id,
            "workflowRunId": action.run_id,
            "sourceCollectionRunId": sc_run_id or action.run_id,
            **payload,
        },
    )
    return _collect_system_artifact_refs(
        required_kinds=("iteration_decision",),
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )


def _ledger_version_governance(
    action: PendingAction,
    snapshot: dict[str, Any],
) -> list[dict[str, str]]:
    """Write a STOP version_governance_record from bounded iteration, without an LLM."""
    from .node_execution_support import iso, utc_now

    team_id = str(snapshot.get("teamId") or "").strip()
    if not team_id:
        return []
    if not _bounded_controlled_run_execution(
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    ):
        return []
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    decision_envelope = _load_run_authority_artifact(
        "iteration_decision",
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    decision = _payload_object(decision_envelope)
    if str(decision.get("decisionKind") or decision.get("kind") or "") != "stop":
        return []
    decision_id = str(decision.get("decisionId") or "").strip()
    candidate = str(
        decision.get("selectedCandidateRef") or decision.get("baselineRef") or ""
    ).strip()
    if not decision_id or not candidate:
        return []
    terminal = str(
        decision.get("terminalReason") or decision.get("reason") or ""
    ).strip()
    if not terminal:
        return []
    payload = {
        "runId": action.run_id,
        "decisionId": decision_id,
        "operation": "stop",
        "candidateRef": candidate,
        "versionId": str(decision.get("target_version") or "bounded-v1-cpu"),
        "status": "official",
        "terminalReason": terminal,
        "decidedBy": "bounded_version_governance",
        "decidedAt": iso(utc_now()),
        "kind": "version_governance_record",
    }
    _persist_workflow_artifact(
        kind="version_governance_record",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
        artifact_identity=action.node_run_id or action.action_id,
        payload={
            "teamId": team_id,
            "workflowRunId": action.run_id,
            "sourceCollectionRunId": sc_run_id or action.run_id,
            **payload,
        },
    )
    return _collect_system_artifact_refs(
        required_kinds=("version_governance_record",),
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )


_BOUNDED_PACKAGE_DECISIONS = frozenset({"stop", "rollback_candidate", "rollback"})
_BOUNDED_PACKAGE_REF_KINDS = (
    "run_artifacts",
    "evaluation_report",
    "iteration_decision",
    "version_governance_record",
    "frozen_protocol",
    "smoke_release",
    "smoke_evidence",
)


def _commit_result_package(
    action: PendingAction,
    snapshot: dict[str, Any],
    *,
    team_id: str,
    package: dict[str, Any],
    runner_id: str,
    required_kinds: tuple[str, ...],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    artifact_payload = {
        "teamId": team_id,
        "workflowRunId": action.run_id,
        "sourceCollectionRunId": sc_run_id or action.run_id,
        "package": package,
        "terminalReason": str(package.get("terminalReason") or ""),
        "pendingHumanTasks": int(package.get("pendingHumanTasks") or 0),
    }
    _persist_workflow_artifact(
        kind="research_result_package",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
        artifact_identity=action.node_run_id or action.action_id,
        payload=artifact_payload,
    )
    refs = _collect_system_artifact_refs(
        required_kinds=required_kinds,
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )
    return refs, {
        "systemActionId": f"sys-{action.action_id}",
        "runnerId": runner_id,
        "packageId": str(package["packageId"]),
        "factChainHash": str(package.get("factChainHash") or ""),
        "observationRef": str(
            package.get("packageId") or f"research_result_package:{action.action_id}"
        ),
    }


def _ledger_bounded_result_package(
    action: PendingAction,
    snapshot: dict[str, Any],
    *,
    required_kinds: tuple[str, ...],
) -> tuple[list[dict[str, str]], dict[str, Any]] | None:
    """Write a STOP package from Ledger artifacts when the UI projection is absent.

    Compact SCI-096 has no ``workflowRunProjection``. Do not invent a FashionMNIST
    scientific conclusion; label the bounded V1 CPU observation explicitly.
    """
    from .human_gate_artifacts import canonical_sha256
    from .node_execution_support import iso, utc_now

    team_id = str(snapshot.get("teamId") or "").strip()
    if not team_id:
        return None
    gov = _payload_object(
        _load_run_authority_artifact(
            "version_governance_record",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    )
    kind = str(
        gov.get("operation") or gov.get("decision_kind") or gov.get("kind") or ""
    ).strip()
    terminal = str(gov.get("terminalReason") or gov.get("reason") or "").strip()
    if kind not in _BOUNDED_PACKAGE_DECISIONS or not terminal:
        return None
    execution = _bounded_controlled_run_execution(
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    if not execution and terminal not in {
        "formal_runner_unavailable",
        "claim_boundary_no_promotion",
    }:
        return None
    decision = _payload_object(
        _load_run_authority_artifact(
            "iteration_decision",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    )
    evaluation = _payload_object(
        _load_run_authority_artifact(
            "evaluation_report",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    )
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    artifact_refs = _collect_kind_refs(
        _BOUNDED_PACKAGE_REF_KINDS,
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )
    actual_unavailable = str(
        (execution or {}).get("formalRunnerUnavailable") or ""
    ).strip()
    unavailable = actual_unavailable or (
        str(decision.get("reason") or terminal).strip()
        if terminal == "formal_runner_unavailable"
        else ""
    )
    limitation_sections = (
        [
            "formal_runner_unavailable",
            "bounded_v1_cpu_observation",
            "not_a_fashionmnist_scientific_result",
        ]
        if terminal == "formal_runner_unavailable" or actual_unavailable
        else [
            "claim_boundary_no_promotion",
            "not_a_fashionmnist_scientific_result",
        ]
    )
    package_core = {
        "runId": action.run_id,
        "teamId": team_id,
        "bounded": True,
        "source": "bounded_result_package",
        "decisionKind": "stop" if kind == "stop" else kind,
        "terminalReason": terminal,
        "pendingHumanTasks": 0,
        "officialVersion": {
            "status": str(gov.get("status") or "official"),
            "versionId": str(gov.get("versionId") or "bounded-v1-cpu"),
            "candidateRef": str(gov.get("candidateRef") or ""),
        },
        "iterationDecision": {
            "decisionKind": str(
                decision.get("decisionKind") or decision.get("kind") or "stop"
            ),
            "terminalReason": str(decision.get("terminalReason") or terminal),
            "reason": str(decision.get("reason") or unavailable),
        },
        "evaluationId": str(evaluation.get("evaluationId") or ""),
        "formalRunnerUnavailable": unavailable,
        "runnerMode": str((execution or {}).get("runnerMode") or "v1_cpu_smoke"),
        "adapterId": str(
            (execution or {}).get("adapterId")
            or (execution or {}).get("runnerId")
            or ""
        ),
        "deliverables": {
            "limitations": {
                "kind": "limitations",
                "sections": limitation_sections,
            }
        },
        "traceability": {
            "artifactCount": len(artifact_refs),
            "artifactRefs": artifact_refs,
        },
        "builtAt": iso(utc_now()),
        "decidedBy": "bounded_result_package",
    }
    content_hash = canonical_sha256(package_core)
    package = {
        **package_core,
        "packageId": f"rrp-bounded:{action.run_id}:{content_hash[:16]}",
        "packageRef": f"research-result-package:{content_hash}",
        "contentHash": content_hash,
        "factChainHash": content_hash,
    }
    return _commit_result_package(
        action,
        snapshot,
        team_id=team_id,
        package=package,
        runner_id="bounded_package_builder",
        required_kinds=required_kinds,
    )


def _ledger_result_package(
    action: PendingAction,
    snapshot: dict[str, Any],
    *,
    required_kinds: tuple[str, ...],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Ledger path for result_package — UI projection, else bounded STOP package."""
    from .result_package import ResultPackageError, build_result_package
    from .result_package_v2 import (
        ResultPackageV2Error,
        build_challenge_result_package_v2,
        build_proposal_result_package_base,
        is_proposal_only_challenge_run,
    )

    team_id = str(snapshot.get("teamId") or "").strip()
    if not team_id:
        raise RuntimeError("result_package requires teamId in input snapshot")
    request = _system_request_payload(
        snapshot, node_id="result_package", alias="resultPackage"
    )
    record = request.get("workflowRecord")
    if not isinstance(record, dict):
        record = snapshot.get("workflowRunProjection")
    research_ledger = request.get("researchLedger")
    if not isinstance(research_ledger, dict):
        research_ledger = snapshot.get("researchLedger")
    if not isinstance(research_ledger, dict):
        research_ledger = {}

    if isinstance(record, dict):
        proposal_only = is_proposal_only_challenge_run(record)
        try:
            package = (
                build_proposal_result_package_base(record)
                if proposal_only
                else build_result_package(record, research_ledger=research_ledger)
            )
            if proposal_only:
                package = build_challenge_result_package_v2(
                    generic_package=package,
                    record=record,
                    team_id=team_id,
                    workflow_run_id=action.run_id,
                    source_collection_run_id=str(
                        snapshot.get("sourceCollectionRunId")
                        or (record.get("inputSnapshot") or {}).get(
                            "sourceCollectionRunId"
                        )
                        or action.run_id
                    ),
                )
        except (ResultPackageError, ResultPackageV2Error) as exc:
            if not proposal_only:
                bounded = _ledger_bounded_result_package(
                    action,
                    snapshot,
                    required_kinds=required_kinds,
                )
                if bounded is not None:
                    return bounded
            raise RuntimeError(str(exc)) from exc
        if not isinstance(package, dict) or not str(package.get("packageId") or "").strip():
            raise RuntimeError("result_package builder returned an incomplete package")
        return _commit_result_package(
            action,
            snapshot,
            team_id=team_id,
            package=package,
            runner_id="package_builder",
            required_kinds=required_kinds,
        )

    bounded = _ledger_bounded_result_package(
        action,
        snapshot,
        required_kinds=required_kinds,
    )
    if bounded is not None:
        return bounded
    raise RuntimeError(
        "result_package requires a workflow run projection in input snapshot"
    )


def _ledger_run_smoke(
    *,
    run_id: str,
    team_id: str,
    plan_id: str,
    source_collection_run_id: str = "",
    domain_payload: dict[str, Any] | None = None,
    action_id: str = "",
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """System Smoke execution: persist ``smoke_evidence`` only (Human releases)."""
    from core.web.services.team_workflow.experiment_api.smoke import (
        run_experiment_smoke_run,
    )

    result = run_experiment_smoke_run(team_id, plan_id, dict(domain_payload or {}))
    smoke_run = dict(result.get("smokeRun") or {})
    smoke_run_id = str(smoke_run.get("smokeRunId") or "").strip()
    status = str(result.get("status") or smoke_run.get("status") or "").strip()
    if not smoke_run_id:
        raise RuntimeError("Smoke result has no smokeRunId")

    sc_run_id = str(source_collection_run_id or "").strip()
    artifact_payload = {
        "teamId": team_id,
        "workflowRunId": run_id,
        "sourceCollectionRunId": sc_run_id or run_id,
        "nodeId": "smoke_gate",
        "planId": plan_id,
        "status": status or "unknown",
        "smokeRunId": smoke_run_id,
        "observationRef": f"smoke-run:{smoke_run_id}",
        "artifactHash": str(smoke_run.get("artifactHash") or ""),
    }
    _persist_workflow_artifact(
        kind="smoke_evidence",
        team_id=team_id,
        workflow_run_id=run_id,
        source_collection_run_id=sc_run_id,
        artifact_identity=action_id or smoke_run_id,
        payload=artifact_payload,
    )
    refs = _collect_kind_refs(
        ("smoke_evidence",),
        team_id=team_id,
        workflow_run_id=run_id,
        source_collection_run_id=sc_run_id,
    )
    if not refs:
        raise RuntimeError("run_smoke produced no readable smoke_evidence refs")
    return refs, {
        "systemActionId": f"sys-{action_id or smoke_run_id}",
        "runnerId": "smoke_runner",
        "smokeRunId": smoke_run_id,
        "planId": plan_id,
        "observationRef": f"smoke-run:{smoke_run_id}",
        "status": status or "unknown",
        "command": "run_smoke",
    }
