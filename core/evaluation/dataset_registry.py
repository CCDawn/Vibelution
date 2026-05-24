# -*- coding: utf-8 -*-
"""Dataset registry and bundle materialization for supervised evaluation."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.infrastructure.workspace_manager import get_workspace

from .chat_case_lifecycle import chat_reviewed_dataset_metadata
from .self_evolution_candidate_pool import ALLOWED_CANDIDATE_TYPES, list_candidate_records
from .supervised_intake import (
    ALLOWED_SUPERVISED_CASE_TYPES,
    DYNAMIC_REPLANNING_CASE_TYPE,
    GENERATED_CASE_TYPE,
    IMPOSSIBLE_TASK_CASE_TYPE,
    REVIEWED_CHAT_CASE_TYPE,
    STATIC_CASE_TYPE,
    dataset_intake_boundary,
    generated_case_dataset_metadata,
    protected_dataset_boundary_fields,
    reviewed_chat_row_status,
    self_evolution_candidate_risk_level,
)
from .supervised_evolution import (
    DEFAULT_BUNDLE_NAME,
    resolve_supervised_bundle_path,
)


DATASET_REGISTRY_PATH = Path("workspace/evaluation/datasets/registry.json")


@dataclass
class DatasetSpec:
    name: str
    kind: str
    description: str
    bundle_name: str
    source_path: Optional[str] = None
    scenario: str = "transaction"
    mode: str = "single_turn"
    timeout_seconds: int = 600
    runnable: bool = True
    adapter_status: str = "ready"
    tags: List[str] = None
    review_required: bool = False
    source_track: str = ""
    allowed_downstream_uses: List[str] = None
    holdout_allowed: bool = True
    raw_chat_direct_training_allowed: bool = True

    def __post_init__(self) -> None:
        if self.tags is None:
            self.tags = []
        if self.allowed_downstream_uses is None:
            self.allowed_downstream_uses = []


@dataclass
class DatasetMaterialization:
    dataset_name: str
    bundle_name: str
    bundle_path: str
    case_count: int
    runnable: bool
    adapter_status: str
    source_path: Optional[str] = None


def list_pending_self_evolution_dataset_candidates(
    project_root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Return self-evolution candidates as pending supervised intake sources.

    These records are visible to the supervised line and dataset registry, but
    they are not registered datasets and cannot be materialized automatically.
    """

    root = (project_root or get_workspace().project_root).resolve()
    rows: List[Dict[str, Any]] = []
    for candidate_type in sorted(ALLOWED_CANDIDATE_TYPES):
        for record in list_candidate_records(candidate_type, project_root=root):
            if str(record.get("review_state") or "").strip().lower() != "pending":
                continue
            boundary = record.get("supervised_intake_boundary")
            rows.append(
                {
                    "candidate_id": str(record.get("candidate_id") or "").strip(),
                    "candidate_type": candidate_type,
                    "source_run_id": str(record.get("source_run_id") or "").strip(),
                    "txn_id": str(record.get("txn_id") or "").strip(),
                    "provenance": record.get("provenance") if isinstance(record.get("provenance"), dict) else {},
                    "review_state": "pending",
                    "risk_level": self_evolution_candidate_risk_level(record.get("risk_level")),
                    "allowed_downstream_uses": _text_list(record.get("allowed_downstream_uses")),
                    "blocked_downstream_uses": _text_list(record.get("blocked_downstream_uses")),
                    "supervised_required": True,
                    "candidate_only": True,
                    "auto_apply": False,
                    "ingest_mode": "self_evolution_candidate",
                    "pending_review_source": True,
                    "accepted_baseline": False,
                    "supervised_intake_boundary": boundary if isinstance(boundary, dict) else {},
                    "source_path": str(record.get("target_path") or "").strip(),
                    "created_at": str(record.get("created_at") or "").strip(),
                }
            )
    return sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def _registry_path(project_root: Optional[Path] = None) -> Path:
    root = (project_root or get_workspace().project_root).resolve()
    return root / DATASET_REGISTRY_PATH


def _text_list(value: Any) -> List[str]:
    raw_items = value if isinstance(value, list) else [] if value is None else [value]
    items: List[str] = []
    for raw in raw_items:
        item = str(raw or "").strip()
        if item and item not in items:
            items.append(item)
    return items


def _default_registry_payload() -> Dict[str, Any]:
    return {
        "version": 1,
        "datasets": [
            {
                "name": "supervised_dry_run",
                "kind": "supervised_bundle",
                "description": "内置监督进化 dry-run 探针集，用于验证事务、lint 和安全修改闭环。",
                "bundle_name": DEFAULT_BUNDLE_NAME,
                "runnable": True,
                "adapter_status": "ready",
                "tags": ["builtin", "smoke"],
            },
            {
                "name": "custom_prompt_jsonl",
                "kind": "prompt_jsonl",
                "description": "通用 JSONL 任务集。每行可包含 case_id、prompt/problem_statement、expected、scenario 等字段。",
                "source_path": "workspace/evaluation/datasets/custom_prompt_tasks.jsonl",
                "bundle_name": "custom_prompt_jsonl_v1",
                "scenario": "transaction",
                "mode": "single_turn",
                "timeout_seconds": 600,
                "runnable": True,
                "adapter_status": "ready",
                "tags": ["local", "jsonl"],
            },
            {
                "name": "generated_cases",
                "kind": "generated_case_jsonl",
                "description": "Gym 依据 Trace、Harness Gap 或 Improvement Episode 生成的训练压力，不可自动进入 holdout。",
                "source_path": "workspace/evaluation/datasets/generated_cases.jsonl",
                "bundle_name": "generated_cases_v1",
                "scenario": "transaction",
                "mode": "single_turn",
                "timeout_seconds": 600,
                "runnable": True,
                "adapter_status": "ready",
                "tags": ["generated", "gym"],
                **generated_case_dataset_metadata(),
            },
            {
                "name": "chat_reviewed_multiturn",
                "kind": "prompt_jsonl",
                "description": "经人工审核通过的多轮 chat 协作片段，物化为单 case prompt，用于监督进化和回归评测。",
                "source_path": "workspace/evaluation/datasets/chat_reviewed_multiturn.jsonl",
                "bundle_name": "chat_reviewed_multiturn_v1",
                "scenario": "conversation_collaboration",
                "mode": "single_turn",
                "timeout_seconds": 600,
                "runnable": True,
                "adapter_status": "ready",
                "tags": ["chat", "multiturn", "reviewed"],
                **chat_reviewed_dataset_metadata(),
            },
            {
                "name": "swe_bench_lite",
                "kind": "swe_bench_jsonl",
                "description": "SWE-bench Lite 本地 JSONL。字段通常包含 instance_id、repo、base_commit、problem_statement、patch、test_patch。",
                "source_path": "workspace/evaluation/datasets/swe_bench_lite.jsonl",
                "bundle_name": "swe_bench_lite_v1",
                "scenario": "swe_patch",
                "mode": "single_turn",
                "timeout_seconds": 1800,
                "runnable": False,
                "adapter_status": "requires_swe_harness",
                "tags": ["swe", "external-repo"],
            },
            {
                "name": "swe_bench_verified",
                "kind": "swe_bench_jsonl",
                "description": "SWE-bench Verified 本地 JSONL。需要后续接入官方 SWE-bench harness 才能真实判分。",
                "source_path": "workspace/evaluation/datasets/swe_bench_verified.jsonl",
                "bundle_name": "swe_bench_verified_v1",
                "scenario": "swe_patch",
                "mode": "single_turn",
                "timeout_seconds": 1800,
                "runnable": False,
                "adapter_status": "requires_swe_harness",
                "tags": ["swe", "verified", "external-repo"],
            },
            {
                "name": "humaneval_jsonl",
                "kind": "prompt_jsonl",
                "description": "HumanEval 风格 JSONL。每行可包含 task_id、prompt、canonical_solution/tests 等字段。",
                "source_path": "workspace/evaluation/datasets/humaneval.jsonl",
                "bundle_name": "humaneval_local_v1",
                "scenario": "transaction",
                "mode": "single_turn",
                "timeout_seconds": 600,
                "runnable": True,
                "adapter_status": "ready",
                "tags": ["codegen", "jsonl"],
            },
            {
                "name": "mbpp_jsonl",
                "kind": "prompt_jsonl",
                "description": "MBPP 风格 JSONL。每行可包含 task_id、text/prompt、test_list/code 等字段。",
                "source_path": "workspace/evaluation/datasets/mbpp.jsonl",
                "bundle_name": "mbpp_local_v1",
                "scenario": "transaction",
                "mode": "single_turn",
                "timeout_seconds": 600,
                "runnable": True,
                "adapter_status": "ready",
                "tags": ["codegen", "jsonl"],
            },
        ],
    }


def _merge_registry_payload(existing: Dict[str, Any]) -> Dict[str, Any]:
    defaults = list(_default_registry_payload().get("datasets") or [])
    merged = list(existing.get("datasets") or [])
    existing_by_name = {
        str(item.get("name") or "").strip(): item
        for item in merged
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    for default_item in defaults:
        name = str(default_item.get("name") or "").strip()
        if not name:
            continue
        existing_item = existing_by_name.get(name)
        if existing_item is None:
            merged.append(default_item)
            continue
        changed = False
        protected_keys = protected_dataset_boundary_fields()
        for key, value in default_item.items():
            if key not in existing_item or key in protected_keys:
                if existing_item.get(key) == value:
                    continue
                existing_item[key] = value
                changed = True
        if changed:
            existing_by_name[name] = existing_item
    return {
        "version": int(existing.get("version") or 1),
        "datasets": merged,
    }


def _bootstrap_builtin_dataset_sources(project_root: Path, specs: List[DatasetSpec]) -> None:
    bootstrap_names = {"generated_cases", "chat_reviewed_multiturn"}
    for spec in specs:
        if spec.name not in bootstrap_names or not spec.source_path:
            continue
        source = resolve_source_path(spec, project_root)
        if source is None or source.exists():
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("", encoding="utf-8")


def ensure_dataset_registry(project_root: Optional[Path] = None) -> Path:
    root = (project_root or get_workspace().project_root).resolve()
    path = _registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        payload = _merge_registry_payload(existing if isinstance(existing, dict) else {})
        rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if path.read_text(encoding="utf-8") != rendered:
            path.write_text(rendered, encoding="utf-8")
    else:
        path.write_text(json.dumps(_default_registry_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _bootstrap_builtin_dataset_sources(root, _dataset_specs_from_payload(payload))
    return path


def _dataset_specs_from_payload(payload: Dict[str, Any]) -> List[DatasetSpec]:
    specs = []
    for item in payload.get("datasets") or []:
        specs.append(
            DatasetSpec(
                name=str(item.get("name") or "").strip(),
                kind=str(item.get("kind") or "").strip(),
                description=str(item.get("description") or "").strip(),
                bundle_name=str(item.get("bundle_name") or "").strip(),
                source_path=item.get("source_path"),
                scenario=str(item.get("scenario") or "transaction"),
                mode=str(item.get("mode") or "single_turn"),
                timeout_seconds=int(item.get("timeout_seconds") or 600),
                runnable=bool(item.get("runnable", True)),
                adapter_status=str(item.get("adapter_status") or "ready"),
                tags=list(item.get("tags") or []),
                review_required=bool(item.get("review_required", False)),
                source_track=str(item.get("source_track") or "").strip(),
                allowed_downstream_uses=[
                    str(use).strip()
                    for use in list(item.get("allowed_downstream_uses") or [])
                    if str(use).strip()
                ],
                holdout_allowed=bool(item.get("holdout_allowed", True)),
                raw_chat_direct_training_allowed=bool(item.get("raw_chat_direct_training_allowed", True)),
            )
        )
    return [item for item in specs if item.name and item.kind and item.bundle_name]


def load_dataset_specs(project_root: Optional[Path] = None) -> List[DatasetSpec]:
    path = ensure_dataset_registry(project_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _dataset_specs_from_payload(payload)


def get_dataset_spec(dataset_name: str, *, project_root: Optional[Path] = None) -> DatasetSpec:
    for spec in load_dataset_specs(project_root):
        if spec.name == dataset_name:
            return spec
    available = ", ".join(item.name for item in load_dataset_specs(project_root)) or "none"
    raise ValueError(f"未知数据集: {dataset_name}；可选: {available}")


def resolve_source_path(spec: DatasetSpec, project_root: Path) -> Optional[Path]:
    if not spec.source_path:
        return None
    path = Path(spec.source_path)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def list_dataset_status(project_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    root = (project_root or get_workspace().project_root).resolve()
    rows = []
    for spec in load_dataset_specs(root):
        source = resolve_source_path(spec, root)
        bundle_path = root / "workspace" / "evaluation" / "bundles" / f"{spec.bundle_name}.json"
        available = spec.kind == "supervised_bundle" or bool(source and source.exists())
        case_count: Optional[int] = None
        validation_error = ""
        if spec.kind == "supervised_bundle":
            try:
                source_bundle = resolve_supervised_bundle_path(spec.bundle_name, project_root=root)
                payload = json.loads(source_bundle.read_text(encoding="utf-8"))
                case_count = len(list(payload.get("cases") or []))
            except Exception as exc:  # pragma: no cover - defensive status reporting
                validation_error = str(exc)
                case_count = 0
        elif source and source.exists():
            try:
                case_count = sum(1 for _ in _iter_jsonl(source))
            except Exception as exc:
                validation_error = str(exc)
                case_count = 0

        if validation_error:
            usability_status = "invalid"
            usability_reason = validation_error
        elif not spec.runnable and spec.adapter_status == "requires_swe_harness":
            usability_status = "requires_external_harness"
            if not available:
                usability_reason = "需要接入外部 SWE harness，且当前源文件不存在。"
            else:
                usability_reason = "需要接入外部 SWE harness 后才能真实判分。"
        elif not available:
            usability_status = "missing_source"
            usability_reason = "数据集源文件不存在。"
        elif not spec.runnable:
            usability_status = "blocked"
            usability_reason = spec.adapter_status or "当前适配器阻止运行。"
        elif case_count == 0:
            usability_status = "empty"
            usability_reason = "数据集当前没有可物化 case。"
        else:
            usability_status = "ready"
            usability_reason = "数据集已有可运行 case。"
        effective = usability_status == "ready"
        boundary = dataset_intake_boundary(
            name=spec.name,
            kind=spec.kind,
            review_required=spec.review_required,
            source_track=spec.source_track,
            allowed_downstream_uses=spec.allowed_downstream_uses,
            holdout_allowed=spec.holdout_allowed,
            raw_chat_direct_training_allowed=spec.raw_chat_direct_training_allowed,
        )
        rows.append(
            {
                "name": spec.name,
                "kind": spec.kind,
                "bundle_name": spec.bundle_name,
                "runnable": spec.runnable,
                "available": available,
                "effective": effective,
                "case_count": case_count,
                "usability_status": usability_status,
                "usability_reason": usability_reason,
                "adapter_status": spec.adapter_status,
                "source_path": str(source) if source else None,
                "source_exists": bool(source and source.exists()),
                "bundle_path": str(bundle_path),
                "bundle_exists": bundle_path.exists(),
                "description": spec.description,
                "tags": spec.tags,
                "review_required": spec.review_required,
                "source_track": spec.source_track,
                "allowed_downstream_uses": spec.allowed_downstream_uses,
                "holdout_allowed": spec.holdout_allowed,
                "raw_chat_direct_training_allowed": spec.raw_chat_direct_training_allowed,
                "intake_boundary": boundary,
                "formal_supervised_evaluation_allowed": boundary[
                    "formal_supervised_evaluation_allowed"
                ],
            }
        )
    return rows


def _iter_jsonl(path: Path, *, limit: Optional[int] = None) -> Iterable[Dict[str, Any]]:
    count = 0
    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} 不是合法 JSONL: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number} 必须是 JSON object")
            yield row
            count += 1
            if limit is not None and count >= limit:
                break


def _slug(value: str, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip()).strip("_")
    return text[:120] or fallback


def _prompt_from_row(row: Dict[str, Any]) -> str:
    for key in ("prompt", "problem_statement", "text", "instruction", "task", "prompt_seed"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError("JSONL row 缺少 prompt/problem_statement/text/instruction/task/prompt_seed 字段")


def _case_id_from_row(row: Dict[str, Any], index: int) -> str:
    for key in ("case_id", "instance_id", "task_id", "id"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return _slug(str(value), f"case_{index:04d}")
    return f"case_{index:04d}"


def _normalize_case_type(row: Dict[str, Any], *, default: str = "static") -> str:
    case_type = str(row.get("case_type") or default).strip().lower()
    if case_type not in ALLOWED_SUPERVISED_CASE_TYPES:
        raise ValueError(f"未知 case_type: {row.get('case_type')}")
    return case_type


def _require_dict_field(row: Dict[str, Any], field_name: str, *, case_type: str) -> Dict[str, Any]:
    value = row.get(field_name)
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{case_type} case 缺少 {field_name}")
    return value


def _copy_case_schema_fields(case: Dict[str, Any], row: Dict[str, Any], *, case_type: str) -> None:
    case["case_type"] = case_type
    for key in (
        "provenance",
        "expected_final_state",
        "expected_infeasible_outcome",
        "dynamic_events",
    ):
        value = row.get(key)
        if value not in (None, "", [], {}):
            case[key] = value


def _validate_dynamic_or_impossible_case(row: Dict[str, Any], *, case_type: str) -> None:
    if case_type not in {DYNAMIC_REPLANNING_CASE_TYPE, IMPOSSIBLE_TASK_CASE_TYPE}:
        return
    _require_dict_field(row, "provenance", case_type=case_type)
    if case_type == DYNAMIC_REPLANNING_CASE_TYPE:
        _require_dict_field(row, "expected_final_state", case_type=case_type)
    if case_type == IMPOSSIBLE_TASK_CASE_TYPE:
        _require_dict_field(row, "expected_infeasible_outcome", case_type=case_type)


def _build_prompt_case(spec: DatasetSpec, row: Dict[str, Any], index: int) -> Dict[str, Any]:
    prompt = _prompt_from_row(row)
    default_case_type = REVIEWED_CHAT_CASE_TYPE if spec.name == "chat_reviewed_multiturn" else STATIC_CASE_TYPE
    case_type = _normalize_case_type(row, default=default_case_type)
    if spec.name == "chat_reviewed_multiturn" and case_type != REVIEWED_CHAT_CASE_TYPE:
        raise ValueError("Reviewed Chat Case 必须使用 case_type=reviewed_chat")
    if case_type == GENERATED_CASE_TYPE and spec.name != "generated_cases":
        raise ValueError("generated_case case_type 只能由 generated_cases 数据集物化")
    _validate_dynamic_or_impossible_case(row, case_type=case_type)
    case = {
        "case_id": _case_id_from_row(row, index),
        "scenario": str(row.get("scenario") or spec.scenario),
        "mode": str(row.get("mode") or spec.mode),
        "timeout_seconds": int(row.get("timeout_seconds") or spec.timeout_seconds),
        "expect_restart": bool(row.get("expect_restart", False)),
        "baseline_prompt": str(row.get("baseline_prompt") or prompt).strip(),
        "candidate_prompt": str(row.get("candidate_prompt") or prompt).strip(),
        "training_tier": _normalize_training_tier(row.get("training_tier")),
        "dataset_ref": {key: row.get(key) for key in ("id", "task_id", "instance_id", "repo", "base_commit") if key in row},
    }
    _copy_case_schema_fields(case, row, case_type=case_type)
    if spec.name == "chat_reviewed_multiturn":
        status = reviewed_chat_row_status(row)
        if status != "positive":
            raise ValueError("Reviewed Chat Case 必须经过 positive review 才能物化为监督 case")
        for key in ("approval", "review", "quality_signals", "conversation_turns", "next_state_signals"):
            if key in row:
                case[key] = row[key]
        review_payload = case.get("review") if isinstance(case.get("review"), dict) else {}
        case["review"] = {
            **review_payload,
            "status": status,
            "review_required": True,
            "source_track": "dialogue",
        }
    if spec.source_track:
        case["source_track"] = spec.source_track
    if spec.allowed_downstream_uses:
        case["allowed_downstream_uses"] = list(spec.allowed_downstream_uses)
    case["intake_boundary"] = dataset_intake_boundary(
        name=spec.name,
        kind=spec.kind,
        review_required=spec.review_required,
        source_track=spec.source_track,
        allowed_downstream_uses=spec.allowed_downstream_uses,
        holdout_allowed=spec.holdout_allowed,
        raw_chat_direct_training_allowed=spec.raw_chat_direct_training_allowed,
    )
    if "expected" in row:
        case["expected"] = row["expected"]
    if "rubric" in row:
        case["rubric"] = row["rubric"]
    if "dataset_splits" in row:
        case["dataset_splits"] = _normalize_dataset_splits(row["dataset_splits"])
    return case


def _normalize_dataset_splits(value: Any) -> List[str]:
    allowed = {"train", "dev", "observe", "regression", "holdout", "smoke"}
    if value is None:
        return ["train"]
    raw_items = value if isinstance(value, list) else [value]
    splits: List[str] = []
    for raw in raw_items:
        split = str(raw).strip().lower()
        if not split:
            continue
        if split not in allowed:
            raise ValueError(f"未知 dataset split: {raw}")
        if split not in splits:
            splits.append(split)
    return splits or ["train"]


def _normalize_training_tier(value: Any) -> str:
    tier = str(value or "foundation").strip().lower()
    allowed = {"foundation", "coordination", "intelligence"}
    if tier not in allowed:
        raise ValueError(f"未知 training tier: {value}")
    return tier


def _validate_generated_case_provenance(row: Dict[str, Any]) -> Dict[str, Any]:
    provenance = row.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("Generated Case 缺少 provenance")
    required = [
        "source_trace_id",
        "source_episode_id",
        "source_harness_gap",
        "generation_reason",
        "creator_version",
        "created_at",
        "allowed_splits",
    ]
    missing = [key for key in required if not provenance.get(key)]
    if missing:
        raise ValueError(f"Generated Case provenance 缺少字段: {', '.join(missing)}")
    allowed_splits = _normalize_dataset_splits(provenance.get("allowed_splits"))
    if "holdout" in allowed_splits:
        raise ValueError("Generated Case provenance 不允许自动进入 holdout")
    provenance["allowed_splits"] = allowed_splits
    return provenance


def _build_generated_case(spec: DatasetSpec, row: Dict[str, Any], index: int) -> Dict[str, Any]:
    provenance = _validate_generated_case_provenance(row)
    splits = _normalize_dataset_splits(row.get("dataset_splits") or provenance.get("allowed_splits"))
    if "holdout" in splits:
        raise ValueError("Generated Case 不能自动进入 holdout")
    disallowed = [split for split in splits if split not in provenance["allowed_splits"]]
    if disallowed:
        raise ValueError(f"Generated Case split 超出 provenance allowed_splits: {', '.join(disallowed)}")
    explicit_case_type = str(row.get("case_type") or GENERATED_CASE_TYPE).strip().lower()
    if explicit_case_type != GENERATED_CASE_TYPE:
        raise ValueError("generated_cases 数据集必须使用 case_type=generated_case")
    case = _build_prompt_case(spec, row, index)
    case["case_type"] = GENERATED_CASE_TYPE
    case["dataset_splits"] = splits
    case["provenance"] = provenance
    case["generated"] = True
    case["source_track"] = "generated"
    case["allowed_downstream_uses"] = list(spec.allowed_downstream_uses)
    case["intake_boundary"] = dataset_intake_boundary(
        name=spec.name,
        kind=spec.kind,
        review_required=spec.review_required,
        source_track=spec.source_track,
        allowed_downstream_uses=spec.allowed_downstream_uses,
        holdout_allowed=spec.holdout_allowed,
        raw_chat_direct_training_allowed=spec.raw_chat_direct_training_allowed,
    )
    return case


def _build_swe_case(spec: DatasetSpec, row: Dict[str, Any], index: int) -> Dict[str, Any]:
    instance_id = _case_id_from_row(row, index)
    problem = str(row.get("problem_statement") or row.get("prompt") or "").strip()
    if not problem:
        raise ValueError("SWE row 缺少 problem_statement")
    repo = str(row.get("repo") or "").strip()
    base_commit = str(row.get("base_commit") or "").strip()
    prompt = (
        "处理 SWE 数据集 case。\n"
        f"instance_id: {instance_id}\n"
        f"repo: {repo or '-'}\n"
        f"base_commit: {base_commit or '-'}\n\n"
        "问题描述:\n"
        f"{problem}\n\n"
        "要求：生成能解决该 issue 的代码修改，并通过对应测试。"
    )
    return {
        "case_id": instance_id,
        "case_type": STATIC_CASE_TYPE,
        "scenario": spec.scenario,
        "mode": spec.mode,
        "timeout_seconds": spec.timeout_seconds,
        "expect_restart": False,
        "baseline_prompt": prompt,
        "candidate_prompt": prompt,
        "training_tier": _normalize_training_tier(row.get("training_tier")),
        "dataset_ref": {
            "dataset": spec.name,
            "instance_id": instance_id,
            "repo": repo,
            "base_commit": base_commit,
        },
        "requires_external_harness": "swe_bench",
    }


def materialize_dataset_bundle(
    dataset_name: str,
    *,
    project_root: Optional[Path] = None,
    limit: Optional[int] = None,
) -> DatasetMaterialization:
    root = (project_root or get_workspace().project_root).resolve()
    spec = get_dataset_spec(dataset_name, project_root=root)
    bundle_path = root / "workspace" / "evaluation" / "bundles" / f"{spec.bundle_name}.json"

    if spec.kind == "supervised_bundle":
        source_bundle = resolve_supervised_bundle_path(spec.bundle_name, project_root=root)
        payload = json.loads(source_bundle.read_text(encoding="utf-8"))
        cases = list(payload.get("cases") or [])
        materialized_bundle_name = spec.bundle_name
        if limit is not None:
            limit_count = max(1, int(limit))
            materialized_bundle_name = f"{spec.bundle_name}_limit_{limit_count}"
            bundle_path = (
                root
                / "workspace"
                / "evaluation"
                / "bundles"
                / f"{materialized_bundle_name}.json"
            )
            payload["bundle_name"] = materialized_bundle_name
            payload["cases"] = cases[:limit_count]
        if source_bundle != bundle_path or limit is not None:
            bundle_path.parent.mkdir(parents=True, exist_ok=True)
            bundle_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        elif not bundle_path.exists():
            bundle_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_bundle, bundle_path)
        return DatasetMaterialization(
            dataset_name=spec.name,
            bundle_name=materialized_bundle_name,
            bundle_path=str(bundle_path),
            case_count=len(payload.get("cases") or []),
            runnable=spec.runnable,
            adapter_status=spec.adapter_status,
        )

    source = resolve_source_path(spec, root)
    if source is None or not source.exists():
        raise FileNotFoundError(f"数据集源文件不存在: {source or spec.source_path}")

    cases: List[Dict[str, Any]] = []
    for index, row in enumerate(_iter_jsonl(source, limit=limit), start=1):
        if spec.kind == "swe_bench_jsonl":
            cases.append(_build_swe_case(spec, row, index))
        elif spec.kind == "generated_case_jsonl":
            cases.append(_build_generated_case(spec, row, index))
        elif spec.kind == "prompt_jsonl":
            cases.append(_build_prompt_case(spec, row, index))
        else:
            raise ValueError(f"暂不支持的数据集 kind: {spec.kind}")

    bundle = {
        "benchmark": f"dataset::{spec.name}",
        "bundle_name": spec.bundle_name,
        "dataset": {
            "name": spec.name,
            "kind": spec.kind,
            "source_path": str(source),
            "adapter_status": spec.adapter_status,
            "runnable": spec.runnable,
            "review_required": spec.review_required,
            "source_track": spec.source_track,
            "allowed_downstream_uses": spec.allowed_downstream_uses,
            "holdout_allowed": spec.holdout_allowed,
            "raw_chat_direct_training_allowed": spec.raw_chat_direct_training_allowed,
            "intake_boundary": dataset_intake_boundary(
                name=spec.name,
                kind=spec.kind,
                review_required=spec.review_required,
                source_track=spec.source_track,
                allowed_downstream_uses=spec.allowed_downstream_uses,
                holdout_allowed=spec.holdout_allowed,
                raw_chat_direct_training_allowed=spec.raw_chat_direct_training_allowed,
            ),
        },
        "default_timeout_seconds": spec.timeout_seconds,
        "cases": cases,
    }
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return DatasetMaterialization(
        dataset_name=spec.name,
        bundle_name=spec.bundle_name,
        bundle_path=str(bundle_path),
        case_count=len(cases),
        runnable=spec.runnable,
        adapter_status=spec.adapter_status,
        source_path=str(source),
    )


__all__ = [
    "DATASET_REGISTRY_PATH",
    "DatasetMaterialization",
    "DatasetSpec",
    "ensure_dataset_registry",
    "get_dataset_spec",
    "list_pending_self_evolution_dataset_candidates",
    "list_dataset_status",
    "load_dataset_specs",
    "materialize_dataset_bundle",
    "resolve_source_path",
]
