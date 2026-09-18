# -*- coding: utf-8 -*-
"""Tests: ordinal hydration, quality ledgers, judge-quality snapshot hook, route."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services import evaluation_quality_ledger as ledger
from core.web.services import supervised_worktree_evolution_service as swte
from core.web.services.team_workflow import reviewer_diagnostic_reward_service as service
from core.web.routes.team_workflows import reviewer_quality as route


# ---------------------------------------------------------------------------
# ordinal 水合
# ---------------------------------------------------------------------------

def _round_with_refs() -> list[dict]:
    return [
        {
            "roundId": "r1",
            "createdAt": "2026-09-01T00:00:00Z",
            "candidates": [
                {
                    "candidateId": "sci-1",
                    "scores": {"novelty": 0.3},
                    "dimensionReviewRefs": [
                        {"reviewRoundId": "hround-1", "hypothesisId": "sci-1"}
                    ],
                }
            ],
        },
        {
            "roundId": "r2",
            "createdAt": "2026-09-02T00:00:00Z",
            "candidates": [
                {
                    "candidateId": "sci-1",
                    "scores": {"novelty": 0.6},
                    "dimensionReviewRefs": [
                        {"reviewRoundId": "hround-2", "hypothesisId": "sci-1"}
                    ],
                }
            ],
        },
    ]


def _artifact(review_round_id: str, hypothesis_id: str, rating: str) -> dict:
    return {
        "kind": "dimension_reviews",
        "updatedAt": "2026-09-03T00:00:00Z",
        "payload": {
            "reviewRoundId": review_round_id,
            "dimensionReviews": [
                {
                    "dimension": "novelty",
                    "rating": rating,
                    "rationale": "fixture",
                    "hypothesis_id": hypothesis_id,
                    "reviewer": "llm:test-reviewer",
                }
            ],
        },
    }


def test_hydration_feeds_ordinal_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service, "list_hypothesis_rounds",
        lambda team_id: {"teamId": team_id, "roundCount": 2, "rounds": _round_with_refs()},
    )
    monkeypatch.setattr(
        service, "list_workflow_artifacts",
        lambda team_id, kind: [
            _artifact("hround-1", "sci-1", "weak"),
            _artifact("hround-2", "sci-1", "adequate"),
        ]
        if kind == "dimension_reviews"
        else [],
    )
    report = service.build_reviewer_diagnostic_reward_report("team-1")
    dr = report["diagnosticReward"]
    assert report["ordinalHydratedFromAuthority"] is True
    assert len(dr["critique_outcomes"]) == 1
    outcome = dr["critique_outcomes"][0]
    assert outcome["reviewer"] == "llm:test-reviewer"
    assert outcome["delta"] == 2
    assert dr["overall"]["improvement_rate"] == 1.0
    # 数值通道不受水合影响
    assert dr["score_overall"]["critique_count"] == 1


def test_hydration_skips_inline_reviews_and_missing_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rounds = _round_with_refs()
    rounds[0]["candidates"][0]["dimensionReviews"] = [
        {"dimension": "novelty", "rating": "strong", "hypothesis_id": "sci-1"}
    ]
    monkeypatch.setattr(
        service, "list_hypothesis_rounds",
        lambda team_id: {"teamId": team_id, "roundCount": 2, "rounds": rounds},
    )
    monkeypatch.setattr(
        service, "list_workflow_artifacts", lambda team_id, kind: []
    )
    report = service.build_reviewer_diagnostic_reward_report("team-1")
    dr = report["diagnosticReward"]
    # round1 内联 strong 不算批评；round2 无权威可水合 → ordinal 无样本
    assert list(dr["critique_outcomes"]) == []


# ---------------------------------------------------------------------------
# 台账
# ---------------------------------------------------------------------------

@pytest.fixture()
def ledger_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ledger, "_PROJECT_ROOT", tmp_path)
    return ledger._ledger_path("probe_ledger").parent


def test_ledger_append_read_and_change_throttle(
    ledger_root: Path,
) -> None:
    result = ledger.append_quality_ledger("probe_ledger", {"value": 1})
    assert Path(result["path"]).exists()
    records = ledger.read_quality_ledger("probe_ledger")
    assert len(records) == 1
    assert records[0]["value"] == 1
    assert records[0]["capturedAt"]
    assert records[0]["contentSha256"]

    skipped = ledger.append_quality_ledger_if_changed("probe_ledger", {"value": 1})
    assert skipped.get("skipped") is True
    appended = ledger.append_quality_ledger_if_changed("probe_ledger", {"value": 2})
    assert appended.get("skipped") is None
    assert len(ledger.read_quality_ledger("probe_ledger")) == 2


def test_ledger_read_empty(ledger_root: Path) -> None:
    assert ledger.read_quality_ledger("probe_ledger") == []
    assert ledger.latest_quality_ledger_fingerprint("probe_ledger") == ""


# ---------------------------------------------------------------------------
# 终态快照挂点 + 路由
# ---------------------------------------------------------------------------

def test_judge_quality_snapshot_hook_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom():
        raise RuntimeError("panel unavailable")

    monkeypatch.setattr(
        "core.web.services.supervised_judge_quality_service.build_supervised_judge_quality_report",
        boom,
    )
    swte._append_judge_quality_snapshot("swte-x", {"status": "failed"})  # 不抛错


def test_reviewer_route_persists_snapshot_on_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ledger, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        service, "build_reviewer_diagnostic_reward_report",
        lambda team_id: {
            "schemaVersion": 1,
            "teamId": team_id,
            "roundCount": 1,
            "ordinalHydratedFromAuthority": True,
            "diagnosticReward": {"roundsExamined": 1},
        },
    )
    monkeypatch.setattr(route, "build_reviewer_diagnostic_reward_report", service.build_reviewer_diagnostic_reward_report)
    first = route.reviewer_diagnostic_reward_report("team-1", None)
    assert first["snapshotPersisted"] is True
    second = route.reviewer_diagnostic_reward_report("team-1", None)
    assert second["snapshotPersisted"] is False  # 内容未变，节流跳过
