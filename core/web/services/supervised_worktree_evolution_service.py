"""Supervised worktree self-evolution loop for the web workbench."""

from __future__ import annotations

import base64
import hashlib
import json
import queue
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from core.evaluation import load_supervised_bundle, prepare_dataset_run
from core.evaluation.supervised_evolution import (
    normalize_supervised_mental_model_mode,
    supervised_mental_model_enabled_for_mode,
)
from core.infrastructure import developer_sandbox, git_process
from core.llm.errors import classify_exception
from core.runtime_manager import work_run_store
from core.runtime_manager.work_run_leases import (
    EVALUATION_LEASE,
    WORKTREE_WRITE_LEASE,
    WorkRunLeaseRequest,
    check_lease_conflicts,
)
from core.runtime_manager.work_run_store import WorkRunStore
from scripts.evolution_harness import (
    create_checkpoint_snapshot,
    create_worktree,
    delete_checkpoint_ref,
    HarnessResult,
    remove_worktree,
)

from .i18n import get_web_language, text_for
from .runtime_scene_service import record_runtime_scene_event
from .session_service import list_active_session_work_runs
from .supervised_agent_service import supervised_agent_bindings
from .supervised_candidate_runtime_service import (
    CandidateRuntimeExecutionError,
    run_candidate_runtime_evidence,
)
from .supervised_conversation_harness_adapter import run_supervised_conversation_harness
from .supervised_judge_closed_loop import (
    build_improvement_prompt,
    build_judge_evaluation_prompt,
    build_judge_rubric_prompt,
    judge_merge_allowed,
    normalize_judge_evaluation,
    normalize_judge_rubric,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_PROJECT_ROOT = PROJECT_ROOT
RUN_KIND = "supervised_worktree_evolution_run"
RUN_LEASES = [EVALUATION_LEASE, WORKTREE_WRITE_LEASE]
RUN_STORE_ROOT = developer_sandbox.formal_workspace_path(PROJECT_ROOT, "supervised_evolution", "worktree_runs")
_RUN_STATE_LOCK = threading.Lock()
_RUN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="web-supervised-worktree")
_RUN_SUBSCRIBERS_LOCK = threading.Lock()
_RUN_SUBSCRIBERS: dict[str, set[queue.Queue[dict[str, Any]]]] = {}
_RUN_CANCEL_EVENTS: dict[str, threading.Event] = {}
_ACTIVE_RUN_ID: str | None = None
_RUN_STREAM_QUEUE_SIZE = 12
_RUN_STREAM_POLL_SECONDS = 2.0
_RUN_STREAM_HEARTBEAT_SECONDS = 15.0
_ACTIVE_STATUSES = {"queued", "running", "paused", "stopping"}
_TERMINAL_STATUSES = {"done", "failed", "cancelled"}
_HIGH_RISK_PATH_PREFIXES = (
    ".runtime/",
    ".env",
    "logs/",
    "log_info/",
    "workspace/ui_runtime_state.json",
    "workspace/tool_registry/",
)
_HIGH_RISK_PATHS = {
    "config.toml",
    "config.local.toml",
    "AGENTS.md",
}
SELF_EVOLUTION_RISKY_WRITE_INITIATOR = "self_evolution_risky_write"
SELF_EVOLUTION_WORKTREE_ROUTE = "api:evolution.self.worktree-runs"
REVIEW_GATE_APPROVED = "approved"
REVIEW_GATE_PENDING = "pending"
APPROVAL_MODES = {"human", "agent"}
APPROVAL_DECISIONS = {"APPROVE", "REJECT", "RERUN_REQUIRED"}
EVALUATION_STATES = {"VALID", "INVALID", "ERROR", "INCONCLUSIVE"}
WORKFLOW_STEP_IDS = (
    "baseline_eval",
    "baseline_judge",
    "improve",
    "rerun_eval",
    "rerun_judge",
    "approval",
)


class SupervisedWorktreeRunBusyError(RuntimeError):
    """Raised when a supervised worktree run is already active."""


class SupervisedWorktreeRunValidationError(ValueError):
    """Raised when a supervised worktree run request is invalid."""


class SupervisedWorktreeRunNotFoundError(LookupError):
    """Raised when a supervised worktree run cannot be found."""


class SupervisedWorktreeRunCancelled(RuntimeError):
    """Raised internally when an active supervised worktree run is cancelled."""


class SupervisedWorktreeRunActionError(RuntimeError):
    """Raised when a supervised worktree run action cannot be completed."""


@dataclass(frozen=True)
class WorktreeRunDependencies:
    evaluation_runner: Callable[[Path, str, str, dict[str, Any]], dict[str, Any]] | None = None
    judge_runner: Callable[[Path, str, str, dict[str, Any]], dict[str, Any]] | None = None
    candidate_modifier: Callable[[Path, str, dict[str, Any]], dict[str, Any]] | None = None
    worktree_factory: Callable[[Path, str], dict[str, Any]] | None = None


def start_supervised_worktree_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Start one supervised self-modifying worktree loop."""

    global _ACTIVE_RUN_ID
    lang = get_web_language()
    options = _normalize_start_payload(payload, lang=lang)
    _raise_if_lease_conflict(lang=lang)

    with _RUN_STATE_LOCK:
        active = _ACTIVE_RUN_ID
        if active:
            snapshot = _work_run_store().load_snapshot(RUN_KIND, active)
            snapshot = _reconcile_orphaned_supervised_worktree_snapshot(snapshot)
            if snapshot and str(snapshot.get("status") or "").strip().lower() in _ACTIVE_STATUSES:
                raise SupervisedWorktreeRunBusyError(
                    text_for(
                        lang,
                        zh="当前已有一轮监督工作树进化在运行，请等它结束后再启动下一轮。",
                        en="A supervised worktree evolution run is already active.",
                    )
                )

        run_id = f"swte-{uuid4().hex[:12]}"
        now = _now_iso()
        snapshot = {
            "runId": run_id,
            "runKind": RUN_KIND,
            "leases": RUN_LEASES,
            "status": "queued",
            "phase": "queued",
            "runtimeStatus": "queued",
            "outcome": "",
            "mode": options["mode"],
            "executionMode": options["executionMode"],
            "sourceKind": options["sourceKind"],
            "datasetName": options["datasetName"],
            "datasetLimit": options["datasetLimit"],
            "bundleName": options["bundleName"],
            "taskContract": options["taskContract"],
            "keepWorktree": bool(options["keepWorktree"]),
            "startRequest": options["startRequest"],
            "selfEvolutionOrigin": options["selfEvolutionOrigin"],
            "reviewGate": options["reviewGate"],
            "approvalMode": options["approvalMode"],
            "approvalDecision": options["approvalDecision"],
            "agentBindings": options["agentBindings"],
            "mentalModelMode": options["mentalModelMode"],
            "mentalModelEnabled": options["mentalModelEnabled"],
            "startedAt": now,
            "updatedAt": now,
            "finishedAt": "",
            "projectRoot": str(PROJECT_ROOT),
            "latestMessage": "监督工作树进化已排队。",
            "costEstimate": options["costEstimate"],
            "stages": [],
            "events": [],
            "baseline": {},
            "judgeRubric": {},
            "baselineJudgment": {},
            "reflection": {},
            "candidateWorktree": {},
            "candidateModification": {},
            "candidate": {},
            "candidateJudgment": {},
            "judgeMergeTrigger": {},
            "baselineConversationSessionId": "",
            "rerunConversationSessionId": "",
            "judgeConversationSessionId": "",
            "approvalConversationSessionId": "",
            "decision": {},
            "mergeAnalysis": {},
            "merge": {},
            "rollback": {},
            "error": "",
            "errorType": "",
        }
        _ACTIVE_RUN_ID = run_id
        _persist_snapshot(snapshot, active_run_id=run_id)
        _record_worktree_started_event(snapshot)
        _append_event(snapshot, "queued", "监督工作树进化已排队。")
        initial_snapshot = _decorate_snapshot(_clone(snapshot))
    _RUN_EXECUTOR.submit(_run_supervised_worktree_thread, run_id, options)
    return initial_snapshot


def run_supervised_worktree_flow(
    payload: dict[str, Any],
    *,
    project_root: Path | None = None,
    dependencies: WorktreeRunDependencies | None = None,
) -> dict[str, Any]:
    """Run the complete loop synchronously. Tests use this to avoid real LLM calls."""

    lang = get_web_language()
    root = (project_root or PROJECT_ROOT).resolve()
    options = _normalize_start_payload(payload, lang=lang, project_root=project_root)
    run_id = f"swte-{uuid4().hex[:12]}"
    now = _now_iso()
    snapshot = {
        "runId": run_id,
        "runKind": RUN_KIND,
        "leases": RUN_LEASES,
        "status": "queued",
        "phase": "queued",
        "runtimeStatus": "queued",
        "outcome": "",
        "mode": options["mode"],
        "executionMode": options["executionMode"],
        "sourceKind": options["sourceKind"],
        "datasetName": options["datasetName"],
        "datasetLimit": options["datasetLimit"],
        "bundleName": options["bundleName"],
        "taskContract": options["taskContract"],
        "keepWorktree": bool(options["keepWorktree"]),
        "startRequest": options["startRequest"],
        "selfEvolutionOrigin": options["selfEvolutionOrigin"],
        "reviewGate": options["reviewGate"],
        "approvalMode": options["approvalMode"],
        "approvalDecision": options["approvalDecision"],
        "agentBindings": options["agentBindings"],
        "mentalModelMode": options["mentalModelMode"],
        "mentalModelEnabled": options["mentalModelEnabled"],
        "startedAt": now,
        "updatedAt": now,
        "finishedAt": "",
        "projectRoot": str(root),
        "latestMessage": "",
        "costEstimate": options["costEstimate"],
        "stages": [],
        "events": [],
        "baseline": {},
        "judgeRubric": {},
        "baselineJudgment": {},
        "reflection": {},
        "candidateWorktree": {},
        "candidateModification": {},
        "candidate": {},
        "candidateJudgment": {},
        "judgeMergeTrigger": {},
        "baselineConversationSessionId": "",
        "rerunConversationSessionId": "",
        "judgeConversationSessionId": "",
        "approvalConversationSessionId": "",
        "decision": {},
        "mergeAnalysis": {},
        "merge": {},
        "rollback": {},
        "error": "",
        "errorType": "",
    }
    run_id = str(snapshot.get("runId") or "")
    try:
        return _execute_flow(snapshot, options, root=root, dependencies=dependencies or WorktreeRunDependencies())
    finally:
        _clear_run_cancel_event(run_id)


def get_supervised_worktree_run(run_id: str) -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    if not normalized:
        return None
    snapshot = _work_run_store().load_snapshot(RUN_KIND, normalized)
    snapshot = _reconcile_orphaned_supervised_worktree_snapshot(snapshot)
    return _decorate_snapshot(snapshot) if snapshot else None


def get_active_supervised_worktree_run() -> dict[str, Any] | None:
    snapshot = _work_run_store().load_active_snapshot(RUN_KIND)
    if not snapshot:
        return None
    snapshot = _reconcile_orphaned_supervised_worktree_snapshot(snapshot)
    if str(snapshot.get("status") or "").strip().lower() not in _ACTIVE_STATUSES:
        return None
    return _decorate_snapshot(snapshot)


def list_supervised_worktree_runs(limit: int = 20) -> list[dict[str, Any]]:
    store = _work_run_store()
    runs_dir = store.runs_dir(RUN_KIND)
    if not runs_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(runs_dir.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payload = _reconcile_orphaned_supervised_worktree_snapshot(payload) or payload
            items.append(_decorate_snapshot(payload))
    items.sort(key=lambda item: str(item.get("updatedAt") or item.get("startedAt") or ""), reverse=True)
    return items[: max(1, min(int(limit or 20), 100))]


def force_cancel_active_supervised_worktree_runs_for_shutdown(reason: str = "") -> list[dict[str, Any]]:
    """Write terminal snapshots for active supervised worktree runs during workbench shutdown."""

    snapshot = _work_run_store().load_active_snapshot(RUN_KIND)
    if not snapshot:
        return []
    if str(snapshot.get("status") or "").strip().lower() not in _ACTIVE_STATUSES:
        _persist_snapshot(snapshot, active_run_id="")
        return []
    cancelled = _force_cancel_supervised_worktree_run_for_shutdown(snapshot, reason=reason)
    return [_decorate_snapshot(cancelled)] if cancelled else []


def _force_cancel_supervised_worktree_run_for_shutdown(
    snapshot: dict[str, Any],
    *,
    reason: str = "",
) -> dict[str, Any] | None:
    run_id = str(snapshot.get("runId") or "").strip()
    if not run_id:
        return None
    _request_run_cancel(run_id)
    updated = _clone(snapshot)
    now = _now_iso()
    message = "工作台关闭前已终止监督工作树进化运行。"
    updated["status"] = "cancelled"
    updated["phase"] = "shutdown"
    updated["runtimeStatus"] = "cancelled"
    updated["outcome"] = "shutdown_cancelled"
    updated["latestMessage"] = message
    updated["finishedAt"] = now
    updated["updatedAt"] = now
    updated["runtimeManagerControl"] = {
        "reason": "shutdown",
        "message": str(reason or ""),
    }
    _append_stage(updated, "shutdown", "cancelled", message)
    _persist_snapshot(updated, active_run_id="")
    _record_worktree_scene_event(
        "shutdown",
        "supervised_worktree_run.shutdown_cancelled",
        run_id=run_id,
        message="Supervised worktree evolution run cancelled for workbench shutdown.",
        outcome="cancelled",
        fields={
            **_snapshot_event_fields(updated),
            "reason": "shutdown",
        },
        child_log_payload={"snapshot": _compact_snapshot_for_child_log(updated)},
        lifecycle=True,
    )
    return updated


def _terminate_supervised_worktree_run_for_operator(
    snapshot: dict[str, Any],
    *,
    reviewer_note: str = "",
) -> dict[str, Any]:
    run_id = str(snapshot.get("runId") or "").strip()
    if not run_id:
        raise SupervisedWorktreeRunNotFoundError("Supervised worktree run not found.")
    status = str(snapshot.get("status") or "").strip().lower()
    if status not in _ACTIVE_STATUSES:
        raise SupervisedWorktreeRunActionError("This supervised worktree run is not active and cannot be terminated.")

    _request_run_cancel(run_id)
    updated = _clone(snapshot)
    now = _now_iso()
    message = "用户已终止监督工作树进化运行。"
    note = str(reviewer_note or "").strip()
    updated["status"] = "cancelled"
    updated["phase"] = "operator_terminated"
    updated["runtimeStatus"] = "cancelled"
    updated["outcome"] = "operator_cancelled"
    updated["latestMessage"] = message
    updated["finishedAt"] = now
    updated["updatedAt"] = now
    updated["cancelRequested"] = True
    updated["cancelRequestedAt"] = now
    updated["stopReason"] = note or message
    updated["runtimeManagerControl"] = {
        "reason": "operator_terminate",
        "message": note,
    }
    _append_stage(updated, "operator_terminated", "cancelled", message)
    with _RUN_STATE_LOCK:
        global _ACTIVE_RUN_ID
        if _ACTIVE_RUN_ID == run_id:
            _ACTIVE_RUN_ID = None
    _persist_snapshot(updated, active_run_id="")
    _record_worktree_scene_event(
        "operator_terminated",
        "supervised_worktree_run.operator_cancelled",
        run_id=run_id,
        message="Supervised worktree evolution run cancelled by operator.",
        outcome="cancelled",
        fields={
            **_snapshot_event_fields(updated),
            "reason": "operator_terminate",
        },
        child_log_payload={"snapshot": _compact_snapshot_for_child_log(updated)},
        lifecycle=True,
    )
    return updated


def _register_run_cancel_event(run_id: str) -> threading.Event:
    normalized = str(run_id or "").strip()
    with _RUN_STATE_LOCK:
        event = _RUN_CANCEL_EVENTS.get(normalized)
        if event is None:
            event = threading.Event()
            _RUN_CANCEL_EVENTS[normalized] = event
        return event


def _request_run_cancel(run_id: str) -> None:
    _register_run_cancel_event(run_id).set()


def _clear_run_cancel_event(run_id: str) -> None:
    normalized = str(run_id or "").strip()
    with _RUN_STATE_LOCK:
        _RUN_CANCEL_EVENTS.pop(normalized, None)


def _run_cancel_reason(run_id: str) -> str:
    normalized = str(run_id or "").strip()
    if not normalized:
        return ""
    with _RUN_STATE_LOCK:
        event = _RUN_CANCEL_EVENTS.get(normalized)
        event_set = bool(event and event.is_set())
    if event_set:
        return "工作台关闭前已请求终止监督工作树进化运行。"
    snapshot = _work_run_store().load_snapshot(RUN_KIND, normalized)
    if isinstance(snapshot, dict) and str(snapshot.get("status") or "").strip().lower() == "cancelled":
        control = snapshot.get("runtimeManagerControl") if isinstance(snapshot.get("runtimeManagerControl"), dict) else {}
        message = str(control.get("message") or snapshot.get("latestMessage") or "").strip()
        return message or "监督工作树进化运行已取消。"
    return ""


def _cancel_checker_for_run(run_id: str) -> Callable[[], str]:
    return lambda: _run_cancel_reason(run_id)


def _raise_if_run_cancelled(snapshot: dict[str, Any]) -> None:
    run_id = str(snapshot.get("runId") or "").strip()
    reason = _run_cancel_reason(run_id)
    if not reason:
        return
    persisted = _work_run_store().load_snapshot(RUN_KIND, run_id)
    if isinstance(persisted, dict) and str(persisted.get("status") or "").strip().lower() == "cancelled":
        snapshot.clear()
        snapshot.update(_clone(persisted))
    else:
        cancelled = _force_cancel_supervised_worktree_run_for_shutdown(snapshot, reason=reason)
        if cancelled:
            snapshot.clear()
            snapshot.update(_clone(cancelled))
    raise SupervisedWorktreeRunCancelled(reason)


def stream_supervised_worktree_run_events(run_id: str, initial_snapshot: dict[str, Any] | None = None):
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SupervisedWorktreeRunNotFoundError("Supervised worktree run not found.")
    snapshot = initial_snapshot or get_supervised_worktree_run(normalized)
    if snapshot is None:
        raise SupervisedWorktreeRunNotFoundError("Supervised worktree run not found.")

    subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_RUN_STREAM_QUEUE_SIZE)
    _register_subscriber(normalized, subscriber)
    last_signature = _snapshot_signature(snapshot)
    last_keepalive = time.monotonic()
    try:
        terminal = _is_terminal(snapshot)
        yield _encode_sse(
            "supervised_worktree_run",
            {"type": "supervised_worktree_run", "runId": normalized, "snapshot": snapshot, "terminal": terminal},
        )
        if terminal:
            return

        while True:
            try:
                event = subscriber.get(timeout=_RUN_STREAM_POLL_SECONDS)
            except queue.Empty:
                latest = get_supervised_worktree_run(normalized)
                if latest:
                    signature = _snapshot_signature(latest)
                    if signature != last_signature:
                        last_signature = signature
                        terminal = _is_terminal(latest)
                        yield _encode_sse(
                            "supervised_worktree_run",
                            {
                                "type": "supervised_worktree_run",
                                "runId": normalized,
                                "snapshot": latest,
                                "terminal": terminal,
                            },
                        )
                        if terminal:
                            break
                        last_keepalive = time.monotonic()
                        continue
                if time.monotonic() - last_keepalive >= _RUN_STREAM_HEARTBEAT_SECONDS:
                    yield ": keep-alive\n\n"
                    last_keepalive = time.monotonic()
                continue

            yield _encode_sse(str(event.get("type") or "supervised_worktree_run"), event)
            if bool(event.get("terminal")):
                break
    finally:
        _unregister_subscriber(normalized, subscriber)


def execute_supervised_worktree_action(
    run_id: str,
    action: str,
    *,
    force: bool = False,
    reviewer_note: str = "",
) -> dict[str, Any]:
    return _execute_supervised_worktree_action(
        run_id,
        action,
        force=force,
        reviewer_note=reviewer_note,
    )


def _execute_supervised_worktree_action(
    run_id: str,
    action: str,
    *,
    force: bool = False,
    reviewer_note: str = "",
) -> dict[str, Any]:
    normalized = str(run_id or "").strip()
    normalized_action = str(action or "").strip().lower().replace("-", "_")
    if not normalized:
        raise SupervisedWorktreeRunNotFoundError("Supervised worktree run not found.")
    snapshot = _work_run_store().load_snapshot(RUN_KIND, normalized)
    if not snapshot:
        raise SupervisedWorktreeRunNotFoundError("Supervised worktree run not found.")

    if normalized_action in {"analyze_merge", "merge_analysis"}:
        updated = _with_merge_analysis(snapshot)
        _append_event(updated, "merge_analysis", "已完成候选工作树合并分析。")
        return _decorate_snapshot(updated)
    if normalized_action == "preserve":
        updated = _mark_preserved(snapshot)
        _append_event(updated, "preserve", "候选工作树已保留，等待后续合并或人工处理。")
        return _decorate_snapshot(updated)
    if normalized_action == "discard":
        updated = _discard_candidate(snapshot)
        _append_event(updated, "discard", "候选工作树已丢弃。")
        return _decorate_snapshot(updated)
    if normalized_action in {"approve_review", "approve_merge_review", "mark_reviewed"}:
        if str(snapshot.get("approvalMode") or "human").strip().lower() != "human":
            raise SupervisedWorktreeRunActionError("本轮使用 Agent 审批，不能写入人工审批决定。")
        updated = _record_approval_decision(
            snapshot,
            decision="APPROVE",
            actor_kind="human",
            reason=reviewer_note,
        )
        merged = _merge_candidate(updated, force=force)
        _append_event(merged, "review_approved", "人工审批决定已记录，后端已执行受控合入。")
        return _decorate_snapshot(merged)
    if normalized_action in {"reject_review", "reject_approval"}:
        updated = _record_approval_decision(
            snapshot,
            decision="REJECT",
            actor_kind="human",
            reason=reviewer_note,
        )
        _append_event(updated, "review_rejected", "人工审批已拒绝本次候选合入。")
        return _decorate_snapshot(updated)
    if normalized_action in {"request_rerun", "rerun_required"}:
        updated = _record_approval_decision(
            snapshot,
            decision="RERUN_REQUIRED",
            actor_kind="human",
            reason=reviewer_note,
        )
        _append_event(updated, "review_rerun_required", "审批要求补充证据并重新运行。")
        return _decorate_snapshot(updated)
    if normalized_action in {"run_agent_approval", "agent_approval"}:
        decided = _request_independent_agent_approval(snapshot)
        if str((decided.get("approvalDecision") or {}).get("decision") or "") == "APPROVE":
            decided = _merge_candidate(decided, force=force)
        _append_event(decided, "agent_approval_decided", "独立审批 Agent 已写入最终决定。")
        return _decorate_snapshot(decided)
    if normalized_action == "merge":
        updated = _merge_candidate(snapshot, force=force)
        _append_event(updated, "merge", "候选改动已合并到主工作区。")
        return _decorate_snapshot(updated)
    if normalized_action in {"rollback_merge", "rollback"}:
        updated = _rollback_merge(snapshot)
        _append_event(updated, "rollback", "已按回滚清单恢复合并前状态。")
        return _decorate_snapshot(updated)
    if normalized_action in {"terminate", "cancel", "stop"}:
        updated = _terminate_supervised_worktree_run_for_operator(snapshot, reviewer_note=reviewer_note)
        return _decorate_snapshot(updated)
    raise SupervisedWorktreeRunValidationError(f"Unsupported supervised worktree action: {action}")


def _run_supervised_worktree_thread(run_id: str, options: dict[str, Any]) -> None:
    global _ACTIVE_RUN_ID
    snapshot = _work_run_store().load_snapshot(RUN_KIND, run_id)
    if not snapshot:
        return
    _register_run_cancel_event(run_id)
    try:
        _execute_flow(snapshot, options, root=PROJECT_ROOT.resolve(), dependencies=WorktreeRunDependencies())
    finally:
        _clear_run_cancel_event(run_id)
        with _RUN_STATE_LOCK:
            if _ACTIVE_RUN_ID == run_id:
                _ACTIVE_RUN_ID = None
        final_snapshot = _work_run_store().load_snapshot(RUN_KIND, run_id)
        if final_snapshot:
            _persist_snapshot(final_snapshot, active_run_id="")


def _execute_flow(
    snapshot: dict[str, Any],
    options: dict[str, Any],
    *,
    root: Path,
    dependencies: WorktreeRunDependencies,
) -> dict[str, Any]:
    run_id = str(snapshot.get("runId") or "")
    _register_run_cancel_event(run_id)
    cancel_checker = _cancel_checker_for_run(run_id)
    try:
        _raise_if_run_cancelled(snapshot)
        _transition(snapshot, "running", "baseline", "正在运行原始 agent 基线题集。")
        evaluator = dependencies.evaluation_runner or _evaluation_runner_for_mode(options["executionMode"])
        judge = dependencies.judge_runner or _judge_runner_for_mode(options["executionMode"])
        modifier = dependencies.candidate_modifier or _candidate_modifier_for_mode(options["executionMode"])
        worktree_factory = dependencies.worktree_factory or _default_worktree_factory

        _raise_if_run_cancelled(snapshot)
        baseline = evaluator(
            root,
            str(options["bundleName"]),
            "baseline",
            {
                "runId": run_id,
                "options": options,
                "cancelChecker": cancel_checker,
                "workflowStepId": "baseline_eval",
                "conversationSessionId": "",
                "progressCallback": _workflow_progress_callback(snapshot, "baseline", "baseline_eval"),
            },
        )
        _raise_if_run_cancelled(snapshot)
        snapshot["baseline"] = baseline
        snapshot["baselineConversationSessionId"] = _evaluation_conversation_session_id(baseline)
        if _baseline_has_retryable_provider_failure(baseline):
            _finish_baseline_unavailable(snapshot, baseline)
            return _decorate_snapshot(snapshot)
        _raise_if_run_cancelled(snapshot)
        _transition(
            snapshot,
            "running",
            "baseline_judge",
            "基线题集完成，Judge Agent 正在根据任务合同生成并冻结本轮 rubric。",
        )

        judge_rubric = judge(
            root,
            str(options["bundleName"]),
            "rubric",
            {
                "runId": run_id,
                "options": options,
                "cancelChecker": cancel_checker,
                "workflowStepId": "baseline_judge",
                "conversationSessionId": "",
                "taskContract": options["taskContract"],
                "progressCallback": _workflow_progress_callback(snapshot, "judge", "baseline_judge"),
            },
        )
        _raise_if_run_cancelled(snapshot)
        snapshot["judgeRubric"] = judge_rubric
        snapshot["judgeConversationSessionId"] = _evaluation_conversation_session_id(judge_rubric)
        if str(judge_rubric.get("status") or "").strip().lower() != "success":
            raise SupervisedWorktreeRunValidationError(
                str(judge_rubric.get("reason") or "Judge 未能生成有效任务 rubric。")
            )
        if not str(judge_rubric.get("rubricHash") or "").strip():
            raise SupervisedWorktreeRunValidationError("Judge rubric 缺少冻结哈希。")
        _record_worktree_scene_event(
            "judge_rubric",
            "supervised_worktree_run.judge_rubric_frozen",
            run_id=run_id,
            message="Judge task rubric frozen for baseline and rerun scoring.",
            outcome="frozen",
            fields={
                "rubricHash": str(judge_rubric["rubricHash"]),
                "taskCriterionCount": len(judge_rubric.get("taskCriteria") or []),
                "systemRubricVersion": str(judge_rubric.get("systemRubricVersion") or ""),
                "judgeConversationSessionId": str(snapshot.get("judgeConversationSessionId") or ""),
            },
            child_log_payload={
                "rubricHash": str(judge_rubric["rubricHash"]),
                "taskCriterionCount": len(judge_rubric.get("taskCriteria") or []),
                "systemRubricVersion": str(judge_rubric.get("systemRubricVersion") or ""),
            },
        )
        _transition(
            snapshot,
            "running",
            "baseline_judge",
            "任务 rubric 已冻结，Judge Agent 正在同一会话中进行基线评分。",
        )
        baseline_judgment = judge(
            root,
            str(options["bundleName"]),
            "baseline",
            {
                "runId": run_id,
                "options": options,
                "cancelChecker": cancel_checker,
                "workflowStepId": "baseline_judge",
                "conversationSessionId": str(snapshot.get("judgeConversationSessionId") or ""),
                "taskContract": options["taskContract"],
                "rubric": judge_rubric,
                "baselineEvaluation": baseline,
                "progressCallback": _workflow_progress_callback(snapshot, "judge", "baseline_judge"),
            },
        )
        _raise_if_run_cancelled(snapshot)
        snapshot["baselineJudgment"] = baseline_judgment
        baseline_judge_session_id = _evaluation_conversation_session_id(baseline_judgment)
        if baseline_judge_session_id != str(snapshot.get("judgeConversationSessionId") or ""):
            raise SupervisedWorktreeRunValidationError("Judge 基线评分未复用 rubric 生成会话。")
        if str(baseline_judgment.get("status") or "").strip().lower() != "success":
            raise SupervisedWorktreeRunValidationError(
                str(baseline_judgment.get("reason") or "Judge 第一次评分缺少有效结构化证据。")
            )
        if str(baseline_judgment.get("rubricHash") or "") != str(judge_rubric.get("rubricHash") or ""):
            raise SupervisedWorktreeRunValidationError("Judge 基线评分未使用冻结 rubric。")

        _transition(snapshot, "running", "reflection", "Judge 首评完成，正在把改进意见交回原基线 Agent 会话。")

        reflection = _build_reflection(snapshot, baseline, baseline_judgment)
        snapshot["reflection"] = reflection
        _persist_snapshot(snapshot, active_run_id=run_id if _ACTIVE_RUN_ID == run_id else "")

        _raise_if_run_cancelled(snapshot)
        _transition(snapshot, "running", "candidate_worktree", "正在创建候选隔离工作树。")
        _raise_if_run_cancelled(snapshot)
        candidate_worktree = worktree_factory(root, run_id)
        candidate_path = _coerce_candidate_worktree_path(
            candidate_worktree,
            project_root=root,
            run_id=run_id,
        )
        _raise_if_run_cancelled(snapshot)
        candidate_worktree["preserved"] = True
        candidate_worktree["path"] = str(candidate_path)
        snapshot["candidateWorktree"] = candidate_worktree
        _persist_snapshot(snapshot, active_run_id=run_id if _ACTIVE_RUN_ID == run_id else "")
        _ensure_bundle_available_in_candidate(
            root,
            candidate_path=candidate_path,
            bundle_name=str(options["bundleName"]),
        )

        _raise_if_run_cancelled(snapshot)
        _transition(snapshot, "running", "candidate_modify", "基线 Agent 正在原会话中依据 Judge 反馈修改自身。")
        _raise_if_run_cancelled(snapshot)
        modification = modifier(
            candidate_path,
            str(reflection.get("selfModificationPrompt") or ""),
            {
                "runId": run_id,
                "options": options,
                "cancelChecker": cancel_checker,
                "workflowStepId": "improve",
                "conversationSessionId": str(snapshot.get("baselineConversationSessionId") or ""),
                "progressCallback": _workflow_progress_callback(snapshot, "baseline", "improve"),
            },
        )
        _raise_if_run_cancelled(snapshot)
        snapshot["candidateModification"] = modification
        modification_session_id = _evaluation_conversation_session_id(modification)
        baseline_session_id = str(snapshot.get("baselineConversationSessionId") or "")
        if modification_session_id and baseline_session_id and modification_session_id != baseline_session_id:
            raise SupervisedWorktreeRunValidationError("基线 Agent 改进阶段未复用原始基线会话。")
        if modification_session_id and not baseline_session_id:
            snapshot["baselineConversationSessionId"] = modification_session_id
        if modification_session_id:
            snapshot["candidateConversationSessionId"] = modification_session_id
        snapshot["candidateWorktree"]["changedFiles"] = _candidate_changed_files(
            candidate_path,
            baseline_untracked=candidate_worktree.get("untrackedFiles"),
        )
        mutation_contract_violations = _candidate_mutation_contract_violations(
            snapshot["candidateWorktree"]["changedFiles"],
            options.get("candidateMutationContract")
            if isinstance(options.get("candidateMutationContract"), dict)
            else {},
        )
        if mutation_contract_violations:
            snapshot["candidateWorktree"]["mutationContractViolations"] = mutation_contract_violations
            raise SupervisedWorktreeRunValidationError(
                "候选改动超出本任务安全变更白名单："
                f"{'、'.join(mutation_contract_violations[:8])}"
            )
        if snapshot["candidateWorktree"]["changedFiles"]:
            candidate_variant = _build_candidate_variant(
                candidate_path,
                checkpoint_commit=str(candidate_worktree.get("checkpointCommit") or ""),
                changed_files=snapshot["candidateWorktree"]["changedFiles"],
                baseline_untracked=candidate_worktree.get("untrackedFiles"),
            )
            snapshot["candidateWorktree"]["variant"] = candidate_variant
            _record_worktree_scene_event(
                "candidate_variant",
                "supervised_worktree_run.candidate_variant_bound",
                run_id=run_id,
                outcome="succeeded",
                fields={
                    "variantId": candidate_variant["variantId"],
                    "checkpointCommit": candidate_variant["checkpointCommit"],
                    "patchSha256": candidate_variant["patchSha256"],
                    "changedFileCount": candidate_variant["changedFileCount"],
                },
            )
        _persist_snapshot(snapshot, active_run_id=run_id if _ACTIVE_RUN_ID == run_id else "")
        modifier_terminal_status = _candidate_modifier_terminal_status(modification)
        if modifier_terminal_status:
            _finish_candidate_modifier_terminal(snapshot, modification, terminal_status=modifier_terminal_status)
            return _decorate_snapshot(snapshot)
        if not snapshot["candidateWorktree"].get("changedFiles"):
            _finish_candidate_modifier_no_changes(snapshot)
            return _decorate_snapshot(snapshot)

        _raise_if_run_cancelled(snapshot)
        _transition(snapshot, "running", "candidate_evaluation", "正在新建独立会话复跑改进后的基线 Agent。")
        _raise_if_run_cancelled(snapshot)
        candidate = evaluator(
            candidate_path,
            str(options["bundleName"]),
            "baseline_rerun",
            {
                "runId": run_id,
                "options": options,
                "cancelChecker": cancel_checker,
                "workflowStepId": "rerun_eval",
                "conversationSessionId": "",
                "cleanRoom": True,
                "candidateVariant": snapshot["candidateWorktree"].get("variant"),
                "progressCallback": _workflow_progress_callback(snapshot, "baseline_rerun", "rerun_eval"),
            },
        )
        _raise_if_run_cancelled(snapshot)
        snapshot["candidate"] = candidate
        trusted_workspace_audit = _build_trusted_rerun_workspace_audit(
            candidate_path,
            frozen_variant=(
                snapshot["candidateWorktree"].get("variant")
                if isinstance(snapshot["candidateWorktree"].get("variant"), dict)
                else {}
            ),
            baseline_untracked=snapshot["candidateWorktree"].get("untrackedFiles"),
        )
        candidate["trustedWorkspaceAudit"] = trusted_workspace_audit
        for case_item in list(candidate.get("cases") or []):
            if not isinstance(case_item, dict):
                continue
            trace_summary = case_item.get("traceSummary")
            if not isinstance(trace_summary, dict):
                continue
            candidate_runtime = trace_summary.get("candidateRuntime")
            if isinstance(candidate_runtime, dict):
                candidate_runtime["trustedWorkspaceAudit"] = _clone(trusted_workspace_audit)
        workspace_audit_verified = (
            str(trusted_workspace_audit.get("status") or "") == "verified"
            and bool(trusted_workspace_audit.get("variantUnchanged"))
        )
        if not workspace_audit_verified:
            candidate["candidateRuntimeStatus"] = "failed"
            candidate["reason"] = str(
                trusted_workspace_audit.get("reason")
                or "候选复跑后工作树校验不可用。"
            )
        _record_worktree_scene_event(
            "candidate_runtime",
            (
                "supervised_worktree_run.candidate_workspace_audit_verified"
                if workspace_audit_verified
                else "supervised_worktree_run.candidate_workspace_audit_failed"
            ),
            run_id=run_id,
            level="info" if workspace_audit_verified else "error",
            outcome="verified" if workspace_audit_verified else "failed",
            fields={
                "candidateVariantId": str(
                    trusted_workspace_audit.get("frozenVariantId") or ""
                ),
                "observedVariantId": str(
                    trusted_workspace_audit.get("observedVariantId") or ""
                ),
                "auditStatus": str(trusted_workspace_audit.get("status") or ""),
                "variantUnchanged": bool(
                    trusted_workspace_audit.get("variantUnchanged")
                ),
                "unexpectedChangedFiles": list(
                    trusted_workspace_audit.get("unexpectedChangedFiles") or []
                )[:24],
            },
        )
        snapshot["rerunConversationSessionId"] = _evaluation_conversation_session_id(candidate)
        if (
            snapshot["rerunConversationSessionId"]
            and snapshot["rerunConversationSessionId"] == str(snapshot.get("baselineConversationSessionId") or "")
        ):
            raise SupervisedWorktreeRunValidationError("改进后复跑错误复用了基线会话，未满足 clean-room 独立性。")
        if (
            str(snapshot.get("executionMode") or "").strip().lower() == "real"
            and str(candidate.get("candidateRuntimeStatus") or "") != "verified"
        ):
            raise SupervisedWorktreeRunValidationError(
                str(candidate.get("reason") or "").strip()
                or "候选 harness 隔离执行或复跑后冻结候选校验未通过，已停止第二次 Judge 评分。"
            )

        _raise_if_run_cancelled(snapshot)
        _transition(snapshot, "running", "candidate_judge", "Judge Agent 正在原 Judge 会话中进行第二次评分。")
        candidate_judgment = judge(
            root,
            str(options["bundleName"]),
            "rerun",
            {
                "runId": run_id,
                "options": options,
                "cancelChecker": cancel_checker,
                "workflowStepId": "rerun_judge",
                "conversationSessionId": str(snapshot.get("judgeConversationSessionId") or ""),
                "taskContract": options["taskContract"],
                "rubric": snapshot.get("judgeRubric"),
                "baselineEvaluation": baseline,
                "baselineJudgment": baseline_judgment,
                "rerunEvaluation": candidate,
                "candidateVariant": snapshot["candidateWorktree"].get("variant"),
                "progressCallback": _workflow_progress_callback(snapshot, "judge", "rerun_judge"),
            },
        )
        _raise_if_run_cancelled(snapshot)
        snapshot["candidateJudgment"] = candidate_judgment
        rerun_judge_session_id = _evaluation_conversation_session_id(candidate_judgment)
        if rerun_judge_session_id != str(snapshot.get("judgeConversationSessionId") or ""):
            raise SupervisedWorktreeRunValidationError("Judge 第二次评分未复用第一次评分会话。")
        if str(candidate_judgment.get("status") or "").strip().lower() != "success":
            raise SupervisedWorktreeRunValidationError(
                str(candidate_judgment.get("reason") or "Judge 第二次评分缺少有效结构化证据。")
            )
        if str(candidate_judgment.get("rubricHash") or "") != str(
            (snapshot.get("judgeRubric") or {}).get("rubricHash") or ""
        ):
            raise SupervisedWorktreeRunValidationError("Judge 第二次评分未使用与基线相同的冻结 rubric。")

        _transition(snapshot, "running", "decision", "Judge 双次评分完成，正在生成用户审批结论。")
        decision = _build_decision(snapshot, options)
        snapshot["decision"] = decision
        snapshot["mergeAnalysis"] = _build_merge_analysis(snapshot)
        _finish_by_decision(snapshot, decision, options)
        return _decorate_snapshot(snapshot)
    except SupervisedWorktreeRunCancelled:
        persisted = _work_run_store().load_snapshot(RUN_KIND, run_id)
        if isinstance(persisted, dict):
            return _decorate_snapshot(persisted)
        return _decorate_snapshot(snapshot)
    except Exception as exc:
        snapshot["status"] = "failed"
        snapshot["phase"] = "failed"
        snapshot["runtimeStatus"] = "failed"
        snapshot["errorType"] = type(exc).__name__
        snapshot["error"] = str(exc)
        snapshot["latestMessage"] = f"监督工作树进化失败：{exc}"
        snapshot["finishedAt"] = _now_iso()
        snapshot["updatedAt"] = snapshot["finishedAt"]
        _append_stage(snapshot, "failed", "failed", snapshot["latestMessage"])
        _persist_snapshot(snapshot, active_run_id="")
        _record_worktree_scene_event(
            "failed",
            "supervised_worktree_run.failed",
            run_id=run_id,
            level="error",
            outcome="failed",
            fields={"errorType": type(exc).__name__, "error": str(exc)},
            lifecycle=True,
        )
        return _decorate_snapshot(snapshot)


def _normalize_start_payload(
    payload: dict[str, Any],
    *,
    lang: str,
    project_root: Path | None = None,
) -> dict[str, Any]:
    storage_project_root = _storage_project_root_arg(project_root)
    source_kind = str(payload.get("sourceKind") or "bundle").strip().lower()
    mode = str(payload.get("mode") or "auto").strip().lower()
    approval_mode = str(payload.get("approvalMode") or "human").strip().lower()
    execution_mode = str(payload.get("executionMode") or "simulation").strip().lower()
    keep_worktree = bool(payload.get("keepWorktree"))
    dataset_name = str(payload.get("datasetName") or "").strip()
    bundle_name = str(payload.get("bundleName") or "").strip()
    dataset_limit = _coerce_optional_int(payload.get("datasetLimit"))
    self_origin = _normalize_self_evolution_origin(payload)
    review_gate = _normalize_review_gate(payload, self_origin, approval_mode=approval_mode)
    mental_model_mode = normalize_supervised_mental_model_mode(payload.get("mentalModelMode") or "follow")
    mental_model_enabled = supervised_mental_model_enabled_for_mode(mental_model_mode)

    if mode not in {"auto", "manual"}:
        raise SupervisedWorktreeRunValidationError("mode must be auto or manual.")
    if approval_mode not in APPROVAL_MODES:
        raise SupervisedWorktreeRunValidationError("approvalMode must be human or agent.")
    if execution_mode not in {"simulation", "real"}:
        raise SupervisedWorktreeRunValidationError("executionMode must be simulation or real.")
    if source_kind not in {"dataset", "bundle"}:
        raise SupervisedWorktreeRunValidationError(
            text_for(lang, zh="请选择监督运行来源。", en="Choose a supervised run source.")
        )
    if source_kind == "dataset":
        if not dataset_name:
            raise SupervisedWorktreeRunValidationError(
                text_for(lang, zh="请选择一个数据集。", en="Choose a dataset.")
            )
        prepared = prepare_dataset_run(storage_project_root, dataset_name, dataset_limit)
        if not prepared.runnable:
            raise SupervisedWorktreeRunValidationError(prepared.blocked_message or "Dataset is not runnable.")
        bundle_name = prepared.bundle_name
    elif not bundle_name:
        raise SupervisedWorktreeRunValidationError(
            text_for(lang, zh="请输入监督 bundle 名称。", en="Enter a supervised bundle name.")
        )

    try:
        bundle = load_supervised_bundle(bundle_name, project_root=storage_project_root)
    except (FileNotFoundError, ValueError) as exc:
        raise SupervisedWorktreeRunValidationError(str(exc)) from exc
    case_count = len(list(bundle.get("cases") or []))
    candidate_mutation_contract = _normalize_candidate_mutation_contract(bundle)
    task_contract = _build_task_contract(
        bundle,
        bundle_name=bundle_name,
        self_origin=self_origin,
        candidate_mutation_contract=candidate_mutation_contract,
    )
    estimate = _estimate_llm_cost(case_count)
    if execution_mode == "real" and not bool(payload.get("confirmRealLlmCost")):
        raise SupervisedWorktreeRunValidationError(
            "真实 LLM 闭环预计会发起 "
            f"{estimate['modelCalls']} 次模型调用，约 {estimate['estimatedTotalTokens']} tokens。"
            " 如确认消耗，请传 confirmRealLlmCost=true。"
        )
    agent_bindings = _normalize_worktree_agent_bindings(payload.get("agentBindings"))
    if execution_mode == "real" and not agent_bindings:
        try:
            agent_bindings = _normalize_worktree_agent_bindings(supervised_agent_bindings())
        except Exception as exc:
            raise SupervisedWorktreeRunValidationError(f"监督 worktree 真实闭环缺少可用 Agent 绑定：{exc}") from exc
    if execution_mode == "real":
        required_bindings = [("baseline", "基线 Agent"), ("judge", "Judge Agent")]
        if approval_mode == "agent":
            required_bindings.append(("auditor", "审批 Agent"))
        missing_bindings = [
            label
            for role, label in required_bindings
            if not str((agent_bindings.get(role) or {}).get("agentId") or "").strip()
        ]
        if missing_bindings:
            raise SupervisedWorktreeRunValidationError(
                f"监督 worktree 真实闭环缺少必要绑定：{'、'.join(missing_bindings)}。"
            )
        if not _candidate_mutation_contract_supports_real_run(candidate_mutation_contract):
            raise SupervisedWorktreeRunValidationError(
                "所选任务缺少可执行的候选变更契约，不能进入真实监督闭环。"
                "请选择明确声明 required=true 且提供安全 allowlisted_paths 的候选补丁任务。"
            )
    return {
        "sourceKind": source_kind,
        "mode": mode,
        "approvalMode": approval_mode,
        "approvalDecision": {
            "schemaVersion": 1,
            "mode": approval_mode,
            "status": "pending",
            "decision": "",
        },
        "executionMode": execution_mode,
        "datasetName": dataset_name,
        "datasetLimit": dataset_limit,
        "bundleName": bundle_name,
        "taskContract": task_contract,
        "candidateMutationContract": candidate_mutation_contract,
        "keepWorktree": keep_worktree,
        "costEstimate": estimate,
        "startRequest": _normalize_start_request_metadata(payload),
        "selfEvolutionOrigin": self_origin,
        "reviewGate": review_gate,
        "agentBindings": agent_bindings,
        "mentalModelMode": mental_model_mode,
        "mentalModelEnabled": mental_model_enabled,
    }


def _build_task_contract(
    bundle: dict[str, Any],
    *,
    bundle_name: str,
    self_origin: dict[str, Any],
    candidate_mutation_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for index, item in enumerate(list(bundle.get("cases") or [])[:50], start=1):
        if not isinstance(item, dict):
            continue
        case = {
            "caseId": _safe_metadata_text(
                item.get("case_id") or item.get("caseId") or f"case-{index}",
                limit=120,
            ),
            "prompt": str(
                item.get("baseline_prompt")
                or item.get("baselinePrompt")
                or item.get("prompt")
                or item.get("task")
                or item.get("instruction")
                or ""
            ).strip()[:4000],
        }
        expected = item.get("expected_output", item.get("expectedOutput"))
        if expected is not None:
            case["expectedOutput"] = str(expected)[:2000]
        cases.append(case)
    return {
        "bundleName": bundle_name,
        "benchmark": _safe_metadata_text(bundle.get("benchmark"), limit=160),
        "goal": _safe_metadata_text(self_origin.get("goal"), limit=500),
        "riskReason": _safe_metadata_text(self_origin.get("riskReason"), limit=300),
        "cases": cases,
        "candidateMutationContract": _clone(candidate_mutation_contract or {}),
    }


def _normalize_candidate_mutation_contract(bundle: dict[str, Any]) -> dict[str, Any]:
    raw = bundle.get("candidate_mutation_contract")
    if not isinstance(raw, dict):
        raw = bundle.get("candidateMutationContract")
    if not isinstance(raw, dict):
        raw = {}
    raw_paths = raw.get("allowlisted_paths")
    if not isinstance(raw_paths, list):
        raw_paths = raw.get("allowlistedPaths")
    allowlisted_paths: list[str] = []
    for value in raw_paths if isinstance(raw_paths, list) else []:
        path = str(value or "").strip().replace("\\", "/").lstrip("/")
        parts = [part for part in path.split("/") if part]
        if (
            not path
            or ":" in path
            or any(part in {".", ".."} for part in parts)
            or path in allowlisted_paths
        ):
            continue
        allowlisted_paths.append(path[:300])
    return {
        "supported": bool(raw.get("supported")),
        "required": bool(raw.get("required")),
        "kind": _safe_metadata_text(raw.get("kind"), limit=80),
        "allowlistedPaths": allowlisted_paths[:20],
    }


def _candidate_mutation_contract_supports_real_run(contract: dict[str, Any]) -> bool:
    return bool(
        contract.get("supported")
        and contract.get("required")
        and str(contract.get("kind") or "").strip()
        and list(contract.get("allowlistedPaths") or [])
    )


def _candidate_mutation_contract_violations(
    changed_files: list[dict[str, Any]],
    contract: dict[str, Any],
) -> list[str]:
    if not bool(contract.get("required")):
        return []
    allowlisted_paths = {
        str(path or "").strip().replace("\\", "/").lstrip("/")
        for path in list(contract.get("allowlistedPaths") or [])
        if str(path or "").strip()
    }
    violations: list[str] = []
    for item in changed_files:
        path = str(item.get("path") or "").strip().replace("\\", "/").lstrip("/")
        if path and path not in allowlisted_paths and path not in violations:
            violations.append(path)
    return violations


def _normalize_worktree_agent_bindings(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    bindings: dict[str, dict[str, Any]] = {}
    for role in ("baseline", "candidate", "auditor", "judge"):
        item = value.get(role)
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id:
            continue
        payload = dict(item)
        payload["agentId"] = agent_id
        payload["role"] = str(payload.get("role") or role).strip() or role
        bindings[role] = payload
    return bindings


def _normalize_self_evolution_origin(payload: dict[str, Any]) -> dict[str, Any]:
    request_source = str(payload.get("requestSource") or "").strip()
    initiator = str(payload.get("initiator") or "").strip()
    goal = str(
        payload.get("selfEvolutionGoal")
        or payload.get("self_evolution_goal")
        or payload.get("goal")
        or ""
    ).strip()
    risk_reason = str(
        payload.get("selfEvolutionRiskReason")
        or payload.get("self_evolution_risk_reason")
        or payload.get("riskReason")
        or ""
    ).strip()
    source_run_id = str(payload.get("sourceSelfRunId") or payload.get("sourceRunId") or "").strip()
    source_candidate_id = str(payload.get("sourceCandidateId") or payload.get("candidateId") or "").strip()
    self_origin_requested = (
        bool(payload.get("requiresSupervisedReview"))
        or request_source == SELF_EVOLUTION_WORKTREE_ROUTE
        or initiator == SELF_EVOLUTION_RISKY_WRITE_INITIATOR
        or bool(goal)
    )
    if not self_origin_requested:
        return {}
    return {
        "sourceTrack": "self_evolution",
        "goal": _safe_metadata_text(goal, limit=500),
        "riskReason": _safe_metadata_text(risk_reason),
        "sourceSelfRunId": _safe_metadata_text(source_run_id),
        "sourceCandidateId": _safe_metadata_text(source_candidate_id),
        "requiresSupervisedReview": True,
    }


def _normalize_review_gate(
    payload: dict[str, Any],
    self_origin: dict[str, Any],
    *,
    approval_mode: str,
) -> dict[str, Any]:
    reason = str(payload.get("reviewReason") or "").strip()
    if not reason:
        reason = (
            "Self-evolution risky write output must be reviewed before merge."
            if self_origin
            else (
                "An independent Approval Agent must decide before controlled merge."
                if approval_mode == "agent"
                else "The user must decide before controlled merge."
            )
        )
    return {
        "required": True,
        "status": REVIEW_GATE_PENDING,
        "reason": _safe_metadata_text(reason, limit=300),
        "approvedAt": "",
        "reviewerNote": "",
    }


def _estimate_llm_cost(case_count: int) -> dict[str, Any]:
    safe_cases = max(1, int(case_count or 1))
    evaluation_calls = safe_cases * 2
    judge_calls = 3
    self_edit_calls = 1
    model_calls = evaluation_calls + judge_calls + self_edit_calls
    estimated_input = evaluation_calls * 3500 + judge_calls * 5000 + 6000
    estimated_output = evaluation_calls * 1200 + judge_calls * 1500 + 3500
    return {
        "caseCount": safe_cases,
        "evaluationCalls": evaluation_calls,
        "judgeCalls": judge_calls,
        "selfEditCalls": self_edit_calls,
        "modelCalls": model_calls,
        "estimatedInputTokens": estimated_input,
        "estimatedOutputTokens": estimated_output,
        "estimatedTotalTokens": estimated_input + estimated_output,
        "note": "粗略估算，包含 rubric 生成与两次同会话评分；真实消耗取决于模型重试、工具输出和题目长度。",
    }


def _normalize_start_request_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    route = _safe_metadata_text(payload.get("requestSource") or "api:evolution.worktree-runs")
    ui_route = _safe_metadata_text(payload.get("uiRoute") or "/evolution")
    initiator = _safe_metadata_text(payload.get("initiator") or "user")
    client_action = _safe_metadata_text(payload.get("clientAction") or "start_supervised_worktree_run")
    return {
        "requestSource": route,
        "uiRoute": ui_route,
        "initiator": initiator,
        "clientAction": client_action,
    }


def _safe_metadata_text(value: Any, *, limit: int = 160) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("\r", " ").replace("\n", " ")
    return text[:limit]


def _evaluation_runner_for_mode(execution_mode: str) -> Callable[[Path, str, str, dict[str, Any]], dict[str, Any]]:
    if execution_mode == "simulation":
        return _simulation_evaluation_runner
    return _real_evaluation_runner


def _judge_runner_for_mode(execution_mode: str) -> Callable[[Path, str, str, dict[str, Any]], dict[str, Any]]:
    if execution_mode == "simulation":
        return _simulation_judge_runner
    return _real_judge_runner


def _candidate_modifier_for_mode(execution_mode: str) -> Callable[[Path, str, dict[str, Any]], dict[str, Any]]:
    if execution_mode == "simulation":
        return _simulation_candidate_modifier
    return _real_candidate_modifier


def _simulation_evaluation_runner(project_root: Path, bundle_name: str, role: str, context: dict[str, Any]) -> dict[str, Any]:
    bundle = load_supervised_bundle(bundle_name, project_root=_storage_project_root_arg(project_root))
    cases = list(bundle.get("cases") or [])
    successes = len(cases) if role == "baseline_rerun" else max(0, len(cases) - 1)
    total = len(cases)
    execution_score = round((successes / total) * 100, 3) if total else 0.0
    session_id = f"simulation-{role}-{str(context.get('runId') or 'run')}"
    return {
        "role": role,
        "status": "success",
        "executionScore": execution_score,
        "successes": successes,
        "total": total,
        "failures": max(0, total - successes),
        "bundleName": bundle_name,
        "summary": f"{role} simulation execution {successes}/{total}",
        "conversationSessionId": session_id,
        "cases": [
            {
                "caseId": str(case.get("case_id") or f"case-{index}"),
                "status": "success" if index <= successes else "failed",
                "reason": "simulation",
            }
            for index, case in enumerate(cases, start=1)
        ],
    }


def _simulation_judge_runner(project_root: Path, bundle_name: str, phase: str, context: dict[str, Any]) -> dict[str, Any]:
    del project_root, bundle_name
    session_id = str(context.get("conversationSessionId") or "").strip()
    if not session_id:
        session_id = f"simulation-judge-{str(context.get('runId') or 'run')}"
    if phase == "rubric":
        rubric = normalize_judge_rubric(
            {
                "phase": "rubric",
                "task_summary": "按题集任务完成目标并提供可验证运行证据。",
                "criteria": [
                    {
                        "id": "task_completion",
                        "label": "任务完成度",
                        "description": "完成题集声明的任务目标。",
                        "weight": 0.7,
                        "evidence_requirements": ["case result"],
                    },
                    {
                        "id": "task_specific_quality",
                        "label": "任务定向质量",
                        "description": "结果满足本轮任务的定向质量要求。",
                        "weight": 0.3,
                        "evidence_requirements": ["case trace"],
                    },
                ],
            },
            task_contract=context.get("taskContract") if isinstance(context.get("taskContract"), dict) else {},
        )
        return {
            **rubric,
            "conversationSessionId": session_id,
        }
    rubric = context.get("rubric") if isinstance(context.get("rubric"), dict) else {}
    if phase == "baseline":
        task_scores = {
            str(item.get("id") or ""): 40.0
            for item in list(rubric.get("taskCriteria") or [])
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        system_scores = {
            str(item.get("id") or ""): 40.0
            for item in list(rubric.get("systemCriteria") or [])
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        return {
            "status": "success",
            "phase": "baseline",
            "recommendation": "REVISE",
            "decision": "REVISE",
            "score": 40.0,
            "taskScore": 40.0,
            "systemScore": 40.0,
            "baselineScore": 40.0,
            "rubricHash": rubric.get("rubricHash"),
            "problems": ["模拟 Judge：基线仍有可改进边界。"],
            "improvementInstructions": ["在隔离 worktree 中补充边界验证。"],
            "taskScores": task_scores,
            "systemScores": system_scores,
            "dimensions": system_scores,
            "evidenceRefs": ["simulation:baseline"],
            "conversationSessionId": session_id,
        }
    task_scores = {
        str(item.get("id") or ""): 80.0
        for item in list(rubric.get("taskCriteria") or [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    system_scores = {
        str(item.get("id") or ""): 80.0
        for item in list(rubric.get("systemCriteria") or [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    return {
        "status": "success",
        "phase": "rerun",
        "recommendation": "APPROVE",
        "decision": "APPROVE",
        "score": 80.0,
        "taskScore": 80.0,
        "systemScore": 80.0,
        "baselineScore": 40.0,
        "rubricHash": rubric.get("rubricHash"),
        "problems": [],
        "improvementInstructions": [],
        "taskScores": task_scores,
        "systemScores": system_scores,
        "dimensions": system_scores,
        "evidenceRefs": ["simulation:rerun"],
        "conversationSessionId": session_id,
    }


def _real_evaluation_runner(project_root: Path, bundle_name: str, role: str, context: dict[str, Any]) -> dict[str, Any]:
    bundle = load_supervised_bundle(bundle_name, project_root=_storage_project_root_arg(project_root))
    cases = list(bundle.get("cases") or [])
    run_id = str(context.get("runId") or "")
    options = context.get("options") if isinstance(context.get("options"), dict) else {}
    agent_bindings = options.get("agentBindings") if isinstance(options.get("agentBindings"), dict) else {}
    binding_role = "baseline" if role in {"baseline", "baseline_rerun"} else role
    agent_binding = dict(agent_bindings.get(binding_role) or {})
    if not agent_binding.get("agentId"):
        return {
            "role": role,
            "status": "failed",
            "score": 0.0,
            "successes": 0,
            "total": len(cases),
            "failures": len(cases),
            "bundleName": bundle_name,
            "summary": f"{role} evaluation missing supervised Agent binding",
            "cases": [
                {
                    "caseId": str(case.get("case_id") or f"case-{index}"),
                    "role": role,
                    "status": "failed",
                    "reason": "missing_supervised_agent_binding",
                }
                for index, case in enumerate(cases, start=1)
            ],
        }
    mental_model_mode = str(options.get("mentalModelMode") or "follow")
    mental_model_enabled = options.get("mentalModelEnabled")
    cancel_checker = context.get("cancelChecker") if callable(context.get("cancelChecker")) else None
    progress_callback = context.get("progressCallback") if callable(context.get("progressCallback")) else None
    conversation_session_id = str(context.get("conversationSessionId") or "").strip()
    results: list[dict[str, Any]] = []
    for case in cases:
        cancel_reason = _call_cancel_checker(cancel_checker)
        if cancel_reason:
            return {
                "role": role,
                "status": "cancelled",
                "score": 0.0,
                "successes": 0,
                "total": len(results),
                "failures": 0,
                "bundleName": bundle_name,
                "summary": f"{role} evaluation cancelled: {cancel_reason}",
                "cases": results,
            }
        case_id = str(case.get("case_id") or "case").strip() or "case"
        if role == "baseline_rerun":
            prompt = str(
                case.get("candidate_prompt")
                or case.get("candidatePrompt")
                or case.get("baseline_prompt")
                or case.get("prompt")
                or ""
            ).strip()
        else:
            prompt = str(
                case.get("baseline_prompt")
                or case.get("baselinePrompt")
                or case.get("prompt")
                or ""
            ).strip()
        scenario = str(case.get("scenario") or "transaction").strip() or "transaction"
        mode = str(case.get("mode") or "single_turn").strip() or "single_turn"
        timeout_seconds = int(case.get("timeout_seconds") or bundle.get("default_timeout_seconds") or 600)
        expect_restart = bool(case.get("expect_restart", False))
        post_restart_observe_seconds = int(case.get("post_restart_observe_seconds") or 20)
        result = run_supervised_conversation_harness(
            repo_root=project_root,
            mode=mode,
            prompt=prompt,
            scenario=scenario,
            timeout_seconds=timeout_seconds,
            max_steps=int(case.get("max_steps") or 0) or None,
            expect_restart=expect_restart,
            post_restart_observe_seconds=post_restart_observe_seconds,
            keep_worktree=False,
            agent_binding=agent_binding,
            mental_model_mode=mental_model_mode,
            mental_model_enabled=mental_model_enabled,
            workspace_override=project_root,
            conversation_session_id=conversation_session_id or None,
            clean_room=bool(context.get("cleanRoom")),
            progress_callback=progress_callback,
            cancel_checker=cancel_checker,
        )
        if role == "baseline_rerun":
            candidate_variant = (
                context.get("candidateVariant")
                if isinstance(context.get("candidateVariant"), dict)
                else {}
            )
            result.worktree_path = str(project_root.resolve())
            result.checkpoint_commit = str(candidate_variant.get("checkpointCommit") or "")
            try:
                candidate_runtime = run_candidate_runtime_evidence(
                    candidate_path=project_root,
                    candidate_variant=candidate_variant,
                    harness_result=result,
                    cancel_checker=cancel_checker,
                )
            except CandidateRuntimeExecutionError as exc:
                candidate_runtime = {
                    "status": "failed",
                    "runtimeEffect": "not_applied",
                    "reason": _bounded_text(str(exc), limit=600),
                    "worktreePath": str(project_root.resolve()),
                }
                result.status = "failed"
                result.reason = f"候选 harness 隔离执行失败：{exc}"
                result.returncode = 1
                result.primary_returncode = 1
                result.effective_returncode = 1
                _record_worktree_scene_event(
                    "candidate_runtime",
                    "supervised_worktree_run.candidate_runtime_failed",
                    run_id=run_id,
                    level="error",
                    outcome="failed",
                    fields={
                        "caseId": case_id,
                        "candidateVariantId": str(candidate_variant.get("variantId") or ""),
                        "errorType": type(exc).__name__,
                        "reason": _bounded_text(str(exc), limit=300),
                    },
                )
            else:
                _record_worktree_scene_event(
                    "candidate_runtime",
                    "supervised_worktree_run.candidate_runtime_verified",
                    run_id=run_id,
                    outcome="verified",
                    fields={
                        "caseId": case_id,
                        "candidateVariantId": str(candidate_runtime.get("candidateVariantId") or ""),
                        "moduleSha256": str(candidate_runtime.get("moduleSha256") or ""),
                        "executionBackend": str(candidate_runtime.get("executionBackend") or ""),
                    },
                )
            result.evolution_summary = {
                **(
                    result.evolution_summary
                    if isinstance(result.evolution_summary, dict)
                    else {}
                ),
                "candidate_runtime": candidate_runtime,
            }
        cancel_reason = _call_cancel_checker(cancel_checker)
        if cancel_reason:
            return {
                "role": role,
                "status": "cancelled",
                "score": 0.0,
                "successes": 0,
                "total": len(results),
                "failures": 0,
                "bundleName": bundle_name,
                "summary": f"{role} evaluation cancelled: {cancel_reason}",
                "cases": results,
            }
        results.append(_harness_result_payload(result, case_id=case_id, role=role))
        if not conversation_session_id:
            conversation_session_id = str((result.process_summary or {}).get("session_id") or "").strip()
        _record_worktree_scene_event(
            "evaluation",
            "supervised_worktree_run.case_finished",
            run_id=run_id,
            fields={"role": role, "caseId": case_id, "status": result.status},
        )
    successes = sum(1 for item in results if item.get("status") == "success")
    total = len(results)
    execution_score = round((successes / total) * 100, 3) if total else 0.0
    evaluation = {
        "role": role,
        "status": "success" if successes == total else "failed",
        "executionScore": execution_score,
        "successes": successes,
        "total": total,
        "failures": max(0, total - successes),
        "bundleName": bundle_name,
        "summary": f"{role} execution {successes}/{total}",
        "conversationSessionId": conversation_session_id,
        "cases": results,
    }
    candidate_variant = context.get("candidateVariant")
    if role == "baseline_rerun" and isinstance(candidate_variant, dict):
        evaluation["candidateVariant"] = _clone(candidate_variant)
        candidate_runtime_statuses = [
            str(
                (
                    (item.get("traceSummary") or {}).get("candidateRuntime")
                    if isinstance(item.get("traceSummary"), dict)
                    else {}
                ).get("status")
                or ""
            )
            for item in results
            if isinstance(item, dict)
        ]
        evaluation["candidateRuntimeStatus"] = (
            "verified"
            if len(candidate_runtime_statuses) == total
            and total > 0
            and all(status == "verified" for status in candidate_runtime_statuses)
            else "failed"
        )
    return evaluation


def _real_judge_runner(project_root: Path, bundle_name: str, phase: str, context: dict[str, Any]) -> dict[str, Any]:
    del bundle_name
    options = context.get("options") if isinstance(context.get("options"), dict) else {}
    agent_bindings = options.get("agentBindings") if isinstance(options.get("agentBindings"), dict) else {}
    agent_binding = dict(agent_bindings.get("judge") or {})
    if not agent_binding.get("agentId"):
        return {
            "status": "failed",
            "phase": phase,
            "decision": "INCONCLUSIVE",
            "reason": "Judge evaluation missing supervised Judge Agent binding.",
        }
    task_contract = context.get("taskContract") if isinstance(context.get("taskContract"), dict) else {}
    if phase == "rubric":
        prompt = build_judge_rubric_prompt(task_contract=task_contract)
    else:
        rubric = context.get("rubric") if isinstance(context.get("rubric"), dict) else {}
        previous_judgment = (
            context.get("baselineJudgment")
            if isinstance(context.get("baselineJudgment"), dict)
            else {}
        )
        prompt = build_judge_evaluation_prompt(
            phase=phase,
            task_contract=task_contract,
            rubric=rubric,
            baseline_evaluation=context.get("baselineEvaluation") if isinstance(context.get("baselineEvaluation"), dict) else {},
            rerun_evaluation=context.get("rerunEvaluation") if isinstance(context.get("rerunEvaluation"), dict) else {},
            previous_judgment=previous_judgment,
            candidate_variant=context.get("candidateVariant") if isinstance(context.get("candidateVariant"), dict) else {},
        )

    def run_judge_turn(turn_prompt: str, *, conversation_session_id: str) -> HarnessResult:
        return run_supervised_conversation_harness(
            repo_root=project_root,
            mode="single_turn",
            prompt=turn_prompt,
            scenario="supervised_judge_evaluation",
            timeout_seconds=600,
            expect_restart=False,
            post_restart_observe_seconds=0,
            keep_worktree=True,
            agent_binding=agent_binding,
            mental_model_mode=str(options.get("mentalModelMode") or "follow"),
            mental_model_enabled=options.get("mentalModelEnabled"),
            workspace_override=project_root,
            conversation_session_id=conversation_session_id or None,
            progress_callback=context.get("progressCallback") if callable(context.get("progressCallback")) else None,
            cancel_checker=context.get("cancelChecker") if callable(context.get("cancelChecker")) else None,
        )

    requested_session_id = str(context.get("conversationSessionId") or "").strip()
    result = run_judge_turn(prompt, conversation_session_id=requested_session_id)
    session_id = str((result.process_summary or {}).get("session_id") or "").strip()
    raw_judgment = (result.evolution_summary or {}).get("agent_judgment")
    observed_phase = (
        str(raw_judgment.get("phase") or "").strip().lower()
        if isinstance(raw_judgment, dict)
        else ""
    )
    normalized_phase = str(phase or "").strip().lower()
    if (
        result.status == "success"
        and isinstance(raw_judgment, dict)
        and observed_phase != normalized_phase
        and (session_id or requested_session_id)
    ):
        retry_session_id = session_id or requested_session_id
        _record_worktree_scene_event(
            "judge_phase_retry",
            "supervised_worktree_run.judge_phase_retry",
            run_id=str(context.get("runId") or ""),
            level="warning",
            outcome="retrying",
            fields={
                "expectedPhase": normalized_phase,
                "observedPhase": observed_phase or "-",
                "judgeConversationSessionId": retry_session_id,
                "retryLimit": 1,
            },
        )
        retry_prompt = (
            "PHASE_CORRECTION_REQUIRED\n"
            f"The previous structured response used the wrong phase; expected phase={normalized_phase}, "
            f"observed phase={observed_phase or '-'}.\n"
            "Continue in this same Judge conversation. Ignore the previous wrong structured response, "
            "do not regenerate or change the frozen rubric, and execute the current phase exactly once.\n"
            "Return one new SUPERVISED_AGENT_JUDGMENT line for the expected phase. "
            "The complete current-phase instruction follows:\n"
            f"{prompt}"
        )
        result = run_judge_turn(retry_prompt, conversation_session_id=retry_session_id)
        session_id = str((result.process_summary or {}).get("session_id") or "").strip()
        raw_judgment = (result.evolution_summary or {}).get("agent_judgment")
    if result.status != "success" or not isinstance(raw_judgment, dict):
        return {
            "status": "failed",
            "phase": phase,
            "decision": "INCONCLUSIVE",
            "reason": result.reason or "Judge Agent did not emit SUPERVISED_AGENT_JUDGMENT.",
            "conversationSessionId": session_id,
        }
    try:
        if phase == "rubric":
            normalized = normalize_judge_rubric(raw_judgment, task_contract=task_contract)
        else:
            normalized = normalize_judge_evaluation(
                raw_judgment,
                expected_phase=phase,
                rubric=context.get("rubric") if isinstance(context.get("rubric"), dict) else {},
                baseline_score=(
                    float((context.get("baselineJudgment") or {}).get("score"))
                    if phase == "rerun"
                    and isinstance(context.get("baselineJudgment"), dict)
                    and isinstance((context.get("baselineJudgment") or {}).get("score"), (int, float))
                    else None
                ),
            )
    except ValueError as exc:
        return {
            "status": "failed",
            "phase": phase,
            "decision": "INCONCLUSIVE",
            "reason": str(exc),
            "conversationSessionId": session_id,
        }
    return {
        **normalized,
        "conversationSessionId": session_id,
        "summary": result.reason or f"Judge {phase} evaluation completed.",
    }


def _harness_result_payload(result: HarnessResult, *, case_id: str, role: str) -> dict[str, Any]:
    summary = result.evolution_summary if isinstance(result.evolution_summary, dict) else {}
    trace_summary = {
        "validation": _clone(summary.get("validation") or {}),
        "transaction": _clone(summary.get("transaction") or {}),
        "git": _clone(summary.get("git") or {}),
        "restart": _clone(summary.get("restart") or {}),
        "toolSequence": [str(item)[:160] for item in list(summary.get("tool_sequence_tail") or [])[-12:]],
        "toolPhases": [str(item)[:200] for item in list(summary.get("tool_phase_sequence_tail") or [])[-12:]],
        "toolTrace": _clone(list(summary.get("tool_trace") or [])[-12:]),
        "guardedTools": _clone(summary.get("guarded_tools") or {}),
        "evidence": _clone(summary.get("evidence") or {}),
    }
    candidate_runtime = summary.get("candidate_runtime")
    if isinstance(candidate_runtime, dict):
        trace_summary["candidateRuntime"] = _clone(candidate_runtime)
    for source_key, target_key in (
        ("environment", "environment"),
        ("final_state", "finalState"),
        ("infeasible_outcome", "infeasibleOutcome"),
        ("supervised_marker_errors", "markerErrors"),
    ):
        value = summary.get(source_key)
        if isinstance(value, dict):
            trace_summary[target_key] = _clone(value)
    return {
        "caseId": case_id,
        "role": role,
        "status": result.status,
        "reason": result.reason,
        "worktreePath": result.worktree_path,
        "checkpointCommit": result.checkpoint_commit,
        "conversationSessionId": str((result.process_summary or {}).get("session_id") or ""),
        "assistantOutput": _bounded_text("\n".join(str(item) for item in result.stdout_tail[-20:]), limit=4000),
        "traceSummary": trace_summary,
        "llmFailure": summary.get("llm_failure") or {},
    }


def _simulation_candidate_modifier(worktree_path: Path, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
    marker = worktree_path / "tests" / "supervised_worktree_candidate_marker.py"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        '"""Simulation marker for supervised worktree evolution."""\n\n'
        'CANDIDATE_SELF_EDITED = True\n',
        encoding="utf-8",
    )
    return {
        "status": "success",
        "summary": "simulation wrote a candidate marker file",
        "promptPreview": prompt[:500],
        "changedPath": "tests/supervised_worktree_candidate_marker.py",
    }


def _candidate_self_edit_protocol_violation(result: HarnessResult) -> str:
    summary = result.evolution_summary if isinstance(result.evolution_summary, dict) else {}
    judgment = summary.get("agent_judgment") if isinstance(summary.get("agent_judgment"), dict) else {}
    judgment_phase = str(judgment.get("phase") or "").strip().lower()
    if judgment_phase:
        return judgment_phase
    assistant_output = "\n".join(str(item) for item in list(result.stdout_tail or [])[-20:])
    if "SUPERVISED_AGENT_JUDGMENT" in assistant_output:
        return "structured_judgment"
    return ""


def _candidate_self_edit_correction_prompt(
    original_prompt: str,
    *,
    attempt: int,
) -> str:
    sanitized_prompt = str(original_prompt or "").replace(
        "SUPERVISED_AGENT_JUDGMENT",
        "Judge structured-output marker",
    )
    correction_kind = (
        "SELF_EDIT_PHASE_CORRECTION_REQUIRED\nBASELINE_IMPLEMENTATION_OUTPUT_ONLY"
        if attempt == 1
        else "FINAL_BASELINE_IMPLEMENTATION_CORRECTION"
    )
    return (
        f"{correction_kind}\n"
        "The previous assessment-style prose is discarded. This is an implementation turn.\n"
        "Start with a repository inspection tool call against the candidate worktree. Use the source evidence "
        "to choose exactly one terminal path: (A) apply an evidence-backed patch and run focused validation, "
        "or (B) return NO_JUSTIFIED_CHANGE with concrete source evidence. Report only implementation actions "
        "and validation evidence; do not produce scoring criteria, scores, recommendations, or a verdict.\n\n"
        "Implementation instruction:\n"
        f"{sanitized_prompt}"
    )


def _real_candidate_modifier(worktree_path: Path, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
    started = _now_iso()
    timeout_seconds = 900
    cancel_checker = context.get("cancelChecker") if callable(context.get("cancelChecker")) else None
    progress_callback = context.get("progressCallback") if callable(context.get("progressCallback")) else None
    options = context.get("options") if isinstance(context.get("options"), dict) else {}
    agent_bindings = options.get("agentBindings") if isinstance(options.get("agentBindings"), dict) else {}
    agent_binding = dict(agent_bindings.get("baseline") or {})
    if not agent_binding.get("agentId"):
        return {
            "status": "failed",
            "startedAt": started,
            "endedAt": _now_iso(),
            "summary": "baseline self-edit missing supervised baseline Agent binding",
        }
    conversation_session_id = str(context.get("conversationSessionId") or "").strip()

    def run_self_edit_turn(turn_prompt: str, *, session_id: str) -> HarnessResult:
        return run_supervised_conversation_harness(
            repo_root=worktree_path,
            mode="single_turn",
            prompt=turn_prompt,
            scenario="candidate_self_improvement",
            timeout_seconds=timeout_seconds,
            expect_restart=False,
            post_restart_observe_seconds=0,
            keep_worktree=True,
            agent_binding=agent_binding,
            mental_model_mode=str(options.get("mentalModelMode") or "follow"),
            mental_model_enabled=options.get("mentalModelEnabled"),
            workspace_override=worktree_path,
            conversation_session_id=session_id or None,
            progress_callback=progress_callback,
            cancel_checker=cancel_checker,
        )

    result = run_self_edit_turn(prompt, session_id=conversation_session_id)
    observed_protocol = _candidate_self_edit_protocol_violation(result)
    retry_count = 0
    retry_limit = 2
    while (
        result.status == "success"
        and observed_protocol
        and conversation_session_id
        and retry_count < retry_limit
    ):
        retry_count += 1
        _record_worktree_scene_event(
            "candidate_modify",
            "supervised_worktree_run.candidate_modify_phase_retry",
            run_id=str(context.get("runId") or ""),
            level="warning",
            outcome="retrying",
            fields={
                "observedProtocol": observed_protocol,
                "conversationSessionId": conversation_session_id,
                "retryIndex": retry_count,
                "retryLimit": retry_limit,
            },
        )
        correction_prompt = _candidate_self_edit_correction_prompt(
            prompt,
            attempt=retry_count,
        )
        result = run_self_edit_turn(correction_prompt, session_id=conversation_session_id)
        observed_protocol = _candidate_self_edit_protocol_violation(result)
    if result.status == "success" and observed_protocol:
        result.status = "failed"
        result.reason = (
            f"baseline self-edit phase mismatch after {retry_count} corrections: "
            f"observed {observed_protocol}"
        )
    return {
        "status": result.status,
        "startedAt": started,
        "endedAt": result.ended_at or _now_iso(),
        "returnCode": result.returncode,
        "command": result.command,
        "summary": result.reason or (
            "candidate self-edit conversation finished"
            if result.status == "success"
            else "candidate self-edit conversation failed"
        ),
        "conversationSummary": result.evolution_summary,
        "conversationSessionId": str((result.process_summary or {}).get("session_id") or ""),
        "workspaceOverride": str(worktree_path),
        "phaseRetryCount": retry_count,
    }


def _default_worktree_factory(project_root: Path, run_id: str) -> dict[str, Any]:
    snapshot = create_checkpoint_snapshot(project_root, run_id)
    worktree_path = create_worktree(project_root, snapshot, run_id)
    return {
        "path": str(worktree_path),
        "cleanupOwner": RUN_KIND,
        "cleanupRunId": run_id,
        "baseHead": snapshot.base_head,
        "checkpointCommit": snapshot.commit,
        "checkpointRef": snapshot.ref_name or "",
        "trackedDirty": snapshot.tracked_dirty,
        "untrackedFiles": snapshot.untracked_files,
    }


def _coerce_candidate_worktree_path(
    candidate_worktree: dict[str, Any],
    *,
    project_root: Path,
    run_id: str,
) -> Path:
    raw_path = str(candidate_worktree.get("path") or "").strip()
    if not raw_path:
        raise SupervisedWorktreeRunValidationError(
            f"候选工作树路径缺失（runId={run_id}）。请检查兼容层或历史快照。"
        )
    try:
        candidate_path = Path(raw_path).expanduser().resolve()
    except Exception:
        raise SupervisedWorktreeRunValidationError(
            f"候选工作树路径格式无效（runId={run_id}）：{raw_path}"
        )
    if not candidate_path.exists():
        raise SupervisedWorktreeRunValidationError(
            f"候选工作树路径不存在（runId={run_id}）：{candidate_path}"
        )
    if not candidate_path.is_dir():
        raise SupervisedWorktreeRunValidationError(
            f"候选工作树路径不是目录（runId={run_id}）：{candidate_path}"
        )
    project_root = project_root.resolve()
    if candidate_path == project_root:
        raise SupervisedWorktreeRunValidationError(
            f"候选工作树路径不可为主项目目录（runId={run_id}）。"
        )
    try:
        candidate_path.relative_to(project_root)
    except ValueError:
        return candidate_path
    raise SupervisedWorktreeRunValidationError(
        f"候选工作树路径不能在主项目目录内（runId={run_id}）：{candidate_path}"
    )


def _coerce_candidate_worktree_path_soft(
    candidate_worktree: dict[str, Any],
    *,
    project_root: Path,
    run_id: str,
) -> tuple[Path | None, str]:
    try:
        return _coerce_candidate_worktree_path(
            candidate_worktree,
            project_root=project_root,
            run_id=run_id,
        ), ""
    except SupervisedWorktreeRunValidationError as exc:
        return None, str(exc)


def _ensure_bundle_available_in_candidate(project_root: Path, *, candidate_path: Path, bundle_name: str) -> None:
    if not bundle_name or not candidate_path.exists():
        return
    source = developer_sandbox.seeded_sandbox_workspace_path(project_root, "evaluation", "bundles", f"{bundle_name}.json")
    if not source.exists():
        return
    target = candidate_path / "workspace" / "evaluation" / "bundles" / source.name
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _build_reflection(
    snapshot: dict[str, Any],
    baseline: dict[str, Any],
    baseline_judgment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    successes = int(baseline.get("successes") or 0)
    total = int(baseline.get("total") or 0)
    failures = max(0, total - successes)
    self_origin = snapshot.get("selfEvolutionOrigin") if isinstance(snapshot.get("selfEvolutionOrigin"), dict) else {}
    requested_goal = str(self_origin.get("goal") or "").strip()
    if isinstance(baseline_judgment, dict) and baseline_judgment:
        return {
            "summary": (
                f"Judge 基线评分 {baseline_judgment.get('score')}；"
                f"已向原基线 Agent 会话发送 {len(list(baseline_judgment.get('improvementInstructions') or []))} 条改进指令。"
            ),
            "selfModificationPrompt": build_improvement_prompt(
                baseline_evaluation=baseline,
                baseline_judgment=baseline_judgment,
                requested_goal=requested_goal,
                task_contract=(
                    snapshot.get("taskContract")
                    if isinstance(snapshot.get("taskContract"), dict)
                    else {}
                ),
            ),
        }
    goal_section = ""
    if requested_goal:
        goal_section = (
            "\n\n本轮来自 self-evolution risky write worktree 请求。\n"
            f"用户请求目标：{requested_goal}\n"
            "你可以在隔离 worktree 中实现候选改动，但候选必须等待监督 review 后才能合并。"
        )
    baseline_is_full_score = total > 0 and successes >= total
    target = (
        "目标：基线已经满分；不要为了制造分数提升而削弱现有成功路径。"
        "请只考虑同一题集未覆盖的边界鲁棒性、错误恢复或诊断改进；"
        "如果没有可信改进，保守地不做无依据改动。"
        if baseline_is_full_score
        else "目标：让候选 agent 在同一题集复测时比基线分数更高。"
    )
    prompt = (
        "你正在隔离 worktree 中执行监督自改闭环。\n"
        "先用中文简短反思基线运行，再直接修改本项目中你认为最能提升同一题集表现的内容。\n"
        "硬约束：只在当前 worktree 内修改；不要改主工作区、不要读取真实密钥、不要改机器全局配置；"
        "修改后运行你认为必要的最小验证。不要提交 git，不要合并。\n\n"
        f"基线结果：{successes}/{total} 通过，失败数 {failures}。\n"
        f"基线摘要：{baseline.get('summary') or '-'}\n"
        f"{target}"
        f"{goal_section}"
    )
    return {
        "summary": (
            f"基线 {successes}/{total} 通过；候选只在有可信边界改进时修改。"
            if baseline_is_full_score
            else f"基线 {successes}/{total} 通过，候选需要针对失败点自改。"
        ),
        "selfModificationPrompt": prompt,
    }


def _baseline_has_retryable_provider_failure(baseline: dict[str, Any]) -> bool:
    for case in list(baseline.get("cases") or []):
        if not isinstance(case, dict):
            continue
        failure = case.get("llmFailure") if isinstance(case.get("llmFailure"), dict) else {}
        category = str(failure.get("category") or "").strip()
        if bool(failure.get("retryable")) and category == "provider_transport_error":
            return True
        if str(case.get("status") or "").strip().lower() != "failed":
            continue
        reason = str(case.get("reason") or failure.get("message") or "").strip()
        if not reason:
            continue
        normalized = classify_exception(RuntimeError(reason))
        if normalized.retryable and normalized.category in {
            "network_error",
            "rate_limit",
            "server_error",
            "timeout",
        }:
            return True
    return False


def _finish_baseline_unavailable(snapshot: dict[str, Any], baseline: dict[str, Any]) -> None:
    run_id = str(snapshot.get("runId") or "")
    reason = _baseline_failure_reason(baseline)
    message = "基线评测因 LLM provider 传输异常失败，本轮已停止，避免继续消耗候选自改 token。"
    snapshot["status"] = "failed"
    snapshot["phase"] = "baseline_unavailable"
    snapshot["runtimeStatus"] = "failed"
    snapshot["outcome"] = "baseline_unavailable"
    snapshot["errorType"] = "ProviderTransportError"
    snapshot["error"] = reason
    snapshot["latestMessage"] = message
    snapshot["finishedAt"] = _now_iso()
    snapshot["updatedAt"] = snapshot["finishedAt"]
    _append_stage(snapshot, "baseline_unavailable", "failed", message)
    _persist_snapshot(snapshot, active_run_id="")
    _record_worktree_scene_event(
        "baseline_unavailable",
        "supervised_worktree_run.baseline_unavailable",
        run_id=run_id,
        level="warning",
        outcome="failed",
        fields={**_snapshot_event_fields(snapshot), "baselineFailureReason": reason},
        child_log_payload={"snapshot": _compact_snapshot_for_child_log(snapshot)},
        lifecycle=True,
    )


def _candidate_modifier_terminal_status(modification: dict[str, Any]) -> str:
    raw_status = str((modification or {}).get("status") or "").strip().lower()
    if raw_status in {"", "success", "succeeded", "done", "completed", "ready"}:
        return ""
    if raw_status in {"cancelled", "canceled", "stopped", "stopped_by_user", "superseded"}:
        return "cancelled"
    return "failed"


def _reconcile_orphaned_supervised_worktree_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return snapshot
    run_id = str(snapshot.get("runId") or "").strip()
    status = str(snapshot.get("status") or "").strip().lower()
    phase = str(snapshot.get("phase") or "").strip().lower()
    if not run_id or status not in _ACTIVE_STATUSES or phase != "candidate_modify":
        return snapshot
    if _ACTIVE_RUN_ID == run_id or run_id in _RUN_CANCEL_EVENTS:
        return snapshot
    progress = snapshot.get("workflowProgress") if isinstance(snapshot.get("workflowProgress"), dict) else {}
    improve = progress.get("improve") if isinstance(progress.get("improve"), dict) else {}
    turn_id = str(
        improve.get("conversationTurnId")
        or improve.get("conversation_turn_id")
        or improve.get("turnId")
        or ""
    ).strip()
    if not turn_id:
        return snapshot
    child = _work_run_store().load_snapshot("chat_turn", turn_id)
    if not isinstance(child, dict):
        return snapshot
    child_status = str(child.get("status") or child.get("runtimeStatus") or "").strip().lower()
    child_runtime_status = str(child.get("runtimeStatus") or "").strip().lower()
    if child_status in {"cancelled", "canceled", "stopped", "stopped_by_user", "force_stopped"} or child_runtime_status == "force_stopped":
        terminal_status = "cancelled"
    elif child_status in {"failed", "error", "timeout"}:
        terminal_status = "failed"
    else:
        return snapshot
    updated = _clone(snapshot)
    modification = updated.get("candidateModification") if isinstance(updated.get("candidateModification"), dict) else {}
    if terminal_status == "cancelled":
        summary = f"候选改良子会话已终止：{child_status or child_runtime_status}"
    else:
        summary = f"候选改良子会话失败：{child_status}"
    updated["candidateModification"] = {
        **modification,
        "status": terminal_status if terminal_status == "cancelled" else child_status or "failed",
        "summary": summary,
        "conversationSummary": {
            **(modification.get("conversationSummary") if isinstance(modification.get("conversationSummary"), dict) else {}),
            "conversation_backend": {
                "enabled": True,
                "session_id": str(improve.get("conversationSessionId") or "").strip(),
                "observed_active_turn_id": turn_id,
                "observed_terminal_status": child_status,
            },
        },
        "reconciledFromChildTurn": turn_id,
        "reconciledAt": _now_iso(),
    }
    _finish_candidate_modifier_terminal(
        updated,
        updated["candidateModification"],
        terminal_status=terminal_status,
    )
    return _work_run_store().load_snapshot(RUN_KIND, run_id) or updated


def _finish_candidate_modifier_terminal(
    snapshot: dict[str, Any],
    modification: dict[str, Any],
    *,
    terminal_status: str,
) -> None:
    run_id = str(snapshot.get("runId") or "")
    raw_status = str((modification or {}).get("status") or terminal_status or "").strip().lower()
    normalized = "cancelled" if terminal_status == "cancelled" else "failed"
    reason = str((modification or {}).get("summary") or (modification or {}).get("reason") or raw_status or normalized).strip()
    if normalized == "cancelled":
        message = f"候选改良会话已停止，本轮监督 worktree 闭环已取消：{reason}"
    else:
        message = f"候选改良未正常完成，本轮监督 worktree 闭环已停止：{reason}"
    finished = _now_iso()
    snapshot["status"] = normalized
    snapshot["phase"] = "candidate_modify"
    snapshot["runtimeStatus"] = normalized
    snapshot["outcome"] = f"candidate_modify_{raw_status or normalized}"
    snapshot["latestMessage"] = message
    snapshot["finishedAt"] = finished
    snapshot["updatedAt"] = finished
    if normalized == "failed":
        snapshot["errorType"] = "CandidateModificationFailed"
        snapshot["error"] = reason
    progress = snapshot.get("workflowProgress") if isinstance(snapshot.get("workflowProgress"), dict) else {}
    if progress is not snapshot.get("workflowProgress"):
        snapshot["workflowProgress"] = progress
    improve_progress = progress.get("improve") if isinstance(progress.get("improve"), dict) else {}
    progress["improve"] = {
        **improve_progress,
        "stepId": "improve",
        "role": "candidate",
        "status": normalized,
        "phase": "candidate_modify",
        "conversationSessionId": _candidate_conversation_session_id(snapshot),
        "conversationTurnId": str(improve_progress.get("conversationTurnId") or "").strip(),
        "latestOutput": reason,
        "latestOutputKind": "status",
        "latestOutputLabel": raw_status or normalized,
        "livePreview": _bounded_text(message),
        "updatedAt": finished,
    }
    _append_stage(snapshot, "candidate_modify", normalized, message)
    _persist_snapshot(snapshot, active_run_id="")
    _record_worktree_scene_event(
        "candidate_modify",
        f"supervised_worktree_run.candidate_modify_{normalized}",
        run_id=run_id,
        level="warning" if normalized == "cancelled" else "error",
        outcome=normalized,
        fields={**_snapshot_event_fields(snapshot), "candidateModifierStatus": raw_status or normalized},
        child_log_payload={"snapshot": _compact_snapshot_for_child_log(snapshot)},
        lifecycle=True,
    )


def _finish_candidate_modifier_no_changes(snapshot: dict[str, Any]) -> None:
    run_id = str(snapshot.get("runId") or "")
    modification = snapshot.get("candidateModification") if isinstance(snapshot.get("candidateModification"), dict) else {}
    reason = str(modification.get("summary") or "候选改良会话未产生任何 worktree 改动。").strip()
    message = f"候选改良未产生可复跑的代码改动，本轮已停止：{reason}"
    finished = _now_iso()
    snapshot["candidateModification"] = {
        **modification,
        "status": "no_changes",
        "summary": message,
    }
    snapshot["status"] = "failed"
    snapshot["phase"] = "candidate_modify"
    snapshot["runtimeStatus"] = "failed"
    snapshot["outcome"] = "candidate_modify_no_changes"
    snapshot["errorType"] = "CandidateModificationNoChanges"
    snapshot["error"] = reason
    snapshot["latestMessage"] = message
    snapshot["finishedAt"] = finished
    snapshot["updatedAt"] = finished
    progress = snapshot.get("workflowProgress") if isinstance(snapshot.get("workflowProgress"), dict) else {}
    if progress is not snapshot.get("workflowProgress"):
        snapshot["workflowProgress"] = progress
    improve_progress = progress.get("improve") if isinstance(progress.get("improve"), dict) else {}
    progress["improve"] = {
        **improve_progress,
        "stepId": "improve",
        "role": "candidate",
        "status": "failed",
        "phase": "candidate_modify",
        "conversationSessionId": _candidate_conversation_session_id(snapshot),
        "conversationTurnId": str(improve_progress.get("conversationTurnId") or "").strip(),
        "latestOutput": reason,
        "latestOutputKind": "status",
        "latestOutputLabel": "no_changes",
        "livePreview": _bounded_text(message),
        "updatedAt": finished,
    }
    _append_stage(snapshot, "candidate_modify", "failed", message)
    _persist_snapshot(snapshot, active_run_id="")
    _record_worktree_scene_event(
        "candidate_modify",
        "supervised_worktree_run.candidate_modify_no_changes",
        run_id=run_id,
        level="warning",
        outcome="failed",
        fields={**_snapshot_event_fields(snapshot), "candidateModifierStatus": "no_changes"},
        child_log_payload={"snapshot": _compact_snapshot_for_child_log(snapshot)},
        lifecycle=True,
    )


def _baseline_failure_reason(baseline: dict[str, Any]) -> str:
    for case in list(baseline.get("cases") or []):
        if not isinstance(case, dict):
            continue
        failure = case.get("llmFailure") if isinstance(case.get("llmFailure"), dict) else {}
        message = str(failure.get("message") or "").strip()
        if message:
            return message
        reason = str(case.get("reason") or "").strip()
        if reason:
            return reason
    return str(baseline.get("summary") or "baseline provider transport failure")


def _evaluation_state(snapshot: dict[str, Any]) -> str:
    judgment = (
        snapshot.get("candidateJudgment")
        if isinstance(snapshot.get("candidateJudgment"), dict)
        else {}
    )
    if not judgment:
        return "ERROR" if str(snapshot.get("status") or "").lower() == "failed" else "INVALID"
    if str(judgment.get("status") or "").strip().lower() != "success":
        return "ERROR"
    if str(judgment.get("phase") or "").strip().lower() != "rerun":
        return "INVALID"
    explicit = str(judgment.get("evaluationState") or "").strip().upper()
    if explicit in EVALUATION_STATES and explicit != "VALID":
        return explicit
    recommendation = str(
        judgment.get("recommendation") or judgment.get("decision") or ""
    ).strip().upper()
    if recommendation == "INCONCLUSIVE":
        return "INCONCLUSIVE"
    if recommendation not in {"APPROVE", "REVISE", "REJECT", "PROMOTE", "HOLD"}:
        return "INVALID"
    rubric = snapshot.get("judgeRubric") if isinstance(snapshot.get("judgeRubric"), dict) else {}
    expected_hash = str(rubric.get("rubricHash") or "").strip()
    observed_hash = str(judgment.get("rubricHash") or "").strip()
    if expected_hash and observed_hash and expected_hash != observed_hash:
        return "INVALID"
    return "VALID"


def _build_decision(snapshot: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    baseline = snapshot.get("baseline") if isinstance(snapshot.get("baseline"), dict) else {}
    candidate = snapshot.get("candidate") if isinstance(snapshot.get("candidate"), dict) else {}
    baseline_judgment = snapshot.get("baselineJudgment") if isinstance(snapshot.get("baselineJudgment"), dict) else {}
    candidate_judgment = snapshot.get("candidateJudgment") if isinstance(snapshot.get("candidateJudgment"), dict) else {}
    judge_rubric = snapshot.get("judgeRubric") if isinstance(snapshot.get("judgeRubric"), dict) else {}
    modification = snapshot.get("candidateModification") if isinstance(snapshot.get("candidateModification"), dict) else {}
    worktree = snapshot.get("candidateWorktree") if isinstance(snapshot.get("candidateWorktree"), dict) else {}
    baseline_score = float(baseline_judgment.get("score") or 0.0)
    candidate_score = float(candidate_judgment.get("score") or 0.0)
    delta = round(candidate_score - baseline_score, 3)
    judge_recommendation = str(
        candidate_judgment.get("recommendation")
        or candidate_judgment.get("decision")
        or "INCONCLUSIVE"
    ).strip().upper()
    rubric_hash = str(judge_rubric.get("rubricHash") or "")
    changed_files = list(worktree.get("changedFiles") or [])
    candidate_variant = worktree.get("variant") if isinstance(worktree.get("variant"), dict) else {}
    high_risk_files = [item for item in changed_files if bool(item.get("highRisk"))]
    gates = [
        {
            "name": "judge_scored_twice",
            "status": (
                "pass"
                if str(baseline_judgment.get("status") or "") == "success"
                and str(candidate_judgment.get("status") or "") == "success"
                and rubric_hash
                and str(baseline_judgment.get("rubricHash") or "") == rubric_hash
                and str(candidate_judgment.get("rubricHash") or "") == rubric_hash
                else "fail"
            ),
            "reason": "两次评分均来自同一 Judge 会话，并使用同一个冻结 rubric。",
        },
        {
            "name": "judge_recommendation",
            "status": "advisory",
            "reason": (
                f"Judge recommendation={judge_recommendation}，复跑分数 {candidate_score}，"
                f"基线分数 {baseline_score}，delta={delta}；仅供用户决策参考。"
            ),
        },
        {
            "name": "candidate_modified",
            "status": "pass" if changed_files else "fail",
            "reason": f"候选工作树改动文件数：{len(changed_files)}",
        },
        {
            "name": "candidate_variant_bound",
            "status": "pass" if _candidate_variant_is_bound(candidate_variant) else "fail",
            "reason": (
                f"候选已绑定 checkpoint={candidate_variant.get('checkpointCommit')}，"
                f"patch={candidate_variant.get('patchSha256')}。"
                if _candidate_variant_is_bound(candidate_variant)
                else "候选缺少可验证的 checkpoint/补丁绑定，禁止自动保留。"
            ),
        },
        {
            "name": "self_edit_finished",
            "status": "pass" if str(modification.get("status") or "") == "success" else "fail",
            "reason": str(modification.get("summary") or modification.get("status") or ""),
        },
        {
            "name": "high_risk_files",
            "status": "pass" if not high_risk_files else "hold",
            "reason": "未触碰高风险文件。" if not high_risk_files else "候选触碰了高风险文件，需要人工确认。",
            "files": [item.get("path") for item in high_risk_files],
        },
    ]
    mode = str(options.get("mode") or "auto")
    technical_failures = [
        gate
        for gate in gates
        if gate["name"] != "judge_recommendation" and gate["status"] != "pass"
    ]
    reason = (
        f"Judge 建议 {judge_recommendation}，但评分和建议仅供参考；"
        "最终是否批准由用户决定。"
        if not technical_failures
        else (
            f"Judge 建议 {judge_recommendation}；仍有 {len(technical_failures)} 个技术完整性项"
            "需要在受控合入前处理。"
        )
    )
    return {
        "mode": mode,
        "approvalMode": str(
            snapshot.get("approvalMode") or options.get("approvalMode") or "human"
        ),
        "evaluationState": _evaluation_state(snapshot),
        "scoreSource": "judge_agent",
        "judgeRecommendation": judge_recommendation,
        "judgeDecision": judge_recommendation,
        "baselineScore": baseline_score,
        "candidateScore": candidate_score,
        "scoreDelta": delta,
        "recommendedAction": "approval_decision",
        "reason": reason,
        "gates": gates,
        "highRisk": bool(high_risk_files),
        "baselineExecution": {
            "successes": baseline.get("successes"),
            "total": baseline.get("total"),
            "executionScore": baseline.get("executionScore"),
        },
        "rerunExecution": {
            "successes": candidate.get("successes"),
            "total": candidate.get("total"),
            "executionScore": candidate.get("executionScore"),
        },
    }


def _finish_by_decision(snapshot: dict[str, Any], decision: dict[str, Any], options: dict[str, Any]) -> None:
    del options
    judge_recommendation = str(
        decision.get("judgeRecommendation")
        or decision.get("judgeDecision")
        or "INCONCLUSIVE"
    )
    approval_mode = str(snapshot.get("approvalMode") or "human").strip().lower()
    outcome = "awaiting_agent_approval" if approval_mode == "agent" else "awaiting_user_approval"
    message = (
        f"Judge 双次评分完成（建议：{judge_recommendation}），"
        f"候选工作树已保留，最终由{'独立审批 Agent' if approval_mode == 'agent' else '用户'}审批。"
    )
    finished = _now_iso()
    snapshot["status"] = "done"
    snapshot["phase"] = "complete"
    snapshot["runtimeStatus"] = "idle"
    snapshot["outcome"] = outcome
    snapshot["latestMessage"] = message
    snapshot["finishedAt"] = finished
    snapshot["updatedAt"] = finished
    _append_stage(snapshot, "complete", "done", message)
    _persist_snapshot(snapshot, active_run_id="")
    _record_worktree_scene_event(
        "complete",
        "supervised_worktree_run.completed",
        run_id=str(snapshot.get("runId") or ""),
        outcome="succeeded",
        fields={
            "outcome": outcome,
            "baselineScore": decision.get("baselineScore"),
            "candidateScore": decision.get("candidateScore"),
            "scoreDelta": decision.get("scoreDelta"),
        },
        lifecycle=True,
    )


def _workflow_progress_callback(snapshot: dict[str, Any], role: str, step_id: str) -> Callable[[dict[str, Any]], None]:
    def _callback(event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        _record_workflow_progress(snapshot, role=role, step_id=step_id, event=event)

    return _callback


def _record_workflow_progress(
    snapshot: dict[str, Any],
    *,
    role: str,
    step_id: str,
    event: dict[str, Any],
) -> None:
    normalized_step = step_id if step_id in WORKFLOW_STEP_IDS else "improve"
    progress = snapshot.get("workflowProgress")
    if not isinstance(progress, dict):
        progress = {}
        snapshot["workflowProgress"] = progress
    existing = progress.get(normalized_step) if isinstance(progress.get(normalized_step), dict) else {}

    def _text(*values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    session_fallback = ""
    if normalized_step in {"baseline_eval", "improve"}:
        session_fallback = str(snapshot.get("baselineConversationSessionId") or "")
    elif normalized_step in {"baseline_judge", "rerun_judge"}:
        session_fallback = str(snapshot.get("judgeConversationSessionId") or "")
    elif normalized_step == "rerun_eval":
        session_fallback = str(snapshot.get("rerunConversationSessionId") or "")
    conversation_session_id = _text(
        event.get("conversation_session_id"),
        event.get("conversationSessionId"),
        existing.get("conversationSessionId"),
        session_fallback,
    )
    conversation_turn_id = _text(
        event.get("conversation_turn_id"),
        event.get("conversationTurnId"),
        event.get("turn_id"),
        event.get("turnId"),
        existing.get("conversationTurnId"),
    )
    updated_at = _text(event.get("updated_at"), event.get("updatedAt"), _now_iso())
    latest_output = _text(event.get("latest_output"), event.get("latestOutput"))
    latest_label = _text(event.get("latest_output_label"), event.get("latestOutputLabel"))
    phase = _text(event.get("phase"), existing.get("phase"))
    live_preview = _bounded_text(latest_output or latest_label or phase or existing.get("livePreview"), limit=280)
    conversation_messages = event.get("conversation_messages") or event.get("conversationMessages")
    if not isinstance(conversation_messages, list):
        conversation_messages = existing.get("conversationMessages") if isinstance(existing.get("conversationMessages"), list) else []
    transcript = event.get("transcript")
    if not isinstance(transcript, list):
        transcript = existing.get("transcript") if isinstance(existing.get("transcript"), list) else []

    progress[normalized_step] = {
        "stepId": normalized_step,
        "role": str(role or "").strip().lower(),
        "status": "running",
        "phase": phase,
        "conversationPath": _text(event.get("conversation_path"), event.get("conversationPath"), f"session:{conversation_session_id}" if conversation_session_id else ""),
        "conversationSessionId": conversation_session_id,
        "conversationTurnId": conversation_turn_id,
        "latestInput": _text(event.get("latest_input"), event.get("latestInput"), existing.get("latestInput")),
        "latestOutput": latest_output,
        "latestOutputKind": _text(event.get("latest_output_kind"), event.get("latestOutputKind"), existing.get("latestOutputKind")),
        "latestOutputLabel": latest_label,
        "livePreview": live_preview,
        "updatedAt": updated_at,
        "conversationMessages": conversation_messages[-20:],
        "transcript": transcript[-20:],
    }
    if role == "baseline" and conversation_session_id:
        snapshot["baselineConversationSessionId"] = conversation_session_id
    elif role == "baseline_rerun" and conversation_session_id:
        snapshot["rerunConversationSessionId"] = conversation_session_id
    elif role == "judge" and conversation_session_id:
        snapshot["judgeConversationSessionId"] = conversation_session_id
    elif role == "candidate" and conversation_session_id:
        snapshot["candidateConversationSessionId"] = conversation_session_id
    if live_preview:
        snapshot["latestMessage"] = live_preview
    snapshot["updatedAt"] = updated_at
    active_run_id = str(snapshot.get("runId") or "") if str(snapshot.get("status") or "").strip().lower() in _ACTIVE_STATUSES else ""
    _persist_snapshot(snapshot, active_run_id=active_run_id)


def _candidate_conversation_session_id(snapshot: dict[str, Any]) -> str:
    direct = str(snapshot.get("candidateConversationSessionId") or "").strip()
    if direct:
        return direct
    progress = snapshot.get("workflowProgress") if isinstance(snapshot.get("workflowProgress"), dict) else {}
    for step_id in ("improve", "rerun_score"):
        item = progress.get(step_id) if isinstance(progress.get(step_id), dict) else {}
        session_id = str(item.get("conversationSessionId") or "").strip()
        if session_id:
            return session_id
    modification = snapshot.get("candidateModification") if isinstance(snapshot.get("candidateModification"), dict) else {}
    for key in ("conversationSessionId", "sessionId"):
        session_id = str(modification.get(key) or "").strip()
        if session_id:
            return session_id
    summary = modification.get("conversationSummary") if isinstance(modification.get("conversationSummary"), dict) else {}
    backend = summary.get("conversation_backend") if isinstance(summary.get("conversation_backend"), dict) else {}
    session_id = str(backend.get("session_id") or backend.get("sessionId") or "").strip()
    if session_id:
        return session_id
    camel_backend = summary.get("conversationBackend") if isinstance(summary.get("conversationBackend"), dict) else {}
    return str(camel_backend.get("sessionId") or camel_backend.get("session_id") or "").strip()


def _evaluation_conversation_session_id(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("conversationSessionId", "sessionId"):
        session_id = str(payload.get(key) or "").strip()
        if session_id:
            return session_id
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    for item in cases:
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("conversationSessionId") or item.get("sessionId") or "").strip()
        if session_id:
            return session_id
    summary = payload.get("conversationSummary") if isinstance(payload.get("conversationSummary"), dict) else {}
    backend = summary.get("conversation_backend") if isinstance(summary.get("conversation_backend"), dict) else {}
    return str(backend.get("session_id") or backend.get("sessionId") or "").strip()


def _is_self_evolution_worktree_snapshot(snapshot: dict[str, Any]) -> bool:
    self_origin = snapshot.get("selfEvolutionOrigin") if isinstance(snapshot.get("selfEvolutionOrigin"), dict) else {}
    if str(self_origin.get("sourceTrack") or "").strip() == "self_evolution":
        return True
    start_request = snapshot.get("startRequest") if isinstance(snapshot.get("startRequest"), dict) else {}
    request_source = str(start_request.get("requestSource") or "").strip()
    initiator = str(start_request.get("initiator") or "").strip()
    return request_source == SELF_EVOLUTION_WORKTREE_ROUTE or initiator == SELF_EVOLUTION_RISKY_WRITE_INITIATOR


def _build_self_evolution_workflow_steps(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    progress = snapshot.get("workflowProgress") if isinstance(snapshot.get("workflowProgress"), dict) else {}
    action_states = snapshot.get("actionStates") if isinstance(snapshot.get("actionStates"), dict) else {}
    baseline = snapshot.get("baseline") if isinstance(snapshot.get("baseline"), dict) else {}
    candidate = snapshot.get("candidate") if isinstance(snapshot.get("candidate"), dict) else {}
    modification = snapshot.get("candidateModification") if isinstance(snapshot.get("candidateModification"), dict) else {}
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    merge_analysis = snapshot.get("mergeAnalysis") if isinstance(snapshot.get("mergeAnalysis"), dict) else {}
    worktree = snapshot.get("candidateWorktree") if isinstance(snapshot.get("candidateWorktree"), dict) else {}
    changed_files = list(worktree.get("changedFiles") or [])
    status = str(snapshot.get("status") or "").strip().lower()
    phase = str(snapshot.get("phase") or "").strip().lower()
    candidate_session_id = _candidate_conversation_session_id(snapshot)

    def _progress_item(step_id: str) -> dict[str, Any]:
        return progress.get(step_id) if isinstance(progress.get(step_id), dict) else {}

    conversation_progress = _progress_item("improve") or _progress_item("rerun_score") or _progress_item("baseline_eval")
    conversation_turn_id = str(conversation_progress.get("conversationTurnId") or "").strip()
    conversation_messages = list(conversation_progress.get("conversationMessages") or [])
    self_running = status in _ACTIVE_STATUSES and phase not in {"complete", "failed", "baseline_unavailable", "shutdown"}
    self_terminal_status = "failed" if status == "failed" else ("cancelled" if status == "cancelled" else "done")
    self_status = "running" if self_running else (self_terminal_status if status in _TERMINAL_STATUSES else "pending")
    approval_status = "pending" if status == "done" else ("failed" if status == "failed" else ("cancelled" if status == "cancelled" else "pending"))
    self_summary = (
        modification.get("summary")
        or (snapshot.get("reflection") if isinstance(snapshot.get("reflection"), dict) else {}).get("summary")
        or decision.get("reason")
        or candidate.get("summary")
        or baseline.get("summary")
        or "等待自进化 Agent 在候选 worktree 中完成分析、改良和复跑。"
    )
    self_preview = (
        _workflow_live_preview(snapshot, "improve")
        or _workflow_live_preview(snapshot, "rerun_score")
        or _workflow_live_preview(snapshot, "baseline_eval")
        or self_summary
    )

    return [
        {
            "id": "self_evolution",
            "label": "自进化",
            "ownerKind": "agent",
            "role": "candidate",
            "status": self_status,
            "current": self_running or status not in _TERMINAL_STATUSES,
            "summary": _bounded_text(self_summary),
            "livePreview": _bounded_text(self_preview),
            "metrics": {
                "baselineScore": decision.get("baselineScore", baseline.get("score")),
                "candidateScore": decision.get("candidateScore", candidate.get("score")),
                "scoreDelta": decision.get("scoreDelta"),
                "changedFileCount": len(changed_files),
            },
            "conversationSessionId": candidate_session_id,
            "conversationTurnId": conversation_turn_id,
            "chatRoute": _workflow_chat_route(candidate_session_id),
            "conversationMessages": conversation_messages,
        },
        {
            "id": "approval",
            "label": "审批",
            "ownerKind": "agent" if str(snapshot.get("approvalMode") or "human") == "agent" else "human",
            "role": "auditor" if str(snapshot.get("approvalMode") or "human") == "agent" else None,
            "status": approval_status,
            "current": status in _TERMINAL_STATUSES,
            "summary": _bounded_text(_approval_summary(snapshot, decision, merge_analysis, action_states)),
            "livePreview": _bounded_text(str(snapshot.get("latestMessage") or decision.get("reason") or "")),
            "metrics": {
                "baselineScore": decision.get("baselineScore", baseline.get("score")),
                "candidateScore": decision.get("candidateScore", candidate.get("score")),
                "scoreDelta": decision.get("scoreDelta"),
                "changedFileCount": len(changed_files),
            },
            "conversationSessionId": "",
            "conversationTurnId": "",
            "chatRoute": "",
            "conversationMessages": [],
        },
    ]


def _build_workflow_steps(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    progress = snapshot.get("workflowProgress") if isinstance(snapshot.get("workflowProgress"), dict) else {}
    action_states = snapshot.get("actionStates") if isinstance(snapshot.get("actionStates"), dict) else {}
    baseline = snapshot.get("baseline") if isinstance(snapshot.get("baseline"), dict) else {}
    candidate = snapshot.get("candidate") if isinstance(snapshot.get("candidate"), dict) else {}
    baseline_judgment = snapshot.get("baselineJudgment") if isinstance(snapshot.get("baselineJudgment"), dict) else {}
    candidate_judgment = snapshot.get("candidateJudgment") if isinstance(snapshot.get("candidateJudgment"), dict) else {}
    modification = snapshot.get("candidateModification") if isinstance(snapshot.get("candidateModification"), dict) else {}
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    merge_analysis = snapshot.get("mergeAnalysis") if isinstance(snapshot.get("mergeAnalysis"), dict) else {}
    workflow_current = _current_workflow_step_id(snapshot)

    def _step_progress(step_id: str) -> dict[str, Any]:
        return progress.get(step_id) if isinstance(progress.get(step_id), dict) else {}

    def _conversation_fields(step_id: str, fallback_session_id: str = "") -> dict[str, Any]:
        item = _step_progress(step_id)
        session_id = str(item.get("conversationSessionId") or fallback_session_id or "").strip()
        turn_id = str(item.get("conversationTurnId") or "").strip()
        return {
            "conversationSessionId": session_id,
            "conversationTurnId": turn_id,
            "chatRoute": _workflow_chat_route(session_id),
            "conversationMessages": list(item.get("conversationMessages") or []),
        }

    baseline_session_id = str(snapshot.get("baselineConversationSessionId") or "")
    rerun_session_id = str(snapshot.get("rerunConversationSessionId") or "")
    judge_session_id = str(snapshot.get("judgeConversationSessionId") or "")
    baseline_fields = _conversation_fields("baseline_eval", baseline_session_id)
    baseline_judge_fields = _conversation_fields("baseline_judge", judge_session_id)
    improve_fields = _conversation_fields("improve", baseline_session_id)
    rerun_fields = _conversation_fields("rerun_eval", rerun_session_id)
    rerun_judge_fields = _conversation_fields("rerun_judge", judge_session_id)
    changed_files = list((snapshot.get("candidateWorktree") if isinstance(snapshot.get("candidateWorktree"), dict) else {}).get("changedFiles") or [])
    approval_status = "pending" if str(snapshot.get("status") or "").strip().lower() == "done" else _workflow_status(snapshot, "approval")
    if str(snapshot.get("status") or "").strip().lower() in {"failed", "cancelled"}:
        approval_status = str(snapshot.get("status") or "").strip().lower()

    return [
        {
            "id": "baseline_eval",
            "label": "基线运行",
            "ownerKind": "agent",
            "role": "baseline",
            "status": _workflow_status(snapshot, "baseline_eval"),
            "current": workflow_current == "baseline_eval",
            "summary": _bounded_text(baseline.get("summary") or "等待基线评测。"),
            "livePreview": _workflow_live_preview(snapshot, "baseline_eval", baseline.get("summary")),
            "metrics": _score_metrics(baseline),
            **baseline_fields,
        },
        {
            "id": "baseline_judge",
            "label": "基线评分",
            "ownerKind": "agent",
            "role": "judge",
            "status": _workflow_status(snapshot, "baseline_judge"),
            "current": workflow_current == "baseline_judge",
            "summary": _bounded_text(baseline_judgment.get("summary") or "等待 Judge 对基线轨迹评分。"),
            "livePreview": _workflow_live_preview(snapshot, "baseline_judge", baseline_judgment.get("summary")),
            "metrics": {
                "score": baseline_judgment.get("score"),
                "decision": baseline_judgment.get("decision"),
                "scoreSource": "judge_agent",
            },
            **baseline_judge_fields,
        },
        {
            "id": "improve",
            "label": "基线自改",
            "ownerKind": "agent",
            "role": "baseline",
            "status": _workflow_status(snapshot, "improve"),
            "current": workflow_current == "improve",
            "summary": _bounded_text(modification.get("summary") or (snapshot.get("reflection") or {}).get("summary") or "等待原基线 Agent 在同一会话中修改候选 worktree。"),
            "livePreview": _workflow_live_preview(snapshot, "improve", modification.get("summary")),
            "metrics": {"changedFileCount": len(changed_files), "highRiskFileCount": sum(1 for item in changed_files if isinstance(item, dict) and item.get("highRisk"))},
            **improve_fields,
        },
        {
            "id": "rerun_eval",
            "label": "独立复跑",
            "ownerKind": "agent",
            "role": "baseline_rerun",
            "status": _workflow_status(snapshot, "rerun_eval"),
            "current": workflow_current == "rerun_eval",
            "summary": _bounded_text(candidate.get("summary") or "等待在全新会话中独立复跑改进后的基线 Agent。"),
            "livePreview": _workflow_live_preview(snapshot, "rerun_eval", candidate.get("summary")),
            "metrics": _score_metrics(candidate),
            **rerun_fields,
        },
        {
            "id": "rerun_judge",
            "label": "复跑评分",
            "ownerKind": "agent",
            "role": "judge",
            "status": _workflow_status(snapshot, "rerun_judge"),
            "current": workflow_current == "rerun_judge",
            "summary": _bounded_text(decision.get("reason") or candidate_judgment.get("summary") or "等待 Judge 在原评分会话中进行第二次评分。"),
            "livePreview": _workflow_live_preview(snapshot, "rerun_judge", decision.get("reason") or candidate_judgment.get("summary")),
            "metrics": {
                "baselineScore": decision.get("baselineScore"),
                "candidateScore": decision.get("candidateScore"),
                "scoreDelta": decision.get("scoreDelta"),
                "decision": candidate_judgment.get("decision"),
                "scoreSource": "judge_agent",
            },
            **rerun_judge_fields,
        },
        {
            "id": "approval",
            "label": "最终审批与合入",
            "ownerKind": "agent" if str(snapshot.get("approvalMode") or "human") == "agent" else "human",
            "role": "auditor" if str(snapshot.get("approvalMode") or "human") == "agent" else None,
            "status": approval_status,
            "current": workflow_current == "approval",
            "summary": _bounded_text(_approval_summary(snapshot, decision, merge_analysis, action_states)),
            "livePreview": _bounded_text(str(snapshot.get("latestMessage") or decision.get("reason") or "")),
            "metrics": {
                "baselineScore": decision.get("baselineScore"),
                "candidateScore": decision.get("candidateScore"),
                "scoreDelta": decision.get("scoreDelta"),
                "changedFileCount": len(changed_files),
            },
            "conversationSessionId": "",
            "conversationTurnId": "",
            "chatRoute": "",
            "conversationMessages": [],
        },
    ]


def _current_workflow_step_id(snapshot: dict[str, Any]) -> str:
    status = str(snapshot.get("status") or "").strip().lower()
    phase = str(snapshot.get("phase") or "").strip().lower()
    if phase in {"candidate_judge", "decision"}:
        return "rerun_judge"
    if phase == "candidate_evaluation":
        return "rerun_eval"
    if phase in {"reflection", "candidate_worktree", "candidate_modify"}:
        return "improve"
    if phase == "baseline_judge":
        return "baseline_judge"
    if status in _TERMINAL_STATUSES or phase in {"complete", "failed", "baseline_unavailable", "shutdown"}:
        return "approval"
    return "baseline_eval"


def _workflow_status(snapshot: dict[str, Any], step_id: str) -> str:
    status = str(snapshot.get("status") or "").strip().lower()
    phase = str(snapshot.get("phase") or "").strip().lower()
    if status == "failed":
        if step_id == "baseline_eval" and phase == "baseline_unavailable":
            return "failed"
        return "failed" if _current_workflow_step_id(snapshot) == step_id else ("done" if _step_has_output(snapshot, step_id) else "pending")
    if status == "cancelled":
        return "cancelled" if _current_workflow_step_id(snapshot) == step_id else ("done" if _step_has_output(snapshot, step_id) else "pending")
    if step_id == "baseline_eval":
        if phase == "baseline" or (status in _ACTIVE_STATUSES and not snapshot.get("baseline")):
            return "running"
        return "done" if snapshot.get("baseline") else "pending"
    if step_id == "baseline_judge":
        if phase == "baseline_judge":
            return "running"
        return "done" if snapshot.get("baselineJudgment") else "pending"
    if step_id == "improve":
        if phase in {"reflection", "candidate_worktree", "candidate_modify"}:
            return "running"
        return "done" if snapshot.get("candidateModification") else "pending"
    if step_id == "rerun_eval":
        if phase == "candidate_evaluation":
            return "running"
        return "done" if snapshot.get("candidate") else "pending"
    if step_id == "rerun_judge":
        if phase in {"candidate_judge", "decision"}:
            return "running"
        return "done" if snapshot.get("candidateJudgment") or snapshot.get("decision") else "pending"
    if step_id == "approval":
        return "pending"
    return "pending"


def _step_has_output(snapshot: dict[str, Any], step_id: str) -> bool:
    if step_id == "baseline_eval":
        return bool(snapshot.get("baseline"))
    if step_id == "baseline_judge":
        return bool(snapshot.get("baselineJudgment"))
    if step_id == "improve":
        return bool(snapshot.get("candidateModification"))
    if step_id == "rerun_eval":
        return bool(snapshot.get("candidate"))
    if step_id == "rerun_judge":
        return bool(snapshot.get("candidateJudgment") or snapshot.get("decision"))
    if step_id == "approval":
        return bool(snapshot.get("decision") or snapshot.get("mergeAnalysis"))
    return False


def _workflow_live_preview(snapshot: dict[str, Any], step_id: str, fallback: Any = "") -> str:
    progress = snapshot.get("workflowProgress") if isinstance(snapshot.get("workflowProgress"), dict) else {}
    item = progress.get(step_id) if isinstance(progress.get(step_id), dict) else {}
    return _bounded_text(item.get("livePreview") or item.get("latestOutput") or fallback or "")


def _score_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "executionScore": payload.get("executionScore"),
        "successes": payload.get("successes"),
        "total": payload.get("total"),
        "failures": payload.get("failures"),
    }


def _approval_summary(
    snapshot: dict[str, Any],
    decision: dict[str, Any],
    merge_analysis: dict[str, Any],
    action_states: dict[str, Any],
) -> str:
    if str(snapshot.get("status") or "").strip().lower() == "done":
        action = str(decision.get("recommendedAction") or snapshot.get("outcome") or "").strip()
        delta = decision.get("scoreDelta")
        if action:
            actor = "独立审批 Agent" if str(snapshot.get("approvalMode") or "human") == "agent" else "用户"
            return f"等待{actor}审批：建议 {action}，scoreDelta={delta}。"
        if bool((action_states.get("merge") if isinstance(action_states.get("merge"), dict) else {}).get("enabled")):
            return "候选可进入人工入库或合并。"
    if merge_analysis:
        return str(merge_analysis.get("reason") or merge_analysis.get("status") or "").strip()
    return str(snapshot.get("latestMessage") or "等待最终结果、改进提案和样本评审证据。")


def _workflow_chat_route(session_id: str) -> str:
    normalized = str(session_id or "").strip()
    if not normalized:
        return ""
    return f"/chat?session={normalized}"


def _bounded_text(value: Any, *, limit: int = 280) -> str:
    text = str(value or "").strip().replace("\r", " ").replace("\n", " ")
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}…"


def _with_merge_analysis(snapshot: dict[str, Any]) -> dict[str, Any]:
    updated = _clone(snapshot)
    updated["mergeAnalysis"] = _build_merge_analysis(updated)
    updated["updatedAt"] = _now_iso()
    _persist_snapshot(updated, active_run_id="")
    return updated


def _build_merge_analysis(snapshot: dict[str, Any]) -> dict[str, Any]:
    project_root = _snapshot_project_root(snapshot)
    worktree = snapshot.get("candidateWorktree") if isinstance(snapshot.get("candidateWorktree"), dict) else {}
    candidate_path = Path(str(worktree.get("path") or ""))
    if not candidate_path.exists() or not candidate_path.is_dir():
        return {
            "status": "unavailable",
            "mergeAllowed": False,
            "reason": "候选工作树不可用，无法合并。",
            "changedFiles": [],
            "overlapFiles": [],
            "highRiskFiles": [],
            "blockers": ["missing_candidate_worktree"],
        }
    changed_files = _candidate_changed_files(candidate_path, baseline_untracked=worktree.get("untrackedFiles"))
    dirty_main = {item["path"] for item in _git_status_files(project_root)}
    overlap = [item for item in changed_files if item["path"] in dirty_main]
    high_risk = [item for item in changed_files if bool(item.get("highRisk"))]
    blockers: list[str] = []
    frozen_variant = worktree.get("variant") if isinstance(worktree.get("variant"), dict) else {}
    variant_status = "verified"
    current_variant: dict[str, Any] = {}
    if not _candidate_variant_is_bound(frozen_variant):
        variant_status = "unbound"
        blockers.append("candidate_variant_unbound")
    else:
        try:
            current_variant = _build_candidate_variant(
                candidate_path,
                checkpoint_commit=str(frozen_variant.get("checkpointCommit") or ""),
                changed_files=changed_files,
                baseline_untracked=worktree.get("untrackedFiles"),
            )
        except SupervisedWorktreeRunValidationError:
            variant_status = "unverifiable"
            blockers.append("candidate_variant_unverifiable")
        else:
            if str(current_variant.get("variantId") or "") != str(
                frozen_variant.get("variantId") or ""
            ):
                variant_status = "drifted"
                blockers.append("candidate_variant_changed_after_judging")
    if overlap:
        blockers.append("main_workspace_overlap")
    approval = snapshot.get("approvalDecision") if isinstance(snapshot.get("approvalDecision"), dict) else {}
    approval_authorized = (
        str(approval.get("status") or "").strip().lower() == "decided"
        and str(approval.get("decision") or "").strip().upper() == "APPROVE"
        and str(approval.get("evaluationState") or "").strip().upper() == "VALID"
    )
    if high_risk and not approval_authorized:
        blockers.append("high_risk_files")
    if not changed_files:
        blockers.append("empty_candidate_diff")
    if _review_gate_requires_approval(snapshot):
        blockers.append("supervised_review_pending")
    return {
        "status": "blocked" if blockers else "ready",
        "mergeAllowed": not blockers,
        "reason": "合并前检查通过。" if not blockers else "合并前检查发现冲突、高风险项或待审核项。",
        "changedFiles": changed_files,
        "overlapFiles": [item["path"] for item in overlap],
        "highRiskFiles": [item["path"] for item in high_risk],
        "blockers": blockers,
        "candidateVariantStatus": variant_status,
        "candidateVariantId": str(frozen_variant.get("variantId") or ""),
        "currentCandidateVariantId": str(current_variant.get("variantId") or ""),
        "mainDirtyFiles": sorted(dirty_main),
        "reviewGate": snapshot.get("reviewGate") if isinstance(snapshot.get("reviewGate"), dict) else {},
        "analyzedAt": _now_iso(),
    }


def _record_approval_decision(
    snapshot: dict[str, Any],
    *,
    decision: str,
    actor_kind: str,
    reason: str = "",
    actor_id: str = "",
    conversation_session_id: str = "",
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    status = str(snapshot.get("status") or "").strip().lower()
    if status not in _TERMINAL_STATUSES:
        raise SupervisedWorktreeRunActionError("候选运行尚未结束，不能提前作出最终审批。")
    normalized_decision = str(decision or "").strip().upper()
    if normalized_decision not in APPROVAL_DECISIONS:
        raise SupervisedWorktreeRunValidationError("审批决定必须是 APPROVE、REJECT 或 RERUN_REQUIRED。")
    approval_mode = str(snapshot.get("approvalMode") or "human").strip().lower()
    normalized_actor = str(actor_kind or "").strip().lower()
    if approval_mode not in APPROVAL_MODES:
        raise SupervisedWorktreeRunActionError("本轮审批模式无效，禁止写入审批决定。")
    if normalized_actor != approval_mode:
        raise SupervisedWorktreeRunActionError(
            f"本轮审批模式为 {approval_mode}，不能由 {normalized_actor or 'unknown'} 写入最终决定。"
        )
    existing = (
        snapshot.get("approvalDecision")
        if isinstance(snapshot.get("approvalDecision"), dict)
        else {}
    )
    if str(existing.get("status") or "").strip().lower() == "decided":
        raise SupervisedWorktreeRunActionError("最终审批记录不可变，不能覆盖已有决定。")
    evaluation_state = _evaluation_state(snapshot)
    if normalized_decision == "APPROVE" and evaluation_state != "VALID":
        raise SupervisedWorktreeRunActionError(
            f"当前评估状态为 {evaluation_state}，禁止批准合入；请拒绝或要求复跑。"
        )
    judgment = (
        snapshot.get("candidateJudgment")
        if isinstance(snapshot.get("candidateJudgment"), dict)
        else {}
    )
    recommendation = str(
        judgment.get("recommendation") or judgment.get("decision") or "INCONCLUSIVE"
    ).strip().upper()
    updated = _clone(snapshot)
    decided_at = _now_iso()
    updated["approvalDecision"] = {
        "schemaVersion": 1,
        "mode": approval_mode,
        "status": "decided",
        "decision": normalized_decision,
        "evaluationState": evaluation_state,
        "reason": _safe_metadata_text(reason, limit=1000),
        "evidenceRefs": [
            _safe_metadata_text(item, limit=240)
            for item in list(evidence_refs or [])[:20]
            if str(item or "").strip()
        ],
        "judgeRecommendation": recommendation,
        "baselineScore": (updated.get("decision") or {}).get("baselineScore"),
        "candidateScore": (updated.get("decision") or {}).get("candidateScore"),
        "scoreDelta": (updated.get("decision") or {}).get("scoreDelta"),
        "decidedBy": {
            "kind": normalized_actor,
            "actorId": _safe_metadata_text(actor_id, limit=160),
            "conversationSessionId": _safe_metadata_text(
                conversation_session_id,
                limit=200,
            ),
        },
        "decidedAt": decided_at,
    }
    gate = updated.get("reviewGate") if isinstance(updated.get("reviewGate"), dict) else {}
    updated["reviewGate"] = {
        **gate,
        "required": True,
        "status": "approved" if normalized_decision == "APPROVE" else "rejected",
        "approvedAt": decided_at if normalized_decision == "APPROVE" else "",
        "reviewerNote": _safe_metadata_text(reason, limit=500),
        "judgeRecommendation": recommendation,
        "overrodeJudgeRecommendation": (
            normalized_decision == "APPROVE" and recommendation != "APPROVE"
        ),
    }
    if normalized_decision == "REJECT":
        updated["outcome"] = "approval_rejected"
    elif normalized_decision == "RERUN_REQUIRED":
        updated["outcome"] = "approval_rerun_required"
    updated["updatedAt"] = decided_at
    updated["mergeAnalysis"] = _build_merge_analysis(updated)
    _persist_snapshot(updated, active_run_id="")
    return updated


def _request_independent_agent_approval(snapshot: dict[str, Any]) -> dict[str, Any]:
    if str(snapshot.get("approvalMode") or "").strip().lower() != "agent":
        raise SupervisedWorktreeRunActionError("本轮不是 Agent 审批模式。")
    evaluation_state = _evaluation_state(snapshot)
    if evaluation_state != "VALID":
        raise SupervisedWorktreeRunActionError(
            f"当前评估状态为 {evaluation_state}，不能启动批准流程；请补证据或复跑。"
        )
    if str(snapshot.get("executionMode") or "simulation").strip().lower() != "real":
        recommendation = str(
            ((snapshot.get("candidateJudgment") or {}).get("recommendation"))
            or "INCONCLUSIVE"
        ).strip().upper()
        simulated_decision = "APPROVE" if recommendation == "APPROVE" else "RERUN_REQUIRED"
        return _record_approval_decision(
            snapshot,
            decision=simulated_decision,
            actor_kind="agent",
            actor_id="simulated-independent-approval-agent",
            reason="Simulation approval projection; no real Approval Agent was called.",
            evidence_refs=["simulation:approval"],
        )

    bindings = snapshot.get("agentBindings") if isinstance(snapshot.get("agentBindings"), dict) else {}
    agent_binding = dict(bindings.get("auditor") or {})
    agent_id = str(agent_binding.get("agentId") or "").strip()
    if not agent_id:
        raise SupervisedWorktreeRunActionError("缺少独立审批 Agent 绑定，禁止 Agent 审批。")
    merge_analysis = _build_merge_analysis(snapshot)
    approval_neutral_blockers = [
        item
        for item in list(merge_analysis.get("blockers") or [])
        if str(item) != "supervised_review_pending"
    ]
    merge_analysis = {
        **merge_analysis,
        "blockers": approval_neutral_blockers,
        "mergeAllowedAfterApproval": not approval_neutral_blockers,
    }
    evidence_package = {
        "runId": str(snapshot.get("runId") or ""),
        "evaluationState": evaluation_state,
        "judgeRubric": snapshot.get("judgeRubric") or {},
        "baselineJudgment": snapshot.get("baselineJudgment") or {},
        "candidateJudgment": snapshot.get("candidateJudgment") or {},
        "decision": snapshot.get("decision") or {},
        "mergeAnalysis": merge_analysis,
        "candidateVariant": (
            (snapshot.get("candidateWorktree") or {}).get("variant")
            if isinstance(snapshot.get("candidateWorktree"), dict)
            else {}
        ),
    }
    prompt = (
        "你是独立审批 Agent，不是本轮 Judge，也不是基线 Agent。"
        "你只能读取冻结评分、评估状态、候选版本和合并分析，不能调用工具、修改文件或改写评分。\n"
        "分数不是硬门槛。必须同时审查 evaluationState、证据完整性、候选版本绑定、冲突和风险。"
        "仅当 evaluationState=VALID 且证据足以承担合入风险时才可 APPROVE；"
        "否则输出 REJECT 或 RERUN_REQUIRED。\n"
        "最后单独输出严格 JSON：\n"
        'SUPERVISED_AGENT_JUDGMENT: {"phase":"approval_decision",'
        '"decision":"APPROVE|REJECT|RERUN_REQUIRED","reason":"...",'
        '"evidence_refs":[]}\n'
        f"冻结审批证据：{json.dumps(evidence_package, ensure_ascii=False, sort_keys=True)}"
    )
    result = run_supervised_conversation_harness(
        repo_root=_snapshot_project_root(snapshot),
        mode="single_turn",
        prompt=prompt,
        scenario="supervised_independent_approval",
        timeout_seconds=600,
        expect_restart=False,
        post_restart_observe_seconds=0,
        keep_worktree=True,
        agent_binding=agent_binding,
        mental_model_mode=str(snapshot.get("mentalModelMode") or "follow"),
        mental_model_enabled=snapshot.get("mentalModelEnabled"),
        workspace_override=_snapshot_project_root(snapshot),
        conversation_session_id="",
    )
    raw_decision = (result.evolution_summary or {}).get("agent_judgment")
    observed_session_id = str((result.process_summary or {}).get("session_id") or "").strip()
    forbidden_sessions = {
        str(snapshot.get("baselineConversationSessionId") or "").strip(),
        str(snapshot.get("rerunConversationSessionId") or "").strip(),
        str(snapshot.get("judgeConversationSessionId") or "").strip(),
    } - {""}
    if (
        result.status != "success"
        or not observed_session_id
        or observed_session_id in forbidden_sessions
        or not isinstance(raw_decision, dict)
        or str(raw_decision.get("phase") or "").strip().lower() != "approval_decision"
    ):
        raise SupervisedWorktreeRunActionError(
            result.reason or "独立审批 Agent 未在新会话中输出有效最终决定。"
        )
    decision = str(raw_decision.get("decision") or "").strip().upper()
    updated = _record_approval_decision(
        snapshot,
        decision=decision,
        actor_kind="agent",
        actor_id=agent_id,
        conversation_session_id=observed_session_id,
        reason=str(raw_decision.get("reason") or ""),
        evidence_refs=list(raw_decision.get("evidence_refs") or []),
    )
    updated["approvalConversationSessionId"] = observed_session_id
    _persist_snapshot(updated, active_run_id="")
    return updated


def _merge_candidate(snapshot: dict[str, Any], *, force: bool) -> dict[str, Any]:
    updated = _with_merge_analysis(snapshot)
    analysis = updated.get("mergeAnalysis") if isinstance(updated.get("mergeAnalysis"), dict) else {}
    blockers = set(str(item) for item in list(analysis.get("blockers") or []))
    if "supervised_review_pending" in blockers:
        raise SupervisedWorktreeRunActionError(
            "候选仍处于最终审批 pending，必须先完成审批，不能用 force 绕过。"
        )
    judgment = updated.get("candidateJudgment") if isinstance(updated.get("candidateJudgment"), dict) else {}
    approval = updated.get("approvalDecision") if isinstance(updated.get("approvalDecision"), dict) else {}
    if (
        str(approval.get("status") or "").strip().lower() != "decided"
        or str(approval.get("decision") or "").strip().upper() != "APPROVE"
    ):
        raise SupervisedWorktreeRunActionError("缺少不可变的 APPROVE 审批记录，禁止受控合入。")
    if str(approval.get("evaluationState") or "").strip().upper() != "VALID":
        raise SupervisedWorktreeRunActionError("审批记录未绑定 VALID 评估状态，禁止受控合入。")
    if not judge_merge_allowed(judgment, force=force):
        raise SupervisedWorktreeRunActionError("Judge 第二次结构化评分状态不可用于审批，禁止受控合入。")
    if "main_workspace_overlap" in blockers:
        overlap_files = ", ".join(str(item) for item in list(analysis.get("overlapFiles") or []))
        raise SupervisedWorktreeRunActionError(
            f"主工作区冲突不能被 force 覆盖：{overlap_files or 'unknown'}。"
        )
    variant_blockers = {
        "candidate_variant_unbound",
        "candidate_variant_unverifiable",
        "candidate_variant_changed_after_judging",
    }
    if blockers.intersection(variant_blockers):
        raise SupervisedWorktreeRunActionError(
            "候选版本绑定与 Judge 评分时不一致，禁止受控合入。"
        )
    if "empty_candidate_diff" in blockers:
        raise SupervisedWorktreeRunActionError("候选差异为空，禁止受控合入。")
    if not bool(analysis.get("mergeAllowed")) and not force:
        raise SupervisedWorktreeRunActionError(
            "合并分析未通过。请先处理冲突/高风险项，或在明确确认后使用 force。"
        )
    worktree = updated.get("candidateWorktree") if isinstance(updated.get("candidateWorktree"), dict) else {}
    candidate_path = Path(str(worktree.get("path") or ""))
    if not candidate_path.exists() or not candidate_path.is_dir():
        raise SupervisedWorktreeRunActionError("候选工作树不可用或已被清理，无法执行合并。")
    changed_files = list(analysis.get("changedFiles") or [])
    rollback_manifest = _apply_candidate_files(
        _snapshot_project_root(updated),
        candidate_path,
        changed_files,
        force=force,
    )
    updated["merge"] = {
        "status": "merged",
        "mergedAt": _now_iso(),
        "force": force,
        "triggeredBy": {
            "role": "approval_executor",
            "approvalMode": str(approval.get("mode") or ""),
            "conversationSessionId": str(
                ((approval.get("decidedBy") or {}).get("conversationSessionId"))
                if isinstance(approval.get("decidedBy"), dict)
                else ""
            ),
            "decision": str(judgment.get("decision") or judgment.get("recommendation") or ""),
            "mechanism": "controlled_candidate_apply",
        },
        "changedFiles": [item.get("path") for item in changed_files],
        "rollbackManifestPath": rollback_manifest["path"],
    }
    updated["rollback"] = {
        "status": "available",
        "manifestPath": rollback_manifest["path"],
        "reason": "已生成合并回滚清单。",
    }
    updated["outcome"] = "merged"
    updated["updatedAt"] = _now_iso()
    _persist_snapshot(updated, active_run_id="")
    _record_worktree_scene_event(
        "merge",
        "supervised_worktree_run.merge.applied",
        run_id=str(updated.get("runId") or ""),
        outcome="succeeded",
        fields={"force": force, "fileCount": len(changed_files)},
        lifecycle=True,
    )
    return updated


def _review_gate_requires_approval(snapshot: dict[str, Any]) -> bool:
    gate = snapshot.get("reviewGate") if isinstance(snapshot.get("reviewGate"), dict) else {}
    if not bool(gate.get("required")):
        return False
    return str(gate.get("status") or "").strip().lower() != REVIEW_GATE_APPROVED


def _approve_review_gate(snapshot: dict[str, Any], *, reviewer_note: str = "") -> dict[str, Any]:
    status = str(snapshot.get("status") or "").strip().lower()
    if status not in _TERMINAL_STATUSES:
        raise SupervisedWorktreeRunActionError("候选运行尚未结束，不能提前批准合并 review。")
    gate = snapshot.get("reviewGate") if isinstance(snapshot.get("reviewGate"), dict) else {}
    if not bool(gate.get("required")):
        raise SupervisedWorktreeRunValidationError("此候选没有可审批的受控合入闸门。")
    updated = _clone(snapshot)
    judgment = updated.get("candidateJudgment") if isinstance(updated.get("candidateJudgment"), dict) else {}
    recommendation = str(
        judgment.get("recommendation")
        or judgment.get("decision")
        or "INCONCLUSIVE"
    ).strip().upper()
    overrode_recommendation = recommendation != "APPROVE"
    updated["reviewGate"] = {
        **gate,
        "required": True,
        "status": REVIEW_GATE_APPROVED,
        "approvedAt": _now_iso(),
        "reviewerNote": _safe_metadata_text(reviewer_note, limit=500),
        "judgeRecommendation": recommendation,
        "overrodeJudgeRecommendation": overrode_recommendation,
    }
    updated["updatedAt"] = _now_iso()
    updated["mergeAnalysis"] = _build_merge_analysis(updated)
    _persist_snapshot(updated, active_run_id="")
    self_origin = updated.get("selfEvolutionOrigin") if isinstance(updated.get("selfEvolutionOrigin"), dict) else {}
    _record_worktree_scene_event(
        "review",
        "supervised_worktree_run.review.approved",
        run_id=str(updated.get("runId") or ""),
        outcome="succeeded",
        fields={
            "reviewGateStatus": REVIEW_GATE_APPROVED,
            "sourceTrack": str(self_origin.get("sourceTrack") or ""),
            "reviewerNotePreview": str(reviewer_note or "")[:160],
            "judgeRecommendation": recommendation,
            "overrodeJudgeRecommendation": overrode_recommendation,
        },
        lifecycle=True,
    )
    return updated


def _rollback_merge(snapshot: dict[str, Any]) -> dict[str, Any]:
    rollback = snapshot.get("rollback") if isinstance(snapshot.get("rollback"), dict) else {}
    manifest_path = Path(str(rollback.get("manifestPath") or ""))
    if not manifest_path.exists():
        raise SupervisedWorktreeRunActionError("未找到可执行的合并回滚清单。")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries") if isinstance(manifest.get("entries"), list) else []
    for entry in entries:
        rel = str(entry.get("path") or "")
        target = _safe_project_path(_snapshot_project_root(snapshot), rel)
        if bool(entry.get("existed")):
            data = base64.b64decode(str(entry.get("contentBase64") or ""))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        else:
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
    updated = _clone(snapshot)
    updated["rollback"] = {
        **rollback,
        "status": "rolled_back",
        "rolledBackAt": _now_iso(),
        "reason": "已恢复合并前文件状态。",
    }
    updated["outcome"] = "merge_rolled_back"
    updated["updatedAt"] = _now_iso()
    _persist_snapshot(updated, active_run_id="")
    _record_worktree_scene_event(
        "merge",
        "supervised_worktree_run.merge.rolled_back",
        run_id=str(updated.get("runId") or ""),
        outcome="succeeded",
        fields={"fileCount": len(entries)},
        lifecycle=True,
    )
    return updated


def _apply_candidate_files(
    project_root: Path,
    candidate_path: Path,
    changed_files: list[dict[str, Any]],
    *,
    force: bool,
) -> dict[str, Any]:
    run_id = f"merge-{uuid4().hex[:12]}"
    root = project_root.resolve()
    manifest_dir = _run_store_root(root) / "merge_rollback"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for item in changed_files:
        rel = str(item.get("path") or "").strip()
        if not rel:
            continue
        target = _safe_project_path(root, rel)
        source = _safe_project_path(candidate_path, rel)
        entry = {
            "path": rel,
            "existed": target.exists(),
            "contentBase64": "",
        }
        if target.exists() and target.is_file():
            entry["contentBase64"] = base64.b64encode(target.read_bytes()).decode("ascii")
        entries.append(entry)
        if str(item.get("changeType") or "") == "deleted" or not source.exists():
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            continue
        if source.is_dir():
            raise SupervisedWorktreeRunActionError(f"暂不支持合并目录路径：{rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    manifest_path = manifest_dir / f"{run_id}.json"
    payload = {
        "runId": run_id,
        "createdAt": _now_iso(),
        "force": force,
        "entries": entries,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(manifest_path), "entries": entries}


def _mark_preserved(snapshot: dict[str, Any]) -> dict[str, Any]:
    updated = _clone(snapshot)
    updated["outcome"] = "preserved"
    updated["candidateWorktree"] = {
        **(updated.get("candidateWorktree") if isinstance(updated.get("candidateWorktree"), dict) else {}),
        "preserved": True,
    }
    updated["updatedAt"] = _now_iso()
    _persist_snapshot(updated, active_run_id="")
    return updated


def _discard_candidate(snapshot: dict[str, Any]) -> dict[str, Any]:
    updated = _clone(snapshot)
    cleanup = _cleanup_candidate_worktree(updated)
    updated["outcome"] = "discarded" if cleanup.get("status") == "removed" else "discard_skipped"
    updated["updatedAt"] = _now_iso()
    _persist_snapshot(updated, active_run_id="")
    return updated


def _cleanup_candidate_worktree(snapshot: dict[str, Any]) -> dict[str, Any]:
    project_root = _snapshot_project_root(snapshot)
    worktree = snapshot.get("candidateWorktree") if isinstance(snapshot.get("candidateWorktree"), dict) else {}
    raw_path = str(worktree.get("path") or "").strip()
    checkpoint_ref = str(worktree.get("checkpointRef") or "").strip() or None
    cleanup: dict[str, Any] = {"status": "skipped", "reason": "missing_path", "path": raw_path}
    if raw_path:
        candidate_path = Path(raw_path)
        if candidate_path.exists() and not candidate_path.is_dir():
            cleanup = {"status": "skipped", "reason": "not_directory", "path": raw_path}
            if cleanup["status"] in {"skipped", "failed"}:
                _record_candidate_cleanup_event(snapshot, cleanup)
        else:
            cleanup = _candidate_worktree_cleanup_plan(snapshot, project_root=project_root, worktree=worktree)
            if cleanup["status"] == "allowed":
                try:
                    remove_worktree(project_root, Path(raw_path))
                    cleanup = {**cleanup, "status": "removed", "removedAt": _now_iso()}
                except Exception as exc:
                    cleanup = {
                        **cleanup,
                        "status": "failed",
                        "reason": type(exc).__name__,
                        "message": str(exc)[:300],
                        "failedAt": _now_iso(),
                    }
            else:
                cleanup = {**cleanup, "skippedAt": _now_iso()}
            if cleanup["status"] in {"skipped", "failed"}:
                _record_candidate_cleanup_event(snapshot, cleanup)
    try:
        delete_checkpoint_ref(project_root, checkpoint_ref)
    except Exception:
        pass
    removed = cleanup.get("status") == "removed"
    snapshot["candidateWorktree"] = {
        **worktree,
        "preserved": not removed,
        "cleanup": cleanup,
        **({"removedAt": cleanup.get("removedAt") or _now_iso()} if removed else {}),
    }
    return cleanup


def _candidate_worktree_cleanup_plan(
    snapshot: dict[str, Any],
    *,
    project_root: Path,
    worktree: dict[str, Any],
) -> dict[str, Any]:
    raw_path = str(worktree.get("path") or "").strip()
    run_id = str(snapshot.get("runId") or "").strip()
    if not raw_path:
        return {"status": "skipped", "reason": "missing_path", "path": raw_path}
    try:
        candidate_path = Path(raw_path).expanduser().resolve()
    except Exception:
        return {"status": "skipped", "reason": "invalid_path", "path": raw_path}

    project_root = project_root.resolve()
    if candidate_path == project_root:
        return {"status": "skipped", "reason": "candidate_is_project_root", "path": str(candidate_path)}
    try:
        candidate_path.relative_to(project_root)
        return {"status": "skipped", "reason": "candidate_inside_project_root", "path": str(candidate_path)}
    except ValueError:
        pass

    if not candidate_path.exists():
        return {"status": "skipped", "reason": "missing_path", "path": str(candidate_path)}
    if not candidate_path.is_dir():
        return {"status": "skipped", "reason": "not_directory", "path": str(candidate_path)}

    cleanup_owner = str(worktree.get("cleanupOwner") or "").strip()
    cleanup_run_id = str(worktree.get("cleanupRunId") or "").strip()
    if cleanup_owner == RUN_KIND and cleanup_run_id == run_id:
        return {"status": "allowed", "reason": "owned_candidate_worktree", "path": str(candidate_path)}

    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        candidate_path.relative_to(temp_root)
        is_temp_path = True
    except ValueError:
        is_temp_path = False
    if is_temp_path and candidate_path.name.startswith(f"vibelution-harness-{run_id[:8]}-"):
        return {"status": "allowed", "reason": "legacy_harness_candidate_worktree", "path": str(candidate_path)}

    return {"status": "skipped", "reason": "unowned_candidate_path", "path": str(candidate_path)}


def _record_candidate_cleanup_event(snapshot: dict[str, Any], cleanup: dict[str, Any]) -> None:
    run_id = str(snapshot.get("runId") or "")
    status = str(cleanup.get("status") or "")
    reason = str(cleanup.get("reason") or "")
    message = (
        f"候选工作树清理已跳过：{reason}"
        if status == "skipped"
        else f"候选工作树清理失败：{reason}"
    )
    events = snapshot.setdefault("events", [])
    if isinstance(events, list):
        events.append(
            {
                "type": "candidate_cleanup",
                "message": message,
                "timestamp": _now_iso(),
                "cleanup": cleanup,
            }
        )
    _record_worktree_scene_event(
        "candidate_cleanup",
        f"supervised_worktree_run.candidate_cleanup_{status}",
        run_id=run_id,
        message=message,
        level="warning",
        outcome=status or "observed",
        fields={
            **_snapshot_event_fields(snapshot),
            "cleanupStatus": status,
            "cleanupReason": reason,
            "candidatePath": str(cleanup.get("path") or ""),
        },
        child_log_payload={"cleanup": cleanup},
        lifecycle=True,
    )


def _candidate_changed_files(
    candidate_path: Path,
    *,
    baseline_untracked: Any = None,
) -> list[dict[str, Any]]:
    files = _git_status_files(candidate_path)
    baseline_noise = _baseline_untracked_paths(baseline_untracked)
    return [
        {
            **item,
            "changeType": _change_type(item.get("status", "")),
            "highRisk": _is_high_risk_path(item["path"]),
        }
        for item in files
        if not _is_baseline_untracked_noise(item, baseline_noise)
    ]


def _build_candidate_variant(
    candidate_path: Path,
    *,
    checkpoint_commit: str,
    changed_files: list[dict[str, Any]],
    baseline_untracked: Any = None,
) -> dict[str, Any]:
    normalized_checkpoint = str(checkpoint_commit or "").strip()
    if not normalized_checkpoint:
        raise SupervisedWorktreeRunValidationError("候选工作树缺少 checkpointCommit，无法绑定评测版本。")

    try:
        diff_proc = git_process.run_git(
            ["diff", "--binary", "HEAD", "--"],
            cwd=str(candidate_path),
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise SupervisedWorktreeRunValidationError(f"无法读取候选补丁：{exc}") from exc
    if diff_proc.returncode != 0:
        stderr = _decode_git_output(diff_proc.stderr).strip()
        raise SupervisedWorktreeRunValidationError(f"无法读取候选补丁：{stderr or 'git diff failed'}")

    digest = hashlib.sha256()
    digest.update(b"tracked-diff\0")
    digest.update(_git_output_bytes(diff_proc.stdout))
    baseline_noise = _baseline_untracked_paths(baseline_untracked)
    for relative_path in _candidate_untracked_files(candidate_path, baseline_noise=baseline_noise):
        digest.update(b"\0untracked-path\0")
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0untracked-content\0")
        try:
            digest.update((candidate_path / relative_path).read_bytes())
        except OSError as exc:
            raise SupervisedWorktreeRunValidationError(
                f"无法读取候选未跟踪文件 {relative_path}：{exc}"
            ) from exc

    patch_sha256 = digest.hexdigest()
    binding_payload = json.dumps(
        {"checkpointCommit": normalized_checkpoint, "patchSha256": patch_sha256},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    changed_paths = sorted(
        {
            str(item.get("path") or "").replace("\\", "/").strip()
            for item in changed_files
            if str(item.get("path") or "").strip()
        }
    )
    return {
        "schemaVersion": 1,
        "bindingStatus": "verified",
        "variantId": f"swte-variant-{hashlib.sha256(binding_payload).hexdigest()}",
        "checkpointCommit": normalized_checkpoint,
        "patchSha256": patch_sha256,
        "changedFileCount": len(changed_paths),
        "changedPaths": changed_paths,
        "source": "worktree_patch",
    }


def _candidate_untracked_files(candidate_path: Path, *, baseline_noise: set[str]) -> list[str]:
    try:
        proc = git_process.run_git(
            ["ls-files", "--others", "--exclude-standard", "-z"],
            cwd=str(candidate_path),
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise SupervisedWorktreeRunValidationError(f"无法枚举候选未跟踪文件：{exc}") from exc
    if proc.returncode != 0:
        raise SupervisedWorktreeRunValidationError(
            f"无法枚举候选未跟踪文件：{_decode_git_output(proc.stderr).strip() or 'git ls-files failed'}"
        )
    return sorted(
        path
        for path in {
            raw.replace("\\", "/").lstrip("/")
            for raw in _decode_git_nul_records(proc.stdout)
        }
        if path and not _is_baseline_untracked_noise({"path": path, "status": "??"}, baseline_noise)
    )


def _git_output_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value or "").encode("utf-8", errors="surrogatepass")


def _decode_git_output(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _decode_git_nul_records(value: Any) -> list[str]:
    return [
        record.decode("utf-8", errors="surrogateescape")
        for record in _git_output_bytes(value).split(b"\0")
        if record
    ]


def _candidate_variant_is_bound(candidate_variant: dict[str, Any]) -> bool:
    checkpoint_commit = str(candidate_variant.get("checkpointCommit") or "").strip()
    patch_sha256 = str(candidate_variant.get("patchSha256") or "").strip().lower()
    try:
        changed_file_count = int(candidate_variant.get("changedFileCount") or 0)
    except (TypeError, ValueError):
        return False
    if (
        candidate_variant.get("bindingStatus") != "verified"
        or not checkpoint_commit
        or len(patch_sha256) != 64
        or any(character not in "0123456789abcdef" for character in patch_sha256)
        or changed_file_count <= 0
    ):
        return False
    binding_payload = json.dumps(
        {"checkpointCommit": checkpoint_commit, "patchSha256": patch_sha256},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected_variant_id = f"swte-variant-{hashlib.sha256(binding_payload).hexdigest()}"
    return str(candidate_variant.get("variantId") or "").strip() == expected_variant_id


def _build_trusted_rerun_workspace_audit(
    candidate_path: Path,
    *,
    frozen_variant: dict[str, Any],
    baseline_untracked: Any = None,
) -> dict[str, Any]:
    """Verify that the rerun left the frozen candidate worktree unchanged."""

    frozen_variant_id = str(frozen_variant.get("variantId") or "").strip()
    frozen_patch_sha = str(frozen_variant.get("patchSha256") or "").strip().lower()
    frozen_paths = sorted(
        {
            str(item or "").replace("\\", "/").strip().lstrip("/")
            for item in list(frozen_variant.get("changedPaths") or [])
            if str(item or "").strip()
        }
    )
    base = {
        "basis": "frozen_candidate_variant",
        "frozenVariantId": frozen_variant_id,
        "frozenPatchSha256": frozen_patch_sha,
    }
    if not _candidate_variant_is_bound(frozen_variant):
        return {
            **base,
            "status": "unavailable",
            "reason": "冻结候选版本未完成可信绑定，无法校验复跑后的工作树。",
            "variantUnchanged": False,
            "unexpectedChangedFiles": [],
        }

    try:
        observed_changed_files = _candidate_changed_files(
            candidate_path,
            baseline_untracked=baseline_untracked,
        )
        observed_variant = _build_candidate_variant(
            candidate_path,
            checkpoint_commit=str(frozen_variant.get("checkpointCommit") or ""),
            changed_files=observed_changed_files,
            baseline_untracked=baseline_untracked,
        )
    except (OSError, SupervisedWorktreeRunValidationError) as exc:
        return {
            **base,
            "status": "unavailable",
            "reason": f"复跑后候选工作树审计不可用：{_bounded_text(str(exc), limit=400)}",
            "variantUnchanged": False,
            "unexpectedChangedFiles": [],
        }

    observed_variant_id = str(observed_variant.get("variantId") or "").strip()
    observed_patch_sha = str(observed_variant.get("patchSha256") or "").strip().lower()
    observed_paths = sorted(
        {
            str(item or "").replace("\\", "/").strip().lstrip("/")
            for item in list(observed_variant.get("changedPaths") or [])
            if str(item or "").strip()
        }
    )
    patch_unchanged = observed_patch_sha == frozen_patch_sha
    path_set_unchanged = observed_paths == frozen_paths
    variant_unchanged = (
        observed_variant_id == frozen_variant_id
        and patch_unchanged
        and path_set_unchanged
    )
    if variant_unchanged:
        unexpected_changed_files: list[str] = []
    elif path_set_unchanged:
        unexpected_changed_files = observed_paths
    else:
        unexpected_changed_files = sorted(set(frozen_paths).symmetric_difference(observed_paths))
    return {
        **base,
        "status": "verified",
        "reason": (
            "复跑后的候选工作树与冻结候选版本一致。"
            if variant_unchanged
            else "复跑后的候选工作树偏离冻结候选版本。"
        ),
        "observedVariantId": observed_variant_id,
        "observedPatchSha256": observed_patch_sha,
        "variantUnchanged": variant_unchanged,
        "patchUnchanged": patch_unchanged,
        "pathSetUnchanged": path_set_unchanged,
        "frozenChangedFiles": frozen_paths,
        "observedChangedFiles": observed_paths,
        "unexpectedChangedFiles": unexpected_changed_files,
    }


def _baseline_untracked_paths(raw: Any) -> set[str]:
    if not isinstance(raw, list):
        return set()
    paths: set[str] = set()
    for item in raw:
        normalized = str(item or "").replace("\\", "/").strip().lstrip("/")
        if normalized:
            paths.add(normalized)
            if normalized.endswith("/"):
                paths.add(normalized.rstrip("/"))
    return paths


def _is_baseline_untracked_noise(item: dict[str, str], baseline_untracked: set[str]) -> bool:
    if not baseline_untracked:
        return False
    status = str(item.get("status") or "")
    if "??" not in status:
        return False
    path = str(item.get("path") or "").replace("\\", "/").strip().lstrip("/")
    if not path:
        return False
    if path in baseline_untracked:
        return True
    if path.endswith("/"):
        return any(existing.startswith(path) for existing in baseline_untracked)
    return False


def _git_status_files(repo_root: Path) -> list[dict[str, str]]:
    try:
        proc = git_process.run_git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    items: list[dict[str, str]] = []
    records = _decode_git_nul_records(proc.stdout)
    index = 0
    while index < len(records):
        raw = records[index]
        index += 1
        if len(raw) < 4:
            continue
        status = raw[:2]
        path = raw[3:]
        normalized = path.replace("\\", "/")
        items.append({"path": normalized, "status": status.strip() or "??"})
        if "R" in status or "C" in status:
            index += 1
    return items


def _call_cancel_checker(cancel_checker: Callable[[], Any] | None) -> str:
    if not callable(cancel_checker):
        return ""
    try:
        value = cancel_checker()
    except Exception:
        return ""
    if isinstance(value, bool):
        return "监督工作树进化运行已取消。" if value else ""
    return str(value or "").strip()


def _change_type(status: str) -> str:
    raw = str(status or "")
    if "D" in raw:
        return "deleted"
    if "??" in raw or "A" in raw:
        return "added"
    if "R" in raw:
        return "renamed"
    return "modified"


def _is_high_risk_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lstrip("/")
    if normalized in _HIGH_RISK_PATHS:
        return True
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in _HIGH_RISK_PATH_PREFIXES)


def _safe_project_path(root: Path, relative: str) -> Path:
    rel = str(relative or "").replace("\\", "/").lstrip("/")
    if not rel or rel.startswith("../") or "/../" in f"/{rel}/":
        raise SupervisedWorktreeRunActionError(f"非法相对路径：{relative}")
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise SupervisedWorktreeRunActionError(f"路径越界：{relative}") from exc
    return target


def _snapshot_project_root(snapshot: dict[str, Any]) -> Path:
    raw = str(snapshot.get("projectRoot") or "").strip()
    return Path(raw).resolve() if raw else PROJECT_ROOT.resolve()


def _run_store_root(project_root: Path) -> Path:
    return developer_sandbox.route_workspace_path(
        project_root,
        "supervised_evolution",
        "supervised_evolution",
        "worktree_runs",
        intent="state",
        seed=True,
    )


def _storage_project_root_arg(project_root: Path | None) -> Path | None:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT.resolve()
    return None if root == SOURCE_PROJECT_ROOT.resolve() else root


def _transition(snapshot: dict[str, Any], status: str, phase: str, message: str) -> None:
    snapshot["status"] = status
    snapshot["phase"] = phase
    snapshot["runtimeStatus"] = status
    snapshot["latestMessage"] = message
    snapshot["updatedAt"] = _now_iso()
    _append_stage(snapshot, phase, status, message)
    active_run_id = str(snapshot.get("runId") or "") if status in _ACTIVE_STATUSES else ""
    _persist_snapshot(snapshot, active_run_id=active_run_id)
    _record_worktree_scene_event(
        phase,
        f"supervised_worktree_run.{phase}",
        run_id=str(snapshot.get("runId") or ""),
        outcome="observed",
        fields=_snapshot_event_fields(snapshot),
        child_log_payload={"snapshot": _compact_snapshot_for_child_log(snapshot)},
        lifecycle=True,
    )


def _append_stage(snapshot: dict[str, Any], phase: str, status: str, message: str) -> None:
    stages = snapshot.setdefault("stages", [])
    if isinstance(stages, list):
        stages.append(
            {
                "phase": phase,
                "status": status,
                "message": message,
                "timestamp": _now_iso(),
            }
        )


def _append_event(snapshot: dict[str, Any], event_type: str, message: str) -> None:
    events = snapshot.setdefault("events", [])
    item = {
        "type": event_type,
        "message": message,
        "timestamp": _now_iso(),
    }
    if isinstance(events, list):
        events.append(item)
    snapshot["latestMessage"] = message
    snapshot["updatedAt"] = item["timestamp"]
    _persist_snapshot(snapshot, active_run_id=str(snapshot.get("runId") or "") if snapshot.get("status") in _ACTIVE_STATUSES else "")
    _publish_snapshot(snapshot)


def _persist_snapshot(snapshot: dict[str, Any], *, active_run_id: str = "") -> dict[str, Any]:
    payload = _clone(snapshot)
    run_id = str(payload.get("runId") or "").strip()
    if run_id and str(payload.get("status") or "").strip().lower() in _ACTIVE_STATUSES:
        existing = _work_run_store().load_snapshot(RUN_KIND, run_id)
        if isinstance(existing, dict) and str(existing.get("status") or "").strip().lower() in _TERMINAL_STATUSES:
            _publish_snapshot(existing)
            return existing
    persisted = _work_run_store().persist_snapshot(RUN_KIND, payload, active_run_id=active_run_id)
    _publish_snapshot(persisted)
    return persisted


def _work_run_store() -> WorkRunStore:
    return WorkRunStore(root=work_run_store.WORK_RUNS_DIR)


def _raise_if_lease_conflict(*, lang: str) -> None:
    active_runs = list_active_session_work_runs()
    active_runs.extend(_active_evolution_run_snapshots())
    decision = check_lease_conflicts(
        WorkRunLeaseRequest(run_kind=RUN_KIND, leases=RUN_LEASES),
        active_runs,
    )
    if decision.allowed:
        return
    raise SupervisedWorktreeRunBusyError(
        text_for(
            lang,
            zh=f"当前有其它运行持有冲突资源，请等它结束后再启动。{decision.reason}",
            en=f"Another active run holds a conflicting resource lease. {decision.reason}",
        )
    )


def _active_evolution_run_snapshots() -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    try:
        from core.runtime_manager.evolution_store import load_active_run_snapshot

        for kind in ("self", "supervised"):
            payload = load_active_run_snapshot(kind)
            if isinstance(payload, dict):
                snapshots.append(payload)
    except Exception:
        pass
    return snapshots


def _record_worktree_started_event(snapshot: dict[str, Any]) -> None:
    start_request = snapshot.get("startRequest") if isinstance(snapshot.get("startRequest"), dict) else {}
    fields = {
        **_snapshot_event_fields(snapshot),
        "sourceKind": str(snapshot.get("sourceKind") or ""),
        "datasetName": str(snapshot.get("datasetName") or ""),
        "datasetLimit": snapshot.get("datasetLimit"),
        "requestSource": str(start_request.get("requestSource") or ""),
        "uiRoute": str(start_request.get("uiRoute") or ""),
        "initiator": str(start_request.get("initiator") or ""),
        "clientAction": str(start_request.get("clientAction") or ""),
    }
    _record_worktree_scene_event(
        "started",
        "supervised_worktree_run.started",
        run_id=str(snapshot.get("runId") or ""),
        message="Supervised worktree run started.",
        outcome="queued",
        fields=fields,
        child_log_payload={"startRequest": _compact_start_request_for_child_log(snapshot)},
        lifecycle=True,
    )


def _record_worktree_scene_event(
    phase: str,
    event_code: str,
    *,
    run_id: str = "",
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
    child_log_payload: dict[str, Any] | None = None,
    lifecycle: bool = False,
) -> None:
    try:
        record_runtime_scene_event(
            "supervised_worktree_run",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields={"runId": run_id, **(fields or {})},
            child_log_path=_child_log_path(run_id) if child_log_payload is not None else "",
            child_log_payload=child_log_payload,
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _child_log_path(run_id: str) -> str:
    normalized = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in str(run_id or ""))
    return f"runs/supervised_worktree/{normalized or 'run'}/timeline.jsonl"


def _snapshot_event_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    review_gate = snapshot.get("reviewGate") if isinstance(snapshot.get("reviewGate"), dict) else {}
    self_origin = snapshot.get("selfEvolutionOrigin") if isinstance(snapshot.get("selfEvolutionOrigin"), dict) else {}
    return {
        "status": str(snapshot.get("status") or ""),
        "phase": str(snapshot.get("phase") or ""),
        "outcome": str(snapshot.get("outcome") or ""),
        "mode": str(snapshot.get("mode") or ""),
        "executionMode": str(snapshot.get("executionMode") or ""),
        "bundleName": str(snapshot.get("bundleName") or ""),
        "sourceKind": str(snapshot.get("sourceKind") or ""),
        "baselineScore": decision.get("baselineScore"),
        "candidateScore": decision.get("candidateScore"),
        "scoreDelta": decision.get("scoreDelta"),
        "reviewGateRequired": bool(review_gate.get("required")),
        "reviewGateStatus": str(review_gate.get("status") or ""),
        "sourceTrack": str(self_origin.get("sourceTrack") or ""),
    }


def _compact_start_request_for_child_log(snapshot: dict[str, Any]) -> dict[str, Any]:
    start_request = snapshot.get("startRequest") if isinstance(snapshot.get("startRequest"), dict) else {}
    return {
        "runId": snapshot.get("runId"),
        "runKind": snapshot.get("runKind"),
        "status": snapshot.get("status"),
        "phase": snapshot.get("phase"),
        "mode": snapshot.get("mode"),
        "executionMode": snapshot.get("executionMode"),
        "sourceKind": snapshot.get("sourceKind"),
        "datasetName": snapshot.get("datasetName"),
        "datasetLimit": snapshot.get("datasetLimit"),
        "bundleName": snapshot.get("bundleName"),
        "keepWorktree": snapshot.get("keepWorktree"),
        "costEstimate": snapshot.get("costEstimate"),
        "requestSource": start_request.get("requestSource"),
        "uiRoute": start_request.get("uiRoute"),
        "initiator": start_request.get("initiator"),
        "clientAction": start_request.get("clientAction"),
        "selfEvolutionOrigin": snapshot.get("selfEvolutionOrigin"),
        "reviewGate": snapshot.get("reviewGate"),
    }


def _compact_snapshot_for_child_log(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": snapshot.get("runId"),
        "status": snapshot.get("status"),
        "phase": snapshot.get("phase"),
        "outcome": snapshot.get("outcome"),
        "startRequest": snapshot.get("startRequest"),
        "latestMessage": snapshot.get("latestMessage"),
        "decision": snapshot.get("decision"),
        "mergeAnalysis": snapshot.get("mergeAnalysis"),
        "reviewGate": snapshot.get("reviewGate"),
    }


def _register_subscriber(run_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _RUN_SUBSCRIBERS_LOCK:
        _RUN_SUBSCRIBERS.setdefault(run_id, set()).add(subscriber)


def _unregister_subscriber(run_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _RUN_SUBSCRIBERS_LOCK:
        subscribers = _RUN_SUBSCRIBERS.get(run_id)
        if not subscribers:
            return
        subscribers.discard(subscriber)
        if not subscribers:
            _RUN_SUBSCRIBERS.pop(run_id, None)


def _publish_snapshot(snapshot: dict[str, Any]) -> None:
    run_id = str(snapshot.get("runId") or "")
    if not run_id:
        return
    event = {
        "type": "supervised_worktree_run",
        "runId": run_id,
        "snapshot": _decorate_snapshot(snapshot),
        "terminal": _is_terminal(snapshot),
    }
    with _RUN_SUBSCRIBERS_LOCK:
        subscribers = list(_RUN_SUBSCRIBERS.get(run_id) or [])
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            continue


def _decorate_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    payload = _clone(snapshot)
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    if decision or str(payload.get("status") or "").strip().lower() == "done":
        payload["decision"] = {
            **decision,
            "approvalMode": str(payload.get("approvalMode") or decision.get("approvalMode") or "human"),
            "evaluationState": _evaluation_state(payload),
            "recommendedAction": "approval_decision",
        }
    if not isinstance(payload.get("approvalDecision"), dict):
        payload["approvalDecision"] = {
            "schemaVersion": 1,
            "mode": str(payload.get("approvalMode") or "human"),
            "status": "pending",
            "decision": "",
        }
    worktree = payload.get("candidateWorktree")
    if isinstance(worktree, dict) and str(worktree.get("path") or "").strip():
        project_root = _snapshot_project_root(payload)
        run_id = str(payload.get("runId") or "")
        _, reason = _coerce_candidate_worktree_path_soft(
            worktree,
            project_root=project_root,
            run_id=run_id,
        )
        if reason:
            worktree.pop("path", None)
            worktree["pathValidationError"] = reason
    payload["actionStates"] = _action_states(payload)
    payload["workflowSteps"] = _build_workflow_steps(payload)
    return payload


def _action_states(snapshot: dict[str, Any]) -> dict[str, Any]:
    status = str(snapshot.get("status") or "").strip().lower()
    outcome = str(snapshot.get("outcome") or "").strip().lower()
    worktree = snapshot.get("candidateWorktree") if isinstance(snapshot.get("candidateWorktree"), dict) else {}
    has_worktree = bool(str(worktree.get("path") or "").strip()) and bool(worktree.get("preserved", True))
    merge = snapshot.get("merge") if isinstance(snapshot.get("merge"), dict) else {}
    rollback = snapshot.get("rollback") if isinstance(snapshot.get("rollback"), dict) else {}
    done = status in _TERMINAL_STATUSES
    active = status in _ACTIVE_STATUSES
    review_pending = _review_gate_requires_approval(snapshot)
    review_gate = snapshot.get("reviewGate") if isinstance(snapshot.get("reviewGate"), dict) else {}
    approval_mode = str(snapshot.get("approvalMode") or "human").strip().lower()
    approval = snapshot.get("approvalDecision") if isinstance(snapshot.get("approvalDecision"), dict) else {}
    approval_pending = str(approval.get("status") or "pending").strip().lower() != "decided"
    evaluation_state = _evaluation_state(snapshot)
    candidate_judgment = snapshot.get("candidateJudgment") if isinstance(snapshot.get("candidateJudgment"), dict) else {}
    judge_scoring_complete = judge_merge_allowed(candidate_judgment)
    return {
        "terminate": {
            "enabled": active,
            "reason": "" if active else "这一轮没有正在运行的监督工作树进化任务。",
        },
        "preserve": {"enabled": done and has_worktree and outcome not in {"preserved", "merged"}},
        "discard": {"enabled": done and has_worktree and outcome not in {"discarded", "discard_skipped", "merged"}},
        "analyzeMerge": {"enabled": done and has_worktree},
        "approveReview": {
            "enabled": (
                done
                and has_worktree
                and bool(review_gate.get("required"))
                and review_pending
                and judge_scoring_complete
                and approval_mode == "human"
                and approval_pending
            ),
            "reason": (
                ""
                if judge_scoring_complete
                else (
                    f"当前评估状态为 {evaluation_state}，不能批准；"
                    "可拒绝或要求补充证据后复跑。"
                )
            ),
        },
        "runAgentApproval": {
            "enabled": (
                done
                and has_worktree
                and review_pending
                and judge_scoring_complete
                and approval_mode == "agent"
                and approval_pending
            ),
            "reason": (
                ""
                if judge_scoring_complete
                else f"当前评估状态为 {evaluation_state}，不能启动 Agent 批准流程。"
            ),
        },
        "rejectReview": {
            "enabled": (
                done
                and has_worktree
                and approval_mode == "human"
                and approval_pending
            ),
        },
        "requestRerun": {
            "enabled": (
                done
                and has_worktree
                and approval_mode == "human"
                and approval_pending
            ),
        },
        "merge": {
            "enabled": done
            and has_worktree
            and str(merge.get("status") or "") != "merged"
            and str(approval.get("status") or "").strip().lower() == "decided"
            and str(approval.get("decision") or "").strip().upper() == "APPROVE"
            and evaluation_state == "VALID"
            and not review_pending
        },
        "rollback": {"enabled": str(rollback.get("status") or "") == "available"},
    }


def _encode_sse(event_name: str, payload: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _snapshot_signature(snapshot: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(snapshot.get("status") or ""),
        str(snapshot.get("phase") or ""),
        str(snapshot.get("outcome") or ""),
        str(snapshot.get("updatedAt") or ""),
    )


def _is_terminal(snapshot: dict[str, Any]) -> bool:
    return str(snapshot.get("status") or "").strip().lower() in _TERMINAL_STATUSES


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clone(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "RUN_KIND",
    "SupervisedWorktreeRunActionError",
    "SupervisedWorktreeRunBusyError",
    "SupervisedWorktreeRunNotFoundError",
    "SupervisedWorktreeRunValidationError",
    "WorktreeRunDependencies",
    "execute_supervised_worktree_action",
    "force_cancel_active_supervised_worktree_runs_for_shutdown",
    "get_active_supervised_worktree_run",
    "get_supervised_worktree_run",
    "list_supervised_worktree_runs",
    "run_supervised_worktree_flow",
    "start_supervised_worktree_run",
    "stream_supervised_worktree_run_events",
]
