# -*- coding: utf-8 -*-
"""Tests: rubric promotion gate (pure layer + gated promote service)."""

from __future__ import annotations

import pytest

from core.research.competition.rubric_promotion_gate import (
    evaluate_rubric_promotion_gate,
)
from core.web.services import supervised_rubric_promotion_service as service


def _version(version_id: str, status: str, rubric_hash: str) -> dict:
    return {
        "rubricVersionId": version_id,
        "status": status,
        "rubricHash": rubric_hash,
        "source": "swte-src",
    }


def _panel(
    *,
    anchored_pairs: int = 5,
    kappa: float = 0.8,
    defined: bool = True,
    trials: int = 10,
    bound: float = 0.01,
) -> dict:
    return {
        "anchoredPairs": anchored_pairs,
        "anchoredKappa": {"kappa": kappa, "defined": defined},
        "falseAutoApproveUpperBounds": {
            "trialsAutoApproved": trials,
            "beta_binomial": bound,
            "wilson": bound,
        },
        "topLevelSampleSource": "anchored",
        "totalRuns": 20,
    }


def test_all_criteria_pass_is_eligible() -> None:
    versions = [_version("rv-1", "shadow", "h1")]
    result = evaluate_rubric_promotion_gate(_panel(), versions)
    assert result.eligible is True
    assert result.candidate_version_id == "rv-1"
    assert all(check.passed for check in result.checks)
    assert result.evidence_scope == "global_panel_v1"


def test_no_distinct_shadow_candidate_blocks() -> None:
    versions = [_version("rv-1", "active", "h1"), _version("rv-2", "shadow", "h1")]
    result = evaluate_rubric_promotion_gate(_panel(), versions)
    assert result.eligible is False
    assert not result.checks[0].passed


def test_insufficient_anchored_pairs_blocks() -> None:
    result = evaluate_rubric_promotion_gate(
        _panel(anchored_pairs=2), [_version("rv-1", "shadow", "h1")]
    )
    assert result.eligible is False
    failed = {c.check_id for c in result.checks if not c.passed}
    assert "anchored_evidence_sufficient" in failed


def test_low_or_undefined_kappa_blocks() -> None:
    low = evaluate_rubric_promotion_gate(
        _panel(kappa=0.5), [_version("rv-1", "shadow", "h1")]
    )
    assert low.eligible is False
    undefined = evaluate_rubric_promotion_gate(
        _panel(defined=False), [_version("rv-1", "shadow", "h1")]
    )
    assert undefined.eligible is False


def test_uncontrolled_false_auto_approve_bound_blocks() -> None:
    result = evaluate_rubric_promotion_gate(
        _panel(bound=0.4), [_version("rv-1", "shadow", "h1")]
    )
    assert result.eligible is False
    failed = {c.check_id for c in result.checks if not c.passed}
    assert "false_auto_approve_bounded" in failed
    zero_trials = evaluate_rubric_promotion_gate(
        _panel(trials=0, bound=0.0), [_version("rv-1", "shadow", "h1")]
    )
    assert zero_trials.eligible is False  # 无数据 fail-closed


def test_promote_service_enforces_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service, "build_supervised_judge_quality_report",
        lambda limit=200: _panel(anchored_pairs=0),
    )
    monkeypatch.setattr(
        service, "list_rubric_versions",
        lambda limit=500: [_version("rv-1", "shadow", "h1")],
    )
    promoted: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        service, "promote_rubric_version",
        lambda version_id, evidence: promoted.append((version_id, evidence))
        or {"rubricVersionId": "rv-new", "status": "active"},
    )
    with pytest.raises(service.RubricPromotionBlockedError) as excinfo:
        service.promote_rubric_if_eligible()
    assert "anchored_evidence_sufficient" in str(excinfo.value)
    assert promoted == []


def test_promote_service_promotes_when_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service, "build_supervised_judge_quality_report", lambda limit=200: _panel()
    )
    monkeypatch.setattr(
        service, "list_rubric_versions",
        lambda limit=500: [_version("rv-1", "shadow", "h1")],
    )
    promoted: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        service, "promote_rubric_version",
        lambda version_id, evidence: promoted.append((version_id, evidence))
        or {"rubricVersionId": "rv-new", "status": "active"},
    )
    result = service.promote_rubric_if_eligible()
    assert result["promoted"]["status"] == "active"
    assert promoted[0][0] == "rv-1"
    assert promoted[0][1]["gate"] == "rubric_promotion_v1"
    assert promoted[0][1]["anchoredPairs"] == 5


def test_malformed_evidence_counters_fail_closed() -> None:
    """Malformed (non-numeric) counters must fail closed, not raise 500."""
    panel = _panel()
    panel["anchoredPairs"] = "many"
    panel["falseAutoApproveUpperBounds"]["trialsAutoApproved"] = None
    result = evaluate_rubric_promotion_gate(panel, [_version("rv-1", "shadow", "h1")])
    assert result.eligible is False
    failed = {c.check_id for c in result.checks if not c.passed}
    assert "anchored_evidence_sufficient" in failed
    assert "false_auto_approve_bounded" in failed
    assert result.evidence["anchoredPairs"] == 0


def test_bool_evidence_values_count_as_missing() -> None:
    """bool is an int subclass; True must never satisfy a numeric threshold."""
    panel = _panel()
    panel["anchoredKappa"]["kappa"] = True
    panel["falseAutoApproveUpperBounds"]["beta_binomial"] = True
    result = evaluate_rubric_promotion_gate(panel, [_version("rv-1", "shadow", "h1")])
    assert result.eligible is False
    failed = {c.check_id for c in result.checks if not c.passed}
    assert "anchored_kappa_acceptable" in failed
    assert "false_auto_approve_bounded" in failed


def test_negative_or_fractional_pair_counts_fail_closed() -> None:
    panel = _panel(anchored_pairs=-3)
    result = evaluate_rubric_promotion_gate(panel, [_version("rv-1", "shadow", "h1")])
    assert result.eligible is False
    assert "anchored_evidence_sufficient" in {
        c.check_id for c in result.checks if not c.passed
    }
