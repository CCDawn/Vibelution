# -*- coding: utf-8 -*-
"""Wiring tests: rubric shadow registration + dimension-guidance hint injection."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.web.services import supervised_worktree_evolution_service as service


def test_rubric_shadow_version_recorded_on_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict] = []

    def fake_record(rubric, *, source, rubric_hash, status="shadow"):
        recorded.append({"rubric": rubric, "source": source, "hash": rubric_hash, "status": status})
        return {"rubricVersionId": "rv-x", "status": status}

    monkeypatch.setattr(
        "core.web.services.supervised_rubric_version_store.record_rubric_version",
        fake_record,
    )
    service._record_rubric_shadow_version(
        "swte-1",
        {"rubricHash": "abc", "status": "success", "criteria": ["c1"], "conversationSessionId": "s"},
    )
    assert recorded == [
        {"rubric": {"rubricHash": "abc", "criteria": ["c1"]}, "source": "swte-1", "hash": "abc", "status": "shadow"}
    ]


def test_rubric_shadow_version_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr(
        "core.web.services.supervised_rubric_version_store.record_rubric_version",
        boom,
    )
    service._record_rubric_shadow_version("swte-1", {"rubricHash": "abc"})  # 静默


def test_dimension_guidance_hint_reads_latest_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import evaluation_quality_ledger as ledger

    monkeypatch.setattr(
        ledger,
        "read_quality_ledger",
        lambda name, limit=50: [
            {
                "diagnosticReward": {
                    "score_by_dimension": {
                        "novelty": {"critique_count": 4, "improved_count": 1, "harmed_count": 2, "mean_delta": -0.02},
                        "feasibility": {"critique_count": 4, "improved_count": 3, "harmed_count": 1, "mean_delta": 0.05},
                    }
                }
            }
        ],
    )
    hint = service._dimension_guidance_hint()
    assert "谨慎处理 novelty" in hint
    assert "重点强化 feasibility" in hint


def test_dimension_guidance_hint_empty_without_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import evaluation_quality_ledger as ledger

    monkeypatch.setattr(ledger, "read_quality_ledger", lambda name, limit=50: [])
    assert service._dimension_guidance_hint() == ""


def test_reflection_prompt_appends_guidance_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service, "_dimension_guidance_hint", lambda: "修订指引：谨慎处理 novelty。"
    )
    reflection = service._build_reflection(
        {"taskContract": {}},
        {"successes": 1, "total": 2},
        {"score": 40.0, "improvementInstructions": ["fix evidence support"]},
    )
    prompt = str(reflection.get("selfModificationPrompt") or "")
    assert "修订指引：谨慎处理 novelty。" in prompt
