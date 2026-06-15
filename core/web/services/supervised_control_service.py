"""Live supervised run control for the web workbench."""

from __future__ import annotations

import json
import os
import queue
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.infrastructure import developer_sandbox
from core.evaluation import (
    SupervisedEvolutionCancelled,
    build_workbench_state,
    default_bundle_name,
    execute_gym_promotion_action,
    list_available_workbench_bundles,
    list_dataset_choices,
    load_gym_promotion_lifecycle,
    prepare_dataset_run,
    resolve_workbench_bundle_path,
    run_workbench_session,
    save_workbench_state,
)
from core.evaluation.supervised_evolution import (
    normalize_supervised_mental_model_mode,
    supervised_mental_model_enabled_for_mode,
)
from core.evaluation.supervised_workbench import bundle_environment_preflight_block_message
from core.runtime_manager.constants import RESULTS_DIR
from core.runtime_manager.command_queue import submit_command, wait_for_result
from core.runtime_manager.evolution_store import (
    delete_run_snapshot as delete_manager_run_snapshot,
    load_active_run_snapshot as load_manager_active_run_snapshot,
    load_latest_run_snapshot as load_manager_latest_run_snapshot,
    load_run_snapshot as load_manager_run_snapshot,
    persist_run_snapshot as persist_manager_run_snapshot,
)
from core.runtime_manager.work_run_leases import (
    EVALUATION_LEASE,
    WorkRunLeaseRequest,
    check_lease_conflicts,
)

from .evolution_service import (
    get_run,
    get_workbench_state_payload,
    manual_governance_block_reason,
    manual_governance_enabled,
)
from .i18n import get_web_language, text_for
from .runtime_manager_control_service import runtime_manager_live_control_enabled
from .runtime_scene_service import record_runtime_scene_event
from .session_service import list_active_session_work_runs
from .supervised_agent_service import supervised_agent_bindings
from .supervised_conversation_harness_adapter import (
    run_supervised_conversation_harness as _run_supervised_conversation_harness,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RUN_STATE_LOCK = threading.Lock()
_RUN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="web-supervised-run")
_RUN_SUBSCRIBERS_LOCK = threading.Lock()
_RUN_SUBSCRIBERS: dict[str, set[queue.Queue[dict[str, Any]]]] = {}
_RUN_STATES: dict[str, dict[str, Any]] = {}
_RUN_CONTROLLERS: dict[str, "_SupervisedRunController"] = {}
_ACTIVE_RUN_ID: str | None = None
_RUN_STREAM_HEARTBEAT_SECONDS = 15.0
_RUN_STREAM_QUEUE_SIZE = 16
_EVENT_TAIL_LIMIT = 12
_ACTIVE_RUN_STATUSES = {"queued", "running", "paused", "stopping"}
_MANAGER_CONTROL_KEY = "runtimeManagerControl"


class SupervisedRunBusyError(RuntimeError):
    """Raised when a supervised run is already active."""


class SupervisedRunValidationError(ValueError):
    """Raised when a start request is invalid."""


class SupervisedRunNotFoundError(ValueError):
    """Raised when a requested supervised run cannot be found."""


class SupervisedRunActionError(RuntimeError):
    """Raised when a supervised proposal action cannot be executed."""


class SupervisedRunStateError(RuntimeError):
    """Raised when a run control request is invalid for the current state."""


class SupervisedRunDeleteError(RuntimeError):
    """Raised when a supervised run snapshot cannot be deleted."""


class _SupervisedRunInterrupted(RuntimeError):
    """Raised when the live run thread should exit without being marked failed."""


def _runtime_manager_live_control_enabled() -> bool:
    return runtime_manager_live_control_enabled(PROJECT_ROOT)


def _ensure_runtime_manager_daemon() -> None:
    from core.runtime_manager.daemon import ensure_daemon_running

    ensure_daemon_running()


def _map_runtime_manager_error(message: str, error_type: str) -> Exception:
    normalized = str(error_type or "").strip()
    if normalized == "SupervisedRunBusyError":
        return SupervisedRunBusyError(message)
    if normalized == "SupervisedRunNotFoundError":
        return SupervisedRunNotFoundError(message)
    if normalized == "SupervisedRunStateError":
        return SupervisedRunStateError(message)
    if normalized == "SupervisedRunActionError":
        return SupervisedRunActionError(message)
    if normalized == "SupervisedRunDeleteError":
        return SupervisedRunDeleteError(message)
    return SupervisedRunValidationError(message)


def _record_supervised_scene_event(
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
    event_fields: dict[str, Any] = {"runId": str(run_id or "").strip()}
    if fields:
        event_fields.update(fields)
    try:
        record_runtime_scene_event(
            "supervised_run",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields=event_fields,
            child_log_path=_supervised_child_log_path(run_id) if child_log_payload is not None else "",
            child_log_payload=child_log_payload,
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _supervised_child_log_path(run_id: str) -> str:
    normalized = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in str(run_id or "").strip()
    ).strip("._-")
    return f"agent/supervised_runs/{normalized or 'run'}.jsonl"


def _supervised_snapshot_event_fields(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    return {
        "status": str(payload.get("status") or "").strip(),
        "currentPhase": str(payload.get("currentPhase") or payload.get("phase") or "").strip(),
        "runtimeStatus": str(payload.get("runtimeStatus") or "").strip(),
        "sourceKind": str(payload.get("sourceKind") or "").strip(),
        "bundleName": str(payload.get("bundleName") or "").strip(),
        "datasetName": str(payload.get("datasetName") or "").strip(),
        "sessionId": str(payload.get("sessionId") or "").strip(),
        "caseIndex": _optional_int(payload.get("currentCaseIndex")),
        "caseTotal": _optional_int(payload.get("caseTotal")),
        "mentalModelMode": str(payload.get("mentalModelMode") or "").strip(),
        "mentalModelEnabled": payload.get("mentalModelEnabled"),
        "decision": str(payload.get("decision") or "").strip(),
        "policyAction": str(payload.get("policyAction") or "").strip(),
        "error": str(payload.get("error") or payload.get("reason") or "").strip(),
        "updatedAt": str(payload.get("updatedAt") or "").strip(),
        "finishedAt": str(payload.get("finishedAt") or "").strip(),
    }


class _SupervisedRunController:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.pause_requested = False
        self.stop_requested = False

    def request_pause(self) -> None:
        with self.condition:
            self.pause_requested = True
            self.condition.notify_all()

    def request_resume(self) -> None:
        with self.condition:
            self.pause_requested = False
            self.condition.notify_all()

    def request_stop(self) -> None:
        with self.condition:
            self.stop_requested = True
            self.condition.notify_all()


def get_supervised_workbench(
    *,
    active_run: dict[str, Any] | None = None,
    active_run_loaded: bool = False,
    include_catalog: bool = True,
    saved_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return workbench defaults, datasets, and current live run when present."""

    datasets = [item for item in list_dataset_choices(PROJECT_ROOT) if item.get("visibility") == "primary"] if include_catalog else []
    return {
        "defaultBundleName": default_bundle_name(),
        "savedState": saved_state if saved_state is not None else get_workbench_state_payload(project_root=PROJECT_ROOT),
        "bundles": list_available_workbench_bundles(PROJECT_ROOT) if include_catalog else [],
        "datasets": [_dataset_payload(item) for item in datasets],
        "activeRun": active_run if active_run_loaded else get_active_supervised_run(),
    }


def _official_task_environment_block_reason(bundle_path: Path, *, lang: str, require_official: bool = False) -> str:
    """Return a user-facing block reason when a bundle requires the official task sandbox."""

    try:
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    dataset = payload.get("dataset") if isinstance(payload.get("dataset"), dict) else {}
    cases = [item for item in list(payload.get("cases") or []) if isinstance(item, dict)]
    official_pending = str(dataset.get("official_verifier_status") or "").strip() == "harbor_pending"
    requires_official_env = any(
        bool(case.get("requires_official_task_environment"))
        or str(case.get("official_runner") or "").strip() == "harbor_pending"
        for case in cases
    )
    if not official_pending and not requires_official_env:
        return ""
    if not require_official:
        return ""

    missing: list[str] = []
    if shutil.which("uv") is None:
        missing.append("uv")
    if shutil.which("docker") is None:
        missing.append("docker")
    if not _docker_daemon_available():
        missing.append("docker daemon")
    missing_text = "、".join(dict.fromkeys(missing))
    suffix = f" 当前缺少：{missing_text}。" if missing_text else ""
    return text_for(
        lang,
        zh=(
            "这个 bundle 需要 Harbor/Docker 官方 Terminal-Bench 任务环境，当前监督 harness 还没有提供 "
            "/app sandbox 与官方判分器；不能作为真实评测启动。请先使用 terminal_bench_smoke，"
            "或接入官方 runner 后再运行。"
            f"{suffix}"
        ),
        en=(
            "This bundle requires the official Harbor/Docker Terminal-Bench task environment. "
            "The supervised harness does not currently provide the /app sandbox or official verifier, "
            "so it cannot be started as a real evaluation. Use terminal_bench_smoke first, or wire "
            f"the official runner before running it. Missing: {missing_text or 'official task environment'}."
        ),
    )


def _custom_harness_evaluation_notice(bundle_path: Path, *, lang: str) -> dict[str, Any]:
    """Return a notice payload when a Terminal-Bench seed bundle is run without the official verifier."""

    try:
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    dataset = payload.get("dataset") if isinstance(payload.get("dataset"), dict) else {}
    official_status = str(dataset.get("official_verifier_status") or "").strip()
    evaluation_mode = str(dataset.get("evaluation_mode") or "").strip()
    if evaluation_mode == "agent_judged":
        return {
            "evaluationMode": "agent_judged",
            "officialVerifierStatus": official_status or "not_required",
            "officialScoreAvailable": False,
            "scoreLabel": str(dataset.get("score_label") or "Agent-judged score (non-official)").strip(),
            "message": text_for(
                lang,
                zh="将使用纯 agent 裁决评分；不需要官方 Harbor/Docker 判分器，结果不是官方 Terminal-Bench 成绩。",
                en="This run will use pure agent judgment; no official Harbor/Docker verifier is required, and results are not official Terminal-Bench scores.",
            ),
        }
    if official_status != "harbor_pending" and evaluation_mode != "custom_harness":
        return {}
    return {
        "evaluationMode": evaluation_mode or "custom_harness",
        "officialVerifierStatus": official_status or "harbor_pending",
        "officialScoreAvailable": False,
        "scoreLabel": str(dataset.get("score_label") or "Vibelution custom score (non-official)").strip(),
        "message": text_for(
            lang,
            zh="将使用 Vibelution 自定义 harness 运行；结果不是 Terminal-Bench 官方成绩。",
            en="This run will use the Vibelution custom harness; results are not official Terminal-Bench scores.",
        ),
    }


def _record_custom_harness_evaluation_notice(
    bundle_path: Path,
    *,
    lang: str,
    bundle_name: str,
    source_kind: str,
    retry_of_run_id: str = "",
) -> dict[str, Any]:
    notice = _custom_harness_evaluation_notice(bundle_path, lang=lang)
    if not notice:
        return {}
    fields = {
        "bundleName": bundle_name,
        "sourceKind": source_kind,
        "retryOfRunId": retry_of_run_id,
        **notice,
    }
    _record_supervised_scene_event(
        "preflight",
        "supervised_run.preflight.custom_harness_non_official",
        message=str(notice.get("message") or ""),
        level="info",
        outcome="observed",
        fields=fields,
        lifecycle=True,
    )
    return notice


def _record_supervised_environment_preflight_block(
    *,
    message: str,
    bundle_name: str,
    source_kind: str,
    dataset_name: str = "",
    retry_of_run_id: str = "",
) -> None:
    _record_supervised_scene_event(
        "preflight",
        "supervised_run.preflight.environment_unavailable_blocked",
        message=message,
        level="warning",
        outcome="blocked",
        fields={
            "bundleName": bundle_name,
            "sourceKind": source_kind,
            "datasetName": dataset_name,
            "retryOfRunId": retry_of_run_id,
        },
        lifecycle=True,
    )


def _docker_daemon_available() -> bool:
    docker = shutil.which("docker")
    if not docker:
        return False
    try:
        import subprocess

        proc = subprocess.run(
            [docker, "version", "--format", "{{.Server.Version}}"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0,
        )
    except Exception:
        return False
    return proc.returncode == 0 and bool((proc.stdout or "").strip())


def start_supervised_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Start a live supervised run and return the initial snapshot."""

    lang = get_web_language()
    source_kind = str(payload.get("sourceKind") or "").strip().lower()
    requested_evaluation_mode = str(payload.get("evaluationMode") or "").strip().lower()
    require_official = requested_evaluation_mode in {"official", "official_verifier", "harbor", "harbor_official"}
    keep_worktree = bool(payload.get("keepWorktree"))
    dataset_name = str(payload.get("datasetName") or "").strip()
    dataset_limit = _coerce_dataset_limit(payload.get("datasetLimit"))
    bundle_name = str(payload.get("bundleName") or "").strip()
    mental_model_mode = normalize_supervised_mental_model_mode(payload.get("mentalModelMode"))
    mental_model_enabled = supervised_mental_model_enabled_for_mode(mental_model_mode)

    if source_kind not in {"dataset", "bundle"}:
        raise SupervisedRunValidationError(
            text_for(lang, zh="请选择监督运行来源。", en="Choose a supervised run source.")
        )

    if source_kind == "dataset":
        if not dataset_name:
            raise SupervisedRunValidationError(
                text_for(lang, zh="请选择一个数据集。", en="Choose a dataset.")
            )
        prepared = prepare_dataset_run(PROJECT_ROOT, dataset_name, dataset_limit)
        if not prepared.runnable:
            block_message = prepared.blocked_message or text_for(
                lang,
                zh="当前数据集暂不可运行。",
                en="This dataset is not runnable right now.",
            )
            if str(prepared.blocked_message or "").startswith("任务环境预检未通过"):
                _record_supervised_environment_preflight_block(
                    message=block_message,
                    bundle_name=prepared.bundle_name,
                    source_kind=source_kind,
                    dataset_name=dataset_name,
                )
            raise SupervisedRunValidationError(
                block_message
            )
        bundle_name = prepared.bundle_name
    else:
        if not bundle_name:
            raise SupervisedRunValidationError(
                text_for(lang, zh="请输入监督 bundle 名称。", en="Enter a supervised bundle name.")
            )
        bundle_path = resolve_workbench_bundle_path(PROJECT_ROOT, bundle_name)
        if not bundle_path.exists():
            raise SupervisedRunValidationError(
                text_for(
                    lang,
                    zh=f"监督 bundle 不存在：{bundle_name}",
                    en=f"Supervised bundle does not exist: {bundle_name}",
                )
            )
        environment_block_reason = bundle_environment_preflight_block_message(bundle_path, project_root=PROJECT_ROOT)
        if environment_block_reason:
            _record_supervised_environment_preflight_block(
                message=environment_block_reason,
                bundle_name=bundle_name,
                source_kind=source_kind,
            )
            raise SupervisedRunValidationError(environment_block_reason)
        block_reason = _official_task_environment_block_reason(bundle_path, lang=lang, require_official=require_official)
        if block_reason:
            _record_supervised_scene_event(
                "preflight",
                "supervised_run.preflight.official_environment_blocked",
                message=block_reason,
                level="warning",
                outcome="blocked",
                fields={
                    "bundleName": bundle_name,
                    "sourceKind": source_kind,
                },
                lifecycle=True,
            )
            raise SupervisedRunValidationError(block_reason)
        _record_custom_harness_evaluation_notice(
            bundle_path,
            lang=lang,
            bundle_name=bundle_name,
            source_kind=source_kind,
        )
        dataset_name = ""
        dataset_limit = None

    _raise_if_supervised_lease_conflict(lang=lang)
    agent_bindings = _validate_supervised_agent_bindings(supervised_agent_bindings(), lang=lang)

    context = {
        "runId": f"web-supervised-{uuid4().hex[:12]}",
        "lang": lang,
        "sourceKind": source_kind,
        "datasetName": dataset_name,
        "datasetLimit": dataset_limit,
        "bundleName": bundle_name,
        "keepWorktree": keep_worktree,
        "startedAt": _now_timestamp(),
        "agentBindings": agent_bindings,
        "mentalModelMode": mental_model_mode,
        "mentalModelEnabled": mental_model_enabled,
    }
    state = _initial_run_state(context)

    with _RUN_STATE_LOCK:
        active = _current_active_run_locked()
        if active is not None and str(active.get("status") or "").strip().lower() in _ACTIVE_RUN_STATUSES:
            raise SupervisedRunBusyError(
                text_for(
                    lang,
                    zh="当前已有监督任务在运行，请等这一轮结束后再启动新的任务。",
                    en="A supervised run is already active. Wait for it to finish before starting another one.",
                )
            )
        _RUN_STATES[context["runId"]] = state
        _RUN_CONTROLLERS[context["runId"]] = _SupervisedRunController()
        global _ACTIVE_RUN_ID
        _ACTIVE_RUN_ID = context["runId"]

    save_workbench_state(
        PROJECT_ROOT,
        build_workbench_state(
            source_kind=source_kind,
            dataset_name=dataset_name or None,
            dataset_limit=dataset_limit,
            bundle_name=bundle_name,
            keep_worktree=keep_worktree,
        ),
    )
    _publish_run_snapshot(context["runId"])

    try:
        _RUN_EXECUTOR.submit(_run_supervised_session, context)
    except Exception as exc:
        _mark_run_failed(
            context["runId"],
            text_for(
                lang,
                zh=f"无法启动监督任务：{type(exc).__name__}: {exc}",
                en=f"Failed to start supervised run: {type(exc).__name__}: {exc}",
            ),
        )
        raise
    return get_supervised_run_snapshot(context["runId"])


def _local_retry_supervised_run(run_id: str) -> dict[str, Any]:
    """Start a new supervised run that reuses successful roles from a finished run."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SupervisedRunValidationError(text_for(lang, zh="缺少监督 run id。", en="Missing supervised run id."))
    previous = _load_supervised_run_for_retry(normalized)
    if previous is None:
        raise SupervisedRunNotFoundError(text_for(lang, zh="未找到监督记录。", en="Supervised run not found."))

    status = str(previous.get("status") or "").strip().lower()
    if status not in {"done", "failed", "cancelled"}:
        raise SupervisedRunStateError(
            text_for(lang, zh="只有已结束的监督记录才能重跑失败项。", en="Only a finished supervised run can rerun failed items.")
        )
    decision_path = str(previous.get("decisionPath") or "").strip()
    if not decision_path:
        raise SupervisedRunValidationError(
            text_for(lang, zh="这条监督记录没有 decision 文件，不能重跑失败项。", en="This supervised run has no decision file to reuse for rerun.")
        )
    resolved_decision_path = _resolve_retry_decision_path(decision_path)
    if not resolved_decision_path.exists():
        raise SupervisedRunValidationError(
            text_for(lang, zh="续跑来源 decision 文件不存在。", en="The source decision file for retry does not exist.")
        )

    _raise_if_supervised_lease_conflict(lang=lang)
    agent_bindings = _validate_supervised_agent_bindings(supervised_agent_bindings(), lang=lang)
    mental_model_mode = normalize_supervised_mental_model_mode(previous.get("mentalModelMode") or previous.get("mental_model_mode"))
    mental_model_enabled = supervised_mental_model_enabled_for_mode(mental_model_mode)
    context = {
        "runId": f"web-supervised-{uuid4().hex[:12]}",
        "lang": lang,
        "sourceKind": str(previous.get("sourceKind") or "bundle").strip() or "bundle",
        "datasetName": str(previous.get("datasetName") or "").strip(),
        "datasetLimit": previous.get("datasetLimit") if previous.get("datasetLimit") != "" else None,
        "bundleName": str(previous.get("bundleName") or "").strip(),
        "keepWorktree": bool(previous.get("keepWorktree")),
        "startedAt": _now_timestamp(),
        "agentBindings": agent_bindings,
        "mentalModelMode": mental_model_mode,
        "mentalModelEnabled": mental_model_enabled,
        "retryOfRunId": normalized,
        "resumeFromDecisionPath": str(resolved_decision_path),
    }
    if not context["bundleName"]:
        raise SupervisedRunValidationError(
            text_for(lang, zh="这条监督记录缺少 bundle 名称，不能重跑失败项。", en="This supervised run has no bundle name to rerun.")
        )
    bundle_path = resolve_workbench_bundle_path(PROJECT_ROOT, context["bundleName"])
    environment_block_reason = bundle_environment_preflight_block_message(bundle_path, project_root=PROJECT_ROOT)
    if environment_block_reason:
        _record_supervised_environment_preflight_block(
            message=environment_block_reason,
            bundle_name=context["bundleName"],
            source_kind=context["sourceKind"],
            retry_of_run_id=normalized,
        )
        raise SupervisedRunValidationError(environment_block_reason)
    block_reason = _official_task_environment_block_reason(bundle_path, lang=lang, require_official=False)
    if block_reason:
        _record_supervised_scene_event(
            "preflight",
            "supervised_run.preflight.official_environment_blocked",
            message=block_reason,
            level="warning",
            outcome="blocked",
            fields={
                "bundleName": context["bundleName"],
                "sourceKind": context["sourceKind"],
                "retryOfRunId": normalized,
            },
            lifecycle=True,
        )
        raise SupervisedRunValidationError(block_reason)
    _record_custom_harness_evaluation_notice(
        bundle_path,
        lang=lang,
        bundle_name=context["bundleName"],
        source_kind=context["sourceKind"],
        retry_of_run_id=normalized,
    )
    state = _initial_run_state(context)
    state["retryOfRunId"] = normalized
    state["resumeFromDecisionPath"] = str(resolved_decision_path)
    state["latestMessage"] = text_for(
        lang,
        zh="已创建重跑任务：成功项会复用，失败或缺失项会重跑。",
        en="Queued rerun. Successful roles will be reused; failed or missing roles will rerun.",
    )
    state["currentTask"] = state["latestMessage"]
    state["eventTail"][0]["event"] = "retry_queued"
    state["eventTail"][0]["title"] = "失败项重跑已排队"
    state["eventTail"][0]["summary"] = state["latestMessage"]
    state["eventTail"][0]["retryOfRunId"] = normalized

    with _RUN_STATE_LOCK:
        active = _current_active_run_locked()
        if active is not None and str(active.get("status") or "").strip().lower() in _ACTIVE_RUN_STATUSES:
            raise SupervisedRunBusyError(
                text_for(
                    lang,
                    zh="当前已有监督任务在运行，请等这一轮结束后再重跑失败项。",
                    en="A supervised run is already active. Wait for it to finish before retrying.",
                )
            )
        _RUN_STATES[context["runId"]] = state
        _RUN_CONTROLLERS[context["runId"]] = _SupervisedRunController()
        global _ACTIVE_RUN_ID
        _ACTIVE_RUN_ID = context["runId"]

    _publish_run_snapshot(context["runId"])
    try:
        _RUN_EXECUTOR.submit(_run_supervised_session, context)
    except Exception as exc:
        _mark_run_failed(
            context["runId"],
            text_for(
                lang,
                zh=f"无法启动失败项重跑：{type(exc).__name__}: {exc}",
                en=f"Failed to start supervised retry: {type(exc).__name__}: {exc}",
            ),
        )
        raise
    return get_supervised_run_snapshot(context["runId"])


def get_active_supervised_run() -> dict[str, Any] | None:
    """Return the current active supervised run snapshot."""

    with _RUN_STATE_LOCK:
        active = _current_active_run_locked()
        if active is None:
            return None
        return _decorate_supervised_snapshot(_clone_locked(active))


def get_supervised_run_snapshot(run_id: str) -> dict[str, Any]:
    """Return a supervised run snapshot by its live run id."""

    with _RUN_STATE_LOCK:
        payload = _RUN_STATES.get(str(run_id or "").strip())
        if payload is None:
            raise SupervisedRunNotFoundError("Supervised run not found.")
        return _decorate_supervised_snapshot(_clone_locked(payload))


def request_pause_supervised_run(run_id: str) -> dict[str, Any]:
    """Pause one active supervised run at the next safe checkpoint."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SupervisedRunValidationError(text_for(lang, zh="缺少监督 run id。", en="Missing supervised run id."))

    publish_terminal = False
    with _RUN_STATE_LOCK:
        state = _require_run_locked(normalized, lang=lang)
        controller = _require_controller_locked(normalized, lang=lang)
        status = str(state.get("status") or "").strip().lower()
        now = _now_timestamp()

        if status in {"done", "failed", "cancelled"}:
            raise SupervisedRunStateError(
                text_for(lang, zh="这条监督记录已经结束，不能再暂停。", en="This supervised run is already finished.")
            )
        if status == "stopping":
            raise SupervisedRunStateError(
                text_for(lang, zh="这条监督记录正在终止，不能再暂停。", en="This supervised run is stopping already.")
            )
        if status == "paused" or bool(state.get("pauseRequested")):
            return _clone_locked(state)

        state["pauseRequested"] = True
        state["pauseRequestedAt"] = now
        _append_control_event_locked(
            state,
            event="pause_requested",
            title="已请求暂停",
            summary=text_for(
                lang,
                zh="这一轮会在当前安全点暂停。",
                en="This run will pause at the next safe checkpoint.",
            ),
            status="waiting",
        )
        if status == "queued":
            _set_paused_locked(
                state,
                lang=lang,
                now=now,
                summary=text_for(
                    lang,
                    zh="监督任务已在启动前暂停，等待恢复。",
                    en="The supervised run is paused before start and waiting to resume.",
                ),
            )
        else:
            state["currentPhase"] = "pause_requested"
            state["runtimeStatus"] = "waiting"
            state["currentTask"] = text_for(
                lang,
                zh="将在当前 case 结束后的安全点暂停监督运行。",
                en="The supervised run will pause at the next safe checkpoint after the current case.",
            )
            state["latestMessage"] = text_for(
                lang,
                zh="已请求暂停，当前 case 结束后会停下。",
                en="Pause requested. The run will stop after the current case reaches a safe checkpoint.",
            )
        publish_terminal = str(state.get("status") or "").strip().lower() == "cancelled"

    controller.request_pause()
    _publish_run_snapshot(normalized, terminal=publish_terminal)
    return get_supervised_run_snapshot(normalized)


def request_resume_supervised_run(run_id: str) -> dict[str, Any]:
    """Resume one paused supervised run or cancel a pending pause request."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SupervisedRunValidationError(text_for(lang, zh="缺少监督 run id。", en="Missing supervised run id."))

    with _RUN_STATE_LOCK:
        state = _require_run_locked(normalized, lang=lang)
        controller = _require_controller_locked(normalized, lang=lang)
        status = str(state.get("status") or "").strip().lower()
        pause_requested = bool(state.get("pauseRequested"))
        if status in {"done", "failed", "cancelled"}:
            raise SupervisedRunStateError(
                text_for(lang, zh="这条监督记录已经结束，不能再恢复。", en="This supervised run is already finished.")
            )
        if status == "stopping":
            raise SupervisedRunStateError(
                text_for(lang, zh="这条监督记录正在终止，不能再恢复。", en="This supervised run is already stopping.")
            )
        if status != "paused" and not pause_requested:
            return _clone_locked(state)

        state["pauseRequested"] = False
        if status == "paused":
            if _has_session_started(state):
                state["status"] = "running"
                state["currentPhase"] = "running"
                state["runtimeStatus"] = "running"
            else:
                state["status"] = "queued"
                state["currentPhase"] = "queued"
                state["runtimeStatus"] = "preparing"
            state["currentTask"] = text_for(
                lang,
                zh="监督任务已恢复，准备继续执行。",
                en="The supervised run has resumed and is preparing to continue.",
            )
        else:
            state["currentPhase"] = "running"
            state["runtimeStatus"] = "running"
            state["currentTask"] = text_for(
                lang,
                zh="已取消暂停请求，继续执行这一轮监督任务。",
                en="The pause request was cleared and the supervised run will keep going.",
            )
        state["latestMessage"] = text_for(
            lang,
            zh="监督任务已恢复。",
            en="The supervised run has resumed.",
        )
        _append_control_event_locked(
            state,
            event="run_resumed",
            title="监督任务已恢复",
            summary=state["latestMessage"],
            status="running" if _has_session_started(state) else "queued",
        )

    controller.request_resume()
    _publish_run_snapshot(normalized)
    return get_supervised_run_snapshot(normalized)


def request_stop_supervised_run(run_id: str) -> dict[str, Any]:
    """Request a graceful stop for one active supervised run."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SupervisedRunValidationError(text_for(lang, zh="缺少监督 run id。", en="Missing supervised run id."))

    publish_terminal = False
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(normalized)
        if state is None:
            return _cancel_file_only_supervised_run(normalized, lang=lang)
        controller = _require_controller_locked(normalized, lang=lang)
        status = str(state.get("status") or "").strip().lower()
        now = _now_timestamp()

        if status in {"done", "failed", "cancelled"}:
            return _clone_locked(state)
        if status == "stopping" or bool(state.get("stopRequested")):
            return _clone_locked(state)

        state["stopRequested"] = True
        state["stopRequestedAt"] = now
        state["pauseRequested"] = False
        _append_control_event_locked(
            state,
            event="stop_requested",
            title="已请求终止",
            summary=text_for(
                lang,
                zh="这一轮会在当前安全点终止。",
                en="This run will stop at the next safe checkpoint.",
            ),
            status="stopping",
        )
        if status in {"queued", "paused"}:
            _cancel_run_locked(
                normalized,
                state,
                lang=lang,
                now=now,
                summary=text_for(
                    lang,
                    zh="监督任务已按请求终止。",
                    en="The supervised run was cancelled as requested.",
                ),
                reason=text_for(
                    lang,
                    zh="操作者请求终止这一轮监督任务。",
                    en="The operator requested this supervised run to stop.",
                ),
            )
            publish_terminal = True
        else:
            state["status"] = "stopping"
            state["currentPhase"] = "stopping"
            state["runtimeStatus"] = "stopping"
            state["currentTask"] = text_for(
                lang,
                zh="将在当前 case 结束后的安全点终止监督运行。",
                en="The supervised run will stop at the next safe checkpoint after the current case.",
            )
            state["latestMessage"] = text_for(
                lang,
                zh="已请求终止，等待当前安全点收口。",
                en="Stop requested. Waiting for the current safe checkpoint to close.",
            )

    controller.request_stop()
    _publish_run_snapshot(normalized, terminal=publish_terminal)
    return get_supervised_run_snapshot(normalized)


def delete_supervised_run_snapshot(run_id: str) -> dict[str, Any]:
    """Delete one inactive supervised runtime-manager snapshot without touching audit records."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SupervisedRunValidationError(text_for(lang, zh="缺少监督 run id。", en="Missing supervised run id."))

    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(normalized)
        if state is not None:
            status = str(state.get("status") or "").strip().lower()
            if status in {"running", "paused", "stopping"}:
                raise SupervisedRunStateError(
                    text_for(
                        lang,
                        zh="这条监督任务仍在执行或暂停中，请先终止后再删除记录。",
                        en="This supervised run is still running or paused. Terminate it before deleting the record.",
                    )
                )
            if status == "queued":
                now = _now_timestamp()
                state["stopRequested"] = True
                state["stopRequestedAt"] = now
                _cancel_run_locked(
                    normalized,
                    state,
                    lang=lang,
                    now=now,
                    summary=text_for(
                        lang,
                        zh="已取消并删除这条排队中的监督任务。",
                        en="The queued supervised run was cancelled and deleted.",
                    ),
                    reason=text_for(
                        lang,
                        zh="操作者删除了排队中的监督任务。",
                        en="The operator deleted this queued supervised run.",
                    ),
                )
            _RUN_STATES.pop(normalized, None)
            _RUN_CONTROLLERS.pop(normalized, None)
            _clear_active_run_locked(normalized)

    return _delete_manager_supervised_run_snapshot(normalized, lang=lang)


def _delete_manager_supervised_run_snapshot(run_id: str, *, lang: str) -> dict[str, Any]:
    stored = load_manager_run_snapshot("supervised", run_id)
    status = str((stored or {}).get("status") or "").strip().lower()
    if status in {"running", "paused", "stopping"}:
        raise SupervisedRunStateError(
            text_for(
                lang,
                zh="这条监督任务仍在执行或暂停中，请先终止后再删除记录。",
                en="This supervised run is still running or paused. Terminate it before deleting the record.",
            )
        )
    if status == "queued":
        # A queued run may only exist as an orphaned runtime-manager snapshot. Deleting it is the
        # explicit cancel-and-clear path and does not touch supervised decision/proposal evidence.
        pass
    elif stored is None:
        # Empty or corrupt snapshot files load as missing; deleting still clears stale index pointers.
        pass
    elif status not in {"done", "failed", "cancelled", "success", "waiting", ""}:
        raise SupervisedRunStateError(
            text_for(
                lang,
                zh="这条监督记录状态暂不支持直接删除。",
                en="This supervised run state cannot be deleted directly.",
            )
        )

    try:
        result = delete_manager_run_snapshot("supervised", run_id)
    except ValueError as exc:
        raise SupervisedRunValidationError(text_for(lang, zh="监督 run id 无效。", en="Invalid supervised run id.")) from exc
    except OSError as exc:
        raise SupervisedRunDeleteError(str(exc)) from exc

    changed_store = bool(result.get("deleted")) or bool(result.get("clearedActive")) or bool(result.get("clearedLatest"))
    if not changed_store:
        if stored is None:
            raise SupervisedRunNotFoundError(text_for(lang, zh="未找到监督记录。", en="Supervised run not found."))
        raise SupervisedRunDeleteError(
            text_for(lang, zh="监督记录删除失败。", en="Failed to delete the supervised run record.")
        )

    return {
        "deleted": changed_store,
        "runId": str(result.get("runId") or run_id),
        "clearedActive": bool(result.get("clearedActive")),
        "clearedLatest": bool(result.get("clearedLatest")),
        "activeRunId": str(result.get("activeRunId") or ""),
        "latestRunId": str(result.get("latestRunId") or ""),
        "summary": text_for(
            lang,
            zh="已清理这条监督运行记录。",
            en="The supervised run record was cleared.",
        ),
    }


def _cancel_file_only_supervised_run(run_id: str, *, lang: str) -> dict[str, Any]:
    stored = load_manager_run_snapshot("supervised", run_id)
    if stored is None:
        raise SupervisedRunNotFoundError(text_for(lang, zh="未找到监督记录。", en="Supervised run not found."))

    status = str(stored.get("status") or "").strip().lower()
    if status not in _ACTIVE_RUN_STATUSES:
        return _decorate_supervised_snapshot(_clone_locked(stored))

    successful_snapshot = _build_completed_file_supervised_run_snapshot_if_closed_successfully(
        stored,
        lang=lang,
        control_reason="orphaned_success",
    )
    if successful_snapshot is not None:
        persisted = persist_manager_run_snapshot("supervised", successful_snapshot, active_run_id="")
        return _decorate_supervised_snapshot(_clone_locked(persisted))

    summary = text_for(
        lang,
        zh="运行管理器中断后已清理孤儿监督运行。",
        en="The orphaned supervised run was cleaned up after the runtime manager lost its live control context.",
    )
    reason = text_for(
        lang,
        zh="监督运行只有持久化快照，没有可继续控制的内存运行上下文。",
        en="The supervised run only had a persisted snapshot and no live in-memory control context.",
    )
    payload = _build_cancelled_file_supervised_run_snapshot(
        stored,
        lang=lang,
        summary=summary,
        reason=reason,
        control_reason="orphaned",
    )
    persisted = persist_manager_run_snapshot("supervised", payload, active_run_id="")
    return _decorate_supervised_snapshot(_clone_locked(persisted))


def force_cancel_active_supervised_runs_for_shutdown(reason: str = "") -> list[dict[str, Any]]:
    """Force-close active supervised snapshots before the workbench process exits."""

    lang = get_web_language()
    run_ids: list[str] = []
    with _RUN_STATE_LOCK:
        if _ACTIVE_RUN_ID:
            run_ids.append(_ACTIVE_RUN_ID)
    try:
        active_snapshot = load_manager_active_run_snapshot("supervised")
    except Exception:
        active_snapshot = None
    active_run_id = str((active_snapshot or {}).get("runId") or "").strip()
    if active_run_id and active_run_id not in run_ids:
        run_ids.append(active_run_id)

    closed: list[dict[str, Any]] = []
    for run_id in run_ids:
        snapshot = _force_cancel_supervised_run_for_shutdown(run_id, lang=lang, reason=reason)
        if snapshot is not None:
            closed.append(snapshot)
    return closed


def _force_cancel_supervised_run_for_shutdown(run_id: str, *, lang: str, reason: str = "") -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    if not normalized:
        return None

    summary = text_for(
        lang,
        zh="工作台正在关闭，系统已收口这轮监督运行，可以重新开始新的一轮。",
        en="The workbench is shutting down, so this supervised run was closed and a new run can be started later.",
    )
    cancel_reason = str(reason or "").strip() or text_for(
        lang,
        zh="工作台关闭时终止活跃监督运行。",
        en="Closed the active supervised run during workbench shutdown.",
    )
    controller: _SupervisedRunController | None = None
    publish_memory_snapshot = False
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(normalized)
        if state is not None:
            status = str(state.get("status") or "").strip().lower()
            if status not in _ACTIVE_RUN_STATUSES:
                return _decorate_supervised_snapshot(_clone_locked(state))
            now = _now_timestamp()
            controller = _RUN_CONTROLLERS.get(normalized)
            state["stopRequested"] = True
            state["stopRequestedAt"] = str(state.get("stopRequestedAt") or now)
            state["pauseRequested"] = False
            _cancel_run_locked(
                normalized,
                state,
                lang=lang,
                now=now,
                summary=summary,
                reason=cancel_reason,
            )
            state[_MANAGER_CONTROL_KEY] = {
                "ownerPid": "",
                "kind": "supervised",
                "clearedAt": now,
                "reason": "shutdown",
            }
            publish_memory_snapshot = True

    if controller is not None:
        controller.request_stop()
    if publish_memory_snapshot:
        _publish_run_snapshot(normalized, terminal=True)
        return get_supervised_run_snapshot(normalized)

    stored = load_manager_run_snapshot("supervised", normalized)
    if stored is None:
        return None
    status = str(stored.get("status") or "").strip().lower()
    if status not in _ACTIVE_RUN_STATUSES:
        return _decorate_supervised_snapshot(_clone_locked(stored))
    successful_snapshot = _build_completed_file_supervised_run_snapshot_if_closed_successfully(
        stored,
        lang=lang,
        control_reason="shutdown_success",
    )
    if successful_snapshot is not None:
        persisted = persist_manager_run_snapshot("supervised", successful_snapshot, active_run_id="")
        return _decorate_supervised_snapshot(_clone_locked(persisted))
    payload = _build_cancelled_file_supervised_run_snapshot(
        stored,
        lang=lang,
        summary=summary,
        reason=cancel_reason,
        control_reason="shutdown",
    )
    persisted = persist_manager_run_snapshot("supervised", payload, active_run_id="")
    return _decorate_supervised_snapshot(_clone_locked(persisted))


def _build_cancelled_file_supervised_run_snapshot(
    snapshot: dict[str, Any],
    *,
    lang: str,
    summary: str,
    reason: str,
    control_reason: str,
) -> dict[str, Any]:
    now = _now_timestamp()
    payload = _clone_locked(snapshot)
    payload["status"] = "cancelled"
    payload["currentPhase"] = "cancelled"
    payload["runtimeStatus"] = "idle"
    payload["updatedAt"] = now
    payload["finishedAt"] = now
    payload["stopRequested"] = True
    payload["stopRequestedAt"] = str(payload.get("stopRequestedAt") or now)
    payload["pauseRequested"] = False
    payload["reason"] = reason
    payload["latestMessage"] = summary
    payload["currentTask"] = text_for(
        lang,
        zh="监督任务已结束，不再继续执行。",
        en="The supervised run has stopped and will not continue.",
    )
    payload[_MANAGER_CONTROL_KEY] = {
        "ownerPid": "",
        "kind": "supervised",
        "clearedAt": now,
        "reason": control_reason,
    }
    _append_control_event_locked(
        payload,
        event="run_cancelled",
        title="监督任务已终止",
        summary=summary,
        status="cancelled",
    )
    return payload


def _build_completed_file_supervised_run_snapshot_if_closed_successfully(
    snapshot: dict[str, Any],
    *,
    lang: str,
    control_reason: str,
) -> dict[str, Any] | None:
    if not _snapshot_has_successful_transaction_close(snapshot):
        return None

    now = _now_timestamp()
    payload = _clone_locked(snapshot)
    summary = text_for(
        lang,
        zh="监督事务已成功关账；运行管理器只清理残留控制权。",
        en="The supervised transaction closed successfully; only the stale runtime-manager control state was cleared.",
    )
    payload["status"] = "done"
    payload["currentPhase"] = "done"
    payload["runtimeStatus"] = "idle"
    payload["updatedAt"] = now
    payload["finishedAt"] = str(payload.get("finishedAt") or now)
    payload["stopRequested"] = False
    payload["stopRequestedAt"] = ""
    payload["pauseRequested"] = False
    payload["reason"] = str(payload.get("reason") or summary)
    payload["latestMessage"] = summary
    payload["currentTask"] = text_for(
        lang,
        zh="监督任务已完成，可查看 case 输出轨迹。",
        en="The supervised run is complete. Review the case output trace.",
    )
    payload[_MANAGER_CONTROL_KEY] = {
        "ownerPid": "",
        "kind": "supervised",
        "clearedAt": now,
        "reason": control_reason,
    }
    _append_control_event_locked(
        payload,
        event="run_completed",
        title="监督运行完成",
        summary=summary,
        status="done",
    )
    return payload


def _snapshot_has_successful_transaction_close(snapshot: dict[str, Any]) -> bool:
    def normalize_status(value: Any) -> str:
        return str(value or "").lstrip("\ufeff").strip().lower()

    case_io = snapshot.get("currentCaseIo") if isinstance(snapshot.get("currentCaseIo"), dict) else {}
    for item in case_io.get("transcript") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip().lower() != "tool":
            continue
        if str(item.get("label") or "").strip() != "close_evolution_transaction_tool":
            continue
        status = normalize_status(item.get("status"))
        content = str(item.get("content") or "")
        if status and status not in {"success", "ok"}:
            continue
        raw_content = item.get("content")
        if isinstance(raw_content, dict):
            payload = raw_content
        else:
            try:
                payload = json.loads(content.lstrip("\ufeff").strip())
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        success_statuses = {"success", "ok"}
        transaction_status = normalize_status(payload.get("transaction_status"))
        tool_status = normalize_status(payload.get("status"))
        if transaction_status in success_statuses or tool_status in {"success", "ok"}:
            return True
        lowered = content.lower().replace("\ufeff", "")
        if '"transaction_status"' in lowered and ('"success"' in lowered or '"ok"' in lowered):
            return True
    return False


def stream_active_supervised_run_events(initial_snapshot: dict[str, Any] | None = None):
    """Yield SSE snapshots for the current active supervised run."""

    snapshot = initial_snapshot or get_active_supervised_run()
    if snapshot is None:
        raise SupervisedRunNotFoundError("No active supervised run.")

    run_id = str(snapshot.get("runId") or "").strip()
    if not run_id:
        raise SupervisedRunNotFoundError("No active supervised run.")

    subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_RUN_STREAM_QUEUE_SIZE)
    _register_run_subscriber(run_id, subscriber)
    try:
        yield _encode_sse_event(
            "supervised_run",
            {
                "type": "supervised_run",
                "runId": run_id,
                "snapshot": snapshot,
            },
        )
        while True:
            try:
                event = subscriber.get(timeout=_RUN_STREAM_HEARTBEAT_SECONDS)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield _encode_sse_event(str(event.get("type") or "supervised_run"), event)
            if bool(event.get("terminal")):
                break
    finally:
        _unregister_run_subscriber(run_id, subscriber)


def execute_supervised_action(session_id: str, action: str) -> dict[str, Any]:
    """Execute a proposal lifecycle action for a finished supervised run."""

    lang = get_web_language()
    if developer_sandbox.is_developer_mode_enabled():
        _record_supervised_scene_event(
            "action",
            "supervised_run.proposal_action.blocked_by_developer_mode",
            message="Supervised proposal action blocked in developer sandbox mode.",
            level="warning",
            outcome="blocked",
            fields={
                "sessionId": str(session_id or "").strip(),
                "action": str(action or "").strip().lower(),
                "developerMode": True,
            },
        )
        raise SupervisedRunActionError(
            text_for(
                lang,
                zh="开发者模式开启时不会修改正式监督进化治理链路；请关闭开发者模式后再执行 apply/activate/rollback。",
                en="Developer mode does not mutate the formal supervised-governance chain. Disable developer mode before apply/activate/rollback.",
            )
        )
    if not manual_governance_enabled():
        _record_supervised_scene_event(
            "action",
            "supervised_run.proposal_action.blocked_by_mode",
            message="Supervised proposal action blocked by automatic review mode.",
            level="warning",
            outcome="blocked",
            fields={
                "sessionId": str(session_id or "").strip(),
                "action": str(action or "").strip().lower(),
                "intakeMode": "auto",
            },
        )
        raise SupervisedRunActionError(manual_governance_block_reason(lang=lang))
    active = get_active_supervised_run()
    if active is not None and str(active.get("status") or "").strip().lower() in _ACTIVE_RUN_STATUSES:
        raise SupervisedRunBusyError(
            text_for(
                lang,
                zh="监督任务运行中，暂时不能改 proposal 状态。",
                en="A supervised run is active. Proposal actions are blocked until it finishes.",
            )
        )

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise SupervisedRunNotFoundError(text_for(lang, zh="未找到监督运行。", en="Supervised run not found."))

    decision_path = PROJECT_ROOT / "workspace" / "supervised_evolution" / "decisions" / f"{normalized_session_id}.json"
    if not decision_path.exists():
        raise SupervisedRunNotFoundError(text_for(lang, zh="未找到监督运行。", en="Supervised run not found."))

    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"apply", "activate", "rollback"}:
        raise SupervisedRunActionError(
            text_for(lang, zh="未知 proposal 动作。", en="Unknown proposal action.")
        )

    try:
        result = execute_gym_promotion_action(
            str(decision_path),
            normalized_action,
            project_root=PROJECT_ROOT,
        )
    except ValueError as exc:
        raise SupervisedRunActionError(str(exc)) from exc

    run_payload = get_run(normalized_session_id, project_root=PROJECT_ROOT)
    lifecycle = load_gym_promotion_lifecycle(str(decision_path), project_root=PROJECT_ROOT)
    return {
        "action": normalized_action,
        "summary": result.summary,
        "run": run_payload,
        "lifecycle": _lifecycle_payload(lifecycle),
    }


def _run_supervised_session(context: dict[str, Any]) -> None:
    run_id = context["runId"]
    try:
        if not _supervised_run_should_execute(run_id):
            return
        _checkpoint_supervised_run(
            run_id,
            {
                "phase": "preflight",
                "bundle_name": context["bundleName"],
                "agent_bindings": context.get("agentBindings") or {},
                "mental_model_mode": context.get("mentalModelMode") or "follow",
                "mental_model_enabled": context.get("mentalModelEnabled"),
            },
        )
        if not _supervised_run_should_execute(run_id):
            return
        result = run_workbench_session(
            bundle_name=context["bundleName"],
            keep_worktree=bool(context["keepWorktree"]),
            progress_callback=lambda event: _handle_progress_event(run_id, event),
            checkpoint_callback=lambda checkpoint: _checkpoint_supervised_run(run_id, checkpoint),
            cancel_checker=lambda: _supervised_run_cancel_reason(run_id),
            project_root=PROJECT_ROOT,
            agent_bindings=context.get("agentBindings") or {},
            mental_model_mode=str(context.get("mentalModelMode") or "follow"),
            harness_runner=_run_supervised_conversation_harness,
            resume_from_decision_path=(
                Path(str(context.get("resumeFromDecisionPath") or ""))
                if str(context.get("resumeFromDecisionPath") or "").strip()
                else None
            ),
        )
    except _SupervisedRunInterrupted:
        return
    except SupervisedEvolutionCancelled as exc:
        _finish_run_cancelled_from_harness(run_id, exc.reason or str(exc))
        return
    except Exception as exc:
        _mark_run_failed(run_id, f"{type(exc).__name__}: {exc}")
        return

    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None:
            return
        status = str(state.get("status") or "").strip().lower()
        if status in {"done", "failed", "cancelled"}:
            return
        decision = result.decision
        state["status"] = "done"
        state["currentPhase"] = "done"
        state["runtimeStatus"] = "idle"
        state["currentTask"] = text_for(
            get_web_language(),
            zh="监督运行已完成，可查看结论并决定后续动作。",
            en="The supervised run is complete. Review the decision and choose the next action.",
        )
        state["sessionId"] = str(getattr(decision, "session_id", "") or state.get("sessionId") or "")
        state["decision"] = str(getattr(decision, "decision", "") or "")
        state["reason"] = str(getattr(decision, "reason", "") or "")
        state["decisionPath"] = str(getattr(decision, "decision_path", "") or "")
        policy_action = getattr(decision, "policy_action", {}) or {}
        state["policyAction"] = str(policy_action.get("action") or "")
        state["latestMessage"] = result.decision_summary
        state["updatedAt"] = _now_timestamp()
        state["finishedAt"] = state["updatedAt"]
        state["lineageIndexPath"] = str(result.lineage_index_path or "")
        state["lineageSummary"] = str(result.lineage_summary or "")
        _append_event_locked(
            state,
            {
                "timestamp": state["updatedAt"],
                "event": "run_completed",
                "title": "监督运行完成",
                "summary": result.decision_summary,
                "status": "done",
                "decision": state["decision"],
                "reason": state["reason"],
                "sessionId": state["sessionId"],
            },
        )
        _clear_active_run_locked(run_id)
        _RUN_CONTROLLERS.pop(run_id, None)
    _publish_run_snapshot(run_id, terminal=True)


def _supervised_run_should_execute(run_id: str) -> bool:
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None or run_id not in _RUN_CONTROLLERS:
            return False
        status = str(state.get("status") or "").strip().lower()
        return status not in {"done", "failed", "cancelled"} and not bool(state.get("stopRequested"))


def _supervised_run_cancel_reason(run_id: str) -> str:
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None or run_id not in _RUN_CONTROLLERS:
            return "监督运行控制状态已不存在，终止当前执行。"
        status = str(state.get("status") or "").strip().lower()
        if status in {"done", "failed", "cancelled"}:
            return "监督运行已进入终态，终止当前执行。"
        if bool(state.get("stopRequested")):
            return text_for(
                get_web_language(),
                zh="操作者请求终止这一轮监督任务。",
                en="The operator requested this supervised run to stop.",
            )
    return ""


def _finish_run_cancelled_from_harness(run_id: str, reason: str) -> None:
    lang = get_web_language()
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None:
            return
        status = str(state.get("status") or "").strip().lower()
        if status in {"done", "failed", "cancelled"}:
            return
        now = _now_timestamp()
        _cancel_run_locked(
            run_id,
            state,
            lang=lang,
            now=now,
            summary=text_for(
                lang,
                zh="监督任务已按请求终止，当前 case 进程已停止。",
                en="The supervised run was cancelled as requested, and the current case process was stopped.",
            ),
            reason=reason
            or text_for(
                lang,
                zh="操作者请求终止这一轮监督任务。",
                en="The operator requested this supervised run to stop.",
            ),
        )
    _publish_run_snapshot(run_id, terminal=True)



def _handle_progress_event(run_id: str, event: dict[str, Any]) -> None:
    lang = get_web_language()
    scene_event: dict[str, Any] | None = None
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None:
            return
        event_type = str(event.get("event") or "").strip()
        status = str(state.get("status") or "").strip().lower()
        pause_requested = bool(state.get("pauseRequested"))
        stop_requested = bool(state.get("stopRequested"))
        state["updatedAt"] = _now_timestamp()
        if event_type == "session_start":
            if status not in {"paused", "stopping", "cancelled"}:
                state["status"] = "running"
            state["currentPhase"] = "stopping" if stop_requested else "pause_requested" if pause_requested else "running"
            state["sessionId"] = str(event.get("session_id") or state.get("sessionId") or "")
            state["bundleName"] = str(event.get("bundle_name") or state.get("bundleName") or "")
            state["caseTotal"] = max(0, int(event.get("case_total") or 0))
            state["activeAdvisoryCount"] = max(0, int(event.get("active_advisory_count") or 0))
            if event.get("mental_model_mode") is not None:
                state["mentalModelMode"] = normalize_supervised_mental_model_mode(event.get("mental_model_mode"))
            if "mental_model_enabled" in event:
                state["mentalModelEnabled"] = event.get("mental_model_enabled")
            state["latestMessage"] = _event_summary(event)
            state["runtimeStatus"] = "stopping" if stop_requested else "waiting" if pause_requested else "running"
            if stop_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求终止，等待当前安全点收口。",
                    en="Stop requested. Waiting for the current safe checkpoint to close.",
                )
            elif pause_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求暂停，等待当前安全点停下。",
                    en="Pause requested. Waiting for the next safe checkpoint.",
                )
            else:
                state["currentTask"] = text_for(
                    lang,
                    zh="监督会话已启动，准备进入 case 对比。",
                    en="The supervised session started and is preparing the case comparison run.",
                )
        elif event_type == "role_start":
            if status not in {"paused", "stopping", "cancelled"}:
                state["status"] = "running"
            state["currentPhase"] = "stopping" if stop_requested else "pause_requested" if pause_requested else "running"
            state["currentCaseIndex"] = max(0, int(event.get("case_index") or 0))
            state["caseTotal"] = max(0, int(event.get("case_total") or state.get("caseTotal") or 0))
            state["currentCaseId"] = str(event.get("case_id") or "")
            state["currentRole"] = str(event.get("role") or "")
            state["currentCaseScenario"] = str(event.get("scenario") or "")
            state["currentCaseMode"] = str(event.get("mode") or "")
            state["currentCasePrompt"] = str(event.get("prompt") or "")
            state["currentAgentBinding"] = _agent_binding_snapshot(event.get("agent_binding"))
            state["currentCaseIo"] = None
            state["latestMessage"] = _event_summary(event)
            state["runtimeStatus"] = "stopping" if stop_requested else "waiting" if pause_requested else "running"
            if stop_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求终止，当前 case 结束后会收口。",
                    en="Stop requested. The run will stop after the current case finishes.",
                )
            elif pause_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求暂停，当前 case 结束后会停下。",
                    en="Pause requested. The run will pause after the current case finishes.",
                )
            else:
                state["currentTask"] = text_for(
                    lang,
                    zh=f"正在执行 case {state['currentCaseIndex']}/{state['caseTotal']} 的 {state['currentRole']} 对比。",
                    en=(
                        f"Running case {state['currentCaseIndex']}/{state['caseTotal']} "
                        f"for the {state['currentRole']} role."
                    ),
                )
        elif event_type == "role_live":
            if status not in {"paused", "stopping", "cancelled"}:
                state["status"] = "running"
            state["currentPhase"] = "stopping" if stop_requested else "pause_requested" if pause_requested else "running"
            state["currentCaseIndex"] = max(0, int(event.get("case_index") or state.get("currentCaseIndex") or 0))
            state["caseTotal"] = max(0, int(event.get("case_total") or state.get("caseTotal") or 0))
            state["currentCaseId"] = str(event.get("case_id") or state.get("currentCaseId") or "")
            state["currentRole"] = str(event.get("role") or state.get("currentRole") or "")
            state["currentCaseScenario"] = str(event.get("scenario") or state.get("currentCaseScenario") or "")
            state["currentCaseMode"] = str(event.get("mode") or state.get("currentCaseMode") or "")
            state["currentCasePrompt"] = str(event.get("prompt") or state.get("currentCasePrompt") or "")
            state["currentAgentBinding"] = _agent_binding_snapshot(event.get("agent_binding") or state.get("currentAgentBinding"))
            state["currentCaseIo"] = _case_io_payload(event)
            phase = str(event.get("phase") or "").strip()
            latest_output = str(((state.get("currentCaseIo") or {}).get("latestOutput")) or "").strip()
            latest_label = str(((state.get("currentCaseIo") or {}).get("latestOutputLabel")) or "").strip()
            if latest_output:
                state["latestMessage"] = latest_output
            elif phase == "environment_preflight":
                state["latestMessage"] = _event_summary(event)
            state["runtimeStatus"] = "stopping" if stop_requested else "waiting" if pause_requested else "running"
            if stop_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求终止，当前 case 结束后会收口。",
                    en="Stop requested. The run will stop after the current case finishes.",
                )
            elif pause_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求暂停，当前 case 结束后会停下。",
                    en="Pause requested. The run will pause after the current case finishes.",
                )
            elif phase == "environment_preflight":
                state["currentTask"] = text_for(
                    lang,
                    zh=f"正在预检 case {state['currentCaseIndex']}/{state['caseTotal']} 的任务环境。",
                    en=(
                        f"Checking the task environment for case {state['currentCaseIndex']}/"
                        f"{state['caseTotal']}."
                    ),
                )
            elif latest_label:
                state["currentTask"] = text_for(
                    lang,
                    zh=(
                        f"正在执行 case {state['currentCaseIndex']}/{state['caseTotal']} 的 "
                        f"{state['currentRole']}，最新输出来自 {latest_label}。"
                    ),
                    en=(
                        f"Running case {state['currentCaseIndex']}/{state['caseTotal']} "
                        f"for {state['currentRole']}. Latest output came from {latest_label}."
                    ),
                )
            else:
                state["currentTask"] = text_for(
                    lang,
                    zh=f"正在执行 case {state['currentCaseIndex']}/{state['caseTotal']} 的 {state['currentRole']} 对比。",
                    en=(
                        f"Running case {state['currentCaseIndex']}/{state['caseTotal']} "
                        f"for the {state['currentRole']} role."
                    ),
                )
            if phase == "environment_preflight":
                scene_event = _event_tail_entry(event, timestamp=state["updatedAt"])
        elif event_type in {"role_finish", "role_reused"}:
            if status not in {"paused", "stopping", "cancelled"}:
                state["status"] = "running"
            state["currentPhase"] = "stopping" if stop_requested else "pause_requested" if pause_requested else "running"
            state["currentCaseIndex"] = max(0, int(event.get("case_index") or state.get("currentCaseIndex") or 0))
            state["caseTotal"] = max(0, int(event.get("case_total") or state.get("caseTotal") or 0))
            state["currentCaseId"] = str(event.get("case_id") or "")
            state["currentRole"] = str(event.get("role") or "")
            state["currentAgentBinding"] = _agent_binding_snapshot(event.get("agent_binding") or state.get("currentAgentBinding"))
            state["latestMessage"] = _event_summary(event)
            state["runtimeStatus"] = "stopping" if stop_requested else "waiting" if pause_requested else "running"
            if stop_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求终止，等待当前安全点结束这一轮。",
                    en="Stop requested. Waiting for the current safe checkpoint to end this run.",
                )
            elif pause_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求暂停，等待当前安全点停下。",
                    en="Pause requested. Waiting for the current safe checkpoint.",
                )
            else:
                state["currentTask"] = text_for(
                    lang,
                    zh=f"已完成 case {state['currentCaseId'] or state['currentCaseIndex']} 的 {state['currentRole']}，准备继续。",
                    en=(
                        f"Finished {state['currentRole']} for case "
                        f"{state['currentCaseId'] or state['currentCaseIndex']} and preparing the next step."
                    ),
                )
        elif event_type == "session_finish":
            if status not in {"paused", "stopping", "cancelled"}:
                state["status"] = "running"
            state["currentPhase"] = "evaluating"
            state["sessionId"] = str(event.get("session_id") or state.get("sessionId") or "")
            state["decision"] = str(event.get("decision") or "")
            state["reason"] = str(event.get("reason") or "")
            state["decisionPath"] = str(event.get("decision_path") or "")
            state["policyAction"] = str(event.get("policy_action") or "")
            state["activeAdvisoryCount"] = max(0, int(event.get("active_advisory_count") or state.get("activeAdvisoryCount") or 0))
            state["latestMessage"] = _event_summary(event)
            state["runtimeStatus"] = "running"
            state["currentTask"] = text_for(
                lang,
                zh="case 对比已结束，正在整理监督结论。",
                en="The case comparison run finished and the supervised decision is being assembled.",
            )
        elif event_type == "session_error":
            if status not in {"paused", "stopping", "cancelled"}:
                state["status"] = "running"
            state["latestMessage"] = _event_summary(event)
            state["runtimeStatus"] = "failed"
            state["currentTask"] = text_for(
                lang,
                zh="监督运行遇到异常，请查看错误与日志。",
                en="The supervised run hit an error. Inspect the error and logs.",
            )
        elif event_type == "session_cancelled":
            state["currentPhase"] = "stopping"
            state["latestMessage"] = _event_summary(event)
            state["runtimeStatus"] = "stopping"
            state["currentTask"] = text_for(
                lang,
                zh="监督运行正在按请求终止，当前 case 进程已被停止。",
                en="The supervised run is cancelling as requested, and the current case process has been stopped.",
            )
        if event_type != "role_live":
            scene_event = _event_tail_entry(event, timestamp=state["updatedAt"])
            _append_event_locked(state, scene_event)
        elif scene_event is not None:
            _append_event_locked(state, scene_event)
    if scene_event is not None:
        _record_supervised_progress_scene_event(run_id, scene_event)
    _publish_run_snapshot(run_id)


def _mark_run_failed(run_id: str, message: str) -> None:
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None:
            return
        state["status"] = "failed"
        state["currentPhase"] = "failed"
        state["runtimeStatus"] = "failed"
        state["reason"] = str(message or "").strip()
        state["latestMessage"] = str(message or "").strip()
        state["updatedAt"] = _now_timestamp()
        state["finishedAt"] = state["updatedAt"]
        state["currentTask"] = text_for(
            get_web_language(),
            zh="监督运行失败，请检查错误与日志。",
            en="The supervised run failed. Inspect the error and logs.",
        )
        _append_event_locked(
            state,
            {
                "timestamp": state["updatedAt"],
                "event": "run_failed",
                "title": "监督运行失败",
                "summary": state["latestMessage"],
                "status": "failed",
                "reason": state["reason"],
            },
        )
        _clear_active_run_locked(run_id)
        _RUN_CONTROLLERS.pop(run_id, None)
    _publish_run_snapshot(run_id, terminal=True)


def _initial_run_state(context: dict[str, Any]) -> dict[str, Any]:
    dataset_name = str(context.get("datasetName") or "").strip()
    lang = str(context.get("lang") or "zh")
    return {
        "runId": context["runId"],
        "status": "queued",
        "currentPhase": "queued",
        "runtimeStatus": "queued",
        "sourceKind": context["sourceKind"],
        "runKind": "supervised_evolution_run",
        "leases": [EVALUATION_LEASE],
        "sessionId": "",
        "bundleName": context["bundleName"],
        "datasetName": dataset_name,
        "datasetLimit": context["datasetLimit"],
        "keepWorktree": bool(context["keepWorktree"]),
        "mentalModelMode": str(context.get("mentalModelMode") or "follow"),
        "mentalModelEnabled": context.get("mentalModelEnabled"),
        "startedAt": context["startedAt"],
        "updatedAt": context["startedAt"],
        "finishedAt": "",
        "caseTotal": 0,
        "currentCaseIndex": 0,
        "currentCaseId": "",
        "currentRole": "",
        "currentCaseScenario": "",
        "currentCaseMode": "",
        "currentCasePrompt": "",
        "currentAgentBinding": {},
        "currentCaseIo": None,
        "currentTask": text_for(
            lang,
            zh="监督任务已排队，等待开始。",
            en="The supervised run is queued and waiting to start.",
        ),
        "decision": "",
        "reason": "",
        "decisionPath": "",
        "policyAction": "",
        "lineageIndexPath": "",
        "lineageSummary": "",
        "activeAdvisoryCount": 0,
        "agentBindings": _agent_bindings_snapshot(context.get("agentBindings") or {}),
        "retryOfRunId": str(context.get("retryOfRunId") or "").strip(),
        "resumeFromDecisionPath": str(context.get("resumeFromDecisionPath") or "").strip(),
        "pauseRequested": False,
        "pauseRequestedAt": "",
        "pausedAt": "",
        "stopRequested": False,
        "stopRequestedAt": "",
        "latestMessage": text_for(
            lang,
            zh="监督任务已排队。",
            en="Queued supervised run.",
        ),
        "eventTail": [
            {
                "timestamp": context["startedAt"],
                "event": "queued",
                "title": "监督任务已排队",
                "summary": _queued_summary(context),
                "status": "queued",
                "sourceKind": context["sourceKind"],
                "datasetName": dataset_name,
                "datasetLimit": context["datasetLimit"],
                "bundleName": context["bundleName"],
                "keepWorktree": bool(context["keepWorktree"]),
                "agentBindings": _agent_bindings_snapshot(context.get("agentBindings") or {}),
                "mentalModelMode": str(context.get("mentalModelMode") or "follow"),
                "mentalModelEnabled": context.get("mentalModelEnabled"),
            }
        ],
        _MANAGER_CONTROL_KEY: _build_manager_control_payload(),
    }


def _clone_locked(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _build_manager_control_payload() -> dict[str, Any]:
    return {
        "ownerPid": os.getpid(),
        "kind": "supervised",
        "claimedAt": _now_timestamp(),
    }


def _agent_bindings_snapshot(bindings: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bindings, dict):
        return {}
    snapshot: dict[str, Any] = {}
    for role, binding in bindings.items():
        if not isinstance(binding, dict):
            continue
        normalized_role = str(role or binding.get("role") or "").strip()
        if not normalized_role:
            continue
        snapshot[normalized_role] = {
            "agentId": str(binding.get("agentId") or "").strip(),
            "displayName": str(binding.get("displayName") or "").strip(),
            "profileId": str(binding.get("profileId") or "").strip(),
            "dialogueModelId": str(binding.get("dialogueModelId") or "").strip(),
            "llmBindings": dict(binding.get("llmBindings") or {}) if isinstance(binding.get("llmBindings"), dict) else {},
            "directSessionId": str(binding.get("directSessionId") or "").strip(),
            "workspacePath": str(binding.get("workspacePath") or "").strip(),
            "role": str(binding.get("role") or normalized_role).strip(),
            "roleLabel": str(binding.get("roleLabel") or "").strip(),
        }
    return snapshot


def _agent_binding_snapshot(binding: Any) -> dict[str, Any]:
    if not isinstance(binding, dict):
        return {}
    return {
        "agentId": str(binding.get("agentId") or "").strip(),
        "displayName": str(binding.get("displayName") or "").strip(),
        "profileId": str(binding.get("profileId") or "").strip(),
        "dialogueModelId": str(binding.get("dialogueModelId") or "").strip(),
        "llmBindings": dict(binding.get("llmBindings") or {}) if isinstance(binding.get("llmBindings"), dict) else {},
        "directSessionId": str(binding.get("directSessionId") or "").strip(),
        "workspacePath": str(binding.get("workspacePath") or "").strip(),
        "role": str(binding.get("role") or "").strip(),
        "roleLabel": str(binding.get("roleLabel") or "").strip(),
    }


def _validate_supervised_agent_bindings(bindings: Any, *, lang: str) -> dict[str, dict[str, Any]]:
    if not isinstance(bindings, dict) or not bindings:
        _record_supervised_scene_event(
            "preflight",
            "supervised_run.preflight.agent_binding_invalid",
            message="Supervised run has no Agent bindings.",
            level="error",
            outcome="blocked",
            fields={"reason": "missing_agent_bindings"},
            lifecycle=True,
        )
        raise SupervisedRunValidationError(
            text_for(lang, zh="监督运行缺少 Agent 绑定，已阻止启动。", en="Supervised run is missing Agent bindings and was blocked.")
        )
    validated: dict[str, dict[str, Any]] = {}
    for role, binding in bindings.items():
        normalized_role = str(role or "").strip()
        if not normalized_role or not isinstance(binding, dict):
            continue
        agent_id = str(binding.get("agentId") or "").strip()
        dialogue_model_id = str(binding.get("dialogueModelId") or "").strip()
        llm_bindings = binding.get("llmBindings") if isinstance(binding.get("llmBindings"), dict) else {}
        dialogue_binding_id = str((llm_bindings.get("dialogue") or {}).get("modelId") or "").strip() if isinstance(llm_bindings.get("dialogue"), dict) else ""
        reason = ""
        if not agent_id:
            reason = "missing_agent_id"
        elif not dialogue_model_id:
            reason = "missing_dialogue_model_id"
        elif not dialogue_binding_id:
            reason = "missing_dialogue_llm_binding"
        elif dialogue_binding_id != dialogue_model_id:
            reason = "dialogue_model_mismatch"
        if reason:
            _record_supervised_scene_event(
                "preflight",
                "supervised_run.preflight.agent_binding_invalid",
                message="Supervised Agent binding is incomplete.",
                level="error",
                outcome="blocked",
                fields={
                    "role": normalized_role,
                    "agentId": agent_id,
                    "dialogueModelId": dialogue_model_id,
                    "dialogueBindingModelId": dialogue_binding_id,
                    "reason": reason,
                },
                lifecycle=True,
            )
            raise SupervisedRunValidationError(
                text_for(
                    lang,
                    zh=f"监督角色 {normalized_role} 的 Agent 模型绑定不完整，已阻止启动：{reason}",
                    en=f"Supervised role {normalized_role} has an incomplete Agent model binding and was blocked: {reason}",
                )
            )
        normalized = dict(binding)
        normalized["llmSlot"] = str(normalized.get("llmSlot") or "dialogue").strip() or "dialogue"
        validated[normalized_role] = normalized
    return validated


def _current_runtime_manager_owner_pid() -> int:
    try:
        from core.runtime_manager.state_store import load_pid

        return int(load_pid() or 0)
    except Exception:
        return 0


def _manager_control_is_current(payload: dict[str, Any]) -> bool:
    control = payload.get(_MANAGER_CONTROL_KEY) if isinstance(payload.get(_MANAGER_CONTROL_KEY), dict) else {}
    try:
        owner_pid = int(control.get("ownerPid") or 0)
    except (TypeError, ValueError):
        owner_pid = 0
    return owner_pid > 0 and owner_pid == _current_runtime_manager_owner_pid()


def _decorate_supervised_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    payload["actionStates"] = _supervised_action_states(payload, lang=get_web_language())
    return payload


def _supervised_action_states(payload: dict[str, Any], *, lang: str) -> dict[str, dict[str, Any]]:
    status = str(payload.get("status") or "").strip().lower()
    pause_requested = bool(payload.get("pauseRequested"))
    stop_requested = bool(payload.get("stopRequested"))
    decision_path = str(payload.get("decisionPath") or "").strip()

    def enabled_state() -> dict[str, Any]:
        return {"enabled": True, "reason": ""}

    def disabled_state(reason: str) -> dict[str, Any]:
        return {"enabled": False, "reason": reason}

    if status in {"queued", "running"} and not pause_requested and not stop_requested:
        pause_state = enabled_state()
    elif status == "paused":
        pause_state = disabled_state(
            text_for(lang, zh="这一轮已经暂停，可以直接恢复。", en="This run is already paused and can be resumed directly.")
        )
    elif status in {"done", "failed", "cancelled"}:
        pause_state = disabled_state(
            text_for(lang, zh="这条监督记录已经结束，不能再暂停。", en="This supervised run is already finished and cannot be paused.")
        )
    elif stop_requested or status == "stopping":
        pause_state = disabled_state(
            text_for(lang, zh="这一轮正在终止，不能再请求暂停。", en="This run is already stopping and cannot accept another pause request.")
        )
    else:
        pause_state = disabled_state(
            text_for(lang, zh="暂停请求已经发出，等待当前安全点收口。", en="Pause has already been requested. Wait for the current safe checkpoint.")
        )

    if status == "paused" or (status in {"queued", "running"} and pause_requested):
        resume_state = enabled_state()
    elif status in {"done", "failed", "cancelled"}:
        resume_state = disabled_state(
            text_for(lang, zh="这条监督记录已经结束，不能再恢复。", en="This supervised run is already finished and cannot be resumed.")
        )
    else:
        resume_state = disabled_state(
            text_for(lang, zh="只有已暂停或等待暂停的这一轮才能恢复。", en="Only a paused run, or one waiting to pause, can be resumed.")
        )

    if status in {"queued", "running", "paused"} and not stop_requested:
        terminate_state = enabled_state()
    elif status in {"done", "failed", "cancelled"}:
        terminate_state = disabled_state(
            text_for(lang, zh="这条监督记录已经结束，无需再次终止。", en="This supervised run is already finished and does not need another stop request.")
        )
    else:
        terminate_state = disabled_state(
            text_for(lang, zh="终止请求已经发出，等待这一轮收口。", en="A stop request has already been sent. Wait for this run to close.")
        )

    if status in {"queued", "done", "failed", "cancelled"}:
        delete_state = enabled_state()
    elif status in {"running", "paused", "stopping"}:
        delete_state = disabled_state(
            text_for(
                lang,
                zh="这条监督任务仍在执行或暂停中，请先终止后再删除记录。",
                en="This supervised run is still running or paused. Terminate it before deleting the record.",
            )
        )
    else:
        delete_state = disabled_state(
            text_for(lang, zh="这条监督记录状态暂不支持直接删除。", en="This supervised run state cannot be deleted directly.")
        )

    if status in {"done", "failed", "cancelled"} and decision_path:
        retry_state = enabled_state()
    elif status in {"queued", "running", "paused", "stopping"}:
        retry_state = disabled_state(
            text_for(lang, zh="这条监督任务仍在执行或暂停中，结束后才能重跑失败项。", en="This run is still active. Rerun is available after it finishes.")
        )
    else:
        retry_state = disabled_state(
            text_for(lang, zh="这条监督记录没有可复用的 decision，不能重跑失败项。", en="This record has no reusable decision for rerun.")
        )

    return {
        "pause": pause_state,
        "resume": resume_state,
        "terminate": terminate_state,
        "delete": delete_state,
        "retry": retry_state,
    }


def _require_run_locked(run_id: str, *, lang: str) -> dict[str, Any]:
    state = _RUN_STATES.get(run_id)
    if state is None:
        raise SupervisedRunNotFoundError(text_for(lang, zh="未找到监督记录。", en="Supervised run not found."))
    return state


def _load_supervised_run_for_retry(run_id: str) -> dict[str, Any] | None:
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is not None:
            return _clone_locked(state)
    stored = load_manager_run_snapshot("supervised", run_id)
    return _clone_locked(stored) if isinstance(stored, dict) else None


def _resolve_retry_decision_path(value: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return Path()
    path = Path(raw)
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def _raise_if_supervised_lease_conflict(*, lang: str) -> None:
    active_runs = list_active_session_work_runs()
    self_active = _load_active_work_run_snapshot("self")
    if self_active is not None:
        active_runs.append(self_active)
    decision = check_lease_conflicts(
        WorkRunLeaseRequest(run_kind="supervised_evolution_run", leases=[EVALUATION_LEASE]),
        active_runs,
    )
    if not decision.allowed:
        raise SupervisedRunBusyError(_localize_lease_conflict(decision.reason, lang=lang))


def _load_active_work_run_snapshot(kind: str) -> dict[str, Any] | None:
    try:
        snapshot = load_manager_active_run_snapshot(kind)
    except Exception:
        return None
    return snapshot if isinstance(snapshot, dict) else None


def _localize_lease_conflict(reason: str, *, lang: str) -> str:
    fallback = str(reason or "").strip()
    return text_for(
        lang,
        zh=f"当前资源正在被另一条运行占用，请等待它收束后再启动监督运行。{fallback}",
        en=f"Another active run holds a conflicting resource lease. Wait for it to finish before starting supervised evolution. {fallback}",
    ).strip()


def _require_controller_locked(run_id: str, *, lang: str) -> _SupervisedRunController:
    controller = _RUN_CONTROLLERS.get(run_id)
    if controller is None:
        raise SupervisedRunStateError(
            text_for(
                lang,
                zh="这条监督记录当前没有可继续控制的运行上下文。",
                en="This supervised run no longer has a live control context.",
            )
        )
    return controller


def _clear_active_run_locked(run_id: str) -> None:
    global _ACTIVE_RUN_ID
    if _ACTIVE_RUN_ID == run_id:
        _ACTIVE_RUN_ID = None


def _has_session_started(state: dict[str, Any]) -> bool:
    return bool(str(state.get("sessionId") or "").strip()) or int(state.get("caseTotal") or 0) > 0


def _append_control_event_locked(
    state: dict[str, Any],
    *,
    event: str,
    title: str,
    summary: str,
    status: str,
) -> None:
    _append_event_locked(
        state,
        {
            "timestamp": state["updatedAt"],
            "event": event,
            "title": title,
            "summary": summary,
            "status": status,
            "caseId": str(state.get("currentCaseId") or ""),
            "caseIndex": _optional_int(state.get("currentCaseIndex")),
            "caseTotal": _optional_int(state.get("caseTotal")),
            "role": str(state.get("currentRole") or ""),
            "scenario": "",
            "mode": "",
            "bundleName": str(state.get("bundleName") or ""),
            "sessionId": str(state.get("sessionId") or ""),
            "decision": str(state.get("decision") or ""),
            "reason": str(state.get("reason") or ""),
            "errorType": "",
            "elapsedSeconds": None,
            "resultStatus": status,
        },
    )


def _set_paused_locked(state: dict[str, Any], *, lang: str, now: str, summary: str) -> None:
    state["status"] = "paused"
    state["currentPhase"] = "paused"
    state["runtimeStatus"] = "paused"
    state["updatedAt"] = now
    state["pausedAt"] = now
    state["currentTask"] = text_for(
        lang,
        zh="监督任务已暂停，等待人工恢复。",
        en="The supervised run is paused and waiting to resume.",
    )
    state["latestMessage"] = summary
    _append_control_event_locked(
        state,
        event="run_paused",
        title="监督任务已暂停",
        summary=summary,
        status="paused",
    )


def _cancel_run_locked(
    run_id: str,
    state: dict[str, Any],
    *,
    lang: str,
    now: str,
    summary: str,
    reason: str,
) -> None:
    state["status"] = "cancelled"
    state["currentPhase"] = "cancelled"
    state["runtimeStatus"] = "idle"
    state["updatedAt"] = now
    state["finishedAt"] = now
    state["reason"] = reason
    state["latestMessage"] = summary
    state["currentTask"] = text_for(
        lang,
        zh="监督任务已结束，不再继续执行。",
        en="The supervised run has stopped and will not continue.",
    )
    _append_control_event_locked(
        state,
        event="run_cancelled",
        title="监督任务已终止",
        summary=summary,
        status="cancelled",
    )
    _clear_active_run_locked(run_id)
    _RUN_CONTROLLERS.pop(run_id, None)


def _checkpoint_supervised_run(run_id: str, checkpoint: dict[str, Any]) -> None:
    controller = _RUN_CONTROLLERS.get(run_id)
    if controller is None:
        return

    lang = get_web_language()
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None:
            return
        status = str(state.get("status") or "").strip().lower()
        if status in {"done", "failed", "cancelled"}:
            return
        stop_requested = bool(state.get("stopRequested"))
        pause_requested = bool(state.get("pauseRequested"))
        if stop_requested:
            now = _now_timestamp()
            _cancel_run_locked(
                run_id,
                state,
                lang=lang,
                now=now,
                summary=text_for(
                    lang,
                    zh="监督任务已在安全点终止。",
                    en="The supervised run stopped at a safe checkpoint.",
                ),
                reason=text_for(
                    lang,
                    zh="操作者请求在安全点终止这一轮监督任务。",
                    en="The operator requested this supervised run to stop at a safe checkpoint.",
                ),
            )
            terminal = True
        elif pause_requested:
            now = _now_timestamp()
            if status != "paused":
                _set_paused_locked(
                    state,
                    lang=lang,
                    now=now,
                    summary=text_for(
                        lang,
                        zh="监督任务已在安全点暂停，等待恢复。",
                        en="The supervised run paused at a safe checkpoint and is waiting to resume.",
                    ),
                )
            terminal = False
        else:
            terminal = False
            status = ""
    if terminal:
        _publish_run_snapshot(run_id, terminal=True)
        raise _SupervisedRunInterrupted()

    with controller.condition:
        while controller.pause_requested and not controller.stop_requested:
            controller.condition.wait()
        stop_requested = controller.stop_requested

    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None:
            return
        status = str(state.get("status") or "").strip().lower()
        if status in {"done", "failed", "cancelled"}:
            return
        if stop_requested or bool(state.get("stopRequested")):
            now = _now_timestamp()
            _cancel_run_locked(
                run_id,
                state,
                lang=lang,
                now=now,
                summary=text_for(
                    lang,
                    zh="监督任务已在安全点终止。",
                    en="The supervised run stopped at a safe checkpoint.",
                ),
                reason=text_for(
                    lang,
                    zh="操作者请求在安全点终止这一轮监督任务。",
                    en="The operator requested this supervised run to stop at a safe checkpoint.",
                ),
            )
            terminal = True
        elif status == "paused":
            now = _now_timestamp()
            if _has_session_started(state):
                state["status"] = "running"
                state["currentPhase"] = "running"
                state["runtimeStatus"] = "running"
            else:
                state["status"] = "queued"
                state["currentPhase"] = "queued"
                state["runtimeStatus"] = "preparing"
            state["updatedAt"] = now
            state["currentTask"] = text_for(
                lang,
                zh="监督任务已恢复，继续推进下一步。",
                en="The supervised run resumed and is continuing with the next step.",
            )
            state["latestMessage"] = text_for(
                lang,
                zh="监督任务已恢复。",
                en="The supervised run has resumed.",
            )
            terminal = False
        else:
            terminal = False
    _publish_run_snapshot(run_id, terminal=terminal)
    if terminal:
        raise _SupervisedRunInterrupted()


def _dataset_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(item.get("name") or "").strip(),
        "bundleName": str(item.get("bundle_name") or "").strip(),
        "available": bool(item.get("available")),
        "runnable": bool(item.get("runnable")),
        "effective": bool(item.get("effective")),
        "caseCount": item.get("case_count"),
        "usabilityStatus": str(item.get("usability_status") or "").strip(),
        "usabilityReason": str(item.get("usability_reason") or "").strip(),
        "officialVerifierStatus": str(item.get("official_verifier_status") or "").strip(),
        "evaluationMode": str(item.get("evaluation_mode") or "").strip(),
        "scoreLabel": str(item.get("score_label") or "").strip(),
        "officialScoreAvailable": bool(item.get("official_score_available", False)),
        "visibility": str(item.get("visibility") or "").strip(),
        "visibilityReason": str(item.get("visibility_reason") or "").strip(),
        "selectable": bool(item.get("selectable", item.get("effective"))),
        "noiseLevel": str(item.get("noise_level") or "").strip(),
        "workbenchVisible": bool(item.get("workbench_visible", True)),
        "adapterStatus": str(item.get("adapter_status") or "").strip(),
        "description": str(item.get("description") or "").strip(),
        "sourcePath": str(item.get("source_path") or "").strip(),
        "sourceExists": bool(item.get("source_exists")),
        "tags": [str(tag) for tag in list(item.get("tags") or []) if str(tag).strip()],
        "reviewRequired": bool(item.get("review_required")),
        "sourceTrack": str(item.get("source_track") or "").strip(),
        "allowedDownstreamUses": [
            str(use).strip()
            for use in list(item.get("allowed_downstream_uses") or [])
            if str(use).strip()
        ],
        "holdoutAllowed": bool(item.get("holdout_allowed", True)),
        "rawChatDirectTrainingAllowed": bool(item.get("raw_chat_direct_training_allowed", True)),
        "intakeBoundary": item.get("intake_boundary") if isinstance(item.get("intake_boundary"), dict) else {},
        "formalSupervisedEvaluationAllowed": bool(
            item.get("formal_supervised_evaluation_allowed", False)
        ),
    }


def _lifecycle_payload(lifecycle) -> dict[str, Any]:
    return {
        "status": lifecycle.status,
        "proposalId": lifecycle.proposal_id,
        "targetKey": lifecycle.target_key,
        "runtimeEffect": lifecycle.runtime_effect,
        "agentConsumption": lifecycle.agent_consumption,
        "availableActions": list(lifecycle.available_actions),
        "note": lifecycle.note,
        "error": lifecycle.error,
    }


def _coerce_dataset_limit(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise SupervisedRunValidationError("datasetLimit must be an integer or null.")
    try:
        numeric = int(value)
    except (TypeError, ValueError) as exc:
        raise SupervisedRunValidationError("datasetLimit must be an integer or null.") from exc
    if numeric <= 0:
        raise SupervisedRunValidationError("datasetLimit must be greater than zero.")
    return numeric


def _queued_summary(context: dict[str, Any]) -> str:
    source_kind = str(context.get("sourceKind") or "")
    if source_kind == "dataset":
        limit_text = context["datasetLimit"] if context["datasetLimit"] is not None else "all"
        return (
            f"source=dataset {context['datasetName']} "
            f"limit={limit_text} keep_worktree={context['keepWorktree']}"
        )
    return f"source=bundle {context['bundleName']} keep_worktree={context['keepWorktree']}"


def _event_tail_entry(event: dict[str, Any], *, timestamp: str) -> dict[str, Any]:
    item = {
        "timestamp": timestamp,
        "event": str(event.get("event") or "").strip(),
        "title": _event_title(event),
        "summary": _event_summary(event),
        "status": _event_status(event),
        "caseId": str(event.get("case_id") or ""),
        "caseIndex": _optional_int(event.get("case_index")),
        "caseTotal": _optional_int(event.get("case_total")),
        "role": str(event.get("role") or ""),
        "scenario": str(event.get("scenario") or ""),
        "mode": str(event.get("mode") or ""),
        "bundleName": str(event.get("bundle_name") or ""),
        "sessionId": str(event.get("session_id") or ""),
        "decision": str(event.get("decision") or ""),
        "reason": str(event.get("reason") or event.get("error") or ""),
        "errorType": str(event.get("error_type") or ""),
        "elapsedSeconds": _optional_float(event.get("elapsed_seconds")),
        "resultStatus": str(event.get("status") or ""),
        "agentBinding": _agent_binding_snapshot(event.get("agent_binding")),
        "mentalModelMode": str(event.get("mental_model_mode") or "").strip(),
        "mentalModelEnabled": event.get("mental_model_enabled") if "mental_model_enabled" in event else None,
    }
    phase = str(event.get("phase") or "").strip()
    if phase:
        item["phase"] = phase
    environment_preflight = event.get("environment_preflight")
    if isinstance(environment_preflight, dict):
        item["environmentPreflight"] = environment_preflight
    environment_contract_kind = str(event.get("environment_contract_kind") or "").strip()
    if environment_contract_kind:
        item["environmentContractKind"] = environment_contract_kind
    return item


def _record_supervised_progress_scene_event(run_id: str, item: dict[str, Any]) -> None:
    event_name = str(item.get("event") or "").strip() or "progress"
    phase = str(item.get("phase") or "").strip()
    event_code_suffix = f"{event_name}.{phase}" if phase else event_name
    status = str(item.get("status") or "").strip().lower()
    level = "error" if event_name == "session_error" else "info"
    outcome = (
        "cancelled"
        if event_name == "session_cancelled"
        else "failed"
        if event_name == "session_error"
        else "failed"
        if event_name == "role_finish" and status == "failed"
        else "timeout"
        if event_name == "role_finish" and status == "timeout"
        else "succeeded"
        if event_name in {"role_finish", "role_reused", "session_finish"}
        else "observed"
    )
    lifecycle = event_name in {"session_start", "session_finish", "session_error", "session_cancelled"}
    fields = {
        "runId": run_id,
        "event": event_name,
        "status": status,
        "caseId": str(item.get("caseId") or ""),
        "caseIndex": _optional_int(item.get("caseIndex")),
        "caseTotal": _optional_int(item.get("caseTotal")),
        "role": str(item.get("role") or ""),
        "scenario": str(item.get("scenario") or ""),
        "mode": str(item.get("mode") or ""),
        "bundleName": str(item.get("bundleName") or ""),
        "sessionId": str(item.get("sessionId") or ""),
        "decision": str(item.get("decision") or ""),
        "policyAction": str(item.get("policyAction") or ""),
        "reason": str(item.get("reason") or ""),
        "errorType": str(item.get("errorType") or ""),
        "elapsedSeconds": _optional_float(item.get("elapsedSeconds")),
        "agentId": str(((item.get("agentBinding") or {}).get("agentId")) or ""),
        "agentProfileId": str(((item.get("agentBinding") or {}).get("profileId")) or ""),
        "phase": phase,
        "environmentContractKind": str(item.get("environmentContractKind") or ""),
        "mentalModelMode": str(item.get("mentalModelMode") or "").strip(),
        "mentalModelEnabled": item.get("mentalModelEnabled"),
    }
    if isinstance(item.get("environmentPreflight"), dict):
        fields["environmentPreflightStatus"] = str((item.get("environmentPreflight") or {}).get("status") or "")
        fields["environmentPreflightAvailable"] = bool((item.get("environmentPreflight") or {}).get("available"))
    _record_supervised_scene_event(
        "progress",
        f"supervised_run.progress.{event_code_suffix}",
        run_id=run_id,
        message=str(item.get("summary") or item.get("title") or event_name),
        level=level,
        outcome=outcome,
        fields=fields,
        child_log_payload={
            **fields,
            "timestamp": str(item.get("timestamp") or ""),
            "title": str(item.get("title") or ""),
            "summary": str(item.get("summary") or ""),
            "agentBinding": dict(item.get("agentBinding") or {}),
            "environmentPreflight": dict(item.get("environmentPreflight") or {})
            if isinstance(item.get("environmentPreflight"), dict)
            else {},
        },
        lifecycle=lifecycle,
    )


def _event_title(event: dict[str, Any]) -> str:
    event_type = str(event.get("event") or "").strip()
    return {
        "session_start": "监督任务开始",
        "role_start": "Case 开始",
        "role_reused": "Case 复用",
        "role_finish": "Case 完成",
        "session_error": "监督任务异常",
        "session_cancelled": "监督任务终止",
        "session_finish": "监督任务结束",
    }.get(event_type, event_type or "监督任务更新")


def _event_status(event: dict[str, Any]) -> str:
    event_type = str(event.get("event") or "").strip()
    if event_type == "session_error":
        return "failed"
    if event_type == "session_cancelled":
        return "cancelled"
    if event_type == "session_finish":
        return "done"
    if event_type in {"role_finish", "role_reused"}:
        raw_status = str(event.get("status") or "").strip().lower()
        return raw_status or "running"
    return "running"


def _event_summary(event: dict[str, Any]) -> str:
    event_type = str(event.get("event") or "").strip()
    if event_type == "session_start":
        return (
            f"session={event.get('session_id')} bundle={event.get('bundle_name')} "
            f"cases={event.get('case_total')}"
        )
    if event_type == "role_start":
        return (
            f"case {event.get('case_index')}/{event.get('case_total')} "
            f"{event.get('case_id')} {event.get('role')} "
            f"scenario={event.get('scenario')} mode={event.get('mode')}"
        )
    if event_type == "role_finish":
        return (
            f"{event.get('case_id')} {event.get('role')} status={event.get('status')} "
            f"reason={event.get('reason')}"
        )
    if event_type == "role_reused":
        return (
            f"{event.get('case_id')} {event.get('role')} reused status={event.get('status')} "
            f"report={event.get('report_path') or '-'}"
        )
    if event_type == "session_error":
        return (
            f"case {event.get('case_index')}/{event.get('case_total')} "
            f"{event.get('case_id')} {event.get('role')} "
            f"{event.get('error_type')}: {event.get('error')}"
        )
    if event_type == "session_cancelled":
        return (
            f"case {event.get('case_index')}/{event.get('case_total')} "
            f"{event.get('case_id')} {event.get('role')} cancelled: {event.get('reason')}"
        )
    if event_type == "session_finish":
        return f"decision={event.get('decision')} reason={event.get('reason')}"
    if event_type == "role_live" and str(event.get("phase") or "").strip() == "environment_preflight":
        preflight = event.get("environment_preflight") if isinstance(event.get("environment_preflight"), dict) else {}
        return (
            f"{event.get('case_id')} {event.get('role')} environment_preflight "
            f"status={preflight.get('status') or '-'} available={preflight.get('available')}"
        )
    return json.dumps(event, ensure_ascii=False)


def _case_io_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    transcript_items = []
    for raw in list(event.get("transcript") or []):
        if not isinstance(raw, dict):
            continue
        transcript_items.append(
            {
                "timestamp": str(raw.get("timestamp") or "").strip(),
                "kind": str(raw.get("kind") or "").strip(),
                "label": str(raw.get("label") or "").strip(),
                "content": str(raw.get("content") or "").strip(),
                "status": str(raw.get("status") or "").strip(),
            }
        )

    payload = {
        "conversationPath": str(event.get("conversation_path") or "").strip(),
        "latestInput": str(event.get("latest_input") or "").strip(),
        "latestOutput": str(event.get("latest_output") or "").strip(),
        "latestOutputKind": str(event.get("latest_output_kind") or "").strip(),
        "latestOutputLabel": str(event.get("latest_output_label") or "").strip(),
        "updatedAt": str(event.get("updated_at") or "").strip(),
        "transcript": transcript_items,
    }

    if any(
        [
            payload["conversationPath"],
            payload["latestInput"],
            payload["latestOutput"],
            payload["latestOutputKind"],
            payload["latestOutputLabel"],
            payload["updatedAt"],
            transcript_items,
        ]
    ):
        return payload
    return None


def _append_event_locked(state: dict[str, Any], item: dict[str, Any]) -> None:
    tail = list(state.get("eventTail") or [])
    tail.append(item)
    state["eventTail"] = tail[-_EVENT_TAIL_LIMIT:]


def _optional_int(value: Any) -> int | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return numeric


def _optional_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric


def _publish_run_snapshot(run_id: str, *, terminal: bool = False) -> None:
    with _RUN_STATE_LOCK:
        current = _RUN_STATES.get(run_id)
        if current is None:
            return
        snapshot = _clone_locked(current)
        active_run_id = _ACTIVE_RUN_ID if _ACTIVE_RUN_ID else ""
    persist_manager_run_snapshot("supervised", snapshot, active_run_id=active_run_id)
    event = {
        "type": "supervised_run",
        "runId": run_id,
        "snapshot": snapshot,
        "terminal": terminal,
    }
    with _RUN_SUBSCRIBERS_LOCK:
        subscribers = list(_RUN_SUBSCRIBERS.get(run_id) or [])
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            try:
                subscriber.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                continue


def _current_active_run_locked() -> dict[str, Any] | None:
    if not _ACTIVE_RUN_ID:
        return None
    return _RUN_STATES.get(_ACTIVE_RUN_ID)


def _register_run_subscriber(run_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _RUN_SUBSCRIBERS_LOCK:
        bucket = _RUN_SUBSCRIBERS.setdefault(run_id, set())
        bucket.add(subscriber)


def _unregister_run_subscriber(run_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _RUN_SUBSCRIBERS_LOCK:
        bucket = _RUN_SUBSCRIBERS.get(run_id)
        if not bucket:
            return
        bucket.discard(subscriber)
        if not bucket:
            _RUN_SUBSCRIBERS.pop(run_id, None)


def _encode_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


_LOCAL_GET_SUPERVISED_WORKBENCH = get_supervised_workbench
_LOCAL_START_SUPERVISED_RUN = start_supervised_run
_LOCAL_RETRY_SUPERVISED_RUN = _local_retry_supervised_run
_LOCAL_GET_ACTIVE_SUPERVISED_RUN = get_active_supervised_run
_LOCAL_GET_SUPERVISED_RUN_SNAPSHOT = get_supervised_run_snapshot
_LOCAL_REQUEST_PAUSE_SUPERVISED_RUN = request_pause_supervised_run
_LOCAL_REQUEST_RESUME_SUPERVISED_RUN = request_resume_supervised_run
_LOCAL_REQUEST_STOP_SUPERVISED_RUN = request_stop_supervised_run
_LOCAL_DELETE_SUPERVISED_RUN_SNAPSHOT = delete_supervised_run_snapshot
_LOCAL_STREAM_ACTIVE_SUPERVISED_RUN_EVENTS = stream_active_supervised_run_events


def _stream_manager_supervised_events(initial_snapshot: dict[str, Any] | None = None):
    snapshot = initial_snapshot or load_manager_active_run_snapshot("supervised")
    if snapshot is None:
        raise SupervisedRunNotFoundError("No active supervised run.")

    run_id = str(snapshot.get("runId") or "").strip()
    if not run_id:
        raise SupervisedRunNotFoundError("No active supervised run.")

    last_signature = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    last_keepalive = time.monotonic()
    yield _encode_sse_event(
        "supervised_run",
        {
            "type": "supervised_run",
            "runId": run_id,
            "snapshot": snapshot,
            "terminal": False,
        },
    )

    while True:
        latest = load_manager_run_snapshot("supervised", run_id)
        if latest is not None:
            signature = json.dumps(latest, ensure_ascii=False, sort_keys=True)
            if signature != last_signature:
                last_signature = signature
                terminal = str(latest.get("status") or "").strip().lower() in {"done", "failed", "cancelled"}
                yield _encode_sse_event(
                    "supervised_run",
                    {
                        "type": "supervised_run",
                        "runId": run_id,
                        "snapshot": latest,
                        "terminal": terminal,
                    },
                )
                last_keepalive = time.monotonic()
                if terminal:
                    break
        if time.monotonic() - last_keepalive >= _RUN_STREAM_HEARTBEAT_SECONDS:
            yield ": keep-alive\n\n"
            last_keepalive = time.monotonic()
        time.sleep(1.5)


def _submit_supervised_runtime_manager_command(command_type: str, *, run_id: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _ensure_runtime_manager_daemon()
    args: dict[str, Any] = {}
    if run_id:
        args["runId"] = run_id
    if payload is not None:
        args["payload"] = payload
    command = submit_command(command_type, args=args, requested_by="web_ui")
    result = wait_for_result(command["commandId"])
    if not bool(result.get("ok")):
        _record_supervised_scene_event(
            "runtime_manager",
            f"supervised_run.manager.{command_type}.failed",
            run_id=run_id,
            message=str(result.get("message") or "Runtime manager command failed."),
            level="error",
            outcome="failed",
            fields={
                "commandType": command_type,
                "commandId": str(command.get("commandId") or ""),
                "errorType": str(result.get("errorType") or ""),
            },
            lifecycle=True,
        )
        raise _map_runtime_manager_error(
            str(result.get("message") or "Runtime manager command failed."),
            str(result.get("errorType") or ""),
        )
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else None
    if snapshot is not None and str(snapshot.get("runId") or run_id or "").strip():
        _record_supervised_scene_event(
            "runtime_manager",
            f"supervised_run.manager.{command_type}.succeeded",
            run_id=str(snapshot.get("runId") or run_id),
            message="Supervised runtime-manager command succeeded.",
            outcome="succeeded",
            fields={
                "commandType": command_type,
                "commandId": str(command.get("commandId") or ""),
                **_supervised_snapshot_event_fields(snapshot),
            },
            lifecycle=True,
        )
        return snapshot
    delete_result = result.get("deleteResult") if isinstance(result.get("deleteResult"), dict) else None
    if delete_result is not None:
        _record_supervised_scene_event(
            "runtime_manager",
            f"supervised_run.manager.{command_type}.succeeded",
            run_id=run_id,
            message="Supervised runtime-manager delete command succeeded.",
            outcome="succeeded",
            fields={
                "commandType": command_type,
                "commandId": str(command.get("commandId") or ""),
                **delete_result,
            },
            lifecycle=True,
        )
        return delete_result
    target_run_id = str(result.get("runId") or run_id or "").strip()
    loaded = load_manager_run_snapshot("supervised", target_run_id) if target_run_id else None
    if loaded is not None:
        _record_supervised_scene_event(
            "runtime_manager",
            f"supervised_run.manager.{command_type}.succeeded",
            run_id=target_run_id,
            message="Supervised runtime-manager command loaded snapshot.",
            outcome="succeeded",
            fields={
                "commandType": command_type,
                "commandId": str(command.get("commandId") or ""),
                **_supervised_snapshot_event_fields(loaded),
            },
            lifecycle=True,
        )
        return loaded
    missing_snapshot_message = "Runtime manager command completed without a supervised run snapshot."
    _record_supervised_scene_event(
        "runtime_manager",
        f"supervised_run.manager.{command_type}.failed",
        run_id=target_run_id,
        message=missing_snapshot_message,
        level="error",
        outcome="failed",
        fields={
            "commandType": command_type,
            "commandId": str(command.get("commandId") or ""),
            "errorType": "MissingRuntimeManagerSnapshot",
        },
        lifecycle=True,
    )
    raise SupervisedRunValidationError(missing_snapshot_message)


def _load_immediate_runtime_manager_command_result(command_id: str) -> dict[str, Any] | None:
    normalized = str(command_id or "").strip()
    if not normalized:
        return None
    result_path = RESULTS_DIR / f"{normalized}.json"
    if not result_path.exists():
        return None
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_runtime_manager_command_id(command_id: str) -> str:
    normalized = str(command_id or "").strip()
    if not normalized:
        raise SupervisedRunValidationError("Runtime manager command id is required.")
    if any(not (char.isalnum() or char in {"-", "_"}) for char in normalized):
        raise SupervisedRunValidationError("Runtime manager command id is invalid.")
    return normalized


def get_supervised_runtime_manager_command_status(command_id: str) -> dict[str, Any]:
    normalized = _normalize_runtime_manager_command_id(command_id)
    result = _load_immediate_runtime_manager_command_result(normalized)
    if result is None:
        return {
            "commandId": normalized,
            "accepted": False,
            "completed": False,
            "ok": None,
            "status": "pending",
            "message": "",
            "errorType": "",
        }

    raw_ok = result.get("ok")
    ok = raw_ok if isinstance(raw_ok, bool) else None
    completed = bool(result.get("completed"))
    if completed and ok is False:
        command_status = "failed"
    elif completed and ok is True:
        command_status = "succeeded"
    else:
        command_status = "pending"

    payload: dict[str, Any] = {
        "commandId": normalized,
        "accepted": bool(result.get("accepted")),
        "completed": completed,
        "ok": ok,
        "status": command_status,
        "message": str(result.get("message") or ""),
        "errorType": str(result.get("errorType") or ""),
    }
    run_id = str(result.get("runId") or "").strip()
    if run_id:
        payload["runId"] = run_id
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else None
    if snapshot is not None:
        payload["snapshot"] = _decorate_supervised_snapshot(_clone_locked(snapshot))
    return payload


def _submit_supervised_runtime_manager_command_accepted(
    command_type: str,
    *,
    run_id: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_runtime_manager_daemon()
    args: dict[str, Any] = {}
    if run_id:
        args["runId"] = run_id
    if payload is not None:
        args["payload"] = payload
    command = submit_command(command_type, args=args, requested_by="web_ui")
    command_id = str(command.get("commandId") or "").strip()

    immediate_result = _load_immediate_runtime_manager_command_result(command_id)
    if immediate_result is not None and not bool(immediate_result.get("ok")):
        _record_supervised_scene_event(
            "runtime_manager",
            f"supervised_run.manager.{command_type}.failed",
            run_id=run_id,
            message=str(immediate_result.get("message") or "Runtime manager command failed."),
            level="error",
            outcome="failed",
            fields={
                "commandType": command_type,
                "commandId": command_id,
                "errorType": str(immediate_result.get("errorType") or ""),
                "accepted": bool(immediate_result.get("accepted")),
                "completed": bool(immediate_result.get("completed")),
            },
            lifecycle=True,
        )
        raise _map_runtime_manager_error(
            str(immediate_result.get("message") or "Runtime manager command failed."),
            str(immediate_result.get("errorType") or ""),
        )

    accepted = {
        "accepted": True,
        "commandId": command_id,
        "commandType": command_type,
        "runId": str(run_id or "").strip(),
        "status": "queued",
        "summary": text_for(
            get_web_language(),
            zh="监督运行命令已提交，运行记录会稍后刷新。",
            en="Supervised run command accepted; the run record will refresh shortly.",
        ),
    }
    if immediate_result is not None:
        accepted["completed"] = bool(immediate_result.get("completed"))
    _record_supervised_scene_event(
        "runtime_manager",
        f"supervised_run.manager.{command_type}.accepted",
        run_id=run_id,
        message="Supervised runtime-manager command accepted.",
        outcome="accepted",
        fields={
            "commandType": command_type,
            "commandId": command_id,
            "accepted": True,
            "hasPayload": payload is not None,
        },
        lifecycle=True,
    )
    return accepted


def get_supervised_workbench(
    *,
    active_run: dict[str, Any] | None = None,
    active_run_loaded: bool = False,
    include_catalog: bool = True,
    saved_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        datasets = [item for item in list_dataset_choices(PROJECT_ROOT) if item.get("visibility") == "primary"] if include_catalog else []
        return {
            "defaultBundleName": default_bundle_name(),
            "savedState": saved_state if saved_state is not None else get_workbench_state_payload(project_root=PROJECT_ROOT),
            "bundles": list_available_workbench_bundles(PROJECT_ROOT) if include_catalog else [],
            "datasets": [_dataset_payload(item) for item in datasets],
            "activeRun": active_run if active_run_loaded else get_active_supervised_run(),
        }
    return _LOCAL_GET_SUPERVISED_WORKBENCH(
        active_run=active_run,
        active_run_loaded=active_run_loaded,
        include_catalog=include_catalog,
        saved_state=saved_state,
    )


def start_supervised_run(payload: dict[str, Any]) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_supervised_runtime_manager_command_accepted("start_supervised_run", payload=payload)
    snapshot = _LOCAL_START_SUPERVISED_RUN(payload)
    _record_supervised_scene_event(
        "control",
        "supervised_run.started",
        run_id=str(snapshot.get("runId") or ""),
        message="Supervised run started from web UI.",
        outcome="succeeded",
        fields=_supervised_snapshot_event_fields(snapshot),
        lifecycle=True,
    )
    return snapshot


def retry_supervised_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_supervised_runtime_manager_command("retry_supervised_run", run_id=run_id)
    snapshot = _LOCAL_RETRY_SUPERVISED_RUN(run_id)
    _record_supervised_scene_event(
        "control",
        "supervised_run.retry_started",
        run_id=str(snapshot.get("runId") or ""),
        message="Supervised run retry started; successful roles will be reused.",
        outcome="succeeded",
        fields={
            **_supervised_snapshot_event_fields(snapshot),
            "retryOfRunId": str(snapshot.get("retryOfRunId") or ""),
        },
        lifecycle=True,
    )
    return snapshot


def get_active_supervised_run() -> dict[str, Any] | None:
    if _runtime_manager_live_control_enabled():
        snapshot = load_manager_active_run_snapshot("supervised")
        if snapshot is None:
            return None
        status = str(snapshot.get("status") or "").strip().lower()
        if status in _ACTIVE_RUN_STATUSES and not _manager_control_is_current(snapshot):
            _cancel_file_only_supervised_run(str(snapshot.get("runId") or ""), lang=get_web_language())
            return None
        return _decorate_supervised_snapshot(_clone_locked(snapshot))
    return _LOCAL_GET_ACTIVE_SUPERVISED_RUN()


def get_latest_supervised_run(
    *,
    active_run: dict[str, Any] | None = None,
    active_run_loaded: bool = False,
) -> dict[str, Any] | None:
    if _runtime_manager_live_control_enabled():
        active = active_run if active_run_loaded else get_active_supervised_run()
        if active is not None:
            return _decorate_supervised_snapshot(_clone_locked(active))
        snapshot = load_manager_latest_run_snapshot("supervised")
        if snapshot is None:
            return None
        status = str(snapshot.get("status") or "").strip().lower()
        if status in _ACTIVE_RUN_STATUSES and not _manager_control_is_current(snapshot):
            return _cancel_file_only_supervised_run(str(snapshot.get("runId") or ""), lang=get_web_language())
        return _decorate_supervised_snapshot(_clone_locked(snapshot))
    active = _LOCAL_GET_ACTIVE_SUPERVISED_RUN()
    if active is not None:
        return active
    latest = load_manager_latest_run_snapshot("supervised")
    return _decorate_supervised_snapshot(_clone_locked(latest)) if isinstance(latest, dict) else None


def get_supervised_run_snapshot(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        payload = load_manager_run_snapshot("supervised", run_id)
        if payload is None:
            raise SupervisedRunNotFoundError("Supervised run not found.")
        return _decorate_supervised_snapshot(_clone_locked(payload))
    return _LOCAL_GET_SUPERVISED_RUN_SNAPSHOT(run_id)


def request_pause_supervised_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_supervised_runtime_manager_command("pause_supervised_run", run_id=run_id)
    snapshot = _LOCAL_REQUEST_PAUSE_SUPERVISED_RUN(run_id)
    _record_supervised_scene_event(
        "control",
        "supervised_run.pause_requested",
        run_id=run_id,
        message="Supervised run pause requested.",
        outcome="succeeded",
        fields=_supervised_snapshot_event_fields(snapshot),
        lifecycle=True,
    )
    return snapshot


def request_resume_supervised_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_supervised_runtime_manager_command("resume_supervised_run", run_id=run_id)
    snapshot = _LOCAL_REQUEST_RESUME_SUPERVISED_RUN(run_id)
    _record_supervised_scene_event(
        "control",
        "supervised_run.resumed",
        run_id=run_id,
        message="Supervised run resumed.",
        outcome="succeeded",
        fields=_supervised_snapshot_event_fields(snapshot),
        lifecycle=True,
    )
    return snapshot


def request_stop_supervised_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_supervised_runtime_manager_command("stop_supervised_run", run_id=run_id)
    snapshot = _LOCAL_REQUEST_STOP_SUPERVISED_RUN(run_id)
    _record_supervised_scene_event(
        "control",
        "supervised_run.stop_requested",
        run_id=run_id,
        message="Supervised run stop requested.",
        outcome="succeeded",
        fields=_supervised_snapshot_event_fields(snapshot),
        lifecycle=True,
    )
    return snapshot


def delete_supervised_run_snapshot(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_supervised_runtime_manager_command_accepted("delete_supervised_run", run_id=run_id)
    result = _LOCAL_DELETE_SUPERVISED_RUN_SNAPSHOT(run_id)
    _record_supervised_scene_event(
        "control",
        "supervised_run.snapshot.deleted",
        run_id=run_id,
        message="Supervised run snapshot deleted.",
        outcome="succeeded" if bool(result.get("deleted")) else "skipped",
        fields=result,
        lifecycle=True,
    )
    return result


def stream_active_supervised_run_events(initial_snapshot: dict[str, Any] | None = None):
    if _runtime_manager_live_control_enabled():
        return _stream_manager_supervised_events(initial_snapshot=initial_snapshot)
    return _LOCAL_STREAM_ACTIVE_SUPERVISED_RUN_EVENTS(initial_snapshot=initial_snapshot)
