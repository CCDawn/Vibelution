"""Recovery: lagging checkpoint retry, blocked events, handoff artifact projection."""

from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.web.services.team_workflow.research_runtime.blocked_reason import (
    format_blocked_reason,
    parse_problem_json,
    problem_from_graph_error,
)
from core.web.services.team_workflow.research_runtime.command_offers import (
    build_command_offers,
)
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    _linear_successor_path,
)
from core.web.services.team_workflow.research_runtime.query_service import (
    WorkflowQueryService,
)
from tests._support.graph_helpers import GraphHarness
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
)


def test_parse_nested_required_artifact_problem() -> None:
    raw = json.dumps(
        {
            "code": "required_artifact_missing",
            "detail": json.dumps(
                {
                    "code": "required_artifact_missing",
                    "detail": "source_extraction requires ['evidence_card_batch']",
                }
            ),
        }
    )
    problem = parse_problem_json(raw)
    assert problem is not None
    assert problem["code"] == "required_artifact_missing"
    assert "evidence_card_batch" in problem["detail"]
    assert "缺少必需产物" in format_blocked_reason(problem)


def test_checkpoint_mismatch_is_not_iteration_decision() -> None:
    problem = problem_from_graph_error(
        "thread 中断于 source_finding，但 dispatch 目标是 source_extraction"
    )
    assert problem["code"] == "checkpoint_node_mismatch"


def test_dispatch_mismatch_writes_blocked_event_and_run_status(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        harness.enqueue_graph_dispatch("run-test", "source_extraction", 1)
        harness.worker.run_once()

        extraction = harness.commands.store.latest_attempt(
            "run-test", "source_extraction"
        )
        assert extraction is not None
        assert extraction.status == "blocked"
        assert "checkpoint_node_mismatch" in (extraction.problem_json or "")
        assert "iteration_decision_invalid" not in (extraction.problem_json or "")

        run = harness.commands.store.get_run("run-test")
        assert run is not None
        assert run.status == "blocked"
        assert run.blocked_problem_json
        assert "checkpoint_node_mismatch" in run.blocked_problem_json

        events = harness.commands.store.list_events("run-test")
        types = {event.event_type for event in events}
        assert "node_blocked" in types
        assert "run_blocked" in types
        blocked = next(event for event in events if event.event_type == "node_blocked")
        payload = json.loads(blocked.payload_json)
        assert payload["nodeId"] == "source_extraction"
        assert payload["code"] == "checkpoint_node_mismatch"
        assert payload["reason"]
    finally:
        harness.close()


def test_retry_advances_lagging_source_finding_checkpoint(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        first_action_id = json.loads(first_pending.payload_json)["actionId"]
        harness.consume_adapter(first_pending.action_id)

        finding = harness.commands.store.latest_attempt("run-test", "source_finding")
        assert finding is not None

        def prepare(uow):
            uow.repository.update_attempt_status(
                finding.node_run_id,
                "succeeded",
                FIXED_NOW_MS + 10,
                finished_at_ms=FIXED_NOW_MS + 10,
            )
            uow.repository.insert_handoff(
                handoff_id="ho-finding-extract",
                run_id="run-test",
                edge_id="source_finding->source_extraction",
                from_node_run_id=finding.node_run_id,
                to_node_id="source_extraction",
                to_node_run_id=None,
                gate_kind="auto",
                input_snapshot_hash="a" * 64,
                offered_at_ms=FIXED_NOW_MS + 10,
            )
            uow.repository.update_handoff_status(
                "ho-finding-extract", "ready", FIXED_NOW_MS + 11
            )
            uow.repository.update_handoff_status(
                "ho-finding-extract", "accepted", FIXED_NOW_MS + 12
            )
            uow.repository.insert_artifact_receipt(
                receipt_id="ar-candidates",
                run_id="run-test",
                node_run_id=finding.node_run_id,
                team_id="research-team",
                artifact_kind="source_candidate_batch",
                canonical_ref_json=json.dumps(
                    {"canonicalRef": "source_candidate_batch://research-team/run-test/abc"}
                ),
                artifact_version="1.0.0",
                sha256="a" * 64,
                domain_revision="rev-1",
                materialized=1,
                verified_at_ms=FIXED_NOW_MS + 10,
            )
            uow.repository.insert_handoff_receipt(
                "ho-finding-extract", "ar-candidates", 0
            )

        harness.commands.store.submit(prepare, force_flush=True).result(timeout=10)

        snapshot_before = harness.coordinator.snapshot("run-test")
        assert "source_finding" in (snapshot_before.get("nextNodeIds") or [])

        harness.enqueue_graph_dispatch("run-test", "source_extraction", 2)
        harness.worker.run_once()

        snapshot_after = harness.coordinator.snapshot("run-test")
        assert "source_extraction" in (snapshot_after.get("nextNodeIds") or []) or (
            (snapshot_after.get("values") or {}).get("active_node_id")
            == "source_extraction"
        )
        extraction = harness.commands.store.latest_attempt(
            "run-test", "source_extraction"
        )
        assert extraction is not None
        assert extraction.attempt == 2
        assert extraction.status == "dispatching"
        assert "checkpoint_node_mismatch" not in (extraction.problem_json or "")
        pending = harness.latest_adapter_pending()
        assert pending is not None
        payload = json.loads(pending.payload_json)
        assert payload["nodeId"] == "source_extraction"
        assert int(payload["attempt"]) == 2
    finally:
        harness.close()


def test_linear_path_reaches_controlled_run_from_source_finding() -> None:
    path = _linear_successor_path("source_finding", "controlled_run")
    assert path is not None
    assert path[0] == "source_finding"
    assert path[-1] == "controlled_run"
    assert path[path.index("smoke_gate") + 1] == "controlled_run"
    assert _linear_successor_path("controlled_run", "source_finding") is None
    assert _linear_successor_path("source_finding", "source_extraction") == [
        "source_finding",
        "source_extraction",
    ]


def test_retry_advances_multi_hop_lagging_checkpoint(tmp_path: Path) -> None:
    """SCI-096: thread still at source_finding, retry is two+ hops downstream."""
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        harness.consume_adapter(first_pending.action_id)

        finding = harness.commands.store.latest_attempt("run-test", "source_finding")
        assert finding is not None

        def prepare(uow):
            uow.repository.update_attempt_status(
                finding.node_run_id,
                "succeeded",
                FIXED_NOW_MS + 10,
                finished_at_ms=FIXED_NOW_MS + 10,
            )
            uow.repository.insert_handoff(
                handoff_id="ho-finding-extract",
                run_id="run-test",
                edge_id="source_finding->source_extraction",
                from_node_run_id=finding.node_run_id,
                to_node_id="source_extraction",
                to_node_run_id=None,
                gate_kind="auto",
                input_snapshot_hash="a" * 64,
                offered_at_ms=FIXED_NOW_MS + 10,
            )
            uow.repository.update_handoff_status(
                "ho-finding-extract", "ready", FIXED_NOW_MS + 11
            )
            uow.repository.update_handoff_status(
                "ho-finding-extract", "accepted", FIXED_NOW_MS + 12
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-extract-seed",
                    run_id="run-test",
                    node_id="source_extraction",
                    idempotency_key="seed-extract",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-run-test-source_extraction-a1",
                    run_id="run-test",
                    node_id="source_extraction",
                    attempt=1,
                    status="succeeded",
                    command_id="cmd-extract-seed",
                )
            )
            uow.repository.insert_handoff(
                handoff_id="ho-extract-relations",
                run_id="run-test",
                edge_id="source_extraction->evidence_relations",
                from_node_run_id="nr-run-test-source_extraction-a1",
                to_node_id="evidence_relations",
                to_node_run_id=None,
                gate_kind="auto",
                input_snapshot_hash="a" * 64,
                offered_at_ms=FIXED_NOW_MS + 13,
            )
            uow.repository.update_handoff_status(
                "ho-extract-relations", "ready", FIXED_NOW_MS + 14
            )
            uow.repository.update_handoff_status(
                "ho-extract-relations", "accepted", FIXED_NOW_MS + 15
            )

        harness.commands.store.submit(prepare, force_flush=True).result(timeout=10)

        snapshot_before = harness.coordinator.snapshot("run-test")
        assert "source_finding" in (snapshot_before.get("nextNodeIds") or [])

        harness.enqueue_graph_dispatch("run-test", "evidence_relations", 2)
        harness.worker.run_once()

        snapshot_after = harness.coordinator.snapshot("run-test")
        assert "evidence_relations" in (snapshot_after.get("nextNodeIds") or []) or (
            (snapshot_after.get("values") or {}).get("active_node_id")
            == "evidence_relations"
        )
        relations = harness.commands.store.latest_attempt(
            "run-test", "evidence_relations"
        )
        assert relations is not None
        assert relations.attempt == 2
        assert relations.status == "dispatching"
        assert "checkpoint_node_mismatch" not in (relations.problem_json or "")
        pending = harness.latest_adapter_pending()
        assert pending is not None
        payload = json.loads(pending.payload_json)
        assert payload["nodeId"] == "evidence_relations"
        assert int(payload["attempt"]) == 2
        finding_after = harness.commands.store.latest_attempt(
            "run-test", "source_finding"
        )
        assert finding_after is not None
        assert finding_after.status == "succeeded"
    finally:
        harness.close()


def test_succeeded_interrupt_redispatch_does_not_rewind_attempt(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        harness.consume_adapter(first_pending.action_id)
        finding = harness.commands.store.latest_attempt("run-test", "source_finding")
        assert finding is not None

        def prepare(uow):
            uow.repository.update_attempt_status(
                finding.node_run_id,
                "succeeded",
                FIXED_NOW_MS + 10,
                finished_at_ms=FIXED_NOW_MS + 10,
            )

        harness.commands.store.submit(prepare, force_flush=True).result(timeout=10)
        harness.enqueue_graph_dispatch(
            "run-test",
            "source_finding",
            1,
            command_id="cmd-stale-finding",
            idempotency_key="graph-stale-finding",
        )
        harness.worker.run_once()
        finding_after = harness.commands.store.latest_attempt(
            "run-test", "source_finding"
        )
        assert finding_after is not None
        assert finding_after.status == "succeeded"
    finally:
        harness.close()


def test_graph_at_node_ignores_active_node_id_without_interrupt() -> None:
    from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
        _graph_at_node,
    )

    snapshot = {
        "nextNodeIds": ["source_finding"],
        "values": {"active_node_id": "controlled_run", "active_attempt": 4},
        "pendingAction": {"nodeId": "source_finding", "runId": "run-test", "attempt": 1},
    }
    assert _graph_at_node(snapshot, "source_finding") is True
    assert _graph_at_node(snapshot, "controlled_run") is False


def test_retry_does_not_empty_ack_when_active_node_id_is_ahead(tmp_path: Path) -> None:
    """SCI-096 split: values already at the target, interrupt still upstream."""
    from core.research.workflow.challenge_cup_runtime import GraphDispatch

    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        harness.consume_adapter(first_pending.action_id)
        finding = harness.commands.store.latest_attempt("run-test", "source_finding")
        assert finding is not None

        def prepare(uow):
            uow.repository.update_attempt_status(
                finding.node_run_id,
                "succeeded",
                FIXED_NOW_MS + 10,
                finished_at_ms=FIXED_NOW_MS + 10,
            )
            uow.repository.insert_handoff(
                handoff_id="ho-split-extract",
                run_id="run-test",
                edge_id="source_finding->source_extraction",
                from_node_run_id=finding.node_run_id,
                to_node_id="source_extraction",
                to_node_run_id=None,
                gate_kind="auto",
                input_snapshot_hash="a" * 64,
                offered_at_ms=FIXED_NOW_MS + 10,
            )
            uow.repository.update_handoff_status(
                "ho-split-extract", "ready", FIXED_NOW_MS + 11
            )
            uow.repository.update_handoff_status(
                "ho-split-extract", "accepted", FIXED_NOW_MS + 12
            )

        harness.commands.store.submit(prepare, force_flush=True).result(timeout=10)
        harness.coordinator.retry_attempt(
            GraphDispatch(
                action_id="act-goto-split",
                run_id="run-test",
                node_run_id="nr-run-test-source_extraction-a2",
                node_id="source_extraction",
                attempt=2,
                dispatch_kind="start",
                team_id="research-team",
                input_snapshot_hash="a" * 64,
            )
        )
        harness.enqueue_graph_dispatch("run-test", "source_extraction", 2)
        harness.worker.run_once()
        extraction = harness.commands.store.latest_attempt(
            "run-test", "source_extraction"
        )
        assert extraction is not None
        assert extraction.status != "starting"
        if extraction.status == "dispatching":
            pending = harness.latest_adapter_pending()
            assert pending is not None
            assert json.loads(pending.payload_json)["nodeId"] == "source_extraction"
        finding_after = harness.commands.store.latest_attempt(
            "run-test", "source_finding"
        )
        assert finding_after is not None
        assert finding_after.status == "succeeded"
    finally:
        harness.close()


_HUMAN_NODES = {"knowledge_handoff", "protocol_freeze", "smoke_gate"}


def _split_empty_run_id_interrupt(harness: GraphHarness, run_id: str = "run-test") -> None:
    """Reproduce SCI-096: empty-runId finding interrupt, values at controlled_run."""
    graph, stack = harness.coordinator._compile()
    try:
        state = graph.get_state(harness.coordinator._config(run_id))
        saved = graph.update_state(
            state.config,
            {"run_id": "", "active_node_id": "controlled_run"},
        )
        graph.invoke(None, saved)
    finally:
        stack.close()


def _seed_succeeded_path(
    harness: GraphHarness,
    path: list[str],
    *,
    run_id: str = "run-test",
    with_handoffs: bool = True,
) -> None:
    def prepare(uow):
        for index, node_id in enumerate(path):
            node_run_id = f"nr-{run_id}-{node_id}-a1"
            actor_kind = "human" if node_id in _HUMAN_NODES else "agent"
            if uow.repository.get_attempt(node_run_id) is None:
                command_id = f"cmd-seed-{node_id}"
                uow.repository.insert_command(
                    build_command_record(
                        command_id=command_id,
                        run_id=run_id,
                        node_id=node_id,
                        idempotency_key=f"seed-{node_id}",
                    )
                )
                uow.repository.insert_attempt(
                    build_attempt_record(
                        node_run_id=node_run_id,
                        run_id=run_id,
                        node_id=node_id,
                        attempt=1,
                        actor_kind=actor_kind,
                        status="succeeded",
                        command_id=command_id,
                    )
                )
            else:
                uow.repository.update_attempt_status(
                    node_run_id,
                    "succeeded",
                    FIXED_NOW_MS + 10 + index,
                    finished_at_ms=FIXED_NOW_MS + 10 + index,
                )
            if not with_handoffs or index + 1 >= len(path):
                continue
            nxt = path[index + 1]
            handoff_id = f"ho-seed-{node_id}"
            uow.repository.insert_handoff(
                handoff_id=handoff_id,
                run_id=run_id,
                edge_id=f"{node_id}->{nxt}",
                from_node_run_id=node_run_id,
                to_node_id=nxt,
                to_node_run_id=None,
                gate_kind="human" if node_id in _HUMAN_NODES else "auto",
                input_snapshot_hash="a" * 64,
                offered_at_ms=FIXED_NOW_MS + 20 + index,
            )
            uow.repository.update_handoff_status(
                handoff_id, "ready", FIXED_NOW_MS + 21 + index
            )
            uow.repository.update_handoff_status(
                handoff_id, "accepted", FIXED_NOW_MS + 22 + index
            )

    harness.commands.store.submit(prepare, force_flush=True).result(timeout=10)


def test_empty_runid_interrupt_advances_without_handoff(tmp_path: Path) -> None:
    """SCI-096: stale finding interrupt has empty runId; Ledger already moved on."""
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        harness.consume_adapter(first_pending.action_id)
        _split_empty_run_id_interrupt(harness)
        before = harness.coordinator.snapshot("run-test")
        pending_before = before.get("pendingAction") or {}
        assert pending_before.get("nodeId") == "source_finding"
        assert not str(pending_before.get("runId") or "").strip()
        assert pending_before.get("nodeRunId") == "nr--source_finding-a1"
        values = before.get("values") or {}
        assert values.get("active_node_id") == "controlled_run"

        harness.enqueue_graph_dispatch("run-test", "source_extraction", 2)
        harness.worker.run_once()

        after = harness.coordinator.snapshot("run-test")
        pending_after = after.get("pendingAction") or {}
        assert pending_after.get("nodeId") == "source_extraction"
        assert pending_after.get("runId") == "run-test"
        extraction = harness.commands.store.latest_attempt(
            "run-test", "source_extraction"
        )
        assert extraction is not None
        assert extraction.status == "dispatching"
        assert "checkpoint_node_mismatch" not in (extraction.problem_json or "")
        adapter = harness.latest_adapter_pending()
        assert adapter is not None
        payload = json.loads(adapter.payload_json)
        assert payload["nodeId"] == "source_extraction"
        assert payload["runId"] == "run-test"
    finally:
        harness.close()


def test_empty_runid_interrupt_walks_to_controlled_run(tmp_path: Path) -> None:
    """SCI-096: finding interrupt must be pushed all the way to controlled_run."""
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        harness.consume_adapter(first_pending.action_id)
        _split_empty_run_id_interrupt(harness)
        path = _linear_successor_path("source_finding", "controlled_run")
        assert path is not None
        _seed_succeeded_path(harness, path[:-1], with_handoffs=False)

        harness.enqueue_graph_dispatch("run-test", "controlled_run", 4)
        harness.worker.run_once()

        after = harness.coordinator.snapshot("run-test")
        pending_after = after.get("pendingAction") or {}
        assert pending_after.get("nodeId") == "controlled_run"
        assert pending_after.get("runId") == "run-test"
        assert pending_after.get("nodeRunId") == "nr-run-test-controlled_run-a4"
        controlled = harness.commands.store.latest_attempt(
            "run-test", "controlled_run"
        )
        assert controlled is not None
        assert controlled.status == "dispatching"
        assert "checkpoint_node_mismatch" not in (controlled.problem_json or "")
        adapter = harness.latest_adapter_pending()
        assert adapter is not None
        payload = json.loads(adapter.payload_json)
        assert payload["nodeId"] == "controlled_run"
        assert int(payload["attempt"]) == 4
        assert payload["runId"] == "run-test"
    finally:
        harness.close()


def test_real_runid_finding_interrupt_walks_to_controlled_run(tmp_path: Path) -> None:
    """SCI-096 live: finding interrupt already has real runId and formula actionId."""
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        harness.consume_adapter(first_pending.action_id)
        before = harness.coordinator.snapshot("run-test")
        pending_before = before.get("pendingAction") or {}
        assert pending_before.get("nodeId") == "source_finding"
        assert pending_before.get("runId") == "run-test"
        assert pending_before.get("nodeRunId") == "nr-run-test-source_finding-a1"
        path = _linear_successor_path("source_finding", "controlled_run")
        assert path is not None
        _seed_succeeded_path(harness, path[:-1], with_handoffs=False)

        harness.enqueue_graph_dispatch(
            "run-test", "controlled_run", 3, command_id="cmd-retry-cr"
        )
        harness.worker.run_once()

        after = harness.coordinator.snapshot("run-test")
        pending_after = after.get("pendingAction") or {}
        assert pending_after.get("nodeId") == "controlled_run"
        assert pending_after.get("runId") == "run-test"
        assert pending_after.get("nodeRunId") == "nr-run-test-controlled_run-a3"
        controlled = harness.commands.store.latest_attempt(
            "run-test", "controlled_run"
        )
        assert controlled is not None
        assert controlled.status == "dispatching"
        assert "checkpoint_node_mismatch" not in (controlled.problem_json or "")
        adapter = harness.latest_adapter_pending()
        assert adapter is not None
        payload = json.loads(adapter.payload_json)
        assert payload["nodeId"] == "controlled_run"
        assert int(payload["attempt"]) == 3
        assert payload["runId"] == "run-test"
    finally:
        harness.close()


def _split_goto_controlled_run(harness: GraphHarness, run_id: str = "run-test") -> None:
    """Reproduce SCI-096: Command.goto writes values.controlled_run, finding stays."""
    from langgraph.types import Command

    graph, stack = harness.coordinator._compile()
    try:
        graph.invoke(
            Command(
                goto="controlled_run",
                update={
                    "run_id": run_id,
                    "active_node_id": "controlled_run",
                    "active_attempt": 2,
                },
            ),
            harness.coordinator._config(run_id),
        )
    finally:
        stack.close()


def test_goto_split_finding_interrupt_walks_to_controlled_run(tmp_path: Path) -> None:
    """SCI-096 live shape: values at controlled_run, interrupt still source_finding."""
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        harness.consume_adapter(first_pending.action_id)
        _split_goto_controlled_run(harness)
        before = harness.coordinator.snapshot("run-test")
        pending_before = before.get("pendingAction") or {}
        assert pending_before.get("nodeId") == "source_finding"
        assert pending_before.get("runId") == "run-test"
        assert (before.get("values") or {}).get("active_node_id") == "controlled_run"
        path = _linear_successor_path("source_finding", "controlled_run")
        assert path is not None
        _seed_succeeded_path(harness, path[:-1], with_handoffs=False)

        harness.enqueue_graph_dispatch(
            "run-test", "controlled_run", 3, command_id="cmd-retry-cr-goto"
        )
        harness.worker.run_once()

        after = harness.coordinator.snapshot("run-test")
        pending_after = after.get("pendingAction") or {}
        assert pending_after.get("nodeId") == "controlled_run"
        assert pending_after.get("runId") == "run-test"
        assert pending_after.get("nodeRunId") == "nr-run-test-controlled_run-a3"
        controlled = harness.commands.store.latest_attempt(
            "run-test", "controlled_run"
        )
        assert controlled is not None
        assert controlled.status == "dispatching"
        assert "checkpoint_node_mismatch" not in (controlled.problem_json or "")
    finally:
        harness.close()


def test_pump_repairs_starting_attempt_missing_graph_dispatch(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()

        def seed_starting(uow):
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-starting-orphan",
                    run_id="run-test",
                    node_id="problem_understanding",
                    idempotency_key="seed-starting-orphan",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-run-test-problem_understanding-a1",
                    run_id="run-test",
                    node_id="problem_understanding",
                    attempt=1,
                    status="starting",
                    command_id="cmd-starting-orphan",
                )
            )

        harness.commands.store.submit(seed_starting, force_flush=True).result(timeout=10)
        harness.worker.run_once()
        harness.worker.run_once()
        finding = harness.commands.store.latest_attempt(
            "run-test", "problem_understanding"
        )
        assert finding is not None
        assert finding.status == "dispatching"
        pending = harness.latest_adapter_pending()
        assert pending is not None
    finally:
        harness.close()


def test_half_advanced_resumes_when_checkpoint_still_at_predecessor(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        first_action_id = json.loads(first_pending.payload_json)["actionId"]
        harness.consume_adapter(first_pending.action_id)
        finding = harness.commands.store.latest_attempt("run-test", "source_finding")
        assert finding is not None

        def prepare(uow):
            uow.repository.update_attempt_status(
                finding.node_run_id,
                "succeeded",
                FIXED_NOW_MS + 10,
                finished_at_ms=FIXED_NOW_MS + 10,
            )
            uow.repository.insert_handoff(
                handoff_id="ho-lag",
                run_id="run-test",
                edge_id="source_finding->source_extraction",
                from_node_run_id=finding.node_run_id,
                to_node_id="source_extraction",
                to_node_run_id=None,
                gate_kind="auto",
                input_snapshot_hash="a" * 64,
                offered_at_ms=FIXED_NOW_MS + 10,
            )
            uow.repository.update_handoff_status("ho-lag", "ready", FIXED_NOW_MS + 11)
            uow.repository.update_handoff_status(
                "ho-lag", "accepted", FIXED_NOW_MS + 12
            )

        harness.commands.store.submit(prepare, force_flush=True).result(timeout=10)
        harness.resume(
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            action_id=first_action_id,
            outcome="succeeded",
        )
        harness.worker.run_once()
        snapshot = harness.coordinator.snapshot("run-test")
        assert "source_extraction" in (snapshot.get("nextNodeIds") or [])
        extraction = harness.commands.store.latest_attempt(
            "run-test", "source_extraction"
        )
        assert extraction is not None
    finally:
        harness.close()


def test_handoff_summary_includes_output_artifact_refs(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-ho", status="running", run_version=2)

        def seed(uow):
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-ho",
                    run_id="run-ho",
                    node_id="source_finding",
                    idempotency_key="seed-ho",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-run-ho-source_finding-a1",
                    run_id="run-ho",
                    node_id="source_finding",
                    attempt=1,
                    status="succeeded",
                    command_id="cmd-ho",
                )
            )
            uow.repository.insert_handoff(
                handoff_id="ho-1",
                run_id="run-ho",
                edge_id="source_finding->source_extraction",
                from_node_run_id="nr-run-ho-source_finding-a1",
                to_node_id="source_extraction",
                to_node_run_id=None,
                gate_kind="auto",
                input_snapshot_hash="a" * 64,
                offered_at_ms=FIXED_NOW_MS,
            )
            uow.repository.update_handoff_status("ho-1", "ready", FIXED_NOW_MS)
            uow.repository.update_handoff_status("ho-1", "accepted", FIXED_NOW_MS)
            uow.repository.insert_artifact_receipt(
                receipt_id="ar-1",
                run_id="run-ho",
                node_run_id="nr-run-ho-source_finding-a1",
                team_id="research-team",
                artifact_kind="source_candidate_batch",
                canonical_ref_json=json.dumps(
                    {"canonicalRef": "source_candidate_batch://research-team/run-ho/hash"}
                ),
                artifact_version="1.0.0",
                sha256="b" * 64,
                domain_revision="rev",
                materialized=1,
                verified_at_ms=FIXED_NOW_MS,
            )
            uow.repository.insert_handoff_receipt("ho-1", "ar-1", 0)

        harness.store.submit(seed, force_flush=True).result(timeout=10)
        query = WorkflowQueryService(
            store=harness.store,
            readiness_service=harness.readiness,
            readiness_context=lambda: harness.context,
            clock_iso=lambda: "2026-08-13T01:00:00.000Z",
            evaluated_at_ms=lambda: FIXED_NOW_MS,
        )
        snap = query.get_snapshot(team_id="research-team", run_id="run-ho")
        refs = snap.handoff_summary.refs
        assert len(refs) == 1
        assert refs[0].from_node_id == "source_finding"
        assert refs[0].to_node_id == "source_extraction"
        assert len(refs[0].output_artifact_refs) == 1
        assert refs[0].output_artifact_refs[0]["kind"] == "source_candidate_batch"
        payload = refs[0].to_dict()
        assert payload["outputArtifactRefs"][0]["kind"] == "source_candidate_batch"
    finally:
        harness.close()


def test_blocked_node_disables_start_and_keeps_retry(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-offers", status="blocked", run_version=3)

        def seed(uow):
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-ex",
                    run_id="run-offers",
                    node_id="source_extraction",
                    idempotency_key="seed-ex",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-run-offers-source_extraction-a2",
                    run_id="run-offers",
                    node_id="source_extraction",
                    attempt=2,
                    status="blocked",
                    command_id="cmd-ex",
                    problem_json=json.dumps(
                        {
                            "code": "checkpoint_node_mismatch",
                            "detail": "thread 中断于 source_finding，但 dispatch 目标是 source_extraction",
                        }
                    ),
                )
            )

        harness.store.submit(seed, force_flush=True).result(timeout=10)
        run = harness.store.get_run("run-offers")
        assert run is not None
        offers = build_command_offers(
            readiness_service=harness.readiness,
            context=harness.context,
            team_id=run.team_id,
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=harness.store.list_attempts("run-offers"),
            evaluated_at_ms=FIXED_NOW_MS,
        )
        start = next(
            offer
            for offer in offers
            if offer.command == WorkflowCommandKind.START_NODE
            and offer.node_id == "source_extraction"
        )
        retry = next(
            offer
            for offer in offers
            if offer.command == WorkflowCommandKind.RETRY_NODE
            and offer.node_id == "source_extraction"
        )
        assert start.available is False
        assert start.reason_code == "retry_owns_recovery"
        assert retry.available is True
    finally:
        harness.close()


def test_snapshot_overlays_blocked_status_from_active_attempt(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-overlay", status="running", run_version=2)

        def seed(uow):
            uow.repository.execute(
                "UPDATE workflow_runs SET active_node_id = ? WHERE run_id = ?",
                ("source_extraction", "run-overlay"),
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-overlay",
                    run_id="run-overlay",
                    node_id="source_extraction",
                    idempotency_key="seed-overlay",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-run-overlay-source_extraction-a2",
                    run_id="run-overlay",
                    node_id="source_extraction",
                    attempt=2,
                    status="blocked",
                    command_id="cmd-overlay",
                    problem_json=json.dumps(
                        {
                            "code": "checkpoint_node_mismatch",
                            "detail": "thread 中断于 source_finding，但 dispatch 目标是 source_extraction",
                        }
                    ),
                )
            )

        harness.store.submit(seed, force_flush=True).result(timeout=10)
        query = WorkflowQueryService(
            store=harness.store,
            readiness_service=harness.readiness,
            readiness_context=lambda: harness.context,
            clock_iso=lambda: "2026-08-13T01:00:00.000Z",
            evaluated_at_ms=lambda: FIXED_NOW_MS,
        )
        snap = query.get_snapshot(team_id="research-team", run_id="run-overlay")
        assert snap.run.status == "blocked"
        assert snap.run.blocked_reason
        assert "source_finding" in snap.run.blocked_reason
        detail = query.get_node_detail(
            team_id="research-team",
            run_id="run-overlay",
            node_id="source_extraction",
        )
        assert detail.status == "blocked"
        assert "source_finding" in (detail.blocked_reason or "")
        ledger_run = harness.store.get_run("run-overlay")
        assert ledger_run is not None
        assert ledger_run.status == "running"
    finally:
        harness.close()
