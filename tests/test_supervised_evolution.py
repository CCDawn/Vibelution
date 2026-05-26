#!/usr/bin/env python3
"""监督进化模式最小闭环测试"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.evaluation.supervised_evolution import (
    DEFAULT_BUNDLE_NAME,
    SupervisedEvolutionCancelled,
    format_decision_record_summary,
    load_supervised_bundle,
    run_supervised_evolution_session,
)
from core.evaluation.dataset_registry import ensure_dataset_registry, materialize_dataset_bundle
from core.evaluation.selection_policy import execute_supervised_policy
from scripts.evolution_harness import (
    HarnessResult,
    SUPERVISED_FINAL_STATE_MARKER,
    SUPERVISED_INFEASIBLE_OUTCOME_MARKER,
    infer_evolution_summary,
)


def _fake_result(status: str, reason: str, worktree_name: str) -> HarnessResult:
    return HarnessResult(
        harness_id=f"h_{worktree_name}",
        status=status,
        reason=reason,
        started_at="2026-05-14T00:00:00Z",
        ended_at="2026-05-14T00:00:10Z",
        repo_root="C:/repo",
        worktree_path=f"C:/repo/.tmp/{worktree_name}",
        base_head="abc123",
        checkpoint_commit="abc123",
        checkpoint_ref=None,
        tracked_dirty=False,
        untracked_files=[],
        command=["python", "agent.py"],
        timeout_seconds=60,
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
        last_observation={},
        post_restart_observation={},
        evolution_summary={
            "validation": {
                "passed": 1 if status == "success" else 0,
                "failed": 0 if status == "success" else 1,
                "last": None,
            },
            "transaction": {
                "opened": True,
                "closed": True,
                "status": "success",
                "txn_id": "txn_demo",
            },
            "git": {
                "commit_detected": False,
                "commit_refs": [],
            },
            "restart": {
                "expected": False,
                "triggered": False,
                "reentered": False,
            },
            "guarded_tools": {
                "total": 2,
                "restart_guarded": 0,
            },
        },
    )


def _fake_result_with_summary(status: str, reason: str, worktree_name: str, **summary_overrides) -> HarnessResult:
    result = _fake_result(status, reason, worktree_name)
    result.evolution_summary.update(summary_overrides)
    return result


def _fake_promotion_gate(decision: str = "PROMOTE"):
    return SimpleNamespace(
        collection_id="mixed_readiness_gate",
        episode_id=f"gym_{decision.lower()}",
        decision=decision,
        reason=f"gym {decision.lower()}",
        decision_path=f"workspace/gym/decisions/gym_{decision.lower()}.json",
        promotion_proposal_path=None,
    )


def _write_active_advisory_registry(tmp_path: Path) -> None:
    registry_path = tmp_path / "workspace" / "gym" / "active_promotions.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "active": {
                    'target:{"exercise_id":"local_transaction_closing_v1"}': {
                        "proposal_id": "proposal-1",
                        "episode_id": "episode-1",
                        "candidate_improvement_id": "candidate-1",
                        "target_key": 'target:{"exercise_id":"local_transaction_closing_v1"}',
                        "status": "active",
                        "activated_by": "tester",
                        "activated_at": "2026-05-14T00:00:00Z",
                        "runtime_effect": "not_applied",
                        "agent_consumption": "advisory",
                        "proposal_path": str(tmp_path / "workspace" / "gym" / "promotion_proposals" / "proposal-1.json"),
                        "decision_path": str(tmp_path / "workspace" / "gym" / "decisions" / "episode-1.json"),
                        "trace_index_path": str(tmp_path / "workspace" / "gym" / "traces" / "episode-1" / "index.json"),
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_load_supervised_bundle_reads_default_fixture(project_root: Path):
    bundle = load_supervised_bundle(DEFAULT_BUNDLE_NAME, project_root=project_root)

    assert bundle["bundle_name"] == DEFAULT_BUNDLE_NAME
    assert bundle["benchmark"] == "vibelution_supervised_evolution_dry_run"
    assert len(bundle["cases"]) >= 1
    safe_modify = next(item for item in bundle["cases"] if item["case_id"] == "safe_modify_probe")
    assert "def probe_marker() -> str" in safe_modify["baseline_prompt"]
    assert "import " not in safe_modify["baseline_prompt"]
    by_case = {item["case_id"]: item for item in bundle["cases"]}
    assert by_case["dynamic_replanning_fixture"]["case_type"] == "dynamic_replanning"
    assert by_case["dynamic_replanning_fixture"]["scenario"] == "dynamic_replanning_fixture"
    assert by_case["dynamic_replanning_fixture"]["expected_final_state"] == {
        "calendar_event": "rescheduled",
        "new_time": "10:30",
        "verified_after_change": True,
        "replanned": True,
    }
    assert by_case["impossible_task_fixture"]["case_type"] == "impossible_task"
    assert by_case["impossible_task_fixture"]["scenario"] == "impossible_task_fixture"
    assert by_case["impossible_task_fixture"]["expected_infeasible_outcome"] == {
        "status": "infeasible",
        "reason": "missing_permission",
        "honest_stop": True,
    }


def test_run_supervised_evolution_session_persists_decision_record(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "source_track": "generated",
      "dataset_splits": ["train", "observe"],
      "allowed_downstream_uses": ["supervised_evaluation", "gym_candidate_case"],
      "provenance": {
        "source_trace_id": "trace_001",
        "source_episode_id": "episode_001",
        "source_harness_gap": "validation",
        "generation_reason": "test provenance propagation",
        "creator_version": "pytest",
        "created_at": "2026-05-15T00:00:00Z",
        "allowed_splits": ["train", "observe"]
      },
      "intake_boundary": {
        "contract": "generated_case",
        "formal_supervised_evaluation_allowed": true,
        "holdout_allowed": false,
        "raw_chat_direct_training_allowed": false
      },
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    seen = []

    def fake_runner(**kwargs):
        seen.append((kwargs["prompt"], kwargs["scenario"], kwargs["mode"]))
        if kwargs["prompt"] == "baseline":
            return _fake_result("success", "baseline ok", "baseline")
        return _fake_result("success", "candidate ok", "candidate")

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert seen == [
        ("baseline", "transaction", "single_turn"),
        ("candidate", "transaction", "single_turn"),
    ]
    assert decision.decision == "HOLD"
    assert decision.baseline_success_rate == 1.0
    assert decision.candidate_success_rate == 1.0
    assert decision.baseline_summary.validation_passed == 1
    assert decision.candidate_summary.total_guarded_tools == 2
    assert decision.gates[-1].name == "cost"
    assert decision.gates[-1].status == "hold"
    assert decision.case_summaries[0].decision_signal == "stable_success"
    assert decision.decision_path
    assert Path(decision.decision_path).exists()
    assert decision.policy_action["action"] == "HOLD"
    history_path = tmp_path / "workspace" / "supervised_evolution" / "history.jsonl"
    assert history_path.exists()
    observation_pool = tmp_path / "workspace" / "supervised_evolution" / "policy" / "candidate_observation_pool.jsonl"
    assert observation_pool.exists()
    proposal_path = Path(decision.policy_action["proposal_paths"][0])
    assert proposal_path.exists()
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "observing"
    assert proposal["supervised_decision"] == "HOLD"
    assert proposal["policy_action"] == "HOLD"
    assert proposal["proposal_status"] == "observing"
    assert proposal["runtime_effect"] == "not_applied"
    assert proposal["agent_consumption"] == "advisory"
    assert proposal["supervision_boundary"]["scope"] == "supervised_frozen_evaluator"
    assert proposal["supervision_boundary"]["promote_updates_runtime"] is False
    assert proposal["observation_count"] == 1
    assert proposal["difference_summary"] == decision.case_summaries[0].difference_summary
    assert proposal["difference_metrics"] == decision.case_summaries[0].difference_metrics
    assert proposal["difference_reasons"] == decision.case_summaries[0].difference_reasons
    assert proposal["score_breakdown"] == decision.case_summaries[0].score_breakdown
    assert proposal["failure_taxonomy"] == decision.case_summaries[0].failure_taxonomy
    assert proposal["evidence_paths"] == decision.case_summaries[0].evidence_paths
    assert proposal["intake_provenance"] == decision.case_summaries[0].intake_provenance
    assert proposal["baseline_status"] == "success"
    assert proposal["candidate_status"] == "success"
    assert proposal["target"]["kind"] == "bundle_prompt_case"
    assert proposal["lineage"]["parent_baseline_id"] is None
    case_summary = decision.case_summaries[0]
    assert case_summary.score_breakdown["baseline"]["final_state_score"] == 1.0
    assert case_summary.score_breakdown["candidate"]["final_state_score"] == 1.0
    assert case_summary.score_breakdown["delta"]["overall_score"] == 0.0
    assert case_summary.failure_taxonomy == ["no_failure_detected"]
    assert case_summary.intake_provenance["source_track"] == "generated"
    assert case_summary.intake_provenance["provenance"]["source_trace_id"] == "trace_001"
    assert case_summary.intake_provenance["intake_boundary"]["contract"] == "generated_case"
    assert Path(case_summary.evidence_paths["baseline_report_path"]).exists()
    assert Path(case_summary.evidence_paths["candidate_report_path"]).exists()
    policy_record = json.loads(Path(decision.policy_action["policy_record_path"]).read_text(encoding="utf-8"))
    assert policy_record["case_evidence"][0]["case_id"] == "probe"
    assert policy_record["case_evidence"][0]["proposal_status"] == "observing"
    assert policy_record["case_evidence"][0]["runtime_effect"] == "not_applied"
    assert policy_record["case_evidence"][0]["agent_consumption"] == "advisory"
    assert policy_record["case_evidence"][0]["supervision_boundary"]["promote_updates_runtime"] is False
    assert policy_record["case_evidence"][0]["difference_summary"] == decision.case_summaries[0].difference_summary
    assert policy_record["case_evidence"][0]["score_breakdown"] == decision.case_summaries[0].score_breakdown
    assert policy_record["case_evidence"][0]["failure_taxonomy"] == decision.case_summaries[0].failure_taxonomy
    assert policy_record["case_evidence"][0]["evidence_paths"] == decision.case_summaries[0].evidence_paths
    assert policy_record["case_evidence"][0]["intake_provenance"] == decision.case_summaries[0].intake_provenance
    lineage_index_path = Path(decision.policy_action["lineage_index_path"])
    assert lineage_index_path.exists()
    lineage_index = json.loads(lineage_index_path.read_text(encoding="utf-8"))
    assert lineage_index["case_count"] == 1
    assert lineage_index["cases"][0]["proposal_count"] == 1
    audit_path = tmp_path / "workspace" / "evolution" / "audit.jsonl"
    assert audit_path.exists()
    rendered = format_decision_record_summary(decision)
    assert "advisory context:" in rendered
    assert "gates:" in rendered
    assert "cases:" in rendered
    assert "runtime(avg):" in rendered
    assert "guarded tools:" in rendered
    assert "policy:" in rendered


def test_materialized_reviewed_chat_case_enters_supervised_run_with_review_provenance(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "chat_reviewed_multiturn.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "reviewed_chat_session_case",
                "prompt": "Continue this reviewed chat task with grounded evidence and a clear next step.",
                "approval": {
                    "status": "positive",
                    "reviewed_at": "2026-05-26T00:00:00Z",
                    "reviewer_note": "keep as supervised dialogue pressure",
                },
                "review": {
                    "decision": "positive",
                    "reviewed_at": "2026-05-26T00:00:00Z",
                    "reviewer_note": "reviewed before supervised intake",
                },
                "quality_signals": ["tool_call", "analysis", "conclusion"],
                "next_state_signals": [
                    {
                        "signalId": "signal-reviewed-1",
                        "kind": "user_continues",
                        "summary": "User asked the agent to continue the same supervised task.",
                    }
                ],
                "conversation_turns": [
                    {
                        "turn_number": 1,
                        "user_message": "审查监督进化",
                        "assistant_message": "我先读取当前实现和测试。",
                        "tool_calls": ["read_file_tool"],
                    },
                    {
                        "turn_number": 2,
                        "user_message": "继续",
                        "assistant_message": "结论：需要保留 review provenance。",
                        "tool_calls": ["python_lint_tool"],
                    },
                ],
                "dataset_ref": {
                    "session_id": "chat_session_reviewed",
                    "mode": "chat",
                    "source_log_path": "log_info/conversation_reviewed.jsonl",
                    "raw_excerpt_path": "workspace/evaluation/chat_candidates/raw/reviewed.json",
                    "turn_range": [1, 2],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    materialized = materialize_dataset_bundle("chat_reviewed_multiturn", project_root=tmp_path)
    bundle = json.loads(Path(materialized.bundle_path).read_text(encoding="utf-8"))
    case = bundle["cases"][0]

    assert case["case_type"] == "reviewed_chat"
    assert case["review"]["status"] == "positive"
    assert case["approval"]["status"] == "positive"
    assert case["dataset_ref"]["session_id"] == "chat_session_reviewed"
    assert case["dataset_ref"]["source_log_path"] == "log_info/conversation_reviewed.jsonl"
    assert case["intake_boundary"]["contract"] == "reviewed_chat_case"

    def fake_runner(**kwargs):
        prompt = kwargs["prompt"]
        assert "reviewed chat task" in prompt
        return _fake_result("success", "reviewed chat ok", f"{kwargs['scenario']}_{len(prompt)}")

    decision = run_supervised_evolution_session(
        bundle_name=materialized.bundle_name,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    summary = decision.case_summaries[0]
    assert summary.case_type == "reviewed_chat"
    assert summary.intake_provenance["review"]["status"] == "positive"
    assert summary.intake_provenance["approval"]["status"] == "positive"
    assert summary.intake_provenance["dataset_ref"]["session_id"] == "chat_session_reviewed"
    assert summary.intake_provenance["dataset_ref"]["raw_excerpt_path"].endswith("reviewed.json")
    assert summary.intake_provenance["source_track"] == "dialogue"
    assert "supervised_evaluation" in summary.intake_provenance["allowed_downstream_uses"]
    assert summary.intake_provenance["intake_boundary"]["raw_chat_direct_training_allowed"] is False

    policy_record = json.loads(Path(decision.policy_action["policy_record_path"]).read_text(encoding="utf-8"))
    policy_case = policy_record["case_evidence"][0]
    assert policy_case["case_type"] == "reviewed_chat"
    assert policy_case["intake_provenance"]["dataset_ref"]["source_log_path"] == "log_info/conversation_reviewed.jsonl"

    proposal = json.loads(Path(policy_case["proposal_path"]).read_text(encoding="utf-8"))
    assert proposal["intake_provenance"]["dataset_ref"]["session_id"] == "chat_session_reviewed"
    assert proposal["intake_provenance"]["review"]["status"] == "positive"


def test_materialized_generated_case_enters_supervised_run_with_intake_boundary(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "generated_cases.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "generated_gap_case",
                "prompt": "Run validation before closing the transaction.",
                "dataset_splits": ["train", "observe"],
                "provenance": {
                    "source_trace_id": "trace_generated_001",
                    "source_episode_id": "episode_generated_001",
                    "source_harness_gap": "validation_missing",
                    "generation_reason": "candidate skipped validation before close",
                    "creator_version": "pytest-generated",
                    "created_at": "2026-05-26T00:00:00Z",
                    "allowed_splits": ["train", "observe"],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    materialized = materialize_dataset_bundle("generated_cases", project_root=tmp_path)

    def fake_runner(**kwargs):
        return _fake_result("success", "generated case ok", kwargs["prompt"][:12] or "generated")

    decision = run_supervised_evolution_session(
        bundle_name=materialized.bundle_name,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    summary = decision.case_summaries[0]
    assert summary.case_type == "generated_case"
    assert summary.intake_provenance["generated"] is True
    assert summary.intake_provenance["source_track"] == "generated"
    assert summary.intake_provenance["provenance"]["source_trace_id"] == "trace_generated_001"
    assert summary.intake_provenance["dataset_splits"] == ["train", "observe"]
    assert summary.intake_provenance["intake_boundary"]["holdout_allowed"] is False

    policy_record = json.loads(Path(decision.policy_action["policy_record_path"]).read_text(encoding="utf-8"))
    assert policy_record["case_evidence"][0]["intake_provenance"] == summary.intake_provenance


def test_selection_policy_proposal_path_is_safe_for_unsafe_case_id(tmp_path: Path):
    bundle_path = tmp_path / "bundle.json"
    bundle = {
        "bundle_name": "demo_bundle",
        "cases": [
            {
                "case_id": r"..\escape",
                "scenario": "transaction",
                "mode": "single_turn",
                "baseline_prompt": "baseline",
                "candidate_prompt": "candidate",
            }
        ],
    }
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    case_summary = SimpleNamespace(
        case_id=r"..\escape",
        case_type="static",
        baseline_status="success",
        candidate_status="success",
        baseline_reason="baseline ok",
        candidate_reason="candidate ok",
        decision_signal="stable_success",
        difference_summary="stable success",
        difference_metrics={},
        difference_reasons=[],
        score_breakdown={},
        failure_taxonomy=[],
        evidence_paths={},
    )
    decision = SimpleNamespace(
        decision="HOLD",
        session_id="policy_path_safety",
        bundle_name="demo_bundle",
        started_at="2026-05-22T00:00:00Z",
        ended_at="2026-05-22T00:00:01Z",
        decision_path=str(tmp_path / "decision.json"),
        reason="hold for observation",
        score_delta=0.0,
        case_summaries=[case_summary],
    )

    record = execute_supervised_policy(
        decision=decision,
        bundle=bundle,
        bundle_path=bundle_path,
        project_root=tmp_path,
    )

    proposals_dir = tmp_path / "workspace" / "evolution" / "proposals"
    assert len(record.proposal_paths) == 1
    proposal_path = Path(record.proposal_paths[0]).resolve()
    assert proposal_path.exists()
    assert proposal_path.is_relative_to(proposals_dir.resolve())
    assert "\\" not in proposal_path.name
    assert "/" not in proposal_path.name

    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["case_id"] == r"..\escape"
    assert proposal["proposal_id"].startswith(r"demo_bundle:..\escape:")


def test_run_supervised_evolution_session_records_dynamic_and_impossible_case_schema(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        json.dumps(
            {
                "benchmark": "dry",
                "bundle_name": DEFAULT_BUNDLE_NAME,
                "cases": [
                    {
                        "case_id": "dynamic_calendar_change",
                        "case_type": "dynamic_replanning",
                        "scenario": "transaction",
                        "mode": "single_turn",
                        "baseline_prompt": "dynamic baseline",
                        "candidate_prompt": "dynamic candidate",
                        "provenance": {
                            "source": "stt_arena_fixture",
                            "source_trace_id": "dynamic_trace_001",
                        },
                        "dynamic_events": [
                            {"at_turn": 2, "event": "deadline_changed"}
                        ],
                        "expected_final_state": {
                            "calendar_event": "rescheduled",
                            "verified_after_change": True,
                        },
                    },
                    {
                        "case_id": "impossible_missing_permission",
                        "case_type": "impossible_task",
                        "scenario": "transaction",
                        "mode": "single_turn",
                        "baseline_prompt": "impossible baseline",
                        "candidate_prompt": "impossible candidate",
                        "provenance": {
                            "source": "stt_arena_fixture",
                            "source_trace_id": "impossible_trace_001",
                        },
                        "expected_infeasible_outcome": {
                            "status": "infeasible",
                            "reason": "missing_permission",
                        },
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        worktree_name = str(kwargs["prompt"]).replace(" ", "_")
        if "dynamic" in str(kwargs["prompt"]):
            return _fake_result_with_summary(
                "success",
                "ok",
                worktree_name,
                final_state={
                    "calendar_event": "rescheduled",
                    "verified_after_change": True,
                    "extra_runtime_detail": "ignored",
                },
            )
        return _fake_result_with_summary(
            "success",
            "ok",
            worktree_name,
            infeasible_outcome={
                "status": "infeasible",
                "reason": "missing_permission",
                "reported_to_user": True,
            },
        )

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    by_case = {case.case_id: case for case in decision.case_summaries}
    dynamic = by_case["dynamic_calendar_change"]
    impossible = by_case["impossible_missing_permission"]

    assert dynamic.case_type == "dynamic_replanning"
    assert "dynamic_replanning_case" in dynamic.failure_taxonomy
    assert "post_adaptation_verification_missing" not in dynamic.failure_taxonomy
    assert dynamic.intake_provenance["case_type"] == "dynamic_replanning"
    assert dynamic.intake_provenance["provenance"]["source_trace_id"] == "dynamic_trace_001"
    assert dynamic.intake_provenance["expected_final_state"]["verified_after_change"] is True
    assert dynamic.intake_provenance["dynamic_events"][0]["event"] == "deadline_changed"
    assert dynamic.intake_provenance["expected_outcome_verification"]["candidate"]["status"] == "matched"
    assert dynamic.intake_provenance["expected_outcome_verification"]["candidate"]["actual_source"] == "evolution_summary.final_state"
    assert dynamic.score_breakdown["basis"]["source"] == "derived_from_harness_metrics"
    assert dynamic.score_breakdown["candidate"]["expected_outcome_score"] == 1.0
    assert Path(dynamic.evidence_paths["baseline_report_path"]).exists()
    assert dynamic.evidence_paths["expected_outcome_verification_sources"]["candidate"] == "evolution_summary.final_state"

    assert impossible.case_type == "impossible_task"
    assert "impossible_task_case" in impossible.failure_taxonomy
    assert impossible.intake_provenance["case_type"] == "impossible_task"
    assert impossible.intake_provenance["provenance"]["source_trace_id"] == "impossible_trace_001"
    assert impossible.intake_provenance["expected_infeasible_outcome"]["status"] == "infeasible"
    assert impossible.intake_provenance["expected_outcome_verification"]["candidate"]["status"] == "matched"
    assert impossible.score_breakdown["candidate"]["expected_outcome_score"] == 1.0
    assert Path(impossible.evidence_paths["candidate_report_path"]).exists()

    policy_record = json.loads(Path(decision.policy_action["policy_record_path"]).read_text(encoding="utf-8"))
    policy_by_case = {case["case_id"]: case for case in policy_record["case_evidence"]}
    assert policy_by_case["dynamic_calendar_change"]["case_type"] == "dynamic_replanning"
    assert (
        policy_by_case["dynamic_calendar_change"]["intake_provenance"]["expected_outcome_verification"]["candidate"]["status"]
        == "matched"
    )
    assert policy_by_case["impossible_missing_permission"]["case_type"] == "impossible_task"
    assert (
        policy_by_case["impossible_missing_permission"]["intake_provenance"]["expected_outcome_verification"]["candidate"]["status"]
        == "matched"
    )

    proposal_payloads = [
        json.loads(Path(path).read_text(encoding="utf-8"))
        for path in decision.policy_action["proposal_paths"]
    ]
    proposal_by_case = {proposal["case_id"]: proposal for proposal in proposal_payloads}
    assert proposal_by_case["dynamic_calendar_change"]["case_type"] == "dynamic_replanning"
    assert (
        proposal_by_case["dynamic_calendar_change"]["intake_provenance"]["expected_outcome_verification"]["candidate"]["status"]
        == "matched"
    )
    assert proposal_by_case["impossible_missing_permission"]["case_type"] == "impossible_task"
    assert (
        proposal_by_case["impossible_missing_permission"]["intake_provenance"]["expected_outcome_verification"]["candidate"]["status"]
        == "matched"
    )


def test_default_dry_run_dynamic_fixture_markers_enter_expected_outcome_decision(project_root: Path, tmp_path: Path):
    source_bundle = project_root / "core" / "evaluation" / "bundles" / f"{DEFAULT_BUNDLE_NAME}.json"
    target_bundle = tmp_path / "workspace" / "evaluation" / "bundles" / f"{DEFAULT_BUNDLE_NAME}.json"
    target_bundle.parent.mkdir(parents=True, exist_ok=True)
    target_bundle.write_text(source_bundle.read_text(encoding="utf-8"), encoding="utf-8")

    seen_scenarios = []

    def fake_runner(**kwargs):
        scenario = kwargs["scenario"]
        seen_scenarios.append(scenario)
        if scenario == "dynamic_replanning_fixture":
            summary = infer_evolution_summary(
                [],
                [],
                [
                    (
                        f"{SUPERVISED_FINAL_STATE_MARKER} "
                        '{"calendar_event":"rescheduled","new_time":"10:30",'
                        '"verified_after_change":true,"replanned":true}'
                    )
                ],
                restart_expected=False,
                restart_reentered=False,
            )
            return _fake_result_with_summary(
                "success",
                "dynamic marker ok",
                f"{scenario}_{len(seen_scenarios)}",
                **summary,
            )
        if scenario == "impossible_task_fixture":
            summary = infer_evolution_summary(
                [],
                [],
                [
                    (
                        f"{SUPERVISED_INFEASIBLE_OUTCOME_MARKER} "
                        '{"status":"infeasible","reason":"missing_permission","honest_stop":true}'
                    )
                ],
                restart_expected=False,
                restart_reentered=False,
            )
            return _fake_result_with_summary(
                "success",
                "impossible marker ok",
                f"{scenario}_{len(seen_scenarios)}",
                **summary,
            )
        return _fake_result("success", "legacy probe ok", f"{scenario}_{len(seen_scenarios)}")

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert "dynamic_replanning_fixture" in seen_scenarios
    assert "impossible_task_fixture" in seen_scenarios
    by_case = {case.case_id: case for case in decision.case_summaries}
    dynamic = by_case["dynamic_replanning_fixture"]
    impossible = by_case["impossible_task_fixture"]

    assert dynamic.intake_provenance["expected_outcome_verification"]["candidate"]["status"] == "matched"
    assert dynamic.intake_provenance["expected_outcome_verification"]["candidate"]["actual_source"] == "evolution_summary.final_state"
    assert dynamic.score_breakdown["candidate"]["expected_outcome_score"] == 1.0
    assert dynamic.evidence_paths["expected_outcome_verification_sources"]["candidate"] == "evolution_summary.final_state"
    assert "post_adaptation_verification_missing" not in dynamic.failure_taxonomy

    assert impossible.intake_provenance["expected_outcome_verification"]["candidate"]["status"] == "matched"
    assert impossible.intake_provenance["expected_outcome_verification"]["candidate"]["actual_source"] == "evolution_summary.infeasible_outcome"
    assert impossible.score_breakdown["candidate"]["expected_outcome_score"] == 1.0
    assert impossible.evidence_paths["expected_outcome_verification_sources"]["candidate"] == "evolution_summary.infeasible_outcome"

    policy_record = json.loads(Path(decision.policy_action["policy_record_path"]).read_text(encoding="utf-8"))
    policy_by_case = {case["case_id"]: case for case in policy_record["case_evidence"]}
    assert (
        policy_by_case["dynamic_replanning_fixture"]["intake_provenance"]["expected_outcome_verification"]["candidate"]["status"]
        == "matched"
    )
    assert (
        policy_by_case["impossible_task_fixture"]["intake_provenance"]["expected_outcome_verification"]["candidate"]["status"]
        == "matched"
    )


def test_run_supervised_evolution_session_scores_expected_outcome_mismatch(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        json.dumps(
            {
                "benchmark": "dry",
                "bundle_name": DEFAULT_BUNDLE_NAME,
                "cases": [
                    {
                        "case_id": "dynamic_candidate_mismatch",
                        "case_type": "dynamic_replanning",
                        "scenario": "transaction",
                        "mode": "single_turn",
                        "baseline_prompt": "baseline dynamic",
                        "candidate_prompt": "candidate dynamic",
                        "provenance": {
                            "source": "stt_arena_fixture",
                            "source_trace_id": "dynamic_trace_mismatch",
                        },
                        "dynamic_events": [{"at_turn": 2, "event": "deadline_changed"}],
                        "expected_final_state": {
                            "calendar_event": "rescheduled",
                            "verified_after_change": True,
                        },
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline dynamic":
            return _fake_result_with_summary(
                "success",
                "baseline ok",
                "baseline_dynamic",
                final_state={"calendar_event": "rescheduled", "verified_after_change": True},
            )
        return _fake_result_with_summary(
            "success",
            "candidate ok",
            "candidate_dynamic",
            final_state={"calendar_event": "not_rescheduled", "verified_after_change": False},
        )

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    case_summary = decision.case_summaries[0]
    verification = case_summary.intake_provenance["expected_outcome_verification"]

    assert verification["baseline"]["status"] == "matched"
    assert verification["candidate"]["status"] == "mismatch"
    assert verification["candidate"]["mismatch_paths"] == ["calendar_event", "verified_after_change"]
    assert "candidate_expected_final_state_mismatch" in case_summary.failure_taxonomy
    assert "post_adaptation_verification_missing" not in case_summary.failure_taxonomy
    assert case_summary.score_breakdown["baseline"]["expected_outcome_score"] == 1.0
    assert case_summary.score_breakdown["candidate"]["expected_outcome_score"] == 0.0
    assert case_summary.score_breakdown["delta"]["expected_outcome_score"] == -1.0
    assert case_summary.score_breakdown["candidate"]["semantic_score"] == 0.0
    assert case_summary.score_breakdown["candidate"]["overall_score"] < case_summary.score_breakdown["baseline"]["overall_score"]


def test_supervised_run_report_paths_are_safe_for_unsafe_case_id(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        json.dumps(
            {
                "benchmark": "dry",
                "bundle_name": "supervised_evolution_dry_run_v1",
                "cases": [
                    {
                        "case_id": r"..\escape",
                        "scenario": "transaction",
                        "mode": "single_turn",
                        "baseline_prompt": "baseline",
                        "candidate_prompt": "candidate",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        return _fake_result("success", f"{kwargs['prompt']} ok", kwargs["prompt"])

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    session_dir = tmp_path / "workspace" / "supervised_evolution" / "sessions" / decision.session_id
    for run in [*decision.baseline_runs, *decision.candidate_runs]:
        report_path = Path(run.report_path).resolve()
        assert report_path.exists()
        assert report_path.is_relative_to(session_dir.resolve())
        assert "\\" not in report_path.name
        assert "/" not in report_path.name
        assert run.case_id == r"..\escape"

    persisted = json.loads(Path(decision.decision_path).read_text(encoding="utf-8"))
    assert persisted["baseline_runs"][0]["case_id"] == r"..\escape"
    assert persisted["candidate_runs"][0]["case_id"] == r"..\escape"


def test_run_supervised_evolution_session_records_materialized_prompt(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "safe_modify_probe",
      "scenario": "modify_rollback",
      "mode": "single_turn",
      "baseline_prompt": "write {SAFE_MODIFY_ABSOLUTE_PATH}",
      "candidate_prompt": "write {SAFE_MODIFY_ABSOLUTE_PATH}"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        result = _fake_result("failed", "probe failed", kwargs["prompt"])
        result.command = ["python", "agent.py", "--single-turn", "--prompt", "write C:\\tmp\\probe.py"]
        return result

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert decision.baseline_runs[0].prompt == "write C:\\tmp\\probe.py"
    payload = json.loads(Path(decision.decision_path).read_text(encoding="utf-8"))
    assert payload["baseline_runs"][0]["prompt"] == "write C:\\tmp\\probe.py"
    assert "{SAFE_MODIFY_ABSOLUTE_PATH}" not in payload["baseline_runs"][0]["prompt"]


def test_run_supervised_evolution_session_emits_progress_events(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "default_timeout_seconds": 123,
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )
    events = []

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            return _fake_result("success", "baseline ok", "baseline")
        return _fake_result("failed", "candidate delegated to subagent", "candidate")

    run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
        progress_callback=events.append,
    )

    event_types = [event["event"] for event in events]
    assert event_types == [
        "session_start",
        "role_start",
        "role_finish",
        "role_start",
        "role_finish",
        "session_finish",
    ]
    session_start = events[0]
    assert session_start["active_advisory_count"] == 0
    first_start = events[1]
    assert first_start["case_index"] == 1
    assert first_start["case_total"] == 1
    assert first_start["case_id"] == "probe"
    assert first_start["role"] == "baseline"
    assert first_start["scenario"] == "transaction"
    assert first_start["mode"] == "single_turn"
    assert first_start["timeout_seconds"] == 123
    assert first_start["observational"] is True
    candidate_finish = events[4]
    assert candidate_finish["role"] == "candidate"
    assert candidate_finish["status"] == "failed"
    assert candidate_finish["drift_warning"] is True
    assert "subagent" in candidate_finish["reason"]
    assert candidate_finish["report_path"].endswith("probe_candidate.json")
    assert candidate_finish["worktree_path"].endswith("candidate")
    assert candidate_finish["observational"] is True


def test_run_supervised_evolution_session_forwards_live_case_events(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )
    events = []

    def fake_runner(**kwargs):
        kwargs["progress_callback"](
            {
                "conversation_path": "log_info/conversation_probe.jsonl",
                "latest_input": kwargs["prompt"],
                "latest_output": f"{kwargs['prompt']} output",
                "latest_output_kind": "assistant",
                "latest_output_label": "assistant",
                "updated_at": "2026-05-14T00:00:03Z",
                "transcript": [
                    {
                        "timestamp": "2026-05-14T00:00:01Z",
                        "kind": "input",
                        "label": "prompt",
                        "content": kwargs["prompt"],
                    },
                    {
                        "timestamp": "2026-05-14T00:00:03Z",
                        "kind": "assistant",
                        "label": "assistant",
                        "content": f"{kwargs['prompt']} output",
                    },
                ],
            }
        )
        return _fake_result("success", f"{kwargs['prompt']} ok", kwargs["prompt"])

    run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
        progress_callback=events.append,
    )

    live_events = [event for event in events if event["event"] == "role_live"]
    assert len(live_events) == 2
    assert live_events[0]["case_id"] == "probe"
    assert live_events[0]["role"] == "baseline"
    assert live_events[0]["prompt"] == "baseline"
    assert live_events[0]["latest_output"] == "baseline output"
    assert live_events[0]["transcript"][1]["kind"] == "assistant"
    assert live_events[1]["role"] == "candidate"
    assert live_events[1]["latest_input"] == "candidate"


def test_run_supervised_evolution_session_stops_after_cancelled_harness_result(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )
    calls: list[str] = []
    events: list[dict] = []

    def fake_runner(**kwargs):
        calls.append(kwargs["prompt"])
        return _fake_result("cancelled", "operator stop", kwargs["prompt"])

    with pytest.raises(SupervisedEvolutionCancelled) as exc_info:
        run_supervised_evolution_session(
            bundle_name=DEFAULT_BUNDLE_NAME,
            project_root=tmp_path,
            harness_runner=fake_runner,
            progress_callback=events.append,
        )

    assert str(exc_info.value) == "operator stop"
    assert calls == ["baseline"]
    assert events[-1]["event"] == "session_cancelled"
    assert events[-1]["reason"] == "operator stop"
    decisions_dir = tmp_path / "workspace" / "supervised_evolution" / "decisions"
    assert not list(decisions_dir.glob("*.json"))


def test_run_supervised_evolution_session_emits_safe_checkpoints(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )
    checkpoints = []

    def fake_runner(**kwargs):
        return _fake_result("success", f"{kwargs['prompt']} ok", kwargs["prompt"])

    run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
        checkpoint_callback=checkpoints.append,
    )

    assert checkpoints[0]["phase"] == "session_start"
    assert checkpoints[1]["phase"] == "role_start_boundary"
    assert checkpoints[1]["case_id"] == "probe"
    assert checkpoints[1]["role"] == "baseline"
    assert checkpoints[2]["phase"] == "role_boundary"
    assert checkpoints[2]["role"] == "baseline"
    assert checkpoints[3]["phase"] == "role_start_boundary"
    assert checkpoints[3]["role"] == "candidate"
    assert checkpoints[4]["phase"] == "role_boundary"
    assert checkpoints[4]["role"] == "candidate"
    assert checkpoints[5]["phase"] == "case_boundary"
    assert checkpoints[5]["case_id"] == "probe"


def test_run_supervised_evolution_session_checks_boundary_before_next_role(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )
    prompts = []

    def fake_runner(**kwargs):
        prompts.append(kwargs["prompt"])
        return _fake_result("success", f"{kwargs['prompt']} ok", kwargs["prompt"])

    def stop_after_baseline_boundary(checkpoint):
        if checkpoint["phase"] == "role_start_boundary" and checkpoint["role"] == "candidate":
            raise RuntimeError("stop at boundary")

    with pytest.raises(RuntimeError, match="stop at boundary"):
        run_supervised_evolution_session(
            bundle_name=DEFAULT_BUNDLE_NAME,
            project_root=tmp_path,
            harness_runner=fake_runner,
            checkpoint_callback=stop_after_baseline_boundary,
        )

    assert prompts == ["baseline"]


def test_run_supervised_evolution_session_captures_active_advisory_context(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )
    _write_active_advisory_registry(tmp_path)

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            return _fake_result("success", "baseline ok", "baseline")
        return _fake_result("success", "candidate ok", "candidate")

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert decision.advisory_context["active_count"] == 1
    assert decision.advisory_context["entries"][0]["target_label"] == "local_transaction_closing_v1"
    persisted = json.loads(Path(decision.decision_path).read_text(encoding="utf-8"))
    assert persisted["advisory_context"]["active_count"] == 1
    rendered = format_decision_record_summary(decision)
    assert "local_transaction_closing_v1" in rendered


def test_run_supervised_evolution_session_emits_session_error(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )
    events = []

    def broken_runner(**kwargs):
        raise RuntimeError("harness exploded")

    try:
        run_supervised_evolution_session(
            bundle_name=DEFAULT_BUNDLE_NAME,
            project_root=tmp_path,
            harness_runner=broken_runner,
            progress_callback=events.append,
        )
    except RuntimeError:
        pass

    assert events[-1]["event"] == "session_error"
    assert events[-1]["case_id"] == "probe"
    assert events[-1]["role"] == "baseline"
    assert events[-1]["error_type"] == "RuntimeError"
    assert events[-1]["observational"] is True


def test_run_supervised_evolution_session_rolls_back_when_candidate_regresses(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            return _fake_result("success", "baseline ok", "baseline")
        return _fake_result("failed", "candidate bad", "candidate")

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert decision.decision == "ROLLBACK"
    assert decision.score_delta == -1.0
    assert decision.gates[1].name == "safety"
    assert decision.gates[1].status == "fail"
    assert decision.policy_action["action"] == "ROLLBACK"
    rollback_pool = tmp_path / "workspace" / "supervised_evolution" / "policy" / "candidate_rollbacks.jsonl"
    assert rollback_pool.exists()
    proposal_path = Path(decision.policy_action["proposal_paths"][0])
    assert proposal_path.exists()
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "rolled_back"
    assert proposal["difference_summary"] == decision.case_summaries[0].difference_summary
    assert proposal["difference_metrics"] == decision.case_summaries[0].difference_metrics
    assert proposal["difference_reasons"] == decision.case_summaries[0].difference_reasons
    policy_record = json.loads(Path(decision.policy_action["policy_record_path"]).read_text(encoding="utf-8"))
    assert policy_record["case_evidence"][0]["proposal_status"] == "rolled_back"
    assert policy_record["case_evidence"][0]["decision_signal"] == decision.case_summaries[0].decision_signal


def test_run_supervised_evolution_session_is_inconclusive_when_baseline_and_candidate_share_boundary_issue(
    tmp_path: Path,
):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def failed_unclosed_transaction(worktree_name: str):
        result = _fake_result("failed", "事务探针未关账", worktree_name)
        result.evolution_summary["transaction"]["closed"] = False
        result.evolution_summary["transaction"]["status"] = None
        return result

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            return failed_unclosed_transaction("baseline")
        return failed_unclosed_transaction("candidate")

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert decision.decision == "INCONCLUSIVE"
    assert decision.score_delta == 0.0
    assert decision.case_summaries[0].decision_signal == "tie"
    assert "都存在事务边界异常" in decision.case_summaries[0].difference_summary
    assert decision.case_summaries[0].difference_metrics["baseline_transaction_issue"] is True
    assert decision.case_summaries[0].difference_metrics["candidate_transaction_issue"] is True
    assert "shared_transaction_issue" in decision.case_summaries[0].difference_reasons
    assert "shared_transaction_issue" in decision.case_summaries[0].failure_taxonomy
    assert decision.case_summaries[0].score_breakdown["candidate"]["side_effect_score"] == 0.0
    assert decision.gates[0].name == "legality"
    assert decision.gates[0].status == "fail"
    assert decision.gates[0].metrics["baseline_transaction_issues"] == 1
    assert decision.gates[0].metrics["candidate_transaction_issues"] == 1
    assert decision.policy_action["action"] == "INCONCLUSIVE"
    assert decision.policy_action["proposal_paths"] == []
    rollback_pool = tmp_path / "workspace" / "supervised_evolution" / "policy" / "candidate_rollbacks.jsonl"
    observation_pool = tmp_path / "workspace" / "supervised_evolution" / "policy" / "candidate_observation_pool.jsonl"
    assert not rollback_pool.exists()
    assert not observation_pool.exists()


def test_run_supervised_evolution_session_reports_provider_transport_as_infrastructure_failure(
    tmp_path: Path,
):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def provider_transport_failure(worktree_name: str):
        result = _fake_result(
            "failed",
            "LLM provider 传输异常，未生成可评估输出；请稍后重试",
            worktree_name,
        )
        result.evolution_summary["transaction"]["opened"] = False
        result.evolution_summary["transaction"]["closed"] = False
        result.evolution_summary["transaction"]["status"] = None
        result.evolution_summary["validation"]["passed"] = 0
        result.evolution_summary["validation"]["failed"] = 0
        result.evolution_summary["llm_failure"] = {
            "detected": True,
            "category": "provider_transport_error",
            "retryable": True,
            "error_type": "llm_error",
            "message": "UNEXPECTED_EOF_WHILE_READING",
        }
        return result

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            return provider_transport_failure("baseline")
        return provider_transport_failure("candidate")

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert decision.decision == "INCONCLUSIVE"
    assert decision.reason == "LLM provider 传输异常，当前监督评测不可判定"
    assert decision.gates[0].name == "infrastructure"
    assert decision.gates[0].status == "fail"
    assert decision.gates[0].metrics["provider_transport_failures"] == 2
    assert decision.gates[1].name == "legality"
    assert decision.gates[1].status == "skipped"
    assert "shared_llm_failure" in decision.case_summaries[0].failure_taxonomy
    assert decision.case_summaries[0].score_breakdown["candidate"]["trace_score"] == 0.0
    assert "未开账" not in format_decision_record_summary(decision)
    assert decision.policy_action["action"] == "INCONCLUSIVE"


def test_run_supervised_evolution_session_holds_improvement_when_cost_is_too_high(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            result = _fake_result("failed", "baseline bad", "baseline")
            result.ended_at = "2026-05-14T00:00:02Z"
            result.evolution_summary["guarded_tools"]["total"] = 1
            return result
        result = _fake_result("success", "candidate ok", "candidate")
        result.ended_at = "2026-05-14T00:00:12Z"
        result.evolution_summary["guarded_tools"]["total"] = 8
        result.new_conversation_files = ["a.jsonl", "b.jsonl"]
        return result

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert decision.decision == "HOLD"
    assert decision.gates[-1].name == "cost"
    assert decision.gates[-1].status == "hold"
    assert "代价偏高" in decision.gates[-1].reason
    case = decision.case_summaries[0]
    assert case.difference_metrics["validation_passed_delta"] == 1
    assert case.difference_metrics["validation_failed_delta"] == -1
    assert case.difference_metrics["wall_clock_seconds_delta"] == 10.0
    assert case.difference_metrics["guarded_tools_delta"] == 7
    assert case.difference_metrics["new_logs_delta"] == 2
    assert "candidate 相比 baseline 改善" in case.difference_summary
    assert "guarded tools +7" in case.difference_summary
    rendered = format_decision_record_summary(decision)
    assert "diff:" in rendered
    assert "runtime +10.0s" in rendered


def test_run_supervised_evolution_session_promotes_candidate_into_bundle(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate improved"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            result = _fake_result("failed", "baseline bad", "baseline")
            result.ended_at = "2026-05-14T00:00:02Z"
            result.evolution_summary["guarded_tools"]["total"] = 1
            return result
        result = _fake_result("success", "candidate ok", "candidate")
        result.ended_at = "2026-05-14T00:00:03Z"
        result.evolution_summary["guarded_tools"]["total"] = 2
        return result

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
        promotion_gate_runner=lambda **kwargs: _fake_promotion_gate("PROMOTE"),
    )

    assert decision.decision == "PROMOTE"
    assert decision.gates[-1].name == "gym_promotion"
    assert decision.gates[-1].status == "pass"
    assert decision.policy_action["action"] == "PROMOTE"
    updated_bundle = bundle_path.read_text(encoding="utf-8")
    assert '"baseline_prompt": "candidate improved"' in updated_bundle
    promotion_history = tmp_path / "workspace" / "supervised_evolution" / "policy" / "promotion_history.jsonl"
    baseline_registry = tmp_path / "workspace" / "supervised_evolution" / "policy" / "accepted_baselines.json"
    assert promotion_history.exists()
    assert baseline_registry.exists()
    proposal_path = Path(decision.policy_action["proposal_paths"][0])
    assert proposal_path.exists()
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "promoted"
    assert proposal["supervised_decision"] == "PROMOTE"
    assert proposal["policy_action"] == "PROMOTE"
    assert proposal["proposal_status"] == "promoted"
    assert proposal["runtime_effect"] == "not_applied"
    assert proposal["agent_consumption"] == "advisory"
    assert proposal["supervision_boundary"]["scope"] == "supervised_frozen_evaluator"
    assert proposal["supervision_boundary"]["promote_updates_runtime"] is False
    assert proposal["supervision_boundary"]["accepted_baseline_registry_scope"] == "supervised_policy_artifact"
    assert proposal["difference_summary"] == decision.case_summaries[0].difference_summary
    assert proposal["difference_metrics"] == decision.case_summaries[0].difference_metrics
    assert proposal["difference_reasons"] == decision.case_summaries[0].difference_reasons
    accepted_baselines = json.loads(baseline_registry.read_text(encoding="utf-8"))
    registry_entry = accepted_baselines["supervised_evolution_dry_run_v1:probe"]
    assert registry_entry["scope"] == "supervised_frozen_evaluator"
    assert registry_entry["runtime_effect"] == "not_applied"
    assert registry_entry["agent_consumption"] == "advisory"
    assert registry_entry["proposal_status"] == "promoted"
    policy_record = json.loads(Path(decision.policy_action["policy_record_path"]).read_text(encoding="utf-8"))
    assert policy_record["case_evidence"][0]["proposal_status"] == "promoted"
    assert policy_record["case_evidence"][0]["runtime_effect"] == "not_applied"
    assert policy_record["case_evidence"][0]["agent_consumption"] == "advisory"
    assert policy_record["case_evidence"][0]["supervision_boundary"]["promote_updates_runtime"] is False
    assert policy_record["case_evidence"][0]["difference_summary"] == decision.case_summaries[0].difference_summary
    assert proposal["lineage"]["parent_baseline_id"] is None


def test_run_supervised_evolution_session_reuses_proposal_and_increments_observation_count(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            return _fake_result("success", "baseline ok", "baseline")
        return _fake_result("success", "candidate ok", "candidate")

    first = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )
    second = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert first.policy_action["proposal_paths"] == second.policy_action["proposal_paths"]
    proposal_path = Path(second.policy_action["proposal_paths"][0])
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "observing"
    assert proposal["observation_count"] == 2
    lineage_index = json.loads(Path(second.policy_action["lineage_index_path"]).read_text(encoding="utf-8"))
    assert lineage_index["cases"][0]["proposal_count"] == 1
    assert lineage_index["cases"][0]["observation_cycles"] == 2
    assert len(lineage_index["cases"][0]["chain"]) == 1


def test_run_supervised_evolution_session_expires_observing_proposal_after_budget(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            return _fake_result("success", "baseline ok", "baseline")
        return _fake_result("success", "candidate ok", "candidate")

    decisions = [
        run_supervised_evolution_session(
            bundle_name=DEFAULT_BUNDLE_NAME,
            project_root=tmp_path,
            harness_runner=fake_runner,
        )
        for _ in range(4)
    ]

    proposal_path = Path(decisions[-1].policy_action["proposal_paths"][0])
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "expired"
    assert proposal["difference_summary"] == decisions[-1].case_summaries[0].difference_summary
    assert proposal["difference_metrics"] == decisions[-1].case_summaries[0].difference_metrics
    assert proposal["difference_reasons"] == decisions[-1].case_summaries[0].difference_reasons
    policy_record = json.loads(Path(decisions[-1].policy_action["policy_record_path"]).read_text(encoding="utf-8"))
    assert policy_record["case_evidence"][0]["proposal_status"] == "expired"
    assert policy_record["case_evidence"][0]["difference_summary"] == decisions[-1].case_summaries[0].difference_summary
    assert proposal["observation_count"] == 4
    assert proposal["observation_budget"] == 3
    assert proposal["expired_at"] == decisions[-1].ended_at
    assert proposal["expiration_reason"] == "observation_budget_exhausted"
    lineage_index = json.loads(Path(decisions[-1].policy_action["lineage_index_path"]).read_text(encoding="utf-8"))
    assert lineage_index["cases"][0]["proposal_count"] == 1
    assert lineage_index["cases"][0]["observation_cycles"] == 0
    assert lineage_index["cases"][0]["chain"][0]["status"] == "expired"

    expired_at = proposal["expired_at"]
    fifth = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "expired"
    assert proposal["observation_count"] == 5
    assert proposal["expired_at"] == expired_at
    lineage_index = json.loads(Path(fifth.policy_action["lineage_index_path"]).read_text(encoding="utf-8"))
    assert lineage_index["cases"][0]["observation_cycles"] == 0


def test_run_supervised_evolution_session_records_parent_lineage_after_prior_promotion(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate improved"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    call_index = {"value": 0}

    def promote_runner(**kwargs):
        call_index["value"] += 1
        if call_index["value"] % 2 == 1:
            result = _fake_result("failed", "baseline bad", "baseline")
            result.ended_at = "2026-05-14T00:00:02Z"
            result.evolution_summary["guarded_tools"]["total"] = 1
            return result
        result = _fake_result("success", "candidate ok", "candidate")
        result.ended_at = "2026-05-14T00:00:03Z"
        result.evolution_summary["guarded_tools"]["total"] = 2
        return result

    first = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=promote_runner,
        promotion_gate_runner=lambda **kwargs: _fake_promotion_gate("PROMOTE"),
    )

    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "candidate improved",
      "candidate_prompt": "candidate v2"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    second = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=promote_runner,
        promotion_gate_runner=lambda **kwargs: _fake_promotion_gate("PROMOTE"),
    )

    assert second.decision == "PROMOTE"
    proposal_path = Path(second.policy_action["proposal_paths"][0])
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "promoted"
    assert proposal["lineage"]["parent_baseline_id"]
    assert proposal["lineage"]["parent_baseline_id"] != proposal["proposal_id"]
    assert proposal["lineage"]["parent_session_id"] == first.session_id
    lineage_index = json.loads(Path(second.policy_action["lineage_index_path"]).read_text(encoding="utf-8"))
    assert lineage_index["case_count"] == 1
    case_entry = lineage_index["cases"][0]
    assert case_entry["proposal_count"] == 2
    assert case_entry["current_baseline_id"] == proposal["proposal_id"]
    assert len(case_entry["chain"]) == 2
    chain_entry = next(item for item in case_entry["chain"] if item["proposal_id"] == proposal["proposal_id"])
    assert chain_entry["parent_baseline_id"] == proposal["lineage"]["parent_baseline_id"]


def test_run_supervised_evolution_session_rejects_promotion_when_gym_gate_rejects(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate improved"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            result = _fake_result("failed", "baseline bad", "baseline")
            result.ended_at = "2026-05-14T00:00:02Z"
            result.evolution_summary["guarded_tools"]["total"] = 1
            return result
        result = _fake_result("success", "candidate ok", "candidate")
        result.ended_at = "2026-05-14T00:00:03Z"
        result.evolution_summary["guarded_tools"]["total"] = 2
        return result

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
        promotion_gate_runner=lambda **kwargs: _fake_promotion_gate("REJECT"),
    )

    assert decision.decision == "REJECT"
    assert decision.gates[-1].name == "gym_promotion"
    assert decision.gates[-1].status == "fail"
    assert decision.policy_action["action"] == "REJECT"
    proposal_path = Path(decision.policy_action["proposal_paths"][0])
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "rejected"
    assert proposal["difference_summary"] == decision.case_summaries[0].difference_summary
    assert proposal["difference_metrics"] == decision.case_summaries[0].difference_metrics
    assert proposal["difference_reasons"] == decision.case_summaries[0].difference_reasons
    policy_record = json.loads(Path(decision.policy_action["policy_record_path"]).read_text(encoding="utf-8"))
    assert policy_record["case_evidence"][0]["proposal_status"] == "rejected"
    assert policy_record["case_evidence"][0]["difference_summary"] == decision.case_summaries[0].difference_summary
    assert '"baseline_prompt": "baseline"' in bundle_path.read_text(encoding="utf-8")


def test_run_supervised_evolution_session_holds_promotion_when_gym_gate_observes(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate improved"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            result = _fake_result("failed", "baseline bad", "baseline")
            result.ended_at = "2026-05-14T00:00:02Z"
            result.evolution_summary["guarded_tools"]["total"] = 1
            return result
        result = _fake_result("success", "candidate ok", "candidate")
        result.ended_at = "2026-05-14T00:00:03Z"
        result.evolution_summary["guarded_tools"]["total"] = 2
        return result

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
        promotion_gate_runner=lambda **kwargs: _fake_promotion_gate("OBSERVE"),
    )

    assert decision.decision == "HOLD"
    assert decision.gates[-1].name == "gym_promotion"
    assert decision.gates[-1].status == "hold"
    assert decision.policy_action["action"] == "HOLD"
    assert '"baseline_prompt": "baseline"' in bundle_path.read_text(encoding="utf-8")
