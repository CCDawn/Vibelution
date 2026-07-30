import pytest

from core.web.services.supervised_judge_closed_loop import (
    build_improvement_prompt,
    build_judge_evaluation_prompt,
    build_judge_rubric_prompt,
    judge_merge_allowed,
    normalize_judge_evaluation,
    normalize_judge_rubric,
)


def _rubric():
    return normalize_judge_rubric(
        {
            "phase": "rubric",
            "task_summary": "修复失败恢复并保留可验证证据",
            "criteria": [
                {
                    "id": "failure_recovery",
                    "label": "失败恢复",
                    "description": "失败后能够恢复并保持状态一致。",
                    "weight": 0.6,
                    "evidence_requirements": ["失败路径轨迹", "恢复后的验证结果"],
                },
                {
                    "id": "task_completion",
                    "label": "任务完成度",
                    "description": "完整实现本次任务合同。",
                    "weight": 0.4,
                    "evidence_requirements": ["任务结果", "聚焦验证"],
                },
            ],
        },
        task_contract={"goal": "修复失败恢复", "cases": [{"caseId": "one", "prompt": "recover"}]},
    )


def test_judge_generates_task_rubric_from_task_contract_before_seeing_baseline_result():
    prompt = build_judge_rubric_prompt(
        task_contract={
            "goal": "修复失败恢复",
            "bundleName": "recovery_v1",
            "cases": [{"caseId": "one", "prompt": "recover after provider failure"}],
        }
    )

    assert "本轮要评估的任务合同" in prompt
    assert "recover after provider failure" in prompt
    assert "SUPERVISED_AGENT_JUDGMENT:" in prompt
    assert '"phase":"rubric"' in prompt
    assert "baselineEvaluation" not in prompt
    assert "baseline_score" not in prompt


def test_judge_rubric_is_frozen_with_task_specific_and_system_fixed_criteria():
    rubric = _rubric()
    repeated = _rubric()

    assert rubric["status"] == "success"
    assert rubric["source"] == "judge_agent"
    assert rubric["taskSummary"] == "修复失败恢复并保留可验证证据"
    assert [item["id"] for item in rubric["taskCriteria"]] == [
        "failure_recovery",
        "task_completion",
    ]
    assert rubric["compositionWeights"] == {
        "taskSpecific": 0.7,
        "systemFixed": 0.3,
    }
    assert [item["id"] for item in rubric["systemCriteria"]] == [
        "evidence_verifiability",
        "tool_transaction_discipline",
        "scope_and_safety",
        "recovery_and_state_consistency",
        "efficiency_and_minimality",
    ]
    assert len(rubric["rubricHash"]) == 64
    assert repeated["rubricHash"] == rubric["rubricHash"]


def test_judge_rubric_and_scores_reject_non_finite_numbers():
    with pytest.raises(ValueError, match="must be positive"):
        normalize_judge_rubric(
            {
                "phase": "rubric",
                "criteria": [
                    {
                        "id": "task_completion",
                        "label": "任务完成度",
                        "description": "完成任务。",
                        "weight": float("nan"),
                    },
                    {
                        "id": "task_quality",
                        "label": "任务质量",
                        "description": "结果可信。",
                        "weight": 1.0,
                    },
                ],
            },
            task_contract={"goal": "完成任务"},
        )

    rubric = _rubric()
    with pytest.raises(ValueError, match="must be in 0..1"):
        normalize_judge_evaluation(
            {
                "phase": "baseline",
                "recommendation": "REVISE",
                "rubric_hash": rubric["rubricHash"],
                "task_scores": {
                    "failure_recovery": float("inf"),
                    "task_completion": 0.5,
                },
                "system_scores": {
                    "evidence_verifiability": 0.5,
                    "tool_transaction_discipline": 0.5,
                    "scope_and_safety": 0.5,
                    "recovery_and_state_consistency": 0.5,
                    "efficiency_and_minimality": 0.5,
                },
            },
            expected_phase="baseline",
            rubric=rubric,
        )


def test_judge_prompt_keeps_second_evaluation_in_same_session_context():
    rubric = _rubric()
    prompt = build_judge_evaluation_prompt(
        phase="rerun",
        task_contract={"goal": "修复失败恢复"},
        rubric=rubric,
        baseline_evaluation={"summary": "baseline trace", "cases": [{"caseId": "one", "status": "success"}]},
        rerun_evaluation={"summary": "rerun trace", "cases": [{"caseId": "one", "status": "success"}]},
        previous_judgment={
            "phase": "baseline",
            "score": 42.0,
            "problems": ["缺少失败路径验证"],
            "improvementInstructions": ["补充失败路径验证"],
        },
        candidate_variant={"variantId": "variant-1", "patchSha256": "abc"},
    )

    assert "这是同一 Judge 会话中的第二次评估" in prompt
    assert "缺少失败路径验证" in prompt
    assert "baseline trace" in prompt
    assert "rerun trace" in prompt
    assert rubric["rubricHash"] in prompt
    assert "使用已冻结 rubric" in prompt
    assert "SUPERVISED_AGENT_JUDGMENT:" in prompt


def test_judge_normalization_backend_composes_score_and_keeps_recommendation_advisory():
    rubric = _rubric()
    judgment = normalize_judge_evaluation(
        {
            "phase": "rerun",
            "recommendation": "REJECT",
            "rubric_hash": rubric["rubricHash"],
            "problems": [],
            "improvement_instructions": [],
            "task_scores": {
                "failure_recovery": 0.9,
                "task_completion": 0.8,
            },
            "system_scores": {
                "evidence_verifiability": 0.8,
                "tool_transaction_discipline": 0.7,
                "scope_and_safety": 0.9,
                "recovery_and_state_consistency": 0.6,
                "efficiency_and_minimality": 0.5,
            },
            "evidence_refs": ["case:one"],
        },
        expected_phase="rerun",
        rubric=rubric,
        baseline_score=42.0,
    )

    assert judgment["status"] == "success"
    assert judgment["recommendation"] == "REJECT"
    assert judgment["decision"] == "REJECT"
    assert judgment["taskScore"] == 86.0
    assert judgment["systemScore"] == 75.5
    assert judgment["score"] == 82.85
    assert judgment["baselineScore"] == 42.0
    assert judgment["rubricHash"] == rubric["rubricHash"]
    assert judgment["systemScores"]["scope_and_safety"] == 90.0

    with pytest.raises(ValueError, match="recommendation"):
        normalize_judge_evaluation(
            {"phase": "rerun", "rubric_hash": rubric["rubricHash"]},
            expected_phase="rerun",
            rubric=rubric,
        )

    with pytest.raises(ValueError, match="rubric hash"):
        normalize_judge_evaluation(
            {
                "phase": "rerun",
                "recommendation": "APPROVE",
                "rubric_hash": "stale",
                "task_scores": {},
                "system_scores": {},
            },
            expected_phase="rerun",
            rubric=rubric,
        )


def test_judge_recommendation_never_replaces_the_users_final_decision():
    for recommendation in ("APPROVE", "REVISE", "REJECT", "INCONCLUSIVE"):
        judgment = {
            "status": "success",
            "phase": "rerun",
            "recommendation": recommendation,
        }
        assert judge_merge_allowed(judgment) is True

    assert judge_merge_allowed(
        {"status": "failed", "phase": "rerun", "recommendation": "APPROVE"}
    ) is False
    assert judge_merge_allowed(
        {"status": "success", "phase": "baseline", "recommendation": "APPROVE"}
    ) is False


def test_improvement_prompt_is_for_baseline_agent_and_carries_judge_feedback():
    prompt = build_improvement_prompt(
        baseline_evaluation={"summary": "baseline summary", "successes": 1, "total": 2},
        baseline_judgment={
            "score": 35.0,
            "problems": ["没有验证错误恢复"],
            "improvementInstructions": ["补充错误恢复并运行聚焦测试"],
            "evidenceRefs": ["case:two"],
        },
        requested_goal="提升失败恢复",
    )

    assert "你就是刚才执行基线评测的基线 Agent" in prompt
    assert "继续当前会话" in prompt
    assert prompt.startswith("PHASE: BASELINE_SELF_EDIT_IMPLEMENTATION")
    assert "当前阶段是基线 Agent 的代码实施阶段，不是 Judge 评分阶段" in prompt
    assert "SUPERVISED_AGENT_JUDGMENT" not in prompt
    assert "第一步必须调用仓库检查工具" in prompt
    assert "--candidate-runtime-input" in prompt
    assert "collect_candidate_runtime_extension" in prompt
    assert "最终只允许输出实施结果或 NO_JUSTIFIED_CHANGE" in prompt
    assert "没有验证错误恢复" in prompt
    assert "补充错误恢复并运行聚焦测试" in prompt
    assert "提升失败恢复" in prompt
