#!/usr/bin/env python3
"""数据集注册与 bundle 物化测试。"""

import json
from pathlib import Path

import pytest

from core.evaluation.dataset_registry import (
    ensure_dataset_registry,
    list_pending_self_evolution_dataset_candidates,
    list_dataset_status,
    materialize_dataset_bundle,
)
from core.evaluation.self_evolution_candidate_pool import append_candidate_record


def test_default_dataset_registry_lists_builtin_and_swe(tmp_path: Path):
    path = ensure_dataset_registry(tmp_path)

    assert path.exists()
    rows = list_dataset_status(tmp_path)
    by_name = {item["name"]: item for item in rows}

    assert by_name["supervised_dry_run"]["runnable"] is True
    assert by_name["chat_reviewed_multiturn"]["runnable"] is True
    assert by_name["chat_reviewed_multiturn"]["workbench_visible"] is False
    assert by_name["chat_reviewed_multiturn"]["visibility"] == "hidden"
    assert by_name["chat_reviewed_multiturn"]["review_required"] is True
    assert by_name["chat_reviewed_multiturn"]["source_track"] == "dialogue"
    assert by_name["chat_reviewed_multiturn"]["holdout_allowed"] is False
    assert by_name["chat_reviewed_multiturn"]["raw_chat_direct_training_allowed"] is False
    assert "supervised_evaluation" in by_name["chat_reviewed_multiturn"]["allowed_downstream_uses"]
    assert by_name["chat_reviewed_multiturn"]["intake_boundary"]["contract"] == "reviewed_chat_case"
    assert by_name["chat_reviewed_multiturn"]["formal_supervised_evaluation_allowed"] is True
    assert by_name["generated_cases"]["source_track"] == "generated"
    assert by_name["generated_cases"]["workbench_visible"] is False
    assert by_name["generated_cases"]["visibility"] == "hidden"
    assert by_name["generated_cases"]["holdout_allowed"] is False
    assert by_name["generated_cases"]["raw_chat_direct_training_allowed"] is False
    assert by_name["generated_cases"]["intake_boundary"]["contract"] == "generated_case"
    assert by_name["generated_cases"]["formal_supervised_evaluation_allowed"] is True
    assert "supervised_evaluation" in by_name["generated_cases"]["allowed_downstream_uses"]
    assert by_name["terminal_bench_smoke"]["runnable"] is True
    assert by_name["terminal_bench_smoke"]["kind"] == "terminal_bench_jsonl"
    assert by_name["terminal_bench_smoke"]["adapter_status"] == "ready_local_smoke"
    assert by_name["terminal_bench_smoke"]["effective"] is True
    assert by_name["terminal_bench_smoke"]["visibility"] == "primary"
    assert by_name["terminal_bench_smoke"]["selectable"] is True
    assert by_name["terminal_bench_smoke"]["case_count"] >= 2
    assert by_name["terminal_bench_core"]["runnable"] is True
    assert by_name["terminal_bench_core"]["adapter_status"] == "ready_official_seed"
    assert by_name["terminal_bench_core"]["effective"] is True
    assert by_name["terminal_bench_core"]["visibility"] == "primary"
    assert by_name["terminal_bench_core"]["case_count"] >= 5
    assert by_name["swe_bench_lite"]["runnable"] is False
    assert by_name["swe_bench_lite"]["adapter_status"] == "requires_swe_harness"


def test_ensure_dataset_registry_backfills_missing_builtin_datasets(tmp_path: Path):
    legacy_path = tmp_path / "workspace" / "evaluation" / "datasets" / "registry.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "datasets": [
                    {
                        "name": "custom_prompt_jsonl",
                        "kind": "prompt_jsonl",
                        "bundle_name": "custom_prompt_jsonl_v1",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    ensure_dataset_registry(tmp_path)
    payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    names = {item["name"] for item in payload["datasets"]}

    assert "generated_cases" in names
    assert "chat_reviewed_multiturn" in names
    assert "terminal_bench_smoke" in names
    assert "terminal_bench_core" in names
    assert "custom_prompt_jsonl" in names


def test_dataset_registry_backfills_chat_review_boundary_metadata(tmp_path: Path):
    registry_path = tmp_path / "workspace" / "evaluation" / "datasets" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "datasets": [
                    {
                        "name": "chat_reviewed_multiturn",
                        "kind": "prompt_jsonl",
                        "description": "legacy chat cases",
                        "source_path": "workspace/evaluation/datasets/chat_reviewed_multiturn.jsonl",
                        "bundle_name": "chat_reviewed_multiturn_v1",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    ensure_dataset_registry(tmp_path)
    rows = list_dataset_status(tmp_path)
    row = next(item for item in rows if item["name"] == "chat_reviewed_multiturn")

    assert row["review_required"] is True
    assert row["source_track"] == "dialogue"
    assert row["holdout_allowed"] is False
    assert row["raw_chat_direct_training_allowed"] is False
    assert row["allowed_downstream_uses"] == [
        "supervised_evaluation",
        "gym_candidate_case",
        "future_training_export",
    ]


def test_dataset_registry_backfills_generated_case_boundary_metadata(tmp_path: Path):
    registry_path = tmp_path / "workspace" / "evaluation" / "datasets" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "datasets": [
                    {
                        "name": "generated_cases",
                        "kind": "generated_case_jsonl",
                        "description": "legacy generated cases",
                        "source_path": "workspace/evaluation/datasets/generated_cases.jsonl",
                        "bundle_name": "generated_cases_v1",
                        "holdout_allowed": True,
                        "raw_chat_direct_training_allowed": True,
                        "allowed_downstream_uses": ["holdout", "runtime_prompt_override"],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    ensure_dataset_registry(tmp_path)
    row = next(item for item in list_dataset_status(tmp_path) if item["name"] == "generated_cases")

    assert row["source_track"] == "generated"
    assert row["holdout_allowed"] is False
    assert row["raw_chat_direct_training_allowed"] is False
    assert row["allowed_downstream_uses"] == [
        "supervised_evaluation",
        "gym_candidate_case",
        "regression_observation",
    ]
    assert row["intake_boundary"]["boundary_reasons"] == []


def test_dataset_registry_lists_self_evolution_candidates_as_pending_intake_sources(tmp_path: Path):
    append_candidate_record(
        {
            "candidate_id": "prompt_candidate:dataset-registry",
            "candidate_type": "prompt_candidate",
            "source_experience_id": "exp-registry",
            "source_reflection_id": "refl-registry",
            "source_run_id": "web-self-registry",
            "txn_id": "txn-registry",
            "risk_level": "medium",
            "provenance": {
                "source_run_id": "web-self-registry",
                "evidence_refs": ["logs/runtime_scenes/pkg/agent/self_evolution_runs/web-self-registry.jsonl"],
            },
            "allowed_downstream_uses": ["supervised_review", "accepted_baseline"],
            "blocked_downstream_uses": "manual_block",
        },
        project_root=tmp_path,
    )

    rows = list_pending_self_evolution_dataset_candidates(tmp_path)

    assert len(rows) == 1
    row = rows[0]
    assert row["candidate_id"] == "prompt_candidate:dataset-registry"
    assert row["source_run_id"] == "web-self-registry"
    assert row["review_state"] == "pending"
    assert row["risk_level"] == "medium"
    assert row["candidate_only"] is True
    assert row["supervised_required"] is True
    assert row["auto_apply"] is False
    assert row["pending_review_source"] is True
    assert row["accepted_baseline"] is False
    assert row["allowed_downstream_uses"] == ["supervised_review"]
    assert "accepted_baseline" in row["blocked_downstream_uses"]
    assert "manual_block" in row["blocked_downstream_uses"]
    assert "m" not in row["blocked_downstream_uses"]
    assert row["supervised_intake_boundary"]["contract"] == "self_evolution_candidate"
    assert row["supervised_intake_boundary"]["risk_level"] == "medium"


def test_dataset_registry_normalizes_legacy_self_evolution_candidate_risk(tmp_path: Path):
    append_candidate_record(
        {
            "candidate_id": "skill_candidate:legacy-risk",
            "candidate_type": "skill_candidate",
            "source_experience_id": "exp-legacy-risk",
            "source_run_id": "web-self-legacy-risk",
            "risk_level": "accepted",
            "provenance": {
                "source_run_id": "web-self-legacy-risk",
                "evidence_refs": ["reflection:web-self-legacy-risk"],
            },
        },
        project_root=tmp_path,
    )

    row = list_pending_self_evolution_dataset_candidates(tmp_path)[0]

    assert row["risk_level"] == "pending_review"
    assert row["supervised_intake_boundary"]["risk_level"] == "pending_review"


def test_ensure_dataset_registry_bootstraps_generated_and_chat_sources(tmp_path: Path):
    ensure_dataset_registry(tmp_path)

    assert (tmp_path / "workspace" / "evaluation" / "datasets" / "generated_cases.jsonl").exists()
    assert (tmp_path / "workspace" / "evaluation" / "datasets" / "chat_reviewed_multiturn.jsonl").exists()
    terminal_path = tmp_path / "workspace" / "evaluation" / "datasets" / "terminal_bench_smoke.jsonl"
    assert terminal_path.exists()
    assert len([line for line in terminal_path.read_text(encoding="utf-8").splitlines() if line.strip()]) >= 2
    core_path = tmp_path / "workspace" / "evaluation" / "datasets" / "terminal_bench_core.jsonl"
    assert core_path.exists()
    assert len([line for line in core_path.read_text(encoding="utf-8").splitlines() if line.strip()]) >= 5


def test_dataset_status_distinguishes_effective_empty_missing_and_harness(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    custom_path = tmp_path / "workspace" / "evaluation" / "datasets" / "custom_prompt_tasks.jsonl"
    custom_path.parent.mkdir(parents=True, exist_ok=True)
    custom_path.write_text(
        json.dumps({"case_id": "ready", "prompt": "Run a tiny task."}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    rows = list_dataset_status(tmp_path)
    by_name = {item["name"]: item for item in rows}

    assert by_name["custom_prompt_jsonl"]["effective"] is True
    assert by_name["custom_prompt_jsonl"]["case_count"] == 1
    assert by_name["custom_prompt_jsonl"]["usability_status"] == "ready"
    assert by_name["generated_cases"]["effective"] is False
    assert by_name["generated_cases"]["case_count"] == 0
    assert by_name["generated_cases"]["usability_status"] == "empty"
    assert by_name["generated_cases"]["visibility"] == "hidden"
    assert by_name["generated_cases"]["selectable"] is False
    assert by_name["humaneval_jsonl"]["effective"] is False
    assert by_name["humaneval_jsonl"]["usability_status"] == "missing_source"
    assert by_name["humaneval_jsonl"]["visibility"] == "hidden"
    assert by_name["swe_bench_lite"]["effective"] is False
    assert by_name["swe_bench_lite"]["usability_status"] == "requires_external_harness"
    assert by_name["swe_bench_lite"]["selectable"] is False
    assert "源文件不存在" in by_name["swe_bench_lite"]["usability_reason"]


def test_materialize_builtin_supervised_bundle(tmp_path: Path):
    result = materialize_dataset_bundle("supervised_dry_run", project_root=tmp_path)

    assert result.bundle_name == "supervised_evolution_dry_run_v1"
    assert result.runnable is True
    assert result.case_count >= 1
    assert Path(result.bundle_path).exists()


def test_materialize_builtin_supervised_bundle_respects_limit(tmp_path: Path):
    full = materialize_dataset_bundle("supervised_dry_run", project_root=tmp_path)
    result = materialize_dataset_bundle("supervised_dry_run", project_root=tmp_path, limit=1)
    bundle = json.loads(Path(result.bundle_path).read_text(encoding="utf-8"))
    full_bundle = json.loads(Path(full.bundle_path).read_text(encoding="utf-8"))

    assert result.case_count == 1
    assert result.bundle_name.endswith("_limit_1")
    assert len(bundle["cases"]) == 1
    assert bundle["bundle_name"] == result.bundle_name
    assert Path(result.bundle_path).stem == result.bundle_name
    assert result.bundle_path != full.bundle_path
    assert len(full_bundle["cases"]) > 1


def test_materialize_custom_prompt_jsonl(tmp_path: Path):
    registry_path = ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "custom_prompt_tasks.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "hello_case",
                "prompt": "调用 python_lint_tool 检查 scripts/evolution_harness.py，然后成功关账。",
                "training_tier": "coordination",
                "expected": {"kind": "lint_pass"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = materialize_dataset_bundle("custom_prompt_jsonl", project_root=tmp_path)
    bundle = json.loads(Path(result.bundle_path).read_text(encoding="utf-8"))

    assert registry_path.exists()
    assert result.case_count == 1
    assert bundle["dataset"]["name"] == "custom_prompt_jsonl"
    assert bundle["cases"][0]["case_id"] == "hello_case"
    assert bundle["cases"][0]["training_tier"] == "coordination"
    assert bundle["cases"][0]["expected"] == {"kind": "lint_pass"}


def test_materialize_dynamic_and_impossible_case_types_preserves_schema(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "custom_prompt_tasks.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": "dynamic_calendar_change",
                        "case_type": "dynamic_replanning",
                        "prompt": "The calendar changes mid-task; replan and verify the final state.",
                        "provenance": {
                            "source": "stt_arena_fixture",
                            "source_trace_id": "dynamic_trace_001",
                        },
                        "dynamic_events": [
                            {"at_turn": 2, "event": "deadline_changed", "new_deadline": "2026-05-25T10:00:00Z"}
                        ],
                        "expected_final_state": {
                            "calendar_event": "rescheduled",
                            "verified_after_change": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "case_id": "impossible_missing_permission",
                        "case_type": "impossible_task",
                        "prompt": "Try to edit a protected resource without permission.",
                        "provenance": {
                            "source": "stt_arena_fixture",
                            "source_trace_id": "impossible_trace_001",
                        },
                        "expected_infeasible_outcome": {
                            "status": "infeasible",
                            "reason": "missing_permission",
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = materialize_dataset_bundle("custom_prompt_jsonl", project_root=tmp_path)
    bundle = json.loads(Path(result.bundle_path).read_text(encoding="utf-8"))
    by_case = {case["case_id"]: case for case in bundle["cases"]}

    dynamic = by_case["dynamic_calendar_change"]
    assert dynamic["case_type"] == "dynamic_replanning"
    assert dynamic["provenance"]["source_trace_id"] == "dynamic_trace_001"
    assert dynamic["expected_final_state"]["verified_after_change"] is True
    assert dynamic["dynamic_events"][0]["event"] == "deadline_changed"

    impossible = by_case["impossible_missing_permission"]
    assert impossible["case_type"] == "impossible_task"
    assert impossible["provenance"]["source_trace_id"] == "impossible_trace_001"
    assert impossible["expected_infeasible_outcome"]["status"] == "infeasible"


def test_materialize_dynamic_and_impossible_case_types_require_expected_schema(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "custom_prompt_tasks.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "bad_dynamic",
                "case_type": "dynamic_replanning",
                "prompt": "Replan without expected state.",
                "provenance": {"source": "test"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected_final_state"):
        materialize_dataset_bundle("custom_prompt_jsonl", project_root=tmp_path)

    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "bad_impossible",
                "case_type": "impossible_task",
                "prompt": "Fail gracefully without expected infeasible outcome.",
                "provenance": {"source": "test"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected_infeasible_outcome"):
        materialize_dataset_bundle("custom_prompt_jsonl", project_root=tmp_path)


def test_materialize_swe_jsonl_marks_external_harness_requirement(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "swe_bench_lite.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps(
            {
                "instance_id": "django__django-1",
                "repo": "django/django",
                "base_commit": "abc123",
                "problem_statement": "Fix a failing queryset edge case.",
                "patch": "gold patch is hidden from prompts",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = materialize_dataset_bundle("swe_bench_lite", project_root=tmp_path)
    bundle = json.loads(Path(result.bundle_path).read_text(encoding="utf-8"))

    assert result.runnable is False
    assert result.adapter_status == "requires_swe_harness"
    assert bundle["cases"][0]["scenario"] == "swe_patch"
    assert bundle["cases"][0]["requires_external_harness"] == "swe_bench"
    assert "gold patch" not in bundle["cases"][0]["baseline_prompt"]


def test_materialize_terminal_bench_smoke_preserves_harness_contract(tmp_path: Path):
    ensure_dataset_registry(tmp_path)

    result = materialize_dataset_bundle("terminal_bench_smoke", project_root=tmp_path)
    bundle = json.loads(Path(result.bundle_path).read_text(encoding="utf-8"))
    case = bundle["cases"][0]

    assert result.runnable is True
    assert result.adapter_status == "ready_local_smoke"
    assert result.case_count >= 2
    assert bundle["dataset"]["name"] == "terminal_bench_smoke"
    assert bundle["dataset"]["source_track"] == "benchmark"
    assert bundle["dataset"]["holdout_allowed"] is False
    assert case["scenario"] == "transaction"
    assert case["mode"] == "multi_step_react"
    assert case["benchmark_family"] == "terminal_bench"
    assert case["terminal_bench_adapter"] == "local_smoke"
    assert case["requires_react_trace"] is True
    assert case["requires_terminal_harness"] is True
    assert case["official_runner"] == "pending"
    assert case["verifier"]["command"]
    assert "multi-step ReAct" in case["baseline_prompt"]
    assert "Official metadata" not in case["baseline_prompt"]
    assert "Close the transaction" in case["baseline_prompt"] or "close the transaction" in case["baseline_prompt"]


def test_materialize_terminal_bench_core_preserves_official_metadata(tmp_path: Path):
    ensure_dataset_registry(tmp_path)

    result = materialize_dataset_bundle("terminal_bench_core", project_root=tmp_path, limit=2)
    bundle = json.loads(Path(result.bundle_path).read_text(encoding="utf-8"))
    case = bundle["cases"][0]

    assert result.bundle_name == "terminal_bench_core_v1"
    assert result.runnable is True
    assert result.adapter_status == "ready_official_seed"
    assert result.case_count == 2
    assert bundle["dataset"]["name"] == "terminal_bench_core"
    assert case["mode"] == "multi_step_react"
    assert case["terminal_bench_adapter"] == "official_seed"
    assert case["official_runner"] == "harbor_pending"
    assert case["official_metadata"]["dataset"] == "terminal-bench@2.0"
    assert case["official_metadata"]["repo"].endswith("terminal-bench-2")
    assert case["official_metadata"]["revision"]
    assert case["official_metadata"]["task_slug"]
    assert case["official_metadata"]["docker_image"]
    assert case["verifier"]["kind"] == "harbor_terminal_bench"
    assert "uv run harbor run --dataset terminal-bench@2.0" in case["verifier"]["command"]
    assert "Official metadata" in case["baseline_prompt"]


def test_materialize_missing_dataset_source_fails_clearly(tmp_path: Path):
    ensure_dataset_registry(tmp_path)

    with pytest.raises(FileNotFoundError):
        materialize_dataset_bundle("custom_prompt_jsonl", project_root=tmp_path)


def test_materialize_generated_cases_requires_provenance_and_blocks_holdout(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "generated_cases.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "generated_validation_case",
                "prompt": "Run validation before closing the transaction.",
                "training_tier": "intelligence",
                "dataset_splits": ["train", "observe"],
                "provenance": {
                    "source_trace_id": "trace_001",
                    "source_episode_id": "episode_001",
                    "source_harness_gap": "validation",
                    "generation_reason": "candidate closed without validation",
                    "creator_version": "gym-v1-test",
                    "created_at": "2026-05-15T00:00:00Z",
                    "allowed_splits": ["train", "observe"],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = materialize_dataset_bundle("generated_cases", project_root=tmp_path)
    bundle = json.loads(Path(result.bundle_path).read_text(encoding="utf-8"))

    assert result.bundle_name == "generated_cases_v1"
    assert bundle["dataset"]["source_track"] == "generated"
    assert bundle["dataset"]["holdout_allowed"] is False
    assert bundle["dataset"]["raw_chat_direct_training_allowed"] is False
    assert bundle["dataset"]["intake_boundary"]["contract"] == "generated_case"
    assert bundle["cases"][0]["generated"] is True
    assert bundle["cases"][0]["training_tier"] == "intelligence"
    assert bundle["cases"][0]["dataset_splits"] == ["train", "observe"]
    assert bundle["cases"][0]["provenance"]["source_trace_id"] == "trace_001"
    assert bundle["cases"][0]["source_track"] == "generated"
    assert bundle["cases"][0]["intake_boundary"]["formal_supervised_evaluation_allowed"] is True

    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "bad_holdout",
                "prompt": "This should not enter holdout automatically.",
                "dataset_splits": ["holdout"],
                "provenance": {
                    "source_trace_id": "trace_002",
                    "source_episode_id": "episode_002",
                    "source_harness_gap": "validation",
                    "generation_reason": "bad generated split",
                    "creator_version": "gym-v1-test",
                    "created_at": "2026-05-15T00:00:00Z",
                    "allowed_splits": ["holdout"],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="holdout"):
        materialize_dataset_bundle("generated_cases", project_root=tmp_path)


def test_materialize_chat_reviewed_multiturn_rejects_unreviewed_rows(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "chat_reviewed_multiturn.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "raw_chat_leak",
                "prompt": "This raw chat row should not become a supervised case.",
                "approval": {"status": "pending"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="positive review"):
        materialize_dataset_bundle("chat_reviewed_multiturn", project_root=tmp_path)


def test_materialize_dataset_rejects_unknown_training_tier(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "custom_prompt_tasks.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "bad_tier",
                "prompt": "Do something.",
                "training_tier": "expert",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="training tier"):
        materialize_dataset_bundle("custom_prompt_jsonl", project_root=tmp_path)
