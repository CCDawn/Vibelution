"""T2 RED: source collection / evidence / knowledge readiness — the
SCI-096 missing-candidates scenario surfaces the same blocker as the
command path will."""

from __future__ import annotations

from core.web.services.team_workflow.research_runtime.readiness import (
    NodeReadinessService,
)
from core.web.services.team_workflow.research_runtime.readiness.common import (
    hypothesis_first_chain_state,
)
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


def test_problem_understanding_ready_with_question() -> None:
    service = _service()
    context = FakeDomainContext()
    context.bindings["problem_understanding"] = {
        "snapshotId": "bs-problem",
        "agentId": "agent-a",
    }
    context._question = {"questionId": "SCI-096", "snapshotHash": "q" * 64}
    result = _evaluate(service, context, "problem_understanding")
    assert result.ready is True


def test_problem_understanding_missing_question_blocks() -> None:
    service = _service()
    context = FakeDomainContext()
    context.bindings["problem_understanding"] = {
        "snapshotId": "bs-problem",
        "agentId": "agent-a",
    }
    context._question = None
    result = _evaluate(service, context, "problem_understanding")
    assert result.ready is False
    assert any(b.code == "question_snapshot_missing" for b in result.blockers)


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


def test_hypothesis_chain_readiness_passes_current_workflow_run_id() -> None:
    context = FakeDomainContext()
    calls: list[tuple[str, str, str]] = []

    def read_chain_state(team_id: str, question_id: str, workflow_run_id: str):
        calls.append((team_id, question_id, workflow_run_id))
        return {"collectionReady": False}

    context.hypothesis_first_chain_state = read_chain_state  # type: ignore[attr-defined]
    state = hypothesis_first_chain_state(
        context,
        make_run(run_id="run-new", team_id="team-new", question_id="SCI-002"),
    )

    assert state == {"collectionReady": False}
    assert calls == [("team-new", "SCI-002", "run-new")]


def test_sci096_missing_candidates_blocks_source_extraction() -> None:
    service = _service()
    context = FakeDomainContext()
    context._candidate_stats = None
    result = _evaluate(service, context, "source_extraction")
    assert result.ready is False
    assert any(b.code == "source_candidates_missing" for b in result.blockers)
    assert result.blockers[0].detail


def test_missing_candidates_blocker_points_to_finding_rerun() -> None:
    """Empty candidate store after a succeeded finding attempt must remediate
    by re-running the idempotent finding stage, not by retrying extraction."""
    from core.research.workflow.contracts.node_readiness import RemediationKind

    for stats in (None, {"record_count": 0}):
        service = _service()
        context = FakeDomainContext()
        context._candidate_stats = stats
        result = _evaluate(service, context, "source_extraction")
        blocker = next(
            b for b in result.blockers if b.code == "source_candidates_missing"
        )
        assert blocker.remediation is not None
        assert blocker.remediation.kind == RemediationKind.RETRY
        assert blocker.remediation.label == "重跑资料寻找"
        assert blocker.remediation.target_node_id == "source_finding"


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


# ---------------------------------------------------------------------------
# Scoped candidate stats regression (run-16cfab646d08 family root causes).
# ---------------------------------------------------------------------------

from core.web.services import data_processing_service, team_workflow_orchestration_service


def test_scope_candidates_admits_tagged_and_skips_unmarked() -> None:
    from core.web.services.team_workflow.research_runtime.readiness_providers import (
        _scope_candidates,
    )

    tagged = {
        "candidateId": "c-1",
        "metadata": {
            "sourceCollectionRunId": "dprun-x",
            "researchProjectId": "research-a",
            "workflowRunId": "run-w",
        },
    }
    unmarked = {"candidateId": "c-2", "metadata": {}}
    snapshot = {"sourceCollectionRunId": "dprun-x", "projectId": "research-a"}
    assert _scope_candidates([tagged, unmarked], snapshot, "run-w") == [tagged]


def test_scope_candidates_skips_other_run_markers() -> None:
    from core.web.services.team_workflow.research_runtime.readiness_providers import (
        _scope_candidates,
    )

    other_sc_run = {"candidateId": "c-3", "metadata": {"sourceCollectionRunId": "dprun-other"}}
    other_project = {
        "candidateId": "c-4",
        "metadata": {"sourceCollectionRunId": "dprun-x", "researchProjectId": "research-b"},
    }
    snapshot = {"sourceCollectionRunId": "dprun-x", "projectId": "research-a"}
    assert _scope_candidates([other_sc_run, other_project], snapshot, "run-w") == []


def test_fetch_candidate_stats_falls_back_to_data_processing_records(tmp_path, monkeypatch) -> None:
    """根因 C：scoped 候选过滤为空时，兜底 recordCount 读 data_processing 记录权威。

    复现 run-16cfab646d08：活跃项目与 run 属主项目分离后 get_source_collection_summary
    抛「不属于活跃项目」被吞掉，兜底恒 0。
    """
    from core.web.services.team_workflow import research_projects as research_projects_service
    from core.web.services.team_workflow.research_runtime.readiness_providers import (
        fetch_candidate_stats,
    )
    from tests._support.team_workflow.cases_source_collection import (
        _finding_close_first_step_task,
    )

    env = _finding_close_first_step_task(tmp_path, monkeypatch)
    team = env["team"]
    run_id = env["runId"]
    task = env["task"]
    workflow_run_id = str(task.get("workflowRunId") or "")
    assert workflow_run_id

    run_scope = (data_processing_service.get_processing_run(run_id).get("scope") or {})
    owner_project_id = str(run_scope.get("researchProjectId") or "")

    data_processing_service.add_record(
        run_id,
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.1038/stats-1",
            "title": "Fallback record 1",
            "summary": "data_processing 记录权威回归。",
            "metadata": {"doi": "10.1038/stats-1"},
        },
    )
    data_processing_service.add_record(
        run_id,
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.1038/stats-2",
            "title": "Fallback record 2",
            "summary": "data_processing 记录权威回归。",
            "metadata": {"doi": "10.1038/stats-2"},
        },
    )

    # 活跃项目与 run 属主项目分离（与实测现象一致）。
    project_b = research_projects_service.create_research_project(
        team["teamId"], {"name": "challenge-sci-001-sim"}
    )["project"]
    research_projects_service.activate_research_project(team["teamId"], project_b["projectId"])

    stats = fetch_candidate_stats(
        team["teamId"],
        workflow_run_id,
        input_snapshot={"sourceCollectionRunId": run_id, "projectId": owner_project_id},
    )
    assert stats is not None
    assert stats["record_count"] == 2


def test_fetch_candidate_stats_unlocks_with_tagged_candidates(tmp_path, monkeypatch) -> None:
    """根因 B + A 联动：带定界标记的候选在活跃项目漂移后仍解锁 scoped readiness。"""
    from core.web.services.team_workflow import research_projects as research_projects_service
    from core.web.services.team_workflow.research_runtime.readiness_providers import (
        fetch_candidate_stats,
    )
    from tests._support.team_workflow.cases_source_collection import (
        _finding_close_first_step_task,
    )

    env = _finding_close_first_step_task(tmp_path, monkeypatch)
    team = env["team"]
    run_id = env["runId"]
    task = env["task"]
    workflow_run_id = str(task.get("workflowRunId") or "")

    lead = {
        "leadId": "lead-readiness-unlock",
        "title": "Predictive coding unlocks readiness",
        "locator": "https://doi.org/10.1038/unlock",
        "sourceType": "paper",
        "query": "predictive coding",
        "perspective": "mechanism",
    }
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {"status": "needs_review", "summary": "写回解锁候选。", "result": {"candidateLeads": [lead]}},
    )
    assert response["writeback"]["materializedSources"]["importedCandidateCount"] == 1

    run_scope = (data_processing_service.get_processing_run(run_id).get("scope") or {})
    owner_project_id = str(run_scope.get("researchProjectId") or "")

    project_b = research_projects_service.create_research_project(
        team["teamId"], {"name": "challenge-sci-001-sim"}
    )["project"]
    research_projects_service.activate_research_project(team["teamId"], project_b["projectId"])

    stats = fetch_candidate_stats(
        team["teamId"],
        workflow_run_id,
        input_snapshot={"sourceCollectionRunId": run_id, "projectId": owner_project_id},
    )
    assert stats is not None
    assert stats["record_count"] == 1
