# -*- coding: utf-8 -*-
"""Thin Team workflow routes: reviewer diagnostic-reward quality report.

只读构建 + 变化时快照落盘（``evaluation/reviewer_diagnostic_reward`` 台账）；
报告本体完全由团队轮次与权威审计行决定，可复算。Handler 保持薄层，
构建逻辑在 ``reviewer_diagnostic_reward_service``。
"""
from __future__ import annotations

from fastapi import Request

from core.web.services.evaluation_quality_ledger import append_quality_ledger_if_changed
from core.web.services.team_workflow.reviewer_diagnostic_reward_service import (
    build_reviewer_diagnostic_reward_report,
)

from ._errors import _raise_team_workflow_route_error
from ._router import router
from .reviewer_quality_models import ReviewerDiagnosticRewardResponse

_LEDGER_NAME = "reviewer_diagnostic_reward"


@router.get(
    "/teams/{team_id}/research-workflow/reviewer-diagnostic-reward",
    response_model=ReviewerDiagnosticRewardResponse,
    response_model_exclude_unset=True,
)
def reviewer_diagnostic_reward_report(team_id: str, request: Request) -> dict:
    """Build the reviewer diagnostic-reward report; persist on content change."""
    del request  # server-principal read; control-token middleware already ran
    try:
        report = build_reviewer_diagnostic_reward_report(team_id)
    except Exception as exc:  # noqa: BLE001 - route boundary maps all failures
        _raise_team_workflow_route_error("reviewer_diagnostic_reward", exc)
    persisted = False
    try:
        ledger_result = append_quality_ledger_if_changed(_LEDGER_NAME, report)
        persisted = not bool(ledger_result.get("skipped"))
    except Exception:
        persisted = False  # 台账失败不阻断只读报告
    return {**report, "snapshotPersisted": persisted}
