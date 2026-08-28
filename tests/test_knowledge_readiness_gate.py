"""Accepted-knowledge-package readiness gate + absorption re-check loop.

Covers plan Task 4 deliverable 3:
- hypothesis_design blocks without an accepted knowledge package and passes
  once a sideflow invocation is absorbed (completed + accepted + hash);
- a rejected handoff never unblocks the downstream node (fail-closed);
- after a successful absorb, the wired ``readiness_recheck`` hook creates a
  successor attempt at the requesting node THROUGH the command service
  (idempotency + CAS + fresh readiness apply), and never rewrites the
  parent checkpoint;
- when readiness is still unsatisfied, no attempt and no adapter dispatch
  is created.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services.team_workflow.research_runtime.event_publish_worker import (
    EventPublishWorker,
)
from core.web.services.team_workflow.research_runtime.readiness.knowledge_recheck import (
    build_knowledge_readiness_recheck,
)
from core.web.services.team_workflow.research_runtime.readiness.service import (
    NodeReadinessService,
)

from tests._support.readiness_fakes import FakeDomainContext
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS
from tests.test_knowledge_sideflow_run import (
    _invoke,
    _invocation_row,
    _outbox_rows,
    _seed_parent,
    _walk_child_to_handoff,
)

from tests._support.graph_helpers import GraphHarness


@pytest.fixture(autouse=True)
def _isolated_registry():
    from core.research.workflow.definition_registry import reset_registry_for_tests

    reset_registry_for_tests()
    from core.research.workflow.definition import build_challenge_cup_workflow_definition
    from core.research.workflow.definition_registry import register_or_resolve

    register_or_resolve(build_challenge_cup_workflow_definition())
    yield
    reset_registry_for_tests()


class StoreBackedKnowledgeContext(FakeDomainContext):
    """Fake readiness context whose knowledge probe reads the real ledger."""

    def __init__(self, store) -> None:
        super().__init__()
        self._store = store

    def accepted_knowledge_invocations(self, team_id: str, run_id: str):
        records = self._store.submit(
            lambda uow: uow.repository.list_knowledge_invocations_for_parent(run_id),
            force_flush=True,
        ).result(timeout=10)
        return [
            {
                "invocationId": record.invocation_id,
                "parentRunId": record.parent_run_id,
                "status": str(record.status),
                "handoffState": str(record.handoff_state),
                "packageContentHash": str(record.package_content_hash or ""),
            }
            for record in records or []
        ]


def _harness(tmp_path: Path, *, store_backed: bool = True) -> GraphHarness:
    harness = GraphHarness(tmp_path)
    if store_backed:
        harness.commands.context = StoreBackedKnowledgeContext(harness.commands.store)
    _seed_parent(harness)
    return harness


def _evaluate_hypothesis(harness: GraphHarness, *, use_cache: bool = False):
    readiness: NodeReadinessService = harness.commands.readiness
    return readiness.evaluate(
        team_id="research-team",
        run_id="run-parent",
        node_id="hypothesis_design",
        context=harness.commands.context,
        use_cache=use_cache,
    )


def _mark_invocation(harness: GraphHarness, invocation_id: str, *, handoff: str) -> None:
    harness.commands.store.submit(
        lambda uow: uow.repository.update_knowledge_invocation(
            invocation_id,
            FIXED_NOW_MS + 5,
            status="completed",
            knowledge_package_ref=json.dumps({"artifactId": "art-kp-1"}),
            package_content_hash="a" * 64,
            handoff_state=handoff,
        ),
        force_flush=True,
    ).result(timeout=10)


def _knowledge_blocker_codes(readiness) -> list[str]:
    return [
        blocker.code
        for blocker in readiness.blockers
        if blocker.code
        in {"knowledge_handoff_not_accepted", "knowledge_package_not_materialized"}
    ]


def test_knowledge_gate_blocks_without_package_passes_with_absorbed_invocation(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    try:
        blocked = _evaluate_hypothesis(harness)
        assert blocked.ready is False
        assert "knowledge_handoff_not_accepted" in _knowledge_blocker_codes(blocked)

        result = _invoke(harness)
        invocation_id = result["invocation"].invocation_id

        _mark_invocation(harness, invocation_id, handoff="accepted")
        passed = _evaluate_hypothesis(harness)
        assert _knowledge_blocker_codes(passed) == []

        # A rejected handoff never counts: the gate re-blocks (fail-closed).
        _mark_invocation(harness, invocation_id, handoff="rejected")
        rejected = _evaluate_hypothesis(harness)
        assert rejected.ready is False
        assert "knowledge_handoff_not_accepted" in _knowledge_blocker_codes(rejected)
    finally:
        harness.close()


def test_absorb_triggers_recheck_and_creates_successor_attempt(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    try:
        store = harness.commands.store
        result = _invoke(harness)
        child_run_id = result["childRunId"]
        parent_version_before = store.get_run("run-parent").run_version
        assert parent_version_before == 1

        pending = _walk_child_to_handoff(harness, child_run_id)
        assert pending is not None
        from tests.test_knowledge_sideflow_run import _accept_handoff

        _accept_handoff(harness, child_run_id, pending)
        assert len(_outbox_rows(harness, child_run_id, "event_publish")) == 1

        now = {"ms": FIXED_NOW_MS + 5000}
        worker = EventPublishWorker(
            store=store,
            now_provider=lambda: now["ms"],
            readiness_recheck=build_knowledge_readiness_recheck(
                store=store,
                command_service=harness.commands.command_service,
                readiness_invalidate=harness.commands.readiness.invalidate,
                now_provider=lambda: now["ms"],
            ),
        )
        assert worker.run_once() == 1

        # The requesting node gained a successor attempt through the single
        # write entry (attempt + graph_dispatch), not a checkpoint rewrite.
        attempt = store.latest_attempt("run-parent", "hypothesis_design")
        assert attempt is not None
        assert attempt.status == "starting"
        dispatches = _outbox_rows(harness, "run-parent", "graph_dispatch")
        assert len(dispatches) == 1 and dispatches[0][1] == "pending"
        assert store.get_run("run-parent").run_version == parent_version_before + 1

        # Re-delivery of the same payload is inert: the live attempt wins.
        payload = json.loads(_outbox_rows(harness, child_run_id, "event_publish")[0][2])
        from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import (
            absorb_knowledge_result,
        )

        replay = absorb_knowledge_result(
            store, payload, now_provider=lambda: now["ms"] + 1
        )
        assert replay["status"] == "already_absorbed"
        recheck = build_knowledge_readiness_recheck(
            store=store,
            command_service=harness.commands.command_service,
            readiness_invalidate=harness.commands.readiness.invalidate,
            now_provider=lambda: now["ms"] + 1,
        )
        recheck(payload)
        attempts = store.submit(
            lambda uow: uow.repository.list_attempts("run-parent"),
            force_flush=True,
        ).result(timeout=10)
        hypothesis_attempts = [
            item for item in attempts if item.node_id == "hypothesis_design"
        ]
        assert len(hypothesis_attempts) == 1
    finally:
        harness.close()


def test_recheck_creates_no_attempt_when_readiness_not_satisfied(
    tmp_path: Path,
) -> None:
    """No accepted-knowledge evidence in the readiness context -> blocked,
    no attempt, no adapter dispatch (fail-closed)."""
    harness = _harness(tmp_path, store_backed=False)
    try:
        store = harness.commands.store
        result = _invoke(harness)
        child_run_id = result["childRunId"]

        pending = _walk_child_to_handoff(harness, child_run_id)
        from tests.test_knowledge_sideflow_run import _accept_handoff

        _accept_handoff(harness, child_run_id, pending)

        now = {"ms": FIXED_NOW_MS + 5000}
        worker = EventPublishWorker(
            store=store,
            now_provider=lambda: now["ms"],
            readiness_recheck=build_knowledge_readiness_recheck(
                store=store,
                command_service=harness.commands.command_service,
                now_provider=lambda: now["ms"],
            ),
        )
        assert worker.run_once() == 1
        assert len(store.list_events("run-parent")) >= 1
        assert store.latest_attempt("run-parent", "hypothesis_design") is None
        assert _outbox_rows(harness, "run-parent", "graph_dispatch") == []
        assert store.get_run("run-parent").run_version == 1

        # The readiness authority still reports the knowledge gate.
        readiness = _evaluate_hypothesis(harness)
        assert readiness.ready is False
        assert "knowledge_handoff_not_accepted" in _knowledge_blocker_codes(readiness)
    finally:
        harness.close()


def test_human_rejection_leaves_downstream_without_evidence(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    try:
        store = harness.commands.store
        result = _invoke(harness)
        child_run_id = result["childRunId"]

        pending = _walk_child_to_handoff(harness, child_run_id)
        payload = json.loads(pending.payload_json)
        # The human REJECTS the knowledge handoff: no package receipt is ever
        # materialized and the child closes without a publishable result.
        harness.resume(
            run_id=child_run_id,
            node_id="knowledge_handoff",
            attempt=int(payload["attempt"]),
            action_id=str(payload["actionId"]),
            outcome="failed",
        )
        harness.consume_adapter(pending.action_id)
        for _ in range(4):
            harness.worker.run_once()

        invocation = _invocation_row(harness, result["invocation"].invocation_id)
        assert invocation.status != "completed"
        assert _outbox_rows(harness, child_run_id, "event_publish") == []

        now = {"ms": FIXED_NOW_MS + 5000}
        worker = EventPublishWorker(
            store=store,
            now_provider=lambda: now["ms"],
            readiness_recheck=build_knowledge_readiness_recheck(
                store=store,
                command_service=harness.commands.command_service,
                readiness_invalidate=harness.commands.readiness.invalidate,
                now_provider=lambda: now["ms"],
            ),
        )
        assert worker.run_once() == 0

        assert not any(
            event.event_type == "knowledge_result_absorbed"
            for event in store.list_events("run-parent")
        )
        assert store.latest_attempt("run-parent", "hypothesis_design") is None
        readiness = _evaluate_hypothesis(harness)
        assert readiness.ready is False
        assert "knowledge_handoff_not_accepted" in _knowledge_blocker_codes(readiness)
    finally:
        harness.close()
