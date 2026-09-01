"""Durable bounded ResearchTaskBundle lifecycle for Agent NodeRuns."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from core.research.workflow.contracts import ContractValidationError, ResearchTaskBundle
from core.research.workflow.models import WorkflowNodeSpec

from .node_execution_support import build_event, iso, replace_by_id, utc_now
from .store import WorkflowRunStore


class TaskBundleError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


_ACTIVE_SUBTASK_STATUSES = {"pending", "queued", "running"}
_TERMINAL_SUBTASK_STATUSES = {"succeeded", "failed", "cancelled"}


def derive_task_bundle_status(subtasks: Sequence[Mapping[str, Any]]) -> str:
    """Derive bundle state from ordered subtask state, without completion-order drift."""
    statuses = [
        str(
            (
                item.get("status")
                if isinstance(item, Mapping)
                else getattr(item, "status", None)
            )
            or "pending"
        )
        for item in subtasks
    ]
    if not statuses:
        raise TaskBundleError(
            "task bundle must contain at least one subtask",
            code="empty_task_bundle",
        )
    unknown = sorted(
        set(statuses) - _ACTIVE_SUBTASK_STATUSES - _TERMINAL_SUBTASK_STATUSES
    )
    if unknown:
        raise TaskBundleError(
            f"unknown subtask status: {', '.join(unknown)}",
            code="invalid_task_bundle_state",
        )
    if "failed" in statuses:
        return "failed"
    if "running" in statuses:
        return "running"
    if "pending" in statuses or "queued" in statuses:
        return "pending"
    if all(status == "succeeded" for status in statuses):
        return "succeeded"
    return "cancelled"


def _select_subtask_index(
    bundle: Mapping[str, Any],
    subtask_id: str | None,
) -> int:
    subtasks = list(bundle.get("subtasks") or [])
    if not subtasks:
        raise TaskBundleError(
            "task bundle has no subtasks",
            code="empty_task_bundle",
        )
    requested = str(subtask_id or "").strip()
    if not requested:
        if len(subtasks) != 1:
            raise TaskBundleError(
                "subtaskId is required for a multi-subtask bundle",
                code="subtask_id_required",
            )
        return 0
    for index, subtask in enumerate(subtasks):
        if str(subtask.get("subtaskId") or "") == requested:
            return index
    raise TaskBundleError(
        f"subtask not found: {requested}",
        code="unknown_subtask",
    )


def _bundle_for_id(record: Mapping[str, Any], bundle_id: str) -> dict[str, Any]:
    bundle = next(
        (
            dict(item)
            for item in record.get("taskBundles") or []
            if item.get("bundleId") == bundle_id
        ),
        None,
    )
    if bundle is None:
        raise TaskBundleError("task bundle not found", code="unknown_task_bundle")
    return bundle


def task_bundle_id(node_run_id: str) -> str:
    return f"bundle-{hashlib.sha256(node_run_id.encode()).hexdigest()[:16]}"


def ensure_task_bundle_capacity(
    record: dict[str, Any],
    *,
    node_run_id: str,
    subtask_count: int = 1,
    max_concurrency: int | None = None,
) -> None:
    if isinstance(subtask_count, bool) or not isinstance(subtask_count, int) or subtask_count < 1:
        raise TaskBundleError(
            "subtask_count must be a positive integer",
            code="invalid_subtask_count",
        )
    bundle_id = task_bundle_id(node_run_id)
    if any(
        item.get("bundleId") == bundle_id
        for item in record.get("taskBundles") or []
    ):
        return
    policy = dict((record.get("inputSnapshot") or {}).get("budgetPolicy") or {})
    max_parallel_tasks = int(policy.get("maxParallelTasks") or 0)
    if max_concurrency is not None and (
        isinstance(max_concurrency, bool)
        or not isinstance(max_concurrency, int)
        or max_concurrency < 1
        or max_concurrency > subtask_count
    ):
        raise TaskBundleError(
            "max_concurrency must be an integer between 1 and subtask count",
            code="invalid_max_concurrency",
        )
    active_subtasks = 0
    for current_bundle in record.get("taskBundles") or []:
        active_count = sum(
            1
            for subtask in current_bundle.get("subtasks") or []
            if subtask.get("status") in _ACTIVE_SUBTASK_STATUSES
        )
        configured_concurrency = int(
            current_bundle.get("maxConcurrency") or len(current_bundle.get("subtasks") or []) or 1
        )
        active_subtasks += min(active_count, configured_concurrency)
    requested_slots = min(subtask_count, max_concurrency or subtask_count)
    if max_parallel_tasks < 1 or active_subtasks + requested_slots > max_parallel_tasks:
        raise TaskBundleError(
            "budgetPolicy.maxParallelTasks must allow this task bundle",
            code="parallel_budget_exhausted",
        )


def _normalise_subtask_specs(
    *,
    node_run_id: str,
    node_spec: WorkflowNodeSpec,
    input_snapshot_hash: str,
    budget_reservation_ref: str,
    deadline_seconds: int,
    now: Any,
    subtask_specs: Sequence[Mapping[str, Any]] | None,
    selected_candidate_ids: Sequence[str] | None,
    selection_id: str,
) -> list[dict[str, Any]]:
    if subtask_specs is None:
        if selected_candidate_ids:
            if not str(selection_id or "").strip():
                raise TaskBundleError(
                    "selection_id is required when creating candidate subtasks",
                    code="invalid_subtask_scope",
                )
            subtask_specs = [
                {
                    "selectionId": selection_id,
                    "candidateId": candidate_id,
                }
                for candidate_id in selected_candidate_ids
            ]
        else:
            # Preserve the v2 single-subtask shape and identifiers exactly.
            subtask_specs = [{}]
    if not isinstance(subtask_specs, Sequence) or isinstance(subtask_specs, (str, bytes)):
        raise TaskBundleError(
            "subtask_specs must be a non-empty list",
            code="invalid_subtask_specs",
        )
    if not subtask_specs:
        raise TaskBundleError(
            "subtask_specs must be a non-empty list",
            code="invalid_subtask_specs",
        )

    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_candidate_ids: set[str] = set()
    for index, raw_spec in enumerate(subtask_specs):
        if not isinstance(raw_spec, Mapping):
            raise TaskBundleError(
                "each subtask spec must be an object",
                code="invalid_subtask_specs",
            )
        spec = dict(raw_spec)
        candidate_id = str(spec.get("candidateId") or "").strip()
        scoped_selection_id = str(spec.get("selectionId") or selection_id or "").strip()
        scope_value = spec.get("scope")
        if scope_value is not None and hasattr(scope_value, "to_dict"):
            scope_value = scope_value.to_dict()
        if isinstance(scope_value, Mapping):
            candidate_id = candidate_id or str(scope_value.get("candidateId") or "").strip()
            scoped_selection_id = scoped_selection_id or str(
                scope_value.get("selectionId") or ""
            ).strip()
        if scope_value is None:
            if scoped_selection_id and candidate_id:
                scope_value = {
                    "kind": "workflow_candidate",
                    "selectionId": scoped_selection_id,
                    "candidateId": candidate_id,
                }
            else:
                scope_value = {
                    "kind": "workflow_node_root",
                    "nodeRunId": node_run_id,
                }
        if not isinstance(scope_value, Mapping) or not scope_value:
            raise TaskBundleError(
                "subtask scope must be a non-empty object",
                code="invalid_subtask_scope",
            )
        scope = dict(scope_value)
        if str(scope.get("kind") or "") == "workflow_candidate" and (
            not candidate_id or not scoped_selection_id
        ):
            raise TaskBundleError(
                "candidate subtask scope requires selectionId and candidateId",
                code="invalid_subtask_scope",
            )
        if candidate_id and not scoped_selection_id:
            raise TaskBundleError(
                "candidate subtask scope requires selectionId",
                code="invalid_subtask_scope",
            )
        if candidate_id and str(scope.get("candidateId") or "") not in {"", candidate_id}:
            raise TaskBundleError(
                "subtask candidateId conflicts with scope",
                code="invalid_subtask_scope",
            )
        if scoped_selection_id and str(scope.get("selectionId") or "") not in {
            "",
            scoped_selection_id,
        }:
            raise TaskBundleError(
                "subtask selectionId conflicts with scope",
                code="invalid_subtask_scope",
            )
        if candidate_id:
            if candidate_id in seen_candidate_ids:
                raise TaskBundleError(
                    "candidateId values must be unique within a task bundle",
                    code="duplicate_candidate_id",
                )
            seen_candidate_ids.add(candidate_id)

        if index == 0 and len(subtask_specs) == 1 and not candidate_id and not spec.get("subtaskId"):
            subtask_id = f"subtask-{node_run_id}"
        else:
            subtask_id = str(spec.get("subtaskId") or "").strip()
            if not subtask_id:
                if scoped_selection_id and candidate_id:
                    subtask_id = f"{node_run_id}:{scoped_selection_id}:{candidate_id}"
                else:
                    subtask_id = f"{node_run_id}:subtask:{index + 1}"
        if subtask_id in seen_ids:
            raise TaskBundleError(
                "subtaskId values must be unique",
                code="duplicate_subtask_id",
            )
        seen_ids.add(subtask_id)

        attempt_value = spec.get("attempt", 1)
        if isinstance(attempt_value, bool) or not isinstance(attempt_value, int) or attempt_value < 1:
            raise TaskBundleError(
                "subtask attempt must be an integer >= 1",
                code="invalid_subtask_attempt",
            )
        acceptance = {
            "artifactKinds": list(node_spec.producesArtifactKinds),
            "inputSnapshotHash": input_snapshot_hash,
        }
        raw_acceptance = spec.get("acceptanceContract")
        if raw_acceptance is not None:
            if not isinstance(raw_acceptance, Mapping) or not raw_acceptance:
                raise TaskBundleError(
                    "subtask acceptanceContract must be a non-empty object",
                    code="invalid_subtask_specs",
                )
            acceptance.update(dict(raw_acceptance))

        deadline_at = str(spec.get("deadlineAt") or "").strip()
        if not deadline_at:
            raw_deadline_seconds = spec.get("deadlineSeconds", deadline_seconds)
            if (
                isinstance(raw_deadline_seconds, bool)
                or not isinstance(raw_deadline_seconds, int)
                or raw_deadline_seconds < 1
            ):
                raise TaskBundleError(
                    "subtask deadlineSeconds must be an integer >= 1",
                    code="invalid_subtask_specs",
                )
            deadline_at = iso(now + timedelta(seconds=raw_deadline_seconds))

        output_refs = spec.get("outputArtifactRefs") or []
        if not isinstance(output_refs, list):
            raise TaskBundleError(
                "subtask outputArtifactRefs must be a list",
                code="invalid_subtask_specs",
            )
        result.append(
            {
                "subtaskId": subtask_id,
                "role": str(spec.get("role") or node_spec.primaryRoleKey).strip(),
                "scope": scope,
                "attempt": attempt_value,
                "acceptanceContract": acceptance,
                "budgetReservationRef": str(
                    spec.get("budgetReservationRef") or budget_reservation_ref
                ).strip(),
                "deadlineAt": deadline_at,
                "status": "pending",
                "taskId": str(spec.get("taskId") or "").strip(),
                "sessionId": str(spec.get("sessionId") or "").strip(),
                "turnId": str(spec.get("turnId") or "").strip(),
                "outputArtifactRefs": [str(item) for item in output_refs],
            }
        )
    return result


def create_agent_task_bundle(
    store: WorkflowRunStore,
    *,
    record: dict[str, Any],
    node_run: dict[str, Any],
    node_spec: WorkflowNodeSpec,
    model_route: dict[str, Any],
    budget_reservation_ref: str,
    idempotency_key: str,
    deadline_seconds: int,
    subtask_specs: Sequence[Mapping[str, Any]] | None = None,
    max_concurrency: int | None = None,
    selected_candidate_ids: Sequence[str] | None = None,
    selection_id: str = "",
    maxConcurrency: int | None = None,
) -> dict[str, Any]:
    bundle_id = task_bundle_id(str(node_run["nodeRunId"]))
    existing = next(
        (
            dict(item)
            for item in record.get("taskBundles") or []
            if item.get("bundleId") == bundle_id
        ),
        None,
    )
    if existing is not None:
        if existing.get("idempotencyKey") != idempotency_key:
            raise TaskBundleError(
                "NodeRun already has a task bundle with another idempotencyKey",
                code="task_bundle_idempotency_conflict",
            )
        return existing
    now = utc_now()
    objective = str(
        ((record.get("inputSnapshot") or {}).get("researchObjectiveContract") or {}).get(
            "question"
        )
        or node_spec.label
    )
    specs = _normalise_subtask_specs(
        node_run_id=str(node_run["nodeRunId"]),
        node_spec=node_spec,
        input_snapshot_hash=str(node_run["inputSnapshotHash"]),
        budget_reservation_ref=budget_reservation_ref,
        deadline_seconds=deadline_seconds,
        now=now,
        subtask_specs=subtask_specs,
        selected_candidate_ids=selected_candidate_ids,
        selection_id=selection_id,
    )
    if max_concurrency is not None and maxConcurrency is not None and max_concurrency != maxConcurrency:
        raise TaskBundleError(
            "max_concurrency conflicts with maxConcurrency",
            code="invalid_max_concurrency",
        )
    requested_concurrency = (
        max_concurrency if max_concurrency is not None else maxConcurrency
    )
    if requested_concurrency is None:
        policy_max_parallel = int(
            ((record.get("inputSnapshot") or {}).get("budgetPolicy") or {}).get(
                "maxParallelTasks"
            )
            or 0
        )
        requested_concurrency = min(
            len(specs),
            3,
            policy_max_parallel if policy_max_parallel > 0 else len(specs),
        )
    if (
        isinstance(requested_concurrency, bool)
        or not isinstance(requested_concurrency, int)
        or requested_concurrency < 1
        or requested_concurrency > len(specs)
    ):
        raise TaskBundleError(
            "maxConcurrency must be an integer between 1 and subtask count",
            code="invalid_max_concurrency",
        )
    ensure_task_bundle_capacity(
        record,
        node_run_id=str(node_run["nodeRunId"]),
        subtask_count=len(specs),
        max_concurrency=requested_concurrency,
    )
    raw_bundle = {
        "bundleId": bundle_id,
        "runId": record["runId"],
        "parentNodeRunId": node_run["nodeRunId"],
        "objective": objective,
        "inputArtifactRefs": list(node_run.get("artifactRefs") or []),
        "subtasks": specs,
        "maxConcurrency": requested_concurrency,
        "aggregationContract": {
            "mode": "all_required",
            "requiredArtifactKinds": list(node_spec.producesArtifactKinds),
        },
        "status": derive_task_bundle_status(specs),
    }
    try:
        bundle = {
            **ResearchTaskBundle.from_dict(raw_bundle).to_dict(),
            "nodeId": node_run["nodeId"],
            "modelRoutingDecisionId": model_route["decisionId"],
            "idempotencyKey": idempotency_key,
            "createdAt": iso(now),
            "cancelReason": "",
        }
    except ContractValidationError as exc:
        raise TaskBundleError(str(exc), code="invalid_task_bundle") from exc

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        bundles = list(current.get("taskBundles") or [])
        prior = next(
            (item for item in bundles if item.get("bundleId") == bundle_id),
            None,
        )
        if prior is not None:
            if prior.get("idempotencyKey") != idempotency_key:
                raise TaskBundleError(
                    "NodeRun task bundle changed before commit",
                    code="task_bundle_idempotency_conflict",
                )
            return current
        return {
            **current,
            "taskBundles": [*bundles, bundle],
            "modelRoutingDecisions": [
                *(current.get("modelRoutingDecisions") or []),
                model_route,
            ],
        }

    persisted = store.mutate_run(str(record["runId"]), mutation)
    return next(
        item for item in persisted.get("taskBundles") or [] if item["bundleId"] == bundle_id
    )


def bind_agent_task_bundle(
    store: WorkflowRunStore,
    *,
    run_id: str,
    bundle_id: str,
    task_id: str,
    session_id: str,
    turn_id: str,
    subtask_id: str | None = None,
    attempt: int | None = None,
) -> dict[str, Any]:
    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        bundles = list(current.get("taskBundles") or [])
        bundle = _bundle_for_id(current, bundle_id)
        subtask_index = _select_subtask_index(bundle, subtask_id)
        subtasks = [dict(item) for item in bundle.get("subtasks") or []]
        subtask = subtasks[subtask_index]
        if attempt is not None and (
            isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or attempt < 1
            or attempt != int(subtask.get("attempt") or 1)
        ):
            raise TaskBundleError(
                "task bundle binding attempt does not match subtask",
                code="task_bundle_attempt_conflict",
            )
        if subtask.get("taskId"):
            if (
                subtask.get("taskId") == task_id
                and subtask.get("sessionId") == session_id
                and (
                    not str(turn_id or "").strip()
                    or subtask.get("turnId") == str(turn_id).strip()
                )
            ):
                return current
            raise TaskBundleError(
                "task bundle is already bound to another task",
                code="task_bundle_binding_conflict",
            )
        derived_status = derive_task_bundle_status(subtasks)
        if subtask.get("status") in {"succeeded", "failed", "cancelled"} or (
            derived_status in {"succeeded", "cancelled"}
        ):
            raise TaskBundleError(
                f"task bundle cannot bind in {derived_status} state",
                code="invalid_task_bundle_state",
            )
        subtask.update(
            {
                "status": "running",
                "taskId": task_id,
                "sessionId": session_id,
                "turnId": turn_id,
            }
        )
        subtasks[subtask_index] = subtask
        bundle.update(
            {
                "status": derive_task_bundle_status(subtasks),
                "subtasks": subtasks,
            }
        )
        replace_by_id(bundles, "bundleId", bundle_id, bundle)
        return {**current, "taskBundles": bundles}

    persisted = store.mutate_run(run_id, mutation)
    return next(
        item for item in persisted.get("taskBundles") or [] if item["bundleId"] == bundle_id
    )


def complete_task_bundle_records(
    record: dict[str, Any],
    *,
    node_run_id: str,
    subtask_id: str | None = None,
    output_artifact_refs: list[str],
    completed_at: str,
    attempt: int | None = None,
) -> list[dict[str, Any]]:
    bundles = list(record.get("taskBundles") or [])
    bundle = next(
        (
            dict(item)
            for item in bundles
            if item.get("parentNodeRunId") == node_run_id
        ),
        None,
    )
    if bundle is None:
        return bundles
    subtasks = [dict(item) for item in bundle.get("subtasks") or []]
    if subtask_id is None and len(subtasks) > 1:
        if bundle.get("status") != "succeeded":
            raise TaskBundleError(
                "multi-subtask bundle must finish every candidate before aggregation",
                code="task_bundle_incomplete",
            )
        bundle["aggregationArtifactRefs"] = list(output_artifact_refs)
        bundle["completedAt"] = str(bundle.get("completedAt") or completed_at)
        replace_by_id(bundles, "bundleId", str(bundle["bundleId"]), bundle)
        return bundles
    subtask_index = _select_subtask_index(bundle, subtask_id)
    subtask = subtasks[subtask_index]
    if attempt is not None and (
        isinstance(attempt, bool)
        or not isinstance(attempt, int)
        or attempt < 1
        or attempt != int(subtask.get("attempt") or 1)
    ):
        raise TaskBundleError(
            "task bundle completion attempt does not match subtask",
            code="task_bundle_attempt_conflict",
        )
    if subtask.get("status") == "succeeded":
        if list(subtask.get("outputArtifactRefs") or []) == list(output_artifact_refs):
            return bundles
        raise TaskBundleError(
            "subtask already completed with different artifacts",
            code="task_bundle_completion_conflict",
        )
    if bundle.get("status") == "succeeded":
        raise TaskBundleError(
            "task bundle is succeeded but subtask is not completed",
            code="invalid_task_bundle_state",
        )
    if subtask.get("status") != "running":
        raise TaskBundleError(
            f"subtask must be running, got {subtask.get('status')}",
            code="invalid_task_bundle_state",
        )
    subtask.update(
        {
            "status": "succeeded",
            "outputArtifactRefs": list(output_artifact_refs),
        }
    )
    subtasks[subtask_index] = subtask
    next_status = derive_task_bundle_status(subtasks)
    bundle.update({"status": next_status, "subtasks": subtasks})
    if next_status == "succeeded":
        bundle["completedAt"] = completed_at
    replace_by_id(bundles, "bundleId", str(bundle["bundleId"]), bundle)
    return bundles


def _promote_next_pending_candidate(subtasks: list[dict[str, Any]]) -> bool:
    """Claim the next pending candidate for dispatch as ``queued``.

    Must run inside ``store.mutate_run`` so a terminal subtask hands its
    fan-out concurrency slot to exactly one queued candidate, even with
    concurrent terminal events.
    """

    for index, subtask in enumerate(subtasks):
        if (
            str(subtask.get("taskId") or "").strip()
            or str(subtask.get("status") or "") != "pending"
        ):
            continue
        scope = subtask.get("scope")
        scope = dict(scope) if isinstance(scope, dict) else {}
        if not (
            str(scope.get("selectionId") or "").strip()
            and str(scope.get("candidateId") or "").strip()
        ):
            continue
        subtask.update({"status": "queued", "queuedAt": iso(utc_now())})
        subtasks[index] = subtask
        return True
    return False


def _dispatch_queued_candidate_subtasks(
    store: WorkflowRunStore,
    *,
    run_id: str,
    node_run_id: str,
) -> None:
    # Late import: agent_node_execution imports this module at load time.
    from .agent_node_execution import dispatch_queued_candidate_subtasks

    dispatch_queued_candidate_subtasks(store, run_id=run_id, node_run_id=node_run_id)


def complete_agent_task_bundle_subtask(
    store: WorkflowRunStore,
    *,
    run_id: str,
    node_run_id: str,
    subtask_id: str,
    output_artifact_refs: list[str],
    attempt: int,
    dispatch_pending: bool = True,
) -> dict[str, Any]:
    """Persist one candidate completion without mutating sibling subtasks."""

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        bundles = complete_task_bundle_records(
            current,
            node_run_id=node_run_id,
            subtask_id=subtask_id,
            output_artifact_refs=output_artifact_refs,
            completed_at=iso(utc_now()),
            attempt=attempt,
        )
        bundle = next(
            (
                dict(item)
                for item in bundles
                if item.get("parentNodeRunId") == node_run_id
            ),
            None,
        )
        # The completed subtask freed one fan-out slot; hand it to the next
        # pending candidate atomically under the mutate_run lock.
        if bundle is not None:
            subtasks = [dict(item) for item in bundle.get("subtasks") or []]
            if _promote_next_pending_candidate(subtasks):
                bundle.update({"subtasks": subtasks})
                replace_by_id(bundles, "bundleId", str(bundle["bundleId"]), bundle)
        return {**current, "taskBundles": bundles}

    persisted = store.mutate_run(run_id, mutation)
    bundle = next(
        (
            dict(item)
            for item in persisted.get("taskBundles") or []
            if item.get("parentNodeRunId") == node_run_id
        ),
        None,
    )
    if bundle is None:
        raise TaskBundleError("task bundle not found", code="unknown_task_bundle")
    if dispatch_pending:
        _dispatch_queued_candidate_subtasks(
            store, run_id=run_id, node_run_id=node_run_id
        )
    return bundle


def fail_agent_task_bundle_subtask(
    store: WorkflowRunStore,
    *,
    run_id: str,
    node_run_id: str,
    subtask_id: str,
    failure_code: str,
    failure_summary: str,
    attempt: int | None = None,
    dispatch_pending: bool = True,
) -> dict[str, Any]:
    """Fail exactly one subtask while preserving every sibling outcome."""

    normalized_code = str(failure_code or "").strip()
    normalized_summary = str(failure_summary or "").strip()
    if not normalized_code or not normalized_summary:
        raise TaskBundleError(
            "subtask failure requires failure code and summary",
            code="invalid_subtask_failure",
        )
    failed_at = iso(utc_now())

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        bundles = list(current.get("taskBundles") or [])
        bundle = next(
            (
                dict(item)
                for item in bundles
                if item.get("parentNodeRunId") == node_run_id
            ),
            None,
        )
        if bundle is None:
            raise TaskBundleError("task bundle not found", code="unknown_task_bundle")
        subtask_index = _select_subtask_index(bundle, subtask_id)
        subtasks = [dict(item) for item in bundle.get("subtasks") or []]
        selected = subtasks[subtask_index]
        current_attempt = int(selected.get("attempt") or 1)
        if attempt is not None and (
            isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or attempt != current_attempt
        ):
            raise TaskBundleError(
                "task bundle failure attempt does not match subtask",
                code="task_bundle_attempt_conflict",
            )
        if selected.get("status") == "failed":
            if (
                str(selected.get("failureCode") or "") == normalized_code
                and str(selected.get("failureSummary") or "") == normalized_summary
            ):
                return current
            raise TaskBundleError(
                "subtask already failed with a different failure",
                code="task_bundle_failure_conflict",
            )
        if selected.get("status") not in _ACTIVE_SUBTASK_STATUSES:
            raise TaskBundleError(
                f"subtask must be active, got {selected.get('status')}",
                code="invalid_task_bundle_state",
            )
        freed_slot = selected.get("status") == "running" and bool(
            str(selected.get("taskId") or "").strip()
        )
        selected.update(
            {
                "status": "failed",
                "failureCode": normalized_code,
                "failureSummary": normalized_summary,
                "failedAt": failed_at,
            }
        )
        subtasks[subtask_index] = selected
        if freed_slot:
            # The failed running candidate freed one fan-out slot; hand it to
            # the next pending candidate atomically under the mutate_run lock.
            _promote_next_pending_candidate(subtasks)
        bundle.update(
            {
                "status": derive_task_bundle_status(subtasks),
                "failureCode": normalized_code,
                "failureSummary": normalized_summary,
                "failedSubtaskId": str(subtask_id),
                "subtasks": subtasks,
            }
        )
        replace_by_id(bundles, "bundleId", str(bundle["bundleId"]), bundle)
        return {**current, "taskBundles": bundles}

    persisted = store.mutate_run(run_id, mutation)
    if dispatch_pending:
        _dispatch_queued_candidate_subtasks(
            store, run_id=run_id, node_run_id=node_run_id
        )
    return next(
        item
        for item in persisted.get("taskBundles") or []
        if item.get("parentNodeRunId") == node_run_id
    )


def replace_agent_task_bundle_subtask(
    store: WorkflowRunStore,
    *,
    run_id: str,
    bundle_id: str,
    subtask_id: str,
    retry_task_id: str,
    task_id: str,
    session_id: str,
    turn_id: str,
    attempt: int | None = None,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Bind one formal retry to a failed subtask, idempotently.

    The prior task id is part of the compare-and-swap contract.  A retry can
    never replace a sibling or overwrite a task that has already been
    rebound by another request.
    """

    normalized_retry_task_id = str(retry_task_id or "").strip()
    normalized_task_id = str(task_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    normalized_idempotency_key = str(idempotency_key or "").strip()
    if not all(
        (
            normalized_task_id,
            normalized_session_id,
            normalized_turn_id,
        )
    ):
        raise TaskBundleError(
            "formal subtask retry requires previous and new task/session/turn anchors",
            code="invalid_subtask_retry",
        )

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        bundles = list(current.get("taskBundles") or [])
        bundle = _bundle_for_id(current, bundle_id)
        subtask_index = _select_subtask_index(bundle, subtask_id)
        subtasks = [dict(item) for item in bundle.get("subtasks") or []]
        selected = subtasks[subtask_index]
        current_attempt = int(selected.get("attempt") or 1)
        requested_attempt = attempt
        if (
            selected.get("status") in _ACTIVE_SUBTASK_STATUSES
            and str(selected.get("taskId") or "") == normalized_task_id
            and str(selected.get("sessionId") or "") == normalized_session_id
            and str(selected.get("turnId") or "") == normalized_turn_id
            and requested_attempt is not None
            and int(selected.get("attempt") or 1) == requested_attempt
            and (
                not normalized_idempotency_key
                or str(selected.get("retryIdempotencyKey") or "")
                == normalized_idempotency_key
            )
        ):
            return current
        unbound_retry = not normalized_retry_task_id
        next_attempt = current_attempt if unbound_retry else current_attempt + 1
        requested_attempt = next_attempt if requested_attempt is None else requested_attempt
        if (
            isinstance(requested_attempt, bool)
            or not isinstance(requested_attempt, int)
            or requested_attempt != next_attempt
        ):
            raise TaskBundleError(
                "formal subtask retry attempt must increment exactly once",
                code="task_bundle_attempt_conflict",
            )
        if selected.get("status") != "failed":
            raise TaskBundleError(
                f"formal subtask retry requires failed state, got {selected.get('status')}",
                code="subtask_retry_not_failed",
            )
        persisted_task_id = str(selected.get("taskId") or "")
        if unbound_retry and persisted_task_id:
            raise TaskBundleError(
                "unbound subtask retry requires a failed subtask without a taskId",
                code="subtask_retry_source_conflict",
            )
        if not unbound_retry and persisted_task_id != normalized_retry_task_id:
            raise TaskBundleError(
                "formal subtask retry source task does not match the persisted subtask",
                code="subtask_retry_source_conflict",
            )
        selected.update(
            {
                "status": "running",
                "attempt": requested_attempt,
                "taskId": normalized_task_id,
                "sessionId": normalized_session_id,
                "turnId": normalized_turn_id,
                "outputArtifactRefs": [],
                "failureCode": "",
                "failureSummary": "",
                "failedAt": "",
                "retrySourceTaskId": normalized_retry_task_id,
                "retryIdempotencyKey": normalized_idempotency_key,
            }
        )
        subtasks[subtask_index] = selected
        bundle.update(
            {
                "status": derive_task_bundle_status(subtasks),
                "failureCode": "",
                "failureSummary": "",
                "failedSubtaskId": "",
                "subtasks": subtasks,
            }
        )
        replace_by_id(bundles, "bundleId", bundle_id, bundle)
        return {**current, "taskBundles": bundles}

    persisted = store.mutate_run(run_id, mutation)
    return next(
        item
        for item in persisted.get("taskBundles") or []
        if item.get("bundleId") == bundle_id
    )


def cancel_task_bundle(
    store: WorkflowRunStore,
    *,
    run_id: str,
    bundle_id: str,
    reason: str,
    idempotency_key: str,
    subtask_id: str | None = None,
) -> dict[str, Any]:
    if not reason.strip() or not idempotency_key.strip():
        raise TaskBundleError(
            "bundle cancellation requires reason and idempotencyKey",
            code="invalid_task_bundle_cancel",
        )
    record = store.get_run(run_id)
    if record is None:
        raise TaskBundleError(f"Unknown runId: {run_id}", code="unknown_run")
    bundle = _bundle_for_id(record, bundle_id)
    if subtask_id:
        selected_index = _select_subtask_index(bundle, subtask_id)
        selected_subtask_ids = {
            str(bundle["subtasks"][selected_index].get("subtaskId") or "")
        }
    else:
        selected_subtask_ids = {
            str(item.get("subtaskId") or "")
            for item in bundle.get("subtasks") or []
            if item.get("status") in _ACTIVE_SUBTASK_STATUSES
        }
    prior_receipt = next(
        (
            item
            for item in record.get("commandReceipts") or []
            if item.get("command") == "cancel_task_bundle"
            and item.get("idempotencyKey") == idempotency_key
        ),
        None,
    )
    if prior_receipt is not None:
        return record

    stop_results: list[dict[str, Any]] = []
    from core.web.services.session_service import request_stop_session_turn

    for subtask in bundle.get("subtasks") or []:
        session_id = str(subtask.get("sessionId") or "")
        turn_id = str(subtask.get("turnId") or "")
        if (
            str(subtask.get("subtaskId") or "") in selected_subtask_ids
            and subtask.get("status") == "running"
            and session_id
        ):
            stop_results.append(
                request_stop_session_turn(session_id, expected_turn_id=turn_id)
            )
    now = iso(utc_now())

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        if any(
            item.get("command") == "cancel_task_bundle"
            and item.get("idempotencyKey") == idempotency_key
            for item in current.get("commandReceipts") or []
        ):
            return current
        bundles = list(current.get("taskBundles") or [])
        current_bundle = _bundle_for_id(current, bundle_id)
        current_subtasks = [dict(item) for item in current_bundle.get("subtasks") or []]
        changed = False
        for index, item in enumerate(current_subtasks):
            if (
                str(item.get("subtaskId") or "") in selected_subtask_ids
                and item.get("status") in _ACTIVE_SUBTASK_STATUSES
            ):
                current_subtasks[index] = {
                    **item,
                    "status": "cancelled",
                    "cancelReason": reason,
                    "cancelledAt": now,
                }
                changed = True
        if not changed and current_bundle.get("status") not in {"cancelled", "succeeded", "failed"}:
            raise TaskBundleError(
                "task bundle has no cancellable subtasks",
                code="invalid_task_bundle_state",
            )
        next_status = derive_task_bundle_status(current_subtasks)
        current_bundle.update(
            {
                "status": next_status,
                "subtasks": current_subtasks,
            }
        )
        if next_status == "cancelled":
            current_bundle.update({"cancelReason": reason, "cancelledAt": now})
        replace_by_id(bundles, "bundleId", bundle_id, current_bundle)
        node_runs = list(current.get("nodeRuns") or [])
        node_run = next(
            (
                dict(item)
                for item in node_runs
                if item.get("nodeRunId") == current_bundle["parentNodeRunId"]
            ),
            None,
        )
        if (
            next_status == "cancelled"
            and node_run is not None
            and node_run.get("status") == "running"
        ):
            node_run.update(
                {
                    "status": "cancelled",
                    "finishedAt": now,
                    "failureCode": "task_bundle_cancelled",
                    "failureSummary": reason,
                }
            )
            replace_by_id(node_runs, "nodeRunId", node_run["nodeRunId"], node_run)
        receipt = {
            "receiptId": f"receipt-{uuid.uuid4().hex[:10]}",
            "runId": run_id,
            "nodeId": current_bundle.get("nodeId", ""),
            "nodeRunId": current_bundle["parentNodeRunId"],
            "command": "cancel_task_bundle",
            "idempotencyKey": idempotency_key,
            "subtaskId": str(subtask_id or ""),
            "status": "applied",
            "recordedAt": now,
            "stopResults": stop_results,
        }
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=current_bundle.get("nodeId", ""),
            nodeRunId=current_bundle["parentNodeRunId"],
            type="TaskBundleCancelled",
            summary={"bundleId": bundle_id, "reason": reason},
        )
        return {
            **current,
            "status": "blocked" if next_status == "cancelled" else current.get("status"),
            "blockedReason": "task_bundle_cancelled" if next_status == "cancelled" else current.get("blockedReason", ""),
            "taskBundles": bundles,
            "nodeRuns": node_runs,
            "commandReceipts": [
                *(current.get("commandReceipts") or []),
                receipt,
            ],
            "events": [*(current.get("events") or []), event],
        }

    return store.mutate_run(run_id, mutation)


def reconcile_expired_task_bundles(
    store: WorkflowRunStore,
    *,
    run_id: str,
) -> dict[str, Any]:
    record = store.get_run(run_id)
    if record is None:
        raise TaskBundleError(f"Unknown runId: {run_id}", code="unknown_run")
    now = iso(utc_now())
    expired = [
        dict(bundle)
        for bundle in record.get("taskBundles") or []
        if bundle.get("status") in {"pending", "queued", "running"}
        and any(
            str(subtask.get("deadlineAt") or "") < now
            for subtask in bundle.get("subtasks") or []
            if subtask.get("status") in _ACTIVE_SUBTASK_STATUSES
        )
    ]
    for bundle in expired:
        for subtask in bundle.get("subtasks") or []:
            if (
                subtask.get("status") not in _ACTIVE_SUBTASK_STATUSES
                or str(subtask.get("deadlineAt") or "") >= now
            ):
                continue
            subtask_id = str(subtask.get("subtaskId") or "")
            record = cancel_task_bundle(
                store,
                run_id=run_id,
                bundle_id=str(bundle["bundleId"]),
                subtask_id=subtask_id,
                reason="task bundle deadline exceeded",
                idempotency_key=(
                    f"expire:{bundle['bundleId']}:{subtask_id}:"
                    f"{subtask.get('deadlineAt') or ''}"
                ),
            )
    return record
