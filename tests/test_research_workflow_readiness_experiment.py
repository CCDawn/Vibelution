"""T2 RED: experiment design readiness — hypothesis through smoke gate."""

from __future__ import annotations

from core.web.services.team_workflow.research_runtime.readiness import NodeReadinessService
from tests._support.readiness_fakes import FakeDomainContext, make_run


def _service() -> NodeReadinessService:
    return NodeReadinessService(run_source={"run-test": make_run()}.get)


def _evaluate(context, node_id):
    return _service().evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id=node_id,
        context=context,
        use_cache=False,
    )


def test_hypothesis_design_blocks_without_accepted_package() -> None:
    context = FakeDomainContext()
    context._knowledge_package = {"accepted": False}
    result = _evaluate(context, "hypothesis_design")
    assert result.ready is False
    assert any(b.code == "knowledge_handoff_not_accepted" for b in result.blockers)


def test_hypothesis_design_ready_with_accepted_package() -> None:
    context = FakeDomainContext()
    result = _evaluate(context, "hypothesis_design")
    assert result.ready is True


def test_protocol_design_blocks_without_hypotheses() -> None:
    context = FakeDomainContext()
    context._hypothesis_set = None
    result = _evaluate(context, "protocol_design")
    assert result.ready is False
    assert any(b.code == "hypothesis_contract_incomplete" for b in result.blockers)


def test_protocol_review_blocks_on_missing_fields() -> None:
    context = FakeDomainContext()
    context._protocol_draft = {"dataset": True, "baseline": True, "metric": True}
    result = _evaluate(context, "protocol_review")
    assert result.ready is False
    assert any(b.code == "protocol_draft_incomplete" for b in result.blockers)
    assert "seed" in result.blockers[0].detail


def test_protocol_review_ready() -> None:
    context = FakeDomainContext()
    result = _evaluate(context, "protocol_review")
    assert result.ready is True


def test_protocol_freeze_blocks_on_blocking_issues() -> None:
    context = FakeDomainContext()
    context._protocol_review = {"blocking_issue_count": 1, "open_waivers": 0}
    result = _evaluate(context, "protocol_freeze")
    assert result.ready is False
    assert any(b.code == "protocol_review_blocked" for b in result.blockers)


def test_protocol_freeze_ready() -> None:
    context = FakeDomainContext()
    result = _evaluate(context, "protocol_freeze")
    assert result.ready is True


def test_smoke_gate_blocks_without_frozen_protocol() -> None:
    context = FakeDomainContext()
    context._frozen_protocol = None
    result = _evaluate(context, "smoke_gate")
    assert result.ready is False
    assert any(b.code == "frozen_protocol_missing" for b in result.blockers)


def test_smoke_gate_ready_with_frozen_protocol() -> None:
    context = FakeDomainContext()
    result = _evaluate(context, "smoke_gate")
    assert result.ready is True
