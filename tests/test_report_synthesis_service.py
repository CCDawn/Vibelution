"""Report synthesis orchestration: LLM stubbed, artifact + anchor invariants."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.web.services.team_workflow.research_runtime import report_synthesis_service as svc
from core.web.services.team_workflow.research_runtime.report_synthesis_service import (
    ReportSynthesisError,
    synthesize_research_report,
)

ITEMS = [
    {
        "itemId": "ki-1",
        "title": "GNN 综述",
        "summary": "GNN 用于材料筛选。",
        "sourceRefs": ["https://example.com/gnn"],
        "section": "证据",
    },
    {
        "itemId": "ki-2",
        "title": "评审标准",
        "summary": "聚焦机制可解释性。",
        "sourceRefs": [],
        "section": "方法",
    },
]


def _patch_llm(monkeypatch, prose: str):
    class _Response:
        content = prose

    monkeypatch.setattr(svc, "invoke_llm", lambda *a, **k: _Response())
    monkeypatch.setattr(svc, "_reflection_stub", None, raising=False)
    monkeypatch.setattr(svc, "config_for_agent_llm_model", lambda *a, **k: object())
    monkeypatch.setattr(svc, "get_llm_client", lambda **k: object())


def _patch_store(monkeypatch, tmp_path: Path):
    recorded: dict[str, dict] = {}

    def fake_put(team_id, *, kind, workflow_run_id, payload, source_collection_run_id="", artifact_identity=""):
        recorded["call"] = {
            "teamId": team_id,
            "kind": kind,
            "workflowRunId": workflow_run_id,
            "payload": payload,
        }
        return {"recordId": artifact_identity or "r1", "updatedAt": "2026-09-20T00:00:00Z"}

    monkeypatch.setattr(svc, "put_workflow_artifact", fake_put)
    return recorded


def test_synthesis_writes_anchored_report_artifact(tmp_path, monkeypatch):
    _patch_llm(monkeypatch, "# 报告\n\n证据：GNN 有效 [KI-ki-1]。方法上需可解释 [KI-ki-2]。")
    recorded = _patch_store(monkeypatch, tmp_path)

    result = synthesize_research_report(
        "team-1",
        topic="材料筛选",
        items=ITEMS,
        model_ref="dashscope_main/qwen3.7-plus",
        workflow_run_id="run-1",
    )

    assert result["itemCount"] == 2
    assert "[KI-ki-1]" in result["reportMarkdown"]
    assert result["citationIntegrity"] == {"clean": False, "problems": ["KI-ki-2 has no source reference"]}
    stored = recorded["call"]
    assert stored["kind"] == "research_report"
    assert stored["teamId"] == "team-1"
    assert stored["payload"]["skeleton"]["itemCount"] == 2


def test_synthesis_rejects_invented_anchors(tmp_path, monkeypatch):
    _patch_llm(monkeypatch, "幻觉锚点 [KI-not-exist] 出现。")
    _patch_store(monkeypatch, tmp_path)

    with pytest.raises(ReportSynthesisError) as error:
        synthesize_research_report(
            "team-1", topic="t", items=ITEMS, model_ref="m", workflow_run_id="run-1"
        )
    assert error.value.code == "anchor_violation"


def test_synthesis_rejects_empty_inputs(tmp_path, monkeypatch):
    _patch_store(monkeypatch, tmp_path)
    with pytest.raises(ReportSynthesisError) as no_items:
        synthesize_research_report("team-1", topic="t", items=[], model_ref="m", workflow_run_id="run-1")
    assert no_items.value.code == "empty_items"
    with pytest.raises(ReportSynthesisError) as no_run:
        synthesize_research_report("team-1", topic="t", items=ITEMS, model_ref="m", workflow_run_id="")
    assert no_run.value.code == "invalid_request"


def test_research_route_contract():
    route_source = Path("core/web/routes/research.py").read_text(encoding="utf-8")
    assert "/research/teams/{team_id}/report-synthesis" in route_source
    models_source = Path("core/web/routes/research_models.py").read_text(encoding="utf-8")
    assert "ResearchReportSynthesisPayload" in models_source
