# -*- coding: utf-8 -*-
"""Reviewer diagnostic-reward service for hypothesis rounds.

P0-1 的链路接线：读取团队的 HypothesisRound 历史（最新记录按 createdAt
排序——与 append-only 存储的时间序一致），把候选 ``dimensionReviewRefs``
所指的七维 ordinal 审计行从工作流 artifact 权威存储水合回候选，再交给
``reviewer_diagnostic_reward`` 纯计算层产出「批评 → 下一轮改进」的评审者
质量归因。对轮次存储只读；水合只发生在本次报告的内存副本上。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from core.research.competition.reviewer_diagnostic_reward import (
    build_diagnostic_reward_report,
)
from .hypothesis_rounds import list_hypothesis_rounds
from .research_runtime.workflow_artifact_store import list_workflow_artifacts

_DIMENSION_REVIEWS_KIND = "dimension_reviews"


def _latest_dimension_review_payloads(team_id: str) -> dict[str, dict[str, Any]]:
    """Index the authority store as {reviewRoundId: payload} (latest wins)."""
    indexed: dict[str, dict[str, Any]] = {}
    for artifact in list_workflow_artifacts(team_id, kind=_DIMENSION_REVIEWS_KIND):
        payload = artifact.get("payload")
        if not isinstance(payload, dict):
            continue
        review_round_id = str(payload.get("reviewRoundId") or "").strip()
        if not review_round_id:
            continue
        existing = indexed.get(review_round_id)
        if existing is None or str(artifact.get("updatedAt") or "") >= str(
            existing.get("_updatedAt") or ""
        ):
            indexed[review_round_id] = {
                "dimensionReviews": list(payload.get("dimensionReviews") or []),
                "_updatedAt": str(artifact.get("updatedAt") or ""),
            }
    return indexed


def _hydrate_dimension_reviews(
    rounds: list[dict[str, Any]], payloads_by_round: dict[str, dict[str, Any]]
) -> None:
    """Attach authority-store audit rows onto candidates that only carry refs.

    只补缺：候选已有内联 ``dimensionReviews`` 时不覆盖；按 refs 的
    ``reviewRoundId`` 取权威 payload，再按 ``hypothesis_id`` 绑定过滤行，
    行内自带的 ``reviewer`` 归属优于角色回退。
    """
    for record in rounds:
        candidates = record.get("candidates")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("dimensionReviews") or candidate.get("dimension_reviews"):
                continue
            refs = candidate.get("dimensionReviewRefs")
            if not isinstance(refs, list):
                continue
            candidate_id = str(candidate.get("candidateId") or "").strip()
            if not candidate_id:
                continue
            rows: list[dict[str, Any]] = []
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                payload = payloads_by_round.get(
                    str(ref.get("reviewRoundId") or "").strip()
                )
                if payload is None:
                    continue
                for row in payload.get("dimensionReviews") or []:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("hypothesis_id") or "").strip() != candidate_id:
                        continue
                    rows.append(dict(row))
            if rows:
                candidate["dimensionReviews"] = rows


def build_reviewer_diagnostic_reward_report(team_id: str) -> dict[str, Any]:
    """Build the reviewer diagnostic-reward report for one team's rounds."""
    listing = list_hypothesis_rounds(team_id)
    rounds = list(listing.get("rounds") or [])
    hydrated_rounds: list[dict[str, Any]] = []
    for record in rounds:
        cloned = dict(record)
        cloned_candidates = [
            dict(candidate) if isinstance(candidate, dict) else candidate
            for candidate in (record.get("candidates") or [])
        ]
        cloned["candidates"] = cloned_candidates
        hydrated_rounds.append(cloned)
    payloads_by_round = _latest_dimension_review_payloads(
        str(listing.get("teamId") or team_id)
    )
    _hydrate_dimension_reviews(hydrated_rounds, payloads_by_round)
    report = build_diagnostic_reward_report(hydrated_rounds)
    return {
        "schemaVersion": 1,
        "teamId": str(listing.get("teamId") or ""),
        "roundCount": int(listing.get("roundCount") or 0),
        "corruptQuarantinedLineCount": int(
            listing.get("corruptQuarantinedLineCount") or 0
        ),
        "ordinalHydratedFromAuthority": bool(payloads_by_round),
        "diagnosticReward": asdict(report),
    }
