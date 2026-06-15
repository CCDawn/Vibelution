# -*- coding: utf-8 -*-
"""监督进化执行策略。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from config import get_config
from core.infrastructure import developer_sandbox

DEFAULT_OBSERVATION_BUDGET = 3
SUPERVISED_BASELINE_SCOPE = "supervised_frozen_evaluator"
SUPERVISED_POLICY_ARTIFACT_SCOPE = "supervised_policy_artifact"
SUPERVISED_POLICY_RUNTIME_EFFECT = "not_applied"
SUPERVISED_POLICY_AGENT_CONSUMPTION = "advisory"
_SAFE_PROPOSAL_FILE_STEM_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_WINDOWS_RESERVED_FILE_STEMS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _safe_proposal_file_stem(proposal_id: str) -> str:
    raw = str(proposal_id or "").strip()
    stem = _SAFE_PROPOSAL_FILE_STEM_RE.sub("-", raw).strip("._-")
    if not stem:
        stem = "proposal"
    base_name = stem.split(".", 1)[0].upper()
    should_hash = stem != raw or len(stem) > 140 or base_name in _WINDOWS_RESERVED_FILE_STEMS
    if base_name in _WINDOWS_RESERVED_FILE_STEMS:
        stem = f"proposal-{stem}"
    if should_hash:
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:10]
        stem = f"{stem[:128].rstrip('._-') or 'proposal'}-{digest}"
    return stem


def _record_policy_scene_event(
    phase: str,
    event_code: str,
    *,
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: Dict[str, Any] | None = None,
    lifecycle: bool = False,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "selection_policy",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=lifecycle,
        )
    except Exception:
        return


@dataclass
class PolicyExecutionRecord:
    action: str
    summary: str
    bundle_path: str
    policy_record_path: str
    touched_files: List[str] = field(default_factory=list)
    promoted_cases: List[str] = field(default_factory=list)
    observation_cases: List[str] = field(default_factory=list)
    rejected_cases: List[str] = field(default_factory=list)
    case_evidence: List[Dict[str, Any]] = field(default_factory=list)
    proposal_paths: List[str] = field(default_factory=list)
    lineage_index_path: str = ""


def _candidate_id(bundle_name: str, case_id: str, prompt: str) -> str:
    digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12]
    return f"{bundle_name}:{case_id}:{digest}"


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resolve_project_path(project_root: Path, path_str: str) -> Path:
    candidate = Path(path_str)
    if candidate.is_absolute():
        return candidate.resolve()
    parts = candidate.parts
    if parts and parts[0] == "workspace":
        return developer_sandbox.seeded_sandbox_workspace_path(project_root, *parts[1:]).resolve()
    return (project_root / candidate).resolve()


def _proposal_path(project_root: Path, candidate_id: str) -> Path:
    evolution = get_config().evolution
    proposals_dir = _resolve_project_path(project_root, evolution.proposals_dir)
    proposals_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_proposal_file_stem(candidate_id)
    return proposals_dir / f"{safe_name}.json"


def _proposals_dir(project_root: Path) -> Path:
    evolution = get_config().evolution
    proposals_dir = _resolve_project_path(project_root, evolution.proposals_dir)
    proposals_dir.mkdir(parents=True, exist_ok=True)
    return proposals_dir


def _load_json_if_exists(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _lineage_for_case(registry: Dict[str, Any], bundle_name: str, case_id: str) -> Dict[str, Any]:
    baseline_entry = registry.get(f"{bundle_name}:{case_id}") or {}
    return {
        "bundle_case_id": f"{bundle_name}:{case_id}",
        "parent_baseline_id": baseline_entry.get("candidate_id"),
        "parent_session_id": baseline_entry.get("session_id"),
        "last_promoted_at": baseline_entry.get("promoted_at"),
    }


def _target_for_case(bundle_name: str, case_id: str) -> Dict[str, Any]:
    return {
        "kind": "bundle_prompt_case",
        "bundle_name": bundle_name,
        "case_id": case_id,
        "field": "baseline_prompt",
    }


def _supervision_boundary_payload(*, policy_action: str, proposal_status: str) -> Dict[str, Any]:
    return {
        "scope": SUPERVISED_BASELINE_SCOPE,
        "accepted_baseline_registry_scope": SUPERVISED_POLICY_ARTIFACT_SCOPE,
        "policy_action": str(policy_action or "").strip(),
        "proposal_status": str(proposal_status or "").strip(),
        "runtime_effect": SUPERVISED_POLICY_RUNTIME_EFFECT,
        "agent_consumption": SUPERVISED_POLICY_AGENT_CONSUMPTION,
        "promote_updates_runtime": False,
        "runtime_prompt_override_allowed": False,
        "runtime_config_update_allowed": False,
    }


def _run_has_boundary_issue(run: Any) -> bool:
    summary = getattr(run, "evolution_summary", None)
    if not isinstance(summary, dict):
        return False
    git_summary = summary.get("git") if isinstance(summary.get("git"), dict) else {}
    if bool(git_summary.get("commit_detected")):
        return True
    transaction = summary.get("transaction") if isinstance(summary.get("transaction"), dict) else {}
    if not bool(transaction.get("opened")) or not bool(transaction.get("closed")):
        return True
    return str(transaction.get("status") or "").strip() not in {"", "success"}


def _run_has_restart_issue(run: Any) -> bool:
    summary = getattr(run, "evolution_summary", None)
    if not isinstance(summary, dict):
        return False
    restart = summary.get("restart") if isinstance(summary.get("restart"), dict) else {}
    return bool(restart.get("expected")) and not bool(restart.get("reentered"))


def _rollback_supported_for_case(decision: Any, case_summary: Any) -> bool:
    if case_summary.decision_signal == "candidate_regressed":
        return True
    baseline = next((run for run in decision.baseline_runs if run.case_id == case_summary.case_id), None)
    candidate = next((run for run in decision.candidate_runs if run.case_id == case_summary.case_id), None)
    if candidate is None:
        return False
    candidate_boundary_issue = _run_has_boundary_issue(candidate)
    baseline_boundary_issue = _run_has_boundary_issue(baseline)
    if candidate_boundary_issue and not baseline_boundary_issue:
        return True
    return _run_has_restart_issue(candidate) and not _run_has_restart_issue(baseline)


def _case_evidence_payload(
    case_summary: Any,
    *,
    proposal_payload: Dict[str, Any] | None = None,
    proposal_path: Path | None = None,
) -> Dict[str, Any]:
    evidence = {
        "case_id": str(getattr(case_summary, "case_id", "") or ""),
        "case_type": str(getattr(case_summary, "case_type", "") or ""),
        "baseline_status": str(getattr(case_summary, "baseline_status", "") or ""),
        "candidate_status": str(getattr(case_summary, "candidate_status", "") or ""),
        "baseline_reason": str(getattr(case_summary, "baseline_reason", "") or ""),
        "candidate_reason": str(getattr(case_summary, "candidate_reason", "") or ""),
        "decision_signal": str(getattr(case_summary, "decision_signal", "") or ""),
        "difference_summary": str(getattr(case_summary, "difference_summary", "") or ""),
        "difference_metrics": dict(getattr(case_summary, "difference_metrics", {}) or {}),
        "difference_reasons": list(getattr(case_summary, "difference_reasons", []) or []),
        "score_breakdown": dict(getattr(case_summary, "score_breakdown", {}) or {}),
        "failure_taxonomy": list(getattr(case_summary, "failure_taxonomy", []) or []),
        "evidence_paths": dict(getattr(case_summary, "evidence_paths", {}) or {}),
        "intake_provenance": dict(getattr(case_summary, "intake_provenance", {}) or {}),
    }
    evaluation_metadata = _case_evaluation_metadata(case_summary)
    if evaluation_metadata:
        evidence["evaluation_metadata"] = evaluation_metadata
    if proposal_payload is not None:
        evidence["proposal_id"] = str(proposal_payload.get("proposal_id") or "")
        evidence["proposal_status"] = str(proposal_payload.get("status") or "")
        evidence["runtime_effect"] = str(proposal_payload.get("runtime_effect") or "")
        evidence["agent_consumption"] = str(proposal_payload.get("agent_consumption") or "")
        evidence["supervision_boundary"] = dict(proposal_payload.get("supervision_boundary") or {})
    if proposal_path is not None:
        evidence["proposal_path"] = str(proposal_path)
    return evidence


def _case_evaluation_metadata(case_summary: Any) -> Dict[str, Any]:
    intake = getattr(case_summary, "intake_provenance", None)
    if not isinstance(intake, dict):
        return {}
    evaluation_mode = str(intake.get("evaluation_mode") or "").strip()
    official_status = str(intake.get("official_verifier_status") or "").strip()
    score_label = str(intake.get("score_label") or "").strip()
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


def _write_proposal(
    *,
    proposal_path: Path,
    proposal_id: str,
    decision: Any,
    case_summary: Any,
    case_payload: Dict[str, Any],
    status: str,
    registry: Dict[str, Any],
) -> Dict[str, Any]:
    existing = _load_json_if_exists(proposal_path)
    observation_count = int(existing.get("observation_count") or 0)
    observation_budget = int(existing.get("observation_budget") or DEFAULT_OBSERVATION_BUDGET)
    expired_at = existing.get("expired_at")
    expiration_reason = existing.get("expiration_reason")
    if status == "observing":
        observation_count += 1
        if observation_count > observation_budget:
            status = "expired"
            expired_at = expired_at or decision.ended_at
            expiration_reason = expiration_reason or "observation_budget_exhausted"
    elif observation_count <= 0:
        observation_count = 1
    supervision_boundary = _supervision_boundary_payload(
        policy_action=decision.decision,
        proposal_status=status,
    )
    evaluation_metadata = _case_evaluation_metadata(case_summary)
    proposal_payload = {
        "proposal_id": proposal_id,
        "session_id": decision.session_id,
        "bundle_name": decision.bundle_name,
        "case_id": case_summary.case_id,
        "case_type": str(getattr(case_summary, "case_type", "") or ""),
        "target": _target_for_case(decision.bundle_name, case_summary.case_id),
        "lineage": _lineage_for_case(registry, decision.bundle_name, case_summary.case_id),
        "candidate_prompt": str(case_payload.get("candidate_prompt") or ""),
        "baseline_prompt": str(case_payload.get("baseline_prompt") or ""),
        "baseline_prompt_before": str(case_payload.get("baseline_prompt") or ""),
        "baseline_status": case_summary.baseline_status,
        "candidate_status": case_summary.candidate_status,
        "baseline_reason": case_summary.baseline_reason,
        "candidate_reason": case_summary.candidate_reason,
        "decision_signal": case_summary.decision_signal,
        "difference_summary": case_summary.difference_summary,
        "difference_metrics": dict(case_summary.difference_metrics or {}),
        "difference_reasons": list(case_summary.difference_reasons or []),
        "score_breakdown": dict(getattr(case_summary, "score_breakdown", {}) or {}),
        "failure_taxonomy": list(getattr(case_summary, "failure_taxonomy", []) or []),
        "evidence_paths": dict(getattr(case_summary, "evidence_paths", {}) or {}),
        "intake_provenance": dict(getattr(case_summary, "intake_provenance", {}) or {}),
        "evaluation_metadata": evaluation_metadata,
        "status": status,
        "supervised_decision": decision.decision,
        "policy_action": decision.decision,
        "proposal_status": status,
        "runtime_effect": SUPERVISED_POLICY_RUNTIME_EFFECT,
        "agent_consumption": SUPERVISED_POLICY_AGENT_CONSUMPTION,
        "supervision_boundary": supervision_boundary,
        "decision": decision.decision,
        "decision_path": decision.decision_path,
        "observation_count": observation_count,
        "observation_budget": observation_budget,
        "first_seen_at": existing.get("first_seen_at") or decision.started_at,
        "updated_at": decision.ended_at,
    }
    if expired_at:
        proposal_payload["expired_at"] = expired_at
    if expiration_reason:
        proposal_payload["expiration_reason"] = expiration_reason
    proposal_path.write_text(json.dumps(proposal_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return proposal_payload


def _refresh_lineage_index(project_root: Path) -> Path:
    proposals_dir = _proposals_dir(project_root)
    index_path = proposals_dir / "lineage_index.json"
    baseline_registry_path = project_root / "workspace" / "supervised_evolution" / "policy" / "accepted_baselines.json"
    baseline_registry = _load_json_if_exists(baseline_registry_path)
    proposals: List[Dict[str, Any]] = []
    for path in sorted(proposals_dir.glob("*.json")):
        if path.name == "lineage_index.json":
            continue
        payload = _load_json_if_exists(path)
        if payload:
            proposals.append(payload)

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for payload in proposals:
        target = payload.get("target") or {}
        bundle_name = str(payload.get("bundle_name") or target.get("bundle_name") or "").strip()
        case_id = str(payload.get("case_id") or target.get("case_id") or "").strip()
        if not bundle_name or not case_id:
            continue
        key = f"{bundle_name}:{case_id}"
        grouped.setdefault(key, []).append(payload)

    cases: List[Dict[str, Any]] = []
    for key in sorted(grouped):
        items = grouped[key]
        items.sort(key=lambda item: (str(item.get("first_seen_at") or ""), str(item.get("proposal_id") or "")))
        observing = [item for item in items if item.get("status") == "observing"]
        latest = max(items, key=lambda item: str(item.get("updated_at") or ""))
        bundle_name, case_id = key.split(":", 1)
        registry_entry = baseline_registry.get(key) or {}
        cases.append(
            {
                "bundle_name": bundle_name,
                "case_id": case_id,
                "target": latest.get("target") or _target_for_case(bundle_name, case_id),
                "current_baseline_id": registry_entry.get("candidate_id"),
                "latest_candidate_id": latest.get("proposal_id"),
                "proposal_count": len(items),
                "observation_cycles": sum(int(item.get("observation_count") or 0) for item in observing),
                "chain": [
                    {
                        "proposal_id": item.get("proposal_id"),
                        "status": item.get("status"),
                        "decision": item.get("decision"),
                        "observation_count": item.get("observation_count"),
                        "parent_baseline_id": (item.get("lineage") or {}).get("parent_baseline_id"),
                        "first_seen_at": item.get("first_seen_at"),
                        "updated_at": item.get("updated_at"),
                    }
                    for item in items
                ],
            }
        )

    index_payload = {
        "generated_at": _utcnow_iso(),
        "proposal_count": len(proposals),
        "case_count": len(cases),
        "cases": cases,
    }
    index_path.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return index_path


def _audit_policy_action(project_root: Path, payload: Dict[str, Any]) -> Path:
    evolution = get_config().evolution
    audit_path = _resolve_project_path(project_root, evolution.audit_log_path)
    _append_jsonl(
        audit_path,
        {
            "timestamp": _utcnow_iso(),
            **payload,
        },
    )
    return audit_path


def execute_supervised_policy(
    *,
    decision: Any,
    bundle: Dict[str, Any],
    bundle_path: Path,
    project_root: Path,
) -> PolicyExecutionRecord:
    base_dir = developer_sandbox.seeded_sandbox_workspace_path(project_root, "supervised_evolution")
    policy_dir = base_dir / "policy"
    policy_dir.mkdir(parents=True, exist_ok=True)

    observation_pool_path = policy_dir / "candidate_observation_pool.jsonl"
    rejection_pool_path = policy_dir / "candidate_rejections.jsonl"
    rollback_pool_path = policy_dir / "candidate_rollbacks.jsonl"
    promotion_history_path = policy_dir / "promotion_history.jsonl"
    baseline_registry_path = policy_dir / "accepted_baselines.json"
    policy_record_path = policy_dir / f"{decision.session_id}.json"

    touched_files: List[str] = []
    promoted_cases: List[str] = []
    observation_cases: List[str] = []
    rejected_cases: List[str] = []
    case_evidence: List[Dict[str, Any]] = []
    proposal_paths: List[str] = []
    lineage_index_path = ""

    bundle_cases = {str(case.get("case_id") or "").strip() or "case": case for case in bundle.get("cases", [])}

    registry: Dict[str, Any] = {}
    if baseline_registry_path.exists():
        registry = json.loads(baseline_registry_path.read_text(encoding="utf-8"))

    if decision.decision == "PROMOTE":
        for case_summary in decision.case_summaries:
            if case_summary.candidate_status != "success":
                continue
            if case_summary.decision_signal not in {"candidate_improved", "stable_success"}:
                continue
            case_payload = bundle_cases.get(case_summary.case_id)
            if not case_payload:
                continue
            candidate_prompt = str(case_payload.get("candidate_prompt") or "").strip()
            if not candidate_prompt:
                continue
            proposal_id = _candidate_id(decision.bundle_name, case_summary.case_id, candidate_prompt)
            proposal_path = _proposal_path(project_root, proposal_id)
            proposal_payload = _write_proposal(
                proposal_path=proposal_path,
                proposal_id=proposal_id,
                decision=decision,
                case_summary=case_summary,
                case_payload=case_payload,
                status="promoted",
                registry=registry,
            )
            proposal_paths.append(str(proposal_path))
            case_evidence.append(
                _case_evidence_payload(
                    case_summary,
                    proposal_payload=proposal_payload,
                    proposal_path=proposal_path,
                )
            )
            case_payload["baseline_prompt"] = candidate_prompt
            promoted_cases.append(case_summary.case_id)
            registry_key = f"{decision.bundle_name}:{case_summary.case_id}"
            registry[registry_key] = {
                "session_id": decision.session_id,
                "bundle_name": decision.bundle_name,
                "case_id": case_summary.case_id,
                "decision_path": decision.decision_path,
                "candidate_id": proposal_id,
                "promoted_at": decision.ended_at,
                "decision": decision.decision,
                "score_delta": decision.score_delta,
                "scope": SUPERVISED_BASELINE_SCOPE,
                "policy_action": decision.decision,
                "proposal_status": "promoted",
                "runtime_effect": SUPERVISED_POLICY_RUNTIME_EFFECT,
                "agent_consumption": SUPERVISED_POLICY_AGENT_CONSUMPTION,
                "supervision_boundary": _supervision_boundary_payload(
                    policy_action=decision.decision,
                    proposal_status="promoted",
                ),
            }
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        baseline_registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        touched_files.extend([str(bundle_path), str(baseline_registry_path)])
        _append_jsonl(
            promotion_history_path,
            {
                "session_id": decision.session_id,
                "bundle_name": decision.bundle_name,
                "decision": decision.decision,
                "score_delta": decision.score_delta,
                "promoted_cases": promoted_cases,
                "decision_path": decision.decision_path,
                "ended_at": decision.ended_at,
            },
        )
        touched_files.append(str(promotion_history_path))
        audit_path = _audit_policy_action(
            project_root,
            {
                "event": "supervised_policy_executed",
                "action": decision.decision,
                "session_id": decision.session_id,
                "bundle_name": decision.bundle_name,
                "cases": promoted_cases,
                "decision_path": decision.decision_path,
            },
        )
        touched_files.append(str(audit_path))
        summary = f"已晋升 {len(promoted_cases)} 个 case 到新 baseline"
    elif decision.decision == "HOLD":
        for case_summary in decision.case_summaries:
            case_payload = bundle_cases.get(case_summary.case_id)
            if not case_payload:
                continue
            candidate_prompt = str(case_payload.get("candidate_prompt") or "").strip()
            if not candidate_prompt:
                continue
            proposal_id = _candidate_id(decision.bundle_name, case_summary.case_id, candidate_prompt)
            proposal_path = _proposal_path(project_root, proposal_id)
            proposal_payload = _write_proposal(
                proposal_path=proposal_path,
                proposal_id=proposal_id,
                decision=decision,
                case_summary=case_summary,
                case_payload=case_payload,
                status="observing",
                registry=registry,
            )
            proposal_paths.append(str(proposal_path))
            case_evidence.append(
                _case_evidence_payload(
                    case_summary,
                    proposal_payload=proposal_payload,
                    proposal_path=proposal_path,
                )
            )
            observation_cases.append(case_summary.case_id)
            _append_jsonl(
                observation_pool_path,
                {
                    "session_id": decision.session_id,
                    "bundle_name": decision.bundle_name,
                    "case_id": case_summary.case_id,
                    "candidate_id": proposal_id,
                    "decision_signal": case_summary.decision_signal,
                    "decision": decision.decision,
                    "reason": decision.reason,
                    "decision_path": decision.decision_path,
                    "ended_at": decision.ended_at,
                },
            )
        touched_files.append(str(observation_pool_path))
        audit_path = _audit_policy_action(
            project_root,
            {
                "event": "supervised_policy_executed",
                "action": decision.decision,
                "session_id": decision.session_id,
                "bundle_name": decision.bundle_name,
                "cases": observation_cases,
                "decision_path": decision.decision_path,
            },
        )
        touched_files.append(str(audit_path))
        summary = f"已将 {len(observation_cases)} 个 case 放入观察池"
    elif decision.decision == "ROLLBACK":
        for case_summary in decision.case_summaries:
            if not _rollback_supported_for_case(decision, case_summary):
                continue
            case_payload = bundle_cases.get(case_summary.case_id)
            candidate_prompt = str((case_payload or {}).get("candidate_prompt") or "").strip()
            proposal_id = (
                _candidate_id(decision.bundle_name, case_summary.case_id, candidate_prompt) if candidate_prompt else None
            )
            proposal_path = _proposal_path(project_root, proposal_id or f"{decision.bundle_name}:{case_summary.case_id}:missing")
            proposal_payload = _write_proposal(
                proposal_path=proposal_path,
                proposal_id=proposal_id or "",
                decision=decision,
                case_summary=case_summary,
                case_payload=case_payload or {},
                status="rolled_back",
                registry=registry,
            )
            proposal_paths.append(str(proposal_path))
            case_evidence.append(
                _case_evidence_payload(
                    case_summary,
                    proposal_payload=proposal_payload,
                    proposal_path=proposal_path,
                )
            )
            rejected_cases.append(case_summary.case_id)
            _append_jsonl(
                rollback_pool_path,
                {
                    "session_id": decision.session_id,
                    "bundle_name": decision.bundle_name,
                    "case_id": case_summary.case_id,
                    "candidate_id": proposal_id,
                    "decision_signal": case_summary.decision_signal,
                    "decision": decision.decision,
                    "reason": decision.reason,
                    "decision_path": decision.decision_path,
                    "ended_at": decision.ended_at,
                },
            )
        touched_files.append(str(rollback_pool_path))
        audit_path = _audit_policy_action(
            project_root,
            {
                "event": "supervised_policy_executed",
                "action": decision.decision,
                "session_id": decision.session_id,
                "bundle_name": decision.bundle_name,
                "cases": rejected_cases,
                "decision_path": decision.decision_path,
            },
        )
        touched_files.append(str(audit_path))
        summary = f"已记录 {len(rejected_cases)} 个回滚 case"
    elif decision.decision == "INCONCLUSIVE":
        audit_path = _audit_policy_action(
            project_root,
            {
                "event": "supervised_policy_executed",
                "action": decision.decision,
                "session_id": decision.session_id,
                "bundle_name": decision.bundle_name,
                "cases": [],
                "decision_path": decision.decision_path,
                "reason": decision.reason,
            },
        )
        touched_files.append(str(audit_path))
        summary = "监督评测未能区分 baseline 与 candidate，未写入候选观察池或回滚池"
    else:
        for case_summary in decision.case_summaries:
            case_payload = bundle_cases.get(case_summary.case_id)
            candidate_prompt = str((case_payload or {}).get("candidate_prompt") or "").strip()
            proposal_id = (
                _candidate_id(decision.bundle_name, case_summary.case_id, candidate_prompt) if candidate_prompt else None
            )
            proposal_path = _proposal_path(project_root, proposal_id or f"{decision.bundle_name}:{case_summary.case_id}:missing")
            proposal_payload = _write_proposal(
                proposal_path=proposal_path,
                proposal_id=proposal_id or "",
                decision=decision,
                case_summary=case_summary,
                case_payload=case_payload or {},
                status="rejected",
                registry=registry,
            )
            proposal_paths.append(str(proposal_path))
            case_evidence.append(
                _case_evidence_payload(
                    case_summary,
                    proposal_payload=proposal_payload,
                    proposal_path=proposal_path,
                )
            )
            rejected_cases.append(case_summary.case_id)
            _append_jsonl(
                rejection_pool_path,
                {
                    "session_id": decision.session_id,
                    "bundle_name": decision.bundle_name,
                    "case_id": case_summary.case_id,
                    "candidate_id": proposal_id,
                    "decision_signal": case_summary.decision_signal,
                    "decision": decision.decision,
                    "reason": decision.reason,
                    "decision_path": decision.decision_path,
                    "ended_at": decision.ended_at,
                },
            )
        touched_files.append(str(rejection_pool_path))
        audit_path = _audit_policy_action(
            project_root,
            {
                "event": "supervised_policy_executed",
                "action": decision.decision,
                "session_id": decision.session_id,
                "bundle_name": decision.bundle_name,
                "cases": rejected_cases,
                "decision_path": decision.decision_path,
            },
        )
        touched_files.append(str(audit_path))
        summary = f"已记录 {len(rejected_cases)} 个拒绝 case"

    record = PolicyExecutionRecord(
        action=decision.decision,
        summary=summary,
        bundle_path=str(bundle_path),
        policy_record_path=str(policy_record_path),
        touched_files=touched_files,
        promoted_cases=promoted_cases,
        observation_cases=observation_cases,
        rejected_cases=rejected_cases,
        case_evidence=case_evidence,
        proposal_paths=proposal_paths,
        lineage_index_path=lineage_index_path,
    )
    lineage_index = _refresh_lineage_index(project_root)
    lineage_index_path = str(lineage_index)
    if lineage_index_path not in touched_files:
        touched_files.append(lineage_index_path)
    record.lineage_index_path = lineage_index_path
    record.touched_files = touched_files
    policy_record_path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8")
    if str(policy_record_path) not in touched_files:
        touched_files.append(str(policy_record_path))
        record.touched_files = touched_files
        policy_record_path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8")
    _record_policy_scene_event(
        "execute",
        "selection_policy.executed",
        message="Supervised selection policy executed.",
        outcome="succeeded",
        fields={
            "action": record.action,
            "summary": record.summary,
            "bundlePath": record.bundle_path,
            "policyRecordPath": record.policy_record_path,
            "touchedFileCount": len(record.touched_files),
            "promotedCaseCount": len(record.promoted_cases),
            "observationCaseCount": len(record.observation_cases),
            "rejectedCaseCount": len(record.rejected_cases),
            "caseEvidenceCount": len(record.case_evidence),
            "proposalCount": len(record.proposal_paths),
            "proposalPaths": record.proposal_paths,
            "lineageIndexPath": record.lineage_index_path,
        },
        lifecycle=True,
    )
    return record


__all__ = ["PolicyExecutionRecord", "execute_supervised_policy"]
