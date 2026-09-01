"""Workflow Query Service — scoped read orchestration over the Ledger.

Zero writes. No route/HTTP objects enter this layer. Ledger unavailability
fails closed; legacy JSON stores are never consulted.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from core.research.workflow.contracts import ResearchWorkflowSnapshot
from core.research.workflow.contracts.workflow_snapshot import (
    HumanTaskSummary,
    ResearchWorkflowNodeDetail,
)
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.ledger.errors import (
    WorkflowLedgerClosedError,
    WorkflowLedgerUnavailableError,
)
from core.research.workflow.ledger.repository import WorkflowLedgerRepository

from .blocked_reason import format_blocked_reason
from .command_offer_builder import build_command_offers
from .node_scoped_session_projection import project_ledger_scoped_sessions
from .projection_builder import ProjectionInputs, build_research_workflow_snapshot
from .readiness import NodeReadinessService
from .readiness.common import DomainReadinessContext
from .run_catalog import catalog_dict_from_run

logger = logging.getLogger(__name__)

# Schema version of the registered legacy snapshot that pre-identity runs
# fall back to (challenge-cup-research@2.1.0, the 17-node chain).
_LEGACY_SCHEMA_VERSION = "2.1.0"


class WorkflowQueryError(RuntimeError):
    code = "workflow_query_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class TeamScopeMismatchError(WorkflowQueryError):
    code = "team_scope_mismatch"

    def __init__(self, detail: str = "teamId does not match run scope") -> None:
        super().__init__(detail, code="team_scope_mismatch")


class RunNotFoundError(WorkflowQueryError):
    code = "run_not_found"

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run not found: {run_id}", code="run_not_found")


class NodeNotFoundError(WorkflowQueryError):
    code = "unknown_node"

    def __init__(self, node_id: str) -> None:
        super().__init__(f"unknown nodeId: {node_id}", code="unknown_node")


class WorkflowLedgerUnavailable(WorkflowQueryError):
    code = "workflow_ledger_unavailable"

    def __init__(self, detail: str = "workflow ledger unavailable") -> None:
        super().__init__(detail, code="workflow_ledger_unavailable")


class WorkflowQueryService:
    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        readiness_service: NodeReadinessService,
        readiness_context: Callable[[], DomainReadinessContext],
        clock_iso: Callable[[], str] | None = None,
        evaluated_at_ms: Callable[[], int] | None = None,
        definition: Any | None = None,
        revise_checkpoint_resolver: Callable[[str], str] | None = None,
        session_detail_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self._store = store
        self._readiness = readiness_service
        self._readiness_context = readiness_context
        self._clock_iso = clock_iso or _default_iso_clock
        self._evaluated_at_ms = evaluated_at_ms
        self._definition = definition or build_challenge_cup_workflow_definition()
        self._revise_checkpoint_resolver = revise_checkpoint_resolver
        self._session_detail_reader = session_detail_reader

    def _resolve_revise_checkpoint_id(self, run: Any) -> str | None:
        """Revision offers need a fork base checkpoint.

        Root runs never carry ``forked_from_checkpoint_id``; resolve the
        thread's latest durable checkpoint instead (fail soft to unavailable).
        """
        if str(run.forked_from_checkpoint_id or "").strip():
            return None
        if self._revise_checkpoint_resolver is None:
            return None
        try:
            return str(self._revise_checkpoint_resolver(run.thread_id) or "").strip() or None
        except Exception:  # noqa: BLE001 - snapshot reads must fail soft
            return None

    def list_runs(self, *, team_id: str, workflow_id: str) -> dict[str, Any]:
        scoped_team = _require_team_id(team_id)
        try:
            records = self._store.list_runs_for_team(scoped_team, workflow_id)
        except (WorkflowLedgerUnavailableError, WorkflowLedgerClosedError) as exc:
            raise WorkflowLedgerUnavailable(str(exc)) from exc
        return {
            "workflowId": workflow_id,
            "runs": [catalog_dict_from_run(item) for item in records],
        }

    def get_snapshot(self, *, team_id: str, run_id: str) -> ResearchWorkflowSnapshot:
        scoped_team = _require_team_id(team_id)
        try:
            bundle = self._read_bundle(run_id)
        except (WorkflowLedgerUnavailableError, WorkflowLedgerClosedError) as exc:
            raise WorkflowLedgerUnavailable(str(exc)) from exc
        except WorkflowLedgerUnavailable:
            raise
        if bundle is None:
            # Distinguish missing run vs wrong team without leaking cross-team existence.
            try:
                bare = self._store.get_run(run_id)
            except (WorkflowLedgerUnavailableError, WorkflowLedgerClosedError) as exc:
                raise WorkflowLedgerUnavailable(str(exc)) from exc
            if bare is None:
                raise RunNotFoundError(run_id)
            raise TeamScopeMismatchError()

        (
            run,
            attempts,
            human_tasks,
            handoffs,
            budget_receipts,
            artifact_receipts,
            delivery_status,
            delivery_artifact,
            launch_context,
            discussion_projection,
            discussion_meetings,
            discussion_rooms,
            latest_seq,
            execution_anchors,
            knowledge_invocations,
            knowledge_child_node_states,
        ) = bundle
        if run.team_id != scoped_team:
            raise TeamScopeMismatchError()

        definition, definition_resolution = self._definition_for_run(run)
        offers = build_command_offers(
            readiness_service=self._readiness,
            context=self._readiness_context(),
            team_id=scoped_team,
            run=run,
            definition=definition,
            pending_human_tasks=human_tasks,
            attempts=attempts,
            evaluated_at_ms=(
                self._evaluated_at_ms() if self._evaluated_at_ms is not None else None
            ),
            revise_checkpoint_id=self._resolve_revise_checkpoint_id(run),
            invocations=knowledge_invocations,
            definition_resolution=definition_resolution,
        )
        return build_research_workflow_snapshot(
            ProjectionInputs(
                run=run,
                definition=definition,
                definition_resolution=definition_resolution,
                attempts=tuple(attempts),
                pending_human_tasks=tuple(human_tasks),
                handoffs=tuple(handoffs),
                budget_receipts=tuple(budget_receipts),
                command_offers=tuple(offers),
                artifact_receipts=tuple(artifact_receipts),
                delivery_status=delivery_status,
                delivery_artifact=delivery_artifact,
                launch_context=launch_context,
                discussion_projection=discussion_projection,
                discussion_meetings=discussion_meetings,
                discussion_rooms=discussion_rooms,
                execution_anchors=tuple(execution_anchors),
                knowledge_invocations=tuple(knowledge_invocations),
                knowledge_child_node_states=dict(knowledge_child_node_states),
                latest_event_sequence=latest_seq,
                generated_at=self._clock_iso(),
            )
        )

    def _definition_for_run(self, run: Any) -> tuple[Any, str]:
        """Resolve the definition pinned by the run's version identity.

        The canvas must render the topology the run was created with (2.1.0
        legacy runs keep the 17-node chain; 3.0.0/sideflow runs render their
        own pinned graph).  Returns ``(definition, resolution)`` where
        resolution is one of:

        - ``"pinned"``: the registry resolved the run's version identity
          (including its structureHash).
        - ``"legacy_default"``: the run predates version identities (empty
          ``workflow_version_id``); the fallback is the REGISTERED 2.1.0
          snapshot definition — never the current in-code build.
        - ``"degraded"``: the run's version identity exists but could not be
          honored (unknown version / hash mismatch / registry unavailable).
          The substitution is diagnostic-visible in the snapshot
          (``definitionResolution``) and logged, never silent.
        """
        workflow_id = str(getattr(run, "workflow_id", "") or "").strip()
        version_id = str(getattr(run, "workflow_version_id", "") or "").strip()
        structure_hash = str(getattr(run, "structure_hash", "") or "").strip()
        run_id = str(getattr(run, "run_id", "") or "")
        if not version_id:
            legacy = self._registered_legacy_definition(workflow_id)
            if legacy is not None:
                return legacy, "legacy_default"
            logger.warning(
                "workflow_definition_degraded: run has no version identity and "
                "no registered %s snapshot; falling back to the service default "
                "(runId=%s workflowId=%s)",
                _LEGACY_SCHEMA_VERSION,
                run_id or "<unknown>",
                workflow_id or "<unknown>",
            )
            return self._definition, "degraded"
        try:
            from core.research.workflow.definition_registry import resolve_definition

            return (
                resolve_definition(
                    workflow_id=workflow_id,
                    workflow_version_id=version_id,
                    structure_hash=structure_hash,
                    run_id=run_id,
                ),
                "pinned",
            )
        except Exception as exc:  # noqa: BLE001 - snapshot reads fail soft, visibly
            logger.warning(
                "workflow_definition_degraded: pinned resolution failed; "
                "falling back to the service default "
                "(runId=%s workflowId=%s workflowVersionId=%s structureHash=%s error=%s)",
                run_id or "<unknown>",
                workflow_id or "<unknown>",
                version_id,
                structure_hash or "<absent>",
                exc,
            )
            return self._definition, "degraded"

    def _registered_legacy_definition(self, workflow_id: str) -> Any | None:
        """The registered 2.1.0 snapshot definition for ``workflow_id``.

        Ancient runs carry no version identity; the only honest fallback is
        the registered legacy snapshot, resolved through the registry (the
        same reader every other consumer uses) — never a fresh compile of the
        current graph.
        """
        try:
            from core.research.workflow.definition_registry import (
                registered_definitions,
            )

            return next(
                (
                    item
                    for item in registered_definitions()
                    if str(item.workflowId) == workflow_id
                    and str(item.schemaVersion) == _LEGACY_SCHEMA_VERSION
                ),
                None,
            )
        except Exception:  # noqa: BLE001 - legacy fallback stays fail-soft
            return None

    def get_node_detail(
        self, *, team_id: str, run_id: str, node_id: str
    ) -> ResearchWorkflowNodeDetail:
        # Node membership is judged against the run's OWN pinned definition,
        # not the service default: a 2.1.0 run and a 3.0.0 run have different
        # node sets (e.g. knowledge_handoff exists only in the legacy chain).
        try:
            run = self._store.get_run(run_id)
        except (WorkflowLedgerUnavailableError, WorkflowLedgerClosedError) as exc:
            raise WorkflowLedgerUnavailable(str(exc)) from exc
        if run is not None:
            definition, _ = self._definition_for_run(run)
            node = next(
                (item for item in definition.nodes if item.nodeId == node_id),
                None,
            )
            if node is None:
                raise NodeNotFoundError(node_id)
        # A missing run skips the node check on purpose: get_snapshot below
        # raises the precise RunNotFoundError / TeamScopeMismatchError.

        def load(_repo: WorkflowLedgerRepository):
            snap = self.get_snapshot(team_id=team_id, run_id=run_id)
            attempts = snap.node_attempts.get(node_id, ())
            latest = attempts[-1] if attempts else None
            anchor = _load_anchor(
                self._store,
                latest.node_run_id if latest is not None else None,
            )
            return snap, latest, anchor

        if hasattr(self._store, "read"):
            snap, latest, anchor = self._store.read(load)
        else:
            snap, latest, anchor = load(self._store)  # type: ignore[arg-type]
        attempts = snap.node_attempts.get(node_id, ())
        offers = tuple(
            offer for offer in snap.command_offers if offer.node_id == node_id
        )
        frozen = _frozen_binding_for(snap, node_id)
        session = _session_fields(
            anchor,
            actor_kind=node.actorKind.value,
            frozen=frozen,
        )
        scoped_session_projection = project_ledger_scoped_sessions(
            anchor,
            team_id=team_id,
            run_id=run_id,
            node_id=node_id,
            node_run_id=latest.node_run_id if latest is not None else None,
            node_status=latest.status if latest is not None else snap.run.status,
            session_detail_reader=self._session_detail_reader,
        )
        formal_projection = bool(
            scoped_session_projection.get("_formalProjection")
        )
        formal_root = scoped_session_projection.get("rootSession")
        if formal_projection:
            formal_root_healthy = bool(
                isinstance(formal_root, Mapping)
                and not formal_root.get("sessionAnchorDegraded")
            )
            if formal_root_healthy:
                projected_session_id = _optional_session_scalar(
                    formal_root.get("sessionId")
                )
                projected_task_id = _optional_session_scalar(
                    formal_root.get("taskId")
                )
                projected_turn_id = _optional_session_scalar(
                    formal_root.get("turnId")
                )
                projected_session_attempt = formal_root.get("sessionAttempt")
                projected_chat_deep_link = _optional_session_scalar(
                    formal_root.get("chatDeepLink")
                )
                projected_session_degraded = False
            else:
                # A formal payload is authoritative even when its root is
                # absent or damaged. Do not fall back to the ledger row's
                # scalar session fields, which may point at a candidate child.
                projected_session_id = None
                projected_task_id = None
                projected_turn_id = None
                projected_session_attempt = None
                projected_chat_deep_link = None
                projected_session_degraded = True
        else:
            projected_session_id = session["session_id"]
            projected_task_id = session["task_id"]
            projected_turn_id = session["turn_id"]
            projected_session_attempt = session["session_attempt"]
            projected_chat_deep_link = _chat_deep_link(
                team_id=team_id,
                run_id=run_id,
                node_id=node_id,
                session_id=projected_session_id,
                task_id=projected_task_id,
                turn_id=projected_turn_id,
            )
            projected_session_degraded = session["degraded"]
        return ResearchWorkflowNodeDetail(
            run_id=run_id,
            team_id=team_id,
            node_id=node_id,
            run_version=snap.run.run_version,
            actor_kind=node.actorKind.value,
            primary_role_key=node.primaryRoleKey,
            label=node.label,
            runtime_current=node_id in snap.active_node_ids,
            status=latest.status if latest is not None else snap.run.status,
            binding_snapshot_id=(
                (latest.binding_snapshot_id if latest is not None else None)
                or (frozen.snapshot_id if frozen is not None and frozen.snapshot_id else None)
            ),
            latest_attempt=latest,
            attempts=attempts,
            command_offers=offers,
            latest_event_sequence=snap.latest_event_sequence,
            generated_at=snap.generated_at,
            agent_id=session["agent_id"],
            display_name=session["display_name"],
            resolved_from=session["resolved_from"],
            session_id=projected_session_id,
            task_id=projected_task_id,
            turn_id=projected_turn_id,
            session_attempt=projected_session_attempt,
            chat_deep_link=projected_chat_deep_link,
            session_anchor_degraded=projected_session_degraded,
            root_session=scoped_session_projection["rootSession"],
            scoped_sessions=tuple(scoped_session_projection["scopedSessions"]),
            blocked_reason=_node_blocked_reason(latest, snap.run.blocked_reason),
        )

    def _read_bundle(self, run_id: str):
        def load(repo: WorkflowLedgerRepository):
            run = repo.get_run(run_id)
            if run is None:
                return None
            attempts = repo.list_attempts(run_id)
            human_rows = repo.list_pending_human_tasks(run_id)
            attempt_by_id = {item.node_run_id: item for item in attempts}
            human_tasks = [
                _human_task_summary(row, attempt_by_id) for row in human_rows
            ]
            execution_anchors = _latest_attempt_anchor_rows(repo, attempts)
            refs_by_handoff: dict[str, list[dict[str, Any]]] = {}
            for row in repo.list_handoff_artifact_refs_for_run(run_id):
                refs_by_handoff.setdefault(str(row[0]), []).append(
                    _artifact_ref_from_receipt(row)
                )
            handoffs = [
                _handoff_summary(row, attempt_by_id, refs_by_handoff)
                for row in repo.list_handoffs_for_run(run_id)
            ]
            budget_receipts = [
                _budget_receipt_summary(row)
                for row in repo.list_budget_receipts_for_run(run_id)
            ]
            artifact_receipts = repo.list_artifact_receipts_for_run(run_id)
            knowledge_invocations = _load_knowledge_invocations(repo, run_id)
            knowledge_child_node_states = _load_knowledge_child_node_states(
                repo, knowledge_invocations
            )
            latest_seq = repo.latest_event_sequence(run_id)
            events = _read_bounded_events(
                repo,
                run_id,
                latest_sequence=latest_seq,
            )
            delivery_status, delivery_artifact = _delivery_projection_from_events(
                events,
                run_status=run.status,
            )
            launch_context = _launch_context_from_run(run, events)
            (
                discussion_projection,
                discussion_meetings,
                discussion_rooms,
            ) = _discussion_inputs_from_run(
                run,
                events,
                launch_context,
            )
            return (
                run,
                attempts,
                human_tasks,
                handoffs,
                budget_receipts,
                artifact_receipts,
                delivery_status,
                delivery_artifact,
                launch_context,
                discussion_projection,
                discussion_meetings,
                discussion_rooms,
                latest_seq,
                execution_anchors,
                knowledge_invocations,
                knowledge_child_node_states,
            )

        if hasattr(self._store, "read"):
            return self._store.read(load)
        # Narrow test doubles may raise WorkflowLedgerUnavailable directly.
        return load(self._store)  # type: ignore[arg-type]


def _load_knowledge_invocations(
    repo: WorkflowLedgerRepository, run_id: str
) -> list[Any]:
    """Load the run's knowledge invocations (fail-soft, additive projection).

    Older test doubles / schemas may not carry the ``knowledge_invocations``
    table; a missing source degrades to "no knowledge activity" instead of
    failing the whole snapshot.
    """
    loader = getattr(repo, "list_knowledge_invocations_for_parent", None)
    if loader is None:
        return []
    try:
        return list(loader(run_id))
    except Exception:  # noqa: BLE001 - badge reads must not break snapshots
        return []


def _load_knowledge_child_node_states(
    repo: WorkflowLedgerRepository,
    invocations: Sequence[Any],
) -> dict[str, dict[str, str]]:
    """Per-child-run latest node status, keyed by sideflow node id.

    The five-node sideflow progress must come from the child run's REAL node
    attempts — an invocation-level status alone cannot say which middle node
    is running. Fail-soft per child run: a missing/unreadable child run
    simply yields no per-node states and the readers fall back to the
    invocation-level derivation.
    """
    loader = getattr(repo, "list_attempts", None)
    if loader is None:
        return {}
    states: dict[str, dict[str, str]] = {}
    for row in invocations:
        child_run_id = str(getattr(row, "knowledge_child_run_id", "") or "").strip()
        if not child_run_id or child_run_id in states:
            continue
        try:
            attempts = list(loader(child_run_id))
        except Exception:  # noqa: BLE001 - child progress must not break snapshots
            continue
        latest_by_node: dict[str, Any] = {}
        for attempt in attempts:
            node_id = str(getattr(attempt, "node_id", "") or "")
            if not node_id:
                continue
            prior = latest_by_node.get(node_id)
            if prior is None or int(attempt.attempt) >= int(prior.attempt):
                latest_by_node[node_id] = attempt
        states[child_run_id] = {
            node_id: str(getattr(attempt, "status", "") or "")
            for node_id, attempt in latest_by_node.items()
        }
    return states


def _latest_attempt_anchor_rows(
    repo: WorkflowLedgerRepository,
    attempts: Sequence[Any],
) -> list[dict[str, Any]]:
    """Load the execution anchor of each node's latest attempt (read-only).

    The snapshot's currentTask uses these to surface the live Agent task
    identity during dispatch instead of only after the adapter commit.
    """

    latest_by_node: dict[str, Any] = {}
    for attempt in attempts:
        prior = latest_by_node.get(attempt.node_id)
        if prior is None or int(attempt.attempt) >= int(prior.attempt):
            latest_by_node[attempt.node_id] = attempt
    anchors: list[dict[str, Any]] = []
    for attempt in latest_by_node.values():
        try:
            row = repo.get_anchor_by_node_run(attempt.node_run_id)
        except Exception:  # noqa: BLE001 - anchor reads must not break snapshots
            row = None
        projection = _anchor_projection(row)
        if projection is not None:
            anchors.append(projection)
    return anchors


def _anchor_projection(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        session_attempt = row[6]
        return {
            "anchorId": str(row[0] or ""),
            "nodeRunId": str(row[1] or ""),
            "agentId": str(row[3] or ""),
            "roleKey": str(row[4] or ""),
            "sessionId": str(row[5] or ""),
            "sessionAttempt": None if session_attempt is None else int(session_attempt),
            "taskId": str(row[7] or ""),
            "turnId": str(row[8] or ""),
            "status": str(row[12] or ""),
        }
    except (IndexError, TypeError, ValueError):
        return None


def _require_team_id(team_id: str) -> str:
    normalized = str(team_id or "").strip()
    if not normalized:
        raise TeamScopeMismatchError("teamId is required")
    return normalized


def _default_iso_clock() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _human_task_summary(row: tuple, attempt_by_id: dict[str, Any]) -> HumanTaskSummary:
    (
        task_id,
        run_id,
        node_run_id,
        handoff_id,
        task_kind,
        _prompt_json,
        status,
        _decision_json,
        created_at_ms,
        resolved_at_ms,
    ) = row
    attempt = attempt_by_id.get(node_run_id)
    return HumanTaskSummary(
        task_id=task_id,
        run_id=run_id,
        node_run_id=node_run_id,
        node_id=attempt.node_id if attempt is not None else None,
        handoff_id=handoff_id,
        task_kind=task_kind,
        status=status,
        created_at_ms=created_at_ms,
        resolved_at_ms=resolved_at_ms,
    )


def _handoff_summary(
    row: tuple,
    attempt_by_id: dict[str, Any],
    refs_by_handoff: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    from_node_run_id = str(row[3] or "")
    attempt = attempt_by_id.get(from_node_run_id)
    edge_id = str(row[2] or "")
    from_node_id = ""
    if attempt is not None:
        from_node_id = str(attempt.node_id or "")
    elif "->" in edge_id:
        from_node_id = edge_id.split("->", 1)[0]
    return {
        "handoffId": row[0],
        "runId": row[1],
        "edgeId": edge_id,
        "fromNodeId": from_node_id,
        "fromNodeRunId": from_node_run_id,
        "toNodeId": row[4],
        "toNodeRunId": row[5],
        "gateKind": row[6],
        "inputSnapshotHash": row[7],
        "status": row[8],
        "outputArtifactRefs": list(refs_by_handoff.get(str(row[0]), [])),
        "offeredAtMs": row[12],
        "acceptedAtMs": row[13],
    }


def _artifact_ref_from_receipt(row: tuple) -> dict[str, Any]:
    canonical_ref = ""
    try:
        payload = json.loads(row[3] or "{}")
        if isinstance(payload, dict):
            canonical_ref = str(payload.get("canonicalRef") or "")
    except (TypeError, ValueError):
        canonical_ref = ""
    return {
        "artifactId": str(row[1] or ""),
        "kind": str(row[2] or ""),
        "version": str(row[4] or "1.0.0"),
        "contentHash": str(row[5] or ""),
        "uri": canonical_ref,
    }


def _event_sequence(event: Any) -> int:
    value = getattr(event, "sequence", event)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _read_bounded_events(
    repo: WorkflowLedgerRepository,
    run_id: str,
    *,
    latest_sequence: int | None = None,
) -> list[Any]:
    """Read a bounded head+tail window from the capped Ledger event query.

    The head preserves launch/authorization facts while the tail preserves
    the newest delivery/recovery fact. Two bounded reads avoid both the
    repository's 500-row cap and an unbounded timeline scan.
    """
    latest = int(
        latest_sequence
        if latest_sequence is not None
        else repo.latest_event_sequence(run_id)
    )
    head = repo.list_events(run_id, 0, 250)
    tail_after = max(0, latest - 250)
    tail = repo.list_events(run_id, tail_after, 500)
    merged: dict[tuple[int, str], Any] = {}
    for event in (*head, *tail):
        key = (_event_sequence(event), str(getattr(event, "event_id", "")))
        merged[key] = event
    return sorted(merged.values(), key=_event_sequence)


def _event_payload(event: Any) -> Mapping[str, Any]:
    try:
        payload = json.loads(str(getattr(event, "payload_json", "") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, Mapping) else {}


def _delivery_projection_from_events(
    events: list[Any],
    *,
    run_status: str | None = None,
) -> tuple[str | None, Mapping[str, Any] | None]:
    """Read delivery status and only the event-authoritative final artifact."""
    for event in reversed(events or []):
        event_type = str(getattr(event, "event_type", "") or "")
        if not event_type.startswith("delivery_orchestration_"):
            continue
        payload = _event_payload(event)
        status = str(
            payload.get("deliveryStatus")
            or {
                "delivery_orchestration_completed": "succeeded",
                "delivery_orchestration_blocked": "blocked",
                "delivery_orchestration_failed": "failed",
            }.get(event_type, "")
        ).strip().lower()
        artifact = None
        if event_type == "delivery_orchestration_completed":
            artifact_ref = str(payload.get("artifactRef") or "").strip()
            artifact_kind = str(payload.get("artifactKind") or "").strip()
            if artifact_ref and artifact_kind:
                artifact = {
                    "artifactKind": artifact_kind,
                    "artifactRef": artifact_ref,
                    "artifactId": payload.get("artifactId"),
                }
        return status or None, artifact
    # A successful run atomically enqueues delivery orchestration.  Until its
    # terminal delivery event appears, expose that durable lifecycle fact as
    # pending rather than claiming success or inventing a result.
    return (
        "pending" if str(run_status or "").strip() == "succeeded" else None,
        None,
    )


def _delivery_status_from_events(
    events: list[Any],
    *,
    run_status: str | None = None,
) -> str | None:
    """Compatibility helper returning only the delivery status."""
    return _delivery_projection_from_events(events, run_status=run_status)[0]


def _launch_context_from_run(run: Any, events: list[Any]) -> dict[str, Any]:
    try:
        snapshot = json.loads(str(run.input_snapshot_json or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        snapshot = {}
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    constraint = snapshot.get("constraintSnapshot")
    constraint = constraint if isinstance(constraint, Mapping) else {}
    source = str(
        snapshot.get("launchSource")
        or constraint.get("launchSource")
        or ("catalog" if snapshot.get("competitionRuleRef") else "")
    ).strip() or None
    context: dict[str, Any] = {
        "source": source,
        "sourceCollectionRunId": str(snapshot.get("sourceCollectionRunId") or "").strip() or None,
        "authorizationId": str(
            snapshot.get("authorizationId") or snapshot.get("catalogAuthorizationId") or ""
        ).strip() or None,
        "planId": str(snapshot.get("planId") or "").strip() or None,
        "questionId": str(
            snapshot.get("questionId") or getattr(run, "question_id", "") or ""
        ).strip() or None,
        "hypothesisSelectionId": str(
            snapshot.get("hypothesisSelectionId")
            or snapshot.get("selectionId")
            or ""
        ).strip() or None,
        "catalogAuthorizationId": str(
            snapshot.get("catalogAuthorizationId")
            or snapshot.get("authorizationId")
            or ""
        ).strip() or None,
        "readinessReportSha256": str(
            snapshot.get("readinessReportSha256") or ""
        ).strip() or None,
        "chainCorrelationId": str(
            snapshot.get("chainCorrelationId") or ""
        ).strip() or None,
        "inputSnapshotHash": str(
            getattr(run, "input_snapshot_hash", "") or ""
        ).strip() or None,
    }
    for event in events or []:
        if str(getattr(event, "event_type", "") or "") != "catalog_run_authorized":
            continue
        payload = _event_payload(event)
        authorization_id = payload.get("authorizationId")
        if authorization_id is not None:
            context["authorizationId"] = authorization_id
            context["catalogAuthorizationId"] = authorization_id
        for key in (
            "planId",
            "scopeHash",
            "readinessReportSha256",
            "recordHash",
            "approvedBy",
            "approvedAtMs",
        ):
            if key in payload and payload.get(key) is not None:
                context[key] = payload.get(key)
        if "chainCorrelationId" in payload:
            context["chainCorrelationId"] = str(
                payload.get("chainCorrelationId") or ""
            ).strip() or None
        break
    return context


def _discussion_inputs_from_run(
    run: Any,
    events: list[Any],
    launch_context: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, Any, Any]:
    """Read only the canonical discussion authorities needed by projection.

    The formal ledger owns the workflow run, while hypothesis-first meetings
    and chat rooms remain append-only domain authorities.  This adapter keeps
    those reads out of ``projection_builder`` (which must stay pure) and never
    calls public room APIs that reconcile or repair state.  If no explicit
    discussion scope is present, no anchor is emitted for an ordinary run.
    A scoped run with missing authorities receives empty projections so the
    anchor returns a visible degraded reason instead of falling back to a team
    room.
    """

    projection = _discussion_projection_from_sources(run, events, launch_context)
    snapshot = _run_input_snapshot(run)
    objective = snapshot.get("researchObjectiveContract")
    hypothesis_first = isinstance(objective, Mapping) and objective.get(
        "hypothesisFirst"
    ) is True
    if projection is None and not hypothesis_first:
        return None, None, None
    if projection is None and hypothesis_first:
        try:
            from . import hypothesis_first_chain

            chain = hypothesis_first_chain.chain_state(
                str(getattr(run, "team_id", "") or ""),
                str(
                    snapshot.get("questionId")
                    or getattr(run, "question_id", "")
                    or ""
                ),
                workflow_run_id=str(getattr(run, "run_id", "") or "").strip(),
            )
            active = chain.get("activeDiscussionAnchor")
            if isinstance(active, Mapping):
                projection = dict(active)
        except Exception:  # noqa: BLE001 - missing authority stays degraded
            projection = None

    snapshot_authority = snapshot.get("discussionAuthority")
    if isinstance(snapshot_authority, Mapping):
        authority_projection = snapshot_authority.get("projection")
        if projection is None and isinstance(authority_projection, Mapping):
            projection = dict(authority_projection)
        meetings = snapshot_authority.get("meetings")
        rooms = snapshot_authority.get("rooms")
        if meetings is not None or rooms is not None:
            return projection or {}, meetings if meetings is not None else [], rooms if rooms is not None else []

    # Some adapters carry authority beside the scope in the event payload or
    # launch context.  Accept only the explicit discussion envelope.
    for source in (
        launch_context,
        *(payload for payload in (_event_payload(event) for event in events) if payload),
    ):
        if not isinstance(source, Mapping):
            continue
        authority = source.get("discussionAuthority")
        if not isinstance(authority, Mapping):
            continue
        meetings = authority.get("meetings")
        rooms = authority.get("rooms")
        if meetings is not None or rooms is not None:
            return projection or {}, meetings if meetings is not None else [], rooms if rooms is not None else []

    # Read the two append-only authorities without invoking their public
    # service methods: those methods reconcile active rounds/participants and
    # are therefore not suitable for a zero-write snapshot query.
    meetings: list[Mapping[str, Any]] = []
    rooms: list[Mapping[str, Any]] = []
    try:
        from core.web.services.team_workflow import meeting_rounds

        # Meeting rounds already have a formal read facade.  It folds the
        # append-only log and validates the team scope without writing, so do
        # not bypass that owner through its private path helpers.
        meeting_payload = meeting_rounds.list_meeting_rounds(
            str(getattr(run, "team_id", ""))
        )
        raw_meetings = (
            meeting_payload.get("meetings")
            if isinstance(meeting_payload, Mapping)
            else meeting_payload
        )
        raw_meetings = raw_meetings if isinstance(raw_meetings, list) else []
        latest: dict[str, Mapping[str, Any]] = {}
        for item in raw_meetings:
            if not isinstance(item, Mapping):
                continue
            meeting_id = str(item.get("meetingRoundId") or "").strip()
            if meeting_id:
                latest[meeting_id] = item
        meetings = list(latest.values())
    except Exception:  # noqa: BLE001 - missing legacy authority is degraded
        meetings = []
    try:
        from core.web.services import chat_room_service

        rooms = chat_room_service.read_chat_rooms_snapshot()
    except Exception:  # noqa: BLE001 - missing legacy authority is degraded
        rooms = []
    return projection or {}, meetings, rooms


def _discussion_projection_from_sources(
    run: Any,
    events: list[Any],
    launch_context: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Extract explicit active discussion identity from immutable envelopes."""

    sources: list[Mapping[str, Any]] = []
    snapshot = _run_input_snapshot(run)
    if snapshot:
        sources.append(snapshot)
    if isinstance(launch_context, Mapping):
        sources.append(launch_context)
    for event in events:
        payload = _event_payload(event)
        if payload:
            sources.append(payload)

    for source in sources:
        active = source.get("activeDiscussionAnchor")
        if isinstance(active, Mapping):
            return dict(active)
        for key in (
            "activeDiscussion",
            "discussionProjection",
            "discussionScope",
            "activeDiscussionScope",
        ):
            candidate = source.get(key)
            if isinstance(candidate, Mapping):
                if key in {"discussionScope", "activeDiscussionScope"}:
                    projection: dict[str, Any] = {"scope": dict(candidate)}
                else:
                    projection = dict(candidate)
                _copy_discussion_refs(source, projection)
                return projection
        binding = source.get("scopeBinding")
        if isinstance(binding, Mapping):
            scope = binding.get("discussionScope") or binding.get("scope")
            if isinstance(scope, Mapping):
                projection = {"scope": dict(scope)}
                _copy_discussion_refs(source, projection)
                _copy_discussion_refs(binding, projection)
                return projection
    return None


def _copy_discussion_refs(source: Mapping[str, Any], target: dict[str, Any]) -> None:
    for key in (
        "scopeHash",
        "discussionScopeHash",
        "activeMeetingRoundId",
        "currentMeetingRoundId",
        "meetingRoundId",
        "activeRoomId",
        "currentRoomId",
        "discussionRoomId",
        "roomId",
        "activeSelectionId",
        "currentSelectionId",
        "selectionId",
        "activeCandidateId",
        "currentCandidateId",
        "candidateId",
    ):
        if key in source and key not in target:
            target[key] = source.get(key)


def _run_input_snapshot(run: Any) -> dict[str, Any]:
    try:
        payload = json.loads(str(getattr(run, "input_snapshot_json", "") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _node_blocked_reason(latest: Any, run_blocked_reason: str | None) -> str:
    if latest is None or str(getattr(latest, "status", "") or "") != "blocked":
        return ""
    problem = getattr(latest, "problem", None)
    if isinstance(problem, dict):
        formatted = format_blocked_reason(problem)
        if formatted:
            return formatted
    return str(run_blocked_reason or "")


def _budget_receipt_summary(row: tuple) -> dict[str, Any]:
    def payload(raw: object) -> dict[str, Any]:
        try:
            decoded = json.loads(str(raw or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}

    return {
        "receiptId": row[0],
        "runId": row[1],
        "nodeRunId": row[2],
        "reservationId": row[3],
        "stageId": row[4],
        "policyHash": row[5],
        "reservedPayload": payload(row[6]),
        "settledPayload": payload(row[7]),
        "status": row[8],
        "createdAtMs": row[9],
        "updatedAtMs": row[10],
    }


def _load_anchor(store: Any, node_run_id: str | None) -> tuple | None:
    if not node_run_id:
        return None

    def load(repo: WorkflowLedgerRepository):
        return repo.get_anchor_by_node_run(node_run_id)

    if hasattr(store, "read"):
        return store.read(load)
    return load(store)


def _frozen_binding_for(snap: ResearchWorkflowSnapshot, node_id: str):
    for item in snap.agent_binding_summary.bindings:
        if item.node_id == node_id:
            return item
    return None


def _agent_display_name(agent_id: str) -> str:
    if not agent_id:
        return ""
    try:
        from core.web.services.team_service import lookup_agent_display_name_map

        name = str(lookup_agent_display_name_map().get(agent_id) or "").strip()
        if name:
            return name
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return agent_id
    return agent_id


def _session_fields(
    anchor: tuple | None,
    *,
    actor_kind: str,
    frozen: Any | None = None,
) -> dict[str, Any]:
    agent_id = str(anchor[3] or "").strip() if anchor is not None else ""
    resolved_from = "workflow_default" if agent_id else "unbound"
    if not agent_id and frozen is not None:
        agent_id = str(getattr(frozen, "agent_id", "") or "").strip()
        if agent_id:
            resolved_from = str(getattr(frozen, "resolved_from", "") or "").strip() or "workflow_default"
    session_id = str(anchor[5] or "").strip() if anchor is not None else ""
    session_attempt = anchor[6] if anchor is not None else None
    task_id = str(anchor[7] or "").strip() if anchor is not None else ""
    turn_id = str(anchor[8] or "").strip() if anchor is not None else ""
    complete = bool(session_id and task_id and turn_id)
    display_name = _agent_display_name(agent_id) if agent_id else ""
    return {
        "agent_id": agent_id or None,
        "display_name": display_name or agent_id,
        "resolved_from": resolved_from,
        "session_id": session_id or None,
        "task_id": task_id or None,
        "turn_id": turn_id or None,
        "session_attempt": int(session_attempt) if session_attempt is not None else None,
        "degraded": actor_kind == "agent" and not complete,
    }


def _optional_session_scalar(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _chat_deep_link(
    *,
    team_id: str,
    run_id: str,
    node_id: str,
    session_id: str | None,
    task_id: str | None,
    turn_id: str | None,
) -> str | None:
    if not (session_id and task_id and turn_id):
        return None
    return_to = "/teams?" + urlencode(
        {
            "teamId": team_id,
            "researchView": "workflow",
            "runId": run_id,
            "node": node_id,
        }
    )
    return "/chat?" + urlencode(
        {
            "session": session_id,
            "focusTask": task_id,
            "focusTurn": turn_id,
            "returnTo": return_to,
            "returnLabel": "返回科研流程",
        }
    )
