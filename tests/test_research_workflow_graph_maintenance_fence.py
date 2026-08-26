from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from core.research.workflow.challenge_cup_runtime import GraphDispatch
from core.research.workflow.ledger import outbox as outbox_api
from core.web.services.team_workflow.research_runtime import (
    challenge_cup_maintenance_fence as fence,
)
from core.web.services.team_workflow.research_runtime import graph_dispatch_worker
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def _dispatch() -> GraphDispatch:
    return GraphDispatch(
        action_id="act-maintenance-fence",
        run_id="run-maintenance-fence",
        node_run_id="nr-maintenance-fence",
        node_id="problem_understanding",
        attempt=1,
        dispatch_kind="start",
        input_snapshot_hash="a" * 64,
        workflow_version_id="challenge-cup-research-v2.1.0",
        team_id="research-team",
    )


def test_graph_worker_reclaims_expired_fence_before_dispatch(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(fence, "research_workflow_data_root", lambda: tmp_path)
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(run_id="run-maintenance-fence")
        fence.acquire_fence(
            "research-team",
            purge_plan_id="plan-expired",
            inventory_hash="b" * 64,
            ttl_ms=1,
            owner_pid=99999999,
            now_ms=FIXED_NOW_MS,
        )
        harness.enqueue_graph_dispatch(
            "run-maintenance-fence", "problem_understanding", 1
        )

        assert harness.worker.run_once() == 1
        assert harness.latest_adapter_pending("run-maintenance-fence") is not None
        assert fence.read_fence(
            "research-team", now_ms=FIXED_NOW_MS + 1000
        ) is None
    finally:
        harness.close()


def test_graph_defer_requeues_immediately_after_orphan_reclaim(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(fence, "research_workflow_data_root", lambda: tmp_path)
    harness = GraphHarness(tmp_path)
    calls: list[dict[str, int]] = []
    monkeypatch.setattr(
        outbox_api,
        "requeue_action",
        lambda *_args, **kwargs: calls.append(kwargs) or True,
    )
    monkeypatch.setattr(graph_dispatch_worker, "_record_scene_event", lambda *_args, **_kwargs: None)
    try:
        fence.acquire_fence(
            "research-team",
            purge_plan_id="plan-orphan",
            inventory_hash="c" * 64,
            ttl_ms=60_000,
            owner_pid=99999999,
            now_ms=FIXED_NOW_MS,
        )
        harness.worker._defer_for_maintenance(
            SimpleNamespace(action_id="act-maintenance-fence"),
            _dispatch(),
            "maintenance active",
        )

        assert calls
        assert calls[0]["retry_at_ms"] == FIXED_NOW_MS + 1000
        assert fence.read_fence("research-team", now_ms=FIXED_NOW_MS + 1000) is None
    finally:
        harness.close()
