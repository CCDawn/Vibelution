"""Team workflow research graph / steward / knowledge cases (xdist domain pack).

Implementation: ``tests/_support/team_workflow/cases_research_knowledge.py``.
"""
from __future__ import annotations

from tests._support.team_workflow.cases_research_knowledge import *  # noqa: F403


def test_single_source_steward_pack_keeps_only_one_source_and_its_claims():
    from core.web.services.team_workflow.source_collection.writeback_materialize import (
        _single_source_steward_pack_output,
    )

    source = {
        "candidateId": "source-autism",
        "title": "自闭症早期筛查证据",
        "summary": "自闭症筛查来源摘要。",
        "sourceUrl": "https://example.test/autism",
        "qualityStatus": "approved",
        "metadata": {"sourceIdentityKey": "url:https://example.test/autism", "evidenceLevel": "peer_reviewed"},
        "evidenceRefs": [{"type": "url", "id": "https://example.test/autism"}],
    }
    output = _single_source_steward_pack_output(
        {
            "candidateIds": ["source-autism", "source-cicada"],
            "claims": [
                {"claim": "自闭症 claim", "sourceRef": "source-autism"},
                {"claim": "周期蝉 claim", "sourceRef": "source-cicada"},
            ],
            "proposalPayload": {"title": "旧的大包标题"},
            "sourceTrace": {"sourceCandidateIds": ["source-autism", "source-cicada"]},
        },
        source,
        scope={
            "researchProjectId": "challenge-project",
            "questionId": "SCI-096",
            "sourceCollectionRunId": "run-096",
        },
    )

    assert output["candidateIds"] == ["source-autism"]
    assert output["claims"] == [{"claim": "自闭症 claim", "sourceRef": "source-autism"}]
    assert output["proposalPayload"]["title"] == "自闭症早期筛查证据"
    assert output["questionId"] == "SCI-096"
    assert output["evidenceLevel"] == "peer_reviewed"
    assert output["sourceIdentityHash"].startswith("sha256:")
    assert output["sourceTrace"]["sourceUrl"] == "https://example.test/autism"
    assert {ref["id"] for ref in output["evidenceRefs"]} == {"https://example.test/autism"}


def test_challenge_automatic_memory_lookup_stops_when_authoritative_scope_is_missing(monkeypatch):
    from core.web.services import team_workflow_orchestration_service as service

    called = False

    def unexpected_search(**kwargs):
        nonlocal called
        called = True
        return {"results": []}

    monkeypatch.setattr(service.team_knowledge_service, "search_knowledge_items", unexpected_search)
    results, status = service._research_memory_knowledge_results(
        "research-team",
        research_question="自闭症",
        actor_agent_id="agent-source",
        research_project_id="",
        question_id="",
        require_scope=True,
    )
    assert results == []
    assert status == "scope_incomplete"
    assert called is False
