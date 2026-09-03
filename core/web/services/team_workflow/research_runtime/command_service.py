"""WorkflowCommandService — the single write entry (spec 7.1/7.2).

Synchronous acceptance flow:
  1. teamId non-empty and exactly equal to the run's teamId;
  2. canonical requestHash;
  3. idempotency lookup FIRST: same hash replays the original receipt,
     different hash raises idempotency_conflict;
  4. expectedRunVersion check;
  5. NodeReadiness recomputed (never cached) for attempt-creating commands;
  6. not ready -> NodeNotReadyError, zero side effects;
  7. ready -> one BEGIN IMMEDIATE transaction: conditional version bump,
     accepted command, NodeAttempt(starting), graph_dispatch outbox,
     command_accepted + node_starting events;
  8. commit -> CommandReceipt; after-commit wakes the graph worker.

No network / model / agent / budget / domain writes happen inside the
transaction.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from core.research.workflow.contracts import (
    CommandReceipt,
    CommandRequest,
    WorkflowCommandKind,
)
from core.research.workflow.ledger import (
    CommandNotAllowedError,
    IdempotencyConflictError,
    RunVersionConflictError,
    WorkflowLedgerStore,
)
from core.research.workflow.transitions import (
    HumanTaskStatus,
    NodeAttemptStatus,
    RunStatus,
    require_human_task_transition,
    require_run_transition,
)
from core.research.workflow.models import WorkflowStageId
from core.web.services.team_workflow.research_runtime.readiness import (
    NodeReadinessService,
)
from core.web.services.team_workflow.research_runtime.readiness.common import (
    DomainReadinessContext,
)

from .human_acceptance_artifact import (
    KnowledgeAcceptanceArtifactError,
    PreparedHumanAcceptanceArtifact,
    persist_prepared_human_acceptance_artifact,
    prepare_command_human_acceptance_artifact,
)
from .ids import new_id
from .reconcile_authority import plan_ledger_authority

logger = logging.getLogger(__name__)

# chat_turn snapshot statuses that still represent an in-flight (or possibly
# in-flight) turn; anything else is already terminal and must not be touched
# again by cancel_run turn closure.
_CHAT_TURN_OPEN_STATUSES = frozenset({"", "queued", "running", "stopping", "paused"})


def formal_node_order(run: Any) -> tuple[str, ...]:
    """Canonical node order from this run's pinned definition."""
    definition = _definition_for_ledger_run(run)
    return tuple(node.nodeId for node in definition.nodes)

_ARTIFACT_HUMAN_GATES = frozenset(
    {
        "gate:knowledge_handoff",
        "gate:protocol_freeze",
        "gate:smoke_gate",
    }
)


class WorkflowCommandError(RuntimeError):
    """Base for typed command failures."""


class RunNotFoundError(WorkflowCommandError):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} not found")
        self.run_id = run_id


class TeamScopeMismatchError(WorkflowCommandError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class CommandForbiddenError(WorkflowCommandError):
    def __init__(self, detail: str = "operator lacks permission for this command") -> None:
        super().__init__(detail)
        self.detail = detail


class NodeNotReadyError(WorkflowCommandError):
    def __init__(self, readiness: Any, run_version: int) -> None:
        super().__init__("node_not_ready")
        self.readiness = readiness
        self.run_version = run_version


class InvalidHumanTaskStateError(WorkflowCommandError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class HumanTaskNotFoundError(WorkflowCommandError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"human task {task_id} not found")
        self.task_id = task_id


class KnowledgeCommandError(WorkflowCommandError):
    """Typed knowledge sideflow command failure; ``code`` is stable for HTTP
    mapping (mirrors KnowledgeSideflowError codes)."""

    def __init__(self, detail: str, *, code: str = "invalid_request") -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class StageOneCommandError(WorkflowCommandError):
    """Typed stage-one closeout command failure; ``code`` is stable for HTTP
    mapping (mirrors the fail-closed stage-one validator codes)."""

    def __init__(self, detail: str, *, code: str = "stage_one_command_failed") -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class DefinitionResolutionDegradedError(WorkflowCommandError):
    """A mutation was attempted on a run whose pinned definition could not be
    honored (plan §6.3): the stale-mutation path is fail-closed instead of
    executing against a substituted graph. ``code`` maps to HTTP 409."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.code = "definition_resolution_degraded"
        self.detail = detail


def _positive_budget_limit(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WorkflowCommandError(
            f"extend_budget requires a positive integer for budget limit {field}"
        )
    return int(value)


def _merged_budget_extension(
    current_limits: Mapping[str, Any],
    raw_extension: object,
) -> dict[str, Any]:
    if not isinstance(raw_extension, Mapping) or not raw_extension:
        raise WorkflowCommandError(
            "extend_budget requires a concrete non-empty budget limits extension"
        )
    allowed = {"stageTokens", "toolCalls", "wallClockSeconds", "maxRetries"}
    unknown = set(raw_extension) - allowed
    if unknown:
        raise WorkflowCommandError(
            "extend_budget contains unknown budget limits: "
            + ", ".join(sorted(str(item) for item in unknown))
        )

    merged = dict(current_limits)
    scalar_legacy_keys = {
        "toolCalls": "maxToolCalls",
        "wallClockSeconds": "maxSeconds",
        "maxRetries": "autoRetries",
    }
    for key in ("toolCalls", "wallClockSeconds", "maxRetries"):
        if key not in raw_extension:
            continue
        proposed = _positive_budget_limit(raw_extension[key], field=key)
        prior = current_limits.get(key, current_limits.get(scalar_legacy_keys[key], 0))
        prior_value = int(prior) if isinstance(prior, int) and not isinstance(prior, bool) else 0
        if proposed <= prior_value:
            raise WorkflowCommandError(
                f"extend_budget budget limit {key} must increase above {prior_value}"
            )
        merged[key] = proposed

    if "stageTokens" in raw_extension:
        proposed_stages = raw_extension["stageTokens"]
        if not isinstance(proposed_stages, Mapping) or not proposed_stages:
            raise WorkflowCommandError(
                "extend_budget requires a non-empty stageTokens budget mapping"
            )
        current_stages_raw = current_limits.get("stageTokens")
        if isinstance(current_stages_raw, Mapping):
            merged_stages = dict(current_stages_raw)
            fallback_stage_tokens = 0
        else:
            fallback_stage_tokens = (
                int(current_stages_raw)
                if isinstance(current_stages_raw, int)
                and not isinstance(current_stages_raw, bool)
                else 0
            )
            merged_stages = {
                stage.value: fallback_stage_tokens for stage in WorkflowStageId
            }
        for raw_stage, raw_value in proposed_stages.items():
            stage = str(raw_stage or "").strip()
            if not stage:
                raise WorkflowCommandError(
                    "extend_budget stageTokens contains an empty budget stage"
                )
            proposed = _positive_budget_limit(raw_value, field=f"stageTokens.{stage}")
            prior_raw = merged_stages.get(stage, fallback_stage_tokens)
            prior = (
                int(prior_raw)
                if isinstance(prior_raw, int) and not isinstance(prior_raw, bool)
                else 0
            )
            if proposed <= prior:
                raise WorkflowCommandError(
                    "extend_budget budget limit "
                    f"stageTokens.{stage} must increase above {prior}"
                )
            merged_stages[stage] = proposed
        merged["stageTokens"] = merged_stages
    return merged


_ATTEMPT_CREATING_COMMANDS = frozenset(
    {WorkflowCommandKind.START_NODE, WorkflowCommandKind.RETRY_NODE}
)

# Read-only commands never move a run, so they stay servable on a degraded
# run (the snapshot itself is diagnostic-visible).  Everything else is a
# mutation and requires the run's pinned definition to resolve.
_READ_ONLY_COMMANDS = frozenset(
    {WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION}
)

# Knowledge sideflow facade (plan §4.6): team-authorized sessions may ensure
# or inspect a knowledge collection at allowed nodes.  These commands never
# enter the operator-only set and never bump the parent runVersion — the
# parent run is only ever touched by the one appended invocation event owned
# by the knowledge sideflow service.
_KNOWLEDGE_FLOW_COMMANDS = frozenset(
    {
        WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION,
        WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION,
    }
)

_KNOWLEDGE_TERMINAL_RUN_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "archived"}
)

# 高影响命令：必须由服务端可验证的 operator 身份执行（P1-6）。
_OPERATOR_ONLY_COMMANDS = frozenset(
    {
        WorkflowCommandKind.CANCEL_NODE,
        WorkflowCommandKind.CANCEL_RUN,
        WorkflowCommandKind.REBIND_NODE,
        WorkflowCommandKind.EXTEND_BUDGET,
        WorkflowCommandKind.RESOLVE_HUMAN_TASK,
        WorkflowCommandKind.FORK_REVISION,
        WorkflowCommandKind.ARCHIVE_RUN,
        WorkflowCommandKind.RECONCILE_RUN,
        WorkflowCommandKind.BUILD_STAGE_ONE_PACKAGE,
        WorkflowCommandKind.FINALIZE_STAGE_ONE,
    }
)

# Stage-one G1 closeout operator commands.  Domain preparation (package
# build, Challenge Program registration/readback, artifact-store writes) is
# idempotent file-store IO and runs OUTSIDE the single-writer ledger
# transaction; only durable facts persist inside it (resolve_human_task
# precedent).
_STAGE_ONE_COMMANDS = frozenset(
    {
        WorkflowCommandKind.BUILD_STAGE_ONE_PACKAGE,
        WorkflowCommandKind.FINALIZE_STAGE_ONE,
    }
)


class WorkflowCommandService:
    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        readiness_service: NodeReadinessService,
        readiness_context: Callable[[], DomainReadinessContext],
        clock: Callable[[], int] | None = None,
        wake_worker: Callable[[], None] | None = None,
        coordinator_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._store = store
        self._readiness = readiness_service
        self._readiness_context = readiness_context
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._wake_worker = wake_worker or (lambda: None)
        self._coordinator_factory = coordinator_factory
        self._handlers: dict[WorkflowCommandKind, Callable] = {
            WorkflowCommandKind.START_NODE: self._handle_start_node,
            WorkflowCommandKind.RETRY_NODE: self._handle_retry_node,
            WorkflowCommandKind.CANCEL_NODE: self._handle_cancel_node,
            WorkflowCommandKind.CANCEL_RUN: self._handle_cancel_run,
            WorkflowCommandKind.RESOLVE_HUMAN_TASK: self._handle_resolve_human_task,
            WorkflowCommandKind.EXTEND_BUDGET: self._handle_extend_budget,
            WorkflowCommandKind.RECONCILE_RUN: self._handle_reconcile_run,
            WorkflowCommandKind.ARCHIVE_RUN: self._handle_archive_run,
            WorkflowCommandKind.REBIND_NODE: self._handle_rebind_node,
            WorkflowCommandKind.FORK_REVISION: self._handle_fork_revision,
            WorkflowCommandKind.BUILD_STAGE_ONE_PACKAGE: self._handle_build_stage_one_package,
            WorkflowCommandKind.FINALIZE_STAGE_ONE: self._handle_finalize_stage_one,
        }

    # ------------------------------------------------------------ public

    def submit(self, request: CommandRequest) -> CommandReceipt:
        if not request.team_id:
            raise TeamScopeMismatchError("teamId 缺失")
        if not request.idempotency_key:
            raise WorkflowCommandError("idempotencyKey 缺失")

        run = self._store.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        if run.team_id != request.team_id:
            raise TeamScopeMismatchError(
                f"run {request.run_id} 属于 {run.team_id}，请求 teamId={request.team_id}"
            )

        request_hash = request.request_hash()
        existing = self._store.get_command_by_idempotency(request.run_id, request.idempotency_key)
        if existing is not None:
            return self._replay(existing, request_hash)

        if request.expected_run_version != run.run_version:
            raise RunVersionConflictError(
                f"expected {request.expected_run_version}, current {run.run_version}"
            )

        if request.command not in _READ_ONLY_COMMANDS:
            # Plan §6.3: a run whose pinned definition cannot be honored never
            # executes a stale mutation — every non-read-only command
            # fail-closes after the runVersion CAS, before any handler runs.
            self._assert_pinned_definition_for_mutation(run)

        if request.command in _OPERATOR_ONLY_COMMANDS:
            self._authorize_operator(request)

        if request.command in _KNOWLEDGE_FLOW_COMMANDS:
            # The knowledge sideflow service owns its own single-writer
            # transactions, so these handlers run OUTSIDE a command-service
            # ledger transaction (no attempt, no runVersion bump on the
            # parent) and reuse the sideflow's idempotency instead.
            return self._handle_knowledge_flow_command(request)

        handler = self._handlers.get(request.command)
        if handler is None:
            raise WorkflowCommandError(
                f"command {request.command.value} 尚未接入"
            )

        # Recovery artifacts are materialized before a fresh readiness read so
        # the same visible retry command can repair an old accepted handoff and
        # immediately evaluate the successor against the canonical authority.
        try:
            prepared_artifact = prepare_command_human_acceptance_artifact(
                store=self._store,
                run=run,
                request=request,
            )
        except KnowledgeAcceptanceArtifactError as exc:
            raise WorkflowCommandError(str(exc)) from exc

        prepared_stage_one = None
        if request.command in _STAGE_ONE_COMMANDS:
            # Domain preparation OUTSIDE the ledger transaction: package
            # build, Challenge Program registration/readback and artifact-store
            # writes are idempotent IO and must never run inside the
            # single-writer transaction.
            prepared_stage_one = self._prepare_stage_one_command(run, request)

        if request.command in _ATTEMPT_CREATING_COMMANDS:
            if not request.node_id:
                raise WorkflowCommandError(f"{request.command.value} 需要 nodeId")
            readiness = self._readiness.evaluate(
                team_id=request.team_id,
                run_id=request.run_id,
                node_id=request.node_id,
                context=self._readiness_context(),
                use_cache=False,
            )
            if not readiness.ready:
                raise NodeNotReadyError(readiness, run.run_version)
        if request.command is WorkflowCommandKind.RESOLVE_HUMAN_TASK:
            future = self._store.submit(
                lambda uow: self._handle_resolve_human_task(
                    uow,
                    request,
                    request_hash,
                    prepared_artifact,
                ),
                force_flush=True,
            )
        elif request.command is WorkflowCommandKind.RETRY_NODE:
            future = self._store.submit(
                lambda uow: self._handle_retry_node(
                    uow,
                    request,
                    request_hash,
                    prepared_artifact,
                ),
                force_flush=True,
            )
        elif request.command is WorkflowCommandKind.RECONCILE_RUN:
            future = self._store.submit(
                lambda uow: self._handle_reconcile_run(
                    uow,
                    request,
                    request_hash,
                    prepared_artifact,
                ),
                force_flush=True,
            )
        else:
            if prepared_stage_one is not None:
                future = self._store.submit(
                    lambda uow: handler(uow, request, request_hash, prepared_stage_one),
                    force_flush=True,
                )
            else:
                future = self._store.submit(
                    lambda uow: handler(uow, request, request_hash),
                    force_flush=True,
                )
        receipt = future.result(timeout=30)
        if request.command is WorkflowCommandKind.CANCEL_RUN and receipt.status == "accepted":
            # Post-commit, best-effort fast path: the durable cleanup intent
            # was committed with the command and the resident outbox worker
            # remains the retry/terminal-confirmation path. Never runs inside
            # the ledger transaction and never touches the receipt.
            # Replay returns earlier via the idempotency lookup, so a replayed
            # cancel_run cannot re-run this side effect.
            self._close_cancel_run_inflight_turns(request.run_id)
        if (
            request.command is WorkflowCommandKind.FINALIZE_STAGE_ONE
            and prepared_stage_one is not None
            and receipt.status == "accepted"
            and not dict(receipt.result or {}).get("replayed")
        ):
            # Post-commit checkpoint sync (ledger transaction already durably
            # terminal): either resume the interrupted closure node through the
            # outbox worker, or write the accepted marker straight into the
            # thread's checkpoint when no interrupt is left. A same-key replay
            # returns at the idempotency lookup above with the same result, so
            # this stays idempotent end to end.
            self._sync_stage_one_checkpoint(
                run=run,
                prepared=prepared_stage_one,
                idempotency_key=request.idempotency_key,
            )
        return receipt

    def _authorize_operator(self, request: CommandRequest) -> None:
        """Authorize high-impact commands from server request context only.

        Client body ``requestedBy`` must never self-declare operator authority.
        Privileged roles are required for high-impact commands.
        """
        from .operator_authorization import current_server_operator
        from .operator_permissions import (
            operator_has_privileged_role,
            require_operator_permission,
        )

        context = current_server_operator()
        if context is None or not context.operator_id:
            raise CommandForbiddenError("command_forbidden")
        # Body may carry a display actor, but a forged operator id that disagrees
        # with the server context is rejected.
        actor = request.requested_by
        body_type = str(getattr(actor, "actor_type", "") or "").lower()
        body_id = str(getattr(actor, "actor_id", "") or "").strip()
        if body_type in {"operator", "user"} and body_id and body_id != context.operator_id:
            raise CommandForbiddenError("command_forbidden")
        try:
            require_operator_permission(
                operator_id=context.operator_id,
                roles=context.roles,
                command=request.command.value,
            )
        except PermissionError as exc:
            raise CommandForbiddenError("command_forbidden") from exc
        if (
            request.command is WorkflowCommandKind.ARCHIVE_RUN
            and not operator_has_privileged_role(context.roles)
        ):
            raise CommandForbiddenError("command_forbidden")

    # ------------------------------------------------ cancel_run turn closure

    def _close_cancel_run_inflight_turns(self, run_id: str) -> None:
        """Best-effort fast stop of turns owned by a cancelled run.

        Runs strictly AFTER the ledger transaction committed: stopping a turn
        performs chat IO, takes the session chat-state lock and republishes
        the detail projection, none of which may run inside the single-writer
        SQLite transaction or under the 30s submit future timeout.

        Failures are logged and swallowed here because the cancel command must
        stay successful; the command transaction also writes a durable outbox
        intent, which is retried by ``CancelRunCleanupWorker``. This fast path
        deliberately does not acknowledge that intent.
        Idempotency: replayed cancel_run commands return at the idempotency
        lookup before this hook, and turns already carrying a terminal
        snapshot are skipped, so repeats are natural no-ops.
        """
        try:
            pairs = _collect_cancel_run_turn_pairs(run_id)
        except Exception:  # noqa: BLE001 - side effect must never break the command
            logger.exception(
                "cancel_run turn closure could not read the run record: runId=%s",
                run_id,
            )
            return
        if not pairs:
            return
        from core.web.services import session_service

        outcomes: list[dict[str, str]] = []
        for session_id, turn_id in pairs:
            try:
                outcome = _close_cancel_run_turn(session_service, session_id, turn_id)
            except Exception:  # noqa: BLE001 - per-turn isolation
                logger.exception(
                    "cancel_run turn closure failed: runId=%s sessionId=%s turnId=%s",
                    run_id,
                    session_id,
                    turn_id,
                )
                continue
            outcomes.append(
                {"sessionId": session_id, "turnId": turn_id, "outcome": outcome}
            )
        if outcomes:
            logger.info(
                "cancel_run closed in-flight turns: runId=%s outcomes=%s",
                run_id,
                outcomes,
            )

    # ------------------------------------------------ knowledge sideflow

    def _handle_knowledge_flow_command(self, request: CommandRequest) -> CommandReceipt:
        if request.command is WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION:
            return self._handle_ensure_knowledge_collection(request)
        return self._handle_inspect_knowledge_collection(request)

    def _handle_ensure_knowledge_collection(
        self, request: CommandRequest
    ) -> CommandReceipt:
        """Ensure (idempotently) one knowledge invocation for the parent run.

        The parent run's version/status/active node never move; the sideflow
        service owns the child-run transaction and appends the only parent
        event.  A replayed request returns the SAME invocation without a
        second child run.

        Server-side rollout gate (defense in depth against direct API calls
        that bypass the offer layer): ensure creates a REAL child run, so it
        is only servable in mode ``on`` — shadow stays projection-only.
        """
        from .knowledge_capability import normalize_root_ids
        from .knowledge_rollout import knowledge_ensure_enabled
        from .knowledge_sideflow_service import (
            KnowledgeSideflowError,
            ensure_knowledge_invocation,
        )

        if not knowledge_ensure_enabled():
            raise KnowledgeCommandError(
                "知识侧流程未启用（[research.knowledge_sideflow] mode != on），"
                "不能发起知识搜集",
                code="knowledge_sideflow_disabled",
            )
        run = self._store.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        if str(run.status) in _KNOWLEDGE_TERMINAL_RUN_STATUSES:
            raise CommandNotAllowedError(
                f"run {request.run_id} 已结束，不能发起知识搜集"
            )
        payload = dict(request.payload or {})
        question_id = str(payload.get("questionId") or "").strip()
        if not question_id:
            raise KnowledgeCommandError(
                "ensure_knowledge_collection 需要 questionId",
                code="invalid_request",
            )
        parent_node_id = str(request.node_id or run.active_node_id or "").strip()
        if not parent_node_id:
            raise KnowledgeCommandError(
                "ensure_knowledge_collection 需要 nodeId（或 run 存在 activeNode）",
                code="invalid_request",
            )
        self._assert_node_in_pinned_definition(run, parent_node_id)
        try:
            parent_attempt = int(payload.get("parentAttempt") or 1)
        except (TypeError, ValueError):
            parent_attempt = 1
        managed_root_ids = normalize_root_ids(payload.get("managedSourceRootIds"))
        scope = {
            "questionId": question_id.strip().upper(),
            "projectId": str(run.project_id or ""),
            "managedSourceRootIds": managed_root_ids,
        }
        try:
            outcome = ensure_knowledge_invocation(
                self._store,
                parent_run_id=request.run_id,
                parent_node_id=parent_node_id,
                question_id=question_id,
                scope=scope,
                search_envelope=_normalized_search_envelope(
                    payload.get("searchEnvelope")
                ),
                requirements=_normalized_requirements(payload.get("requirements")),
                source_policy_version=_normalized_source_policy_version(
                    payload.get("sourcePolicyVersion")
                ),
                parent_node_run_id=str(payload.get("parentNodeRunId") or ""),
                parent_attempt=parent_attempt,
                source_manifest_ref=str(payload.get("sourceManifestRef") or ""),
                managed_source_root_ids=managed_root_ids,
                wake_worker=self._wake_worker,
            )
        except KnowledgeSideflowError as exc:
            raise KnowledgeCommandError(str(exc), code=exc.code) from exc
        invocation = outcome["invocation"]
        fresh = self._store.get_run(request.run_id)
        return CommandReceipt(
            command_id=new_id("cmd"),
            run_id=request.run_id,
            status="accepted",
            # The parent runVersion is intentionally unchanged.
            accepted_run_version=int(run.run_version),
            idempotency_key=request.idempotency_key,
            latest_event_sequence=int(fresh.last_event_sequence) if fresh else 0,
            result={
                "invocationId": str(invocation.invocation_id),
                "childRunId": str(
                    outcome.get("childRunId")
                    or invocation.knowledge_child_run_id
                    or ""
                ),
                "replayed": bool(outcome.get("replayed")),
                "reused": bool(outcome.get("reused")),
                "invocationStatus": str(invocation.status),
                "handoffState": str(invocation.handoff_state),
                "managedSourceRootIds": managed_root_ids,
            },
        )

    def _handle_inspect_knowledge_collection(
        self, request: CommandRequest
    ) -> CommandReceipt:
        """Read-only knowledge invocation inspection for the parent run.

        Read-only, so it stays servable in shadow/on but is rejected in mode
        ``off`` (server-side gate against direct API calls).
        """
        from core.research.workflow.knowledge_sideflow_definition import (
            KNOWLEDGE_SIDEFLOW_NODE_IDS,
        )
        from .knowledge_rollout import knowledge_inspect_enabled, knowledge_sideflow_mode

        if not knowledge_inspect_enabled():
            raise KnowledgeCommandError(
                "知识侧流程已关闭（[research.knowledge_sideflow] mode = off），"
                "无法查看知识搜集进度",
                code="knowledge_sideflow_disabled",
            )

        run = self._store.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        payload = dict(request.payload or {})
        invocation_id = str(payload.get("invocationId") or "").strip()
        store = self._store
        if invocation_id:
            invocation = store.read(
                lambda repo: repo.get_knowledge_invocation(invocation_id)
            )
            if invocation is None or str(invocation.parent_run_id) != request.run_id:
                raise KnowledgeCommandError(
                    f"knowledge invocation {invocation_id} 不属于 run {request.run_id}",
                    code="unknown_invocation",
                )
            invocations = [invocation]
        else:
            invocations = store.read(
                lambda repo: repo.list_knowledge_invocations_for_parent(request.run_id)
            )

        invocation_views = [self._inspect_invocation(item) for item in invocations]
        child_view: dict[str, Any] | None = None
        selected = invocation_views[0] if invocation_views else None
        if selected is None:
            recovery_actions: list[str] = ["ensure_knowledge_collection"]
        else:
            child_view = self._inspect_child_run(
                str(selected["childRunId"] or ""), KNOWLEDGE_SIDEFLOW_NODE_IDS
            )
            recovery_actions = _knowledge_recovery_actions(selected, child_view)
        return CommandReceipt(
            command_id=new_id("cmd"),
            run_id=request.run_id,
            status="accepted",
            accepted_run_version=int(run.run_version),
            idempotency_key=request.idempotency_key,
            latest_event_sequence=int(run.last_event_sequence),
            result={
                "invocationId": invocation_id or (
                    str(selected["invocationId"]) if selected else ""
                ),
                "invocations": invocation_views,
                "childRun": child_view,
                "recoveryActions": recovery_actions,
                "knowledgeSideflowMode": knowledge_sideflow_mode(),
            },
        )

    def _inspect_invocation(self, invocation: Any) -> dict[str, Any]:
        error: dict[str, Any] | None = None
        raw_error = str(getattr(invocation, "error_json", "") or "")
        if raw_error:
            try:
                parsed = json.loads(raw_error)
                error = dict(parsed) if isinstance(parsed, Mapping) else {"detail": raw_error}
            except (TypeError, ValueError, json.JSONDecodeError):
                error = {"detail": raw_error}
        return {
            "invocationId": str(invocation.invocation_id),
            "parentRunId": str(invocation.parent_run_id),
            "parentNodeId": str(invocation.parent_node_id),
            "parentNodeRunId": str(invocation.parent_node_run_id or ""),
            "parentAttempt": int(invocation.parent_attempt or 1),
            "questionId": str(invocation.question_id),
            "status": str(invocation.status),
            "handoffState": str(invocation.handoff_state),
            "childRunId": str(invocation.knowledge_child_run_id or ""),
            "knowledgePackageRef": str(invocation.knowledge_package_ref or ""),
            "packageContentHash": str(invocation.package_content_hash or ""),
            "sourcePolicyVersion": str(invocation.source_policy_version or ""),
            "error": error,
            "createdAtMs": int(invocation.created_at_ms or 0),
            "updatedAtMs": int(invocation.updated_at_ms or 0),
        }

    def _inspect_child_run(
        self, child_run_id: str, node_ids: tuple[str, ...]
    ) -> dict[str, Any] | None:
        if not child_run_id:
            return None
        store = self._store
        child = store.get_run(child_run_id)
        if child is None:
            return None
        nodes: dict[str, Any] = {}
        for node_id in node_ids:
            latest = store.latest_attempt(child_run_id, node_id)
            nodes[node_id] = {
                "attempt": int(latest.attempt) if latest else 0,
                "status": str(latest.status) if latest else "not_started",
                "nodeRunId": str(latest.node_run_id) if latest else None,
            }
        artifact_count = store.read(
            lambda repo: repo.execute(
                "SELECT COUNT(*) FROM artifact_receipts WHERE run_id = ?",
                (child_run_id,),
            ).fetchone()[0]
        )
        try:
            limits = json.loads(child.safety_limits_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            limits = {}
        return {
            "runId": child.run_id,
            "workflowId": child.workflow_id,
            "status": child.status,
            "activeNodeId": child.active_node_id,
            "runVersion": int(child.run_version),
            "nodes": nodes,
            "sourceCount": int(artifact_count or 0),
            "budget": dict(limits) if isinstance(limits, Mapping) else {},
            "completionKind": str(child.completion_kind or ""),
            "terminalReason": str(child.terminal_reason or ""),
        }

    def _assert_pinned_definition_for_mutation(self, run: Any) -> None:
        """Fail closed when a registry-era run's pinned definition degrades.

        Plan §6.3: a run whose pinned definition cannot be honored never
        executes a stale mutation.  Version identities come in two eras:

        - ``wv-*`` (T2 registry identity): resolved STRICTLY through the
          registry — unknown version, structureHash drift or registry
          unavailability all reject the mutation with
          ``definition_resolution_degraded`` (diagnostics included).
        - empty ids are the only explicit pre-registry legacy path and retain
          the registered current-definition fallback. A non-empty unknown
          literal is not a legacy credential and fails closed.
        """
        from core.research.workflow.definition_registry import (
            WorkflowDefinitionRegistryError,
            resolve_definition,
        )

        workflow_id = str(getattr(run, "workflow_id", "") or "").strip()
        version_id = str(getattr(run, "workflow_version_id", "") or "").strip()
        run_id = str(getattr(run, "run_id", "") or "")
        if not version_id:
            return
        try:
            resolve_definition(
                workflow_id=workflow_id,
                workflow_version_id=version_id,
                structure_hash=str(getattr(run, "structure_hash", "") or "").strip(),
                run_id=run_id,
            )
        except WorkflowDefinitionRegistryError as exc:
            raise DefinitionResolutionDegradedError(
                f"run {run_id} 的钉住定义无法解析（workflowId={workflow_id} "
                f"workflowVersionId={version_id} "
                f"structureHash={str(getattr(run, 'structure_hash', '') or '') or '<absent>'}）："
                f"{exc}；拒绝执行任何 mutation 命令"
            ) from exc

    def _assert_node_in_pinned_definition(self, run: Any, node_id: str) -> None:
        from core.research.workflow.definition_registry import (
            WorkflowDefinitionRegistryError,
            resolve_definition_for_run_record,
        )

        try:
            resolve_definition_for_run_record(
                {
                    "runId": run.run_id,
                    "workflowId": run.workflow_id,
                    "workflowVersionId": run.workflow_version_id,
                    "structureHash": run.structure_hash,
                    "completedNodeIds": [node_id],
                    "runtimeCurrentNodeIds": [],
                },
                expected_node_ids=[node_id],
            )
        except WorkflowDefinitionRegistryError as exc:
            raise KnowledgeCommandError(
                f"node {node_id} 不属于 run {run.run_id} 冻结的工作流定义",
                code="unknown_node",
            ) from exc

    def _replay(self, existing: Any, request_hash: str) -> CommandReceipt:
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError()
        if existing.result_json:
            payload = json.loads(existing.result_json)
            result = payload.get("result")
            return CommandReceipt(
                command_id=str(payload.get("commandId") or ""),
                run_id=str(payload.get("runId") or ""),
                status=str(payload.get("status") or ""),
                accepted_run_version=payload.get("acceptedRunVersion"),
                idempotency_key=str(payload.get("idempotencyKey") or ""),
                latest_event_sequence=int(payload.get("latestEventSequence") or 0),
                result=dict(result) if isinstance(result, Mapping) else None,
            )
        return CommandReceipt(
            command_id=existing.command_id,
            run_id=existing.run_id,
            status=existing.status,
            accepted_run_version=existing.accepted_run_version,
            idempotency_key=existing.idempotency_key,
            latest_event_sequence=0,
        )

    # ------------------------------------------------------- handlers

    def _handle_start_node(
        self, uow, request: CommandRequest, request_hash: str
    ) -> CommandReceipt:
        node_id = request.node_id
        now_ms = self._clock()
        latest = uow.repository.latest_attempt(request.run_id, node_id)
        if latest is not None and latest.status in (
            NodeAttemptStatus.STARTING.value,
            NodeAttemptStatus.DISPATCHING.value,
            NodeAttemptStatus.RUNNING.value,
            NodeAttemptStatus.WAITING_HUMAN.value,
        ):
            raise CommandNotAllowedError("该节点已有进行中的 attempt")
        attempt = (latest.attempt + 1) if latest is not None else 1
        node_run_id = f"nr-{request.run_id}-{node_id}-a{attempt}"
        command_id = new_id("cmd")

        bumped = _bump(uow, request, event_count=2, now_ms=now_ms)
        accepted_version, sequence = bumped

        run = uow.repository.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        definition = _definition_for_ledger_run(run, expected_node_ids=[node_id])
        node_spec = next(item for item in definition.nodes if item.nodeId == node_id)
        binding_snapshot_id = _binding_snapshot_id(uow, request.run_id, node_id)
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        uow.repository.insert_attempt(
            _attempt_record(
                node_run_id=node_run_id,
                run_id=request.run_id,
                node_id=node_id,
                attempt=attempt,
                status=NodeAttemptStatus.STARTING.value,
                command_id=command_id,
                input_snapshot_hash=_input_snapshot_hash(uow, request.run_id),
                started_at_ms=now_ms,
                retry_of_node_run_id=latest.node_run_id if latest else None,
                binding_snapshot_id=binding_snapshot_id,
                actor_kind=node_spec.actorKind.value,
            )
        )
        uow.repository.insert_outbox(
            _graph_dispatch_record(
                uow=uow,
                run=run,
                attempt=_node_attempt_for_dispatch(
                    node_run_id=node_run_id,
                    run_id=request.run_id,
                    node_id=node_id,
                    attempt=attempt,
                    binding_snapshot_id=binding_snapshot_id,
                    actor_kind=node_spec.actorKind.value,
                ),
                command_id=command_id,
                now_ms=now_ms,
            )
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence - 1,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="command_accepted",
                correlation_id=request.idempotency_key,
                payload={
                    "commandId": command_id,
                    "nodeId": node_id,
                    "expectedRunVersion": request.expected_run_version,
                    "acceptedRunVersion": accepted_version,
                },
                now_ms=now_ms,
            )
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="node_starting",
                correlation_id=request.idempotency_key,
                payload={"nodeRunId": node_run_id, "nodeId": node_id, "attempt": attempt},
                now_ms=now_ms,
            )
        )
        uow.repository.update_run_status(
            request.run_id,
            request.team_id,
            RunStatus.RUNNING.value,
            now_ms,
            active_node_id=node_id,
        )
        uow.after_commit(self._wake_worker)
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_retry_node(
        self,
        uow,
        request: CommandRequest,
        request_hash: str,
        prepared_artifact: PreparedHumanAcceptanceArtifact | None = None,
    ) -> CommandReceipt:
        from .command_offers.retry_node import succeeded_node_rerun_available

        node_id = request.node_id
        latest = uow.repository.latest_attempt(request.run_id, node_id)
        if latest is None:
            raise CommandNotAllowedError("该节点没有可重试的 attempt")
        run = uow.repository.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        if latest.status not in (
            NodeAttemptStatus.FAILED.value,
            NodeAttemptStatus.BLOCKED.value,
            NodeAttemptStatus.CANCELLED.value,
        ) and not succeeded_node_rerun_available(
            node_id=node_id, latest=latest, run=run
        ):
            raise CommandNotAllowedError(f"attempt {latest.status} 不可重试")
        persist_prepared_human_acceptance_artifact(
            uow,
            run=run,
            prepared=prepared_artifact,
            now_ms=self._clock(),
        )
        receipt = self._handle_start_node(uow, request, request_hash)
        uow.repository.update_attempt_status(
            latest.node_run_id,
            NodeAttemptStatus.STALE.value,
            self._clock(),
        )
        return receipt

    def _handle_cancel_node(self, uow, request: CommandRequest, request_hash: str) -> CommandReceipt:
        node_id = request.node_id
        latest = uow.repository.latest_attempt(request.run_id, node_id)
        if latest is None or latest.status not in (
            NodeAttemptStatus.STARTING.value,
            NodeAttemptStatus.DISPATCHING.value,
            NodeAttemptStatus.RUNNING.value,
            NodeAttemptStatus.WAITING_HUMAN.value,
            NodeAttemptStatus.BLOCKED.value,
        ):
            raise CommandNotAllowedError("该节点没有可取消的 attempt")
        now_ms = self._clock()
        command_id = new_id("cmd")
        bumped = _bump(uow, request, event_count=1, now_ms=now_ms)
        accepted_version, sequence = bumped
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        uow.repository.update_attempt_status(
            latest.node_run_id,
            NodeAttemptStatus.CANCELLED.value,
            now_ms,
            finished_at_ms=now_ms,
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="node_blocked",
                correlation_id=request.idempotency_key,
                payload={"nodeRunId": latest.node_run_id, "nodeId": node_id, "cancelled": True},
                now_ms=now_ms,
            )
        )
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_cancel_run(self, uow, request: CommandRequest, request_hash: str) -> CommandReceipt:
        now_ms = self._clock()
        run = uow.repository.get_run(request.run_id)
        require_run_transition(RunStatus(run.status), RunStatus.CANCELLED)
        command_id = new_id("cmd")
        bumped = _bump(uow, request, event_count=1, now_ms=now_ms)
        accepted_version, sequence = bumped
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        # Cancellation and session-turn stopping are separate state machines.
        # Persist the cleanup intent in this same transaction so a process
        # crash after the run transition cannot lose the stop request. The
        # resident workflow outbox tick retries the external session side
        # effect and acknowledges only after terminal snapshot verification.
        from .cancel_run_cleanup import build_cancel_run_cleanup_record

        uow.repository.insert_outbox(
            build_cancel_run_cleanup_record(
                run_id=request.run_id,
                command_id=command_id,
                now_ms=now_ms,
            )
        )
        uow.after_commit(self._wake_worker)
        uow.repository.update_run_status(
            request.run_id,
            request.team_id,
            RunStatus.CANCELLED.value,
            now_ms,
            completion_kind="cancelled",
            terminal_reason=str(request.payload.get("reason") or "operator cancelled"),
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="run_blocked",
                correlation_id=request.idempotency_key,
                payload={"cancelled": True, "reason": str(request.payload.get("reason") or "")},
                now_ms=now_ms,
            )
        )
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_resolve_human_task(
        self,
        uow,
        request: CommandRequest,
        request_hash: str,
        prepared_artifact: PreparedHumanAcceptanceArtifact | None = None,
    ) -> CommandReceipt:
        task_id = str(request.payload.get("taskId") or "")
        decision = str(request.payload.get("decision") or "")
        if not task_id or decision not in ("accept", "reject", "revise"):
            raise WorkflowCommandError("resolve_human_task 需要 taskId 和 decision(accept/reject/revise)")
        row = uow.repository.get_human_task(task_id)
        if row is None:
            raise HumanTaskNotFoundError(task_id)
        if str(row[1]) != request.run_id:
            raise TeamScopeMismatchError("human task 不属于该 run")
        now_ms = self._clock()
        target = {
            "accept": HumanTaskStatus.ACCEPTED.value,
            "reject": HumanTaskStatus.REJECTED.value,
            "revise": HumanTaskStatus.REVISED.value,
        }[decision]
        current_status = HumanTaskStatus(str(row[6] or HumanTaskStatus.PENDING.value))
        if current_status is not HumanTaskStatus.PENDING:
            raise InvalidHumanTaskStateError(
                f"human task {task_id} 已处于 {current_status.value} 状态，不能重复决策"
            )
        require_human_task_transition(current_status, HumanTaskStatus(target))
        command_id = new_id("cmd")
        bumped = _bump(uow, request, event_count=1, now_ms=now_ms)
        accepted_version, sequence = bumped
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        decision_json = json.dumps(
            {
                "decision": decision,
                "reason": str(request.payload.get("reason") or ""),
                "requestedBy": request.requested_by.to_dict(),
            },
            ensure_ascii=False,
        )
        if not uow.repository.update_human_task_decision(
            task_id, target, now_ms, decision_json=decision_json
        ):
            # 守卫 UPDATE（WHERE status='pending'）未命中：并发下任务已被解决。
            raise InvalidHumanTaskStateError(
                f"human task {task_id} 已被并发决策，本次决策未生效"
            )
        # 人工决策后通过正式 graph resume 推进（T5 契约：Human 节点可恢复）。
        attempt = uow.repository.get_attempt(str(row[2]))
        pending_action_id = attempt.pending_action_id if attempt else None
        task_kind = str(row[4] or "")
        if decision == "revise":
            # revise：不把决策压成 failed receipt，而是 fork 新 Run
            # （spec 8.4 revision fork；父 Run 保持 lineage）。
            parent_run = uow.repository.get_run(request.run_id)
            from_node_id = str(
                request.payload.get("fromNodeId") or request.node_id or ""
            )
            if parent_run is None or not from_node_id:
                raise WorkflowCommandError(
                    "revise 决策需要 fromNodeId 且父 run 存在"
                )
            self._create_revision_fork(
                uow,
                parent=parent_run,
                from_node_id=from_node_id,
                reason=str(request.payload.get("reason") or "revise protocol"),
                checkpoint_id=str(request.payload.get("checkpointId") or ""),
                requested_by=request.requested_by,
                command_id=command_id,
                now_ms=now_ms,
            )
        else:
            from core.research.workflow.contracts import ExecutionReceipt

            run = uow.repository.get_run(request.run_id)
            if run is None:
                raise RunNotFoundError(request.run_id)
            artifact_receipt_ids = persist_prepared_human_acceptance_artifact(
                uow,
                run=run,
                prepared=prepared_artifact,
                now_ms=now_ms,
            )
            if (
                decision == "accept"
                and task_kind in _ARTIFACT_HUMAN_GATES
                and not artifact_receipt_ids
            ):
                raise WorkflowCommandError(
                    f"{task_kind} accept requires a materialized artifact receipt"
                )
            if pending_action_id:
                receipt = ExecutionReceipt(
                    action_id=pending_action_id,
                    node_run_id=str(row[2]),
                    outcome="succeeded" if decision == "accept" else "failed",
                    artifact_receipt_ids=artifact_receipt_ids,
                    execution_anchor_id=None,
                    budget_receipt_id=None,
                    problem=None,
                    completed_at_ms=now_ms,
                )
                uow.repository.insert_outbox(
                    _human_resume_dispatch(
                        uow, request, str(row[2]), receipt, command_id, now_ms
                    )
                )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="handoff_accepted" if decision == "accept" else "handoff_rejected",
                correlation_id=request.idempotency_key,
                payload={
                    "taskId": task_id,
                    "decision": decision,
                    "nodeRunId": str(row[2]),
                },
                now_ms=now_ms,
            )
        )
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_extend_budget(self, uow, request: CommandRequest, request_hash: str) -> CommandReceipt:
        now_ms = self._clock()
        run = uow.repository.get_run(request.run_id)
        limits = json.loads(run.safety_limits_json)
        if not isinstance(limits, Mapping):
            raise WorkflowCommandError("extend_budget current budget limits are invalid")
        limits = _merged_budget_extension(limits, request.payload.get("limits"))
        command_id = new_id("cmd")
        bumped = _bump(uow, request, event_count=1, now_ms=now_ms)
        accepted_version, sequence = bumped
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        uow.repository.update_run_safety_limits(
            request.run_id, request.team_id, json.dumps(limits), now_ms
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="budget_settled",
                correlation_id=request.idempotency_key,
                payload={"limits": limits},
                now_ms=now_ms,
            )
        )
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_reconcile_run(
        self,
        uow,
        request: CommandRequest,
        request_hash: str,
        prepared_artifact: PreparedHumanAcceptanceArtifact | None = None,
    ) -> CommandReceipt:
        now_ms = self._clock()
        run = uow.repository.get_run(request.run_id)
        attempts = uow.repository.list_attempts(request.run_id)
        # Reconciliation resets the run projection to ledger authority BEFORE
        # any dispatch is revived. Incident blocked attempts covered by an
        # earlier successful advance (operator-misassigned retries whose
        # nodeId conflicts with the chain frontier) would otherwise pin
        # active_node_id and re-derive the same failing dispatch forever.
        if run is None:
            raise RunNotFoundError(request.run_id)
        plan = plan_ledger_authority(attempts, node_order=formal_node_order(run))
        command_id = new_id("cmd")
        bumped = _bump(uow, request, event_count=1, now_ms=now_ms)
        accepted_version, sequence = bumped
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        artifact_receipt_ids = persist_prepared_human_acceptance_artifact(
            uow,
            run=run,
            prepared=prepared_artifact,
            now_ms=now_ms,
        )
        for node_run_id in plan.superseded_node_run_ids:
            uow.repository.update_attempt_status(
                node_run_id,
                NodeAttemptStatus.STALE.value,
                now_ms,
                finished_at_ms=now_ms,
            )
            uow.repository.execute(
                """
                UPDATE outbox_actions
                SET status = 'cancelled',
                    lease_owner = NULL,
                    lease_expires_at_ms = NULL,
                    updated_at_ms = ?
                WHERE node_run_id = ?
                  AND action_kind = 'graph_dispatch'
                  AND status IN ('failed', 'pending', 'leased')
                """,
                (now_ms, node_run_id),
            )
        # Reconciliation re-derives execution from the durable ledger.  A
        # blocked run usually got there via a terminal-failed graph_dispatch
        # (e.g. checkpoint_node_mismatch); reviving only the run status would
        # strand it as running with nothing left to advance, until the sweep
        # flips it back to reconciliation_required.  Give the worker a fresh
        # routing decision by re-arming failed dispatch rows in this same
        # transaction (same repair shape as _repair_starting_without_progress);
        # live or deliberately cancelled rows stay untouched. Rows whose node's
        # latest attempt holds a readiness-pipeline verdict stay dead: replay
        # them would deterministically re-fail and overwrite that verdict,
        # which both the landing above and the V2 rerun mapping depend on.
        uow.repository.execute(
            """
            UPDATE outbox_actions
            SET status = 'pending',
                lease_owner = NULL,
                lease_expires_at_ms = NULL,
                available_at_ms = ?,
                attempt_count = 0,
                last_problem_json = NULL,
                updated_at_ms = ?
            WHERE run_id = ?
              AND action_kind = 'graph_dispatch'
              AND status = 'failed'
              AND NOT EXISTS (
                SELECT 1 FROM node_attempts na
                WHERE na.node_run_id = outbox_actions.node_run_id
                  AND na.status = 'blocked'
                  AND INSTR(na.problem_json, 'auto_advance_not_ready') > 0
              )
            """,
            (now_ms, now_ms, request.run_id),
        )
        revived = int(uow.repository.affected() or 0)
        active_work_row = uow.repository.execute(
            """
            SELECT
                EXISTS(
                    SELECT 1 FROM outbox_actions
                    WHERE run_id = ?
                      AND action_kind IN ('graph_dispatch', 'adapter_dispatch', 'checkpoint_fork')
                      AND status IN ('pending', 'leased')
                )
                OR EXISTS(
                    SELECT 1 FROM node_attempts
                    WHERE run_id = ?
                      AND status IN ('starting', 'dispatching', 'running', 'waiting_human')
                )
            """,
            (request.run_id, request.run_id),
        ).fetchone()
        has_active_work = revived > 0 or bool(active_work_row and active_work_row[0])
        zero_work_problem = {
            "code": "reconcile_no_active_work",
            "detail": "ledger authority has no active or revivable workflow work",
        }
        if plan.lands_blocked:
            target_status = RunStatus.BLOCKED
            landing_problem = dict(plan.landing_problem)
        elif has_active_work:
            target_status = RunStatus.RUNNING
            landing_problem = None
        else:
            target_status = RunStatus.RECONCILIATION_REQUIRED
            landing_problem = zero_work_problem
        require_run_transition(RunStatus(run.status), target_status)
        if target_status == RunStatus.BLOCKED:
            # The landing verdict is copied verbatim from the deepest readiness
            # verdict the pipeline itself wrote beyond every success —
            # reconcile only re-projects ledger truth onto the run record,
            # never hand-authors a state. The V2 rerun mapping keys off
            # exactly this projection (blocked + auto_advance_not_ready).
            uow.repository.update_run_status(
                request.run_id,
                request.team_id,
                target_status.value,
                now_ms,
                active_node_id=str(plan.active_node_id or ""),
                blocked_problem_json=json.dumps(landing_problem, ensure_ascii=False),
            )
        else:
            uow.repository.update_run_status(
                request.run_id,
                request.team_id,
                target_status.value,
                now_ms,
                blocked_problem_json=(
                    json.dumps(landing_problem, ensure_ascii=False)
                    if landing_problem is not None
                    else None
                ),
            )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="run_blocked",
                correlation_id=request.idempotency_key,
                payload={
                    "reconciled": True,
                    "revivedDispatchCount": revived,
                    "activeWorkFound": has_active_work,
                    "reconciledStatus": target_status.value,
                    "artifactReceiptIds": list(artifact_receipt_ids),
                    "staleAttemptIds": list(plan.superseded_node_run_ids),
                    "recomputedActiveNodeId": plan.active_node_id,
                    "landingProblemCode": (
                        str(landing_problem.get("code") or "")
                        if landing_problem
                        else None
                    ),
                    "landingProblemDetail": (
                        str(landing_problem.get("detail") or "")
                        if landing_problem
                        else None
                    ),
                },
                now_ms=now_ms,
            )
        )
        if revived > 0:
            uow.after_commit(self._wake_worker)
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_archive_run(
        self, uow, request: CommandRequest, request_hash: str
    ) -> CommandReceipt:
        """Archive a terminal run without reviving its execution state."""

        now_ms = self._clock()
        run = uow.repository.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        try:
            current = RunStatus(run.status)
        except ValueError as exc:
            raise WorkflowCommandError("archive_run 的当前 run 状态无效") from exc
        if current not in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.RECONCILIATION_REQUIRED,
        }:
            raise WorkflowCommandError(
                f"archive_run 不能归档 {current.value} 状态的 run"
            )
        require_run_transition(current, RunStatus.ARCHIVED)
        reason = str(request.payload.get("reason") or "operator archived").strip()
        if not reason:
            reason = "operator archived"

        cancelled_outbox_count = 0
        for attempt in uow.repository.list_attempts(request.run_id):
            cancelled_outbox_count += uow.repository.cancel_outbox_by_node_run(
                attempt.node_run_id, now_ms
            )

        command_id = new_id("cmd")
        accepted_version, sequence = _bump(
            uow, request, event_count=1, now_ms=now_ms
        )
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        if not uow.repository.update_run_status(
            request.run_id,
            request.team_id,
            RunStatus.ARCHIVED.value,
            now_ms,
            completion_kind=run.completion_kind,
            terminal_reason=run.terminal_reason,
            blocked_problem_json=run.blocked_problem_json,
        ):
            raise WorkflowCommandError("archive_run 未能更新目标 run")
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="run_archived",
                correlation_id=request.idempotency_key,
                payload={
                    "commandId": command_id,
                    "archivedFromStatus": current.value,
                    "terminalReason": run.terminal_reason,
                    "previousCompletedAtMs": run.completed_at_ms,
                    "archiveReason": reason,
                    "reason": reason,
                    "cancelledOutboxCount": cancelled_outbox_count,
                    "requestedBy": request.requested_by.to_dict(),
                },
                now_ms=now_ms,
            )
        )
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_rebind_node(self, uow, request: CommandRequest, request_hash: str) -> CommandReceipt:
        node_id = request.node_id
        if not node_id:
            raise WorkflowCommandError("rebind_node 需要 nodeId")
        now_ms = self._clock()
        command_id = new_id("cmd")
        bumped = _bump(uow, request, event_count=1, now_ms=now_ms)
        accepted_version, sequence = bumped
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        uow.repository.update_run_binding_set(
            request.run_id,
            request.team_id,
            str(request.payload.get("bindingSnapshotSetId") or "rebound"),
            now_ms,
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="execution_anchor_bound",
                correlation_id=request.idempotency_key,
                payload={"nodeId": node_id, "rebound": True},
                now_ms=now_ms,
            )
        )
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_fork_revision(
        self, uow, request: CommandRequest, request_hash: str
    ) -> CommandReceipt:
        from_node_id = str(request.payload.get("fromNodeId") or "")
        reason = str(request.payload.get("reason") or "")
        if not from_node_id:
            raise WorkflowCommandError("fork_revision 需要 fromNodeId（实验设计节点）")
        if not reason:
            raise WorkflowCommandError("fork_revision 需要 reason")
        parent = uow.repository.get_run(request.run_id)
        if parent is None:
            raise RunNotFoundError(request.run_id)

        # fromNodeId 必须属于当前 run 钉住定义的知识/实验设计阶段。
        from core.research.workflow.models import WorkflowStageId

        definition = _definition_for_ledger_run(
            parent,
            expected_node_ids=[from_node_id],
        )
        node_spec = next(
            (n for n in definition.nodes if n.nodeId == from_node_id), None
        )
        if node_spec is None:
            raise WorkflowCommandError(f"unknown fromNodeId: {from_node_id}")
        if node_spec.stageId not in (
            WorkflowStageId.EXPERIMENT_DESIGN,
            WorkflowStageId.KNOWLEDGE_COLLECTION,
        ):
            raise WorkflowCommandError("fork_revision 只能从知识/实验设计节点分支")

        if parent.status in ("failed", "cancelled", "archived"):
            raise WorkflowCommandError("failed/cancelled/archived run 不能 fork revision")
        if parent.status == "succeeded":
            self._assert_post_approval_revision_authorized(parent, request.payload)

        now_ms = self._clock()
        command_id = new_id("cmd")
        event_count = 2
        bumped = _bump(uow, request, event_count=event_count, now_ms=now_ms)
        accepted_version, sequence = bumped

        # 新 command 属于父 run（谱系：revision fork 的驱动命令挂在父上）。
        # 必须先插入 command，child attempt/outbox 才能引用它（FK）。
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )

        child_run_id = self._create_revision_fork(
            uow,
            parent=parent,
            from_node_id=from_node_id,
            reason=reason,
            checkpoint_id=str(request.payload.get("checkpointId") or ""),
            requested_by=request.requested_by,
            command_id=command_id,
            now_ms=now_ms,
        )

        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence - 1,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="revision_forked",
                correlation_id=request.idempotency_key,
                payload={
                    "commandId": command_id,
                    "childRunId": child_run_id,
                    "fromNodeId": from_node_id,
                    "reason": reason,
                    "requestedBy": request.requested_by.to_dict(),
                },
                now_ms=now_ms,
            )
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="command_accepted",
                correlation_id=request.idempotency_key,
                payload={
                    "commandId": command_id,
                    "nodeId": from_node_id,
                    "expectedRunVersion": request.expected_run_version,
                    "acceptedRunVersion": accepted_version,
                    "forkOf": request.run_id,
                },
                now_ms=now_ms,
            )
        )
        uow.after_commit(self._wake_worker)
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    @staticmethod
    def _assert_post_approval_revision_authorized(
        parent: Any,
        payload: Mapping[str, Any],
    ) -> None:
        """Authorize a terminal-run fork from durable Challenge review state.

        ``postApprovalRevision`` is only a declaration used by the internal V2
        adapter; it is never authority because the legacy formal command route
        can carry arbitrary payload fields.  The registered output and its
        H1-H4 decisions are the server-owned authorization source.
        """

        output_record_id = str(payload.get("outputRecordId") or "").strip()
        if payload.get("postApprovalRevision") is not True or not output_record_id:
            raise WorkflowCommandError(
                "succeeded run 只能通过正式审核修订入口 fork revision"
            )
        from core.web.services.team_workflow.challenge_question_runs import (
            get_challenge_question_run_detail,
        )

        try:
            detail = get_challenge_question_run_detail(
                str(parent.team_id or ""),
                str(parent.question_id or ""),
                run_id=str(parent.run_id or ""),
            )
        except (TypeError, ValueError) as exc:
            raise WorkflowCommandError(
                "正式审核修订授权记录不可用"
            ) from exc
        record = detail.get("record") if isinstance(detail, Mapping) else None
        record = record if isinstance(record, Mapping) else {}
        gates = record.get("humanGates")
        gates = gates if isinstance(gates, Mapping) else {}
        decisions = gates.get("decisions")
        decisions = decisions if isinstance(decisions, Mapping) else {}
        authorized = (
            str(record.get("recordId") or "") == output_record_id
            and str(record.get("questionId") or "").strip().upper()
            == str(parent.question_id or "").strip().upper()
            and str(record.get("runId") or "") == str(parent.run_id or "")
            and str(record.get("status") or "") == "needs_revision"
            and any(
                str(decision or "") == "revision_requested"
                for decision in decisions.values()
            )
        )
        if not authorized:
            raise WorkflowCommandError(
                "正式审核未授权当前 succeeded run 创建修订"
            )

    def _create_revision_fork(
        self,
        uow,
        *,
        parent: Any,
        from_node_id: str,
        reason: str,
        checkpoint_id: str,
        requested_by: Any,
        command_id: str,
        now_ms: int,
    ) -> str:
        """Create the child revision run (parent lineage) in the same transaction.

        Pure child creation: no runVersion bump, no command, no event — the
        caller owns those. Used by fork_revision and by human revise decisions.
        """
        from core.research.workflow.ledger import RunRecord

        definition = _definition_for_ledger_run(
            parent,
            expected_node_ids=[from_node_id],
        )
        node_spec = next(
            (node for node in definition.nodes if node.nodeId == from_node_id),
            None,
        )
        if node_spec is None:
            raise WorkflowCommandError(
                f"unknown node {from_node_id} in pinned workflow definition"
            )

        child_run_id = new_id("run")
        child_thread_id = child_run_id  # threadId == runId (ADR / spec 7.3)
        if not str(checkpoint_id or "").strip():
            raise WorkflowCommandError("fork_revision 需要 checkpointId")
        input_snapshot: dict[str, Any] = {}
        if parent.input_snapshot_json:
            try:
                loaded_snapshot = json.loads(parent.input_snapshot_json)
            except (TypeError, ValueError) as exc:
                raise WorkflowCommandError(
                    "父 run input snapshot 不可解析，已阻断修订分支创建: "
                    f"parentRunId={parent.run_id} error={exc}"
                ) from exc
            if not isinstance(loaded_snapshot, dict):
                raise WorkflowCommandError(
                    "父 run input snapshot 不是对象，已阻断修订分支创建: "
                    f"parentRunId={parent.run_id}"
                )
            input_snapshot = loaded_snapshot
        input_snapshot = dict(input_snapshot)
        input_snapshot["parentRunId"] = parent.run_id
        input_snapshot["forkedFromCheckpointId"] = checkpoint_id
        input_snapshot["forkCorrelationId"] = command_id

        child = RunRecord(
            run_id=child_run_id,
            team_id=parent.team_id,
            workflow_id=parent.workflow_id,
            workflow_version_id=parent.workflow_version_id,
            thread_id=child_thread_id,
            project_id=parent.project_id,
            question_id=parent.question_id,
            status="created",
            run_version=1,
            last_event_sequence=0,
            input_snapshot_json=json.dumps(input_snapshot, ensure_ascii=False),
            input_snapshot_hash=parent.input_snapshot_hash,
            safety_limits_json=parent.safety_limits_json,
            binding_snapshot_set_id=parent.binding_snapshot_set_id,
            active_node_id=from_node_id,
            parent_run_id=parent.run_id,
            forked_from_checkpoint_id=checkpoint_id,
            completion_kind="revision_fork",
            terminal_reason=reason,
            blocked_problem_json=None,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
            completed_at_ms=None,
            structure_hash=parent.structure_hash,
        )
        uow.repository.insert_run(child)

        node_run_id = f"nr-{child_run_id}-{from_node_id}-a1"
        uow.repository.insert_attempt(
            _attempt_record(
                node_run_id=node_run_id,
                run_id=child_run_id,
                node_id=from_node_id,
                attempt=1,
                status=NodeAttemptStatus.STARTING.value,
                command_id=command_id,
                input_snapshot_hash=parent.input_snapshot_hash,
                started_at_ms=now_ms,
                actor_kind=node_spec.actorKind.value,
            )
        )
        # Durable checkpoint fork outbox — child graph_dispatch is inserted only
        # after CheckpointForkWorker succeeds (crash-safe; no after_commit/daemon).
        uow.repository.insert_outbox(
            _checkpoint_fork_record(
                run_id=child_run_id,
                command_id=command_id,
                node_run_id=node_run_id,
                parent_run_id=parent.run_id,
                checkpoint_id=checkpoint_id,
                resume_node_id=from_node_id,
                now_ms=now_ms,
            )
        )
        return child_run_id

    # ------------------------------------------------- stage-one closeout

    def _prepare_stage_one_command(self, run: Any, request: CommandRequest) -> dict[str, Any]:
        """Domain preparation for the stage-one closeout commands.

        Runs OUTSIDE the ledger transaction.  Returns a prepared-facts dict
        consumed by the transaction-side handler; raises StageOneCommandError
        with a stable HTTP-mappable code on every fail-closed gate.
        """
        from .node_execution_support import NodeExecutionError
        from .stage_one_closeout import project_ledger_stage_one_closeout_record

        try:
            projected = project_ledger_stage_one_closeout_record(
                self._store, run_id=request.run_id
            )
        except NodeExecutionError as exc:
            raise StageOneCommandError(
                str(exc), code=str(getattr(exc, "code", "") or "stage_one_policy_invalid")
            ) from exc
        if projected is None:
            raise StageOneCommandError(
                "stage-one completion policy is missing for this run",
                code="stage_one_policy_invalid",
            )
        record, policy = projected
        node_id = str(request.node_id or "").strip() or policy.closureNodeId
        if request.command is WorkflowCommandKind.BUILD_STAGE_ONE_PACKAGE:
            return self._prepare_stage_one_build(request, record, policy, node_id)
        return self._prepare_stage_one_finalize(request, record, policy, node_id)

    def _stage_one_attempt_or_raise(self, run_id: str, node_id: str) -> Any:
        attempt = self._store.latest_attempt(run_id, node_id)
        if attempt is None:
            raise StageOneCommandError(
                f"stage-one closure attempt is missing for {node_id}",
                code="stage_one_closure_attempt_missing",
            )
        return attempt

    def _prepare_stage_one_build(
        self,
        request: CommandRequest,
        record: dict[str, Any],
        policy: Any,
        node_id: str,
    ) -> dict[str, Any]:
        from .artifact_readback_registry import build_canonical_ref
        from .human_gate_artifacts import canonical_sha256
        from .node_execution_support import NodeExecutionError
        from .result_package import ResultPackageError
        from .result_package_system_adapter import build_stage_one_proposal_package
        from .result_package_v2 import ResultPackageV2Error
        from .stage_one_closeout import evaluate_stage_one_closeout

        existing = self._existing_stage_one_package_result(request.run_id)
        if existing is not None:
            return {"kind": "build", "replayed": existing}

        attempt = self._stage_one_attempt_or_raise(request.run_id, node_id)
        try:
            outcome = evaluate_stage_one_closeout(record, node_id=node_id)
        except NodeExecutionError as exc:
            raise StageOneCommandError(str(exc), code=str(exc.code)) from exc
        if outcome is None or outcome.accepted or outcome.status != "program_review_required":
            raise StageOneCommandError(
                "stage-one evidence is not ready for packaging",
                code="stage_one_package_not_ready",
            )

        snapshot = record.get("inputSnapshot")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        team_id = str(record.get("teamId") or "")
        workflow_run_id = str(record.get("runId") or "")
        authority_run_id = str(snapshot.get("sourceCollectionRunId") or workflow_run_id)
        try:
            package, _plan_alias_written = build_stage_one_proposal_package(
                record,
                team_id=team_id,
                workflow_run_id=workflow_run_id,
                source_collection_run_id=authority_run_id,
                idempotency_key=request.idempotency_key,
            )
        except (ResultPackageError, ResultPackageV2Error) as exc:
            raise StageOneCommandError(
                str(exc),
                code=str(getattr(exc, "code", "") or "challenge_v2_package_failed"),
            ) from exc

        from .workflow_artifact_store import put_workflow_artifact

        artifact_payload = {
            "teamId": team_id,
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": authority_run_id,
            "package": package,
        }
        content_hash = canonical_sha256(artifact_payload)
        put_workflow_artifact(
            team_id,
            kind="research_result_package",
            workflow_run_id=workflow_run_id,
            source_collection_run_id=authority_run_id,
            payload=artifact_payload,
            artifact_identity=request.idempotency_key,
        )
        # The package is durable; before handing it to the challenge program,
        # mirror the run's validated invocation receipts into the team
        # official-model evidence store so the program's official-call gate
        # can match them.  Failing closed here keeps an unregistrable package
        # from entering a program review it could never pass.
        self._ensure_stage_one_official_evidence(record)
        handoff = self._handoff_to_challenge_program(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            authority_run_id=authority_run_id,
            registered_by="stage_one_command_service",
        )
        canonical_ref = build_canonical_ref(
            kind="research_result_package",
            team_id=team_id,
            authority_run_id=authority_run_id,
            content_hash=content_hash,
        )
        return {
            "kind": "build",
            "package": package,
            "content_hash": content_hash,
            "canonical_ref": canonical_ref,
            "authority_run_id": authority_run_id,
            "node_run_id": str(attempt.node_run_id),
            "handoff": handoff,
        }

    def _ensure_stage_one_official_evidence(self, record: dict[str, Any]) -> dict[str, Any]:
        """Register official-model evidence rows for the run's receipts.

        The challenge program's official-call gate intersects the v2 output's
        ``invocation_evidence_refs`` with the team official-model evidence
        store; when that store has no rows for the run the intersection is
        empty and program review is unreachable even though every receipt is
        validated.  The mirror lives on the gate's owner module
        (``challenge_question_runs``) so the write and the gate read resolve
        the same store path.  Registration is idempotent by receipt; any
        registration failure fails closed with a stable stage-one command
        error code.
        """
        from ..challenge_question_runs import (
            ensure_official_model_evidence_for_receipt_refs,
        )
        from .model_invocation_receipt_registry import (
            question_model_invocation_receipts,
        )

        snapshot = record.get("inputSnapshot")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        team_id = str(record.get("teamId") or "")
        workflow_run_id = str(record.get("runId") or "")
        question_id = str(
            snapshot.get("questionId") or record.get("questionId") or ""
        ).strip().upper()
        if not team_id or not workflow_run_id or not question_id:
            raise StageOneCommandError(
                "stage-one run lacks the team/question/run identity required for "
                "official model evidence registration",
                code="stage_one_official_evidence_registration_failed",
            )
        try:
            receipts = question_model_invocation_receipts(
                team_id,
                question_id=question_id,
                workflow_run_id=workflow_run_id,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed naming the stage
            raise StageOneCommandError(
                f"official model evidence registration failed for "
                f"{question_id}/{workflow_run_id}: {exc}",
                code="stage_one_official_evidence_registration_failed",
            ) from exc
        if not receipts:
            # No receipts registered for this run means nothing to mirror;
            # the package builder above already fails closed on the missing
            # receipt authority for real stage-one runs.
            return {"registered": 0, "skipped": 0}
        try:
            return ensure_official_model_evidence_for_receipt_refs(
                team_id,
                question_id=question_id,
                workflow_run_id=workflow_run_id,
                receipts=receipts,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed naming the stage
            raise StageOneCommandError(
                f"official model evidence registration failed for "
                f"{question_id}/{workflow_run_id}: {exc}",
                code="stage_one_official_evidence_registration_failed",
            ) from exc

    def _prepare_stage_one_finalize(
        self,
        request: CommandRequest,
        record: dict[str, Any],
        policy: Any,
        node_id: str,
    ) -> dict[str, Any]:
        from .artifact_readback_registry import build_canonical_ref
        from .human_gate_artifacts import canonical_sha256
        from .node_execution_support import NodeExecutionError
        from .program_candidate_handoff import (
            ProgramCandidateHandoffContractError,
            stage_one_completion_manifest_from_handoff,
        )
        from .stage_one_closeout import evaluate_stage_one_closeout

        attempt = self._stage_one_attempt_or_raise(request.run_id, node_id)
        if str(attempt.status) != "succeeded":
            raise StageOneCommandError(
                "stage-one closure attempt is not durably succeeded",
                code="stage_one_closure_attempt_missing",
            )
        snapshot = record.get("inputSnapshot")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        team_id = str(record.get("teamId") or "")
        workflow_run_id = str(record.get("runId") or "")
        authority_run_id = str(snapshot.get("sourceCollectionRunId") or workflow_run_id)
        handoff = self._handoff_to_challenge_program(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            authority_run_id=authority_run_id,
            registered_by="stage_one_closeout_finalizer",
        )
        try:
            manifest = stage_one_completion_manifest_from_handoff(
                handoff,
                policy_sha256=policy.policySha256,
            )
        except ProgramCandidateHandoffContractError as exc:
            raise StageOneCommandError(
                str(exc), code="stage_one_program_review_not_approved"
            ) from exc
        try:
            outcome = evaluate_stage_one_closeout(
                record,
                node_id=node_id,
                program_handoff=handoff,
            )
        except NodeExecutionError as exc:
            raise StageOneCommandError(str(exc), code=str(exc.code)) from exc
        if outcome is None or not outcome.accepted:
            raise StageOneCommandError(
                "stage-one completion manifest did not authorize acceptance",
                code="stage_one_completion_manifest_invalid",
            )

        from .workflow_artifact_store import put_workflow_artifact

        content_hash = canonical_sha256(manifest)
        put_workflow_artifact(
            team_id,
            kind="stage_one_completion_manifest",
            workflow_run_id=workflow_run_id,
            source_collection_run_id=authority_run_id,
            payload=manifest,
            artifact_identity=request.idempotency_key,
        )
        canonical_ref = build_canonical_ref(
            kind="stage_one_completion_manifest",
            team_id=team_id,
            authority_run_id=authority_run_id,
            content_hash=content_hash,
        )
        return {
            "kind": "finalize",
            "manifest": manifest,
            "outcome": outcome,
            "content_hash": content_hash,
            "canonical_ref": canonical_ref,
            "authority_run_id": authority_run_id,
            "node_run_id": str(attempt.node_run_id),
            "completion_state": policy.completionState,
        }

    def _handoff_to_challenge_program(
        self,
        *,
        team_id: str,
        workflow_run_id: str,
        authority_run_id: str,
        registered_by: str,
    ) -> dict[str, Any]:
        from .program_candidate_handoff import (
            HANDOFF_STATUS_NEEDS_CONTEXT,
            handoff_result_package_to_challenge_program,
        )

        handoff = handoff_result_package_to_challenge_program(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=authority_run_id,
            registered_by=registered_by,
        )
        if str(handoff.get("status") or "") == HANDOFF_STATUS_NEEDS_CONTEXT:
            raise StageOneCommandError(
                str(handoff.get("reason") or "stage-one package handoff needs context"),
                code="stage_one_result_package_missing",
            )
        return handoff

    def _existing_stage_one_package_result(self, run_id: str) -> dict[str, Any] | None:
        """Reuse gate: facts from an already-registered canonical package.

        A persisted ``research_result_package`` receipt is the durable marker;
        the registered facts ride the ``stage_one_package_registered`` event.
        Replaying is zero side effect: no CAS, no command row, no event, no
        artifact write, no second Program registration.
        """
        receipts, events = self._store.read(
            lambda repo: (
                repo.list_artifact_receipts_for_run(run_id),
                repo.list_events(run_id, after_sequence=0, limit=100000),
            )
        )
        if not any(str(row[4] or "") == "research_result_package" for row in receipts):
            return None
        for event in reversed(events):
            if str(event.event_type or "") != "stage_one_package_registered":
                continue
            try:
                payload = json.loads(str(event.payload_json or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            result = payload.get("result")
            if isinstance(result, dict):
                return dict(result)
        # Receipt without its registration event (crash between writes):
        # replay the package facts from the artifact authority itself.
        from .artifact_readback_registry import load_scoped_artifact_payload

        row = next(
            item for item in receipts if str(item[4] or "") == "research_result_package"
        )
        try:
            ref = json.loads(str(row[5] or "{}")).get("canonicalRef") or ""
        except (TypeError, ValueError, json.JSONDecodeError):
            ref = ""
        from .artifact_readback_registry import parse_canonical_ref

        parsed = parse_canonical_ref(str(ref))
        envelope = (
            load_scoped_artifact_payload(
                "research_result_package",
                team_id=str(row[3] or ""),
                authority_run_id=str((parsed or {}).get("authorityRunId") or ""),
                workflow_run_id=run_id,
            )
            if parsed
            else None
        )
        payload = (envelope or {}).get("payload") if isinstance(envelope, dict) else None
        package = (payload or {}).get("package") if isinstance(payload, dict) else None
        return {
            "command": "build_stage_one_package",
            "idempotent": False,
            "packageId": str((package or {}).get("packageId") or ""),
            "contentHash": str(row[7] or ""),
            "programRecordId": "",
            "programReviewStatus": "",
            "sourceCollectionRunId": str((parsed or {}).get("authorityRunId") or ""),
            "artifactRef": str(ref),
        }

    def _sync_stage_one_checkpoint(
        self,
        *,
        run: Any,
        prepared: dict[str, Any],
        idempotency_key: str,
    ) -> str:
        """Post-commit checkpoint sync for an accepted stage-one finalize.

        Two branches, decided by the live thread state:

        - interrupt present -> enqueue the authoritative ``resume_action``
          dispatch (``enqueue_ledger_stage_one_closeout``); the graph worker
          resumes the closure node and ``stage_one_terminal_facts`` closes the
          checkpoint, so the Ledger and the thread stay consistent;
        - thread already END / no interrupt -> write the accepted marker and
          closeout outcome straight into the thread's checkpoint through the
          coordinator's direct ``update_state`` (never ``as_node``).

        Raises after the fact when sync is impossible: the run is already
        durably terminal and a same-key replay re-runs this sync.
        """
        from core.research.workflow.stage_one_completion import (
            STAGE_ONE_CHECKPOINT_FIELD,
        )

        from .stage_one_closeout import enqueue_ledger_stage_one_closeout

        coordinator = (
            self._coordinator_factory() if self._coordinator_factory is not None else None
        )
        if coordinator is None:
            raise StageOneCommandError(
                "stage-one checkpoint coordinator is unavailable",
                code="stage_one_checkpoint_sync_failed",
            )
        outcome = prepared["outcome"]
        update = {
            STAGE_ONE_CHECKPOINT_FIELD: outcome.completion_state,
            "stage_one_closeout": outcome.to_dict(),
        }
        try:
            snapshot = coordinator.snapshot(run.run_id, run.workflow_version_id)
        except Exception as exc:  # noqa: BLE001 - surfaced as a typed failure
            raise StageOneCommandError(
                f"stage-one checkpoint state could not be read: {exc}",
                code="stage_one_checkpoint_sync_failed",
            ) from exc
        pending = snapshot.get("pendingAction") if isinstance(snapshot, dict) else None
        if pending:
            enqueued = enqueue_ledger_stage_one_closeout(
                self._store,
                workflow_run_id=run.run_id,
                outcome=outcome,
                idempotency_key=idempotency_key,
                completed_at_ms=self._clock(),
            )
            if not enqueued:
                raise StageOneCommandError(
                    "stage-one formal closeout could not be enqueued",
                    code="stage_one_formal_closeout_enqueue_failed",
                )
            self._wake_worker()
            return "resume_dispatch"
        try:
            coordinator.apply_state_update(
                run.run_id, run.workflow_version_id, update
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a typed failure
            raise StageOneCommandError(
                f"stage-one checkpoint state could not be written: {exc}",
                code="stage_one_checkpoint_sync_failed",
            ) from exc
        return "checkpoint_state_write"

    def _handle_build_stage_one_package(
        self,
        uow,
        request: CommandRequest,
        request_hash: str,
        prepared: dict[str, Any] | None = None,
    ) -> CommandReceipt:
        prepared = prepared or {}
        replayed = prepared.get("replayed")
        if isinstance(replayed, dict):
            fresh = uow.repository.get_run(request.run_id)
            result = dict(replayed)
            result["idempotent"] = True
            result["replayed"] = True
            return CommandReceipt(
                command_id=new_id("cmd"),
                run_id=request.run_id,
                status="accepted",
                accepted_run_version=int(fresh.run_version) if fresh else None,
                idempotency_key=request.idempotency_key,
                latest_event_sequence=int(fresh.last_event_sequence) if fresh else 0,
                result=result,
            )
        now_ms = self._clock()
        command_id = new_id("cmd")
        handoff = dict(prepared.get("handoff") or {})
        result = {
            "command": "build_stage_one_package",
            "idempotent": False,
            "packageId": str((prepared.get("package") or {}).get("packageId") or ""),
            "contentHash": str(prepared.get("content_hash") or ""),
            "programRecordId": str(handoff.get("recordId") or ""),
            "programReviewStatus": str(handoff.get("reviewStatus") or ""),
            "sourceCollectionRunId": str(prepared.get("authority_run_id") or ""),
            "artifactRef": str(prepared.get("canonical_ref") or ""),
        }
        accepted_version, sequence = _bump(uow, request, event_count=1, now_ms=now_ms)
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        uow.repository.insert_artifact_receipt(
            receipt_id=f"ar-stage1-pkg-{str(prepared.get('content_hash') or '')[:24]}",
            run_id=request.run_id,
            node_run_id=str(prepared.get("node_run_id") or ""),
            team_id=request.team_id,
            artifact_kind="research_result_package",
            canonical_ref_json=_json_dumps({"canonicalRef": prepared.get("canonical_ref")}),
            artifact_version="1.0.0",
            sha256=str(prepared.get("content_hash") or ""),
            domain_revision=_stage_one_domain_revision(
                kind="research_result_package",
                team_id=request.team_id,
                authority_run_id=str(prepared.get("authority_run_id") or ""),
                content_hash=str(prepared.get("content_hash") or ""),
            ),
            materialized=1,
            verified_at_ms=now_ms,
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="stage_one_package_registered",
                correlation_id=request.idempotency_key,
                payload={"commandId": command_id, "result": result},
                now_ms=now_ms,
            )
        )
        return _receipt(
            uow, request, command_id, accepted_version, sequence, now_ms, result=result
        )

    def _handle_finalize_stage_one(
        self,
        uow,
        request: CommandRequest,
        request_hash: str,
        prepared: dict[str, Any] | None = None,
    ) -> CommandReceipt:
        prepared = prepared or {}
        run = uow.repository.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        completion_state = str(prepared.get("completion_state") or "")
        manifest = dict(prepared.get("manifest") or {})
        outcome = prepared.get("outcome")
        if str(run.completion_kind or "") == "stage_one_g1_accepted":
            # Idempotency gate: already terminal through this command — no-op.
            return CommandReceipt(
                command_id=new_id("cmd"),
                run_id=request.run_id,
                status="accepted",
                accepted_run_version=int(run.run_version),
                idempotency_key=request.idempotency_key,
                latest_event_sequence=int(run.last_event_sequence),
                result={
                    "command": "finalize_stage_one",
                    "idempotent": True,
                    "replayed": True,
                    "completionState": completion_state,
                },
            )
        now_ms = self._clock()
        command_id = new_id("cmd")
        result = {
            "command": "finalize_stage_one",
            "idempotent": False,
            "completionState": completion_state,
            "manifestSha256": str(manifest.get("manifestSha256") or ""),
            "programRecordId": str(manifest.get("programRecordId") or ""),
            "programOutputSha256": str(manifest.get("programOutputSha256") or ""),
            "canonicalPackageSha256": str(manifest.get("canonicalPackageHash") or ""),
        }
        accepted_version, sequence = _bump(uow, request, event_count=1, now_ms=now_ms)
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        uow.repository.insert_artifact_receipt(
            receipt_id=f"ar-stage1-man-{str(prepared.get('content_hash') or '')[:24]}",
            run_id=request.run_id,
            node_run_id=str(prepared.get("node_run_id") or ""),
            team_id=request.team_id,
            artifact_kind="stage_one_completion_manifest",
            canonical_ref_json=_json_dumps({"canonicalRef": prepared.get("canonical_ref")}),
            artifact_version="1.0.0",
            sha256=str(prepared.get("content_hash") or ""),
            domain_revision=_stage_one_domain_revision(
                kind="stage_one_completion_manifest",
                team_id=request.team_id,
                authority_run_id=str(prepared.get("authority_run_id") or ""),
                content_hash=str(prepared.get("content_hash") or ""),
            ),
            materialized=1,
            verified_at_ms=now_ms,
        )
        if not uow.repository.update_run_status(
            request.run_id,
            request.team_id,
            RunStatus.SUCCEEDED.value,
            now_ms,
            active_node_id="",
            completion_kind="stage_one_g1_accepted",
            terminal_reason=completion_state or None,
            blocked_problem_json=None,
        ):
            raise WorkflowCommandError("finalize_stage_one 未能更新目标 run")
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="stage_one_closeout_completed",
                correlation_id=request.idempotency_key,
                payload={
                    "commandId": command_id,
                    "result": result,
                    "artifactRefs": list(getattr(outcome, "artifact_refs", ()) or ()),
                    "receiptStages": list(getattr(outcome, "receipt_stages", ()) or ()),
                    "humanGateCount": int(getattr(outcome, "human_gate_count", 0) or 0),
                },
                now_ms=now_ms,
            )
        )
        return _receipt(
            uow, request, command_id, accepted_version, sequence, now_ms, result=result
        )


def _checkpoint_fork_record(
    *,
    run_id: str,
    command_id: str,
    node_run_id: str,
    parent_run_id: str,
    checkpoint_id: str,
    resume_node_id: str,
    now_ms: int,
) -> Any:
    from core.research.workflow.ledger import OutboxRecord

    from .ids import new_id

    payload = {
        "parentRunId": parent_run_id,
        "checkpointId": checkpoint_id,
        "childRunId": run_id,
        "resumeNodeId": resume_node_id,
        "commandId": command_id,
        "nodeRunId": node_run_id,
    }
    return OutboxRecord(
        action_id=new_id("act"),
        run_id=run_id,
        command_id=command_id,
        node_run_id=node_run_id,
        action_kind="checkpoint_fork",
        idempotency_key=f"checkpoint_fork:{run_id}:{checkpoint_id}",
        payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        status="pending",
        attempt_count=0,
        available_at_ms=now_ms,
        lease_owner=None,
        lease_expires_at_ms=None,
        last_problem_json=None,
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
    )


def _bump(uow, request: CommandRequest, *, event_count: int, now_ms: int) -> tuple[int, int]:
    bumped = uow.repository.bump_run_version(
        request.run_id,
        request.team_id,
        request.expected_run_version,
        event_count,
        now_ms,
    )
    if bumped is None:
        raise RunVersionConflictError()
    return bumped


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _stage_one_domain_revision(
    *, kind: str, team_id: str, authority_run_id: str, content_hash: str
) -> str:
    """Stable receipt identity (human_acceptance_artifact precedent)."""
    from .human_gate_artifacts import canonical_sha256

    return canonical_sha256(
        {
            "kind": kind,
            "teamId": team_id,
            "authorityRunId": authority_run_id,
            "contentHash": content_hash,
            "schemaVersion": "1.0.0",
        }
    )[:32]


def _command_record(
    *,
    command_id: str,
    request: CommandRequest,
    request_hash: str,
    accepted_run_version: int,
    now_ms: int,
) -> Any:
    from core.research.workflow.ledger import CommandRecord

    return CommandRecord(
        command_id=command_id,
        run_id=request.run_id,
        team_id=request.team_id,
        node_id=request.node_id,
        command_kind=request.command.value,
        expected_run_version=request.expected_run_version,
        accepted_run_version=accepted_run_version,
        idempotency_key=request.idempotency_key,
        request_hash=request_hash,
        request_json=json.dumps(
            {
                "teamId": request.team_id,
                "runId": request.run_id,
                "nodeId": request.node_id,
                "command": request.command.value,
                "expectedRunVersion": request.expected_run_version,
                "idempotencyKey": request.idempotency_key,
                "payload": dict(request.payload),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        requested_by_json=json.dumps(request.requested_by.to_dict()),
        status="accepted",
        result_json=None,
        problem_json=None,
        created_at_ms=now_ms,
        completed_at_ms=None,
    )


def _definition_for_ledger_run(
    run: Any,
    *,
    expected_node_ids: list[str] | None = None,
) -> Any:
    if not str(getattr(run, "workflow_version_id", "") or "").strip():
        from core.research.workflow.definition import (
            build_challenge_cup_workflow_definition,
        )

        return build_challenge_cup_workflow_definition()
    from core.research.workflow.definition_registry import (
        resolve_definition_for_run_record,
    )

    return resolve_definition_for_run_record(
        {
            "runId": run.run_id,
            "workflowId": run.workflow_id,
            "workflowVersionId": run.workflow_version_id,
            "structureHash": run.structure_hash,
        },
        expected_node_ids=expected_node_ids or [],
    )


def _attempt_record(
    *,
    node_run_id: str,
    run_id: str,
    node_id: str,
    attempt: int,
    status: str,
    command_id: str,
    input_snapshot_hash: str,
    started_at_ms: int,
    retry_of_node_run_id: str | None = None,
    binding_snapshot_id: str | None = None,
    actor_kind: str | None = None,
) -> Any:
    from core.research.workflow.ledger import NodeAttemptRecord

    if not str(actor_kind or "").strip():
        raise WorkflowCommandError("attempt record requires pinned actor_kind")

    return NodeAttemptRecord(
        node_run_id=node_run_id,
        run_id=run_id,
        node_id=node_id,
        attempt=attempt,
        actor_kind=str(actor_kind),
        status=status,
        command_id=command_id,
        binding_snapshot_id=binding_snapshot_id,
        input_snapshot_hash=input_snapshot_hash,
        pending_action_id=None,
        execution_anchor_id=None,
        retry_of_node_run_id=retry_of_node_run_id,
        problem_json=None,
        started_at_ms=started_at_ms,
        updated_at_ms=started_at_ms,
        finished_at_ms=None,
    )


def _node_attempt_for_dispatch(
    *,
    node_run_id: str,
    run_id: str,
    node_id: str,
    attempt: int,
    binding_snapshot_id: str | None = None,
    actor_kind: str,
) -> Any:
    from core.research.workflow.ledger import NodeAttemptRecord

    return NodeAttemptRecord(
        node_run_id=node_run_id,
        run_id=run_id,
        node_id=node_id,
        attempt=attempt,
        actor_kind=actor_kind,
        status="starting",
        command_id="",
        binding_snapshot_id=binding_snapshot_id,
        input_snapshot_hash="",
        pending_action_id=None,
        execution_anchor_id=None,
        retry_of_node_run_id=None,
        problem_json=None,
        started_at_ms=0,
        updated_at_ms=0,
        finished_at_ms=None,
    )


def _graph_dispatch_record(*, uow, run: Any, attempt: Any, command_id: str, now_ms: int) -> Any:
    from .graph_dispatch_factory import build_graph_dispatch_record

    return build_graph_dispatch_record(
        run=run,
        attempt=attempt,
        command_id=command_id,
        dispatch_kind="start",
        now_ms=now_ms,
    )


def _binding_snapshot_id(uow, run_id: str, node_id: str) -> str | None:
    from .graph_dispatch_factory import binding_snapshot_id_for_node

    run = uow.repository.get_run(run_id)
    if run is None or not run.input_snapshot_json:
        return None
    import json

    try:
        input_snapshot = json.loads(run.input_snapshot_json)
    except (TypeError, ValueError):
        return None
    return binding_snapshot_id_for_node(input_snapshot, node_id)


def _event_record(
    *,
    run_id: str,
    sequence: int,
    event_id: str,
    run_version: int,
    event_type: str,
    correlation_id: str,
    payload: dict[str, Any],
    now_ms: int,
) -> Any:
    from core.research.workflow.ledger import EventRecord

    return EventRecord(
        run_id=run_id,
        sequence=sequence,
        event_id=event_id,
        run_version=run_version,
        event_type=event_type,
        actor_json=json.dumps({"actorType": "system", "actorId": "workflow-command-service"}),
        correlation_id=correlation_id,
        causation_id=None,
        payload_json=json.dumps(payload, ensure_ascii=False),
        occurred_at_ms=now_ms,
    )


def _receipt(
    uow,
    request: CommandRequest,
    command_id: str,
    accepted_version: int,
    sequence: int,
    now_ms: int,
    result: Mapping[str, Any] | None = None,
) -> CommandReceipt:
    receipt = CommandReceipt(
        command_id=command_id,
        run_id=request.run_id,
        status="accepted",
        accepted_run_version=accepted_version,
        idempotency_key=request.idempotency_key,
        latest_event_sequence=sequence,
        result=result,
    )
    uow.repository.complete_command(
        command_id, "accepted", now_ms, result_json=json.dumps(receipt.to_dict())
    )
    return receipt


def _input_snapshot_hash(uow, run_id: str) -> str:
    run = uow.repository.get_run(run_id)
    return run.input_snapshot_hash if run else ""


def _human_resume_dispatch(uow, request: CommandRequest, node_run_id: str, receipt: Any, command_id: str, now_ms: int):
    from .graph_dispatch_factory import build_graph_dispatch_record

    run = uow.repository.get_run(request.run_id)
    attempt = uow.repository.get_attempt(node_run_id)
    if run is None or attempt is None:
        raise WorkflowCommandError(f"resume dispatch 缺少 run/attempt: {node_run_id}")
    return build_graph_dispatch_record(
        run=run,
        attempt=attempt,
        command_id=command_id,
        dispatch_kind="resume_human",
        now_ms=now_ms,
        receipt_payload=receipt.to_dict(),
    )


def _normalized_search_envelope(raw: Any) -> dict[str, Any]:
    """Client envelope -> canonical search-envelope fingerprint input.

    Only the three contract fields are accepted: keywords, evidenceTypes and
    the time window; everything else is dropped so the envelope hash can
    never be polluted by client-controlled extras.
    """
    if not isinstance(raw, Mapping):
        return {}
    envelope: dict[str, Any] = {}
    keywords = raw.get("keywords")
    if isinstance(keywords, (list, tuple)):
        envelope["keywords"] = [
            str(item).strip() for item in keywords[:32] if str(item).strip()
        ]
    evidence_types = raw.get("evidenceTypes")
    if isinstance(evidence_types, (list, tuple)):
        envelope["evidenceTypes"] = [
            str(item).strip() for item in evidence_types[:32] if str(item).strip()
        ]
    time_window = raw.get("timeWindow")
    if isinstance(time_window, Mapping):
        envelope["timeWindow"] = dict(time_window)
    return envelope


def _normalized_requirements(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    return {}


def _normalized_source_policy_version(raw: Any) -> str:
    version = str(raw or "").strip()
    return version or "1"


def _knowledge_recovery_actions(
    invocation_view: Mapping[str, Any],
    child_view: Mapping[str, Any] | None,
) -> list[str]:
    """Fail-closed recovery hints derived from durable state only."""
    actions: list[str] = []
    status = str(invocation_view.get("status") or "")
    if status == "awaiting_handoff":
        actions.append("resolve_human_task:knowledge_handoff")
    elif status == "failed":
        actions.append("ensure_knowledge_collection:retry")
    elif status == "cancelled":
        actions.append("ensure_knowledge_collection")
    elif status == "completed" and str(invocation_view.get("handoffState")) == "rejected":
        actions.append("ensure_knowledge_collection")
    child_status = str((child_view or {}).get("status") or "")
    if child_status in {"blocked", "reconciliation_required"}:
        actions.append(f"reconcile_run:{invocation_view.get('childRunId')}")
    if not actions:
        actions.append("none")
    return actions


def _collect_cancel_run_turn_pairs(run_id: str) -> list[tuple[str, str]]:
    """Collect non-terminal (sessionId, turnId) pairs bound to a run record.

    Sources (both live in the JSON run record, not the ledger):
    ``taskBundles[].subtasks[]`` — only entries still in an active status
    (mirrors ``task_bundle_lifecycle._ACTIVE_SUBTASK_STATUSES`` so already
    cancelled/failed/succeeded subtasks are never touched) and
    ``bindingSnapshots[]`` (sessionId+taskId+turnId bindings, filtered again
    by the chat_turn snapshot status at stop time).
    """
    from .store import WorkflowRunStore
    from .task_bundle_lifecycle import _ACTIVE_SUBTASK_STATUSES

    record = WorkflowRunStore().get_run(run_id)
    if record is None:
        return []
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for bundle in record.get("taskBundles") or []:
        if not isinstance(bundle, Mapping):
            continue
        for subtask in bundle.get("subtasks") or []:
            if not isinstance(subtask, Mapping):
                continue
            if str(subtask.get("status") or "") not in _ACTIVE_SUBTASK_STATUSES:
                continue
            session_id = str(subtask.get("sessionId") or "").strip()
            turn_id = str(subtask.get("turnId") or "").strip()
            if session_id and turn_id and (session_id, turn_id) not in seen:
                seen.add((session_id, turn_id))
                pairs.append((session_id, turn_id))
    for snapshot in record.get("bindingSnapshots") or []:
        if not isinstance(snapshot, Mapping):
            continue
        session_id = str(snapshot.get("sessionId") or "").strip()
        turn_id = str(snapshot.get("turnId") or "").strip()
        if session_id and turn_id and (session_id, turn_id) not in seen:
            seen.add((session_id, turn_id))
            pairs.append((session_id, turn_id))
    return pairs


def _close_cancel_run_turn(session_service: Any, session_id: str, turn_id: str) -> str:
    """Stop one in-flight turn or close its stale chat_turn snapshot.

    Returns an outcome label; raises on unexpected failures so the caller can
    isolate per-turn errors.

    When the in-process running set no longer knows the session,
    ``request_stop_session_turn`` early-returns WITHOUT persisting any
    terminal state (control.py early-exit branch).  In that case this writes
    the terminal snapshot directly through ``_persist_chat_turn_work_run`` —
    the canonical single writer for chat_turn records, whose terminal status
    also clears the work-run index activeRunId.  Chosen over
    ``_settle_stale_chat_turn_work_run`` because the latter additionally
    rewrites conversation state, appends runtime notices and clears turn
    control — recovery side effects owned by the stale-run reconciler, not
    needed to close a cancelled run's turn.
    """
    store = getattr(session_service, "_WORK_RUN_STORE", None)
    snapshot = store.load_snapshot("chat_turn", turn_id) if store is not None else None
    if snapshot is not None:
        status = str(
            snapshot.get("status") or snapshot.get("currentPhase") or ""
        ).strip().lower()
        if status not in _CHAT_TURN_OPEN_STATUSES:
            return "already_terminal"
    if session_service._is_session_running(session_id):
        session_service.request_stop_session_turn(session_id, expected_turn_id=turn_id)
        return "stop_requested"
    session_service._persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status="stopped",
        summary=session_service.text_for(
            session_service.get_web_language(),
            zh="研究工作流已取消，本轮已停止。",
            en="The research workflow was cancelled; this turn was stopped.",
        ),
        finished_at=session_service._now_timestamp(),
        updated_at=session_service._now_timestamp(),
    )
    return "snapshot_closed"
