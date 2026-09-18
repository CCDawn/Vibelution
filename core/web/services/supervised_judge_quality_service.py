# -*- coding: utf-8 -*-
"""Supervised judge-quality panel service (read-only accumulation surface)."""

from __future__ import annotations

from typing import Any

from core.research.competition.judge_agreement_stats import build_judge_agreement_report
from .supervised_worktree_evolution_service import list_supervised_worktree_runs


def build_supervised_judge_quality_report(limit: int = 200) -> dict[str, Any]:
    """Build the judge-vs-approval quality panel over persisted run snapshots.

    只读：按需从 run 存储读取历史快照并交给纯计算层；不做任何写回，
    面板证据的复算完全由输入决定。
    """
    runs = list_supervised_worktree_runs(limit=limit)
    report = build_judge_agreement_report(runs)
    return {
        "schemaVersion": 1,
        "totalRuns": report.totalRuns,
        "agreementPairs": report.agreementPairs,
        "confusionMatrix": report.confusionMatrix,
        "kappa": report.kappa,
        "falseAutoApproveUpperBounds": report.falseAutoApproveUpperBounds,
        "scoreStatsByMode": report.scoreStatsByMode,
        "scoreSeries": report.scoreSeries,
    }
