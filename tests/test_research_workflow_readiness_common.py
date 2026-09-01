"""T2 RED: common readiness checks — scope, state, attempts, handoffs,
recovery, budget, actor."""

from __future__ import annotations

from core.web.services.team_workflow.research_runtime.readiness import NodeReadinessService
from tests._support.readiness_fakes import FakeDomainContext, make_run


def _service(runs=None, attempts=None) -> NodeReadinessService:
    runs = runs or {"run-test": make_run()}

    def attempt_count(run_id: str, node_id: str) -> int:
        if attempts is None:
            return 0
        return attempts.get((run_id, node_id), 0)

    return NodeReadinessService(run_source=runs.get, attempt_count_source=attempt_count)


def _evaluate(service, context, node_id="source_finding"):
    return service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id=node_id,
        context=context,
        use_cache=False,
    )


def test_team_scope_mismatch_blocks() -> None:
    service = _service()
    context = FakeDomainContext()
    result = _evaluate(service, context)
    assert result.ready is True

    result = service.evaluate(
        team_id="other-team",
        run_id="run-test",
        node_id="source_finding",
        context=context,
        use_cache=False,
    )
    assert result.ready is False
    assert result.blockers[0].code == "team_scope_mismatch"


def test_run_missing_returns_run_not_found() -> None:
    service = _service()
    result = service.evaluate(
        team_id="research-team",
        run_id="run-missing",
        node_id="source_finding",
        context=FakeDomainContext(),
        use_cache=False,
    )
    assert result.ready is False
    assert result.blockers[0].code == "run_not_found"


def test_terminal_run_blocks() -> None:
    service = _service(runs={"run-test": make_run(status="cancelled")})
    result = _evaluate(service, FakeDomainContext())
    assert result.ready is False
    assert any(b.code == "run_terminal" for b in result.blockers)


def test_reconciliation_required_blocks() -> None:
    service = _service(runs={"run-test": make_run(status="reconciliation_required")})
    result = _evaluate(service, FakeDomainContext())
    assert result.ready is False
    assert any(b.code == "run_reconciliation_required" for b in result.blockers)


def test_live_attempt_blocks() -> None:
    service = _service(attempts={("run-test", "source_finding"): 1})
    result = _evaluate(service, FakeDomainContext())
    assert result.ready is False
    assert any(b.code == "node_live_attempt" for b in result.blockers)


def test_unaccepted_incoming_handoff_blocks() -> None:
    service = _service()
    context = FakeDomainContext()
    context.handoffs["source_extraction"] = [
        type("H", (), {"handoff_id": "ho-1", "from_node_run_id": "nr-1", "status": "pending"})()
    ]
    result = service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id="source_extraction",
        context=context,
        use_cache=False,
    )
    assert result.ready is False
    assert any(b.code == "handoff_not_accepted" for b in result.blockers)


def test_accepted_handoff_unlocks_downstream() -> None:
    service = _service()
    context = FakeDomainContext()
    context.handoffs["source_extraction"] = [
        type("H", (), {"handoff_id": "ho-1", "from_node_run_id": "nr-1", "status": "accepted"})()
    ]
    result = service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id="source_extraction",
        context=context,
        use_cache=False,
    )
    assert result.ready is True
    assert result.accepted_handoff_ids == ("ho-1",)


def test_unresolved_recovery_record_blocks() -> None:
    service = _service()
    context = FakeDomainContext()
    context.recovery_codes = ["source_candidates_missing"]
    result = _evaluate(service, context)
    assert result.ready is False
    assert any(b.code == "recovery_blocked" for b in result.blockers)


def test_budget_limit_blocks() -> None:
    service = _service()
    context = FakeDomainContext()
    context.budget = type(
        "Budget",
        (),
        {
            "policy_hash": "p-1",
            "stage_tokens_limit": 100,
            "stage_tokens_consumed": 90,
            "max_tool_calls": 300,
            "tool_calls_consumed": 0,
            "max_seconds": 21600,
            "seconds_consumed": 0,
            "auto_retries": 2,
            "retries_consumed": 0,
            "estimated_next_attempt_tokens": 20,
            "available": lambda self: (False, "stage_tokens_limit_reached"),
        },
    )()
    result = _evaluate(service, context)
    assert result.ready is False
    assert any(b.code == "budget_safety_limit_reached" for b in result.blockers)


def test_budget_limit_blocker_offers_extend_budget_remediation() -> None:
    """T2: the 412 payload must tell the operator how to exit a mid-run
    budget exhaustion instead of leaving run abandonment as the only exit."""
    service = _service()
    context = FakeDomainContext()
    context.budget = type(
        "Budget",
        (),
        {
            "policy_hash": "p-1",
            "stage_tokens_limit": 100,
            "stage_tokens_consumed": 90,
            "max_tool_calls": 300,
            "tool_calls_consumed": 0,
            "max_seconds": 21600,
            "seconds_consumed": 0,
            "auto_retries": 2,
            "retries_consumed": 0,
            "estimated_next_attempt_tokens": 20,
            "available": lambda self: (False, "stage_tokens_limit_reached"),
        },
    )()
    result = _evaluate(service, context)
    blocker = next(
        b for b in result.blockers if b.code == "budget_safety_limit_reached"
    )
    assert blocker.remediation is not None
    assert blocker.remediation.kind.value == "extend_budget"
    assert blocker.remediation.label == "上调本 run 预算上限"
    payload = blocker.to_dict()
    assert payload["remediation"]["kind"] == "extend_budget"
    assert payload["remediation"]["label"] == "上调本 run 预算上限"


def test_agent_not_configured_blocks_agent_node() -> None:
    service = _service()
    context = FakeDomainContext()
    context.bindings["source_finding"] = None
    result = _evaluate(service, context)
    assert result.ready is False
    assert any(b.code == "agent_not_configured" for b in result.blockers)
    assert result.actor.configured is False


def test_agent_unresolvable_reports_actor_readiness() -> None:
    service = _service()
    context = FakeDomainContext()
    context.resolvable_agents = set()
    result = _evaluate(service, context)
    assert result.actor.configured is True
    assert result.actor.resolvable is False
    assert result.ready is False
    assert any(b.code == "agent_not_configured" for b in result.blockers)


def test_human_node_always_actor_ready() -> None:
    service = _service()
    context = FakeDomainContext()
    context.bindings = {}
    result = service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id="knowledge_handoff",
        context=context,
        use_cache=False,
    )
    assert result.actor.configured is True
    assert result.actor.resolvable is True


def test_missing_adapter_blocks() -> None:
    service = _service()
    context = FakeDomainContext()
    context.registered_adapters = set(context.registered_adapters) - {"source_finding"}
    result = _evaluate(service, context)
    assert result.ready is False
    assert any(b.code == "adapter_not_registered" for b in result.blockers)
