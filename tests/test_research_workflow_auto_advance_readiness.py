"""P1-5a RED: auto-advanced successors must re-run NodeReadiness.

When the graph advances to a NEW node (auto-created attempt), the worker must
re-evaluate NodeReadiness before creating the adapter outbox. A not-ready
successor gets a blocked attempt and no adapter outbox; a ready successor
proceeds normally.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.challenge_cup_runtime import ChallengeCupGraphCoordinator
from core.research.workflow.contracts import (
    NodeReadiness,
    ReadinessBlocker,
)
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)
from tests._support.command_helpers import CommandHarness
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


class StubReadiness:
    def __init__(self, *, ready: bool, blockers: tuple[str, ...] = ()) -> None:
        self._ready = ready
        self._blockers = blockers

    def evaluate(self, *, team_id, run_id, node_id, context, use_cache=True):
        return NodeReadiness(
            run_id=run_id,
            team_id=team_id,
            node_id=node_id,
            run_version=1,
            ready=self._ready,
            evaluated_at_ms=FIXED_NOW_MS,
            domain_revision_vector={},
            accepted_handoff_ids=(),
            input_artifact_refs=(),
            actor=None,
            budget=None,
            blockers=tuple(
                ReadinessBlocker(code=code, title=code, detail=code)
                for code in self._blockers
            ),
        )


def _worker_with_readiness(
    harness: GraphHarness,
    readiness: StubReadiness,
    *,
    owner: str = "graph-worker-readiness",
) -> GraphDispatchWorker:
    return GraphDispatchWorker(
        store=harness.commands.store,
        coordinator=ChallengeCupGraphCoordinator(harness.tmp_path / "checkpoints.sqlite"),
        owner_id=owner,
        now_provider=lambda: FIXED_NOW_MS + 1000,
        readiness_service=readiness,
        readiness_context=lambda: None,
    )


def _consume_adapter(harness: GraphHarness, action_id: str) -> None:
    def mutate(uow):
        uow.repository.execute(
            "UPDATE outbox_actions SET status = 'succeeded' WHERE action_id = ?",
            (action_id,),
        )

    harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def test_not_ready_successor_blocked_no_adapter(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        first_action_id = json.loads(first_pending.payload_json)["actionId"]
        _consume_adapter(harness, first_pending.action_id)

        # resume succeeded -> graph 推进到 source_extraction（新节点）。
        harness.resume(
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            action_id=first_action_id,
            outcome="succeeded",
        )
        # 后继 source_extraction 不 ready。
        worker = _worker_with_readiness(
            harness,
            StubReadiness(
                ready=False,
                blockers=("source_candidates_missing", "handoff_not_accepted"),
            ),
        )
        handled = worker.run_once()
        assert handled == 1

        attempts = harness.commands.store.list_attempts("run-test")
        extraction = next(
            (a for a in attempts if a.node_id == "source_extraction"), None
        )
        assert extraction is not None
        assert extraction.status == "blocked"
        assert "auto_advance_not_ready" in (extraction.problem_json or "")
        assert "source_candidates_missing" in (extraction.problem_json or "")

        adapter_rows = harness.commands.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM outbox_actions WHERE action_kind = 'adapter_dispatch'"
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        # 入口与 source_finding 的 adapter 均已 consume，source_extraction 未创建。
        assert len(adapter_rows) == 2
        assert all(row[0] == "succeeded" for row in adapter_rows)
        # 事件记录 node_blocked。
        events = harness.commands.store.list_events("run-test")
        assert any(e.event_type == "node_blocked" for e in events)
    finally:
        harness.close()


def test_ready_successor_creates_adapter_outbox(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        first_action_id = json.loads(first_pending.payload_json)["actionId"]
        _consume_adapter(harness, first_pending.action_id)

        harness.resume(
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            action_id=first_action_id,
            outcome="succeeded",
        )
        worker = _worker_with_readiness(harness, StubReadiness(ready=True))
        handled = worker.run_once()
        assert handled == 1

        extraction = next(
            (
                a
                for a in harness.commands.store.list_attempts("run-test")
                if a.node_id == "source_extraction"
            ),
            None,
        )
        assert extraction is not None
        assert extraction.status == "dispatching"
        pending = harness.latest_adapter_pending()
        assert pending is not None
        assert json.loads(pending.payload_json)["nodeId"] == "source_extraction"
    finally:
        harness.close()


def test_no_readiness_wiring_defaults_to_pass(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        first_action_id = json.loads(first_pending.payload_json)["actionId"]
        _consume_adapter(harness, first_pending.action_id)
        harness.resume(
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            action_id=first_action_id,
            outcome="succeeded",
        )
        handled = harness.worker.run_once()
        assert handled == 1
        extraction = next(
            (
                a
                for a in harness.commands.store.list_attempts("run-test")
                if a.node_id == "source_extraction"
            ),
            None,
        )
        assert extraction is not None and extraction.status == "dispatching"
    finally:
        harness.close()
