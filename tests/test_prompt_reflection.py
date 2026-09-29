"""GEPA-style prompt reflection: domain logic, orchestration and route."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.evaluation.prompt_reflection import (
    REFLECTION_PROPOSAL_KIND,
    collect_reflection_samples,
    pareto_nondominated,
    reflection_proposal_id,
    reflection_proposal_payload,
)
from core.web.services import prompt_reflection_service
from core.web.services.prompt_reflection_service import (
    PromptReflectionError,
    generate_prompt_reflection_proposal,
)


def _decision_payload() -> dict:
    def case(case_id: str, candidate_status: str, baseline_status: str = "passed") -> dict:
        return {
            "case_id": case_id,
            "case_type": "chat",
            "baseline_status": baseline_status,
            "candidate_status": candidate_status,
            "baseline_reason": "ok" if baseline_status == "passed" else "baseline failed",
            "candidate_reason": f"candidate {candidate_status}",
            "decision_signal": "candidate_regression" if candidate_status != "passed" else "neutral",
            "difference_summary": "diff",
            "difference_reasons": ["reason-a"],
            "failure_taxonomy": ["formatting", "reasoning"],
            "score_breakdown": {"successRate": 0.2, "costTokens": 1200.0, "latencyMs": 8000.0},
        }

    return {
        "session_id": "sess-1",
        "bundle_name": "bundle-a",
        "case_summaries": [
            case("case-1", "failed"),
            case("case-2", "timeout"),
            case("case-3", "passed"),
            case("case-4", "passed", baseline_status="failed"),
        ],
    }


def test_collect_reflection_samples_prioritizes_candidate_failures():
    samples = collect_reflection_samples(_decision_payload(), max_samples=10)
    assert [s["case_id"] for s in samples] == ["case-1", "case-2", "case-4"]
    assert samples[0]["failure_taxonomy"] == ["formatting", "reasoning"]
    bounded = collect_reflection_samples(_decision_payload(), max_samples=1)
    assert [s["case_id"] for s in bounded] == ["case-1"]


def test_pareto_nondominated_keeps_front_and_ties():
    candidates = [
        {"id": "a", "success": 0.5, "cost": 100.0},
        {"id": "b", "idominated": True, "success": 0.4, "cost": 120.0},
        {"id": "c", "success": 0.4, "cost": 100.0},
        {"id": "d", "success": 0.6, "cost": 150.0},
    ]
    front = pareto_nondominated(candidates, ("success", "cost"), maximize=("success",))
    assert {item["id"] for item in front} == {"a", "d"}


def test_reflection_proposal_payload_shape():
    payload = reflection_proposal_payload(
        proposal_id="pr-1",
        session_id="s",
        bundle_name="b",
        target={"bundleName": "b"},
        critique="critique",
        suggested_prompt_delta="delta",
        sample_case_ids=["c1", ""],
        metrics={"sampleSuccessRate": 0.2},
        generated_at="2026-09-20T00:00:00Z",
    )
    assert payload["kind"] == REFLECTION_PROPOSAL_KIND
    assert payload["status"] == "observing"
    assert payload["reflection"]["sampleCaseIds"] == ["c1"]
    assert payload["reflection"]["suggestedPromptDelta"] == "delta"


def test_reflection_proposal_id_is_stable():
    first = reflection_proposal_id(session_id="s", target_prompt_template_id="t")
    second = reflection_proposal_id(session_id="s", target_prompt_template_id="t")
    other = reflection_proposal_id(session_id="s2", target_prompt_template_id="t")
    assert first == second and first != other


def _patch_llm(monkeypatch, critique="批判分析", delta="修改建议"):
    captured = {}

    class _Response:
        content = json.dumps({"critique": critique, "suggestedPromptDelta": delta}, ensure_ascii=False)

    def fake_invoke_llm(client, messages, *, context=None, metadata=None):
        captured["messages"] = messages
        return _Response()

    monkeypatch.setattr(prompt_reflection_service, "invoke_llm", fake_invoke_llm)
    monkeypatch.setattr(
        prompt_reflection_service,
        "_reflection_runtime_config",
        lambda model_ref: object(),
    )
    monkeypatch.setattr(
        prompt_reflection_service,
        "get_llm_client",
        lambda **kwargs: object(),
    )
    return captured


def test_generate_writes_proposal_and_enforces_pareto(tmp_path, monkeypatch):
    _patch_llm(monkeypatch)
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(_decision_payload()), encoding="utf-8")
    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir()
    monkeypatch.setattr(prompt_reflection_service, "_proposals_dir", lambda root: proposals_dir)
    monkeypatch.setattr(prompt_reflection_service, "get_workspace", lambda: type("W", (), {"project_root": tmp_path}))

    result = generate_prompt_reflection_proposal(decision_path, model_ref="dashscope_main/qwen3.7-plus")

    assert result["sampleCount"] == 3
    assert result["kind"] == REFLECTION_PROPOSAL_KIND
    written = json.loads(
        (proposals_dir / f"{result['proposalId']}.json").read_text(encoding="utf-8")
    )
    assert written["reflection"]["critique"] == "批判分析"
    assert written["status"] == "observing"

    # Same-id regeneration is a version update (no domination check), but a
    # different-id proposal with dominated metrics is rejected outright.
    _patch_llm(monkeypatch, critique="worse", delta="worse")
    dominating = dict(written)
    dominating["reflection"] = dict(dominating["reflection"])
    dominating["reflection"]["metrics"] = {
        "sampleSuccessRate": 1.0,
        "avgCostTokens": 1.0,
        "avgLatencyMs": 1.0,
    }
    (proposals_dir / f"{result['proposalId']}.json").write_text(
        json.dumps(dominating, ensure_ascii=False), encoding="utf-8"
    )
    other_decision = _decision_payload()
    other_decision["session_id"] = "sess-2"
    other_path = tmp_path / "decision-other.json"
    other_path.write_text(json.dumps(other_decision), encoding="utf-8")
    with pytest.raises(PromptReflectionError) as error:
        generate_prompt_reflection_proposal(other_path, model_ref="dashscope_main/qwen3.7-plus")
    assert error.value.code == "proposal_dominated"


def test_generate_rejects_when_no_failures(tmp_path, monkeypatch):
    decision = _decision_payload()
    decision["case_summaries"] = decision["case_summaries"][:1]
    decision["case_summaries"][0]["candidate_status"] = "passed"
    decision["case_summaries"][0]["baseline_status"] = "passed"
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    monkeypatch.setattr(prompt_reflection_service, "get_workspace", lambda: type("W", (), {"project_root": tmp_path}))

    with pytest.raises(PromptReflectionError) as error:
        generate_prompt_reflection_proposal(decision_path, model_ref="m")
    assert error.value.code == "no_failure_samples"


def test_generate_rejects_missing_decision(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_reflection_service, "get_workspace", lambda: type("W", (), {"project_root": tmp_path}))
    with pytest.raises(PromptReflectionError) as error:
        generate_prompt_reflection_proposal(tmp_path / "missing.json", model_ref="m")
    assert error.value.code == "decision_unreadable"


def test_route_contract():
    route_source = Path("core/web/routes/evolution.py").read_text(encoding="utf-8")
    assert "/evolution/supervised/prompt-reflection/generate" in route_source
    assert "PromptReflectionError" in route_source
