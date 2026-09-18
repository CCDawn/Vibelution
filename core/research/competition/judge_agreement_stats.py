# -*- coding: utf-8 -*-
"""监督进化链路「评审质量纵向面板」的纯计算层（judge-agreement stats）。

把监督 worktree 进化的历史 run 快照转成「评估器的评估」证据：
Judge 判定（auto 侧）× 独立审批 Agent 决定（human 侧）的一致性矩阵、
Cohen's kappa 与 CI、假自动批准率单侧上界，以及分数漂移序列。统计口径
全部复用 G12 校准门冻结的 ``calibration_stats``（决策 #13），不另造轮子。

映射约定（与决策 #13 的 escalate 正类语义对齐）：

- auto 侧 = Judge：``APPROVE`` → ``auto_approve``；``REVISE``/``REJECT``
  等其他判定 → ``auto_escalate``。
- human 侧 = 独立审批 Agent：``APPROVE`` → ``approve``；
  ``RERUN_REQUIRED``/``REJECT`` → ``escalate``。
- ``riskClass`` 固定 ``low``（监督环自身的门承担风险分级），
  ``domain`` = executionMode（real/simulation 分层统计）。

设计决策（v1, 2026-09-18）：

- 一致性样本只收「Judge 与审批决定都在场」的终态 run；缺任一侧判定的
  run（如中途失败）只进分数/时序统计，不进 kappa——宁缺毋滥，防伪造证据。
- 分数统计按 executionMode 分层（simulation 的分数由确定性假件产生，与
  real 不可比）；漂移以时间序列原样输出（按 finishedAt 升序），不做平滑，
  下游自行选择窗口。
- ``No I/O, no state, no network; every function is deterministic.``
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from statistics import mean, median
from typing import Any

from .calibration_stats import (
    CalibrationStatsError,
    build_confusion_matrix,
    cohens_kappa_with_ci,
    false_auto_approve_upper_bound,
)

_JUDGE_POSITIVE = "APPROVE"
_APPROVAL_POSITIVE = "APPROVE"

_OUTCOME_APPROVAL_MAP = {
    "approval_rerun_required": "RERUN_REQUIRED",
    "approval_rejected": "REJECT",
    "approval_approved": "APPROVE",
    "approval_timeout": "RERUN_REQUIRED",
}


def _approval_decision(run: Mapping[str, Any]) -> str:
    decision, _mode = _approval_decision_entry(run)
    return decision


def _approval_decision_entry(run: Mapping[str, Any]) -> tuple[str, str]:
    """Return (decision, approvalMode) for one run snapshot.

    ``approvalMode == "human"`` 的裁决是人工锚点：与 Judge 同模型族的审批
    Agent 存在相关性误差（Meta-Evaluation Collapse 一致但共同偏差的风险），
    人工裁决优先作为 kappa 的 human 侧真值。
    """
    approval = run.get("approvalDecision")
    if isinstance(approval, Mapping):
        decision = str(approval.get("decision") or "").strip().upper()
        mode = str(approval.get("mode") or "").strip().lower()
        if decision:
            return decision, (mode or "agent")
    outcome = str(run.get("outcome") or "").strip().lower()
    return _OUTCOME_APPROVAL_MAP.get(outcome, ""), "agent"


@dataclass(frozen=True, slots=True)
class ScoreSeriesPoint:
    runId: str
    finishedAt: str
    executionMode: str
    baselineScore: float
    candidateScore: float
    scoreDelta: float


@dataclass(frozen=True, slots=True)
class ModeScoreStats:
    executionMode: str
    scoredRuns: int
    improvedRuns: int
    harmedRuns: int
    meanDelta: float
    medianDelta: float
    meanBaseline: float
    meanCandidate: float


@dataclass(frozen=True, slots=True)
class JudgeAgreementReport:
    totalRuns: int
    agreementPairs: int
    confusionMatrix: dict[str, int]
    kappa: dict[str, Any]
    falseAutoApproveUpperBounds: dict[str, Any]
    scoreStatsByMode: dict[str, dict[str, Any]]
    scoreSeries: list[dict[str, Any]] = field(default_factory=list)
    # 人工锚点（approvalMode=="human" 的裁决）与 agent 审批复立统计；
    # 顶层 confusionMatrix/kappa 优先取人工锚定样本，回落 agent 样本。
    topLevelSampleSource: str = "agent"
    anchoredPairs: int = 0
    anchoredConfusionMatrix: dict[str, int] = field(default_factory=dict)
    anchoredKappa: dict[str, Any] = field(default_factory=dict)
    agentPairs: int = 0
    agentConfusionMatrix: dict[str, int] = field(default_factory=dict)
    agentKappa: dict[str, Any] = field(default_factory=dict)


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _mode_score_stats(mode: str, points: Sequence[ScoreSeriesPoint]) -> ModeScoreStats:
    deltas = [point.scoreDelta for point in points]
    return ModeScoreStats(
        executionMode=mode,
        scoredRuns=len(points),
        improvedRuns=sum(1 for delta in deltas if delta > 0),
        harmedRuns=sum(1 for delta in deltas if delta < 0),
        meanDelta=mean(deltas) if deltas else 0.0,
        medianDelta=median(deltas) if deltas else 0.0,
        meanBaseline=mean([p.baselineScore for p in points]) if points else 0.0,
        meanCandidate=mean([p.candidateScore for p in points]) if points else 0.0,
    )


def build_judge_agreement_report(runs: Sequence[Mapping[str, Any]]) -> JudgeAgreementReport:
    """Compute the judge-quality panel over supervised run snapshots.

    Snapshots may come in any order; the score series is sorted by
    ``finishedAt`` ascending and falls back to ``startedAt``.
    """
    anchored_records: list[dict[str, str]] = []
    agent_records: list[dict[str, str]] = []
    series: list[ScoreSeriesPoint] = []
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        decision = run.get("decision") if isinstance(run.get("decision"), Mapping) else {}
        judge_decision = str(decision.get("judgeDecision") or "").strip().upper()
        approval_decision, approval_mode = _approval_decision_entry(run)
        mode = str(run.get("executionMode") or "").strip().lower()
        if judge_decision and approval_decision:
            record = {
                "autoDecision": (
                    "auto_approve"
                    if judge_decision == _JUDGE_POSITIVE
                    else "auto_escalate"
                ),
                "humanDecision": (
                    "approve"
                    if approval_decision == _APPROVAL_POSITIVE
                    else "escalate"
                ),
                "riskClass": "low",
                "domain": mode or "unknown",
                "runId": str(run.get("runId") or ""),
            }
            if approval_mode == "human":
                anchored_records.append(record)
            else:
                agent_records.append(record)
        baseline = _float_or_none(decision.get("baselineScore"))
        candidate = _float_or_none(decision.get("candidateScore"))
        if baseline is not None and candidate is not None:
            series.append(
                ScoreSeriesPoint(
                    runId=str(run.get("runId") or ""),
                    finishedAt=str(run.get("finishedAt") or run.get("startedAt") or ""),
                    executionMode=mode or "unknown",
                    baselineScore=baseline,
                    candidateScore=candidate,
                    scoreDelta=candidate - baseline,
                )
            )

    anchored_confusion = build_confusion_matrix(anchored_records)
    anchored_kappa = cohens_kappa_with_ci(anchored_confusion)
    agent_confusion = build_confusion_matrix(agent_records)
    agent_kappa = cohens_kappa_with_ci(agent_confusion)
    # 顶层视图向后兼容：有人工锚点用锚定样本，否则回落 agent 样本。
    if anchored_records:
        confusion, kappa_result, top_source = (
            anchored_confusion,
            anchored_kappa,
            "anchored",
        )
        calibration_size = len(anchored_records)
    else:
        confusion, kappa_result, top_source = agent_confusion, agent_kappa, "agent"
        calibration_size = len(agent_records)
    bounds: dict[str, Any] = {"trialsAutoApproved": 0, "falseAutoApproves": 0}
    auto_approved = confusion.false_negatives + confusion.true_negatives
    bounds["trialsAutoApproved"] = auto_approved
    bounds["falseAutoApproves"] = confusion.false_auto_approve_count
    if auto_approved >= 1:
        for method in ("wilson", "beta_binomial"):
            bounds[method] = false_auto_approve_upper_bound(
                trials=auto_approved,
                failures=confusion.false_auto_approve_count,
                method=method,
            )

    series.sort(key=lambda point: point.finishedAt)
    by_mode: dict[str, list[ScoreSeriesPoint]] = {}
    for point in series:
        by_mode.setdefault(point.executionMode, []).append(point)
    stats_by_mode = {
        mode: _mode_score_stats_dict(mode, points)
        for mode, points in sorted(by_mode.items())
    }
    return JudgeAgreementReport(
        totalRuns=len(runs),
        agreementPairs=calibration_size,
        confusionMatrix=confusion.as_dict(),
        kappa=kappa_result.as_dict(),
        topLevelSampleSource=top_source,
        anchoredPairs=len(anchored_records),
        anchoredConfusionMatrix=anchored_confusion.as_dict(),
        anchoredKappa=anchored_kappa.as_dict(),
        agentPairs=len(agent_records),
        agentConfusionMatrix=agent_confusion.as_dict(),
        agentKappa=agent_kappa.as_dict(),
        falseAutoApproveUpperBounds=bounds,
        scoreStatsByMode=stats_by_mode,
        scoreSeries=[
            {
                "runId": point.runId,
                "finishedAt": point.finishedAt,
                "executionMode": point.executionMode,
                "baselineScore": point.baselineScore,
                "candidateScore": point.candidateScore,
                "scoreDelta": point.scoreDelta,
            }
            for point in series
        ],
    )


def _mode_score_stats_dict(mode: str, points: Sequence[ScoreSeriesPoint]) -> dict[str, Any]:
    stats = _mode_score_stats(mode, points)
    return {
        "executionMode": stats.executionMode,
        "scoredRuns": stats.scoredRuns,
        "improvedRuns": stats.improvedRuns,
        "harmedRuns": stats.harmedRuns,
        "meanDelta": stats.meanDelta,
        "medianDelta": stats.medianDelta,
        "meanBaseline": stats.meanBaseline,
        "meanCandidate": stats.meanCandidate,
    }


__all__ = [
    "JudgeAgreementReport",
    "ModeScoreStats",
    "ScoreSeriesPoint",
    "build_judge_agreement_report",
    "CalibrationStatsError",
]
