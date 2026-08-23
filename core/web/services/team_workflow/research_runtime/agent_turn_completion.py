"""Wait for canonical Task/Turn terminal and collect scoped domain artifact refs.

Production RealDomainPorts must not invent deterministic example.local payloads.
After Session/Task/Turn reaches a terminal success status, this module reconciles
Source Collection stage writeback and builds refs from real SC / ClaimEvidence
stores scoped by teamId + sourceCollectionRunId + workflowRunId.
"""

from __future__ import annotations

import json
import time
from typing import Any

from core.research.workflow.contracts import PendingAction

from .domain_ports import AgentTaskHandle

_SUCCESS_TERMINAL_STATUSES = frozenset({"ready", "completed", "done", "success"})
_FAILURE_TERMINAL_STATUSES = frozenset(
    {
        "failed",
        "failed_provider",
        "failed_runtime",
        "error",
        "cancelled",
        "canceled",
        "stopped",
        "stopped_by_user",
        "superseded",
        "paused_limit",
        "needs_continue",
    }
)

DEFAULT_AGENT_TURN_TIMEOUT_MS = 120_000


def _persist_question_model_invocation_receipts(
    snapshot: dict[str, Any],
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
) -> list[dict[str, Any]]:
    raw = snapshot.get("modelInvocationReceipts")
    receipts = [item for item in list(raw or []) if isinstance(item, dict)]
    if not receipts:
        legacy = snapshot.get("modelInvocationReceipt")
        receipts = [legacy] if isinstance(legacy, dict) else []
    if not receipts or not question_id:
        return []
    from .model_invocation_receipt_registry import (
        register_question_model_invocation_receipts,
    )

    return register_question_model_invocation_receipts(
        team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
        receipts=receipts,
    )


def _formal_receipt_writeback_context(
    snapshot: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str, str, dict[str, Any]]:
    """Return a validated receipt and its explicit stage/policy binding.

    The stage is read only from the receipt scope.  A formal workflow node or
    task name must never be guessed as ``generation``/``review``/``revision``;
    an incomplete or malformed receipt therefore falls back to the existing
    legacy evidence path and remains ineligible for the formal package gate.
    """

    raw = snapshot.get("modelInvocationReceipt") if isinstance(snapshot, dict) else None
    if not isinstance(raw, dict):
        return None, "", "", {}
    try:
        from core.research.workflow.contracts.model_invocation_receipt import (
            ModelInvocationReceipt,
        )

        receipt = ModelInvocationReceipt.from_dict(raw)
    except (TypeError, ValueError, KeyError):
        return None, "", "", {}
    scope = dict(receipt.scope or {})
    stage_id = str(
        scope.get("stageId") or scope.get("stage_id") or ""
    ).strip().lower()
    policy_sha256 = str(
        scope.get("modelPolicySha256") or scope.get("model_policy_sha256") or ""
    ).strip().lower()
    if stage_id not in {"generation", "review", "revision"} or len(policy_sha256) != 64:
        return None, "", "", {}
    usage = {
        "source": "canonical_turn_outcome",
        "provider": receipt.provider,
        "model": receipt.model,
        "llmModelId": "",
    }
    for source_key, target_key in (
        ("inputTokens", "inputTokens"),
        ("outputTokens", "outputTokens"),
        ("totalTokens", "totalTokens"),
        ("cachedInputTokens", "cachedInputTokens"),
    ):
        value = receipt.token_usage.get(source_key)
        if value is not None:
            usage[target_key] = int(value or 0)
    return receipt.to_dict(), stage_id, policy_sha256, usage


class TurnNotReadyError(RuntimeError):
    """Turn is still running; adapter should requeue rather than fail permanently."""

    def __init__(self, message: str, *, snapshot: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.snapshot = dict(snapshot or {})


def wait_for_agent_turn_terminal(
    session_id: str,
    turn_id: str,
    *,
    timeout_ms: int = DEFAULT_AGENT_TURN_TIMEOUT_MS,
    poll_ms: int = 200,
) -> dict[str, Any]:
    """Poll canonical turn completion until terminal success, failure, or timeout."""
    from core.web.services.session.turn_diagnostics import (
        get_session_turn_completion_snapshot,
    )

    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id or not normalized_turn_id:
        raise RuntimeError(
            json.dumps(
                {
                    "code": "agent_turn_anchor_incomplete",
                    "sessionId": normalized_session_id,
                    "turnId": normalized_turn_id,
                },
                ensure_ascii=False,
            )
        )

    deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000.0
    sleep_s = max(1, int(poll_ms)) / 1000.0
    last_snapshot: dict[str, Any] = {}
    while True:
        last_snapshot = get_session_turn_completion_snapshot(
            normalized_session_id, normalized_turn_id
        )
        if bool(last_snapshot.get("terminal")):
            status = str(
                last_snapshot.get("terminalStatus")
                or last_snapshot.get("lastTurnStatus")
                or ""
            ).strip().lower()
            if status in _SUCCESS_TERMINAL_STATUSES:
                return last_snapshot
            detail = {
                "code": "agent_turn_terminal_failed",
                "sessionId": normalized_session_id,
                "turnId": normalized_turn_id,
                "terminalStatus": status,
                "completionSource": last_snapshot.get("completionSource"),
                "failureClass": (
                    "terminal_failure"
                    if status in _FAILURE_TERMINAL_STATUSES
                    else "terminal_non_success"
                ),
            }
            raise RuntimeError(json.dumps(detail, ensure_ascii=False))
        if time.monotonic() >= deadline:
            raise TurnNotReadyError(
                json.dumps(
                    {
                        "code": "agent_turn_not_ready",
                        "sessionId": normalized_session_id,
                        "turnId": normalized_turn_id,
                        "terminal": False,
                        "terminalStatus": last_snapshot.get("terminalStatus"),
                        "completionSource": last_snapshot.get("completionSource"),
                        "timeoutMs": timeout_ms,
                    },
                    ensure_ascii=False,
                ),
                snapshot=last_snapshot,
            )
        time.sleep(sleep_s)


def collect_required_artifact_refs(
    node_id: str,
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
) -> list[dict[str, str]]:
    """Build canonical refs from scoped SC / ClaimEvidence store payloads."""
    from .artifact_readback_registry import (
        build_canonical_ref,
        load_scoped_artifact_payload,
        required_artifact_kinds,
    )
    from .human_gate_artifacts import canonical_sha256

    kinds = required_artifact_kinds(node_id)
    if not kinds:
        return []
    normalized_team = str(team_id or "").strip()
    authority_run_id = (
        str(source_collection_run_id or "").strip()
        or str(workflow_run_id or "").strip()
    )
    if not normalized_team or not authority_run_id:
        raise RuntimeError(
            "team_id and source_collection_run_id/workflow_run_id are required "
            "to collect artifact refs"
        )

    refs: list[dict[str, str]] = []
    for kind in kinds:
        payload = load_scoped_artifact_payload(
            kind,
            team_id=normalized_team,
            authority_run_id=authority_run_id,
            workflow_run_id=str(workflow_run_id or "").strip(),
        )
        if payload is None:
            continue
        content_hash = canonical_sha256(payload)
        version = "1.0.0"
        refs.append(
            {
                "canonicalRef": build_canonical_ref(
                    kind=kind,
                    team_id=normalized_team,
                    authority_run_id=authority_run_id,
                    content_hash=content_hash,
                ),
                "kind": kind,
                "sha256": content_hash,
                "version": version,
            }
        )
    return refs


def complete_agent_turn_outputs(
    *,
    action: PendingAction,
    handle: AgentTaskHandle,
    input_snapshot: dict[str, Any],
    timeout_ms: int = DEFAULT_AGENT_TURN_TIMEOUT_MS,
    poll_ms: int = 200,
) -> list[dict[str, str]]:
    """Wait for turn terminal, reconcile its task authority, collect store refs."""
    from .task_adapter_registry import resolve_agent_task_adapter

    team_id = str(input_snapshot.get("teamId") or "").strip()
    if not team_id:
        raise RuntimeError("input snapshot has no teamId for agent turn completion")
    source_collection_run_id = (
        str(input_snapshot.get("sourceCollectionRunId") or "").strip()
        or str(action.run_id or "").strip()
    )

    snapshot = wait_for_agent_turn_terminal(
        handle.session_id,
        handle.turn_id,
        timeout_ms=timeout_ms,
        poll_ms=poll_ms,
    )
    formal_receipt, receipt_stage_id, receipt_policy_sha256, receipt_usage = (
        _formal_receipt_writeback_context(snapshot)
    )
    _persist_question_model_invocation_receipts(
        snapshot,
        team_id=team_id,
        question_id=str(input_snapshot.get("questionId") or "").strip().upper(),
        workflow_run_id=str(action.run_id or "").strip(),
    )

    task_id = str(handle.task_id or "").strip()
    adapter_spec = resolve_agent_task_adapter(action.node_id)
    if task_id and adapter_spec is not None and adapter_spec.family == "source_collection":
        from core.web.services.team_workflow.source_collection.stage_writeback import (
            reconcile_source_collection_stage_session_task_after_turn,
        )

        reconcile_source_collection_stage_session_task_after_turn(
            team_id,
            task_id,
            run_id=source_collection_run_id,
            session_id=handle.session_id,
            turn_id=handle.turn_id,
            final_status=str(snapshot.get("terminalStatus") or ""),
            llm_usage=receipt_usage or None,
            model_invocation_receipt=formal_receipt,
            stage_id=receipt_stage_id or None,
            model_policy_sha256=receipt_policy_sha256 or None,
            reason="session_turn_completed",
        )

        if action.node_id == "source_extraction":
            from .agent_claim_evidence_materializer import (
                materialize_completed_extraction_task,
            )

            materialize_completed_extraction_task(
                team_id=team_id,
                workflow_run_id=str(action.run_id or ""),
                source_collection_run_id=source_collection_run_id,
                task_id=task_id,
            )

    refs = collect_required_artifact_refs(
        action.node_id,
        team_id=team_id,
        workflow_run_id=str(action.run_id or ""),
        source_collection_run_id=source_collection_run_id,
    )
    project_task_authority: dict[str, Any] | None = None
    if task_id and adapter_spec is not None and adapter_spec.family == "research_project":
        project_task_authority = _require_project_task_terminal(
            team_id=team_id,
            project_id=str(input_snapshot.get("projectId") or "").strip(),
            task_id=task_id,
        )
        challenge_contract = project_task_authority.get("challengeTaskContract")
        if formal_receipt is not None and isinstance(challenge_contract, dict):
            from core.web.services.team_workflow.challenge_question_runs import (
                register_challenge_task_model_evidence,
            )

            register_challenge_task_model_evidence(
                team_id,
                project_task_authority,
                final_status=str(project_task_authority.get("status") or "").strip(),
                llm_usage=receipt_usage or None,
                model_invocation_receipt=formal_receipt,
                stage_id=str(challenge_contract.get("stageId") or "").strip(),
                model_policy_sha256=str(
                    challenge_contract.get("modelPolicySha256") or ""
                ).strip().lower(),
            )
    return refs


def _require_project_task_terminal(
    *, team_id: str, project_id: str, task_id: str
) -> dict[str, Any]:
    """Close the canonical project task before the same Agent can take a successor."""
    if not project_id:
        raise RuntimeError("input snapshot has no projectId for project Agent task completion")
    from core.web.services.team_workflow.research_project_agent_tasks import (
        _read_research_project_agent_task_record,
        get_research_project_agent_task_status,
    )

    # Reconcile the canonical turn into the task store first, then read the
    # internal record so status and contract come from one server authority.
    get_research_project_agent_task_status(team_id, project_id)
    task = _read_research_project_agent_task_record(team_id, project_id, task_id)
    if task is None:
        raise RuntimeError("completed project Agent task is missing from its authority")
    task_status = str(task.get("status") or "").strip().lower()
    if task_status in {"queued", "running"}:
        raise TurnNotReadyError(
            json.dumps(
                {
                    "code": "project_agent_task_not_reconciled",
                    "taskId": task_id,
                    "status": task_status,
                },
                ensure_ascii=False,
            ),
            snapshot=task,
        )
    if task_status != "completed":
        raise RuntimeError(
            json.dumps(
                {
                    "code": "project_agent_task_terminal_failed",
                    "taskId": task_id,
                    "status": task_status,
                    "failureCode": task.get("failureCode"),
                },
                ensure_ascii=False,
            )
        )
    return task
