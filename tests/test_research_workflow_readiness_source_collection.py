"""T2 RED: source collection / evidence / knowledge readiness — the
SCI-096 missing-candidates scenario surfaces the same blocker as the
command path will."""

from __future__ import annotations

from core.web.services.team_workflow.research_runtime.readiness import NodeReadinessService
from tests._support.readiness_fakes import FakeDomainContext, make_run


def _service(runs=None) -> NodeReadinessService:
    return NodeReadinessService(run_source=(runs or {"run-test": make_run()}).get)


def _evaluate(service, context, node_id):
    return service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id=node_id,
        context=context,
        use_cache=False,
    )


def test_source_finding_ready_with_question() -> None:
    service = _service()
    context = FakeDomainContext()
    context._question = {"questionId": "SCI-096", "snapshotHash": "q" * 64}
    result = _evaluate(service, context, "source_finding")
    assert result.ready is True


def test_source_finding_missing_question_blocks() -> None:
    service = _service()
    context = FakeDomainContext()
    context._question = None
    result = _evaluate(service, context, "source_finding")
    assert result.ready is False
    assert any(b.code == "question_snapshot_missing" for b in result.blockers)


def test_sci096_missing_candidates_blocks_source_extraction() -> None:
    service = _service()
    context = FakeDomainContext()
    context._candidate_stats = None
    result = _evaluate(service, context, "source_extraction")
    assert result.ready is False
    assert any(b.code == "source_candidates_missing" for b in result.blockers)
    assert result.blockers[0].detail


def test_source_extraction_ready_with_candidates() -> None:
    service = _service()
    context = FakeDomainContext()
    context._candidate_stats = {"record_count": 3}
    result = _evaluate(service, context, "source_extraction")
    assert result.ready is True


def test_evidence_relations_missing_cards_blocks() -> None:
    service = _service()
    context = FakeDomainContext()
    context._evidence_cards = None
    result = _evaluate(service, context, "evidence_relations")
    assert result.ready is False
    assert any(b.code == "evidence_cards_missing" for b in result.blockers)


def test_evidence_relations_incomplete_cards_blocks() -> None:
    service = _service()
    context = FakeDomainContext()
    context._evidence_cards = {"card_count": 2, "missing_minimal_fields": ["card-1"]}
    result = _evaluate(service, context, "evidence_relations")
    assert result.ready is False
    assert any(b.code == "evidence_cards_incomplete" for b in result.blockers)


def test_knowledge_ingestion_blocked_without_waivered_links() -> None:
    service = _service()
    context = FakeDomainContext()
    context._evidence_graph = {"node_count": 4, "missing_link_count": 2, "waiver_count": 0}
    result = _evaluate(service, context, "knowledge_ingestion")
    assert result.ready is False
    assert any(b.code == "evidence_graph_incomplete" for b in result.blockers)


def test_knowledge_ingestion_ready_with_waiver() -> None:
    service = _service()
    context = FakeDomainContext()
    context._evidence_graph = {"node_count": 4, "missing_link_count": 2, "waiver_count": 1}
    result = _evaluate(service, context, "knowledge_ingestion")
    assert result.ready is True


def test_knowledge_handoff_blocks_without_audit() -> None:
    service = _service()
    context = FakeDomainContext()
    context._knowledge_draft = {"reviewable": False}
    result = _evaluate(service, context, "knowledge_handoff")
    assert result.ready is False
    assert any(b.code == "knowledge_package_not_reviewable" for b in result.blockers)


def test_knowledge_handoff_ready_with_audit_complete() -> None:
    service = _service()
    context = FakeDomainContext()
    context._knowledge_draft = {"auditComplete": True}
    result = _evaluate(service, context, "knowledge_handoff")
    assert result.ready is True
