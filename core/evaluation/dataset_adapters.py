# -*- coding: utf-8 -*-
"""Isolated dataset adapters for supervised evaluation materialization."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .dataset_environment import (
    TERMINAL_BENCH_CORE_REPO,
    TERMINAL_BENCH_CORE_REVISION,
    preflight_environment_contract,
    render_environment_contract_prompt,
    terminal_bench_environment_contract,
)
from .supervised_intake import (
    ALLOWED_SUPERVISED_CASE_TYPES,
    DYNAMIC_REPLANNING_CASE_TYPE,
    GENERATED_CASE_TYPE,
    IMPOSSIBLE_TASK_CASE_TYPE,
    REVIEWED_CHAT_CASE_TYPE,
    STATIC_CASE_TYPE,
    dataset_intake_boundary,
    reviewed_chat_row_status,
)


TERMINAL_BENCH_SMOKE_DEFAULT_MAX_STEPS = 100
TERMINAL_BENCH_CORE_DEFAULT_MAX_STEPS = 100


class DatasetAdapter:
    kind = ""

    def materialize_case(self, spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
        raise NotImplementedError

    def bundle_dataset_metadata(self, spec: Any, source: Optional[Path]) -> Dict[str, Any]:
        return _base_dataset_metadata(spec, source)

    def explain_usability(
        self,
        spec: Any,
        *,
        available: bool,
        case_count: Optional[int],
        validation_error: str,
        project_root: Optional[Path] = None,
        include_environment_preflight: bool = True,
    ) -> Dict[str, Any]:
        return _default_usability(spec, available=available, case_count=case_count, validation_error=validation_error)


class PromptJsonlAdapter(DatasetAdapter):
    kind = "prompt_jsonl"

    def materialize_case(self, spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
        return _build_prompt_case(spec, row, index)


class GeneratedCaseJsonlAdapter(DatasetAdapter):
    kind = "generated_case_jsonl"

    def materialize_case(self, spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
        return _build_generated_case(spec, row, index)


class SweBenchJsonlAdapter(DatasetAdapter):
    kind = "swe_bench_jsonl"

    def materialize_case(self, spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
        return _build_swe_case(spec, row, index)

    def explain_usability(
        self,
        spec: Any,
        *,
        available: bool,
        case_count: Optional[int],
        validation_error: str,
        project_root: Optional[Path] = None,
        include_environment_preflight: bool = True,
    ) -> Dict[str, Any]:
        if validation_error:
            return _invalid_usability(validation_error)
        if not available:
            return {
                "usability_status": "requires_external_harness",
                "usability_reason": "需要接入外部 SWE harness，且当前源文件不存在。",
            }
        return {
            "usability_status": "requires_external_harness",
            "usability_reason": "需要接入外部 SWE harness 后才能真实判分。",
        }


class TerminalBenchJsonlAdapter(DatasetAdapter):
    kind = "terminal_bench_jsonl"

    def materialize_case(self, spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
        return _build_terminal_bench_case(spec, row, index)

    def bundle_dataset_metadata(self, spec: Any, source: Optional[Path]) -> Dict[str, Any]:
        metadata = _base_dataset_metadata(spec, source)
        if _is_terminal_bench_official_seed(spec):
            metadata["environment_contract"] = terminal_bench_environment_contract(official_seed=True)
        return metadata

    def explain_usability(
        self,
        spec: Any,
        *,
        available: bool,
        case_count: Optional[int],
        validation_error: str,
        project_root: Optional[Path] = None,
        include_environment_preflight: bool = True,
    ) -> Dict[str, Any]:
        if validation_error:
            return _invalid_usability(validation_error)
        if not available:
            return {"usability_status": "missing_source", "usability_reason": "数据集源文件不存在。"}
        if case_count == 0:
            return {"usability_status": "empty", "usability_reason": "数据集当前没有可物化 case。"}
        if _is_terminal_bench_official_seed(spec):
            contract = terminal_bench_environment_contract(official_seed=True)
            reason = "可启动 Vibelution 自定义 harness 多步评测；结果不是 Terminal-Bench 官方成绩，官方 Harbor 判分器尚未接通。"
            payload = {
                "usability_status": "custom_harness_ready",
                "usability_reason": reason,
                "environment_contract": contract,
            }
            if include_environment_preflight:
                preflight = preflight_environment_contract(contract, project_root=project_root)
                if not preflight["available"]:
                    payload["usability_reason"] += " 当前任务环境预检未完全通过，运行时应按 environment_unavailable 失败关账。"
                payload["environment_preflight"] = preflight
            return payload
        if _is_agent_judged_terminal_bench(spec):
            return {
                "usability_status": "agent_harness_ready",
                "usability_reason": "可启动纯 agent 监督评分；分数由 judge agent 基于轨迹和证据裁决，不依赖官方判分器。",
            }
        return {"usability_status": "ready", "usability_reason": "数据集已有可运行 case。"}


class RepoPatchJsonlAdapter(DatasetAdapter):
    kind = "repo_patch_jsonl"

    def materialize_case(self, spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
        return _build_repo_patch_case(spec, row, index)

    def explain_usability(
        self,
        spec: Any,
        *,
        available: bool,
        case_count: Optional[int],
        validation_error: str,
        project_root: Optional[Path] = None,
        include_environment_preflight: bool = True,
    ) -> Dict[str, Any]:
        del project_root, include_environment_preflight
        return _external_harness_usability(
            spec,
            available=available,
            case_count=case_count,
            validation_error=validation_error,
            harness_label="repo patch",
        )


class RepoGenerationJsonlAdapter(DatasetAdapter):
    kind = "repo_generation_jsonl"

    def materialize_case(self, spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
        return _build_repo_generation_case(spec, row, index)

    def explain_usability(
        self,
        spec: Any,
        *,
        available: bool,
        case_count: Optional[int],
        validation_error: str,
        project_root: Optional[Path] = None,
        include_environment_preflight: bool = True,
    ) -> Dict[str, Any]:
        del project_root, include_environment_preflight
        return _external_harness_usability(
            spec,
            available=available,
            case_count=case_count,
            validation_error=validation_error,
            harness_label="repo generation",
        )


class BlackboxRebuildJsonlAdapter(DatasetAdapter):
    kind = "blackbox_rebuild_jsonl"

    def materialize_case(self, spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
        return _build_blackbox_rebuild_case(spec, row, index)

    def explain_usability(
        self,
        spec: Any,
        *,
        available: bool,
        case_count: Optional[int],
        validation_error: str,
        project_root: Optional[Path] = None,
        include_environment_preflight: bool = True,
    ) -> Dict[str, Any]:
        del project_root, include_environment_preflight
        return _external_harness_usability(
            spec,
            available=available,
            case_count=case_count,
            validation_error=validation_error,
            harness_label="blackbox rebuild",
        )


class BenchmarkRoadmapAdapter(DatasetAdapter):
    kind = "benchmark_roadmap"

    def materialize_case(self, spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
        raise ValueError(f"{spec.name} 是 roadmap-only 评测入口，不能物化为监督运行 bundle。")

    def explain_usability(
        self,
        spec: Any,
        *,
        available: bool,
        case_count: Optional[int],
        validation_error: str,
        project_root: Optional[Path] = None,
        include_environment_preflight: bool = True,
    ) -> Dict[str, Any]:
        del available, case_count, validation_error, project_root, include_environment_preflight
        return {
            "usability_status": "roadmap_only",
            "usability_reason": "该评测集只登记为长期路线图，当前不进入监督运行入口。",
        }


class SupervisedBundleAdapter(DatasetAdapter):
    kind = "supervised_bundle"


ADAPTERS: Dict[str, DatasetAdapter] = {
    "prompt_jsonl": PromptJsonlAdapter(),
    "generated_case_jsonl": GeneratedCaseJsonlAdapter(),
    "swe_bench_jsonl": SweBenchJsonlAdapter(),
    "terminal_bench_jsonl": TerminalBenchJsonlAdapter(),
    "repo_patch_jsonl": RepoPatchJsonlAdapter(),
    "repo_generation_jsonl": RepoGenerationJsonlAdapter(),
    "blackbox_rebuild_jsonl": BlackboxRebuildJsonlAdapter(),
    "benchmark_roadmap": BenchmarkRoadmapAdapter(),
    "supervised_bundle": SupervisedBundleAdapter(),
}


def get_dataset_adapter(kind: str) -> DatasetAdapter:
    adapter = ADAPTERS.get(str(kind or "").strip())
    if adapter is None:
        raise ValueError(f"暂不支持的数据集 kind: {kind}")
    return adapter


def materialize_adapter_case(spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
    return get_dataset_adapter(spec.kind).materialize_case(spec, row, index)


def adapter_bundle_dataset_metadata(spec: Any, source: Optional[Path]) -> Dict[str, Any]:
    return get_dataset_adapter(spec.kind).bundle_dataset_metadata(spec, source)


def adapter_usability(
    spec: Any,
    *,
    available: bool,
    case_count: Optional[int],
    validation_error: str,
    project_root: Optional[Path] = None,
    include_environment_preflight: bool = True,
) -> Dict[str, Any]:
    return get_dataset_adapter(spec.kind).explain_usability(
        spec,
        available=available,
        case_count=case_count,
        validation_error=validation_error,
        project_root=project_root,
        include_environment_preflight=include_environment_preflight,
    )


def _text_list(value: Any) -> List[str]:
    raw_items = value if isinstance(value, list) else [] if value is None else [value]
    items: List[str] = []
    for raw in raw_items:
        item = str(raw or "").strip()
        if item and item not in items:
            items.append(item)
    return items


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


def _dataset_ref_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    explicit_ref = row.get("dataset_ref")
    if isinstance(explicit_ref, dict) and explicit_ref:
        return dict(explicit_ref)
    return {key: row.get(key) for key in ("id", "task_id", "instance_id", "repo", "base_commit") if key in row}


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
    for key in ("provenance", "expected_final_state", "expected_infeasible_outcome", "dynamic_events"):
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


def _intake_boundary(spec: Any) -> Dict[str, Any]:
    return dataset_intake_boundary(
        name=spec.name,
        kind=spec.kind,
        review_required=spec.review_required,
        source_track=spec.source_track,
        allowed_downstream_uses=spec.allowed_downstream_uses,
        holdout_allowed=spec.holdout_allowed,
        raw_chat_direct_training_allowed=spec.raw_chat_direct_training_allowed,
    )


def _build_prompt_case(spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
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
        "dataset_ref": _dataset_ref_from_row(row),
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
        case["review"] = {**review_payload, "status": status, "review_required": True, "source_track": "dialogue"}
    if spec.source_track:
        case["source_track"] = spec.source_track
    if spec.allowed_downstream_uses:
        case["allowed_downstream_uses"] = list(spec.allowed_downstream_uses)
    case["intake_boundary"] = _intake_boundary(spec)
    for key in ("expected", "rubric"):
        if key in row:
            case[key] = row[key]
    if "dataset_splits" in row:
        case["dataset_splits"] = _normalize_dataset_splits(row["dataset_splits"])
    return case


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


def _build_generated_case(spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
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
    case["intake_boundary"] = _intake_boundary(spec)
    return case


def _build_swe_case(spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
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
        "dataset_ref": {"dataset": spec.name, "instance_id": instance_id, "repo": repo, "base_commit": base_commit},
        "requires_external_harness": "swe_bench",
        **_benchmark_case_metadata(spec),
    }


def _benchmark_case_metadata(spec: Any) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    for key in (
        "benchmark_family",
        "task_type",
        "verifier_kind",
        "score_semantics",
        "run_budget_class",
    ):
        value = str(getattr(spec, key, "") or "").strip()
        if value:
            metadata[key] = value
    return metadata


def _benchmark_score_label(spec: Any) -> str:
    semantics = str(getattr(spec, "score_semantics", "") or "").strip()
    if semantics == "dominance":
        return "Dominance score"
    if semantics == "agent_rubric_score":
        return "Agent rubric score"
    if semantics == "build_and_test_pass_rate":
        return "Build/test pass rate"
    if semantics == "behavior_match_rate":
        return "Behavior match rate"
    if semantics == "target_benchmark_delta":
        return "Target benchmark delta"
    if semantics == "pass_rate":
        return "Pass rate"
    return "Benchmark score"


def _external_harness_usability(
    spec: Any,
    *,
    available: bool,
    case_count: Optional[int],
    validation_error: str,
    harness_label: str,
) -> Dict[str, Any]:
    if validation_error:
        return _invalid_usability(validation_error)
    if not available:
        return {
            "usability_status": "requires_external_harness",
            "usability_reason": f"需要接入 {harness_label} harness，且当前源文件不存在。",
        }
    if case_count == 0:
        return {"usability_status": "empty", "usability_reason": "数据集当前没有可物化 case。"}
    return {
        "usability_status": "requires_external_harness",
        "usability_reason": f"需要接入 {harness_label} harness 后才能真实判分。",
    }


def _repo_patch_prompt(
    *,
    instance_id: str,
    repo: str,
    base_commit: str,
    problem: str,
    test_command: str,
    benchmark_family: str,
) -> str:
    verifier_line = f"- Test command: {test_command}\n" if test_command else "- Test command: use verifier metadata.\n"
    return (
        "Run this repository patch benchmark case through the supervised evolution chain.\n"
        f"Benchmark family: {benchmark_family or 'repo_patch'}\n"
        f"Instance: {instance_id}\n"
        f"Repo: {repo or '-'}\n"
        f"Base commit: {base_commit or '-'}\n\n"
        "Issue:\n"
        f"{problem}\n\n"
        "Verifier:\n"
        f"{verifier_line}\n"
        "Contract:\n"
        "1. Work only in the candidate worktree supplied by the supervised run.\n"
        "2. Inspect the repository before editing.\n"
        "3. Produce a patch that addresses the issue without using hidden gold patches.\n"
        "4. Run the verifier or explain why the external harness is unavailable.\n"
        "5. Do not claim an official benchmark score unless an official runner produced it."
    )


def _build_repo_patch_case(spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
    instance_id = _case_id_from_row(row, index)
    problem = str(row.get("problem_statement") or row.get("issue") or row.get("prompt") or "").strip()
    if not problem:
        raise ValueError("repo_patch row 缺少 problem_statement/issue/prompt")
    repo = str(row.get("repo") or "").strip()
    base_commit = str(row.get("base_commit") or "").strip()
    test_command = str(row.get("test_command") or row.get("verifier_command") or "").strip()
    prompt = _repo_patch_prompt(
        instance_id=instance_id,
        repo=repo,
        base_commit=base_commit,
        problem=problem,
        test_command=test_command,
        benchmark_family=str(getattr(spec, "benchmark_family", "") or ""),
    )
    verifier = row.get("verifier") if isinstance(row.get("verifier"), dict) else {}
    if test_command:
        verifier = {**verifier, "test_command": test_command}
    return {
        "case_id": instance_id,
        "case_type": STATIC_CASE_TYPE,
        "scenario": str(row.get("scenario") or spec.scenario),
        "mode": str(row.get("mode") or spec.mode),
        "timeout_seconds": int(row.get("timeout_seconds") or spec.timeout_seconds),
        "expect_restart": bool(row.get("expect_restart", False)),
        "baseline_prompt": prompt,
        "candidate_prompt": prompt,
        "training_tier": _normalize_training_tier(row.get("training_tier")),
        "dataset_ref": {"dataset": spec.name, "instance_id": instance_id, "repo": repo, "base_commit": base_commit},
        "requires_external_harness": "repo_patch",
        "evaluation_mode": "external_harness_required",
        "score_label": _benchmark_score_label(spec),
        "official_score": None,
        "official_score_available": False,
        "verifier": verifier,
        "source_track": spec.source_track,
        "allowed_downstream_uses": list(spec.allowed_downstream_uses),
        "intake_boundary": _intake_boundary(spec),
        **_benchmark_case_metadata(spec),
    }


def _build_repo_generation_case(spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
    task_id = _case_id_from_row(row, index)
    specification = str(row.get("specification") or row.get("prompt") or row.get("task") or "").strip()
    if not specification:
        raise ValueError("repo_generation row 缺少 specification/prompt/task")
    package_name = str(row.get("package_name") or row.get("project_name") or "").strip()
    install_command = str(row.get("install_command") or "").strip()
    test_command = str(row.get("test_command") or "").strip()
    prompt = (
        "Run this NL2Repo-style repository generation case from an empty workspace.\n"
        f"Task: {task_id}\n"
        f"Package/project name: {package_name or '-'}\n\n"
        "Specification:\n"
        f"{specification}\n\n"
        "Contract:\n"
        "1. Start from the empty workspace supplied by the supervised harness.\n"
        "2. Design the repository structure, dependency metadata, implementation, and tests.\n"
        "3. Do not use hidden reference repositories or gold solutions.\n"
        "4. Run install/build/test commands when the repo generation harness is available.\n"
        "5. Report external-harness unavailability instead of claiming an official score."
    )
    verifier = row.get("verifier") if isinstance(row.get("verifier"), dict) else {}
    if install_command:
        verifier = {**verifier, "install_command": install_command}
    if test_command:
        verifier = {**verifier, "test_command": test_command}
    return {
        "case_id": task_id,
        "case_type": STATIC_CASE_TYPE,
        "scenario": str(row.get("scenario") or spec.scenario),
        "mode": str(row.get("mode") or spec.mode),
        "timeout_seconds": int(row.get("timeout_seconds") or spec.timeout_seconds),
        "expect_restart": bool(row.get("expect_restart", False)),
        "baseline_prompt": prompt,
        "candidate_prompt": prompt,
        "training_tier": _normalize_training_tier(row.get("training_tier")),
        "dataset_ref": {"dataset": spec.name, "task_id": task_id, "package_name": package_name},
        "requires_empty_workspace": True,
        "requires_external_harness": "repo_generation",
        "evaluation_mode": "external_harness_required",
        "score_label": _benchmark_score_label(spec),
        "official_score": None,
        "official_score_available": False,
        "verifier": verifier,
        "source_track": spec.source_track,
        "allowed_downstream_uses": list(spec.allowed_downstream_uses),
        "intake_boundary": _intake_boundary(spec),
        **_benchmark_case_metadata(spec),
    }


def _build_blackbox_rebuild_case(spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
    task_id = _case_id_from_row(row, index)
    documentation = str(row.get("documentation") or row.get("prompt") or row.get("task") or "").strip()
    if not documentation:
        raise ValueError("blackbox_rebuild row 缺少 documentation/prompt/task")
    binary_path = str(row.get("binary_path") or row.get("program_path") or "").strip()
    build_command = str(row.get("build_command") or "").strip()
    behavior_check_command = str(row.get("behavior_check_command") or row.get("test_command") or "").strip()
    prompt = (
        "Run this ProgramBench-style blackbox software rebuild case.\n"
        f"Task: {task_id}\n"
        f"Reference binary/program: {binary_path or '-'}\n\n"
        "Documentation and observed behavior:\n"
        f"{documentation}\n\n"
        "Contract:\n"
        "1. Reconstruct source code and build scripts from the binary/documentation behavior.\n"
        "2. Do not use hidden original source code.\n"
        "3. Build the new program and compare behavior when the blackbox harness is available.\n"
        "4. Treat missing behavior harness evidence as external-harness unavailable.\n"
        "5. Do not claim an official score without an official behavior verifier."
    )
    verifier = row.get("verifier") if isinstance(row.get("verifier"), dict) else {}
    if build_command:
        verifier = {**verifier, "build_command": build_command}
    if behavior_check_command:
        verifier = {**verifier, "behavior_check_command": behavior_check_command}
    return {
        "case_id": task_id,
        "case_type": STATIC_CASE_TYPE,
        "scenario": str(row.get("scenario") or spec.scenario),
        "mode": str(row.get("mode") or spec.mode),
        "timeout_seconds": int(row.get("timeout_seconds") or spec.timeout_seconds),
        "expect_restart": bool(row.get("expect_restart", False)),
        "baseline_prompt": prompt,
        "candidate_prompt": prompt,
        "training_tier": _normalize_training_tier(row.get("training_tier")),
        "dataset_ref": {"dataset": spec.name, "task_id": task_id, "binary_path": binary_path},
        "requires_external_harness": "blackbox_rebuild",
        "evaluation_mode": "external_harness_required",
        "score_label": _benchmark_score_label(spec),
        "official_score": None,
        "official_score_available": False,
        "verifier": verifier,
        "source_track": spec.source_track,
        "allowed_downstream_uses": list(spec.allowed_downstream_uses),
        "intake_boundary": _intake_boundary(spec),
        **_benchmark_case_metadata(spec),
    }


def _is_terminal_bench_official_seed(spec: Any) -> bool:
    return str(spec.name or "") == "terminal_bench_core"


def _is_agent_judged_terminal_bench(spec: Any) -> bool:
    return (
        str(getattr(spec, "adapter_status", "") or "").strip() == "agent_harness_ready"
        or str(getattr(spec, "name", "") or "").strip() == "terminal_bench_agent_judged"
    )


def _terminal_bench_max_steps(row: Dict[str, Any], *, official_seed: bool = False) -> int:
    default_max_steps = TERMINAL_BENCH_CORE_DEFAULT_MAX_STEPS if official_seed else TERMINAL_BENCH_SMOKE_DEFAULT_MAX_STEPS
    return int(row.get("max_steps") or default_max_steps)


def _build_terminal_bench_prompt(
    row: Dict[str, Any],
    *,
    case_id: str,
    official_seed: bool = False,
    agent_judged: bool = False,
) -> str:
    instruction = _prompt_from_row(row)
    verifier = row.get("verifier") if isinstance(row.get("verifier"), dict) else {}
    allowed_tools = _text_list(row.get("allowed_tools"))
    max_steps = _terminal_bench_max_steps(row, official_seed=official_seed)
    official_task_name = str(row.get("official_task_name") or "").strip()
    docker_image = str(row.get("docker_image") or "").strip()
    verifier_command = str(verifier.get("command") or "").strip()
    success_marker = str(verifier.get("success_marker") or "").strip()
    tool_line = ", ".join(allowed_tools) if allowed_tools else "project-approved terminal and evolution tools"
    official_lines = []
    if official_task_name:
        official_lines.append(f"- Official task: {official_task_name}")
    if docker_image:
        official_lines.append(f"- Docker image: {docker_image}")
    if official_lines:
        official_lines.append(f"- Official dataset: {TERMINAL_BENCH_CORE_REPO}@{TERMINAL_BENCH_CORE_REVISION}")
    official_block = "\n".join(official_lines)
    verifier_lines = []
    if agent_judged:
        verifier_lines.append("- Scoring: a supervised judge agent will score the final trace and evidence.")
        verifier_lines.append("- Required marker from judge: SUPERVISED_AGENT_JUDGMENT")
    elif verifier_command:
        verifier_lines.append(f"- Verifier command: {verifier_command}")
    if success_marker and not agent_judged:
        verifier_lines.append(f"- Success marker: {success_marker}")
    verifier_block = "\n".join(verifier_lines) or "- Verifier: use the dataset row verifier metadata."
    environment_block = render_environment_contract_prompt(terminal_bench_environment_contract(official_seed=official_seed))
    close_contract = (
        "5. Run the local validation you can justify for the task, then close the transaction.\n"
        "6. Close the transaction with status=success only when your evidence supports completion; otherwise close with status=failed.\n"
        if agent_judged
        else "5. Run the verifier before closing the transaction.\n"
        "6. Close the transaction with status=success only when verification passes; otherwise close with status=failed.\n"
    )
    return (
        "Run this Terminal-Bench-style local smoke case through the full agent harness.\n"
        f"Case: {case_id}\n\n"
        "Task:\n"
        f"{instruction}\n\n"
        + (f"Official metadata:\n{official_block}\n\n" if official_block else "")
        + "Harness contract:\n"
        "1. Open an evolution transaction before doing meaningful work.\n"
        "2. Use a multi-step ReAct loop: inspect evidence, choose a tool action, observe, adjust, then verify.\n"
        f"3. Use only these intended tool classes unless the local runtime requires an equivalent: {tool_line}.\n"
        f"4. Keep the loop within roughly {max_steps} meaningful tool steps.\n"
        f"{close_contract}"
        "7. Do not commit or publish changes."
        f"{environment_block}\n\n"
        "Verifier:\n"
        f"{verifier_block}"
    )


def _build_terminal_bench_case(spec: Any, row: Dict[str, Any], index: int) -> Dict[str, Any]:
    case_id = _case_id_from_row(row, index)
    official_seed = _is_terminal_bench_official_seed(spec)
    agent_judged = _is_agent_judged_terminal_bench(spec)
    adapter = "agent_judged" if agent_judged else "official_seed" if official_seed else "local_smoke"
    prompt = str(row.get("baseline_prompt") or row.get("candidate_prompt") or "").strip()
    if not prompt:
        prompt = _build_terminal_bench_prompt(
            row,
            case_id=case_id,
            official_seed=official_seed,
            agent_judged=agent_judged,
        )
    verifier = row.get("verifier") if isinstance(row.get("verifier"), dict) else {}
    allowed_tools = _text_list(row.get("allowed_tools"))
    max_steps = _terminal_bench_max_steps(row, official_seed=official_seed)
    environment_contract = terminal_bench_environment_contract(official_seed=official_seed)
    case = {
        "case_id": case_id,
        "case_type": STATIC_CASE_TYPE,
        "scenario": str(row.get("scenario") or spec.scenario),
        "mode": str(row.get("mode") or spec.mode),
        "timeout_seconds": int(row.get("timeout_seconds") or spec.timeout_seconds),
        "expect_restart": bool(row.get("expect_restart", False)),
        "baseline_prompt": prompt,
        "candidate_prompt": str(row.get("candidate_prompt") or prompt).strip(),
        "training_tier": _normalize_training_tier(row.get("training_tier")),
        "dataset_ref": {"dataset": spec.name, "case_id": case_id, **_dataset_ref_from_row(row)},
        "benchmark_family": "terminal_bench",
        "terminal_bench_adapter": adapter,
        "requires_react_trace": True,
        "requires_terminal_harness": True,
        "official_runner": "agent_judged" if agent_judged else "harbor_pending" if official_seed else "pending",
        "requires_official_task_environment": False,
        "official_task_environment_required_for": "official_verifier" if official_seed else "",
        "required_task_paths": ["/app"] if official_seed else [],
        "environment_contract": environment_contract,
        "evaluation_mode": "agent_judged" if agent_judged else "custom_harness" if official_seed else "local_harness",
        "score_label": (
            "Agent-judged score (non-official Terminal-Bench score)"
            if agent_judged
            else "Vibelution custom score (non-official Terminal-Bench score)"
            if official_seed
            else "Vibelution local smoke score"
        ),
        "official_score": None,
        "official_score_available": False,
        "official_verifier_status": spec.official_verifier_status,
        "official_metadata": {
            "dataset": "terminal-bench@2.0",
            "repo": TERMINAL_BENCH_CORE_REPO,
            "revision": TERMINAL_BENCH_CORE_REVISION,
            "task_slug": str(row.get("task_slug") or case_id).strip(),
            "task_name": str(row.get("official_task_name") or "").strip(),
            "docker_image": str(row.get("docker_image") or "").strip(),
            "difficulty": str(row.get("difficulty") or "").strip(),
            "category": str(row.get("category") or "").strip(),
        },
        "allowed_tools": allowed_tools,
        "max_steps": max_steps,
        "verifier": verifier,
        "expected": row.get(
            "expected",
            {"kind": "terminal_harness", "requires_transaction": True, "requires_validation": True, "requires_multi_step_trace": True},
        ),
        "source_track": spec.source_track,
        "allowed_downstream_uses": list(spec.allowed_downstream_uses),
        "intake_boundary": _intake_boundary(spec),
        **_benchmark_case_metadata(spec),
    }
    if "rubric" in row:
        case["rubric"] = row["rubric"]
    if agent_judged:
        case["agent_judged"] = True
        case["judge_required"] = True
        case["judge_marker"] = "SUPERVISED_AGENT_JUDGMENT"
    if "dataset_splits" in row:
        case["dataset_splits"] = _normalize_dataset_splits(row["dataset_splits"])
    return case


def _base_dataset_metadata(spec: Any, source: Optional[Path]) -> Dict[str, Any]:
    evaluation_mode = _dataset_evaluation_mode(spec)
    score_label = (
        "Agent-judged score (non-official Terminal-Bench score)"
        if evaluation_mode == "agent_judged"
        else "Vibelution custom score (non-official Terminal-Bench score)"
        if spec.official_verifier_status == "harbor_pending"
        else _benchmark_score_label(spec)
    )
    metadata = {
        "name": spec.name,
        "kind": spec.kind,
        "source_path": str(source) if source is not None else "",
        "adapter_status": spec.adapter_status,
        "official_verifier_status": spec.official_verifier_status,
        "evaluation_mode": evaluation_mode,
        "score_label": score_label,
        "official_score": None,
        "official_score_available": evaluation_mode == "official_or_not_required"
        and spec.official_verifier_status not in {"harbor_pending", "not_connected"},
        "runnable": spec.runnable,
        "review_required": spec.review_required,
        "source_track": spec.source_track,
        "allowed_downstream_uses": spec.allowed_downstream_uses,
        "holdout_allowed": spec.holdout_allowed,
        "raw_chat_direct_training_allowed": spec.raw_chat_direct_training_allowed,
        "intake_boundary": _intake_boundary(spec),
    }
    metadata.update(_benchmark_case_metadata(spec))
    return metadata


def _dataset_evaluation_mode(spec: Any) -> str:
    if _is_agent_judged_terminal_bench(spec):
        return "agent_judged"
    if spec.official_verifier_status == "harbor_pending":
        return "custom_harness"
    if str(getattr(spec, "kind", "") or "") == "benchmark_roadmap":
        return "roadmap_only"
    if str(getattr(spec, "adapter_status", "") or "").startswith("requires_"):
        return "external_harness_required"
    return "official_or_not_required"


def _invalid_usability(validation_error: str) -> Dict[str, Any]:
    return {"usability_status": "invalid", "usability_reason": validation_error}


def _default_usability(
    spec: Any,
    *,
    available: bool,
    case_count: Optional[int],
    validation_error: str,
) -> Dict[str, Any]:
    if validation_error:
        return _invalid_usability(validation_error)
    if not available:
        return {"usability_status": "missing_source", "usability_reason": "数据集源文件不存在。"}
    if not spec.runnable:
        return {"usability_status": "blocked", "usability_reason": spec.adapter_status or "当前适配器阻止运行。"}
    if case_count == 0:
        return {"usability_status": "empty", "usability_reason": "数据集当前没有可物化 case。"}
    return {"usability_status": "ready", "usability_reason": "数据集已有可运行 case。"}


__all__ = [
    "DatasetAdapter",
    "adapter_bundle_dataset_metadata",
    "adapter_usability",
    "get_dataset_adapter",
    "materialize_adapter_case",
]
