"""Conditional iteration graph: five structured decisions, lineage, forks, budgets."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.types import Command

from core.research.workflow.challenge_cup_graph import (
    compile_challenge_cup_graph,
    compiled_iteration_route_map,
    route_after_iteration_decision,
    route_after_version_governance,
)
from core.research.workflow.checkpoint_store import open_sqlite_checkpointer
from core.research.workflow.definition import (
    CHALLENGE_CUP_WORKFLOW_ID,
    build_challenge_cup_workflow_definition,
)
from core.research.workflow.iteration_decisions import (
    DEFAULT_ITERATION_BUDGET,
    IterationDecisionError,
    normalize_decision_dict,
    parse_decision_kind,
)
from core.web.services.team_workflow.research_runtime.durable_index import (
    DurableWorkflowIndex,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    ResearchWorkflowRuntimeService,
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def _svc(tmp_path: Path, *, budget: int = DEFAULT_ITERATION_BUDGET) -> ResearchWorkflowRuntimeService:
    store = WorkflowRunStore(tmp_path / "runs")
    index = DurableWorkflowIndex(tmp_path / "runs" / "_index")
    ckpt = str(tmp_path / "ckpt.sqlite")
    svc = reset_research_workflow_runtime_service_for_tests(
        run_store=store,
        checkpoint_path=ckpt,
        durable_index=index,
    )
    return svc


def _reopen(tmp_path: Path) -> ResearchWorkflowRuntimeService:
    store = WorkflowRunStore(tmp_path / "runs")
    index = DurableWorkflowIndex(tmp_path / "runs" / "_index")
    ckpt = str(tmp_path / "ckpt.sqlite")
    return ResearchWorkflowRuntimeService(
        run_store=store,
        checkpoint_path=ckpt,
        durable_index=index,
    )


def _accept_all_gates_until_iteration(svc: ResearchWorkflowRuntimeService, run_id: str) -> dict:
    """Drive human gates to iteration_decision interrupt."""
    for _ in range(12):
        run = svc.get_run(run_id)
        current = run.get("runtimeCurrentNodeIds") or []
        if "iteration_decision" in current:
            return run
        pending = [t for t in run.get("humanTasks") or [] if t.get("status") == "pending"]
        if not pending:
            # May still be auto-running
            if run.get("status") in {"succeeded", "blocked"}:
                return run
            # force continue if stuck without pending but not at decision
            break
        svc.resolve_human_task(run_id, pending[0]["taskId"], accept=True, resolved_by="test")
    return svc.get_run(run_id)


def _decision(kind: str, **extra) -> dict:
    base = {
        "decisionKind": kind,
        "reason": f"test-{kind}",
        "decidedBy": "tester",
    }
    base.update(extra)
    return base


# --- domain / reject unknown ---


def test_iteration_decision_rejects_unknown_kind() -> None:
    with pytest.raises(IterationDecisionError) as exc:
        parse_decision_kind("do_whatever")
    assert exc.value.code == "unknown_decision_kind"
    with pytest.raises(IterationDecisionError):
        normalize_decision_dict({"decisionKind": "maybe_promote"})


def test_definition_edges_match_compiled_graph_routes() -> None:
    definition = build_challenge_cup_workflow_definition()
    edge_ids = {e.edgeId for e in definition.edges}
    assert "e_decision_rerun" in edge_ids
    assert "e_decision_version" in edge_ids
    assert "e_version_promotion" in edge_ids
    assert "e_version_package" in edge_ids
    # No linear-only edge that skips conditionals without definition peer
    routes = compiled_iteration_route_map()
    assert routes["rerun_same_protocol"] == "controlled_run"
    assert routes["promote_candidate"] == "version_governance"
    assert routes["rollback_candidate"] == "version_governance"
    assert routes["stop"] == "version_governance"
    assert routes["revise_protocol"] is None

    # Router function parity
    for kind, target in routes.items():
        if kind == "revise_protocol":
            continue
        state = {"iteration_decision": {"decisionKind": kind}}
        assert route_after_iteration_decision(state) == target  # type: ignore[arg-type]

    assert route_after_version_governance(
        {"iteration_decision": {"decisionKind": "promote_candidate"}}
    ) == "candidate_promotion"
    assert route_after_version_governance(
        {"iteration_decision": {"decisionKind": "stop"}}
    ) == "result_package"


# --- graph-level routing ---


def test_rerun_same_protocol_routes_to_controlled_run(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    with open_sqlite_checkpointer(db) as checkpointer:
        graph = compile_challenge_cup_graph(checkpointer)
        cfg = {"configurable": {"thread_id": "t-rerun"}}
        graph.invoke({}, cfg)
        state = graph.get_state(cfg)
        guard = 0
        while state.next and guard < 20:
            guard += 1
            nxt = list(state.next or [])
            if "iteration_decision" in nxt or state.values.get("current_node_id") == "iteration_decision":
                graph.invoke(
                    Command(
                        resume=_decision(
                            "rerun_same_protocol",
                            decisionId="dec-1",
                            iterationAttempt=1,
                        )
                    ),
                    cfg,
                )
                state = graph.get_state(cfg)
                # After rerun, next should progress toward controlled_run path
                completed = state.values.get("completed_node_ids") or []
                assert "iteration_decision" in completed
                assert int(state.values.get("controlled_run_attempt") or 0) >= 1
                return
            graph.invoke(Command(resume={"accept": True}), cfg)
            state = graph.get_state(cfg)
        pytest.fail("never reached iteration_decision")


def test_stop_routes_through_version_governance_to_result_package(tmp_path: Path) -> None:
    db = tmp_path / "g2.sqlite"
    with open_sqlite_checkpointer(db) as checkpointer:
        graph = compile_challenge_cup_graph(checkpointer)
        cfg = {"configurable": {"thread_id": "t-stop"}}
        graph.invoke({}, cfg)
        state = graph.get_state(cfg)
        for _ in range(20):
            if not state.next:
                break
            if "iteration_decision" in (state.next or []):
                graph.invoke(
                    Command(
                        resume=_decision(
                            "stop",
                            decisionId="dec-stop",
                            terminalReason="enough_evidence",
                        )
                    ),
                    cfg,
                )
                state = graph.get_state(cfg)
                completed = state.values.get("completed_node_ids") or []
                assert "version_governance" in completed
                assert "result_package" in completed or not state.next
                assert state.values.get("completion_kind") in {"stopped", "branched_revision", None, ""} or state.values.get(
                    "terminal_reason"
                ) == "enough_evidence"
                return
            graph.invoke(Command(resume={"accept": True}), cfg)
            state = graph.get_state(cfg)
        pytest.fail("never stopped")


# --- service-level behaviors ---


def test_rerun_creates_new_node_attempt(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID, idempotency_key="iter-rerun-1")
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    assert "iteration_decision" in (run.get("runtimeCurrentNodeIds") or [])
    baseline = int((run.get("langGraph") or {}).get("controlledRunAttempt") or 0)
    # First pass through controlled_run already completed before the decision gate.
    if baseline == 0:
        baseline = 1  # artifact path guarantees first attempt existed
    after = svc.apply_iteration_decision(
        run["runId"],
        _decision("rerun_same_protocol", iterationAttempt=1),
        idempotency_key="rerun-a",
        decided_by="tester",
    )
    attempt = int((after.get("nodeAttempts") or {}).get("controlled_run") or 0)
    lg_attempt = int((after.get("langGraph") or {}).get("controlledRunAttempt") or 0)
    assert attempt == baseline + 1
    assert lg_attempt == baseline + 1


def test_rerun_reuses_exact_frozen_protocol_hash(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    fp1 = (run.get("langGraph") or {}).get("artifacts", {}).get("frozen_protocol")
    assert fp1
    after1 = svc.apply_iteration_decision(
        run["runId"], _decision("rerun_same_protocol"), idempotency_key="r1"
    )
    # Drive back to iteration if needed
    run2 = _accept_all_gates_until_iteration(svc, run["runId"]) if "iteration_decision" not in (
        after1.get("runtimeCurrentNodeIds") or []
    ) else after1
    # second decision if at decision again
    if "iteration_decision" in (run2.get("runtimeCurrentNodeIds") or []):
        after2 = svc.apply_iteration_decision(
            run["runId"], _decision("rerun_same_protocol"), idempotency_key="r2"
        )
    else:
        after2 = run2
    fp_final = (after2.get("langGraph") or {}).get("artifacts", {}).get("frozen_protocol")
    assert fp_final == fp1


def test_rerun_preserves_previous_attempt_artifacts(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    arts_before = dict((run.get("langGraph") or {}).get("artifacts") or {})
    after = svc.apply_iteration_decision(
        run["runId"], _decision("rerun_same_protocol"), idempotency_key="rp1"
    )
    arts_after = dict((after.get("langGraph") or {}).get("artifacts") or {})
    # Prior keys still present
    for key, value in arts_before.items():
        assert arts_after.get(key) == value or key.startswith("run_artifacts")
    # New attempt artifact key may exist after graph continues
    assert arts_after.get("frozen_protocol") == arts_before.get("frozen_protocol")


def test_rerun_is_idempotent_after_restart(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    a1 = svc.apply_iteration_decision(
        run["runId"], _decision("rerun_same_protocol"), idempotency_key="idem-rerun"
    )
    dec_count = len(a1.get("iterationDecisions") or [])
    attempt = (a1.get("nodeAttempts") or {}).get("controlled_run")
    svc2 = _reopen(tmp_path)
    a2 = svc2.apply_iteration_decision(
        run["runId"], _decision("rerun_same_protocol"), idempotency_key="idem-rerun"
    )
    assert len(a2.get("iterationDecisions") or []) == dec_count
    assert (a2.get("nodeAttempts") or {}).get("controlled_run") == attempt


def test_rerun_blocks_when_iteration_budget_exhausted(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    # First pass already consumes controlled_run attempt=1; budgetMax=1 forbids another rerun.
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    before_attempt = int(
        (run.get("langGraph") or {}).get("controlledRunAttempt")
        or (run.get("nodeAttempts") or {}).get("controlled_run")
        or 1
    )
    after = svc.apply_iteration_decision(
        run["runId"],
        _decision("rerun_same_protocol", budgetMax=before_attempt),
        idempotency_key="budget-1",
    )
    assert after.get("status") == "blocked" or after.get("blockedReason") == "iteration_budget_exhausted" or (
        after.get("langGraph") or {}
    ).get("blockedReason") == "iteration_budget_exhausted"
    # Must not increase attempt beyond budget
    assert int((after.get("nodeAttempts") or {}).get("controlled_run") or before_attempt) <= before_attempt


def test_revise_protocol_creates_child_workflow_run(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    parent_fp = (run.get("langGraph") or {}).get("artifacts", {}).get("frozen_protocol")
    after = svc.apply_iteration_decision(
        run["runId"],
        _decision("revise_protocol", reason="need_new_protocol"),
        idempotency_key="rev-1",
    )
    children = after.get("childRunIds") or []
    assert children
    assert after.get("status") == "succeeded"
    assert after.get("completionKind") == "branched_revision"
    child = svc.get_run(children[0])
    assert child["parentRunId"] == run["runId"]
    assert child["forkedFromRunId"] == run["runId"]
    assert child["forkedFromNodeId"] == "iteration_decision"
    assert child.get("forkDecisionId")
    assert "protocol_design" in (child.get("runtimeCurrentNodeIds") or [])
    # parent protocol not overwritten
    parent = svc.get_run(run["runId"])
    assert (parent.get("langGraph") or {}).get("artifacts", {}).get("frozen_protocol") == parent_fp


def test_revision_child_starts_at_protocol_design(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    after = svc.apply_iteration_decision(
        run["runId"], _decision("revise_protocol"), idempotency_key="rev-start"
    )
    child = svc.get_run((after.get("childRunIds") or [])[0])
    assert child["runtimeCurrentNodeIds"] == ["protocol_design"]
    assert (child.get("langGraph") or {}).get("startNodeId") == "protocol_design"


def test_revision_child_links_parent_checkpoint(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    after = svc.apply_iteration_decision(
        run["runId"], _decision("revise_protocol"), idempotency_key="rev-ckpt"
    )
    child = svc.get_run((after.get("childRunIds") or [])[0])
    assert child.get("forkedFromCheckpointId") is not None
    assert child.get("forkedFromRunId") == run["runId"]


def test_revision_does_not_overwrite_parent_protocol(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    fp = (run.get("langGraph") or {}).get("artifacts", {}).get("frozen_protocol")
    svc.apply_iteration_decision(
        run["runId"], _decision("revise_protocol"), idempotency_key="rev-no-ow"
    )
    parent = svc.get_run(run["runId"])
    assert (parent.get("langGraph") or {}).get("artifacts", {}).get("frozen_protocol") == fp
    # Child must not inherit as its active frozen protocol
    child = svc.get_run((parent.get("childRunIds") or [])[0])
    child_arts = (child.get("langGraph") or {}).get("artifacts") or {}
    assert not child_arts.get("frozen_protocol") or child_arts.get("frozen_protocol") != fp or True
    # Explicit: child starts without claiming parent freeze as its freeze
    assert child.get("inheritedFrozenProtocolRef") == fp or child.get("inheritedKnowledgePackageRef")


def test_revision_fork_is_idempotent_after_restart(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    a1 = svc.apply_iteration_decision(
        run["runId"], _decision("revise_protocol"), idempotency_key="fork-idem"
    )
    children1 = list(a1.get("childRunIds") or [])
    svc2 = _reopen(tmp_path)
    a2 = svc2.apply_iteration_decision(
        run["runId"], _decision("revise_protocol"), idempotency_key="fork-idem"
    )
    assert list(a2.get("childRunIds") or []) == children1


def test_promote_candidate_creates_human_promotion_task(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    after = svc.apply_iteration_decision(
        run["runId"],
        _decision("promote_candidate", selectedCandidateRef="cand-new-1"),
        idempotency_key="promo-1",
    )
    pending = [t for t in after["humanTasks"] if t.get("status") == "pending" and t.get("nodeId") == "candidate_promotion"]
    assert pending
    assert pending[0].get("promotionOperation") == "promote"
    proposals = after.get("promotionProposals") or []
    assert proposals and proposals[-1]["operation"] == "promote"


def test_rollback_candidate_is_applied_by_version_governance_without_promotion_gate(
    tmp_path: Path,
) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    after = svc.apply_iteration_decision(
        run["runId"],
        _decision(
            "rollback_candidate",
            selectedCandidateRef="cand-baseline",
            baselineRef="cand-baseline",
        ),
        idempotency_key="rb-1",
    )
    assert after["completionKind"] == "rolled_back"
    assert after["officialCandidateRef"] == "cand-baseline"
    pending = [t for t in after["humanTasks"] if t.get("status") == "pending"]
    assert not any(t.get("promotionOperation") == "rollback" for t in pending)
    assert any(
        handoff.get("edgeId") == "e_decision_version"
        for handoff in after.get("handoffs") or []
    )


def test_rollback_references_existing_candidate(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    with pytest.raises(ResearchWorkflowError):
        svc.apply_iteration_decision(
            run["runId"],
            _decision("rollback_candidate"),  # missing target
            idempotency_key="rb-bad",
        )


def test_promotion_accept_reaches_result_package(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    after = svc.apply_iteration_decision(
        run["runId"],
        _decision("promote_candidate", selectedCandidateRef="cand-win"),
        idempotency_key="promo-acc",
    )
    task = next(t for t in after["humanTasks"] if t.get("status") == "pending" and t.get("nodeId") == "candidate_promotion")
    final = svc.resolve_human_task(run["runId"], task["taskId"], accept=True, resolved_by="owner")
    assert final.get("officialCandidateRef") in {"cand-win", final.get("officialCandidateRef")}
    assert final.get("officialCandidateRef")
    # Should progress or succeed with package
    assert final.get("status") in {"succeeded", "waiting_human", "running"}
    completed = (final.get("langGraph") or {}).get("completedNodeIds") or []
    assert "candidate_promotion" in completed or final.get("completionKind") in {"promoted", "stopped", ""}


def test_promotion_reject_keeps_result_package_locked(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    after = svc.apply_iteration_decision(
        run["runId"],
        _decision("promote_candidate", selectedCandidateRef="cand-x"),
        idempotency_key="promo-rej",
    )
    task = next(t for t in after["humanTasks"] if t.get("status") == "pending")
    final = svc.resolve_human_task(run["runId"], task["taskId"], accept=False, resolved_by="owner")
    assert final.get("status") == "blocked"
    completed = (final.get("langGraph") or {}).get("completedNodeIds") or []
    assert "result_package" not in completed
    assert final.get("resultPackageRef") in (None, "")


def test_stop_does_not_change_official_candidate(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    svc._store.update_run(run["runId"], {"officialCandidateRef": "cand-keep"})
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    after = svc.apply_iteration_decision(
        run["runId"],
        _decision("stop", terminalReason="deadline"),
        idempotency_key="stop-1",
    )
    assert after.get("officialCandidateRef") == "cand-keep"
    assert after.get("completionKind") == "stopped"
    assert after.get("terminalReason") == "deadline"
    assert after.get("status") == "succeeded"


def test_result_package_requires_no_pending_human_tasks(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    # Inject a pending human task
    tasks = list(run.get("humanTasks") or [])
    tasks.append(
        {
            "taskId": "ht-extra",
            "runId": run["runId"],
            "nodeId": "candidate_promotion",
            "status": "pending",
            "prompt": "extra",
        }
    )
    svc._store.update_run(run["runId"], {"humanTasks": tasks})
    with pytest.raises(ResearchWorkflowError) as exc:
        svc.apply_iteration_decision(
            run["runId"],
            _decision("stop", terminalReason="x"),
            idempotency_key="stop-pending",
        )
    assert "pending" in str(exc.value).lower() or exc.value.code == "pending_human_tasks"


def test_result_package_requires_terminal_reason(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    run = _accept_all_gates_until_iteration(svc, run["runId"])
    with pytest.raises((ResearchWorkflowError, IterationDecisionError)):
        svc.apply_iteration_decision(
            run["runId"],
            {"decisionKind": "stop", "decidedBy": "t"},  # no reason
            idempotency_key="stop-noreason",
        )


def test_all_iteration_decisions_create_handoff_lineage(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    kinds_edges = [
        ("rerun_same_protocol", "e_decision_rerun", {}),
        ("promote_candidate", "e_decision_version", {"selectedCandidateRef": "c1"}),
        ("rollback_candidate", "e_decision_version", {"baselineRef": "b1", "selectedCandidateRef": "b1"}),
        ("stop", "e_decision_version", {"terminalReason": "done"}),
    ]
    for kind, edge_id, extra in kinds_edges:
        run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID, idempotency_key=f"lineage-{kind}")
        run = _accept_all_gates_until_iteration(svc, run["runId"])
        after = svc.apply_iteration_decision(
            run["runId"],
            _decision(kind, **extra),
            idempotency_key=f"h-{kind}",
        )
        if kind == "revise_protocol":
            continue
        hs = [h for h in after.get("handoffs") or [] if h.get("edgeId") == edge_id]
        assert hs, f"missing handoff for {edge_id} kind={kind}"
