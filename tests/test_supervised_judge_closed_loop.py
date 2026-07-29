import pytest

from core.web.services.supervised_judge_closed_loop import (
    build_improvement_prompt,
    build_judge_evaluation_prompt,
    judge_merge_allowed,
    normalize_judge_evaluation,
)


def test_judge_prompt_keeps_second_evaluation_in_same_session_context():
    prompt = build_judge_evaluation_prompt(
        phase="rerun",
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
    assert "SUPERVISED_AGENT_JUDGMENT:" in prompt


def test_judge_normalization_requires_structured_score_and_decision():
    judgment = normalize_judge_evaluation(
        {
            "phase": "rerun",
            "decision": "PROMOTE",
            "score": 0.82,
            "baseline_score": 0.42,
            "problems": [],
            "improvement_instructions": [],
            "dimensions": {
                "task_understanding": 0.9,
                "tool_trace_quality": 0.8,
                "validation_evidence": 0.8,
                "safety_and_scope": 0.78,
            },
            "evidence_refs": ["case:one"],
        },
        expected_phase="rerun",
    )

    assert judgment["status"] == "success"
    assert judgment["decision"] == "PROMOTE"
    assert judgment["score"] == 82.0
    assert judgment["baselineScore"] == 42.0
    assert judgment["dimensions"]["safety_and_scope"] == 78.0

    with pytest.raises(ValueError, match="decision"):
        normalize_judge_evaluation({"phase": "rerun", "score": 0.8}, expected_phase="rerun")

    with pytest.raises(ValueError, match="0..1"):
        normalize_judge_evaluation(
            {
                "phase": "rerun",
                "decision": "PROMOTE",
                "score": 82,
                "baseline_score": 42,
                "dimensions": {
                    "task_understanding": 0.9,
                    "tool_trace_quality": 0.8,
                    "validation_evidence": 0.8,
                    "safety_and_scope": 0.78,
                },
            },
            expected_phase="rerun",
        )


def test_non_promote_judgment_fails_closed_unless_force_is_explicit():
    for decision in ("HOLD", "REJECT", "INCONCLUSIVE", ""):
        judgment = {"status": "success", "phase": "rerun", "decision": decision}
        assert judge_merge_allowed(judgment) is False

    rejected = {"status": "success", "phase": "rerun", "decision": "REJECT"}
    assert judge_merge_allowed(rejected, force=True) is True


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
    assert "没有验证错误恢复" in prompt
    assert "补充错误恢复并运行聚焦测试" in prompt
    assert "提升失败恢复" in prompt
