"""Pure contracts for the supervised three-session Judge loop."""

from __future__ import annotations

import json
from typing import Any


JUDGE_DECISIONS = {"PROMOTE", "HOLD", "REJECT", "INCONCLUSIVE"}
JUDGE_DIMENSIONS = (
    "task_understanding",
    "tool_trace_quality",
    "validation_evidence",
    "safety_and_scope",
)


def build_judge_evaluation_prompt(
    *,
    phase: str,
    baseline_evaluation: dict[str, Any],
    rerun_evaluation: dict[str, Any] | None = None,
    previous_judgment: dict[str, Any] | None = None,
    candidate_variant: dict[str, Any] | None = None,
) -> str:
    normalized_phase = str(phase or "").strip().lower()
    if normalized_phase not in {"baseline", "rerun"}:
        raise ValueError(f"Unsupported Judge phase: {phase}")
    second_turn = normalized_phase == "rerun"
    phase_instruction = (
        "这是同一 Judge 会话中的第二次评估。保持第一次使用的量表、证据标准和任务理解，"
        "比较独立复跑轨迹与第一次基线轨迹。"
        if second_turn
        else
        "这是同一 Judge 会话中的第一次评估。冻结本轮量表和证据标准，"
        "对基线真实运行轨迹评分，并给出可直接交给基线 Agent 的改进指令。"
    )
    decision_instruction = (
        "decision 只能为 PROMOTE、HOLD、REJECT、INCONCLUSIVE。只有证据充分且改进后得分更高时才可 PROMOTE。"
        if second_turn
        else
        "第一次评估的 decision 使用 HOLD；此时尚未看到独立复跑，不得 PROMOTE。"
    )
    payload = {
        "baselineEvaluation": _bounded_evaluation(baseline_evaluation),
        "previousJudgment": _bounded_mapping(previous_judgment or {}),
        "rerunEvaluation": _bounded_evaluation(rerun_evaluation or {}) if second_turn else {},
        "candidateVariant": _bounded_mapping(candidate_variant or {}) if second_turn else {},
    }
    return (
        "你是监督进化 Judge Agent，只负责读取运行证据、评分、给出改进反馈和合入建议；"
        "不要修改代码，不要运行 git merge，不要把测试通过率直接当作质量分。\n"
        f"{phase_instruction}\n"
        "评分范围 0..1，必须分别评估 task_understanding、tool_trace_quality、"
        "validation_evidence、safety_and_scope。缺少轨迹或证据时必须 INCONCLUSIVE。\n"
        f"{decision_instruction}\n"
        "最后单独输出一行严格 JSON：\n"
        'SUPERVISED_AGENT_JUDGMENT: {"phase":"'
        f'{normalized_phase}'
        '","decision":"HOLD","score":0.0,"baseline_score":0.0,'
        '"problems":[],"improvement_instructions":[],"dimensions":'
        '{"task_understanding":0.0,"tool_trace_quality":0.0,'
        '"validation_evidence":0.0,"safety_and_scope":0.0},"evidence_refs":[]}\n'
        "证据包：\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    )


def build_improvement_prompt(
    *,
    baseline_evaluation: dict[str, Any],
    baseline_judgment: dict[str, Any],
    requested_goal: str = "",
) -> str:
    problems = _string_list(baseline_judgment.get("problems"))
    instructions = _string_list(
        baseline_judgment.get("improvementInstructions")
        or baseline_judgment.get("improvement_instructions")
    )
    evidence_refs = _string_list(
        baseline_judgment.get("evidenceRefs")
        or baseline_judgment.get("evidence_refs")
    )
    goal = str(requested_goal or "").strip()
    payload = {
        "baselineSummary": str(baseline_evaluation.get("summary") or "")[:1000],
        "baselineExecution": {
            "successes": baseline_evaluation.get("successes"),
            "total": baseline_evaluation.get("total"),
        },
        "judgeScore": baseline_judgment.get("score"),
        "problems": problems,
        "improvementInstructions": instructions,
        "evidenceRefs": evidence_refs,
        "requestedGoal": goal,
    }
    return (
        "PHASE: BASELINE_SELF_EDIT_IMPLEMENTATION\n"
        "你就是刚才执行基线评测的基线 Agent。继续当前会话，保留你对任务、工具调用和失败轨迹的上下文。\n"
        "当前阶段是基线 Agent 的代码实施阶段，不是 Judge 评分阶段。"
        "禁止输出 SUPERVISED_AGENT_JUDGMENT，禁止重复评分或生成裁决。\n"
        "Judge Agent 已完成第一次独立评分。请在当前隔离 worktree 中依据反馈自行定位并修改代码，"
        "然后运行必要的聚焦验证。不要提交、不要合并、不要修改主工作区或机器全局配置。\n"
        "Judge 反馈是建议而不是事实；如果反馈与代码证据冲突，以可复现证据为准并在会话中说明。\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    )


def normalize_judge_evaluation(
    payload: dict[str, Any],
    *,
    expected_phase: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Judge judgment must be an object.")
    phase = str(payload.get("phase") or "").strip().lower()
    normalized_expected = str(expected_phase or "").strip().lower()
    if phase != normalized_expected:
        raise ValueError(f"Judge phase mismatch: expected {normalized_expected}, got {phase or '-'}")
    decision = str(payload.get("decision") or "").strip().upper()
    if decision not in JUDGE_DECISIONS:
        raise ValueError("Judge decision must be PROMOTE, HOLD, REJECT, or INCONCLUSIVE.")
    if phase == "baseline" and decision == "PROMOTE":
        raise ValueError("Baseline Judge decision cannot be PROMOTE before an independent rerun.")
    score = _score_percent(payload.get("score"), field="score")
    baseline_score_value = payload.get("baseline_score", payload.get("baselineScore"))
    baseline_score = (
        _score_percent(baseline_score_value, field="baseline_score")
        if baseline_score_value is not None
        else (score if phase == "baseline" else None)
    )
    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, dict):
        raise ValueError("Judge dimensions are required.")
    dimensions = {
        dimension: _score_percent(raw_dimensions.get(dimension), field=f"dimensions.{dimension}")
        for dimension in JUDGE_DIMENSIONS
    }
    return {
        "status": "success",
        "phase": phase,
        "decision": decision,
        "score": score,
        "baselineScore": baseline_score,
        "problems": _string_list(payload.get("problems")),
        "improvementInstructions": _string_list(
            payload.get("improvement_instructions")
            or payload.get("improvementInstructions")
        ),
        "dimensions": dimensions,
        "evidenceRefs": _string_list(payload.get("evidence_refs") or payload.get("evidenceRefs")),
    }


def judge_merge_allowed(judgment: dict[str, Any], *, force: bool = False) -> bool:
    if str(judgment.get("status") or "").strip().lower() != "success":
        return False
    if str(judgment.get("phase") or "").strip().lower() != "rerun":
        return False
    decision = str(judgment.get("decision") or "").strip().upper()
    return decision == "PROMOTE" or (force and decision in JUDGE_DECISIONS)


def _score_percent(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Judge {field} must be numeric.")
    score = float(value)
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"Judge {field} must be in 0..1.")
    return round(score * 100.0, 3)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:500] for item in value if str(item or "").strip()][:20]


def _bounded_evaluation(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    cases = value.get("cases") if isinstance(value.get("cases"), list) else []
    return {
        "role": str(value.get("role") or "")[:80],
        "status": str(value.get("status") or "")[:80],
        "summary": str(value.get("summary") or "")[:2000],
        "successes": value.get("successes"),
        "total": value.get("total"),
        "failures": value.get("failures"),
        "cases": [_bounded_mapping(item) for item in cases[:20] if isinstance(item, dict)],
    }


def _bounded_mapping(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in list(value.items())[:40]:
        normalized_key = str(key)[:100]
        if isinstance(item, str):
            result[normalized_key] = item[:2000]
        elif isinstance(item, (int, float, bool)) or item is None:
            result[normalized_key] = item
        elif isinstance(item, list):
            result[normalized_key] = [
                _bounded_mapping(entry) if isinstance(entry, dict) else str(entry)[:500]
                for entry in item[:20]
            ]
        elif isinstance(item, dict):
            result[normalized_key] = _bounded_mapping(item)
    return result
