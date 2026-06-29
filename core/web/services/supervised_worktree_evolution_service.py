"""Supervised worktree self-evolution loop for the web workbench."""

from __future__ import annotations

import base64
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
from .supervised_conversation_harness_adapter import run_supervised_conversation_harness


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
            "keepWorktree": bool(options["keepWorktree"]),
            "startRequest": options["startRequest"],
            "selfEvolutionOrigin": options["selfEvolutionOrigin"],
            "reviewGate": options["reviewGate"],
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
            "reflection": {},
            "candidateWorktree": {},
            "candidateModification": {},
            "candidate": {},
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
        "keepWorktree": bool(options["keepWorktree"]),
        "startRequest": options["startRequest"],
        "selfEvolutionOrigin": options["selfEvolutionOrigin"],
        "reviewGate": options["reviewGate"],
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
        "reflection": {},
        "candidateWorktree": {},
        "candidateModification": {},
        "candidate": {},
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
    return _decorate_snapshot(snapshot) if snapshot else None


def get_active_supervised_worktree_run() -> dict[str, Any] | None:
    snapshot = _work_run_store().load_active_snapshot(RUN_KIND)
    if not snapshot:
        return None
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
        updated = _approve_review_gate(snapshot, reviewer_note=reviewer_note)
        _append_event(updated, "review_approved", "监督 review 已批准，候选允许进入合并分析。")
        return _decorate_snapshot(updated)
    if normalized_action == "merge":
        updated = _merge_candidate(snapshot, force=force)
        _append_event(updated, "merge", "候选改动已合并到主工作区。")
        return _decorate_snapshot(updated)
    if normalized_action in {"rollback_merge", "rollback"}:
        updated = _rollback_merge(snapshot)
        _append_event(updated, "rollback", "已按回滚清单恢复合并前状态。")
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
        modifier = dependencies.candidate_modifier or _candidate_modifier_for_mode(options["executionMode"])
        worktree_factory = dependencies.worktree_factory or _default_worktree_factory

        _raise_if_run_cancelled(snapshot)
        baseline = evaluator(
            root,
            str(options["bundleName"]),
            "baseline",
            {"runId": run_id, "options": options, "cancelChecker": cancel_checker},
        )
        _raise_if_run_cancelled(snapshot)
        snapshot["baseline"] = baseline
        if _baseline_has_retryable_provider_failure(baseline):
            _finish_baseline_unavailable(snapshot, baseline)
            return _decorate_snapshot(snapshot)
        _raise_if_run_cancelled(snapshot)
        _transition(snapshot, "running", "reflection", "基线题集完成，正在生成反思与自改目标。")

        reflection = _build_reflection(snapshot, baseline)
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
        _transition(snapshot, "running", "candidate_modify", "候选 agent 正在反思并修改自身。")
        _raise_if_run_cancelled(snapshot)
        modification = modifier(
            candidate_path,
            str(reflection.get("selfModificationPrompt") or ""),
            {"runId": run_id, "options": options, "cancelChecker": cancel_checker},
        )
        _raise_if_run_cancelled(snapshot)
        snapshot["candidateModification"] = modification
        snapshot["candidateWorktree"]["changedFiles"] = _candidate_changed_files(
            candidate_path,
            baseline_untracked=candidate_worktree.get("untrackedFiles"),
        )
        _persist_snapshot(snapshot, active_run_id=run_id if _ACTIVE_RUN_ID == run_id else "")

        _raise_if_run_cancelled(snapshot)
        _transition(snapshot, "running", "candidate_evaluation", "正在用同一题集复测候选 agent。")
        _raise_if_run_cancelled(snapshot)
        candidate = evaluator(
            candidate_path,
            str(options["bundleName"]),
            "candidate",
            {"runId": run_id, "options": options, "cancelChecker": cancel_checker},
        )
        _raise_if_run_cancelled(snapshot)
        snapshot["candidate"] = candidate

        _raise_if_run_cancelled(snapshot)
        _transition(snapshot, "running", "decision", "正在比较基线与候选结果。")
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
    root = (project_root or PROJECT_ROOT).resolve()
    storage_project_root = _storage_project_root_arg(project_root)
    source_kind = str(payload.get("sourceKind") or "bundle").strip().lower()
    mode = str(payload.get("mode") or "auto").strip().lower()
    execution_mode = str(payload.get("executionMode") or "simulation").strip().lower()
    keep_worktree = bool(payload.get("keepWorktree"))
    dataset_name = str(payload.get("datasetName") or "").strip()
    bundle_name = str(payload.get("bundleName") or "").strip()
    dataset_limit = _coerce_optional_int(payload.get("datasetLimit"))
    self_origin = _normalize_self_evolution_origin(payload)
    review_gate = _normalize_review_gate(payload, self_origin)
    mental_model_mode = normalize_supervised_mental_model_mode(payload.get("mentalModelMode") or "follow")
    mental_model_enabled = supervised_mental_model_enabled_for_mode(mental_model_mode)

    if mode not in {"auto", "manual"}:
        raise SupervisedWorktreeRunValidationError("mode must be auto or manual.")
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
    return {
        "sourceKind": source_kind,
        "mode": mode,
        "executionMode": execution_mode,
        "datasetName": dataset_name,
        "datasetLimit": dataset_limit,
        "bundleName": bundle_name,
        "keepWorktree": keep_worktree,
        "costEstimate": estimate,
        "startRequest": _normalize_start_request_metadata(payload),
        "selfEvolutionOrigin": self_origin,
        "reviewGate": review_gate,
        "agentBindings": agent_bindings,
        "mentalModelMode": mental_model_mode,
        "mentalModelEnabled": mental_model_enabled,
    }


def _normalize_worktree_agent_bindings(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    bindings: dict[str, dict[str, Any]] = {}
    for role in ("baseline", "candidate", "judge"):
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


def _normalize_review_gate(payload: dict[str, Any], self_origin: dict[str, Any]) -> dict[str, Any]:
    required = bool(payload.get("requiresSupervisedReview")) or bool(self_origin)
    if not required:
        return {
            "required": False,
            "status": "not_required",
            "reason": "",
            "approvedAt": "",
            "reviewerNote": "",
        }
    reason = str(payload.get("reviewReason") or "").strip()
    if not reason:
        reason = "Self-evolution risky write output must be reviewed before merge."
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
    self_edit_calls = 1
    model_calls = evaluation_calls + self_edit_calls
    estimated_input = evaluation_calls * 3500 + 6000
    estimated_output = evaluation_calls * 1200 + 3500
    return {
        "caseCount": safe_cases,
        "evaluationCalls": evaluation_calls,
        "selfEditCalls": self_edit_calls,
        "modelCalls": model_calls,
        "estimatedInputTokens": estimated_input,
        "estimatedOutputTokens": estimated_output,
        "estimatedTotalTokens": estimated_input + estimated_output,
        "note": "粗略估算，仅用于启动前确认；真实消耗取决于模型重试、工具输出和题目长度。",
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


def _candidate_modifier_for_mode(execution_mode: str) -> Callable[[Path, str, dict[str, Any]], dict[str, Any]]:
    if execution_mode == "simulation":
        return _simulation_candidate_modifier
    return _real_candidate_modifier


def _simulation_evaluation_runner(project_root: Path, bundle_name: str, role: str, context: dict[str, Any]) -> dict[str, Any]:
    bundle = load_supervised_bundle(bundle_name, project_root=_storage_project_root_arg(project_root))
    cases = list(bundle.get("cases") or [])
    successes = len(cases) if role == "candidate" else max(0, len(cases) - 1)
    total = len(cases)
    score = round((successes / total) * 100, 3) if total else 0.0
    return {
        "role": role,
        "status": "success",
        "score": score,
        "successes": successes,
        "total": total,
        "failures": max(0, total - successes),
        "bundleName": bundle_name,
        "summary": f"{role} simulation score {score}",
        "cases": [
            {
                "caseId": str(case.get("case_id") or f"case-{index}"),
                "status": "success" if index <= successes else "failed",
                "reason": "simulation",
            }
            for index, case in enumerate(cases, start=1)
        ],
    }


def _real_evaluation_runner(project_root: Path, bundle_name: str, role: str, context: dict[str, Any]) -> dict[str, Any]:
    bundle = load_supervised_bundle(bundle_name, project_root=_storage_project_root_arg(project_root))
    cases = list(bundle.get("cases") or [])
    run_id = str(context.get("runId") or "")
    options = context.get("options") if isinstance(context.get("options"), dict) else {}
    agent_bindings = options.get("agentBindings") if isinstance(options.get("agentBindings"), dict) else {}
    agent_binding = dict(agent_bindings.get(role) or {})
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
        prompt = (
            str(case.get("candidate_prompt") or case.get("baseline_prompt") or case.get("prompt") or "").strip()
            if role == "candidate"
            else str(case.get("baseline_prompt") or case.get("prompt") or "").strip()
        )
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
            workspace_override=project_root if role == "candidate" else None,
            cancel_checker=cancel_checker,
        )
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
        _record_worktree_scene_event(
            "evaluation",
            "supervised_worktree_run.case_finished",
            run_id=run_id,
            fields={"role": role, "caseId": case_id, "status": result.status},
        )
    successes = sum(1 for item in results if item.get("status") == "success")
    total = len(results)
    score = round((successes / total) * 100, 3) if total else 0.0
    return {
        "role": role,
        "status": "success" if successes == total else "failed",
        "score": score,
        "successes": successes,
        "total": total,
        "failures": max(0, total - successes),
        "bundleName": bundle_name,
        "summary": f"{role} score {score}",
        "cases": results,
    }


def _harness_result_payload(result: HarnessResult, *, case_id: str, role: str) -> dict[str, Any]:
    return {
        "caseId": case_id,
        "role": role,
        "status": result.status,
        "reason": result.reason,
        "worktreePath": result.worktree_path,
        "checkpointCommit": result.checkpoint_commit,
        "llmFailure": (result.evolution_summary or {}).get("llm_failure") or {},
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


def _real_candidate_modifier(worktree_path: Path, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
    started = _now_iso()
    timeout_seconds = 900
    cancel_checker = context.get("cancelChecker") if callable(context.get("cancelChecker")) else None
    options = context.get("options") if isinstance(context.get("options"), dict) else {}
    agent_bindings = options.get("agentBindings") if isinstance(options.get("agentBindings"), dict) else {}
    agent_binding = dict(agent_bindings.get("candidate") or {})
    if not agent_binding.get("agentId"):
        return {
            "status": "failed",
            "startedAt": started,
            "endedAt": _now_iso(),
            "summary": "candidate self-edit missing supervised candidate Agent binding",
        }
    result = run_supervised_conversation_harness(
        repo_root=worktree_path,
        mode="single_turn",
        prompt=prompt,
        scenario="candidate_self_improvement",
        timeout_seconds=timeout_seconds,
        expect_restart=False,
        post_restart_observe_seconds=0,
        keep_worktree=True,
        agent_binding=agent_binding,
        mental_model_mode=str(options.get("mentalModelMode") or "follow"),
        mental_model_enabled=options.get("mentalModelEnabled"),
        workspace_override=worktree_path,
        cancel_checker=cancel_checker,
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
        "workspaceOverride": str(worktree_path),
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


def _build_reflection(snapshot: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    successes = int(baseline.get("successes") or 0)
    total = int(baseline.get("total") or 0)
    failures = max(0, total - successes)
    self_origin = snapshot.get("selfEvolutionOrigin") if isinstance(snapshot.get("selfEvolutionOrigin"), dict) else {}
    requested_goal = str(self_origin.get("goal") or "").strip()
    goal_section = ""
    if requested_goal:
        goal_section = (
            "\n\n本轮来自 self-evolution risky write worktree 请求。\n"
            f"用户请求目标：{requested_goal}\n"
            "你可以在隔离 worktree 中实现候选改动，但候选必须等待监督 review 后才能合并。"
        )
    prompt = (
        "你正在隔离 worktree 中执行监督自改闭环。\n"
        "先用中文简短反思基线运行，再直接修改本项目中你认为最能提升同一题集表现的内容。\n"
        "硬约束：只在当前 worktree 内修改；不要改主工作区、不要读取真实密钥、不要改机器全局配置；"
        "修改后运行你认为必要的最小验证。不要提交 git，不要合并。\n\n"
        f"基线结果：{successes}/{total} 通过，失败数 {failures}。\n"
        f"基线摘要：{baseline.get('summary') or '-'}\n"
        "目标：让候选 agent 在同一题集复测时比基线分数更高。"
        f"{goal_section}"
    )
    return {
        "summary": f"基线 {successes}/{total} 通过，候选需要针对失败点自改。",
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


def _baseline_failure_reason(baseline: dict[str, Any]) -> str:
    for case in list(baseline.get("cases") or []):
        if not isinstance(case, dict):
            continue
        failure = case.get("llmFailure") if isinstance(case.get("llmFailure"), dict) else {}
        message = str(failure.get("message") or "").strip()
        if message:
            return message
    return str(baseline.get("summary") or "baseline provider transport failure")


def _build_decision(snapshot: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    baseline = snapshot.get("baseline") if isinstance(snapshot.get("baseline"), dict) else {}
    candidate = snapshot.get("candidate") if isinstance(snapshot.get("candidate"), dict) else {}
    modification = snapshot.get("candidateModification") if isinstance(snapshot.get("candidateModification"), dict) else {}
    worktree = snapshot.get("candidateWorktree") if isinstance(snapshot.get("candidateWorktree"), dict) else {}
    baseline_score = float(baseline.get("score") or 0.0)
    candidate_score = float(candidate.get("score") or 0.0)
    delta = round(candidate_score - baseline_score, 3)
    changed_files = list(worktree.get("changedFiles") or [])
    high_risk_files = [item for item in changed_files if bool(item.get("highRisk"))]
    gates = [
        {
            "name": "score_improved",
            "status": "pass" if delta > 0 else "fail",
            "reason": f"候选分数 {candidate_score}，基线分数 {baseline_score}，delta={delta}",
        },
        {
            "name": "candidate_modified",
            "status": "pass" if changed_files else "fail",
            "reason": f"候选工作树改动文件数：{len(changed_files)}",
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
    pass_all = all(gate["status"] == "pass" for gate in gates)
    mode = str(options.get("mode") or "auto")
    if mode == "manual":
        action = "needs_manual_decision"
        reason = "手工操作模式下，候选保留给用户决定。"
    elif pass_all:
        action = "preserve"
        reason = "候选分数提升且通过自动保留闸门。"
    else:
        action = "discard"
        reason = "候选未满足自动保留闸门。"
    return {
        "mode": mode,
        "baselineScore": baseline_score,
        "candidateScore": candidate_score,
        "scoreDelta": delta,
        "recommendedAction": action,
        "reason": reason,
        "gates": gates,
        "highRisk": bool(high_risk_files),
    }


def _finish_by_decision(snapshot: dict[str, Any], decision: dict[str, Any], options: dict[str, Any]) -> None:
    recommended = str(decision.get("recommendedAction") or "")
    if recommended == "discard":
        cleanup = _cleanup_candidate_worktree(snapshot)
        if cleanup.get("status") == "removed":
            outcome = "discarded"
            message = "候选未优于基线或未过闸门，已丢弃候选工作树。"
        else:
            outcome = "discard_skipped"
            message = "候选未过闸门，但候选工作树路径未通过安全校验，已跳过删除。"
    elif recommended == "preserve":
        outcome = "preserved"
        message = "候选优于基线，已保留候选工作树和合并分析。"
    else:
        outcome = "needs_manual_decision"
        message = "手工模式已完成闭环，候选等待用户保留、丢弃或合并。"
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
    if overlap:
        blockers.append("main_workspace_overlap")
    if high_risk:
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
        "mainDirtyFiles": sorted(dirty_main),
        "reviewGate": snapshot.get("reviewGate") if isinstance(snapshot.get("reviewGate"), dict) else {},
        "analyzedAt": _now_iso(),
    }


def _merge_candidate(snapshot: dict[str, Any], *, force: bool) -> dict[str, Any]:
    updated = _with_merge_analysis(snapshot)
    analysis = updated.get("mergeAnalysis") if isinstance(updated.get("mergeAnalysis"), dict) else {}
    blockers = set(str(item) for item in list(analysis.get("blockers") or []))
    if "supervised_review_pending" in blockers:
        raise SupervisedWorktreeRunActionError(
            "self-evolution 来源的候选仍处于 pending review，必须先完成监督 review approve，不能用 force 绕过。"
        )
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
        raise SupervisedWorktreeRunValidationError("此候选不需要 self-evolution merge review。")
    updated = _clone(snapshot)
    updated["reviewGate"] = {
        **gate,
        "required": True,
        "status": REVIEW_GATE_APPROVED,
        "approvedAt": _now_iso(),
        "reviewerNote": _safe_metadata_text(reviewer_note, limit=500),
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
            ["status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    items: list[dict[str, str]] = []
    for raw in proc.stdout.splitlines():
        if not raw.strip():
            continue
        status = raw[:2]
        path = raw[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        normalized = path.replace("\\", "/")
        items.append({"path": normalized, "status": status.strip() or "??"})
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
    return f"agent/supervised_worktree_runs/{normalized or 'run'}.jsonl"


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
    return payload


def _action_states(snapshot: dict[str, Any]) -> dict[str, Any]:
    status = str(snapshot.get("status") or "").strip().lower()
    outcome = str(snapshot.get("outcome") or "").strip().lower()
    worktree = snapshot.get("candidateWorktree") if isinstance(snapshot.get("candidateWorktree"), dict) else {}
    has_worktree = bool(str(worktree.get("path") or "").strip()) and bool(worktree.get("preserved", True))
    merge = snapshot.get("merge") if isinstance(snapshot.get("merge"), dict) else {}
    rollback = snapshot.get("rollback") if isinstance(snapshot.get("rollback"), dict) else {}
    done = status in _TERMINAL_STATUSES
    review_pending = _review_gate_requires_approval(snapshot)
    review_gate = snapshot.get("reviewGate") if isinstance(snapshot.get("reviewGate"), dict) else {}
    return {
        "preserve": {"enabled": done and has_worktree and outcome not in {"preserved", "merged"}},
        "discard": {"enabled": done and has_worktree and outcome not in {"discarded", "discard_skipped", "merged"}},
        "analyzeMerge": {"enabled": done and has_worktree},
        "approveReview": {
            "enabled": done and has_worktree and bool(review_gate.get("required")) and review_pending,
        },
        "merge": {
            "enabled": done
            and has_worktree
            and str(merge.get("status") or "") != "merged"
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
