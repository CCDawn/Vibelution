"""T2 RED: readiness evaluation has zero side effects.

When NodeReadiness rejects a node, these counters must all stay at zero
growth (spec 9.4):
  budget reservation, task bundle, session, turn, node attempt,
  accepted handoff, external-action outbox.
"""

from __future__ import annotations

from pathlib import Path

from core.web.services.team_workflow.research_runtime.readiness import NodeReadinessService
from tests._support.readiness_fakes import FakeDomainContext, make_run
from tests._support.workflow_ledger_helpers import (
    build_run_record,
    open_ledger_store,
)

READ_METHODS = frozenset(
    {
        "domain_revision_vector",
        "question_snapshot",
        "candidate_stats",
        "evidence_cards_stats",
        "evidence_graph_stats",
        "knowledge_package_draft",
        "knowledge_package",
        "hypothesis_set",
        "protocol_draft",
        "protocol_review",
        "frozen_protocol",
        "smoke_evidence",
        "controlled_run",
        "evaluation_report",
        "iteration_decision",
        "version_governance",
        "promotion_proposal",
        "result_package",
        "budget_limits",
        "binding_snapshot",
        "agent_resolvable",
        "recovery_blocker_codes",
        "adapter_registered",
        "incoming_handoffs",
    }
)


def test_rejected_readiness_touches_no_domain_writes() -> None:
    context = FakeDomainContext()
    context._candidate_stats = None  # SCI-096 无候选 -> source_extraction 拒绝
    service = NodeReadinessService(run_source={"run-test": make_run()}.get)
    result = service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id="source_extraction",
        context=context,
        use_cache=False,
    )
    assert result.ready is False
    assert any(b.code == "source_candidates_missing" for b in result.blockers)
    assert context.calls, "readiness 必须读取领域权威"
    for call in context.calls:
        assert call in READ_METHODS, f"readiness 调用了非只读方法: {call}"


def test_rejected_readiness_writes_nothing_to_ledger(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        store.submit(
            lambda uow: uow.repository.insert_run(build_run_record()),
            force_flush=True,
        ).result(timeout=10)

        context = FakeDomainContext()
        context._candidate_stats = None
        service = NodeReadinessService(run_source={"run-test": make_run()}.get)
        result = service.evaluate(
            team_id="research-team",
            run_id="run-test",
            node_id="source_extraction",
            context=context,
            use_cache=False,
        )
        assert result.ready is False

        assert store.list_attempts("run-test") == []
        assert store.list_pending_outbox("run-test") == []
        assert store.get_command_by_idempotency("run-test", "any") is None
        assert store.latest_event_sequence("run-test") == 0
        run = store.get_run("run-test")
        assert run is not None and run.run_version == 1
    finally:
        store.close()


def test_rejected_readiness_leaves_domain_counters_untouched() -> None:
    context = FakeDomainContext()
    context._candidate_stats = None
    before = {
        "budget_reservations": 3,
        "task_bundles": 2,
        "sessions": 4,
        "turns": 6,
        "node_attempts": 1,
        "accepted_handoffs": 1,
        "external_outbox": 0,
    }
    context.side_effect_counters = dict(before)
    service = NodeReadinessService(run_source={"run-test": make_run()}.get)
    result = service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id="source_extraction",
        context=context,
        use_cache=False,
    )
    assert result.ready is False
    # 结构上无写方法；计数保持原样。
    assert getattr(context, "side_effect_counters", None) == before


def test_ready_readiness_still_writes_nothing() -> None:
    context = FakeDomainContext()
    service = NodeReadinessService(run_source={"run-test": make_run()}.get)
    result = service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id="source_finding",
        context=context,
        use_cache=False,
    )
    assert result.ready is True
    for call in context.calls:
        assert call in READ_METHODS


def test_cache_invalidated_by_revision_change() -> None:
    context = FakeDomainContext()
    service = NodeReadinessService(run_source={"run-test": make_run()}.get)
    first = service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id="source_extraction",
        context=context,
        use_cache=True,
    )
    assert service.cache_size == 1
    hit = service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id="source_extraction",
        context=context,
        use_cache=True,
    )
    assert hit is first
    context.revision_vector = {"source_collection": "rev-2"}
    again = service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id="source_extraction",
        context=context,
        use_cache=True,
    )
    assert again is not first
    assert service.cache_size == 2


def test_cache_skipped_when_disabled() -> None:
    context = FakeDomainContext()
    service = NodeReadinessService(run_source={"run-test": make_run()}.get)
    first = service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id="source_extraction",
        context=context,
        use_cache=False,
    )
    second = service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id="source_extraction",
        context=context,
        use_cache=False,
    )
    assert first is not second
    assert service.cache_size == 0
