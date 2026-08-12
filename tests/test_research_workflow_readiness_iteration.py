"""T2 RED: execution/iteration readiness — controlled run through package."""

from __future__ import annotations

from core.web.services.team_workflow.research_runtime.readiness import NodeReadinessService
from tests._support.readiness_fakes import FakeDomainContext, make_run


def _evaluate(context, node_id):
    return NodeReadinessService(run_source={"run-test": make_run()}.get).evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id=node_id,
        context=context,
        use_cache=False,
    )


def test_controlled_run_blocks_without_smoke_release() -> None:
    context = FakeDomainContext()
    context._smoke_evidence = {"released": False}
    result = _evaluate(context, "controlled_run")
    assert result.ready is False
    assert any(b.code == "formal_run_not_released" for b in result.blockers)


def test_controlled_run_ready() -> None:
    context = FakeDomainContext()
    result = _evaluate(context, "controlled_run")
    assert result.ready is True


def test_result_evaluation_blocks_without_terminal_run() -> None:
    context = FakeDomainContext()
    context._controlled_run = {"terminal": False}
    result = _evaluate(context, "result_evaluation")
    assert result.ready is False
    assert any(b.code == "run_artifacts_incomplete" for b in result.blockers)


def test_result_evaluation_blocks_on_missing_artifacts() -> None:
    context = FakeDomainContext()
    context._controlled_run = {"terminal": True, "logs": True, "metrics": False, "artifact_hash": False}
    result = _evaluate(context, "result_evaluation")
    assert result.ready is False
    assert "metrics" in result.blockers[0].detail


def test_result_evaluation_ready() -> None:
    context = FakeDomainContext()
    result = _evaluate(context, "result_evaluation")
    assert result.ready is True


def test_iteration_decision_blocks_without_report() -> None:
    context = FakeDomainContext()
    context._evaluation_report = None
    result = _evaluate(context, "iteration_decision")
    assert result.ready is False
    assert any(b.code == "evaluation_incomplete" for b in result.blockers)


def test_iteration_decision_ready() -> None:
    context = FakeDomainContext()
    result = _evaluate(context, "iteration_decision")
    assert result.ready is True


def test_version_governance_blocks_without_decision() -> None:
    context = FakeDomainContext()
    context._iteration_decision = None
    result = _evaluate(context, "version_governance")
    assert result.ready is False
    assert any(b.code == "version_lineage_invalid" for b in result.blockers)


def test_version_governance_ready() -> None:
    context = FakeDomainContext()
    result = _evaluate(context, "version_governance")
    assert result.ready is True


def test_candidate_promotion_only_after_promote_decision() -> None:
    context = FakeDomainContext()
    context._version_governance = {
        "decision_kind": "stop",
        "candidate_hash": "h" * 64,
        "proposal": True,
    }
    result = _evaluate(context, "candidate_promotion")
    assert result.ready is False
    assert any(b.code == "promotion_proposal_invalid" for b in result.blockers)


def test_candidate_promotion_ready() -> None:
    context = FakeDomainContext()
    result = _evaluate(context, "candidate_promotion")
    assert result.ready is True


def test_result_package_blocks_when_incomplete() -> None:
    context = FakeDomainContext()
    context._result_package = None
    result = _evaluate(context, "result_package")
    assert result.ready is False
    assert any(b.code == "result_package_incomplete" for b in result.blockers)


def test_result_package_ready() -> None:
    context = FakeDomainContext()
    result = _evaluate(context, "result_package")
    assert result.ready is True
