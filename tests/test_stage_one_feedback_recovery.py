"""Recovery retains all blockers and only waives the matching graph gaps."""
import json
from types import SimpleNamespace

import pytest

from core.web.services.team_workflow.research_runtime.command_offers.retry_node import succeeded_node_rerun_target
from tests.test_evidence_graph_missing_link_waiver import _evaluate, _graph_stats_payload, _missing_link


@pytest.mark.parametrize("detail, expected", [
    ("evidence_graph_incomplete; budget_safety_limit_reached", "evidence_relations"),
    ("budget_safety_limit_reached; evidence_graph_incomplete", "evidence_relations"),
    ("source_candidates_missing; evidence_graph_incomplete", "source_finding"),
    ("other_evidence_graph_incomplete", None),
])
def test_recovery_preserves_owner_with_multiple_blockers(detail, expected):
    run = SimpleNamespace(status="blocked", blocked_problem_json=json.dumps({
        "code": "auto_advance_not_ready", "detail": detail,
    }))
    assert succeeded_node_rerun_target(run) == expected


@pytest.mark.parametrize("waived_count, summary_count, should_block", [
    (0, 2, True), (1, 1, True), (1, 99, True), (2, 2, False),
])
def test_only_actual_waived_links_release_ingestion(monkeypatch, waived_count, summary_count, should_block):
    links = [_missing_link(target=f"target-{i}") for i in range(2)]
    for link in links[:waived_count]:
        link.update(waived=True, waiver={"by": "operator", "at": "now", "justification": "explicit review"})
    stats, verdict = _evaluate(monkeypatch, _graph_stats_payload(links, summary_count))
    assert stats["waiver_count"] == waived_count
    assert any(b.code == "evidence_graph_incomplete" for b in verdict.blockers) == should_block
