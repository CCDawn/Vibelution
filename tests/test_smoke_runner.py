"""Smoke Runner 测试（PRD N-11 / V1）：确定性、白名单、结果形态、非执行型。"""

from __future__ import annotations

import pytest

from core.research import smoke_runner

ADAPTER = "synthetic_classification_baseline_vs_variant"


def test_run_smoke_adapter_result_shape():
    result = smoke_runner.run_smoke_adapter(ADAPTER, seed=42)
    assert result["status"] == "completed"
    assert result["runnerMode"] == "v1_cpu_smoke"
    metrics = result["metrics"]
    assert set(metrics) == {"baseline", "variant", "delta", "threshold"}
    assert "accuracy" in metrics["baseline"] and "macro_f1" in metrics["baseline"]
    assert result["artifactHash"].startswith("sha256:")
    assert result["decisionHint"] in {"accept", "iterate", "reject", "needs_full_run"}


def test_run_smoke_adapter_is_deterministic_for_fixed_seed():
    first = smoke_runner.run_smoke_adapter(ADAPTER, seed=42)
    second = smoke_runner.run_smoke_adapter(ADAPTER, seed=42)
    assert first["metrics"] == second["metrics"]
    assert first["artifactHash"] == second["artifactHash"]
    assert first["decisionHint"] == second["decisionHint"]


def test_run_smoke_adapter_seed_changes_artifact_hash():
    first = smoke_runner.run_smoke_adapter(ADAPTER, seed=42)
    other = smoke_runner.run_smoke_adapter(ADAPTER, seed=7)
    assert first["artifactHash"] != other["artifactHash"]


def test_run_smoke_adapter_rejects_non_whitelisted():
    with pytest.raises(smoke_runner.SmokeRunnerError):
        smoke_runner.run_smoke_adapter("arbitrary_user_code", seed=42)


def test_literature_review_smoke_is_non_executable():
    result = smoke_runner.run_smoke_adapter("literature_review_smoke", seed=42)
    assert result["status"] == "non_executable"
    assert result["executable"] is False
    assert result["decisionHint"] == "needs_full_run"


def test_decision_hint_threshold_logic():
    # 高阈值 → 不太可能达标 → reject / needs_full_run（取决于 delta 符号）
    high = smoke_runner.run_smoke_adapter(ADAPTER, seed=42, threshold=0.9)
    assert high["decisionHint"] in {"reject", "needs_full_run"}
    # 极低阈值 → 只要 variant 不劣于 baseline 即 accept/iterate
    low = smoke_runner.run_smoke_adapter(ADAPTER, seed=42, threshold=0.0)
    assert low["decisionHint"] in {"accept", "iterate", "reject"}
