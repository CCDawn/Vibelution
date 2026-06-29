# -*- coding: utf-8 -*-
"""Dataset registry and bundle materialization for supervised evaluation."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.infrastructure.workspace_manager import get_workspace

from .chat_case_lifecycle import chat_reviewed_dataset_metadata
from .dataset_adapters import (
    adapter_bundle_dataset_metadata,
    adapter_usability,
    materialize_adapter_case,
)
from .self_evolution_candidate_pool import ALLOWED_CANDIDATE_TYPES, list_candidate_records
from .supervised_intake import (
    dataset_intake_boundary,
    generated_case_dataset_metadata,
    protected_dataset_boundary_fields,
    self_evolution_candidate_risk_level,
)
from .supervised_evolution import (
    DEFAULT_BUNDLE_NAME,
    resolve_supervised_bundle_path,
)


DATASET_REGISTRY_PATH = Path("evaluation/datasets/registry.json")
TERMINAL_BENCH_SMOKE_ROWS: List[Dict[str, Any]] = [
    {
        "case_id": "tb_smoke_inspect_validate",
        "instruction": (
            "Run a repository-local terminal investigation before answering. Inspect "
            "core/evaluation/dataset_registry.py and tests/test_dataset_registry.py, "
            "run the focused dataset registry tests, then close the evolution "
            "transaction with status=success only if validation passes."
        ),
        "training_tier": "coordination",
        "max_steps": 100,
        "allowed_tools": [
            "open_evolution_transaction_tool",
            "execute_shell_command_tool",
            "python_lint_tool",
            "close_evolution_transaction_tool",
        ],
        "verifier": {
            "kind": "focused_pytest",
            "command": "python -m pytest tests/test_dataset_registry.py -q",
            "success_marker": "passed",
        },
        "expected": {
            "kind": "terminal_harness",
            "requires_transaction": True,
            "requires_validation": True,
            "requires_multi_step_trace": True,
        },
    },
    {
        "case_id": "tb_smoke_safe_probe_edit",
        "instruction": (
            "Use the terminal/tool harness to make one reversible safe-probe edit, "
            "verify it with py_compile or pytest, and close the evolution transaction "
            "successfully. Do not commit. Keep edits scoped to the harness-managed safe "
            "probe path if a write is needed."
        ),
        "training_tier": "coordination",
        "max_steps": 100,
        "allowed_tools": [
            "open_evolution_transaction_tool",
            "execute_shell_command_tool",
            "python_lint_tool",
            "close_evolution_transaction_tool",
        ],
        "verifier": {
            "kind": "safe_probe_validation",
            "command": "python -m py_compile scripts/evolution_harness.py",
            "success_marker": "returncode=0",
        },
        "expected": {
            "kind": "terminal_harness",
            "requires_transaction": True,
            "requires_validation": True,
            "forbid_commit": True,
        },
    },
]
TERMINAL_BENCH_CORE_ROWS: List[Dict[str, Any]] = [
    {
        "case_id": "tb2_fix_code_vulnerability",
        "task_slug": "fix-code-vulnerability",
        "official_task_name": "terminal-bench/fix-code-vulnerability",
        "instruction": (
            "Identify and fix a CRLF injection vulnerability (CWE-93) in the /app Bottle "
            "repository. Analyze /app/bottle.py, write /app/report.jsonl with the vulnerable "
            "file path and CWE id, patch the code so invalid header inputs raise the correct "
            "error, and verify with pytest -rA."
        ),
        "training_tier": "coordination",
        "difficulty": "hard",
        "category": "security",
        "tags": ["security", "code-vulnerability", "common-weakness-enumeration"],
        "docker_image": "alexgshaw/fix-code-vulnerability:20251031",
        "agent_timeout_seconds": 900,
        "verifier": {
            "kind": "harbor_terminal_bench",
            "command": "uv run harbor run --dataset terminal-bench@2.0 --task fix-code-vulnerability",
            "success_marker": "task passed",
        },
    },
    {
        "case_id": "tb2_cancel_async_tasks",
        "task_slug": "cancel-async-tasks",
        "official_task_name": "terminal-bench/cancel-async-tasks",
        "instruction": (
            "Implement async run_tasks(tasks, max_concurrent) in /app/run.py. The function must "
            "limit concurrency and still allow queued/running tasks to execute cleanup code when "
            "the run is cancelled."
        ),
        "training_tier": "coordination",
        "difficulty": "hard",
        "category": "software-engineering",
        "tags": ["async", "concurrency", "python"],
        "docker_image": "alexgshaw/cancel-async-tasks:20251031",
        "agent_timeout_seconds": 900,
        "verifier": {
            "kind": "harbor_terminal_bench",
            "command": "uv run harbor run --dataset terminal-bench@2.0 --task cancel-async-tasks",
            "success_marker": "task passed",
        },
    },
    {
        "case_id": "tb2_fix_git",
        "task_slug": "fix-git",
        "official_task_name": "terminal-bench/fix-git",
        "instruction": (
            "Recover lost commits from a detached HEAD state in a personal-site git repository "
            "and merge the recovered changes back into master."
        ),
        "training_tier": "coordination",
        "difficulty": "easy",
        "category": "software-engineering",
        "tags": ["coding", "version-control"],
        "docker_image": "alexgshaw/fix-git:20251031",
        "agent_timeout_seconds": 900,
        "verifier": {
            "kind": "harbor_terminal_bench",
            "command": "uv run harbor run --dataset terminal-bench@2.0 --task fix-git",
            "success_marker": "task passed",
        },
    },
    {
        "case_id": "tb2_multi_source_data_merger",
        "task_slug": "multi-source-data-merger",
        "official_task_name": "terminal-bench/multi-source-data-merger",
        "instruction": (
            "Merge /data/source_a/users.json, /data/source_b/users.csv, and "
            "/data/source_c/users.parquet into /app/merged_users.parquet. Normalize user fields, "
            "resolve conflicts by source priority, and write /app/conflicts.json."
        ),
        "training_tier": "coordination",
        "difficulty": "medium",
        "category": "data-processing",
        "tags": ["data-processing", "etl", "schema-mapping", "conflict-resolution", "pandas", "parquet"],
        "docker_image": "alexgshaw/multi-source-data-merger:20251031",
        "agent_timeout_seconds": 900,
        "verifier": {
            "kind": "harbor_terminal_bench",
            "command": "uv run harbor run --dataset terminal-bench@2.0 --task multi-source-data-merger",
            "success_marker": "task passed",
        },
    },
    {
        "case_id": "tb2_sqlite_db_truncate",
        "task_slug": "sqlite-db-truncate",
        "official_task_name": "terminal-bench/sqlite-db-truncate",
        "instruction": (
            "Recover as many rows as possible from the binary-truncated SQLite database "
            "/app/trunc.db and write /app/recover.json as a list of word/value objects."
        ),
        "training_tier": "coordination",
        "difficulty": "medium",
        "category": "debugging",
        "tags": ["file-operations", "sqlite", "recovery"],
        "docker_image": "alexgshaw/sqlite-db-truncate:20251031",
        "agent_timeout_seconds": 900,
        "verifier": {
            "kind": "harbor_terminal_bench",
            "command": "uv run harbor run --dataset terminal-bench@2.0 --task sqlite-db-truncate",
            "success_marker": "task passed",
        },
    },
]
TERMINAL_BENCH_AGENT_JUDGED_ROWS: List[Dict[str, Any]] = [
    {
        "case_id": "tb_agent_local_registry_probe",
        "task_slug": "local-registry-probe",
        "instruction": (
            "Run a repository-local multi-step harness probe. Open an evolution transaction, "
            "inspect core/evaluation/dataset_registry.py and core/evaluation/dataset_adapters.py, "
            "confirm how terminal_bench_agent_judged is registered and materialized, run the "
            "focused dataset registry tests, then close the transaction with status=success only "
            "if the evidence and validation support completion. Do not commit or publish changes."
        ),
        "training_tier": "coordination",
        "difficulty": "smoke",
        "category": "software-engineering",
        "tags": ["coding", "dataset-registry", "agent-judged", "local-harness"],
        "max_steps": 100,
        "agent_timeout_seconds": 900,
        "allowed_tools": [
            "open_evolution_transaction_tool",
            "execute_shell_command_tool",
            "python_lint_tool",
            "close_evolution_transaction_tool",
        ],
        "verifier": {
            "kind": "agent_judgment",
            "local_validation": "python -m pytest tests/test_dataset_registry.py -q",
            "success_marker": "SUPERVISED_AGENT_JUDGMENT",
        },
        "expected": {
            "kind": "agent_judged_terminal_harness",
            "requires_transaction": True,
            "requires_validation": True,
            "requires_multi_step_trace": True,
            "judge_scores": True,
        },
        "rubric": {
            "basis": "agent_judgment",
            "scale": "0..1",
            "dimensions": [
                "task_understanding",
                "tool_trace_quality",
                "validation_evidence",
                "safety_and_scope",
                "final_answer_quality",
            ],
            "pass_threshold": 0.70,
        },
    }
]
TERMINAL_BENCH_2_1_SMOKE_ROWS: List[Dict[str, Any]] = [
    {
        "case_id": "tb21_smoke_repo_probe",
        "task_slug": "local-repo-probe",
        "instruction": (
            "Run a Terminal-Bench 2.1 style local terminal task. Inspect the supervised "
            "dataset registry, explain which benchmark metadata controls workbench "
            "visibility, run the focused dataset registry tests, and close the evolution "
            "transaction successfully only when validation passes."
        ),
        "training_tier": "coordination",
        "difficulty": "smoke",
        "category": "software-engineering",
        "tags": ["terminal-bench", "terminus-2", "local-smoke"],
        "max_steps": 100,
        "allowed_tools": [
            "open_evolution_transaction_tool",
            "execute_shell_command_tool",
            "python_lint_tool",
            "close_evolution_transaction_tool",
        ],
        "verifier": {
            "kind": "focused_pytest",
            "command": "python -m pytest tests/test_dataset_registry.py -q",
            "success_marker": "passed",
        },
        "expected": {
            "kind": "terminal_harness",
            "requires_transaction": True,
            "requires_validation": True,
            "requires_multi_step_trace": True,
        },
    },
    {
        "case_id": "tb21_smoke_environment_triage",
        "task_slug": "local-environment-triage",
        "instruction": (
            "Use the terminal harness to inspect the local supervised evaluation environment, "
            "identify whether official benchmark runners are available, avoid claiming an "
            "official score, and close the transaction with evidence-backed status."
        ),
        "training_tier": "coordination",
        "difficulty": "smoke",
        "category": "system-administration",
        "tags": ["terminal-bench", "terminus-2", "environment-preflight"],
        "max_steps": 100,
        "allowed_tools": [
            "open_evolution_transaction_tool",
            "execute_shell_command_tool",
            "close_evolution_transaction_tool",
        ],
        "verifier": {
            "kind": "agent_judgment",
            "local_validation": "python -m pytest tests/test_dataset_registry.py -q",
            "success_marker": "SUPERVISED_AGENT_JUDGMENT",
        },
        "expected": {
            "kind": "terminal_harness",
            "requires_transaction": True,
            "requires_validation": True,
            "requires_multi_step_trace": True,
            "forbid_official_score_claim": True,
        },
    },
]


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
    official_verifier_status: str = "not_required"
    tags: List[str] = None
    review_required: bool = False
    source_track: str = ""
    allowed_downstream_uses: List[str] = None
    holdout_allowed: bool = True
    raw_chat_direct_training_allowed: bool = True
    workbench_visible: bool = True
    benchmark_family: str = ""
    task_type: str = ""
    verifier_kind: str = ""
    score_semantics: str = ""
    run_budget_class: str = ""
    default_visibility: str = ""

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

    root = _workspace_root(project_root)
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
    root = _workspace_root(project_root)
    return root / DATASET_REGISTRY_PATH


def _workspace_root(project_root: Optional[Path] = None) -> Path:
    if project_root is None:
        return get_workspace().root.resolve()
    root = Path(project_root).resolve()
    return root if root.name.lower() == "workspace" else root / "workspace"


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
                "workbench_visible": False,
            },
            {
                "name": "terminal_bench_smoke",
                "kind": "terminal_bench_jsonl",
                "description": (
                    "Terminal-Bench 风格本地 smoke 数据集，要求 agent 通过终端/工具进行多步 inspect、"
                    "modify/verify、transaction close；官方 Terminal-Bench runner 后续再接。"
                ),
                "source_path": "workspace/evaluation/datasets/terminal_bench_smoke.jsonl",
                "bundle_name": "terminal_bench_smoke_v1",
                "scenario": "transaction",
                "mode": "multi_step_react",
                "timeout_seconds": 900,
                "runnable": True,
                "adapter_status": "ready_local_smoke",
                "tags": ["terminal-bench", "react", "harness", "smoke"],
                "source_track": "benchmark",
                "allowed_downstream_uses": ["supervised_evaluation", "regression_observation"],
                "holdout_allowed": False,
                "raw_chat_direct_training_allowed": False,
                "benchmark_family": "terminal_bench",
                "task_type": "terminal_task",
                "verifier_kind": "local_terminal_harness",
                "score_semantics": "pass_rate",
                "run_budget_class": "smoke",
                "default_visibility": "primary",
            },
            {
                "name": "terminal_bench_core",
                "kind": "terminal_bench_jsonl",
                "description": (
                    "Terminal-Bench 2.0 官方任务子集，来自 harbor-framework/terminal-bench-2；"
                    "当前可用 Vibelution 自定义 harness 跑多步终端/ReAct 闭环，分数不是官方 Terminal-Bench 成绩；"
                    "官方 Harbor sandbox 判分器后续接入。"
                ),
                "source_path": "workspace/evaluation/datasets/terminal_bench_core.jsonl",
                "bundle_name": "terminal_bench_core_v1",
                "scenario": "transaction",
                "mode": "multi_step_react",
                "timeout_seconds": 1800,
                "runnable": True,
                "adapter_status": "custom_harness_ready",
                "official_verifier_status": "harbor_pending",
                "tags": ["terminal-bench", "tb2", "react", "harness", "official-seed"],
                "source_track": "benchmark",
                "allowed_downstream_uses": ["supervised_evaluation", "regression_observation"],
                "holdout_allowed": False,
                "raw_chat_direct_training_allowed": False,
                "benchmark_family": "terminal_bench",
                "task_type": "terminal_task",
                "verifier_kind": "custom_terminal_harness",
                "score_semantics": "pass_rate",
                "run_budget_class": "standard",
                "default_visibility": "primary",
            },
            {
                "name": "terminal_bench_agent_judged",
                "kind": "terminal_bench_jsonl",
                "description": (
                    "Terminal-Bench 风格本地纯 agent 评分数据集：baseline/candidate 先跑多步 ReAct，"
                    "再由监督 judge agent 按 rubric 给分和裁决；不接 Harbor、Docker 或官方 verifier。"
                ),
                "source_path": "workspace/evaluation/datasets/terminal_bench_agent_judged.jsonl",
                "bundle_name": "terminal_bench_agent_judged_v1",
                "scenario": "transaction",
                "mode": "multi_step_react",
                "timeout_seconds": 900,
                "runnable": True,
                "adapter_status": "agent_harness_ready",
                "official_verifier_status": "not_required",
                "tags": ["terminal-bench", "react", "agent-judged", "harness"],
                "source_track": "benchmark",
                "allowed_downstream_uses": ["supervised_evaluation", "regression_observation"],
                "holdout_allowed": False,
                "raw_chat_direct_training_allowed": False,
                "benchmark_family": "terminal_bench",
                "task_type": "terminal_task",
                "verifier_kind": "agent_judgment",
                "score_semantics": "agent_rubric_score",
                "run_budget_class": "smoke",
                "default_visibility": "primary",
            },
            {
                "name": "terminal_bench_2_1_smoke",
                "kind": "terminal_bench_jsonl",
                "description": (
                    "Terminal Bench 2.1 / Terminus-2 风格本地 smoke 入口，用于验证多步终端、"
                    "事务关账、环境预检和非官方分数边界；不声明官方榜单成绩。"
                ),
                "source_path": "workspace/evaluation/datasets/terminal_bench_2_1_smoke.jsonl",
                "bundle_name": "terminal_bench_2_1_smoke_v1",
                "scenario": "transaction",
                "mode": "multi_step_react",
                "timeout_seconds": 900,
                "runnable": True,
                "adapter_status": "ready_local_smoke",
                "official_verifier_status": "not_connected",
                "tags": ["terminal-bench", "terminal-bench-2.1", "terminus-2", "react", "harness", "smoke"],
                "source_track": "benchmark",
                "allowed_downstream_uses": ["supervised_evaluation", "regression_observation"],
                "holdout_allowed": False,
                "raw_chat_direct_training_allowed": False,
                "benchmark_family": "terminal_bench",
                "task_type": "terminal_task",
                "verifier_kind": "local_terminal_harness",
                "score_semantics": "pass_rate",
                "run_budget_class": "smoke",
                "default_visibility": "primary",
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
                "workbench_visible": False,
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
                "workbench_visible": False,
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
                "benchmark_family": "swe_bench",
                "task_type": "repo_patch_task",
                "verifier_kind": "swe_harness",
                "score_semantics": "pass_rate",
                "run_budget_class": "standard",
                "default_visibility": "advanced",
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
                "benchmark_family": "swe_bench",
                "task_type": "repo_patch_task",
                "verifier_kind": "swe_harness",
                "score_semantics": "pass_rate",
                "run_budget_class": "standard",
                "default_visibility": "advanced",
            },
            {
                "name": "swe_bench_pro_sample",
                "kind": "repo_patch_jsonl",
                "description": (
                    "SWE-bench Pro 小样本入口；需要真实 repo checkout/setup/verifier harness 后才能判分，"
                    "当前仅作为监督进化 repo patch 任务契约和高级评测来源。"
                ),
                "source_path": "workspace/evaluation/datasets/swe_bench_pro_sample.jsonl",
                "bundle_name": "swe_bench_pro_sample_v1",
                "scenario": "repo_patch",
                "mode": "multi_step_react",
                "timeout_seconds": 3600,
                "runnable": False,
                "adapter_status": "requires_repo_patch_harness",
                "official_verifier_status": "not_connected",
                "tags": ["swe-bench-pro", "repo-patch", "external-repo", "advanced"],
                "source_track": "benchmark",
                "allowed_downstream_uses": ["supervised_evaluation", "regression_observation"],
                "holdout_allowed": False,
                "raw_chat_direct_training_allowed": False,
                "workbench_visible": False,
                "benchmark_family": "swe_bench_pro",
                "task_type": "repo_patch_task",
                "verifier_kind": "repo_patch_harness",
                "score_semantics": "pass_rate",
                "run_budget_class": "medium",
                "default_visibility": "advanced",
            },
            {
                "name": "deep_swe_sample",
                "kind": "repo_patch_jsonl",
                "description": (
                    "DeepSWE 小样本入口；复用 repo patch 任务契约，强调长链路真实仓库修复，"
                    "需要外部 harness 后才能进入默认可运行列表。"
                ),
                "source_path": "workspace/evaluation/datasets/deep_swe_sample.jsonl",
                "bundle_name": "deep_swe_sample_v1",
                "scenario": "repo_patch",
                "mode": "multi_step_react",
                "timeout_seconds": 5400,
                "runnable": False,
                "adapter_status": "requires_repo_patch_harness",
                "official_verifier_status": "not_connected",
                "tags": ["deep-swe", "repo-patch", "external-repo", "advanced"],
                "source_track": "benchmark",
                "allowed_downstream_uses": ["supervised_evaluation", "regression_observation"],
                "holdout_allowed": False,
                "raw_chat_direct_training_allowed": False,
                "workbench_visible": False,
                "benchmark_family": "deep_swe",
                "task_type": "repo_patch_task",
                "verifier_kind": "repo_patch_harness",
                "score_semantics": "pass_rate",
                "run_budget_class": "medium",
                "default_visibility": "advanced",
            },
            {
                "name": "nl2repo_sample",
                "kind": "repo_generation_jsonl",
                "description": (
                    "NL2Repo 小样本入口；从空 workspace 生成完整可安装 repo，需 repo generation "
                    "harness 后才能真实判分。"
                ),
                "source_path": "workspace/evaluation/datasets/nl2repo_sample.jsonl",
                "bundle_name": "nl2repo_sample_v1",
                "scenario": "repo_generation",
                "mode": "multi_step_react",
                "timeout_seconds": 7200,
                "runnable": False,
                "adapter_status": "requires_repo_generation_harness",
                "official_verifier_status": "not_connected",
                "tags": ["nl2repo", "repo-generation", "advanced"],
                "source_track": "benchmark",
                "allowed_downstream_uses": ["supervised_evaluation", "regression_observation"],
                "holdout_allowed": False,
                "raw_chat_direct_training_allowed": False,
                "workbench_visible": False,
                "benchmark_family": "nl2repo",
                "task_type": "repo_generation_task",
                "verifier_kind": "repo_generation_harness",
                "score_semantics": "build_and_test_pass_rate",
                "run_budget_class": "advanced",
                "default_visibility": "advanced",
            },
            {
                "name": "programbench_sample",
                "kind": "blackbox_rebuild_jsonl",
                "description": (
                    "ProgramBench 小样本入口；根据二进制和文档重建源码/构建脚本，"
                    "需要黑盒行为对比 harness 后才能真实判分。"
                ),
                "source_path": "workspace/evaluation/datasets/programbench_sample.jsonl",
                "bundle_name": "programbench_sample_v1",
                "scenario": "blackbox_rebuild",
                "mode": "multi_step_react",
                "timeout_seconds": 7200,
                "runnable": False,
                "adapter_status": "requires_blackbox_rebuild_harness",
                "official_verifier_status": "not_connected",
                "tags": ["programbench", "blackbox-rebuild", "research"],
                "source_track": "benchmark",
                "allowed_downstream_uses": ["supervised_evaluation", "regression_observation"],
                "holdout_allowed": False,
                "raw_chat_direct_training_allowed": False,
                "workbench_visible": False,
                "benchmark_family": "programbench",
                "task_type": "blackbox_rebuild_task",
                "verifier_kind": "blackbox_behavior_harness",
                "score_semantics": "behavior_match_rate",
                "run_budget_class": "research",
                "default_visibility": "roadmap",
            },
            {
                "name": "swe_marathon_roadmap",
                "kind": "benchmark_roadmap",
                "description": "SWE-Marathon 超长软件工程任务，只登记为长期 roadmap，不进入默认监督运行入口。",
                "bundle_name": "swe_marathon_roadmap_v1",
                "runnable": False,
                "adapter_status": "roadmap_only",
                "official_verifier_status": "not_connected",
                "tags": ["swe-marathon", "marathon", "roadmap"],
                "workbench_visible": False,
                "benchmark_family": "swe_marathon",
                "task_type": "marathon_task",
                "verifier_kind": "marathon_harness",
                "score_semantics": "pass_rate",
                "run_budget_class": "marathon",
                "default_visibility": "roadmap",
            },
            {
                "name": "frontier_swe_roadmap",
                "kind": "benchmark_roadmap",
                "description": "FrontierSWE Dominance 需要独立分数语义，只登记为长期 roadmap。",
                "bundle_name": "frontier_swe_roadmap_v1",
                "runnable": False,
                "adapter_status": "roadmap_only",
                "official_verifier_status": "not_connected",
                "tags": ["frontier-swe", "dominance", "roadmap"],
                "workbench_visible": False,
                "benchmark_family": "frontier_swe",
                "task_type": "marathon_task",
                "verifier_kind": "frontier_swe_harness",
                "score_semantics": "dominance",
                "run_budget_class": "marathon",
                "default_visibility": "roadmap",
            },
            {
                "name": "posttrainbench_roadmap",
                "kind": "benchmark_roadmap",
                "description": "PostTrainBench 属于训练/后训练自动化，应进入独立 Training Gym，当前只登记 roadmap。",
                "bundle_name": "posttrainbench_roadmap_v1",
                "runnable": False,
                "adapter_status": "roadmap_only",
                "official_verifier_status": "not_connected",
                "tags": ["posttrainbench", "training-gym", "roadmap"],
                "workbench_visible": False,
                "benchmark_family": "posttrainbench",
                "task_type": "training_research_task",
                "verifier_kind": "training_research_harness",
                "score_semantics": "target_benchmark_delta",
                "run_budget_class": "training_research",
                "default_visibility": "roadmap",
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
        protected_keys = protected_dataset_boundary_fields() | {
            "runnable",
            "adapter_status",
            "official_verifier_status",
            "workbench_visible",
            "benchmark_family",
            "task_type",
            "verifier_kind",
            "score_semantics",
            "run_budget_class",
            "default_visibility",
        }
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
    bootstrap_names = {
        "generated_cases",
        "chat_reviewed_multiturn",
        "terminal_bench_smoke",
        "terminal_bench_core",
        "terminal_bench_agent_judged",
        "terminal_bench_2_1_smoke",
    }
    for spec in specs:
        if spec.name not in bootstrap_names or not spec.source_path:
            continue
        source = resolve_source_path(spec, project_root)
        if source is None:
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        if spec.name == "terminal_bench_smoke":
            _bootstrap_or_refresh_builtin_jsonl(source, TERMINAL_BENCH_SMOKE_ROWS)
        elif spec.name == "terminal_bench_core":
            _bootstrap_or_refresh_builtin_jsonl(source, TERMINAL_BENCH_CORE_ROWS)
        elif spec.name == "terminal_bench_agent_judged":
            _bootstrap_or_refresh_builtin_jsonl(source, TERMINAL_BENCH_AGENT_JUDGED_ROWS)
        elif spec.name == "terminal_bench_2_1_smoke":
            _bootstrap_or_refresh_builtin_jsonl(source, TERMINAL_BENCH_2_1_SMOKE_ROWS)
        elif source.exists():
            continue
        else:
            source.write_text("", encoding="utf-8")


def _bootstrap_or_refresh_builtin_jsonl(source: Path, rows: List[Dict[str, Any]]) -> None:
    rendered = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    if not source.exists():
        source.write_text(rendered, encoding="utf-8")
        return

    existing_rows = []
    try:
        for line in source.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                existing_rows.append(json.loads(stripped))
    except (OSError, json.JSONDecodeError):
        return

    expected_ids = [str(row.get("case_id") or "").strip() for row in rows]
    existing_ids = [
        str(row.get("case_id") or "").strip()
        for row in existing_rows
        if isinstance(row, dict)
    ]
    if (
        existing_ids == expected_ids
        or {item for item in existing_ids if item}.issubset({"tb_agent_fix_git"})
    ) and source.read_text(encoding="utf-8") != rendered:
        source.write_text(rendered, encoding="utf-8")


def ensure_dataset_registry(project_root: Optional[Path] = None) -> Path:
    root = _workspace_root(project_root)
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
                official_verifier_status=str(item.get("official_verifier_status") or "not_required").strip(),
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
                workbench_visible=bool(item.get("workbench_visible", True)),
                benchmark_family=str(item.get("benchmark_family") or "").strip(),
                task_type=str(item.get("task_type") or "").strip(),
                verifier_kind=str(item.get("verifier_kind") or "").strip(),
                score_semantics=str(item.get("score_semantics") or "").strip(),
                run_budget_class=str(item.get("run_budget_class") or "").strip(),
                default_visibility=str(item.get("default_visibility") or "").strip(),
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
        parts = path.parts
        if parts and parts[0] == "workspace":
            path = project_root.joinpath(*parts[1:])
        else:
            path = project_root / path
    return path.resolve()


def _dataset_evaluation_mode(spec: DatasetSpec) -> str:
    if spec.adapter_status == "agent_harness_ready":
        return "agent_judged"
    if spec.official_verifier_status == "harbor_pending":
        return "custom_harness"
    if spec.kind == "benchmark_roadmap":
        return "roadmap_only"
    if spec.adapter_status.startswith("requires_"):
        return "external_harness_required"
    return "official_or_not_required"


def _dataset_score_label(spec: DatasetSpec, evaluation_mode: str) -> str:
    if evaluation_mode == "agent_judged":
        return "Agent-judged score (non-official)"
    if spec.official_verifier_status == "harbor_pending":
        return "Vibelution custom score (non-official)"
    labels = {
        "agent_rubric_score": "Agent rubric score",
        "behavior_match_rate": "Behavior match rate",
        "build_and_test_pass_rate": "Build/test pass rate",
        "dominance": "Dominance score",
        "pass_rate": "Pass rate",
        "target_benchmark_delta": "Target benchmark delta",
    }
    return labels.get(spec.score_semantics, "official_or_local_score")


def list_dataset_status(
    project_root: Optional[Path] = None,
    *,
    include_environment_preflight: bool = True,
) -> List[Dict[str, Any]]:
    root = _workspace_root(project_root)
    rows = []
    for spec in load_dataset_specs(root):
        source = resolve_source_path(spec, root)
        bundle_path = root / "evaluation" / "bundles" / f"{spec.bundle_name}.json"
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

        usability = adapter_usability(
            spec,
            available=available,
            case_count=case_count,
            validation_error=validation_error,
            project_root=root,
            include_environment_preflight=include_environment_preflight,
        )
        usability_status = str(usability.get("usability_status") or "blocked")
        usability_reason = str(usability.get("usability_reason") or spec.adapter_status or "当前适配器阻止运行。")
        environment_contract = usability.get("environment_contract", {})
        if not isinstance(environment_contract, dict):
            environment_contract = {}
        environment_preflight = usability.get("environment_preflight", {})
        if not isinstance(environment_preflight, dict):
            environment_preflight = {}
        preflight_config = (
            environment_contract.get("preflight")
            if isinstance(environment_contract.get("preflight"), dict)
            else {}
        )
        preflight_required = bool(preflight_config.get("required")) or bool(environment_contract.get("required_paths"))
        preflight_blocks_launch = (
            include_environment_preflight
            and preflight_required
            and bool(environment_preflight)
            and not bool(environment_preflight.get("available"))
        )
        if preflight_blocks_launch:
            usability_reason = _append_environment_preflight_missing_reason(
                usability_reason,
                environment_preflight,
            )
        effective = usability_status in {"ready", "agent_harness_ready", "custom_harness_ready"} and not preflight_blocks_launch
        visibility = "primary" if effective and spec.workbench_visible else "hidden"
        if not spec.workbench_visible:
            visibility_reason = "底层数据池不直接作为工作台评测入口展示。"
        elif usability_status == "empty":
            visibility_reason = "空数据集已从主选择器隐藏。"
        elif usability_status == "missing_source":
            visibility_reason = "缺少本地源文件，已从主选择器隐藏。"
        elif usability_status == "requires_external_harness":
            visibility_reason = "需要外部 harness，已从主选择器隐藏。"
        elif usability_status == "requires_official_task_environment":
            visibility_reason = "需要 Harbor/Docker 官方任务环境，已从主选择器隐藏。"
        elif preflight_blocks_launch:
            visibility_reason = "任务环境预检未通过，已从主选择器隐藏。"
        elif spec.default_visibility == "roadmap":
            visibility_reason = "长期研究评测，只登记路线图，不进入默认启动入口。"
        elif usability_status in {"invalid", "blocked"}:
            visibility_reason = "当前不可运行，已从主选择器隐藏。"
        elif usability_status in {"requires_repo_harness", "requires_external_harness", "roadmap_only"}:
            visibility_reason = "需要专用评测 harness 或高级模式，已从主选择器隐藏。"
        elif usability_status == "custom_harness_ready":
            visibility_reason = "可用于 Vibelution 自定义监督评测，但官方判分器未接通。"
        elif usability_status == "agent_harness_ready":
            visibility_reason = "可用于纯 agent 监督评分，不依赖官方判分器。"
        else:
            visibility_reason = "可直接用于监督进化运行。"
        evaluation_mode = _dataset_evaluation_mode(spec)
        score_label = _dataset_score_label(spec, evaluation_mode)
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
                "official_verifier_status": spec.official_verifier_status,
                "evaluation_mode": evaluation_mode,
                "score_label": score_label,
                "official_score_available": (
                    evaluation_mode == "official_or_not_required"
                    and spec.official_verifier_status not in {"harbor_pending", "not_connected"}
                ),
                "visibility": visibility,
                "visibility_reason": visibility_reason,
                "selectable": effective,
                "noise_level": "low" if visibility == "primary" else "hidden",
                "workbench_visible": spec.workbench_visible,
                "adapter_status": spec.adapter_status,
                "source_path": str(source) if source else None,
                "source_exists": bool(source and source.exists()),
                "bundle_path": str(bundle_path),
                "bundle_exists": bundle_path.exists(),
                "description": spec.description,
                "tags": spec.tags,
                "benchmark_family": spec.benchmark_family,
                "task_type": spec.task_type,
                "verifier_kind": spec.verifier_kind,
                "score_semantics": spec.score_semantics,
                "run_budget_class": spec.run_budget_class,
                "default_visibility": spec.default_visibility,
                "review_required": spec.review_required,
                "source_track": spec.source_track,
                "allowed_downstream_uses": spec.allowed_downstream_uses,
                "holdout_allowed": spec.holdout_allowed,
                "raw_chat_direct_training_allowed": spec.raw_chat_direct_training_allowed,
                "intake_boundary": boundary,
                "formal_supervised_evaluation_allowed": boundary[
                    "formal_supervised_evaluation_allowed"
                ],
                "environment_contract": environment_contract,
                "environment_preflight": environment_preflight,
            }
        )
    return rows


def _append_environment_preflight_missing_reason(reason: str, preflight: Dict[str, Any]) -> str:
    missing = _environment_preflight_missing_labels(preflight)
    if not missing:
        return reason
    cleaned = reason.rstrip()
    suffix = f" 缺少/不可用：{'、'.join(missing)}。"
    if cleaned.endswith("。"):
        return f"{cleaned}{suffix}"
    return f"{cleaned}。{suffix}"


def _environment_preflight_missing_labels(preflight: Dict[str, Any]) -> List[str]:
    labels: List[str] = []
    for item in preflight.get("missing") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("path") or "").strip()
        if label:
            labels.append(label)
            continue
        aliases = item.get("aliases")
        if isinstance(aliases, list):
            labels.extend(str(alias).strip() for alias in aliases if str(alias).strip())
    verifier = preflight.get("official_verifier")
    if isinstance(verifier, dict):
        for item in verifier.get("missing") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("name") or item.get("path") or item.get("evidence") or "").strip()
            if label:
                labels.append(label)
    deduped: List[str] = []
    seen: set[str] = set()
    for label in labels:
        key = label.lower()
        if key in seen:
            continue
        deduped.append(label)
        seen.add(key)
    return deduped


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


def materialize_dataset_bundle(
    dataset_name: str,
    *,
    project_root: Optional[Path] = None,
    limit: Optional[int] = None,
) -> DatasetMaterialization:
    root = _workspace_root(project_root)
    spec = get_dataset_spec(dataset_name, project_root=root)
    materialized_bundle_name = spec.bundle_name
    materialization_limit = limit
    bundle_path = root / "evaluation" / "bundles" / f"{materialized_bundle_name}.json"
    if limit is not None:
        limit_count = max(1, int(limit))
        materialization_limit = limit_count
        materialized_bundle_name = f"{spec.bundle_name}_limit_{limit_count}"
        bundle_path = root / "evaluation" / "bundles" / f"{materialized_bundle_name}.json"

    if spec.kind == "supervised_bundle":
        source_bundle = resolve_supervised_bundle_path(spec.bundle_name, project_root=root)
        payload = json.loads(source_bundle.read_text(encoding="utf-8"))
        cases = list(payload.get("cases") or [])
        if limit is not None:
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
    for index, row in enumerate(_iter_jsonl(source, limit=materialization_limit), start=1):
        cases.append(materialize_adapter_case(spec, row, index))

    bundle = {
        "benchmark": f"dataset::{spec.name}",
        "bundle_name": materialized_bundle_name,
        "dataset": adapter_bundle_dataset_metadata(spec, source),
        "default_timeout_seconds": spec.timeout_seconds,
        "cases": cases,
    }
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return DatasetMaterialization(
        dataset_name=spec.name,
        bundle_name=materialized_bundle_name,
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
