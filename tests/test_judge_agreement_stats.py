# -*- coding: utf-8 -*-
"""Tests for the supervised judge-agreement panel (pure layer + loader)."""

from __future__ import annotations

import pytest

from core.research.competition.judge_agreement_stats import build_judge_agreement_report
from core.web.services import supervised_judge_quality_service as service


def _run(
    run_id: str,
    *,
    judge: str = "",
    approval: str = "",
    outcome: str = "",
    baseline: float | None = None,
    candidate: float | None = None,
    mode: str = "real",
    finished_at: str = "",
) -> dict:
    return {
        "runId": run_id,
        "executionMode": mode,
        "outcome": outcome,
        "finishedAt": finished_at,
        "decision": {
            "judgeDecision": judge,
            "baselineScore": baseline,
            "candidateScore": candidate,
        },
        "approvalDecision": {"decision": approval, "mode": "agent"},
    }


def test_agreement_matrix_and_kappa_perfect_agreement() -> None:
    runs = [
        _run("a", judge="APPROVE", approval="APPROVE", baseline=30.0, candidate=99.0),
        _run("b", judge="REVISE", approval="RERUN_REQUIRED", baseline=30.0, candidate=11.25),
    ]
    report = build_judge_agreement_report(runs)
    assert report.agreementPairs == 2
    matrix = report.confusionMatrix
    assert matrix["trueNegatives"] == 1  # judge approve + approval approve
    assert matrix["truePositives"] == 1  # judge escalate + approval escalate
    assert matrix["falsePositives"] == 0
    assert matrix["falseNegatives"] == 0
    assert report.kappa["observedAgreement"] == 1.0
    assert report.falseAutoApproveUpperBounds["falseAutoApproves"] == 0


def test_disagreement_counts_as_false_auto_approve() -> None:
    runs = [
        _run("a", judge="APPROVE", approval="APPROVE"),
        _run("b", judge="APPROVE", approval="RERUN_REQUIRED"),
        _run("c", judge="APPROVE", approval="APPROVE"),
    ]
    report = build_judge_agreement_report(runs)
    matrix = report.confusionMatrix
    assert matrix["falseNegatives"] == 1  # judge approved, approval escalated
    assert report.falseAutoApproveUpperBounds["trialsAutoApproved"] == 3
    assert report.falseAutoApproveUpperBounds["falseAutoApproves"] == 1
    assert 0.0 < report.falseAutoApproveUpperBounds["wilson"] <= 1.0


def test_runs_missing_one_side_do_not_enter_agreement() -> None:
    runs = [
        _run("a", judge="APPROVE", approval=""),
        _run("b", judge="", approval="APPROVE", outcome="approval_approved"),
        _run("c", judge="REVISE", approval="RERUN_REQUIRED"),
    ]
    report = build_judge_agreement_report(runs)
    assert report.agreementPairs == 1
    assert report.confusionMatrix["truePositives"] == 1


def test_outcome_maps_to_approval_decision() -> None:
    runs = [_run("a", judge="REVISE", outcome="approval_rerun_required")]
    report = build_judge_agreement_report(runs)
    assert report.agreementPairs == 1
    assert report.confusionMatrix["truePositives"] == 1


def test_score_series_sorted_and_split_by_mode() -> None:
    runs = [
        _run("late", judge="APPROVE", approval="APPROVE", baseline=30.0,
             candidate=99.0, finished_at="2026-09-18T01:36:00Z"),
        _run("early", judge="REVISE", approval="RERUN_REQUIRED", baseline=30.0,
             candidate=11.25, finished_at="2026-09-17T07:42:00Z"),
        _run("sim", judge="APPROVE", approval="APPROVE", baseline=40.0,
             candidate=80.0, mode="simulation", finished_at="2026-09-17T06:00:00Z"),
    ]
    report = build_judge_agreement_report(runs)
    assert [point["runId"] for point in report.scoreSeries] == ["sim", "early", "late"]
    real_stats = report.scoreStatsByMode["real"]
    assert real_stats["scoredRuns"] == 2
    assert real_stats["improvedRuns"] == 1
    assert real_stats["harmedRuns"] == 1
    assert real_stats["meanDelta"] == pytest.approx((69.0 + (-18.75)) / 2)
    sim_stats = report.scoreStatsByMode["simulation"]
    assert sim_stats["scoredRuns"] == 1
    assert sim_stats["meanDelta"] == pytest.approx(40.0)


def test_empty_runs_yield_empty_panel() -> None:
    report = build_judge_agreement_report([])
    assert report.totalRuns == 0
    assert report.agreementPairs == 0
    assert report.scoreSeries == []
    assert report.scoreStatsByMode == {}


def test_loader_delegates_to_run_store(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, int] = {}

    def fake_list(limit: int = 20, *, summary_only: bool = False):
        captured["limit"] = limit
        return [
            _run("a", judge="APPROVE", approval="APPROVE", baseline=1.0, candidate=2.0)
        ]

    monkeypatch.setattr(service, "list_supervised_worktree_runs", fake_list)
    panel = service.build_supervised_judge_quality_report(limit=50)
    assert captured["limit"] == 50
    assert panel["schemaVersion"] == 1
    assert panel["agreementPairs"] == 1
    assert panel["scoreSeries"][0]["runId"] == "a"


def _human_run(run_id: str, *, judge: str, approval: str) -> dict:
    return {
        "runId": run_id,
        "executionMode": "real",
        "outcome": "",
        "finishedAt": "2026-09-18T02:00:00Z",
        "decision": {"judgeDecision": judge, "baselineScore": 1.0, "candidateScore": 2.0},
        "approvalDecision": {"decision": approval, "mode": "human"},
    }


def test_human_anchor_pairs_counted_separately() -> None:
    runs = [
        _human_run("h1", judge="APPROVE", approval="APPROVE"),
        _run("a1", judge="APPROVE", approval="APPROVE"),
    ]
    report = build_judge_agreement_report(runs)
    assert report.anchoredPairs == 1
    assert report.agentPairs == 1
    # 顶层优先人工锚定样本
    assert report.topLevelSampleSource == "anchored"
    assert report.confusionMatrix["trueNegatives"] == 1
    assert report.anchoredConfusionMatrix["trueNegatives"] == 1
    assert report.agentConfusionMatrix["trueNegatives"] == 1


def test_all_agent_sample_falls_back_with_source_label() -> None:
    runs = [_run("a1", judge="REVISE", approval="RERUN_REQUIRED")]
    report = build_judge_agreement_report(runs)
    assert report.anchoredPairs == 0
    assert report.topLevelSampleSource == "agent"
    assert report.confusionMatrix["truePositives"] == 1
    assert report.agentConfusionMatrix["truePositives"] == 1


def test_human_disagreement_lands_in_anchored_false_auto_approve() -> None:
    runs = [
        _human_run("h1", judge="APPROVE", approval="RERUN_REQUIRED"),
        _human_run("h2", judge="APPROVE", approval="APPROVE"),
    ]
    report = build_judge_agreement_report(runs)
    assert report.anchoredPairs == 2
    assert report.anchoredConfusionMatrix["falseNegatives"] == 1
    assert report.falseAutoApproveUpperBounds["falseAutoApproves"] == 1
