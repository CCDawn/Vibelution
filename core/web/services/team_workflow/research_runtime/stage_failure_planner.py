"""LLM failure-review planner for self-blocked source-collection stage tasks.

Production incident (session-20261017-203847-419417): the relations agent
was rejected, parked itself at ``blocked`` with a question whose answer sat
in the context it had already read, and nothing reviewed the failure or
issued a remediation instruction — the loop never closed.  The first layer
(the deterministic one-shot ``writebackRemediationContract``) answers
rejections the system can diff locally; this module is the second layer:
a maintenance-thread sweep that detects a first blocked attempt, shows an
LLM planner a bounded failure scene, and lands exactly one verdict:

- actionable ``retry_task`` → persist ``plannerDirective`` on the canonical
  task record (injected as ``context["plannerDirective"]``) and submit one
  idempotent ``RETRY_NODE``;
- actionable ``rerun_source_finding`` → persist the directive only (the
  existing ``succeeded_node_rerun`` machinery owns any automatic rerun);
- ``escalate_human`` (or a failed LLM review call) → build the frozen
  ``stage_task_planner_escalation`` anomaly-inbox item and persist it on
  the task record as ``anomalyEscalation``;
- no review credentials → fail-open: no retry, no escalation, one bounded
  scene event (credential flapping must not spam the inbox).

One planning attempt per task: tasks carrying ``plannerDirective`` or
``anomalyEscalation`` are never re-planned. A matching retry directive is a
durable submission intent, recovered with the same attempt-scoped command
identity after an interrupted submission.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from typing import Any

from core.research.workflow.contracts import (
    ActorRef,
    CommandRequest,
    ContractValidationError,
    WorkflowCommandKind,
)
from core.research.workflow.knowledge_sideflow_definition import (
    KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
)

from .human_gate_artifacts import canonical_sha256
from .knowledge_sideflow_trigger import (
    CHALLENGE_CUP_TEAM_ID,
    _stage_task_turn_is_active,
    _stage_task_updated_at_ms,
)

logger = logging.getLogger(__name__)

#: Retry/escalation reason stamped on commands, directives and events.
STAGE_FAILURE_PLANNER_REASON = "stage_failure_planner"
#: Frozen retry-taxonomy code for the human-required escalation item.
STAGE_TASK_PLANNER_ESCALATION_CODE = "stage_task_planner_escalation"
PLANNER_DIRECTIVE_SCHEMA_VERSION = 1

# Grace window before a possibly in-flight task is planned: the planner must
# never race a live agent turn that could still write back on its own.  Same
# default as the self-parked needs_review retry (15 minutes), env override.
STAGE_PLANNER_GRACE_MS_DEFAULT = 900_000
STAGE_PLANNER_GRACE_ENV = "VIBELUTION_STAGE_PLANNER_GRACE_MS"

# Fail-open cooldown (in-memory, per process): a task whose planning attempt
# degraded (no credentials / invalid verdict) is not re-submitted to the LLM
# on every sweep tick; the cooldown forgets on restart, which keeps the
# path fail-open rather than sticky.
_FAIL_OPEN_COOLDOWN_MS = 60 * 60 * 1000
_FAIL_OPEN_SEEN: dict[str, int] = {}
_FAIL_OPEN_SEEN_LIMIT = 256

# Bounded scene assembly clips.
_SCENE_SUMMARY_MAX_CHARS = 4000
_SCENE_ALLOWED_REFS_LIMIT = 80
_SCENE_RELATION_CARD_LIMIT = 20
_SCENE_RELATION_CARD_FIELDS = (
    "claimEvidenceId",
    "candidateId",
    "sourceId",
    "quote",
    "supportLevel",
)


def _planner_grace_ms() -> int:
    raw = str(os.environ.get(STAGE_PLANNER_GRACE_ENV) or "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return STAGE_PLANNER_GRACE_MS_DEFAULT
        if value > 0:
            return value
    return STAGE_PLANNER_GRACE_MS_DEFAULT


def _fail_open_key(run_id: str, node_run_id: str) -> str:
    return f"{run_id}:{node_run_id}"


def _fail_open_recently_seen(run_id: str, node_run_id: str, *, now_ms: int) -> bool:
    last = _FAIL_OPEN_SEEN.get(_fail_open_key(run_id, node_run_id))
    return last is not None and max(0, now_ms - last) < _FAIL_OPEN_COOLDOWN_MS


def _mark_fail_open(run_id: str, node_run_id: str, *, now_ms: int) -> None:
    key = _fail_open_key(run_id, node_run_id)
    while len(_FAIL_OPEN_SEEN) >= _FAIL_OPEN_SEEN_LIMIT:
        oldest = next(iter(_FAIL_OPEN_SEEN), None)
        if oldest is None:
            break
        _FAIL_OPEN_SEEN.pop(oldest, None)
    _FAIL_OPEN_SEEN[key] = now_ms


def reset_stage_failure_planner_fail_open_for_tests() -> None:
    """Test seam: forget the in-memory fail-open cooldown."""
    _FAIL_OPEN_SEEN.clear()


def _record_planner_event(
    event_code: str,
    *,
    outcome: str,
    fields: Mapping[str, Any],
    level: str = "info",
) -> None:
    """Emit one bounded scene event; ids / lengths / verdict only.

    The failure scene and the directive text are business data (the directive
    lives on the task record); they never enter scene events.
    """
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow",
            "stage_failure_planner",
            event_code,
            message="Stage failure planner observed.",
            level=level,
            outcome=outcome,
            fields=dict(fields),
            lifecycle=False,
        )
    except Exception:  # noqa: BLE001 - diagnostics must never fail the sweep
        return


def _planning_ready_task(
    task: Mapping[str, Any] | None,
    *,
    now_ms: int,
) -> bool:
    """First-blocked, unplanned, provably-not-in-flight gate."""

    if not isinstance(task, Mapping):
        return False
    if str(task.get("status") or "").strip().lower() not in {"blocked", "needs_review"}:
        return False
    if isinstance(task.get("plannerDirective"), Mapping) and task.get(
        "plannerDirective"
    ):
        return False
    if isinstance(task.get("anomalyEscalation"), Mapping) and task.get(
        "anomalyEscalation"
    ):
        return False
    if _stage_task_turn_is_active(task):
        return False
    updated_at_ms = _stage_task_updated_at_ms(task)
    if updated_at_ms is None:
        return False
    return max(0, int(now_ms) - updated_at_ms) >= _planner_grace_ms()


def _clip_text(value: Any, max_chars: int) -> str:
    return str(value or "").strip()[:max_chars]


def build_stage_failure_scene(
    task: Mapping[str, Any],
    *,
    team_id: str,
    source_run_id: str,
) -> dict[str, Any]:
    """Assemble the bounded failure-scene payload for one planning call.

    Identity + the authoritative writeback summary + structured failure
    markers + the L1 remediation contract + the evidence-authority views
    (allowed refs, relation binding cards, candidate count).  Candidate
    bodies are never included — counts and binding cards only.
    """

    writeback = (
        task.get("writeback") if isinstance(task.get("writeback"), Mapping) else {}
    )
    contract = (
        task.get("writebackRemediationContract")
        if isinstance(task.get("writebackRemediationContract"), Mapping)
        else {}
    )
    scene: dict[str, Any] = {
        "schemaVersion": 1,
        "teamId": team_id,
        "sourceCollectionRunId": source_run_id,
        "taskId": _clip_text(task.get("taskId"), 160),
        "stageId": _clip_text(task.get("stageId"), 80),
        "status": _clip_text(task.get("status"), 80),
        "agentRole": _clip_text(task.get("agentRole"), 80),
        "summary": _clip_text(writeback.get("summary"), _SCENE_SUMMARY_MAX_CHARS),
        "failureMarkers": {
            "agentRequestedStatus": _clip_text(
                writeback.get("agentRequestedStatus"), 80
            ),
            "evidenceReviewRequiredReason": _clip_text(
                writeback.get("evidenceReviewRequiredReason"), 400
            ),
            "hasQuoteAnchorRemediation": bool(task.get("quoteAnchorRemediation")),
            "blockedReason": _clip_text(task.get("blockedReason"), 400),
        },
        "remediationContract": dict(contract) if contract else {},
        "updatedAt": _clip_text(task.get("updatedAt"), 80),
    }
    try:
        from .artifact_readback_registry import (
            load_allowed_evidence_refs,
            load_relation_evidence_context,
        )

        allowed_refs = list(
            load_allowed_evidence_refs(
                team_id=team_id,
                authority_run_id=source_run_id,
                workflow_run_id=_clip_text(task.get("workflowRunId"), 160),
            )
        )
        cards = list(
            load_relation_evidence_context(
                team_id=team_id,
                authority_run_id=source_run_id,
                workflow_run_id=_clip_text(task.get("workflowRunId"), 160),
            )
        )
    except Exception:  # noqa: BLE001 - scene degrades to counts-free form
        allowed_refs = []
        cards = []
    scene["allowedEvidenceRefs"] = allowed_refs[:_SCENE_ALLOWED_REFS_LIMIT]
    scene["allowedEvidenceRefCount"] = len(allowed_refs)
    scene["relationEvidenceCardCount"] = len(cards)
    scene["relationEvidenceSample"] = [
        {field: _clip_text(card.get(field), 400) for field in _SCENE_RELATION_CARD_FIELDS}
        for card in cards[:_SCENE_RELATION_CARD_LIMIT]
        if isinstance(card, Mapping)
    ]
    try:
        from ..source_collection.candidates import list_candidate_store

        store_view = list_candidate_store(
            team_id,
            limit=1,
            run_id=source_run_id,
        )
        scene["candidateCount"] = int(store_view.get("candidateCount") or 0)
    except Exception:  # noqa: BLE001 - count is optional context
        scene["candidateCount"] = None
    return scene


def _persist_task_fields(
    team_id: str,
    source_run_id: str,
    task: dict[str, Any],
) -> bool:
    """Upsert the canonical task record; False (never raises) on failure."""

    from ..source_collection.stage_session import _service

    try:
        _service()._upsert_source_collection_stage_session_task(
            team_id, source_run_id, task
        )
        return True
    except Exception as exc:  # noqa: BLE001 - persistence failure skips the retry
        logger.warning(
            "stage failure planner task persist failed teamId=%s runId=%s "
            "taskId=%s errorType=%s",
            team_id,
            source_run_id,
            task.get("taskId", ""),
            type(exc).__name__,
        )
        return False


def _submit_planner_retry(
    *,
    store: Any,
    command_service: Any,
    run: Any,
    attempt: Any,
    node_id: str,
    now_ms: int,
) -> bool:
    """Submit exactly one idempotent RETRY_NODE for the planned attempt."""

    fresh, latest = store.read(
        lambda repo: (repo.get_run(run.run_id), repo.latest_attempt(run.run_id, node_id))
    )
    if (
        fresh is None
        or fresh.team_id != run.team_id
        or str(fresh.status or "").strip() != "blocked"
        or str(fresh.active_node_id or "").strip() != node_id
        or latest is None
        or latest.node_run_id != attempt.node_run_id
        or str(latest.status or "").strip() != "blocked"
        or bool(str(latest.retry_of_node_run_id or "").strip())
    ):
        return False
    identity_hash = canonical_sha256(
        {
            "runId": run.run_id,
            "nodeId": node_id,
            "nodeRunId": attempt.node_run_id,
            "reason": STAGE_FAILURE_PLANNER_REASON,
        }
    )
    # A committed retry is already complete even if its caller lost the
    # receipt. Do not replay it with a newer version and a different hash.
    idempotency_key = f"stage-failure-planner:{identity_hash}"
    if store.get_command_by_idempotency(run.run_id, idempotency_key) is not None:
        return False
    command_service.submit(
        CommandRequest(
            command_id=f"cmd-stage-planner-{identity_hash[:24]}",
            run_id=run.run_id,
            team_id=run.team_id,
            command=WorkflowCommandKind.RETRY_NODE,
            node_id=node_id,
            expected_run_version=int(fresh.run_version),
            idempotency_key=idempotency_key,
            payload={
                "reason": STAGE_FAILURE_PLANNER_REASON,
                "retryOfNodeRunId": attempt.node_run_id,
            },
            requested_by=ActorRef("system", "stage-failure-planner"),
            requested_at_ms=now_ms,
        )
    )
    return True


def _pending_planner_retry(task: Any, *, run: Any, attempt: Any, node_id: str) -> bool:
    """Only the original blocked attempt may consume a durable retry intent."""
    if not isinstance(task, Mapping):
        return False
    directive = task.get("plannerDirective")
    return (
        isinstance(directive, Mapping)
        and directive.get("recommendation") == "retry_task"
        and directive.get("runId") == run.run_id
        and directive.get("nodeId") == node_id
        and directive.get("nodeRunId") == attempt.node_run_id
        and str(task.get("status") or "").strip().lower() in {"blocked", "needs_review"}
        and not task.get("anomalyEscalation")
        and not _stage_task_turn_is_active(task)
    )


def _try_planner_retry(**kwargs: Any) -> bool:
    """Submission failure leaves the durable directive available next pass."""
    try:
        return _submit_planner_retry(**kwargs)
    except Exception as exc:  # noqa: BLE001 - directive is already durable
        logger.warning(
            "stage failure planner retry submit failed runId=%s "
            "nodeRunId=%s errorType=%s",
            kwargs["run"].run_id,
            kwargs["attempt"].node_run_id,
            type(exc).__name__,
        )
        return False


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _build_planner_escalation(
    *,
    team_id: str,
    task: Mapping[str, Any],
    run: Any,
    attempt: Any,
    node_id: str,
    source_run_id: str,
    recommendation: str,
    justification: str,
    now_iso: str,
) -> dict[str, Any]:
    """Project the frozen human-required code into one anomaly-inbox item.

    Same synthetic-state pattern as ``_escalate_collection_auto_retry_exhausted``
    (hypothesis_first_chain): the pure ``build_anomaly_inbox`` projector owns
    the canonical item shape; the result is persisted on the task record.
    ``sourceKind=collection_run`` scopes the blocked_run item to the child run.
    """

    task_id = _clip_text(task.get("taskId"), 160)
    stage_id = _clip_text(task.get("stageId"), 80)
    message = (
        f"阶段任务 {task_id}（{stage_id}，run {run.run_id}）被代理停靠后，"
        f"失败审查规划师判定不可自动补救（{recommendation}）："
        f"{_clip_text(justification, 300)}"
    )
    items: list[dict[str, Any]] = []
    try:
        from .anomaly_inbox_service import build_anomaly_inbox

        inbox = build_anomaly_inbox(
            {
                "teamId": team_id,
                "problems": [
                    {
                        "code": STAGE_TASK_PLANNER_ESCALATION_CODE,
                        "category": "execution",
                        "sourceKind": "collection_run",
                        "sourceId": str(run.run_id),
                        "message": message,
                        "detectedAt": now_iso,
                        "taskId": task_id,
                        "nodeId": str(node_id),
                    }
                ],
            },
            generated_at=now_iso,
        )
        items = [item.to_dict() for item in inbox.items]
    except Exception:  # noqa: BLE001 - escalation must not depend on the projector
        items = []
    return {
        "status": "emitted" if items else "unavailable",
        "taxonomyCode": STAGE_TASK_PLANNER_ESCALATION_CODE,
        "taskId": task_id,
        "stageId": stage_id,
        "runId": str(run.run_id),
        "nodeId": str(node_id),
        "nodeRunId": str(attempt.node_run_id),
        "sourceCollectionRunId": source_run_id,
        "recommendation": recommendation,
        "justification": _clip_text(justification, 500),
        "emittedAt": now_iso,
        "items": items,
    }


def plan_stage_task_failure_remediation(
    store: Any,
    command_service: Any,
    *,
    limit: int = 1,
    now_ms: int | None = None,
    llm: Mapping[str, Any] | None = None,
    planner: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
    now_provider: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """Plan one bounded remediation pass over self-blocked stage tasks.

    Returns a small counters dict for the maintenance log.  Never raises per
    candidate; the runtime wrapper adds the outer never-raise net.
    """

    from core.web.services.team_workflow.llm_review_runners import (
        build_failure_review_planner,
    )

    now = int(now_ms if now_ms is not None else (now_provider() if now_provider else time.time() * 1000))
    remaining = max(0, int(limit))
    summary = {
        "scanned": 0,
        "planned": 0,
        "retried": 0,
        "escalated": 0,
        "degraded": 0,
        "skipped": 0,
    }
    if remaining == 0:
        return summary

    def load_candidates(repo: Any) -> list[tuple[Any, Any, str]]:
        candidates: list[tuple[Any, Any, str]] = []
        for run in repo.list_runs_for_team(
            CHALLENGE_CUP_TEAM_ID,
            KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
        ):
            node_id = str(run.active_node_id or "").strip()
            if str(run.status or "").strip() != "blocked" or not node_id:
                continue
            attempt = repo.latest_attempt(run.run_id, node_id)
            if (
                attempt is None
                or str(attempt.status or "").strip() != "blocked"
                or bool(str(attempt.retry_of_node_run_id or "").strip())
            ):
                continue
            try:
                snapshot = json.loads(str(run.input_snapshot_json or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            source_run_id = str(
                (snapshot or {}).get("sourceCollectionRunId") or ""
            ).strip()
            if source_run_id:
                candidates.append((run, attempt, source_run_id))
        return candidates

    candidates = store.read(load_candidates)
    if not candidates:
        return summary

    planner_fn = planner
    if planner_fn is None:
        planner_fn = build_failure_review_planner(llm)

    from .stage_task_remediation import source_stage_task_for_node_run

    for run, attempt, source_run_id in candidates:
        if remaining <= 0:
            break
        summary["scanned"] += 1
        node_id = str(run.active_node_id or "").strip()
        base_fields = {
            "runId": str(run.run_id or ""),
            "nodeRunId": str(attempt.node_run_id or ""),
            "stageId": "",
            "taskId": "",
        }
        try:
            task = source_stage_task_for_node_run(
                team_id=run.team_id,
                source_run_id=source_run_id,
                node_run_id=attempt.node_run_id,
            )
        except Exception:  # noqa: BLE001 - one unreadable task must not stop the pass
            summary["skipped"] += 1
            continue
        pending_retry = _pending_planner_retry(task, run=run, attempt=attempt, node_id=node_id)
        if not pending_retry and not _planning_ready_task(task, now_ms=now):
            summary["skipped"] += 1
            continue
        task = dict(task)
        base_fields = {
            **base_fields,
            "stageId": _clip_text(task.get("stageId"), 80),
            "taskId": _clip_text(task.get("taskId"), 160),
        }
        if not pending_retry and _fail_open_recently_seen(run.run_id, attempt.node_run_id, now_ms=now):
            summary["skipped"] += 1
            continue
        if pending_retry:
            retried = _try_planner_retry(
                store=store, command_service=command_service, run=run,
                attempt=attempt, node_id=node_id, now_ms=now,
            )
            summary["retried"] += int(retried)
            # An unavailable/stale retry intent must not monopolize the
            # batch and starve other blocked tasks on every maintenance tick.
            remaining -= int(retried)
            _record_planner_event(
                "stage_failure_planner.retry_recovered",
                outcome="retry_submitted" if retried else "retry_pending",
                fields=base_fields,
            )
            continue

        remaining -= 1

        if planner_fn is None:
            _mark_fail_open(run.run_id, attempt.node_run_id, now_ms=now)
            _record_planner_event(
                "stage_failure_planner.llm_unavailable",
                outcome="fail_open",
                level="warning",
                fields=base_fields,
            )
            summary["degraded"] += 1
            continue

        scene = build_stage_failure_scene(
            task,
            team_id=run.team_id,
            source_run_id=source_run_id,
        )
        try:
            verdict = planner_fn(scene)
        except ContractValidationError as exc:
            # Invalid / contradictory model verdict: fail-open (no retry, no
            # escalation) so a broken model answer never spams the inbox.
            _mark_fail_open(run.run_id, attempt.node_run_id, now_ms=now)
            _record_planner_event(
                "stage_failure_planner.invalid_verdict",
                outcome="fail_open",
                level="warning",
                fields={**base_fields, "errorType": type(exc).__name__},
            )
            summary["degraded"] += 1
            continue
        except Exception as exc:  # noqa: BLE001 - LLM review call failure escalates
            now_iso = _utc_now_iso()
            escalation = _build_planner_escalation(
                team_id=run.team_id,
                task=task,
                run=run,
                attempt=attempt,
                node_id=node_id,
                source_run_id=source_run_id,
                recommendation="escalate_human",
                justification=f"规划师审查调用失败：{type(exc).__name__}",
                now_iso=now_iso,
            )
            task["anomalyEscalation"] = escalation
            if _persist_task_fields(run.team_id, source_run_id, task):
                summary["escalated"] += 1
            else:
                summary["degraded"] += 1
            _record_planner_event(
                "stage_failure_planner.llm_failed",
                outcome="escalated"
                if escalation.get("status") == "emitted"
                else "escalation_unavailable",
                level="warning",
                fields={
                    **base_fields,
                    "errorType": type(exc).__name__,
                    "anomalyItemCount": len(escalation.get("items") or []),
                },
            )
            continue

        recommendation = str(verdict.get("recommendation") or "").strip()
        actionable = bool(verdict.get("actionable"))
        verdict_fields = {
            **base_fields,
            "actionable": actionable,
            "recommendation": recommendation,
        }
        if recommendation == "escalate_human" or not actionable:
            now_iso = _utc_now_iso()
            escalation = _build_planner_escalation(
                team_id=run.team_id,
                task=task,
                run=run,
                attempt=attempt,
                node_id=node_id,
                source_run_id=source_run_id,
                recommendation="escalate_human",
                justification=str(verdict.get("justification") or ""),
                now_iso=now_iso,
            )
            task["anomalyEscalation"] = escalation
            if _persist_task_fields(run.team_id, source_run_id, task):
                summary["escalated"] += 1
                _record_planner_event(
                    "stage_failure_planner.escalated",
                    outcome="escalated",
                    level="warning",
                    fields={
                        **verdict_fields,
                        "anomalyItemCount": len(escalation.get("items") or []),
                    },
                )
            else:
                summary["degraded"] += 1
                _record_planner_event(
                    "stage_failure_planner.persist_failed",
                    outcome="failed",
                    level="warning",
                    fields=verdict_fields,
                )
            continue

        directive = {
            "schemaVersion": PLANNER_DIRECTIVE_SCHEMA_VERSION,
            "recommendation": recommendation,
            "directive": str(verdict.get("directive") or "").strip(),
            "targetFix": dict(verdict.get("targetFix") or {}),
            "justification": str(verdict.get("justification") or "").strip(),
            "recordedAt": _utc_now_iso(),
            "runId": str(run.run_id),
            "nodeId": node_id,
            "nodeRunId": str(attempt.node_run_id),
        }
        task["plannerDirective"] = directive
        if not _persist_task_fields(run.team_id, source_run_id, task):
            summary["degraded"] += 1
            _record_planner_event(
                "stage_failure_planner.persist_failed",
                outcome="failed",
                level="warning",
                fields=verdict_fields,
            )
            continue
        summary["planned"] += 1
        if recommendation == "retry_task":
            retried = _try_planner_retry(
                store=store,
                command_service=command_service,
                run=run,
                attempt=attempt,
                node_id=node_id,
                now_ms=now,
            )
            if retried:
                summary["retried"] += 1
            _record_planner_event(
                "stage_failure_planner.planned",
                outcome="retry_submitted" if retried else "directive_only",
                fields=verdict_fields,
            )
        else:
            # rerun_source_finding: no automatic submission — the directive
            # records the advice; the existing succeeded_node_rerun machinery
            # owns any automatic source-finding rerun.
            _record_planner_event(
                "stage_failure_planner.planned",
                outcome="directive_only",
                fields=verdict_fields,
            )
    return summary
