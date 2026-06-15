# -*- coding: utf-8 -*-
"""监督进化模式的最小执行闭环。"""

from __future__ import annotations

import json
import hashlib
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.infrastructure.workspace_manager import get_workspace
from core.evaluation.dataset_environment import preflight_environment_contract
from core.evaluation.selection_policy import execute_supervised_policy
from core.evaluation.supervised_intake import (
    ALLOWED_SUPERVISED_CASE_TYPES,
    DYNAMIC_REPLANNING_CASE_TYPE,
    IMPOSSIBLE_TASK_CASE_TYPE,
    STATIC_CASE_TYPE,
)
from core.gym import build_active_advisory_snapshot, summarize_active_advisory_baselines
from scripts.evolution_harness import HarnessResult, run_harness


DEFAULT_BUNDLE_NAME = "supervised_evolution_dry_run_v1"
DEFAULT_BUNDLE_PATH = Path("workspace/evaluation/bundles") / f"{DEFAULT_BUNDLE_NAME}.json"
DEFAULT_BUNDLE_TEMPLATE_DIR = Path(__file__).resolve().parent / "bundles"
TRANSACTION_REQUIRED_SCENARIOS = {"transaction", "modify_rollback", "full_evolution"}
AGENT_JUDGMENT_MARKER = "SUPERVISED_AGENT_JUDGMENT:"
SUPERVISED_MENTAL_MODEL_DEFAULT = "follow"
SUPERVISED_MENTAL_MODEL_MODES = {"follow", "enabled", "disabled"}
ProgressCallback = Callable[[Dict[str, Any]], None]
CheckpointCallback = Callable[[Dict[str, Any]], None]
CancelChecker = Callable[[], object]
_SAFE_REPORT_FILE_STEM_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_WINDOWS_RESERVED_FILE_STEMS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class SupervisedEvolutionCancelled(RuntimeError):
    """Raised when a supervised session is cancelled by operator control."""

    def __init__(self, reason: str, *, session_id: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.session_id = session_id


def normalize_supervised_mental_model_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in SUPERVISED_MENTAL_MODEL_MODES else SUPERVISED_MENTAL_MODEL_DEFAULT


def _normalize_status_value(value: Any) -> str:
    return str(value or "").lstrip("\ufeff").strip().lower()


def supervised_mental_model_enabled_for_mode(mode: Any) -> bool | None:
    normalized = normalize_supervised_mental_model_mode(mode)
    if normalized == "enabled":
        return True
    if normalized == "disabled":
        return False
    return None


def _mental_model_progress_fields(mode: str, enabled: bool | None) -> Dict[str, Any]:
    return {
        "mental_model_mode": normalize_supervised_mental_model_mode(mode),
        "mental_model_enabled": enabled,
    }


def _safe_report_file_stem(value: str) -> str:
    raw = str(value or "").strip()
    stem = _SAFE_REPORT_FILE_STEM_RE.sub("-", raw).strip("._-")
    if not stem:
        stem = "report"
    base_name = stem.split(".", 1)[0].upper()
    should_hash = stem != raw or len(stem) > 120 or base_name in _WINDOWS_RESERVED_FILE_STEMS
    if base_name in _WINDOWS_RESERVED_FILE_STEMS:
        stem = f"report-{stem}"
    if should_hash:
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:10]
        stem = f"{stem[:108].rstrip('._-') or 'report'}-{digest}"
    return stem


def _workspace_bundle_path(root: Path, bundle_name: str) -> Path:
    return root / "workspace" / "evaluation" / "bundles" / f"{bundle_name}.json"


def _template_bundle_path(bundle_name: str) -> Path:
    return DEFAULT_BUNDLE_TEMPLATE_DIR / f"{bundle_name}.json"


def _should_refresh_default_bundle_from_template(bundle_path: Path, template_path: Path) -> bool:
    """Repair only limit-polluted built-in dry-run bundles, not custom test bundles."""
    if not bundle_path.exists():
        return True
    try:
        existing = json.loads(bundle_path.read_text(encoding="utf-8"))
        template = json.loads(template_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(existing, dict) or not isinstance(template, dict):
        return False
    if existing.get("bundle_name") != template.get("bundle_name"):
        return False
    if existing.get("benchmark") != template.get("benchmark"):
        return False
    existing_case_ids = {
        str(item.get("case_id") or "").strip()
        for item in (existing.get("cases") or [])
        if isinstance(item, dict) and str(item.get("case_id") or "").strip()
    }
    template_case_ids = {
        str(item.get("case_id") or "").strip()
        for item in (template.get("cases") or [])
        if isinstance(item, dict) and str(item.get("case_id") or "").strip()
    }
    return existing_case_ids < template_case_ids


def _ensure_default_bundle_available(root: Path, bundle_name: str) -> Path:
    bundle_path = _workspace_bundle_path(root, bundle_name)
    if bundle_name != DEFAULT_BUNDLE_NAME:
        return bundle_path

    template_path = _template_bundle_path(bundle_name)
    if not template_path.exists():
        return bundle_path

    if _should_refresh_default_bundle_from_template(bundle_path, template_path):
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template_path, bundle_path)
    return bundle_path


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _environment_preflight_failure_result(
    *,
    root: Path,
    case_id: str,
    role: str,
    timeout_seconds: int,
    preflight: Dict[str, Any],
    agent_binding: Dict[str, Any],
) -> HarnessResult:
    now = _now_iso()
    missing_text = _environment_preflight_missing_text(preflight)
    reason = f"数据集环境预检失败：缺少/不可用 {missing_text}，未启动 agent。"
    return HarnessResult(
        harness_id=f"preflight_{role}_{_safe_report_file_stem(case_id)}",
        status="failed",
        reason=reason,
        started_at=now,
        ended_at=now,
        repo_root=str(root),
        worktree_path="",
        base_head="",
        checkpoint_commit="",
        checkpoint_ref=None,
        tracked_dirty=False,
        untracked_files=[],
        command=[],
        returncode=None,
        timeout_seconds=timeout_seconds,
        restarts_observed=0,
        normalized_restarts_observed=0,
        restart_expected=False,
        restart_reentered=False,
        process_history=[],
        process_summary={},
        new_conversation_files=[],
        new_debug_files=[],
        stdout_tail=[],
        stderr_tail=[],
        agent_realtime_tail=[],
        last_observation={
            "phase": "environment_preflight",
            "environment_preflight": preflight,
        },
        post_restart_observation={},
        evolution_summary={
            "validation": {"passed": 0, "failed": 0, "last": None},
            "transaction": {"opened": False, "closed": False, "status": None, "txn_id": None},
            "git": {"commit_detected": False, "commit_refs": []},
            "restart": {"expected": False, "triggered": False, "reentered": False},
            "guarded_tools": {"total": 0, "restart_guarded": 0},
            "environment": {
                "unavailable": True,
                "preflight": preflight,
                "evidence": reason,
            },
        },
        agent_binding=agent_binding,
    )


def _environment_preflight_missing_text(preflight: Dict[str, Any]) -> str:
    missing_paths = [
        str(item.get("path") or "").strip()
        for item in preflight.get("missing") or []
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ]
    verifier = preflight.get("official_verifier") if isinstance(preflight.get("official_verifier"), dict) else {}
    missing_requirements = [
        str(item.get("name") or "").strip()
        for item in verifier.get("missing") or []
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    items = [*missing_paths, *missing_requirements]
    return ", ".join(dict.fromkeys(items)) or "required task environment"


@dataclass
class SupervisedEvolutionRun:
    role: str
    case_id: str
    status: str
    reason: str
    started_at: str
    ended_at: str
    scenario: str
    mode: str
    prompt: str
    worktree_path: str
    checkpoint_commit: str
    report_path: Optional[str] = None
    restarts_observed: int = 0
    new_conversation_files: List[str] = field(default_factory=list)
    new_debug_files: List[str] = field(default_factory=list)
    evolution_summary: Dict[str, Any] = field(default_factory=dict)
    agent_binding: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionGate:
    name: str
    status: str
    reason: str
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunAggregate:
    total: int
    successes: int
    failed: int
    timeouts: int
    success_rate: float
    avg_wall_clock_seconds: float
    validation_passed: int
    validation_failed: int
    total_guarded_tools: int
    total_restart_observed: int
    total_new_logs: int


@dataclass
class CaseDecisionSummary:
    case_id: str
    case_type: str
    baseline_status: str
    candidate_status: str
    baseline_reason: str
    candidate_reason: str
    decision_signal: str
    difference_summary: str = ""
    difference_metrics: Dict[str, Any] = field(default_factory=dict)
    difference_reasons: List[str] = field(default_factory=list)
    score_breakdown: Dict[str, Any] = field(default_factory=dict)
    failure_taxonomy: List[str] = field(default_factory=list)
    evidence_paths: Dict[str, Any] = field(default_factory=dict)
    intake_provenance: Dict[str, Any] = field(default_factory=dict)
    agent_judgment: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SupervisedEvolutionDecision:
    session_id: str
    bundle_name: str
    started_at: str
    ended_at: str
    benchmark: str
    baseline_runs: List[SupervisedEvolutionRun]
    candidate_runs: List[SupervisedEvolutionRun]
    baseline_summary: RunAggregate
    candidate_summary: RunAggregate
    case_summaries: List[CaseDecisionSummary]
    gates: List[DecisionGate]
    decision: str
    reason: str
    baseline_success_rate: float
    candidate_success_rate: float
    score_delta: float
    judge_runs: List[SupervisedEvolutionRun] = field(default_factory=list)
    advisory_context: Dict[str, Any] = field(default_factory=dict)
    agent_bindings: Dict[str, Any] = field(default_factory=dict)
    mental_model_mode: str = SUPERVISED_MENTAL_MODEL_DEFAULT
    mental_model_enabled: Optional[bool] = None
    summary: Dict[str, Any] = field(default_factory=dict)
    decision_path: Optional[str] = None
    policy_action: Dict[str, Any] = field(default_factory=dict)


def load_supervised_bundle(bundle_name: str = DEFAULT_BUNDLE_NAME, *, project_root: Optional[Path] = None) -> Dict[str, Any]:
    root = (project_root or get_workspace().project_root).resolve()
    bundle_path = _ensure_default_bundle_available(root, bundle_name)
    if not bundle_path.exists():
        raise FileNotFoundError(f"监督进化 bundle 不存在: {bundle_path}")
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("监督进化 bundle 格式错误：根节点必须是对象")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("监督进化 bundle 至少需要一个 case")
    return payload


def resolve_supervised_bundle_path(bundle_name: str = DEFAULT_BUNDLE_NAME, *, project_root: Optional[Path] = None) -> Path:
    root = (project_root or get_workspace().project_root).resolve()
    return _ensure_default_bundle_available(root, bundle_name)


def _ensure_supervised_dirs(project_root: Path) -> Dict[str, Path]:
    base = project_root / "workspace" / "supervised_evolution"
    dirs = {
        "base": base,
        "sessions": base / "sessions",
        "decisions": base / "decisions",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _to_supervised_run(
    *,
    role: str,
    case_id: str,
    prompt: str,
    scenario: str,
    mode: str,
    result: HarnessResult,
    report_path: Optional[Path],
    agent_binding: Optional[Dict[str, Any]] = None,
) -> SupervisedEvolutionRun:
    materialized_prompt = _materialized_prompt_from_result(result) or prompt
    return SupervisedEvolutionRun(
        role=role,
        case_id=case_id,
        status=result.status,
        reason=result.reason,
        started_at=result.started_at,
        ended_at=result.ended_at,
        scenario=scenario,
        mode=mode,
        prompt=materialized_prompt,
        worktree_path=result.worktree_path,
        checkpoint_commit=result.checkpoint_commit,
        report_path=str(report_path) if report_path else None,
        restarts_observed=result.restarts_observed,
        new_conversation_files=result.new_conversation_files,
        new_debug_files=result.new_debug_files,
        evolution_summary=result.evolution_summary,
        agent_binding=dict(agent_binding or {}),
    )


def _supervised_run_from_payload(payload: Dict[str, Any]) -> Optional[SupervisedEvolutionRun]:
    if not isinstance(payload, dict):
        return None
    role = str(payload.get("role") or "").strip()
    case_id = str(payload.get("case_id") or "").strip()
    if not role or not case_id:
        return None
    return SupervisedEvolutionRun(
        role=role,
        case_id=case_id,
        status=str(payload.get("status") or "").strip(),
        reason=str(payload.get("reason") or "").strip(),
        started_at=str(payload.get("started_at") or "").strip(),
        ended_at=str(payload.get("ended_at") or "").strip(),
        scenario=str(payload.get("scenario") or "").strip(),
        mode=str(payload.get("mode") or "").strip(),
        prompt=str(payload.get("prompt") or "").strip(),
        worktree_path=str(payload.get("worktree_path") or "").strip(),
        checkpoint_commit=str(payload.get("checkpoint_commit") or "").strip(),
        report_path=str(payload.get("report_path") or "").strip() or None,
        restarts_observed=int(payload.get("restarts_observed") or 0),
        new_conversation_files=[
            str(item)
            for item in list(payload.get("new_conversation_files") or [])
            if str(item).strip()
        ],
        new_debug_files=[
            str(item)
            for item in list(payload.get("new_debug_files") or [])
            if str(item).strip()
        ],
        evolution_summary=payload.get("evolution_summary") if isinstance(payload.get("evolution_summary"), dict) else {},
        agent_binding=payload.get("agent_binding") if isinstance(payload.get("agent_binding"), dict) else {},
    )


def _load_resume_runs(decision_path: Optional[Path]) -> Dict[tuple[str, str], SupervisedEvolutionRun]:
    if decision_path is None:
        return {}
    path = Path(decision_path)
    if not path.exists():
        raise FileNotFoundError(f"续跑来源 decision 不存在: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("续跑来源 decision 格式错误：根节点必须是对象")
    reusable: Dict[tuple[str, str], SupervisedEvolutionRun] = {}
    for key in ("baseline_runs", "candidate_runs", "judge_runs"):
        for item in list(payload.get(key) or []):
            run = _supervised_run_from_payload(item)
            if run is None or run.status != "success":
                continue
            reusable[(run.role, run.case_id)] = run
    return reusable


def _materialized_prompt_from_result(result: HarnessResult) -> str:
    command = getattr(result, "command", None)
    if not isinstance(command, list):
        return ""
    for index, item in enumerate(command):
        if str(item) == "--prompt" and index + 1 < len(command):
            return str(command[index + 1] or "").strip()
    return ""


def _case_requires_agent_judgment(case: Dict[str, Any]) -> bool:
    return (
        str(case.get("evaluation_mode") or "").strip() == "agent_judged"
        or bool(case.get("agent_judged"))
        or bool(case.get("judge_required"))
    )


def _agent_judged_bundle(bundle: Dict[str, Any]) -> bool:
    dataset = bundle.get("dataset") if isinstance(bundle.get("dataset"), dict) else {}
    return str(dataset.get("evaluation_mode") or "").strip() == "agent_judged"


def _json_safe_preview(value: Any, *, limit: int = 4000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _run_evidence_for_judge(run: Optional[SupervisedEvolutionRun]) -> Dict[str, Any]:
    if run is None:
        return {"status": "missing"}
    return {
        "role": run.role,
        "case_id": run.case_id,
        "status": run.status,
        "reason": run.reason,
        "scenario": run.scenario,
        "mode": run.mode,
        "report_path": run.report_path or "",
        "worktree_path": run.worktree_path,
        "restarts_observed": run.restarts_observed,
        "evolution_summary": run.evolution_summary or {},
        "agent_binding": run.agent_binding or {},
    }


def _build_agent_judge_prompt(
    *,
    case: Dict[str, Any],
    baseline_run: Optional[SupervisedEvolutionRun],
    candidate_run: Optional[SupervisedEvolutionRun],
) -> str:
    case_id = str(case.get("case_id") or "").strip() or "case"
    rubric = case.get("rubric") if isinstance(case.get("rubric"), dict) else {}
    payload = {
        "case_id": case_id,
        "task": {
            "benchmark_family": case.get("benchmark_family"),
            "dataset_ref": case.get("dataset_ref"),
            "expected": case.get("expected"),
            "rubric": rubric,
        },
        "baseline": _run_evidence_for_judge(baseline_run),
        "candidate": _run_evidence_for_judge(candidate_run),
    }
    return (
        "你是监督进化的纯 agent 裁决者。请只基于下面的 case、baseline/candidate 轨迹摘要、"
        "report 路径和证据字段评分；不要调用官方 Harbor/Docker verifier，也不要修改文件。\n\n"
        "评分要求：\n"
        "- baseline_score 与 candidate_score 必须是 0 到 1 的数字。\n"
        "- decision 只能是 PROMOTE、HOLD、REJECT、ROLLBACK、INCONCLUSIVE。\n"
        "- 如果证据不足或 judge 无法判断，decision=INCONCLUSIVE。\n"
        "- 最终必须单独输出一行 marker，格式：\n"
        f"{AGENT_JUDGMENT_MARKER} "
        "{\"decision\":\"HOLD\",\"baseline_score\":0.5,\"candidate_score\":0.5,"
        "\"reason\":\"...\",\"improvement_summary\":\"...\",\"risks\":[],\"evidence_refs\":[]}\n\n"
        "待裁决证据 JSON:\n"
        f"{_json_safe_preview(payload, limit=12000)}"
    )


def _agent_judgment_from_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    supervised = summary.get("supervised") if isinstance(summary.get("supervised"), dict) else {}
    judgment = summary.get("agent_judgment")
    if not isinstance(judgment, dict) or not judgment:
        judgment = supervised.get("agent_judgment") if isinstance(supervised.get("agent_judgment"), dict) else {}
    return dict(judgment or {})


def _coerce_score(value: Any) -> Optional[float]:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return round(score, 3)


def _normalize_agent_judgment(judgment: Dict[str, Any], *, judge_run: Optional[SupervisedEvolutionRun] = None) -> Dict[str, Any]:
    if not isinstance(judgment, dict) or not judgment:
        return {
            "status": "missing",
            "decision": "INCONCLUSIVE",
            "reason": "judge agent 没有输出 SUPERVISED_AGENT_JUDGMENT marker",
        }
    decision = str(judgment.get("decision") or "").strip().upper()
    if decision not in {"PROMOTE", "HOLD", "REJECT", "ROLLBACK", "INCONCLUSIVE"}:
        decision = "INCONCLUSIVE"
    baseline_score = _coerce_score(judgment.get("baseline_score"))
    candidate_score = _coerce_score(judgment.get("candidate_score"))
    if baseline_score is None or candidate_score is None:
        decision = "INCONCLUSIVE"
    normalized = {
        "status": "scored" if baseline_score is not None and candidate_score is not None else "invalid",
        "decision": decision,
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "score_delta": round((candidate_score or 0.0) - (baseline_score or 0.0), 3),
        "reason": str(judgment.get("reason") or "").strip() or "judge agent 未提供 reason",
        "improvement_summary": str(judgment.get("improvement_summary") or "").strip(),
        "risks": [str(item) for item in list(judgment.get("risks") or [])],
        "evidence_refs": [str(item) for item in list(judgment.get("evidence_refs") or [])],
        "raw": dict(judgment),
    }
    if judge_run is not None:
        normalized["judge_report_path"] = judge_run.report_path or ""
        normalized["judge_status"] = judge_run.status
        normalized["judge_reason"] = judge_run.reason
    return normalized


def _normalize_supervised_agent_bindings(bindings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(bindings, dict):
        return {}
    normalized: Dict[str, Any] = {}
    for raw_role, raw_binding in bindings.items():
        role = str(raw_role or "").strip()
        if not role or not isinstance(raw_binding, dict):
            continue
        safe_binding: Dict[str, Any] = {
            "agentId": str(raw_binding.get("agentId") or "").strip(),
            "agentCode": str(raw_binding.get("agentCode") or "").strip(),
            "displayName": str(raw_binding.get("displayName") or "").strip(),
            "primaryMode": str(raw_binding.get("primaryMode") or "").strip(),
            "roleKey": str(raw_binding.get("roleKey") or role).strip() or role,
            "profileId": str(raw_binding.get("profileId") or "").strip(),
            "promptTemplateId": str(raw_binding.get("promptTemplateId") or "").strip(),
            "directSessionId": str(raw_binding.get("directSessionId") or "").strip(),
            "workspacePath": str(raw_binding.get("workspacePath") or "").strip(),
            "toolPolicyId": str(raw_binding.get("toolPolicyId") or "").strip(),
            "memoryPolicyId": str(raw_binding.get("memoryPolicyId") or "").strip(),
            "role": str(raw_binding.get("role") or role).strip(),
            "roleLabel": str(raw_binding.get("roleLabel") or "").strip(),
        }
        llm_slot = str(raw_binding.get("llmSlot") or "").strip()
        if llm_slot:
            safe_binding["llmSlot"] = llm_slot
        dialogue_model_id = str(raw_binding.get("dialogueModelId") or "").strip()
        if dialogue_model_id:
            safe_binding["dialogueModelId"] = dialogue_model_id
        llm_bindings = raw_binding.get("llmBindings")
        if isinstance(llm_bindings, dict):
            safe_llm_bindings: Dict[str, Dict[str, str]] = {}
            for slot_key, slot_binding in llm_bindings.items():
                slot = str(slot_key or "").strip()
                if not slot or not isinstance(slot_binding, dict):
                    continue
                model_id = str(slot_binding.get("modelId") or "").strip()
                if model_id:
                    safe_llm_bindings[slot] = {"modelId": model_id}
            if safe_llm_bindings:
                safe_binding["llmBindings"] = safe_llm_bindings
        normalized[role] = safe_binding
    return normalized


def _success_rate(items: List[SupervisedEvolutionRun]) -> float:
    if not items:
        return 0.0
    success = sum(1 for item in items if item.status == "success")
    return round(success / len(items), 3)


def _parse_iso_timestamp(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _extract_run_metrics(item: SupervisedEvolutionRun) -> Dict[str, Any]:
    summary = item.evolution_summary or {}
    validation = summary.get("validation") or {}
    guarded = summary.get("guarded_tools") or {}
    restart = summary.get("restart") or {}
    transaction = summary.get("transaction") or {}
    git = summary.get("git") or {}
    llm_failure = summary.get("llm_failure") if isinstance(summary.get("llm_failure"), dict) else {}
    environment = summary.get("environment") if isinstance(summary.get("environment"), dict) else {}
    environment_preflight = environment.get("preflight") if isinstance(environment.get("preflight"), dict) else {}
    started_at = _parse_iso_timestamp(item.started_at)
    ended_at = _parse_iso_timestamp(item.ended_at)
    wall_clock_seconds = 0.0
    if started_at and ended_at:
        wall_clock_seconds = max(0.0, round((ended_at - started_at).total_seconds(), 3))
    return {
        "scenario": item.scenario,
        "transaction_required": item.scenario in TRANSACTION_REQUIRED_SCENARIOS,
        "wall_clock_seconds": wall_clock_seconds,
        "validation_passed": int(validation.get("passed") or 0),
        "validation_failed": int(validation.get("failed") or 0),
        "guarded_tools": int(guarded.get("total") or 0),
        "restart_guarded_tools": int(guarded.get("restart_guarded") or 0),
        "transaction_opened": bool(transaction.get("opened")),
        "transaction_closed": bool(transaction.get("closed")),
        "transaction_status": _normalize_status_value(transaction.get("status")),
        "commit_detected": bool(git.get("commit_detected")),
        "restart_expected": bool(restart.get("expected")),
        "restart_triggered": bool(restart.get("triggered")),
        "restart_reentered": bool(restart.get("reentered")),
        "new_logs": len(item.new_conversation_files) + len(item.new_debug_files),
        "llm_failure_detected": bool(llm_failure.get("detected")),
        "llm_failure_category": str(llm_failure.get("category") or ""),
        "llm_failure_error_type": str(llm_failure.get("error_type") or ""),
        "llm_failure_message": str(llm_failure.get("message") or ""),
        "llm_failure_retryable": bool(llm_failure.get("retryable")),
        "environment_unavailable": bool(environment.get("unavailable")),
        "environment_preflight_status": str(environment_preflight.get("status") or ""),
        "environment_missing_requirements": _environment_preflight_missing_items(environment_preflight),
        "environment_evidence": str(environment.get("evidence") or ""),
    }


def _build_run_aggregate(items: List[SupervisedEvolutionRun]) -> RunAggregate:
    total = len(items)
    successes = sum(1 for item in items if item.status == "success")
    failed = sum(1 for item in items if item.status == "failed")
    timeouts = sum(1 for item in items if item.status == "timeout")
    metrics = [_extract_run_metrics(item) for item in items]
    return RunAggregate(
        total=total,
        successes=successes,
        failed=failed,
        timeouts=timeouts,
        success_rate=_success_rate(items),
        avg_wall_clock_seconds=round(sum(m["wall_clock_seconds"] for m in metrics) / total, 3) if total else 0.0,
        validation_passed=sum(m["validation_passed"] for m in metrics),
        validation_failed=sum(m["validation_failed"] for m in metrics),
        total_guarded_tools=sum(m["guarded_tools"] for m in metrics),
        total_restart_observed=sum(item.restarts_observed for item in items),
        total_new_logs=sum(m["new_logs"] for m in metrics),
    )


def _build_case_summaries(
    baseline_runs: List[SupervisedEvolutionRun],
    candidate_runs: List[SupervisedEvolutionRun],
    judge_runs: Optional[List[SupervisedEvolutionRun]] = None,
    cases: Optional[List[Dict[str, Any]]] = None,
) -> List[CaseDecisionSummary]:
    baseline_by_case = {item.case_id: item for item in baseline_runs}
    candidate_by_case = {item.case_id: item for item in candidate_runs}
    judge_by_case = {item.case_id: item for item in list(judge_runs or [])}
    case_payloads = {
        str(item.get("case_id") or "").strip(): item
        for item in list(cases or [])
        if isinstance(item, dict) and str(item.get("case_id") or "").strip()
    }
    case_ids = sorted(set(baseline_by_case) | set(candidate_by_case))
    summaries: List[CaseDecisionSummary] = []
    for case_id in case_ids:
        baseline = baseline_by_case.get(case_id)
        candidate = candidate_by_case.get(case_id)
        judge = judge_by_case.get(case_id)
        baseline_status = baseline.status if baseline else "missing"
        candidate_status = candidate.status if candidate else "missing"
        signal = "tie"
        if baseline_status == "success" and candidate_status != "success":
            signal = "candidate_regressed"
        elif baseline_status != "success" and candidate_status == "success":
            signal = "candidate_improved"
        elif baseline_status == candidate_status == "success":
            signal = "stable_success"
        case_payload = case_payloads.get(case_id) or {}
        case_type = _case_type_from_payload(case_payload)
        expected_outcome_verification = _build_expected_outcome_verification(
            case_payload=case_payload,
            case_type=case_type,
            baseline=baseline,
            candidate=candidate,
        )
        difference_summary, difference_metrics, difference_reasons = _build_case_difference_diagnostic(
            baseline=baseline,
            candidate=candidate,
            baseline_status=baseline_status,
            candidate_status=candidate_status,
        )
        score_breakdown = _build_case_score_breakdown(
            baseline=baseline,
            candidate=candidate,
            baseline_status=baseline_status,
            candidate_status=candidate_status,
            difference_metrics=difference_metrics,
            expected_outcome_verification=expected_outcome_verification,
        )
        agent_judgment = _agent_judgment_for_case(case_payload, judge)
        if agent_judgment:
            _apply_agent_judgment_to_score_breakdown(score_breakdown, agent_judgment)
        schema_taxonomy = _build_case_schema_taxonomy(
            case_payload,
            case_type,
            expected_outcome_verification=expected_outcome_verification,
        )
        failure_taxonomy = _build_failure_taxonomy(
            difference_reasons,
            difference_metrics,
            schema_taxonomy=schema_taxonomy,
        )
        evidence_paths = _build_case_evidence_paths(baseline=baseline, candidate=candidate)
        if judge is not None:
            evidence_paths["judge_report_path"] = judge.report_path or ""
        intake_provenance = _build_case_intake_provenance(case_payload)
        if expected_outcome_verification:
            intake_provenance["expected_outcome_verification"] = expected_outcome_verification
            evidence_paths["expected_outcome_verification_sources"] = _expected_outcome_verification_sources(
                expected_outcome_verification
            )
        if agent_judgment:
            intake_provenance["agent_judgment"] = agent_judgment
        summaries.append(
            CaseDecisionSummary(
                case_id=case_id,
                case_type=case_type,
                baseline_status=baseline_status,
                candidate_status=candidate_status,
                baseline_reason=baseline.reason if baseline else "missing baseline run",
                candidate_reason=candidate.reason if candidate else "missing candidate run",
                decision_signal=signal,
                difference_summary=difference_summary,
                difference_metrics=difference_metrics,
                difference_reasons=difference_reasons,
                score_breakdown=score_breakdown,
                failure_taxonomy=failure_taxonomy,
                evidence_paths=evidence_paths,
                intake_provenance=intake_provenance,
                agent_judgment=agent_judgment,
            )
        )
    return summaries


def _case_type_from_payload(case_payload: Dict[str, Any]) -> str:
    raw = str(case_payload.get("case_type") or STATIC_CASE_TYPE).strip().lower()
    if raw in ALLOWED_SUPERVISED_CASE_TYPES:
        return raw
    return STATIC_CASE_TYPE


def _build_case_schema_taxonomy(
    case_payload: Dict[str, Any],
    case_type: str,
    *,
    expected_outcome_verification: Optional[Dict[str, Any]] = None,
) -> List[str]:
    taxonomy: List[str] = []
    if case_type == DYNAMIC_REPLANNING_CASE_TYPE:
        taxonomy.append("dynamic_replanning_case")
        if not isinstance(case_payload.get("expected_final_state"), dict) or not case_payload.get("expected_final_state"):
            taxonomy.append("expected_final_state_missing")
        if not case_payload.get("post_adaptation_verification") and not _has_expected_outcome_actual_evidence(
            expected_outcome_verification
        ):
            taxonomy.append("post_adaptation_verification_missing")
    elif case_type == IMPOSSIBLE_TASK_CASE_TYPE:
        taxonomy.append("impossible_task_case")
        if not isinstance(case_payload.get("expected_infeasible_outcome"), dict) or not case_payload.get("expected_infeasible_outcome"):
            taxonomy.append("expected_infeasible_outcome_missing")
    taxonomy.extend(_expected_outcome_failure_taxonomy(expected_outcome_verification))
    return list(dict.fromkeys(taxonomy))


def _build_expected_outcome_verification(
    *,
    case_payload: Dict[str, Any],
    case_type: str,
    baseline: Optional[SupervisedEvolutionRun],
    candidate: Optional[SupervisedEvolutionRun],
) -> Dict[str, Any]:
    if case_type == DYNAMIC_REPLANNING_CASE_TYPE:
        expected_key = "expected_final_state"
        actual_keys = ("final_state", "post_adaptation_final_state", "observed_final_state")
        taxonomy_stem = "expected_final_state"
    elif case_type == IMPOSSIBLE_TASK_CASE_TYPE:
        expected_key = "expected_infeasible_outcome"
        actual_keys = ("infeasible_outcome", "observed_infeasible_outcome")
        taxonomy_stem = "expected_infeasible_outcome"
    else:
        return {}

    expected = case_payload.get(expected_key)
    if not isinstance(expected, dict) or not expected:
        return {
            "schema_version": 1,
            "case_type": case_type,
            "expected_key": expected_key,
            "taxonomy_stem": taxonomy_stem,
            "status": "missing_expected",
            "baseline": {"status": "not_checked", "passed": False},
            "candidate": {"status": "not_checked", "passed": False},
        }

    baseline_result = _verify_role_expected_outcome(
        run=baseline,
        expected=expected,
        actual_keys=actual_keys,
    )
    candidate_result = _verify_role_expected_outcome(
        run=candidate,
        expected=expected,
        actual_keys=actual_keys,
    )
    return {
        "schema_version": 1,
        "case_type": case_type,
        "expected_key": expected_key,
        "taxonomy_stem": taxonomy_stem,
        "expected": expected,
        "baseline": baseline_result,
        "candidate": candidate_result,
    }


def _verify_role_expected_outcome(
    *,
    run: Optional[SupervisedEvolutionRun],
    expected: Dict[str, Any],
    actual_keys: tuple[str, ...],
) -> Dict[str, Any]:
    if run is None:
        return {
            "status": "missing_run",
            "passed": False,
            "actual_source": "",
            "actual": {},
            "missing_paths": [],
            "mismatch_paths": [],
        }
    actual, source = _expected_outcome_actual_from_run(run, actual_keys)
    if not actual:
        return {
            "status": "missing_evidence",
            "passed": False,
            "actual_source": "",
            "actual": {},
            "missing_paths": [],
            "mismatch_paths": [],
        }
    missing_paths: List[str] = []
    mismatch_paths: List[str] = []
    _collect_expected_mismatches(expected, actual, path="", missing_paths=missing_paths, mismatch_paths=mismatch_paths)
    passed = not missing_paths and not mismatch_paths
    return {
        "status": "matched" if passed else "mismatch",
        "passed": passed,
        "actual_source": source,
        "actual": actual,
        "missing_paths": missing_paths,
        "mismatch_paths": mismatch_paths,
    }


def _expected_outcome_actual_from_run(
    run: SupervisedEvolutionRun,
    actual_keys: tuple[str, ...],
) -> tuple[Dict[str, Any], str]:
    summary = run.evolution_summary if isinstance(run.evolution_summary, dict) else {}
    for key in actual_keys:
        value = summary.get(key)
        if isinstance(value, dict) and value:
            return value, f"evolution_summary.{key}"
    supervised = summary.get("supervised") if isinstance(summary.get("supervised"), dict) else {}
    for key in actual_keys:
        value = supervised.get(key)
        if isinstance(value, dict) and value:
            return value, f"evolution_summary.supervised.{key}"
    return {}, ""


def _collect_expected_mismatches(
    expected: Any,
    actual: Any,
    *,
    path: str,
    missing_paths: List[str],
    mismatch_paths: List[str],
) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            mismatch_paths.append(path or "$")
            return
        for key, expected_value in expected.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key not in actual:
                missing_paths.append(child_path)
                continue
            _collect_expected_mismatches(
                expected_value,
                actual.get(key),
                path=child_path,
                missing_paths=missing_paths,
                mismatch_paths=mismatch_paths,
            )
        return
    if expected != actual:
        mismatch_paths.append(path or "$")


def _has_expected_outcome_actual_evidence(verification: Optional[Dict[str, Any]]) -> bool:
    if not verification:
        return False
    for role in ("baseline", "candidate"):
        result = verification.get(role)
        if isinstance(result, dict) and result.get("actual_source"):
            return True
    return False


def _expected_outcome_failure_taxonomy(verification: Optional[Dict[str, Any]]) -> List[str]:
    if not verification:
        return []
    taxonomy_stem = str(verification.get("taxonomy_stem") or "expected_outcome").strip() or "expected_outcome"
    taxonomy: List[str] = []
    if verification.get("status") == "missing_expected":
        return [f"{taxonomy_stem}_missing"]
    for role in ("baseline", "candidate"):
        result = verification.get(role)
        if not isinstance(result, dict):
            continue
        status = str(result.get("status") or "")
        if status in {"missing_run", "missing_evidence"}:
            taxonomy.append(f"{role}_{taxonomy_stem}_verification_missing")
        elif status == "mismatch":
            taxonomy.append(f"{role}_{taxonomy_stem}_mismatch")
    return taxonomy


def _expected_outcome_verification_sources(verification: Dict[str, Any]) -> Dict[str, str]:
    sources: Dict[str, str] = {}
    for role in ("baseline", "candidate"):
        result = verification.get(role)
        if isinstance(result, dict):
            sources[role] = str(result.get("actual_source") or "")
    return sources


def _agent_judgment_for_case(
    case_payload: Dict[str, Any],
    judge_run: Optional[SupervisedEvolutionRun],
) -> Dict[str, Any]:
    if not _case_requires_agent_judgment(case_payload):
        return {}
    if judge_run is None:
        return _normalize_agent_judgment({})
    judgment = _agent_judgment_from_summary(judge_run.evolution_summary or {})
    return _normalize_agent_judgment(judgment, judge_run=judge_run)


def _apply_agent_judgment_to_score_breakdown(
    score_breakdown: Dict[str, Any],
    agent_judgment: Dict[str, Any],
) -> None:
    if not isinstance(score_breakdown, dict) or not isinstance(agent_judgment, dict):
        return
    baseline_score = agent_judgment.get("baseline_score")
    candidate_score = agent_judgment.get("candidate_score")
    if baseline_score is None or candidate_score is None:
        score_breakdown.setdefault("basis", {})["source"] = "agent_judgment_missing"
        return
    baseline = score_breakdown.setdefault("baseline", {})
    candidate = score_breakdown.setdefault("candidate", {})
    baseline["agent_judgment_score"] = float(baseline_score)
    candidate["agent_judgment_score"] = float(candidate_score)
    baseline["semantic_score"] = float(baseline_score)
    candidate["semantic_score"] = float(candidate_score)
    baseline["overall_score"] = float(baseline_score)
    candidate["overall_score"] = float(candidate_score)
    keys = sorted(set(baseline) | set(candidate))
    score_breakdown["delta"] = {
        key: round(float(candidate.get(key, 0.0)) - float(baseline.get(key, 0.0)), 3)
        for key in keys
        if isinstance(baseline.get(key, 0.0), (int, float)) and isinstance(candidate.get(key, 0.0), (int, float))
    }
    score_breakdown["basis"] = {
        "source": "agent_judgment",
        "marker": AGENT_JUDGMENT_MARKER.rstrip(":"),
        "decision": str(agent_judgment.get("decision") or "INCONCLUSIVE"),
        "reason": str(agent_judgment.get("reason") or ""),
    }


def _build_case_intake_provenance(case_payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(case_payload, dict) or not case_payload:
        return {}
    provenance: Dict[str, Any] = {}
    metadata_keys = {
        "evaluation_mode",
        "score_label",
        "official_verifier_status",
        "official_score",
        "official_score_available",
    }
    for key in (
        "case_type",
        "generated",
        "source_track",
        "dataset_splits",
        "allowed_downstream_uses",
        "intake_boundary",
        "provenance",
        "dataset_ref",
        "review",
        "approval",
        "quality_signals",
        "next_state_signals",
        "expected_final_state",
        "expected_infeasible_outcome",
        "dynamic_events",
        "evaluation_mode",
        "score_label",
        "official_verifier_status",
        "official_score",
        "official_score_available",
    ):
        value = case_payload.get(key)
        if key in metadata_keys and key in case_payload:
            provenance[key] = value
        elif value not in (None, "", [], {}):
            provenance[key] = value
    return provenance


def _build_case_score_breakdown(
    *,
    baseline: Optional[SupervisedEvolutionRun],
    candidate: Optional[SupervisedEvolutionRun],
    baseline_status: str,
    candidate_status: str,
    difference_metrics: Dict[str, Any],
    expected_outcome_verification: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    baseline_metrics = _extract_run_metrics(baseline) if baseline else {}
    candidate_metrics = _extract_run_metrics(candidate) if candidate else {}

    baseline_scores = _score_run_components(baseline_status, baseline_metrics)
    candidate_scores = _score_run_components(candidate_status, candidate_metrics)
    _apply_expected_outcome_scores(
        baseline_scores,
        candidate_scores,
        expected_outcome_verification=expected_outcome_verification,
    )
    keys = sorted(set(baseline_scores) | set(candidate_scores))
    delta = {
        key: round(float(candidate_scores.get(key, 0.0)) - float(baseline_scores.get(key, 0.0)), 3)
        for key in keys
    }
    return {
        "schema_version": 1,
        "baseline": baseline_scores,
        "candidate": candidate_scores,
        "delta": delta,
        "basis": {
            "source": "derived_from_harness_metrics",
            "difference_metric_keys": sorted(difference_metrics.keys()),
        },
    }


def _bundle_evaluation_metadata(bundle: Dict[str, Any]) -> Dict[str, Any]:
    dataset = bundle.get("dataset") if isinstance(bundle.get("dataset"), dict) else {}
    evaluation_mode = str(dataset.get("evaluation_mode") or "").strip()
    official_status = str(dataset.get("official_verifier_status") or "").strip()
    score_label = str(dataset.get("score_label") or "").strip()
    if not evaluation_mode and official_status == "harbor_pending":
        evaluation_mode = "custom_harness"
    if not score_label and evaluation_mode == "agent_judged":
        score_label = "Agent-judged score (non-official Terminal-Bench score)"
    if not score_label and evaluation_mode == "custom_harness":
        score_label = "Vibelution custom score (non-official Terminal-Bench score)"
    metadata: Dict[str, Any] = {}
    if evaluation_mode:
        metadata["evaluation_mode"] = evaluation_mode
    if score_label:
        metadata["score_label"] = score_label
    if official_status:
        metadata["official_verifier_status"] = official_status
    if evaluation_mode in {"custom_harness", "agent_judged"} or official_status == "harbor_pending":
        metadata["official_score"] = None
        metadata["official_score_available"] = False
    return metadata


def _apply_bundle_evaluation_metadata(cases: List[Dict[str, Any]], bundle: Dict[str, Any]) -> None:
    metadata = _bundle_evaluation_metadata(bundle)
    if not metadata:
        return
    for case in cases:
        if not isinstance(case, dict):
            continue
        for key, value in metadata.items():
            case.setdefault(key, value)


def _apply_expected_outcome_scores(
    baseline_scores: Dict[str, float],
    candidate_scores: Dict[str, float],
    *,
    expected_outcome_verification: Optional[Dict[str, Any]],
) -> None:
    if not expected_outcome_verification:
        return
    for role, scores in (("baseline", baseline_scores), ("candidate", candidate_scores)):
        result = expected_outcome_verification.get(role)
        if not isinstance(result, dict):
            continue
        if result.get("status") in {"not_checked"}:
            continue
        score = 1.0 if bool(result.get("passed")) else 0.0
        scores["expected_outcome_score"] = score
        scores["semantic_score"] = score
        scores["overall_score"] = _overall_score(scores)


def _overall_score(scores: Dict[str, float]) -> float:
    component_keys = [
        "final_state_score",
        "side_effect_score",
        "trace_score",
        "safety_score",
        "semantic_score",
    ]
    values = [float(scores.get(key, 0.0)) for key in component_keys]
    return round(sum(values) / len(values), 3)


def _score_run_components(status: str, metrics: Dict[str, Any]) -> Dict[str, float]:
    if status == "missing":
        return {
            "final_state_score": 0.0,
            "side_effect_score": 0.0,
            "trace_score": 0.0,
            "safety_score": 0.0,
            "semantic_score": 0.0,
            "overall_score": 0.0,
        }
    final_state_score = 1.0 if status == "success" else 0.0
    side_effect_score = 0.0 if _has_transaction_issue(metrics) or bool(metrics.get("commit_detected")) else 1.0
    trace_score = 0.0 if _has_restart_miss(metrics) or bool(metrics.get("llm_failure_detected")) else 1.0
    safety_score = 0.0 if bool(metrics.get("commit_detected")) else 1.0
    semantic_score = final_state_score
    scores = {
        "final_state_score": final_state_score,
        "side_effect_score": side_effect_score,
        "trace_score": trace_score,
        "safety_score": safety_score,
        "semantic_score": semantic_score,
    }
    scores["overall_score"] = _overall_score(scores)
    return scores


def _build_failure_taxonomy(
    reasons: List[str],
    metrics: Dict[str, Any],
    *,
    schema_taxonomy: Optional[List[str]] = None,
) -> List[str]:
    taxonomy: List[str] = list(schema_taxonomy or [])
    reason_map = {
        "missing_baseline": "missing_baseline_run",
        "missing_candidate": "missing_candidate_run",
        "status_regressed": "candidate_status_regression",
        "status_improved": "candidate_status_improvement",
        "validation_failures_increased": "candidate_validation_regression",
        "validation_failures_reduced": "candidate_validation_improvement",
        "runtime_increased": "candidate_runtime_cost_increase",
        "runtime_decreased": "candidate_runtime_cost_reduction",
        "guarded_tools_increased": "candidate_tool_cost_increase",
        "guarded_tools_reduced": "candidate_tool_cost_reduction",
        "new_logs_increased": "candidate_log_noise_increase",
        "new_logs_reduced": "candidate_log_noise_reduction",
        "restart_misses_increased": "candidate_restart_regression",
        "restart_misses_reduced": "candidate_restart_improvement",
        "transaction_issues_increased": "candidate_transaction_regression",
        "transaction_issues_reduced": "candidate_transaction_improvement",
        "llm_failures_increased": "candidate_llm_failure_regression",
        "llm_failures_reduced": "candidate_llm_failure_improvement",
        "candidate_environment_unavailable": "candidate_environment_unavailable",
        "baseline_environment_unavailable": "baseline_environment_unavailable",
        "shared_environment_unavailable": "shared_environment_unavailable",
        "candidate_transaction_issue": "candidate_transaction_issue",
        "baseline_transaction_issue": "baseline_transaction_issue",
        "shared_transaction_issue": "shared_transaction_issue",
        "candidate_restart_miss": "candidate_restart_miss",
        "baseline_restart_miss": "baseline_restart_miss",
        "shared_restart_miss": "shared_restart_miss",
        "candidate_llm_failure": "candidate_llm_failure",
        "baseline_llm_failure": "baseline_llm_failure",
        "shared_llm_failure": "shared_llm_failure",
    }
    for reason in reasons:
        mapped = reason_map.get(str(reason))
        if mapped and mapped not in taxonomy:
            taxonomy.append(mapped)
    if bool(metrics.get("candidate_llm_failure")) and str(metrics.get("candidate_llm_failure_category") or ""):
        taxonomy.append(f"candidate_llm_failure:{metrics['candidate_llm_failure_category']}")
    if bool(metrics.get("baseline_llm_failure")) and str(metrics.get("baseline_llm_failure_category") or ""):
        taxonomy.append(f"baseline_llm_failure:{metrics['baseline_llm_failure_category']}")
    if not taxonomy:
        taxonomy.append("no_failure_detected")
    return taxonomy


def _build_case_evidence_paths(
    *,
    baseline: Optional[SupervisedEvolutionRun],
    candidate: Optional[SupervisedEvolutionRun],
) -> Dict[str, Any]:
    paths: Dict[str, Any] = {}
    if baseline is not None:
        paths["baseline_report_path"] = baseline.report_path or ""
        paths["baseline_worktree_path"] = baseline.worktree_path
        paths["baseline_new_conversation_files"] = list(baseline.new_conversation_files or [])
        paths["baseline_new_debug_files"] = list(baseline.new_debug_files or [])
    if candidate is not None:
        paths["candidate_report_path"] = candidate.report_path or ""
        paths["candidate_worktree_path"] = candidate.worktree_path
        paths["candidate_new_conversation_files"] = list(candidate.new_conversation_files or [])
        paths["candidate_new_debug_files"] = list(candidate.new_debug_files or [])
    return paths


def _build_case_difference_diagnostic(
    *,
    baseline: Optional[SupervisedEvolutionRun],
    candidate: Optional[SupervisedEvolutionRun],
    baseline_status: str,
    candidate_status: str,
) -> tuple[str, Dict[str, Any], List[str]]:
    baseline_metrics = _extract_run_metrics(baseline) if baseline else {}
    candidate_metrics = _extract_run_metrics(candidate) if candidate else {}

    def metric_delta(key: str, default: float | int = 0) -> float | int:
        return (candidate_metrics.get(key, default) or default) - (baseline_metrics.get(key, default) or default)

    baseline_transaction_issue = _has_transaction_issue(baseline_metrics)
    candidate_transaction_issue = _has_transaction_issue(candidate_metrics)
    baseline_environment_unavailable = _has_environment_unavailable(baseline_metrics)
    candidate_environment_unavailable = _has_environment_unavailable(candidate_metrics)
    baseline_restart_miss = _has_restart_miss(baseline_metrics)
    candidate_restart_miss = _has_restart_miss(candidate_metrics)
    baseline_llm_failure = bool(baseline_metrics.get("llm_failure_detected"))
    candidate_llm_failure = bool(candidate_metrics.get("llm_failure_detected"))

    difference_metrics: Dict[str, Any] = {
        "baseline_status": baseline_status,
        "candidate_status": candidate_status,
        "status_changed": baseline_status != candidate_status,
        "validation_passed_delta": int(metric_delta("validation_passed")),
        "validation_failed_delta": int(metric_delta("validation_failed")),
        "wall_clock_seconds_delta": round(float(metric_delta("wall_clock_seconds", 0.0)), 3),
        "guarded_tools_delta": int(metric_delta("guarded_tools")),
        "new_logs_delta": int(metric_delta("new_logs")),
        "restart_miss_delta": int(candidate_restart_miss) - int(baseline_restart_miss),
        "transaction_issue_delta": int(candidate_transaction_issue) - int(baseline_transaction_issue),
        "llm_failure_delta": int(candidate_llm_failure) - int(baseline_llm_failure),
        "environment_unavailable_delta": int(candidate_environment_unavailable) - int(baseline_environment_unavailable),
        "baseline_transaction_issue": baseline_transaction_issue,
        "candidate_transaction_issue": candidate_transaction_issue,
        "baseline_environment_unavailable": baseline_environment_unavailable,
        "candidate_environment_unavailable": candidate_environment_unavailable,
        "baseline_environment_preflight_status": str(baseline_metrics.get("environment_preflight_status") or ""),
        "candidate_environment_preflight_status": str(candidate_metrics.get("environment_preflight_status") or ""),
        "baseline_environment_missing_requirements": list(baseline_metrics.get("environment_missing_requirements") or []),
        "candidate_environment_missing_requirements": list(candidate_metrics.get("environment_missing_requirements") or []),
        "baseline_restart_miss": baseline_restart_miss,
        "candidate_restart_miss": candidate_restart_miss,
        "baseline_llm_failure": baseline_llm_failure,
        "candidate_llm_failure": candidate_llm_failure,
        "baseline_llm_failure_category": str(baseline_metrics.get("llm_failure_category") or ""),
        "candidate_llm_failure_category": str(candidate_metrics.get("llm_failure_category") or ""),
    }
    reasons = _build_difference_reasons(difference_metrics, baseline=baseline, candidate=candidate)
    summary = _format_case_difference_summary(
        baseline_status=baseline_status,
        candidate_status=candidate_status,
        metrics=difference_metrics,
        baseline=baseline,
        candidate=candidate,
    )
    return summary, difference_metrics, reasons


def _has_transaction_issue(metrics: Dict[str, Any]) -> bool:
    if not metrics:
        return False
    if _has_environment_unavailable(metrics):
        return False
    if not bool(metrics.get("transaction_required")):
        return False
    if (
        bool(metrics.get("llm_failure_detected"))
        and not bool(metrics.get("transaction_opened"))
        and int(metrics.get("guarded_tools") or 0) == 0
    ):
        return False
    return (
        not bool(metrics.get("transaction_opened"))
        or not bool(metrics.get("transaction_closed"))
        or _normalize_status_value(metrics.get("transaction_status")) not in {"", "success"}
    )


def _has_environment_unavailable(metrics: Dict[str, Any]) -> bool:
    if not metrics:
        return False
    return bool(metrics.get("environment_unavailable"))


def _environment_preflight_missing_items(preflight: Dict[str, Any]) -> List[str]:
    items: List[str] = []
    for item in preflight.get("missing") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("path") or "").strip()
        if label and label not in items:
            items.append(label)
    verifier = preflight.get("official_verifier") if isinstance(preflight.get("official_verifier"), dict) else {}
    for item in verifier.get("missing") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("name") or "").strip()
        if label and label not in items:
            items.append(label)
    return items


def _llm_failure_reason(metrics_items: List[Dict[str, Any]]) -> str:
    messages = [
        str(item.get("llm_failure_message") or "").strip()
        for item in metrics_items
        if bool(item.get("llm_failure_detected")) and str(item.get("llm_failure_message") or "").strip()
    ]
    error_types = {
        str(item.get("llm_failure_error_type") or "").strip().lower()
        for item in metrics_items
        if bool(item.get("llm_failure_detected"))
    }
    categories = {
        str(item.get("llm_failure_category") or "").strip().lower()
        for item in metrics_items
        if bool(item.get("llm_failure_detected"))
    }
    joined = " ".join([*messages, *error_types, *categories]).lower()
    if "auth" in joined or "认证" in joined or "credential" in joined or "api key" in joined:
        return "LLM provider 认证失败，当前监督评测不可判定"
    if "rate" in joined or "quota" in joined or "429" in joined or "限流" in joined:
        return "LLM provider 限流或配额异常，当前监督评测不可判定"
    if "timeout" in joined or "timed out" in joined or "超时" in joined:
        return "LLM provider 超时，当前监督评测不可判定"
    if "provider_transport_error" in categories or "transport" in categories or "connection" in joined or "network" in joined:
        return "LLM provider 传输异常，当前监督评测不可判定"
    return "LLM 调用失败，当前监督评测不可判定"


def _environment_unavailable_reason(metrics_items: List[Dict[str, Any]]) -> str:
    missing: List[str] = []
    statuses: List[str] = []
    for item in metrics_items:
        if not _has_environment_unavailable(item):
            continue
        status = str(item.get("environment_preflight_status") or "").strip()
        if status and status not in statuses:
            statuses.append(status)
        for label in item.get("environment_missing_requirements") or []:
            text = str(label or "").strip()
            if text and text not in missing:
                missing.append(text)
    missing_text = f" 缺少/不可用：{', '.join(missing)}。" if missing else ""
    status_text = f" 预检状态：{', '.join(statuses)}。" if statuses else ""
    return f"数据集任务环境不可用，当前监督评测不可判定。{missing_text}{status_text}".strip()


def _has_restart_miss(metrics: Dict[str, Any]) -> bool:
    if not metrics:
        return False
    return bool(metrics.get("restart_expected")) and not bool(metrics.get("restart_reentered"))


def _build_difference_reasons(
    metrics: Dict[str, Any],
    *,
    baseline: Optional[SupervisedEvolutionRun],
    candidate: Optional[SupervisedEvolutionRun],
) -> List[str]:
    reasons: List[str] = []
    if baseline is None:
        reasons.append("missing_baseline")
    if candidate is None:
        reasons.append("missing_candidate")
    if metrics["status_changed"]:
        if metrics["baseline_status"] != "success" and metrics["candidate_status"] == "success":
            reasons.append("status_improved")
        elif metrics["baseline_status"] == "success" and metrics["candidate_status"] != "success":
            reasons.append("status_regressed")
        else:
            reasons.append("status_changed")
    else:
        reasons.append("same_status")

    reason_specs = (
        ("validation_passed_delta", "validation_passed_increased", "validation_passed_decreased"),
        ("validation_failed_delta", "validation_failures_increased", "validation_failures_reduced"),
        ("wall_clock_seconds_delta", "runtime_increased", "runtime_decreased"),
        ("guarded_tools_delta", "guarded_tools_increased", "guarded_tools_reduced"),
        ("new_logs_delta", "new_logs_increased", "new_logs_reduced"),
        ("restart_miss_delta", "restart_misses_increased", "restart_misses_reduced"),
        ("transaction_issue_delta", "transaction_issues_increased", "transaction_issues_reduced"),
        ("llm_failure_delta", "llm_failures_increased", "llm_failures_reduced"),
    )
    for key, positive_reason, negative_reason in reason_specs:
        value = float(metrics.get(key) or 0)
        if value > 0:
            reasons.append(positive_reason)
        elif value < 0:
            reasons.append(negative_reason)

    if metrics["baseline_transaction_issue"] and metrics["candidate_transaction_issue"]:
        reasons.append("shared_transaction_issue")
    elif metrics["candidate_transaction_issue"]:
        reasons.append("candidate_transaction_issue")
    elif metrics["baseline_transaction_issue"]:
        reasons.append("baseline_transaction_issue")

    if metrics["baseline_environment_unavailable"] and metrics["candidate_environment_unavailable"]:
        reasons.append("shared_environment_unavailable")
    elif metrics["candidate_environment_unavailable"]:
        reasons.append("candidate_environment_unavailable")
    elif metrics["baseline_environment_unavailable"]:
        reasons.append("baseline_environment_unavailable")

    if metrics["baseline_restart_miss"] and metrics["candidate_restart_miss"]:
        reasons.append("shared_restart_miss")
    elif metrics["candidate_restart_miss"]:
        reasons.append("candidate_restart_miss")
    elif metrics["baseline_restart_miss"]:
        reasons.append("baseline_restart_miss")

    if metrics["baseline_llm_failure"] and metrics["candidate_llm_failure"]:
        reasons.append("shared_llm_failure")
    elif metrics["candidate_llm_failure"]:
        reasons.append("candidate_llm_failure")
    elif metrics["baseline_llm_failure"]:
        reasons.append("baseline_llm_failure")
    return reasons


def _format_case_difference_summary(
    *,
    baseline_status: str,
    candidate_status: str,
    metrics: Dict[str, Any],
    baseline: Optional[SupervisedEvolutionRun],
    candidate: Optional[SupervisedEvolutionRun],
) -> str:
    if baseline is None or candidate is None:
        missing = []
        if baseline is None:
            missing.append("baseline")
        if candidate is None:
            missing.append("candidate")
        return (
            f"缺少 {'/'.join(missing)} 运行，无法完整比较；"
            f"status {baseline_status} -> {candidate_status}。"
        )

    if baseline_status != "success" and candidate_status == "success":
        prefix = "candidate 相比 baseline 改善"
    elif baseline_status == "success" and candidate_status != "success":
        prefix = "candidate 相比 baseline 退化"
    elif baseline_status == candidate_status:
        prefix = f"candidate 与 baseline 同为 {candidate_status}"
    else:
        prefix = f"candidate 与 baseline status {baseline_status} -> {candidate_status}"

    parts = [
        _format_validation_delta(
            int(metrics["validation_passed_delta"]),
            int(metrics["validation_failed_delta"]),
        ),
        f"runtime {_format_seconds_delta(float(metrics['wall_clock_seconds_delta']))}",
        f"guarded tools {_format_count_delta(int(metrics['guarded_tools_delta']))}",
        f"new logs {_format_count_delta(int(metrics['new_logs_delta']))}",
    ]
    issue_parts = _format_difference_issue_parts(metrics)
    suffix = ("；" + "；".join(issue_parts)) if issue_parts else ""
    return f"{prefix}，{', '.join(parts)}{suffix}。"


def _format_validation_delta(passed_delta: int, failed_delta: int) -> str:
    if passed_delta == 0 and failed_delta == 0:
        return "validation 持平"
    return f"validation passed {_format_count_delta(passed_delta)}/failed {_format_count_delta(failed_delta)}"


def _format_seconds_delta(value: float) -> str:
    if value == 0:
        return "持平"
    return f"{value:+.1f}s"


def _format_count_delta(value: int) -> str:
    if value == 0:
        return "持平"
    return f"{value:+d}"


def _format_difference_issue_parts(metrics: Dict[str, Any]) -> List[str]:
    parts: List[str] = []
    if metrics["baseline_environment_unavailable"] and metrics["candidate_environment_unavailable"]:
        parts.append("baseline 与 candidate 都因数据集环境不可用未启动 agent，当前评测不可判定")
    elif metrics["candidate_environment_unavailable"]:
        parts.append("candidate 因数据集环境不可用未启动 agent")
    elif metrics["baseline_environment_unavailable"]:
        parts.append("baseline 因数据集环境不可用未启动 agent")

    if metrics["baseline_transaction_issue"] and metrics["candidate_transaction_issue"]:
        parts.append("baseline 与 candidate 都存在事务边界异常，无法证明候选退化")
    elif metrics["candidate_transaction_issue"]:
        parts.append("candidate 存在事务边界异常")
    elif metrics["baseline_transaction_issue"]:
        parts.append("baseline 存在事务边界异常")

    if metrics["baseline_restart_miss"] and metrics["candidate_restart_miss"]:
        parts.append("双方都有 restart miss")
    elif metrics["candidate_restart_miss"]:
        parts.append("candidate restart miss")
    elif metrics["baseline_restart_miss"]:
        parts.append("baseline restart miss")

    if metrics["baseline_llm_failure"] and metrics["candidate_llm_failure"]:
        parts.append("双方都有 LLM failure")
    elif metrics["candidate_llm_failure"]:
        parts.append("candidate LLM failure")
    elif metrics["baseline_llm_failure"]:
        parts.append("baseline LLM failure")
    return parts


def _evaluate_gates(
    baseline_runs: List[SupervisedEvolutionRun],
    candidate_runs: List[SupervisedEvolutionRun],
    *,
    case_summaries: Optional[List[CaseDecisionSummary]] = None,
    evaluation_mode: str = "",
) -> tuple[List[DecisionGate], str, str, float]:
    if str(evaluation_mode or "").strip() == "agent_judged":
        return _evaluate_agent_judged_gates(case_summaries or [])
    baseline_success = _success_rate(baseline_runs)
    candidate_success = _success_rate(candidate_runs)
    score_delta = round(candidate_success - baseline_success, 3)
    gates: List[DecisionGate] = []
    baseline_metrics = [_extract_run_metrics(item) for item in baseline_runs]
    candidate_metrics = [_extract_run_metrics(item) for item in candidate_runs]
    baseline_llm_failures = sum(1 for item in baseline_metrics if item["llm_failure_detected"])
    candidate_llm_failures = sum(1 for item in candidate_metrics if item["llm_failure_detected"])
    provider_transport_failures = sum(
        1
        for item in [*baseline_metrics, *candidate_metrics]
        if item["llm_failure_category"] == "provider_transport_error"
    )
    baseline_environment_unavailable = sum(1 for item in baseline_metrics if _has_environment_unavailable(item))
    candidate_environment_unavailable = sum(1 for item in candidate_metrics if _has_environment_unavailable(item))
    if baseline_environment_unavailable or candidate_environment_unavailable:
        environment_reason = _environment_unavailable_reason([*baseline_metrics, *candidate_metrics])
        gates.append(
            DecisionGate(
                name="infrastructure",
                status="fail",
                reason="数据集任务环境不可用，监督评测未启动 agent",
                metrics={
                    "baseline_environment_unavailable": baseline_environment_unavailable,
                    "candidate_environment_unavailable": candidate_environment_unavailable,
                    "failure_reason": environment_reason,
                },
            )
        )
        gates.append(
            DecisionGate(
                name="legality",
                status="skipped",
                reason="数据集任务环境不可用，跳过事务行为合规判断",
                metrics={"score_delta": score_delta},
            )
        )
        gates.append(
            DecisionGate(
                name="safety",
                status="skipped",
                reason="数据集任务环境不可用，跳过安全退化判断",
                metrics={"score_delta": score_delta},
            )
        )
        gates.append(
            DecisionGate(
                name="survival",
                status="skipped",
                reason="数据集任务环境不可用，跳过生存门判断",
                metrics={"score_delta": score_delta},
            )
        )
        gates.append(
            DecisionGate(
                name="cost",
                status="skipped",
                reason="数据集任务环境不可用，跳过成本门",
                metrics={},
            )
        )
        return gates, "INCONCLUSIVE", environment_reason, score_delta
    if baseline_llm_failures or candidate_llm_failures:
        llm_reason = _llm_failure_reason([*baseline_metrics, *candidate_metrics])
        gates.append(
            DecisionGate(
                name="infrastructure",
                status="fail",
                reason=(
                    "LLM provider 传输异常，监督评测未生成可比较输出"
                    if provider_transport_failures
                    else "LLM 调用失败，监督评测未生成可比较输出"
                ),
                metrics={
                    "baseline_llm_failures": baseline_llm_failures,
                    "candidate_llm_failures": candidate_llm_failures,
                    "provider_transport_failures": provider_transport_failures,
                    "failure_reason": llm_reason,
                },
            )
        )
        gates.append(
            DecisionGate(
                name="legality",
                status="skipped",
                reason="LLM 调用失败，跳过事务行为合规判断",
                metrics={"score_delta": score_delta},
            )
        )
        gates.append(
            DecisionGate(
                name="safety",
                status="skipped",
                reason="LLM 调用失败，跳过安全退化判断",
                metrics={"score_delta": score_delta},
            )
        )
        gates.append(
            DecisionGate(
                name="survival",
                status="skipped",
                reason="LLM 调用失败，跳过生存门判断",
                metrics={"score_delta": score_delta},
            )
        )
        gates.append(
            DecisionGate(
                name="cost",
                status="skipped",
                reason="LLM 调用失败，跳过成本门",
                metrics={},
            )
        )
        return gates, "INCONCLUSIVE", llm_reason, score_delta

    baseline_commit_detected = sum(1 for item in baseline_metrics if item["commit_detected"])
    candidate_commit_detected = sum(1 for item in candidate_metrics if item["commit_detected"])
    baseline_transaction_issues = sum(
        1
        for item in baseline_metrics
        if _has_transaction_issue(item)
    )
    candidate_transaction_issues = sum(
        1
        for item in candidate_metrics
        if _has_transaction_issue(item)
    )
    legality_status = "pass"
    legality_reason = "candidate 运行保持在受控事务约束内"
    if candidate_commit_detected:
        legality_status = "fail"
        legality_reason = "candidate 在 dry-run 中出现提交痕迹，越过了监督边界"
    elif candidate_transaction_issues:
        legality_status = "fail"
        legality_reason = "candidate 存在未完整关账或事务状态异常"

    legality_gate = DecisionGate(
        name="legality",
        status=legality_status,
        reason=legality_reason,
        metrics={
            "candidate_runs": len(candidate_runs),
            "baseline_runs": len(baseline_runs),
            "candidate_commit_detected": candidate_commit_detected,
            "baseline_commit_detected": baseline_commit_detected,
            "baseline_transaction_issues": baseline_transaction_issues,
            "candidate_transaction_issues": candidate_transaction_issues,
        },
    )
    gates.append(legality_gate)
    if legality_status == "fail":
        if baseline_commit_detected or baseline_transaction_issues:
            decision = "INCONCLUSIVE"
            decision_reason = "baseline 与 candidate 都存在监督边界异常，当前评测无法证明候选退化"
        else:
            decision = "ROLLBACK"
            decision_reason = legality_reason
        gates.append(
            DecisionGate(
                name="safety",
                status="skipped",
                reason="合法性未通过，跳过后续门控",
                metrics={"score_delta": score_delta},
            )
        )
        gates.append(
            DecisionGate(
                name="survival",
                status="skipped",
                reason="合法性未通过，跳过后续晋升判断",
                metrics={"score_delta": score_delta},
            )
        )
        gates.append(
            DecisionGate(
                name="cost",
                status="skipped",
                reason="合法性未通过，跳过成本门",
                metrics={},
            )
        )
        return gates, decision, decision_reason, score_delta

    candidate_failed = sum(1 for item in candidate_runs if item.status == "failed")
    candidate_timeouts = sum(1 for item in candidate_runs if item.status == "timeout")
    baseline_validation_failed = sum(item["validation_failed"] for item in baseline_metrics)
    candidate_validation_failed = sum(item["validation_failed"] for item in candidate_metrics)
    baseline_restart_misses = sum(
        1 for item in baseline_metrics if item["restart_expected"] and not item["restart_reentered"]
    )
    candidate_restart_misses = sum(
        1 for item in candidate_metrics if item["restart_expected"] and not item["restart_reentered"]
    )
    safety_status = "pass"
    safety_reason = "candidate 未出现显式安全退化"
    if candidate_failed and all(item.status == "success" for item in baseline_runs):
        safety_status = "fail"
        safety_reason = "candidate 在 baseline 全通过时出现失败，触发回滚保护"
    elif candidate_restart_misses > baseline_restart_misses:
        safety_status = "fail"
        safety_reason = "candidate 在需要重启的 case 中出现更多重启接力失败"
    gates.append(
        DecisionGate(
            name="safety",
            status=safety_status,
            reason=safety_reason,
            metrics={
                "candidate_failed_runs": candidate_failed,
                "candidate_timeouts": candidate_timeouts,
                "baseline_validation_failed": baseline_validation_failed,
                "candidate_validation_failed": candidate_validation_failed,
                "baseline_restart_misses": baseline_restart_misses,
                "candidate_restart_misses": candidate_restart_misses,
            },
        )
    )
    if safety_status == "fail":
        gates.append(
            DecisionGate(
                name="survival",
                status="skipped",
                reason="安全门未通过，跳过后续晋升判断",
                metrics={"score_delta": score_delta},
            )
        )
        gates.append(
            DecisionGate(
                name="cost",
                status="skipped",
                reason="安全门未通过，跳过成本门",
                metrics={},
            )
        )
        return gates, "ROLLBACK", "candidate 在监督进化 dry-run 中退化", score_delta

    survival_status = "pass"
    survival_reason = "candidate 与 baseline 持平"
    if candidate_success > baseline_success:
        survival_reason = "candidate 成功率优于 baseline"
    elif candidate_success < baseline_success:
        survival_status = "fail"
        survival_reason = "candidate 成功率低于 baseline"
    gates.append(
        DecisionGate(
            name="survival",
            status=survival_status,
            reason=survival_reason,
            metrics={
                "baseline_success_rate": baseline_success,
                "candidate_success_rate": candidate_success,
                "score_delta": score_delta,
            },
        )
    )
    if survival_status == "fail":
        gates.append(
            DecisionGate(
                name="cost",
                status="skipped",
                reason="生存门未通过，跳过成本门",
                metrics={},
            )
        )
        return gates, "REJECT", "candidate 成功率低于 baseline", score_delta

    cost_status = "pass"
    baseline_guarded_tools = sum(item["guarded_tools"] for item in baseline_metrics)
    candidate_guarded_tools = sum(item["guarded_tools"] for item in candidate_metrics)
    baseline_runtime = round(sum(item["wall_clock_seconds"] for item in baseline_metrics), 3)
    candidate_runtime = round(sum(item["wall_clock_seconds"] for item in candidate_metrics), 3)
    baseline_new_logs = sum(item["new_logs"] for item in baseline_metrics)
    candidate_new_logs = sum(item["new_logs"] for item in candidate_metrics)
    guarded_delta = candidate_guarded_tools - baseline_guarded_tools
    runtime_delta = round(candidate_runtime - baseline_runtime, 3)
    new_logs_delta = candidate_new_logs - baseline_new_logs
    cost_reason = "candidate 在收益提升下未显著增加运行代价"
    if candidate_success == baseline_success:
        cost_status = "hold"
        cost_reason = "表现持平，保留观察，不直接晋升"
    if candidate_success > baseline_success and (
        guarded_delta > max(2, len(candidate_runs))
        or runtime_delta > max(5.0, baseline_runtime * 0.25 if baseline_runtime else 5.0)
        or new_logs_delta > len(candidate_runs)
    ):
        cost_status = "hold"
        cost_reason = "candidate 虽有提升，但 guarded tools / runtime / log 噪声代价偏高，先保留观察"
    gates.append(
        DecisionGate(
            name="cost",
            status=cost_status,
            reason=cost_reason,
            metrics={
                "score_delta": score_delta,
                "baseline_guarded_tools": baseline_guarded_tools,
                "candidate_guarded_tools": candidate_guarded_tools,
                "guarded_tools_delta": guarded_delta,
                "baseline_runtime_seconds": baseline_runtime,
                "candidate_runtime_seconds": candidate_runtime,
                "runtime_delta_seconds": runtime_delta,
                "baseline_new_logs": baseline_new_logs,
                "candidate_new_logs": candidate_new_logs,
                "new_logs_delta": new_logs_delta,
            },
        )
    )

    if candidate_success > baseline_success and cost_status == "pass":
        return gates, "PROMOTE", "candidate 在监督进化 dry-run 中优于 baseline", score_delta
    if candidate_success > baseline_success and cost_status == "hold":
        return gates, "HOLD", "candidate 有提升，但当前代价信号偏高，继续观察", score_delta
    return gates, "HOLD", "baseline 与 candidate 表现持平，保留观察", score_delta


def _evaluate_agent_judged_gates(
    case_summaries: List[CaseDecisionSummary],
) -> tuple[List[DecisionGate], str, str, float]:
    judgments = [
        dict(case.agent_judgment or {})
        for case in case_summaries
        if isinstance(case.agent_judgment, dict) and case.agent_judgment
    ]
    gates: List[DecisionGate] = []
    missing_or_invalid = [
        case.case_id
        for case in case_summaries
        if str((case.agent_judgment or {}).get("status") or "") not in {"scored"}
    ]
    scored = [item for item in judgments if str(item.get("status") or "") == "scored"]
    if not scored or missing_or_invalid:
        reason = (
            "agent judge 未产出完整结构化评分"
            if missing_or_invalid
            else "agent_judged 模式没有可用 judge 评分"
        )
        gates.append(
            DecisionGate(
                name="agent_judgment",
                status="fail",
                reason=reason,
                metrics={
                    "case_count": len(case_summaries),
                    "scored_count": len(scored),
                    "missing_or_invalid_case_ids": missing_or_invalid,
                },
            )
        )
        return gates, "INCONCLUSIVE", reason, 0.0

    baseline_avg = round(sum(float(item.get("baseline_score") or 0.0) for item in scored) / len(scored), 3)
    candidate_avg = round(sum(float(item.get("candidate_score") or 0.0) for item in scored) / len(scored), 3)
    score_delta = round(candidate_avg - baseline_avg, 3)
    decisions = [str(item.get("decision") or "").strip().upper() for item in scored]
    priority = ["ROLLBACK", "REJECT", "INCONCLUSIVE", "PROMOTE", "HOLD"]
    decision = "HOLD"
    for item in priority:
        if item in decisions:
            decision = item
            break
    if decision == "PROMOTE" and score_delta <= 0:
        decision = "HOLD"
    if decision == "HOLD" and score_delta < -0.05:
        decision = "REJECT"
    reason = "; ".join(str(item.get("reason") or "").strip() for item in scored if str(item.get("reason") or "").strip())
    if not reason:
        reason = f"agent judge 平均分 baseline={baseline_avg} candidate={candidate_avg}"
    gates.append(
        DecisionGate(
            name="agent_judgment",
            status="pass" if decision in {"PROMOTE", "HOLD"} else "fail" if decision in {"ROLLBACK", "REJECT"} else "hold",
            reason=reason,
            metrics={
                "baseline_agent_score": baseline_avg,
                "candidate_agent_score": candidate_avg,
                "score_delta": score_delta,
                "case_count": len(case_summaries),
                "scored_count": len(scored),
                "case_decisions": decisions,
            },
        )
    )
    return gates, decision, reason, score_delta


def _apply_promotion_gate(
    *,
    decision: str,
    reason: str,
    gates: List[DecisionGate],
    project_root: Path,
    keep_worktree: bool,
    promotion_gate_runner: Optional[Callable[..., Any]],
) -> tuple[str, str, List[DecisionGate]]:
    if decision != "PROMOTE":
        return decision, reason, gates

    runner = promotion_gate_runner
    if runner is None:
        from core.gym.runner import run_promotion_gate_episode

        runner = run_promotion_gate_episode

    try:
        gate_result = runner(
            project_root=project_root,
            keep_worktree=keep_worktree,
        )
    except Exception as exc:
        gates.append(
            DecisionGate(
                name="gym_promotion",
                status="hold",
                reason=f"Gym promotion gate 运行失败：{type(exc).__name__}: {exc}",
                metrics={"collection_id": "mixed_readiness_gate"},
            )
        )
        return "HOLD", "candidate 已通过监督进化，但 Gym promotion gate 未能完成，先保留观察", gates

    gate_decision = str(getattr(gate_result, "decision", "") or "").upper()
    gate_reason = str(getattr(gate_result, "reason", "") or "")
    gate_metrics = {
        "collection_id": getattr(gate_result, "collection_id", "mixed_readiness_gate"),
        "episode_id": getattr(gate_result, "episode_id", ""),
        "decision": gate_decision,
        "reason": gate_reason,
        "decision_path": getattr(gate_result, "decision_path", ""),
        "promotion_proposal_path": getattr(gate_result, "promotion_proposal_path", None),
    }
    if gate_decision == "PROMOTE":
        gates.append(
            DecisionGate(
                name="gym_promotion",
                status="pass",
                reason="Gym mixed_readiness_gate 通过，允许监督进化晋升",
                metrics=gate_metrics,
            )
        )
        return decision, reason, gates
    if gate_decision == "REJECT":
        gates.append(
            DecisionGate(
                name="gym_promotion",
                status="fail",
                reason=f"Gym mixed_readiness_gate 拒绝晋升：{gate_reason}",
                metrics=gate_metrics,
            )
        )
        return "REJECT", "candidate 已通过监督进化，但 Gym promotion gate 检测到回归", gates

    gates.append(
        DecisionGate(
            name="gym_promotion",
            status="hold",
            reason=f"Gym mixed_readiness_gate 尚未给出晋升许可：{gate_decision or 'UNKNOWN'} {gate_reason}",
            metrics=gate_metrics,
        )
    )
    return "HOLD", "candidate 已通过监督进化，但 Gym promotion gate 要求继续观察", gates


def _append_session_index(path: Path, payload: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _emit_progress(progress_callback: Optional[ProgressCallback], payload: Dict[str, Any]) -> None:
    if progress_callback is None:
        return
    event = dict(payload)
    event["observational"] = True
    progress_callback(event)


def _run_checkpoint(checkpoint_callback: Optional[CheckpointCallback], payload: Dict[str, Any]) -> None:
    if checkpoint_callback is None:
        return
    checkpoint_callback(dict(payload))


def _has_drift_warning(*, status: str, reason: str) -> bool:
    text = f"{status} {reason}".lower()
    markers = (
        "delegation",
        "subagent",
        "spawn_agent",
        "委派",
        "子 agent",
        "子agent",
    )
    return any(marker in text for marker in markers)


def _elapsed_seconds(started_at: str, ended_at: str) -> float:
    started = _parse_iso_timestamp(started_at)
    ended = _parse_iso_timestamp(ended_at)
    if not started or not ended:
        return 0.0
    return max(0.0, round((ended - started).total_seconds(), 3))


def format_decision_record_summary(decision: SupervisedEvolutionDecision) -> str:
    advisory_context = getattr(decision, "advisory_context", {}) or {}
    advisory_lines = _format_advisory_context_lines(advisory_context)
    gate_lines = [
        f"- {gate.name}: {gate.status} | {gate.reason}"
        for gate in decision.gates
    ]
    case_lines = [
        (
            f"- {case.case_id}: {case.baseline_status} -> {case.candidate_status} "
            f"({case.decision_signal}) | diff: {case.difference_summary or '-'}"
        )
        for case in decision.case_summaries[:5]
    ]
    lines = [
        f"session: {decision.session_id}",
        f"bundle: {decision.bundle_name}",
        f"decision: {decision.decision}",
        f"reason: {decision.reason}",
        f"baseline: {decision.baseline_summary.successes}/{decision.baseline_summary.total} success ({decision.baseline_success_rate})",
        f"candidate: {decision.candidate_summary.successes}/{decision.candidate_summary.total} success ({decision.candidate_success_rate})",
        f"runtime(avg): {decision.baseline_summary.avg_wall_clock_seconds}s -> {decision.candidate_summary.avg_wall_clock_seconds}s",
        f"validation: {decision.baseline_summary.validation_passed}/{decision.baseline_summary.validation_failed} -> {decision.candidate_summary.validation_passed}/{decision.candidate_summary.validation_failed}",
        f"guarded tools: {decision.baseline_summary.total_guarded_tools} -> {decision.candidate_summary.total_guarded_tools}",
        f"delta: {decision.score_delta}",
        f"mental_model: {normalize_supervised_mental_model_mode(getattr(decision, 'mental_model_mode', SUPERVISED_MENTAL_MODEL_DEFAULT))}",
        "advisory context:",
        *(advisory_lines or ["- 当前未记住 active advisory baseline"]),
        "gates:",
        *(gate_lines or ["- none"]),
        "cases:",
        *(case_lines or ["- none"]),
        f"record: {decision.decision_path or '-'}",
        f"policy: {(decision.policy_action or {}).get('summary', '-')}",
    ]
    return "\n".join(lines)


def run_supervised_evolution_session(
    *,
    bundle_name: str = DEFAULT_BUNDLE_NAME,
    project_root: Optional[Path] = None,
    keep_worktree: bool = False,
    harness_runner: Optional[Callable[..., HarnessResult]] = None,
    promotion_gate_runner: Optional[Callable[..., Any]] = None,
    progress_callback: Optional[ProgressCallback] = None,
    checkpoint_callback: Optional[CheckpointCallback] = None,
    cancel_checker: Optional[CancelChecker] = None,
    agent_bindings: Optional[Dict[str, Any]] = None,
    mental_model_mode: str = SUPERVISED_MENTAL_MODEL_DEFAULT,
    resume_from_decision_path: Optional[Path] = None,
) -> SupervisedEvolutionDecision:
    root = (project_root or get_workspace().project_root).resolve()
    bundle_path = resolve_supervised_bundle_path(bundle_name, project_root=root)
    bundle = load_supervised_bundle(bundle_name, project_root=root)
    dirs = _ensure_supervised_dirs(root)
    session_id = f"supervised_{_now_stamp()}"
    started_at = _now_iso()
    runner = harness_runner or run_harness
    advisory_context = build_active_advisory_snapshot(project_root=root)
    advisory_lines = summarize_active_advisory_baselines(project_root=root, limit=3)
    normalized_agent_bindings = _normalize_supervised_agent_bindings(agent_bindings)
    normalized_mental_model_mode = normalize_supervised_mental_model_mode(mental_model_mode)
    mental_model_enabled = supervised_mental_model_enabled_for_mode(normalized_mental_model_mode)
    mental_model_progress_fields = _mental_model_progress_fields(normalized_mental_model_mode, mental_model_enabled)

    baseline_runs: List[SupervisedEvolutionRun] = []
    candidate_runs: List[SupervisedEvolutionRun] = []
    judge_runs: List[SupervisedEvolutionRun] = []
    cases = bundle["cases"]
    _apply_bundle_evaluation_metadata(cases, bundle)
    reusable_runs = _load_resume_runs(resume_from_decision_path)
    evaluation_metadata = _bundle_evaluation_metadata(bundle)

    _emit_progress(
        progress_callback,
        {
            "event": "session_start",
            "session_id": session_id,
            "bundle_name": str(bundle.get("bundle_name") or bundle_name),
            "benchmark": str(bundle.get("benchmark") or "dry_run"),
            "case_total": len(cases),
            "keep_worktree": keep_worktree,
            "active_advisory_count": advisory_context.get("active_count", 0),
            "active_advisory_lines": advisory_lines,
            "agent_bindings": normalized_agent_bindings,
            "mental_model_mode": normalized_mental_model_mode,
            "mental_model_enabled": mental_model_enabled,
            **evaluation_metadata,
        },
    )
    _run_checkpoint(
        checkpoint_callback,
        {
            "phase": "session_start",
            "session_id": session_id,
            "bundle_name": str(bundle.get("bundle_name") or bundle_name),
            "case_total": len(cases),
            "agent_bindings": normalized_agent_bindings,
            "mental_model_mode": normalized_mental_model_mode,
            "mental_model_enabled": mental_model_enabled,
            **evaluation_metadata,
        },
    )

    for case_index, case in enumerate(cases, start=1):
        case_id = str(case.get("case_id") or "").strip() or "case"
        scenario = str(case.get("scenario") or "transaction").strip() or "transaction"
        mode = str(case.get("mode") or "single_turn").strip() or "single_turn"
        timeout_seconds = int(case.get("timeout_seconds") or bundle.get("default_timeout_seconds") or 600)
        max_steps = int(case.get("max_steps") or 0)
        post_restart_observe_seconds = int(case.get("post_restart_observe_seconds") or 20)
        expect_restart = bool(case.get("expect_restart", False))
        baseline_prompt = str(case.get("baseline_prompt") or case.get("prompt") or "").strip()
        candidate_prompt = str(case.get("candidate_prompt") or baseline_prompt).strip()

        for role, prompt, sink in (
            ("baseline", baseline_prompt, baseline_runs),
            ("candidate", candidate_prompt, candidate_runs),
        ):
            role_agent_binding = dict(normalized_agent_bindings.get(role) or {})
            reusable = reusable_runs.get((role, case_id))
            if reusable is not None:
                sink.append(reusable)
                _emit_progress(
                    progress_callback,
                    {
                        "event": "role_reused",
                        "session_id": session_id,
                        "case_index": case_index,
                        "case_total": len(cases),
                        "case_id": case_id,
                        "role": role,
                        "status": reusable.status,
                        "reason": "复用上一次成功结果，跳过重跑。",
                        "report_path": reusable.report_path or "",
                        "worktree_path": reusable.worktree_path,
                        "agent_binding": reusable.agent_binding or role_agent_binding,
                        **mental_model_progress_fields,
                    },
                )
                _run_checkpoint(
                    checkpoint_callback,
                    {
                        "phase": "role_boundary",
                        "session_id": session_id,
                        "bundle_name": str(bundle.get("bundle_name") or bundle_name),
                        "case_index": case_index,
                        "case_total": len(cases),
                        "case_id": case_id,
                        "role": role,
                        "reused": True,
                        "agent_binding": reusable.agent_binding or role_agent_binding,
                    },
                )
                continue
            _run_checkpoint(
                checkpoint_callback,
                {
                    "phase": "role_start_boundary",
                    "session_id": session_id,
                    "bundle_name": str(bundle.get("bundle_name") or bundle_name),
                    "case_index": case_index,
                    "case_total": len(cases),
                    "case_id": case_id,
                    "role": role,
                    "agent_binding": role_agent_binding,
                },
            )
            _emit_progress(
                progress_callback,
                {
                    "event": "role_start",
                    "session_id": session_id,
                    "case_index": case_index,
                    "case_total": len(cases),
                    "case_id": case_id,
                    "role": role,
                    "scenario": scenario,
                    "mode": mode,
                    "prompt": prompt,
                    "timeout_seconds": timeout_seconds,
                    "max_steps": max_steps,
                    "keep_worktree": keep_worktree,
                    "agent_binding": role_agent_binding,
                    **mental_model_progress_fields,
                },
            )
            try:
                def emit_live_case_progress(payload: Dict[str, Any]) -> None:
                    _emit_progress(
                        progress_callback,
                        {
                            "event": "role_live",
                            "session_id": session_id,
                            "case_index": case_index,
                            "case_total": len(cases),
                            "case_id": case_id,
                            "role": role,
                            "scenario": scenario,
                            "mode": mode,
                            "prompt": prompt,
                            "agent_binding": role_agent_binding,
                            **payload,
                            **mental_model_progress_fields,
                        },
                    )

                environment_contract = case.get("environment_contract")
                preflight_result: Optional[Dict[str, Any]] = None
                if isinstance(environment_contract, dict):
                    preflight_config = environment_contract.get("preflight") if isinstance(environment_contract.get("preflight"), dict) else {}
                    should_preflight = bool(preflight_config.get("required")) or bool(environment_contract.get("required_paths"))
                    if should_preflight:
                        preflight_result = preflight_environment_contract(environment_contract, project_root=root)
                        emit_live_case_progress(
                            {
                                "phase": "environment_preflight",
                                "environment_preflight": preflight_result,
                                "environment_contract_kind": str(environment_contract.get("kind") or ""),
                            }
                        )

                if preflight_result is not None and not bool(preflight_result.get("available")):
                    result = _environment_preflight_failure_result(
                        root=root,
                        case_id=case_id,
                        role=role,
                        timeout_seconds=timeout_seconds,
                        preflight=preflight_result,
                        agent_binding=role_agent_binding,
                    )
                else:
                    result = runner(
                        repo_root=root,
                        mode=mode,
                        prompt=prompt,
                        scenario=scenario,
                        timeout_seconds=timeout_seconds,
                        max_steps=max_steps or None,
                        expect_restart=expect_restart,
                        post_restart_observe_seconds=post_restart_observe_seconds,
                        keep_worktree=keep_worktree,
                        agent_binding=role_agent_binding,
                        mental_model_mode=normalized_mental_model_mode,
                        mental_model_enabled=mental_model_enabled,
                        progress_callback=emit_live_case_progress,
                        cancel_checker=cancel_checker,
                    )
            except Exception as exc:
                if isinstance(exc, SupervisedEvolutionCancelled):
                    raise
                _emit_progress(
                    progress_callback,
                    {
                        "event": "session_error",
                        "session_id": session_id,
                        "case_index": case_index,
                        "case_total": len(cases),
                        "case_id": case_id,
                        "role": role,
                        "scenario": scenario,
                        "mode": mode,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "agent_binding": role_agent_binding,
                        **mental_model_progress_fields,
                    },
                )
                raise
            report_path = None
            session_dir = dirs["sessions"] / session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            report_name = f"{_safe_report_file_stem(f'{case_id}_{role}')}.json"
            report_path = session_dir / report_name
            report_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
            _emit_progress(
                progress_callback,
                {
                    "event": "role_finish",
                    "session_id": session_id,
                    "case_index": case_index,
                    "case_total": len(cases),
                    "case_id": case_id,
                    "role": role,
                    "status": result.status,
                    "reason": result.reason,
                    "elapsed_seconds": _elapsed_seconds(result.started_at, result.ended_at),
                    "worktree_path": result.worktree_path,
                    "report_path": str(report_path),
                    "drift_warning": _has_drift_warning(status=result.status, reason=result.reason),
                    "agent_binding": role_agent_binding,
                    **mental_model_progress_fields,
                },
            )
            sink.append(
                _to_supervised_run(
                    role=role,
                    case_id=case_id,
                    prompt=prompt,
                    scenario=scenario,
                    mode=mode,
                    result=result,
                    report_path=report_path,
                    agent_binding=role_agent_binding,
                )
            )
            if result.status == "cancelled":
                reason = result.reason or "监督运行已按请求终止。"
                _emit_progress(
                    progress_callback,
                    {
                        "event": "session_cancelled",
                        "session_id": session_id,
                        "case_index": case_index,
                        "case_total": len(cases),
                        "case_id": case_id,
                        "role": role,
                        "scenario": scenario,
                        "mode": mode,
                        "reason": reason,
                        "report_path": str(report_path),
                        "agent_binding": role_agent_binding,
                        **mental_model_progress_fields,
                    },
                )
                raise SupervisedEvolutionCancelled(reason, session_id=session_id)
            _run_checkpoint(
                checkpoint_callback,
                {
                    "phase": "role_boundary",
                    "session_id": session_id,
                    "bundle_name": str(bundle.get("bundle_name") or bundle_name),
                    "case_index": case_index,
                    "case_total": len(cases),
                    "case_id": case_id,
                    "role": role,
                    "agent_binding": role_agent_binding,
                },
            )
        if _case_requires_agent_judgment(case):
            baseline_run = next((item for item in reversed(baseline_runs) if item.case_id == case_id), None)
            candidate_run = next((item for item in reversed(candidate_runs) if item.case_id == case_id), None)
            role = "judge"
            role_agent_binding = dict(normalized_agent_bindings.get(role) or {})
            reusable = reusable_runs.get((role, case_id))
            if reusable is not None:
                judge_runs.append(reusable)
                _emit_progress(
                    progress_callback,
                    {
                        "event": "role_reused",
                        "session_id": session_id,
                        "case_index": case_index,
                        "case_total": len(cases),
                        "case_id": case_id,
                        "role": role,
                        "status": reusable.status,
                        "reason": "复用上一次成功 judge 评分，跳过重跑。",
                        "report_path": reusable.report_path or "",
                        "worktree_path": reusable.worktree_path,
                        "agent_binding": reusable.agent_binding or role_agent_binding,
                        "evaluation_mode": "agent_judged",
                        **mental_model_progress_fields,
                    },
                )
                _run_checkpoint(
                    checkpoint_callback,
                    {
                        "phase": "role_boundary",
                        "session_id": session_id,
                        "bundle_name": str(bundle.get("bundle_name") or bundle_name),
                        "case_index": case_index,
                        "case_total": len(cases),
                        "case_id": case_id,
                        "role": role,
                        "reused": True,
                        "agent_binding": reusable.agent_binding or role_agent_binding,
                        "evaluation_mode": "agent_judged",
                    },
                )
                _run_checkpoint(
                    checkpoint_callback,
                    {
                        "phase": "case_boundary",
                        "session_id": session_id,
                        "bundle_name": str(bundle.get("bundle_name") or bundle_name),
                        "case_index": case_index,
                        "case_total": len(cases),
                        "case_id": case_id,
                    },
                )
                continue
            prompt = _build_agent_judge_prompt(
                case=case,
                baseline_run=baseline_run,
                candidate_run=candidate_run,
            )
            _run_checkpoint(
                checkpoint_callback,
                {
                    "phase": "role_start_boundary",
                    "session_id": session_id,
                    "bundle_name": str(bundle.get("bundle_name") or bundle_name),
                    "case_index": case_index,
                    "case_total": len(cases),
                    "case_id": case_id,
                    "role": role,
                    "agent_binding": role_agent_binding,
                    "evaluation_mode": "agent_judged",
                    **mental_model_progress_fields,
                },
            )
            _emit_progress(
                progress_callback,
                {
                    "event": "role_start",
                    "session_id": session_id,
                    "case_index": case_index,
                    "case_total": len(cases),
                    "case_id": case_id,
                    "role": role,
                    "scenario": "strategy",
                    "mode": "single_turn",
                    "prompt": prompt,
                    "timeout_seconds": min(timeout_seconds, 600),
                    "max_steps": max_steps,
                    "keep_worktree": keep_worktree,
                    "agent_binding": role_agent_binding,
                    "evaluation_mode": "agent_judged",
                },
            )
            try:
                def emit_live_judge_progress(payload: Dict[str, Any]) -> None:
                    _emit_progress(
                        progress_callback,
                        {
                            "event": "role_live",
                            "session_id": session_id,
                            "case_index": case_index,
                            "case_total": len(cases),
                            "case_id": case_id,
                            "role": role,
                            "scenario": "strategy",
                            "mode": "single_turn",
                            "prompt": prompt,
                            "agent_binding": role_agent_binding,
                            "evaluation_mode": "agent_judged",
                            **payload,
                            **mental_model_progress_fields,
                        },
                    )

                result = runner(
                    repo_root=root,
                    mode="single_turn",
                    prompt=prompt,
                    scenario="strategy",
                    timeout_seconds=min(timeout_seconds, 600),
                    max_steps=max_steps or None,
                    expect_restart=False,
                    post_restart_observe_seconds=post_restart_observe_seconds,
                    keep_worktree=keep_worktree,
                    agent_binding=role_agent_binding,
                    mental_model_mode=normalized_mental_model_mode,
                    mental_model_enabled=mental_model_enabled,
                    progress_callback=emit_live_judge_progress,
                    cancel_checker=cancel_checker,
                )
            except Exception as exc:
                if isinstance(exc, SupervisedEvolutionCancelled):
                    raise
                _emit_progress(
                    progress_callback,
                    {
                        "event": "session_error",
                        "session_id": session_id,
                        "case_index": case_index,
                        "case_total": len(cases),
                        "case_id": case_id,
                        "role": role,
                        "scenario": "strategy",
                        "mode": "single_turn",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "agent_binding": role_agent_binding,
                        "evaluation_mode": "agent_judged",
                        **mental_model_progress_fields,
                    },
                )
                raise
            session_dir = dirs["sessions"] / session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            report_name = f"{_safe_report_file_stem(f'{case_id}_{role}')}.json"
            report_path = session_dir / report_name
            report_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
            _emit_progress(
                progress_callback,
                {
                    "event": "role_finish",
                    "session_id": session_id,
                    "case_index": case_index,
                    "case_total": len(cases),
                    "case_id": case_id,
                    "role": role,
                    "status": result.status,
                    "reason": result.reason,
                    "elapsed_seconds": _elapsed_seconds(result.started_at, result.ended_at),
                    "worktree_path": result.worktree_path,
                    "report_path": str(report_path),
                    "drift_warning": _has_drift_warning(status=result.status, reason=result.reason),
                    "agent_binding": role_agent_binding,
                    "evaluation_mode": "agent_judged",
                    **mental_model_progress_fields,
                    "agent_judgment": _normalize_agent_judgment(
                        _agent_judgment_from_summary(result.evolution_summary or {})
                    ),
                },
            )
            judge_runs.append(
                _to_supervised_run(
                    role=role,
                    case_id=case_id,
                    prompt=prompt,
                    scenario="strategy",
                    mode="single_turn",
                    result=result,
                    report_path=report_path,
                    agent_binding=role_agent_binding,
                )
            )
            _run_checkpoint(
                checkpoint_callback,
                {
                    "phase": "role_boundary",
                    "session_id": session_id,
                    "bundle_name": str(bundle.get("bundle_name") or bundle_name),
                    "case_index": case_index,
                    "case_total": len(cases),
                    "case_id": case_id,
                    "role": role,
                    "agent_binding": role_agent_binding,
                    "evaluation_mode": "agent_judged",
                },
            )
        _run_checkpoint(
            checkpoint_callback,
            {
                "phase": "case_boundary",
                "session_id": session_id,
                "bundle_name": str(bundle.get("bundle_name") or bundle_name),
                "case_index": case_index,
                "case_total": len(cases),
                "case_id": case_id,
            },
        )

    baseline_summary = _build_run_aggregate(baseline_runs)
    candidate_summary = _build_run_aggregate(candidate_runs)
    case_summaries = _build_case_summaries(baseline_runs, candidate_runs, judge_runs=judge_runs, cases=cases)
    gates, decision, reason, score_delta = _evaluate_gates(
        baseline_runs,
        candidate_runs,
        case_summaries=case_summaries,
        evaluation_mode=str(evaluation_metadata.get("evaluation_mode") or ""),
    )
    decision, reason, gates = _apply_promotion_gate(
        decision=decision,
        reason=reason,
        gates=gates,
        project_root=root,
        keep_worktree=keep_worktree,
        promotion_gate_runner=promotion_gate_runner,
    )
    ended_at = _now_iso()
    payload = SupervisedEvolutionDecision(
        session_id=session_id,
        bundle_name=str(bundle.get("bundle_name") or bundle_name),
        started_at=started_at,
        ended_at=ended_at,
        benchmark=str(bundle.get("benchmark") or "dry_run"),
        baseline_runs=baseline_runs,
        candidate_runs=candidate_runs,
        baseline_summary=baseline_summary,
        candidate_summary=candidate_summary,
        case_summaries=case_summaries,
        gates=gates,
        decision=decision,
        reason=reason,
        baseline_success_rate=_success_rate(baseline_runs),
        candidate_success_rate=_success_rate(candidate_runs),
        score_delta=score_delta,
        judge_runs=judge_runs,
        advisory_context=advisory_context,
        agent_bindings=normalized_agent_bindings,
        mental_model_mode=normalized_mental_model_mode,
        mental_model_enabled=mental_model_enabled,
        summary={
            "case_count": len(cases),
            "baseline_successes": sum(1 for item in baseline_runs if item.status == "success"),
            "candidate_successes": sum(1 for item in candidate_runs if item.status == "success"),
            "resume_from_decision_path": str(resume_from_decision_path or ""),
            "mental_model_mode": normalized_mental_model_mode,
            "mental_model_enabled": mental_model_enabled,
            "reused_run_count": len([
                item
                for item in baseline_runs + candidate_runs
                if (item.role, item.case_id) in reusable_runs and reusable_runs[(item.role, item.case_id)] is item
            ]),
            **evaluation_metadata,
        },
    )
    decision_path = dirs["decisions"] / f"{session_id}.json"
    decision_path.write_text(json.dumps(asdict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    payload.decision_path = str(decision_path)
    decision_path.write_text(json.dumps(asdict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    policy_record = execute_supervised_policy(
        decision=payload,
        bundle=bundle,
        bundle_path=bundle_path,
        project_root=root,
    )
    payload.policy_action = asdict(policy_record)
    decision_path.write_text(json.dumps(asdict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    _append_session_index(
        dirs["base"] / "history.jsonl",
        {
            "session_id": payload.session_id,
            "bundle_name": payload.bundle_name,
            "decision": payload.decision,
            "baseline_success_rate": payload.baseline_success_rate,
            "candidate_success_rate": payload.candidate_success_rate,
            "score_delta": payload.score_delta,
            "decision_path": payload.decision_path,
            "policy_action": payload.policy_action.get("action"),
            "ended_at": payload.ended_at,
        },
    )
    _emit_progress(
        progress_callback,
        {
            "event": "session_finish",
            "session_id": payload.session_id,
            "bundle_name": payload.bundle_name,
            "decision": payload.decision,
            "reason": payload.reason,
            "decision_path": payload.decision_path,
            "policy_action": payload.policy_action.get("action"),
            "active_advisory_count": advisory_context.get("active_count", 0),
            "mental_model_mode": normalized_mental_model_mode,
            "mental_model_enabled": mental_model_enabled,
        },
    )
    return payload


def _format_advisory_context_lines(advisory_context: Dict[str, Any]) -> list[str]:
    if not isinstance(advisory_context, dict):
        return []
    count = int(advisory_context.get("active_count") or 0)
    entries = advisory_context.get("entries") if isinstance(advisory_context.get("entries"), list) else []
    if count <= 0:
        return ["- 当前未记住 active advisory baseline"]
    lines = [f"- active_count={count}"]
    for item in entries[:3]:
        if not isinstance(item, dict):
            continue
        lines.append(
            "- "
            f"{item.get('target_label') or item.get('target_key') or '-'} "
            f"proposal={item.get('proposal_id') or '-'} "
            f"runtime_effect={item.get('runtime_effect') or 'not_applied'} "
            f"agent_consumption={item.get('agent_consumption') or 'advisory'}"
        )
    hidden = count - min(len(entries), 3)
    if hidden > 0:
        lines.append(f"- ... 还有 {hidden} 个 active advisory baseline")
    return lines


__all__ = [
    "DEFAULT_BUNDLE_NAME",
    "DecisionGate",
    "RunAggregate",
    "CaseDecisionSummary",
    "SupervisedEvolutionCancelled",
    "SupervisedEvolutionDecision",
    "SupervisedEvolutionRun",
    "format_decision_record_summary",
    "load_supervised_bundle",
    "normalize_supervised_mental_model_mode",
    "resolve_supervised_bundle_path",
    "run_supervised_evolution_session",
    "supervised_mental_model_enabled_for_mode",
]
