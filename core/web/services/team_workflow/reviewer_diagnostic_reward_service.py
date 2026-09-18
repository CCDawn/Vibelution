# -*- coding: utf-8 -*-
"""Reviewer diagnostic-reward service for hypothesis rounds (read-only).

P0-1 的链路接线：读取团队的 HypothesisRound 历史（最新记录按 createdAt
排序——与 append-only 存储的时间序一致），交给
``reviewer_diagnostic_reward`` 纯计算层产出「批评 → 下一轮改进」的评审者
质量归因。只读，不写回；报告完全由输入决定，可复算。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from core.research.competition.reviewer_diagnostic_reward import (
    build_diagnostic_reward_report,
)
from .hypothesis_rounds import list_hypothesis_rounds


def build_reviewer_diagnostic_reward_report(team_id: str) -> dict[str, Any]:
    """Build the reviewer diagnostic-reward report for one team's rounds."""
    listing = list_hypothesis_rounds(team_id)
    report = build_diagnostic_reward_report(listing.get("rounds") or [])
    return {
        "schemaVersion": 1,
        "teamId": str(listing.get("teamId") or ""),
        "roundCount": int(listing.get("roundCount") or 0),
        "corruptQuarantinedLineCount": int(
            listing.get("corruptQuarantinedLineCount") or 0
        ),
        "diagnosticReward": asdict(report),
    }
