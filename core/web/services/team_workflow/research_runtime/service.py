"""Research workflow runtime service: definition, runs, commands, HITL, bindings.

HumanTasks, session bindings, handoffs, and idempotency keys are durable on disk.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.research.workflow.bindings import (
    AgentBindingLayers,
    build_run_binding_snapshots,
    resolve_effective_agent_id,
)
from core.research.workflow.checkpoint_store import default_checkpoint_path
from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts.automation_policy import (
    MAX_AUTO_REVISION_ROUNDS_DEFAULT,
)
from core.research.workflow.contracts.evolution_lineage import (
    REVISION_EXHAUSTED_EXCEPTION,
)
from core.research.workflow.contracts.retry_taxonomy import DEFAULT_RETRY_TAXONOMY
from core.research.workflow.definition import (
    CHALLENGE_CUP_WORKFLOW_ID,
    build_challenge_cup_workflow_definition,
)
from core.research.workflow.models import ActorKind
from core.research.workflow.projection import build_canvas_projection

from .anomaly_inbox_service import build_anomaly_inbox
from .binding_config import BindingConfigValidationError, WorkflowBindingConfigStore
from .checkpoint_lifecycle import prepare_initial_checkpoint
from .durable_index import DurableWorkflowIndex
from .evidence_remediation_fork import (
    EvidenceRemediationForkError,
    fork_evidence_remediation,
)
from .evolution_lineage_writer import write_evolution_lineage_artifact
from .external_agent_task_reconciliation import (
    has_reconcilable_external_agent_tasks,
    reconcile_external_agent_tasks,
)
from .failed_agent_budget import (
    FailedAgentBudgetError,
    settle_failed_agent_task_budget,
)
from .handoff_lineage import (
    build_auto_handoffs_for_completed,
)
from .handoff_query import (
    HandoffQueryError,
    get_handoff_detail,
    list_handoffs,
)
from .human_task_resolution import (
    HumanTaskResolutionError,
)
from .human_task_resolution import (
    resolve_human_task as resolve_human_task_transition,
)
from .iteration_revision_fork import _child_run_id, fork_iteration_revision
from .node_command_adapter import (
    NodeCommandError,
    NodeCommandUnavailable,
    apply_node_command,
    node_command_capabilities,
)
from .node_completion import complete_node_execution
from .node_execution import heartbeat_node_execution, start_node_execution
from .node_execution_support import (
    NodeExecutionError,
    build_event,
    iso,
    latest_node_run,
    utc_now,
)
from .node_operational_projection import project_node_operations
from .node_recovery import reconcile_expired_execution, retry_node_execution
from .node_scoped_session_projection import project_node_scoped_sessions
from .question_launch import (
    QuestionLaunchError,
    activate_experiment_campaign,
    attach_question_run_checkpoints,
    build_question_run_input,
    list_catalog_question_launch_options,
)
from .research_ledger import project_research_ledger
from .run_access import RunAccessError, require_run_access
from .run_domain_queries import (
    project_budget,
    project_evaluation,
    project_experiment_campaigns,
    project_hypotheses,
)
from .run_lifecycle import (
    binding_snapshot_payload,
    build_initial_run_record,
    create_request_fingerprint,
    freeze_run_input,
    run_id_for_create,
)
from .run_projection import build_run_canvas_projection
from .session_binding_bridge import (
    SessionBindingBridge,
    SessionBindingError,
)
from .store import WorkflowRunStore
from .task_bundle_lifecycle import (
    TaskBundleError,
    cancel_task_bundle,
    reconcile_expired_task_bundles,
)
from .team_role_source import effective_binding_layers

_FILE_STORE_TERMINAL_RUN_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "archived"}
)

_ACTIVE_TASK_BUNDLE_STATUSES = frozenset({"pending", "queued", "running"})

# Deadline enforcement runs from the resident worker tick. The per-service
# throttle bounds the store enumeration (one list_runs pass at most once per
# interval) even when the pump drains in a tight loop during active work.
_EXPIRED_TASK_BUNDLE_RECONCILE_MIN_INTERVAL_S = 30.0

logger = logging.getLogger(__name__)


def _require_non_terminal_run(record: dict[str, Any], *, command: str) -> None:
    """Legacy file-store commands must not resurrect a terminal run.

    Mirrors RUN_TRANSITIONS authority for the ledger stack: cancelling or
    retrying a finished/failed/cancelled run is an invalid state change.
    """
    status = str(record.get("status") or "").strip()
    if status in _FILE_STORE_TERMINAL_RUN_STATUSES:
        raise ResearchWorkflowError(
            f"{command} not allowed for run in status {status!r}",
            code="invalid_run_state",
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _create_request_fingerprints(run_input: Mapping[str, Any]) -> tuple[str, ...]:
    """Return current and legacy fingerprints for a create request.

    The session-scope mode is a server-owned field added by
    ``freeze_run_input``.  Ignore it for the current idempotency identity, but
    accept the raw fingerprint when replaying a pre-normalization run.
    """
    canonical_request = dict(run_input)
    canonical_request.pop("workflowSessionScopeV3", None)
    canonical = create_request_fingerprint(canonical_request)
    legacy = create_request_fingerprint(run_input)
    return tuple(dict.fromkeys((canonical, legacy)))


def _node_attempt(record: dict[str, Any], node_id: str) -> int:
    attempts = record.get("nodeAttempts") or {}
    if isinstance(attempts, dict):
        return int(attempts.get(node_id) or 0)
    return 0


def _agent_display_name_map() -> dict[str, str]:
    try:
        from core.web.services.team_service import lookup_agent_display_name_map

        return lookup_agent_display_name_map()
    except Exception:
        return {}


def _agent_display_name(agent_id: str) -> str:
    if not agent_id:
        return ""
    return str(_agent_display_name_map().get(agent_id) or "") or agent_id


class ResearchWorkflowError(Exception):
    def __init__(self, message: str, *, code: str = "workflow_error"):
        super().__init__(message)
        self.code = code


# Decision #3 of the 13-decision contract: automatic protocol revision is
# bounded at ``MAX_AUTO_REVISION_ROUNDS_DEFAULT`` rounds per lineage.  The
# frozen retry taxonomy owns the stop semantics: once the auto-revision budget
# is exhausted the only way forward is a human action family, so the parked
# run reuses the taxonomy's ``human_required`` outcome code instead of
# inventing a new one.
_AUTO_REVISION_TAXONOMY_CODE = "budget_exceeded"
_AUTO_REVISION_EVENT_TYPE = "AutoRevisionExhausted"


def _lineage_revision_rounds(
    store: WorkflowRunStore, run_id: str
) -> tuple[int, str, list[str]]:
    """Count persisted auto-revision forks along the parentRunId chain.

    The counter is never held in memory: it is derived from store data, so
    the bound survives process restarts.  ``parentRunId`` is not exclusive
    to the revision fork — evidence-remediation and checkpoint continuation
    children carry it too — so a hop only counts as one already-consumed
    revision round when the child-side run record carries the revision
    fork's exclusive ``forkDecisionId``; any other hop is walked through
    without consuming the budget.  Returns the consumed rounds, the lineage
    root run id and the forked child run ids in round order (fork evidence
    for the lineage record).
    """
    rounds = 0
    fork_run_ids: list[str] = []
    seen: set[str] = set()
    root_run_id = str(run_id or "").strip()
    current_id = root_run_id
    while current_id:
        record = store.get_run(current_id)
        if record is None:
            break
        root_run_id = current_id
        parent_id = str(record.get("parentRunId") or "").strip()
        if not parent_id or parent_id in seen:
            break
        seen.add(parent_id)
        if str(record.get("forkDecisionId") or "").strip():
            fork_run_ids.append(current_id)
            rounds += 1
        current_id = parent_id
    return rounds, root_run_id, list(reversed(fork_run_ids))


def _revision_fork_already_applied(
    store: WorkflowRunStore, parent_run_id: str, decision_id: str
) -> bool:
    """True when this exact decision already forked (idempotent replay)."""
    child_run_id = _child_run_id(parent_run_id, decision_id)
    parent = store.get_run(parent_run_id)
    if parent is None:
        return False
    return parent.get("supersededByRunId") == child_run_id and child_run_id in (
        parent.get("childRunIds") or []
    )


def _auto_revision_exhausted(
    store: WorkflowRunStore, parent: dict[str, Any], decision: dict[str, Any]
) -> bool:
    """True when a revise_protocol decision must no longer fork (decision #3)."""
    parent_run_id = str(parent["runId"])
    decision_id = str(decision.get("decisionId") or "").strip()
    if not decision_id:
        return False
    rounds, _, _ = _lineage_revision_rounds(store, parent_run_id)
    if rounds < MAX_AUTO_REVISION_ROUNDS_DEFAULT:
        return False
    return not _revision_fork_already_applied(store, parent_run_id, decision_id)


def _park_auto_revision_exhausted(
    store: WorkflowRunStore,
    completed: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Stop a revise_protocol decision at the bounded-revision ceiling.

    Instead of forking another automatic child run, the parent stays in a
    structured, recoverable stop state: ``budget_exceeded`` is the frozen
    retry-taxonomy ``human_required`` outcome code, the mandatory
    ``auto_revision_exhausted`` exception is recorded through the canonical
    evolution-lineage projection writer, and an anomaly-inbox escalation item
    is emitted with the frozen kind/severity mapping (``build_anomaly_inbox``
    derives both; no new mapping is introduced here).
    """
    parent_run_id = str(completed["runId"])
    decision_id = str(decision.get("decisionId") or "").strip()
    rounds, root_run_id, fork_run_ids = _lineage_revision_rounds(
        store, parent_run_id
    )
    now = iso(utc_now())
    team_id = str(completed.get("teamId") or "").strip()
    question_id = str(completed.get("questionId") or "").strip()
    taxonomy_entry = DEFAULT_RETRY_TAXONOMY.entry(_AUTO_REVISION_TAXONOMY_CODE)
    occurred_at = str(decision.get("decidedAt") or "").strip() or now
    round_scope = f"revision-lineage:{root_run_id}"
    candidate_id = (
        str(decision.get("selectedCandidateRef") or "").strip()
        or str(completed.get("officialCandidateRef") or "").strip()
        or root_run_id
    )

    lineage_write: dict[str, Any] = {
        "status": "skipped",
        "blockerCodes": [],
        "mandatoryExceptionReview": "",
    }
    if team_id and question_id:
        try:
            write_result = write_evolution_lineage_artifact(
                team_id=team_id,
                workflow_run_id=parent_run_id,
                node_run_id=str(decision.get("nodeRunId") or ""),
                question_id=question_id,
                round_id=round_scope,
                source_collection_run_id=root_run_id,
                events=[
                    {
                        "eventId": f"evt-evlineage-introduced-{root_run_id}",
                        "candidateId": candidate_id,
                        "kind": "introduced",
                        "roundId": round_scope,
                        "reason": "formal_run_started",
                        "occurredAt": occurred_at,
                        "actor": "system_policy",
                        "revisionAttempt": 0,
                        "evidenceRefs": [],
                    },
                    {
                        "eventId": (
                            f"evt-evlineage-{REVISION_EXHAUSTED_EXCEPTION}"
                            f"-{parent_run_id}-{decision_id}"
                        ),
                        "candidateId": candidate_id,
                        "kind": "revision_exhausted",
                        "roundId": round_scope,
                        "reason": REVISION_EXHAUSTED_EXCEPTION,
                        "occurredAt": occurred_at,
                        "actor": "system_policy",
                        "revisionAttempt": 0,
                        "evidenceRefs": [
                            {"kind": "fork_run", "ref": fork_run_id}
                            for fork_run_id in fork_run_ids
                        ],
                    },
                ],
            )
            lineage_summary = dict(
                (write_result.get("evolutionLineage") or {}).get("summary")
                or {}
            )
            lineage_write = {
                "status": str(write_result.get("status") or ""),
                "blockerCodes": list(write_result.get("blockerCodes") or []),
                "mandatoryExceptionReview": str(
                    lineage_summary.get("mandatoryExceptionReview") or ""
                ),
            }
        except Exception as exc:  # noqa: BLE001 - parking must not depend on the projection
            lineage_write = {
                "status": "failed",
                "blockerCodes": [
                    f"evolution_lineage_write_failed:{type(exc).__name__}"
                ],
                "mandatoryExceptionReview": "",
            }

    anomaly_items: list[dict[str, Any]] = []
    if team_id and question_id:
        try:
            inbox = build_anomaly_inbox(
                {
                    "teamId": team_id,
                    "questionId": question_id,
                    "problems": [
                        {
                            "code": _AUTO_REVISION_TAXONOMY_CODE,
                            "sourceKind": "formal_run",
                            "sourceId": parent_run_id,
                            "message": (
                                "automatic protocol revision reached the frozen "
                                f"{MAX_AUTO_REVISION_ROUNDS_DEFAULT}-round "
                                "ceiling; human reconciliation is required"
                            ),
                            "detectedAt": now,
                        }
                    ],
                },
                generated_at=now,
            )
            anomaly_items = [item.to_dict() for item in inbox.items]
        except Exception:  # noqa: BLE001 - parking must not depend on the projector
            anomaly_items = []

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        parked = dict(current.get("autoRevision") or {})
        if (
            parked.get("stopReason") == REVISION_EXHAUSTED_EXCEPTION
            and parked.get("decisionId") == decision_id
        ):
            return current
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId")
            or "",
            nodeId="iteration_decision",
            nodeRunId=str(decision.get("nodeRunId") or ""),
            attempt=int(decision.get("iterationAttempt") or 1),
            type=_AUTO_REVISION_EVENT_TYPE,
            summary={
                "decisionId": decision_id,
                "revisionRoundCount": rounds,
                "maxAutoRevisionRounds": MAX_AUTO_REVISION_ROUNDS_DEFAULT,
                "stopReason": REVISION_EXHAUSTED_EXCEPTION,
                "outcomeCode": taxonomy_entry.outcome_code,
                "outcomeClass": taxonomy_entry.outcome_class.value,
                "mandatoryException": REVISION_EXHAUSTED_EXCEPTION,
                "anomalyItemCount": len(anomaly_items),
            },
        )
        return {
            **current,
            "status": "blocked",
            "blockedReason": taxonomy_entry.outcome_code,
            "autoRevision": {
                "stopReason": REVISION_EXHAUSTED_EXCEPTION,
                "decisionId": decision_id,
                "revisionRoundCount": rounds,
                "maxAutoRevisionRounds": MAX_AUTO_REVISION_ROUNDS_DEFAULT,
                "lineageRootRunId": root_run_id,
                "outcomeCode": taxonomy_entry.outcome_code,
                "outcomeClass": taxonomy_entry.outcome_class.value,
                "recommendedAction": (
                    taxonomy_entry.human_actions[0].value
                    if taxonomy_entry.human_actions
                    else ""
                ),
                "humanActions": [
                    action.value for action in taxonomy_entry.human_actions
                ],
                "mandatoryException": REVISION_EXHAUSTED_EXCEPTION,
                "blockedAt": now,
                "lineageRecord": {
                    "status": str(lineage_write.get("status") or ""),
                    "blockerCodes": list(
                        lineage_write.get("blockerCodes") or []
                    ),
                    "mandatoryExceptionReview": str(
                        lineage_write.get("mandatoryExceptionReview") or ""
                    ),
                },
                "anomalyEscalation": {
                    "status": "emitted" if anomaly_items else "unavailable",
                    "items": anomaly_items,
                },
            },
            "events": [*(current.get("events") or []), event],
        }

    store.mutate_run(parent_run_id, mutation)
    return store.get_run(parent_run_id) or completed


def _definition_meta_from(
    workflow_id: str,
    definition: Any = None,
    identity: Any = None,
) -> tuple[Any, Any]:
    """Validate the workflowId and return (definition, identity) for creation.

    Callers that must keep ONE rollout-mode reading across a whole creation
    transaction (e.g. ``create_run``) pass the already-resolved
    ``definition``/``identity`` through; every independent call resolves the
    current rollout mode exactly once here.
    """
    if workflow_id != CHALLENGE_CUP_WORKFLOW_ID:
        raise ResearchWorkflowError(f"Unknown workflowId: {workflow_id}", code="unknown_workflow")
    if definition is None or identity is None:
        # Rollout-mode aware: off/shadow pin the 2.1.0 default, on pins the
        # registered main-flow 3.0.0 definition (see knowledge_rollout).
        from .knowledge_rollout import creation_workflow_definition

        definition, identity = creation_workflow_definition()
    return definition, identity


class ResearchWorkflowRuntimeService:
    def __init__(
        self,
        *,
        run_store: WorkflowRunStore | None = None,
        checkpoint_path: str | None = None,
        durable_index: DurableWorkflowIndex | None = None,
        binding_config_store: WorkflowBindingConfigStore | None = None,
    ):
        self._store = run_store or WorkflowRunStore()
        self._checkpoint_path = str(checkpoint_path) if checkpoint_path else str(default_checkpoint_path())
        index_root = Path(self._store.root) / "_index"
        self._index = durable_index or DurableWorkflowIndex(index_root)
        self._lock = threading.RLock()
        self._bindings = AgentBindingLayers()
        # Per-(workflowId, teamId) controlled config; team roles are the
        # fallback default source resolved at run creation (never random).
        self._binding_config = binding_config_store or WorkflowBindingConfigStore(self._store.root)
        # Command-level idempotency is also durable via index keys with prefix.
        self._command_memory: dict[str, str] = {}  # key -> run_id snapshot path only for process; reloaded from index
        self._last_expired_bundle_reconcile_at: float = 0.0

    def get_definition(self, workflow_id: str = CHALLENGE_CUP_WORKFLOW_ID) -> dict[str, Any]:
        definition, identity = _definition_meta_from(workflow_id)
        return {
            "workflowId": definition.workflowId,
            "workflowVersionId": identity.workflowVersionId,
            "definition": definition.to_dict(),
        }

    def list_runs(self, workflow_id: str = CHALLENGE_CUP_WORKFLOW_ID, *, team_id: str = "") -> dict[str, Any]:
        runs = self._store.list_runs(workflow_id)
        if str(team_id or "").strip():
            runs = [r for r in runs if str(r.get("teamId") or "") == str(team_id).strip()]
        return {"workflowId": workflow_id, "runs": runs}

    def get_question_launch_options(
        self,
        workflow_id: str = CHALLENGE_CUP_WORKFLOW_ID,
        *,
        team_id: str,
    ) -> dict[str, Any]:
        self.get_definition(workflow_id)
        try:
            from core.web.services.team_service import (
                TeamNotFoundError,
                assert_team_exists,
            )

            try:
                scoped_team_id = assert_team_exists(team_id)
            except TeamNotFoundError as exc:
                raise ResearchWorkflowError(str(exc), code="unknown_team") from exc
            options = list_catalog_question_launch_options(scoped_team_id)
            options["experiments"] = []
            try:
                from .formal_read_runtime import (
                    FormalReadRuntimeUnavailable,
                    get_query_service,
                )
                from .formal_write_runtime import WorkflowMigrationRequired
                from .query_service import WorkflowQueryError

                runs = get_query_service().list_runs(
                    team_id=scoped_team_id,
                    workflow_id=workflow_id,
                )["runs"]
                options["questions"] = attach_question_run_checkpoints(
                    options["questions"],
                    runs,
                )
            except (FormalReadRuntimeUnavailable, WorkflowMigrationRequired, WorkflowQueryError):
                pass
            return {"workflowId": workflow_id, **options}
        except QuestionLaunchError as exc:
            raise ResearchWorkflowError(str(exc), code=exc.code) from exc

    def activate_experiment_campaign(
        self,
        workflow_id: str = CHALLENGE_CUP_WORKFLOW_ID,
        *,
        team_id: str,
        experiment_id: str,
        confirmed: bool,
    ) -> dict[str, Any]:
        self.get_definition(workflow_id)
        try:
            return activate_experiment_campaign(
                team_id,
                experiment_id=experiment_id,
                confirmed=confirmed,
            )
        except QuestionLaunchError as exc:
            raise ResearchWorkflowError(str(exc), code=exc.code) from exc

    def create_question_run(
        self,
        workflow_id: str = CHALLENGE_CUP_WORKFLOW_ID,
        *,
        team_id: str,
        question_id: str,
        safety_limits: Mapping[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.get_definition(workflow_id)
        try:
            run_input = build_question_run_input(
                team_id,
                question_id=question_id,
                safety_limits=safety_limits,
            )
        except QuestionLaunchError as exc:
            raise ResearchWorkflowError(str(exc), code=exc.code) from exc
        return self.create_run(
            workflow_id,
            run_input=run_input,
            idempotency_key=idempotency_key,
        )

    def _effective_binding_layers(self, workflow_id: str, team_id: str) -> AgentBindingLayers:
        """Controlled config (per workflow+team) merged over team-role defaults."""
        config = self._binding_config.load(workflow_id, team_id)
        return effective_binding_layers(team_id, config)

    def get_effective_agent_bindings(
        self,
        workflow_id: str = CHALLENGE_CUP_WORKFLOW_ID,
        *,
        team_id: str = "",
    ) -> dict[str, Any]:
        """Current-configuration view per agent node (never touches run history)."""
        meta = self.get_definition(workflow_id)
        definition = build_challenge_cup_workflow_definition()
        layers = self._effective_binding_layers(workflow_id, team_id)
        names = _agent_display_name_map()
        bindings = []
        for node in definition.nodes:
            if node.actorKind is not ActorKind.AGENT:
                continue
            agent_id, resolved_from = resolve_effective_agent_id(node, layers)
            bindings.append(
                {
                    "nodeId": node.nodeId,
                    "roleKey": node.primaryRoleKey,
                    "agentId": agent_id,
                    "displayName": (str(names.get(agent_id) or "") or agent_id) if agent_id else "",
                    "resolvedFrom": resolved_from,
                }
            )
        return {
            "workflowId": workflow_id,
            "workflowVersionId": meta["workflowVersionId"],
            "teamId": str(team_id or "").strip(),
            "bindings": bindings,
        }

    def put_agent_binding_config(
        self,
        workflow_id: str,
        payload: dict[str, Any],
        *,
        team_id: str = "",
    ) -> dict[str, Any]:
        """Controlled write of binding config layers (per workflow+team scope).

        Only the keys present in the payload are replaced; missing layers keep
        their persisted values. Validated against the workflow definition
        before persisting (unknown role/stage/node rejected).
        """
        if workflow_id != CHALLENGE_CUP_WORKFLOW_ID:
            raise ResearchWorkflowError(f"Unknown workflowId: {workflow_id}", code="unknown_workflow")
        current = self._binding_config.load(workflow_id, team_id)
        team_scoped = bool(str(team_id or "").strip())
        try:
            if not isinstance(payload, dict):
                self._binding_config.validate_payload(payload)
            raw_update = {
                "workflowDefaults": (
                    payload.get("workflowDefaults") or {}
                    if "workflowDefaults" in payload
                    else current.workflowDefaults
                ),
                "stageOverrides": (
                    payload.get("stageOverrides") or {}
                    if "stageOverrides" in payload
                    else current.stageOverrides
                ),
                "nodeOverrides": (
                    payload.get("nodeOverrides") or {}
                    if "nodeOverrides" in payload
                    else current.nodeOverrides
                ),
            }
            self._binding_config.validate_payload(raw_update)
        except BindingConfigValidationError as exc:
            raise ResearchWorkflowError(str(exc), code=exc.code) from exc
        # Replace-whole-layer semantics: a layer present in the payload fully
        # replaces its persisted value (an empty dict clears it); absent
        # layers keep their persisted values.
        update = {
            "workflowDefaults": (
                {}
                if team_scoped
                else {str(k): v for k, v in raw_update["workflowDefaults"].items()}
            ),
            "stageOverrides": {
                str(k): {str(rk): av for rk, av in v.items()}
                for k, v in raw_update["stageOverrides"].items()
            },
            "nodeOverrides": {
                str(k): v for k, v in raw_update["nodeOverrides"].items()
            },
        }
        saved = self._binding_config.save(
            workflow_id,
            team_id,
            AgentBindingLayers(
                workflowDefaults=update["workflowDefaults"],
                stageOverrides=update["stageOverrides"],
                nodeOverrides=update["nodeOverrides"],
            ),
        )
        effective = effective_binding_layers(team_id, AgentBindingLayers(
            workflowDefaults=saved["workflowDefaults"],
            stageOverrides=saved["stageOverrides"],
            nodeOverrides=saved["nodeOverrides"],
        ))
        return {
            "workflowId": workflow_id,
            "teamId": saved["teamId"],
            "workflowDefaults": effective.workflowDefaults,
            "stageOverrides": saved["stageOverrides"],
            "nodeOverrides": saved["nodeOverrides"],
            "updatedAt": saved["updatedAt"],
        }

    def _new_human_task(
        self,
        *,
        run_id: str,
        node_id: str,
        checkpoint_id: str = "",
        node_run_id: str = "",
    ) -> dict[str, Any]:
        return {
            "taskId": f"ht-{uuid.uuid4().hex[:10]}",
            "runId": run_id,
            "nodeId": node_id,
            "nodeRunId": node_run_id or f"nr-{node_id}",
            "checkpointId": checkpoint_id,
            "status": "pending",
            "prompt": f"Resolve gate at {node_id}",
            "createdAt": _utc_now(),
            "resolvedAt": "",
            "resolvedBy": "",
        }

    def _append_auto_handoffs(
        self,
        *,
        run_id: str,
        workflow_id: str,
        workflow_version_id: str,
        completed: list[str],
        artifacts: dict[str, Any],
        existing_edge_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Append auto handoffs using definition edgeId identity (no human dupes)."""
        from core.research.workflow.definition_registry import (
            resolve_definition_for_run_record,
        )

        run_record = self._store.get_run(run_id)
        if run_record is None:
            raise ResearchWorkflowError(
                f"Run not found: {run_id}",
                code="run_not_found",
            )
        definition = resolve_definition_for_run_record(run_record)
        created = build_auto_handoffs_for_completed(
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
            completed=completed,
            artifacts=artifacts,
            existing_edge_ids=existing_edge_ids,
            definition=definition,
        )
        for record in created:
            self._store.append_handoff(run_id, record)
        return created

    def create_run(
        self,
        workflow_id: str = CHALLENGE_CUP_WORKFLOW_ID,
        *,
        run_input: Mapping[str, Any],
        binding_layers: AgentBindingLayers | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            # ONE rollout-mode reading per creation: the (definition, identity)
            # pair resolved here is threaded through every downstream use
            # (binding snapshots, frozen input snapshot, initial checkpoint,
            # run record).  A mode flip between two independent reads could
            # otherwise produce a workflowVersionId that disagrees with the
            # checkpoint/structureHash inside the same run.
            creation_definition, creation_identity = _definition_meta_from(workflow_id)
            create_input_fingerprints = _create_request_fingerprints(run_input)
            create_input_fingerprint = create_input_fingerprints[0]
            run_id = run_id_for_create(workflow_id, idempotency_key)
            create_index_key = f"create:{idempotency_key}" if idempotency_key else ""
            indexed_run_id = self._index.get_run_id(create_index_key) if create_index_key else None
            if indexed_run_id and indexed_run_id != run_id:
                raise ResearchWorkflowError(
                    "idempotency index points to a different run",
                    code="idempotency_index_conflict",
                )
            existing = self._store.get_run(run_id)
            if indexed_run_id and existing is None:
                raise ResearchWorkflowError(
                    "idempotency index points to a missing run",
                    code="idempotency_index_missing_run",
                )
            if existing:
                prior_fingerprint = str(existing.get("createInputFingerprint") or "")
                if prior_fingerprint and prior_fingerprint not in create_input_fingerprints:
                    raise ResearchWorkflowError(
                        "idempotencyKey was already used with different run input",
                        code="idempotency_conflict",
                    )
                return existing
            thread_id = f"thread-{run_id}"
            team_id = str(run_input.get("teamId") or "").strip()
            # Team members always provide workflow defaults. Explicit and
            # service-level layers may add stage/node overrides only.
            service_config = self._bindings
            has_service_config = bool(
                service_config.workflowDefaults
                or service_config.stageOverrides
                or service_config.nodeOverrides
            )
            selected_layers = (
                binding_layers
                or (service_config if has_service_config else None)
                or self._binding_config.load(workflow_id, team_id)
            )
            layers = effective_binding_layers(team_id, selected_layers)
            snapshots = build_run_binding_snapshots(
                run_id=run_id,
                workflow_version_id=creation_identity.workflowVersionId,
                layers=layers,
                captured_at=_utc_now(),
            )
            binding_payloads = [binding_snapshot_payload(snapshot) for snapshot in snapshots]
            created_at = _utc_now()
            try:
                input_snapshot = freeze_run_input(
                    run_input,
                    workflow_version_id=creation_identity.workflowVersionId,
                    binding_snapshots=binding_payloads,
                    created_at=created_at,
                )
            except ContractValidationError as exc:
                raise ResearchWorkflowError(str(exc), code="invalid_run_input") from exc

            # The pinned definition must be the same object identity used for
            # the initial checkpoint and the frozen run record — the exact
            # pair resolved at the top of this method (single mode reading).
            definition = creation_definition
            checkpoint_id = prepare_initial_checkpoint(
                self._checkpoint_path,
                thread_id,
                definition=definition,
            )
            record = build_initial_run_record(
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_version_id=creation_identity.workflowVersionId,
                structure_hash=definition.structureHash,
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                input_snapshot=input_snapshot,
                binding_snapshots=binding_payloads,
                idempotency_key=idempotency_key,
                create_input_fingerprint=create_input_fingerprint,
                created_at=created_at,
                definition=definition,
            )
            self._store.create_run(record)
            if create_index_key:
                self._index.put_run_id(create_index_key, run_id)
            return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        record = self._store.get_run(run_id)
        if record is None:
            raise ResearchWorkflowError(f"Unknown runId: {run_id}", code="unknown_run")
        if has_reconcilable_external_agent_tasks(record):
            with self._lock:
                latest = self._store.get_run(run_id)
                if latest is None:
                    raise ResearchWorkflowError(
                        f"Unknown runId: {run_id}",
                        code="unknown_run",
                    )
                record = reconcile_external_agent_tasks(
                    self._store,
                    checkpoint_path=self._checkpoint_path,
                    record=latest,
                )
        return record

    def authorize_run_access(
        self,
        run_id: str,
        *,
        team_id: str,
        expected_run_version: int | None = None,
    ) -> dict[str, Any]:
        """Validate the only public Run scope and optional write version."""
        try:
            return require_run_access(
                self.get_run(run_id),
                team_id=team_id,
                expected_run_version=expected_run_version,
            )
        except RunAccessError as exc:
            raise ResearchWorkflowError(str(exc), code=exc.code) from exc

    def get_canvas_projection(self, run_id: str | None = None) -> dict[str, Any]:
        if not run_id:
            return build_canvas_projection()
        return build_run_canvas_projection(self.get_run(run_id))

    def get_node_detail(self, run_id: str, node_id: str) -> dict[str, Any]:
        record = self.get_run(run_id)
        from core.research.workflow.definition_registry import (
            resolve_definition_for_run_record,
        )

        definition = resolve_definition_for_run_record(
            record,
            expected_node_ids=[node_id],
        )
        node = next((n for n in definition.nodes if n.nodeId == node_id), None)
        if node is None:
            raise ResearchWorkflowError(f"Unknown nodeId: {node_id}", code="unknown_node")
        snapshots = {s["nodeId"]: s for s in record.get("bindingSnapshots") or []}
        snap = snapshots.get(node_id) or {}
        bridge = SessionBindingBridge(self._store)
        session_binding = self._store.get_session_binding(run_id, node_id)
        chat_href, degraded = bridge.deep_link_for(record, node_id)
        if node.actorKind is not ActorKind.AGENT:
            degraded = False
            chat_href = None
        session_projection = project_node_scoped_sessions(
            record,
            node_id=node_id,
            session_binding=session_binding,
        )
        display_name = ""
        if snap.get("agentId"):
            display_name = _agent_display_name(str(snap["agentId"]))
        research_ledger = (
            self.get_research_ledger(run_id) if node_id == "result_package" else None
        )
        commands = node_command_capabilities(
            record,
            node_id,
            research_ledger=research_ledger,
        )
        if node.actorKind is ActorKind.AGENT:
            commands.append(
                {
                    "command": "open_session",
                    "available": bool(chat_href) and not degraded,
                    "reason": "" if chat_href and not degraded else "会话锚点尚未完整绑定",
                }
            )
        return {
            "runId": run_id,
            "teamId": record["teamId"],
            "runVersion": record["runVersion"],
            "nodeId": node_id,
            "actorKind": node.actorKind.value,
            "primaryRoleKey": node.primaryRoleKey,
            "label": node.label,
            "bindingSnapshot": {**snap, "displayName": display_name},
            "sessionBinding": session_binding,
            "chatDeepLink": chat_href,
            "sessionAnchorDegraded": degraded,
            "rootSession": session_projection["rootSession"],
            "scopedSessions": session_projection["scopedSessions"],
            "runtimeCurrent": node_id in (record.get("runtimeCurrentNodeIds") or []),
            "status": record.get("status"),
            "nodeAttempt": _node_attempt(record, node_id),
            "blockedReason": str(record.get("blockedReason") or (record.get("langGraph") or {}).get("blockedReason") or ""),
            "artifacts": (record.get("langGraph") or {}).get("artifacts") or {},
            "commands": commands,
            **project_node_operations(record, node_id),
        }

    def list_handoffs(self, run_id: str) -> dict[str, Any]:
        return list_handoffs(self.get_run(run_id))

    def get_handoff_detail(
        self,
        run_id: str,
        handoff_id: str,
    ) -> dict[str, Any]:
        try:
            return get_handoff_detail(self.get_run(run_id), handoff_id)
        except HandoffQueryError as exc:
            raise ResearchWorkflowError(str(exc), code=exc.code) from exc

    def get_research_ledger(self, run_id: str) -> dict[str, Any]:
        record = self.get_run(run_id)
        try:
            from core.web.services import (
                research_evidence_service,
                team_knowledge_service,
            )
            from core.web.services.team_workflow.experiment_api.plan import (
                get_experiment_planning_status,
            )

            claim_evidence = research_evidence_service.list_claim_evidence(
                str(record["teamId"])
            )
            team_knowledge = team_knowledge_service.list_team_knowledge_bases(
                str(record["teamId"]),
                internal=True,
            )
            experiment_planning = get_experiment_planning_status(
                str(record["teamId"])
            )
        except Exception as exc:
            raise ResearchWorkflowError(
                f"ResearchLedger canonical source failed: {exc}",
                code="research_ledger_source_failed",
            ) from exc
        return project_research_ledger(
            record,
            claim_evidence=claim_evidence,
            team_knowledge=team_knowledge,
            experiment_planning=experiment_planning,
        )

    def get_budget(self, run_id: str) -> dict[str, Any]:
        return project_budget(self.get_run(run_id))

    def get_hypotheses(self, run_id: str) -> dict[str, Any]:
        return project_hypotheses(self.get_run(run_id))

    def get_experiment_campaigns(self, run_id: str) -> dict[str, Any]:
        return project_experiment_campaigns(self.get_run(run_id))

    def get_evaluation(self, run_id: str) -> dict[str, Any]:
        return project_evaluation(self.get_run(run_id))

    def cancel_task_bundle(
        self,
        run_id: str,
        bundle_id: str,
        *,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with self._lock:
            try:
                return cancel_task_bundle(
                    self._store,
                    run_id=run_id,
                    bundle_id=bundle_id,
                    reason=reason,
                    idempotency_key=idempotency_key,
                )
            except TaskBundleError as exc:
                raise ResearchWorkflowError(str(exc), code=exc.code) from exc

    def reconcile_task_bundles(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                return reconcile_expired_task_bundles(
                    self._store,
                    run_id=run_id,
                )
            except TaskBundleError as exc:
                raise ResearchWorkflowError(str(exc), code=exc.code) from exc

    def reconcile_all_expired_task_bundles(
        self,
        *,
        min_interval_seconds: float = _EXPIRED_TASK_BUNDLE_RECONCILE_MIN_INTERVAL_S,
    ) -> list[dict[str, Any]]:
        """Enforce ``deadlineSeconds`` across every run with active bundles.

        ``reconcile_task_bundles`` had no periodic caller, so bundle deadlines
        never fired. The resident worker tick (WorkflowOutboxPump ->
        ``WorkflowRuntime.run_workers_once``) now calls this best-effort. A
        per-service throttle bounds the enumeration cost; per-run errors are
        logged and skipped so one bad run never blocks the others.
        """
        now_monotonic = time.monotonic()
        if (
            float(min_interval_seconds) > 0
            and now_monotonic - self._last_expired_bundle_reconcile_at
            < float(min_interval_seconds)
        ):
            return []
        self._last_expired_bundle_reconcile_at = now_monotonic
        now = iso(utc_now())
        reconciled: list[dict[str, Any]] = []
        for record in self._store.list_runs():
            if str(record.get("status") or "") in _FILE_STORE_TERMINAL_RUN_STATUSES:
                continue
            has_active_bundle = any(
                str(bundle.get("status") or "") in _ACTIVE_TASK_BUNDLE_STATUSES
                and any(
                    str(subtask.get("status") or "") in _ACTIVE_TASK_BUNDLE_STATUSES
                    and str(subtask.get("deadlineAt") or "") < now
                    for subtask in list(bundle.get("subtasks") or [])
                    if isinstance(subtask, dict)
                )
                for bundle in list(record.get("taskBundles") or [])
                if isinstance(bundle, dict)
            )
            if not has_active_bundle:
                continue
            run_id = str(record.get("runId") or "")
            if not run_id:
                continue
            try:
                reconciled.append(self.reconcile_task_bundles(run_id))
            except ResearchWorkflowError as exc:
                logger.warning(
                    "task bundle deadline reconcile skipped for run %s: %s",
                    run_id,
                    exc,
                )
        return reconciled

    def resolve_human_task(
        self,
        run_id: str,
        task_id: str,
        *,
        decision: str,
        resolved_by: str = "",
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_privileged_operator(command="resolve_human_task")
        with self._lock:
            try:
                return resolve_human_task_transition(
                    self._store,
                    self._checkpoint_path,
                    run_id=run_id,
                    task_id=task_id,
                    decision=decision,
                    resolved_by=resolved_by,
                    idempotency_key=idempotency_key,
                )
            except HumanTaskResolutionError as exc:
                raise ResearchWorkflowError(str(exc), code=exc.code) from exc

    @staticmethod
    def _require_privileged_operator(*, command: str) -> None:
        from .operator_authorization import require_privileged_server_operator

        try:
            require_privileged_server_operator(command=command)
        except PermissionError as exc:
            raise ResearchWorkflowError("command_forbidden", code="command_forbidden") from exc

    def apply_command(
        self,
        run_id: str,
        command: str,
        *,
        idempotency_key: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        durable_key = f"cmd:{run_id}:{command}:{idempotency_key}" if idempotency_key else ""
        if durable_key:
            existing_id = self._index.get_run_id(durable_key)
            if existing_id:
                # Stored value is a marker; return current run after prior command.
                return self.get_run(run_id)

        payload = payload or {}
        if command == "cancel":
            self._require_privileged_operator(command="cancel_run")
            current = self.get_run(run_id)
            if current is None:
                raise ResearchWorkflowError(run_id, code="run_not_found")
            _require_non_terminal_run(current, command="cancel")
            record = self._store.update_run(run_id, {"status": "cancelled", "runtimeCurrentNodeIds": []})
        elif command == "retry_node":
            current = self.get_run(run_id)
            if current is None:
                raise ResearchWorkflowError(run_id, code="run_not_found")
            _require_non_terminal_run(current, command="retry_node")
            attempts = int(current.get("retryCount") or 0) + 1
            record = self._store.update_run(run_id, {"retryCount": attempts, "status": "queued"})
        elif command == "rebind_node":
            self._require_privileged_operator(command="rebind_node")
            node_id = str(payload.get("nodeId") or "")
            agent_id = str(payload.get("agentId") or "").strip()
            if not node_id or not agent_id:
                raise ResearchWorkflowError("rebind_node requires nodeId and agentId", code="invalid_rebind")
            record = self.get_run(run_id)
            snaps = list(record.get("bindingSnapshots") or [])
            history = list(record.get("bindingHistory") or [])
            attempt = int(record.get("rebindAttempt") or 0) + 1
            for snap in snaps:
                if snap.get("nodeId") == node_id:
                    history.append({**snap, "supersededAt": _utc_now()})
            new_snap = {
                "snapshotId": f"snap:{run_id}:{node_id}:rebind-{uuid.uuid4().hex[:6]}",
                "nodeId": node_id,
                "agentId": agent_id,
                "roleKey": next((s.get("roleKey") for s in snaps if s.get("nodeId") == node_id), ""),
                "actorKind": "agent",
                "resolvedFrom": "rebind",
                "capturedAt": _utc_now(),
                "nodeAttempt": attempt,
            }
            snaps = [s for s in snaps if s.get("nodeId") != node_id] + [new_snap]
            record = self._store.update_run(
                run_id,
                {
                    "bindingSnapshots": snaps,
                    "bindingHistory": history,
                    "rebindAttempt": attempt,
                },
            )
            self._store.append_event(
                run_id,
                {
                    "runId": run_id,
                    "nodeId": node_id,
                    "type": "binding.rebind_node",
                    "summary": {"agentId": agent_id, "nodeAttempt": attempt},
                },
            )
            record = self.get_run(run_id)
        else:
            raise ResearchWorkflowError(f"Unknown command: {command}", code="unknown_command")
        if durable_key:
            self._index.put_run_id(durable_key, run_id)
        return record

    def put_session_binding(self, run_id: str, node_id: str, binding: dict[str, Any]) -> dict[str, Any]:
        record = self.get_run(run_id)
        try:
            bridge = SessionBindingBridge(self._store)
            record_binding = bridge.put(record, node_id, binding)
        except SessionBindingError as exc:
            raise ResearchWorkflowError(str(exc), code=exc.code) from exc
        self._store.append_event(
            run_id,
            {
                "runId": run_id,
                "nodeId": node_id,
                "type": "session_binding.bound",
                "summary": {
                    "bindingId": record_binding["bindingId"],
                    "agentId": record_binding["agentId"],
                    "sessionId": record_binding["sessionId"],
                    "taskId": record_binding["taskId"],
                    "turnId": record_binding["turnId"],
                    "status": record_binding["status"],
                    "supersedesBindingId": record_binding.get("supersedesBindingId") or "",
                },
            },
        )
        return record_binding

    def apply_node_command(
        self,
        run_id: str,
        node_id: str,
        command: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Node-level command execution through the real backend adapter."""
        with self._lock:
            record = self.get_run(run_id)
            try:
                if command == "start_execution":
                    return start_node_execution(
                        self._store,
                        run_id=run_id,
                        node_id=node_id,
                        payload=payload or {},
                    )
                if command == "heartbeat_execution":
                    return heartbeat_node_execution(
                        self._store,
                        run_id=run_id,
                        node_id=node_id,
                        payload=payload or {},
                    )
                if command == "complete_execution":
                    completed = complete_node_execution(
                        self._store,
                        checkpoint_path=self._checkpoint_path,
                        run_id=run_id,
                        node_id=node_id,
                        payload=payload or {},
                    )
                    if node_id == "iteration_decision":
                        decision = next(
                            (
                                dict(item)
                                for item in reversed(
                                    completed.get("iterationDecisions") or []
                                )
                                if isinstance(item, dict)
                            ),
                            None,
                        )
                        if (
                            decision is not None
                            and decision.get("decisionKind") == "revise_protocol"
                            and _auto_revision_exhausted(
                                self._store, completed, decision
                            )
                        ):
                            # Decision #3: the lineage already consumed its
                            # bounded auto-revision rounds; park the parent
                            # instead of forking another automatic child run.
                            return _park_auto_revision_exhausted(
                                self._store, completed, decision
                            )
                        if (
                            decision is not None
                            and decision.get("decisionKind") == "revise_protocol"
                        ):
                            fork_iteration_revision(
                                self._store,
                                self._checkpoint_path,
                                parent=completed,
                                decision=decision,
                            )
                            return self.get_run(run_id)
                    return completed
                if command == "reconcile_execution":
                    return reconcile_expired_execution(
                        self._store,
                        run_id=run_id,
                        node_id=node_id,
                        payload=payload or {},
                    )
                if command == "retry_execution":
                    latest_attempt = dict(latest_node_run(record, node_id))
                    record = settle_failed_agent_task_budget(
                        self._store,
                        record=record,
                        node_run=latest_attempt,
                    )
                    return retry_node_execution(
                        self._store,
                        run_id=run_id,
                        node_id=node_id,
                        payload=payload or {},
                    )
                if command == "fork_evidence_remediation":
                    if node_id != "source_extraction":
                        raise EvidenceRemediationForkError(
                            "evidence remediation is only valid for source_extraction",
                            code="evidence_remediation_not_available",
                        )
                    return fork_evidence_remediation(
                        self._store,
                        self._checkpoint_path,
                        parent=record,
                        payload=payload or {},
                    )
            except (
                EvidenceRemediationForkError,
                FailedAgentBudgetError,
                NodeExecutionError,
            ) as exc:
                raise ResearchWorkflowError(str(exc), code=exc.code) from exc
            if command == "rebind_node":
                # Controlled rebind keeps snapshot lineage (apply_command).
                return self.apply_command(
                    run_id,
                    "rebind_node",
                    payload={**(payload or {}), "nodeId": node_id},
                )
            try:
                research_ledger = (
                    self.get_research_ledger(run_id)
                    if command == "build_package"
                    else None
                )
                result = apply_node_command(
                    store=self._store,
                    checkpoint_path=self._checkpoint_path,
                    record=record,
                    node_id=node_id,
                    command=command,
                    payload=payload,
                    research_ledger=research_ledger,
                )
            except NodeCommandUnavailable as exc:
                raise ResearchWorkflowError(str(exc), code=exc.code) from exc
            except NodeCommandError as exc:
                raise ResearchWorkflowError(str(exc), code=exc.code) from exc
            self._store.append_event(
                run_id,
                {
                    "runId": run_id,
                    "nodeId": node_id,
                    "type": "node.command.applied",
                    "summary": {
                        "command": command,
                        "result": {k: v for k, v in result.items() if k != "artifacts"},
                    },
                },
            )
            return result

    def list_events(self, run_id: str, *, after_sequence: int = 0) -> dict[str, Any]:
        record = self.get_run(run_id)
        events = [e for e in (record.get("events") or []) if int(e.get("sequence") or 0) > after_sequence]
        return {
            "runId": run_id,
            "teamId": record["teamId"],
            "runVersion": record["runVersion"],
            "events": events,
            "snapshot": {
                "status": record.get("status"),
                "runtimeCurrentNodeIds": record.get("runtimeCurrentNodeIds") or [],
                "bindingSnapshots": record.get("bindingSnapshots") or [],
                "handoffs": record.get("handoffs") or [],
                "humanTasks": record.get("humanTasks") or [],
                "langGraph": record.get("langGraph") or {},
            },
        }

    def set_binding_layers(self, layers: AgentBindingLayers) -> None:
        self._bindings = layers


_SERVICE: ResearchWorkflowRuntimeService | None = None
_SERVICE_LOCK = threading.Lock()


def peek_research_workflow_runtime_service() -> ResearchWorkflowRuntimeService | None:
    """Return the live singleton without creating one.

    Background tick wiring uses this so test runtimes and processes that never
    built the domain runtime stay inert instead of materializing a production
    store as a side effect.
    """
    with _SERVICE_LOCK:
        return _SERVICE


def get_research_workflow_runtime_service() -> ResearchWorkflowRuntimeService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = ResearchWorkflowRuntimeService()
        return _SERVICE


def reset_research_workflow_runtime_service_for_tests(
    *,
    run_store: WorkflowRunStore | None = None,
    checkpoint_path: str | None = None,
    durable_index: DurableWorkflowIndex | None = None,
) -> ResearchWorkflowRuntimeService:
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = ResearchWorkflowRuntimeService(
            run_store=run_store,
            checkpoint_path=checkpoint_path,
            durable_index=durable_index,
        )
        return _SERVICE
