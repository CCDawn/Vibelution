"""SCI-096: heal empty adapter runId and synthesize pending when lag-walk fails."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
    _heal_pending_action_identity,
)
from tests._support.graph_helpers import GraphHarness


def _pending(
    *,
    run_id: str = "",
    node_run_id: str = "nr--controlled_run-a2",
    node_id: str = "controlled_run",
    attempt: int = 2,
) -> PendingAction:
    return PendingAction(
        action_id="act-empty",
        run_id=run_id,
        node_run_id=node_run_id,
        node_id=node_id,
        attempt=attempt,
        actor_kind=ActorKind.SYSTEM,
        action_kind=f"system_action:{node_id}",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )


def test_heal_pending_action_identity_fills_empty_run_id() -> None:
    outbox = SimpleNamespace(
        run_id="run-317ed54cb838",
        node_run_id="nr-run-317ed54cb838-controlled_run-a2",
    )
    healed = _heal_pending_action_identity(outbox, _pending())
    assert healed.run_id == "run-317ed54cb838"
    assert healed.node_run_id == "nr-run-317ed54cb838-controlled_run-a2"


def test_heal_pending_action_identity_keeps_matching_ids() -> None:
    action = _pending(
        run_id="run-test",
        node_run_id="nr-run-test-controlled_run-a2",
    )
    outbox = SimpleNamespace(
        run_id="run-test",
        node_run_id="nr-run-test-controlled_run-a2",
    )
    healed = _heal_pending_action_identity(outbox, action)
    assert healed is action


def test_downstream_retry_synthesizes_pending_when_lag_walk_fails(
    tmp_path: Path, monkeypatch
) -> None:
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
        assert before.get("nextNodeIds")

        monkeypatch.setattr(
            harness.worker,
            "_advance_lagging_checkpoint",
            lambda *args, **kwargs: None,
        )
        harness.enqueue_graph_dispatch(
            "run-test",
            "controlled_run",
            4,
            command_id="cmd-retry-cr-heal",
        )
        harness.worker.run_once()

        controlled = harness.commands.store.latest_attempt(
            "run-test", "controlled_run"
        )
        assert controlled is not None
        assert controlled.status == "dispatching"
        assert "checkpoint_node_mismatch" not in (controlled.problem_json or "")
        adapter = harness.latest_adapter_pending()
        assert adapter is not None
        payload = json.loads(adapter.payload_json)
        assert payload["runId"] == "run-test"
        assert payload["nodeRunId"] == "nr-run-test-controlled_run-a4"
        assert payload["nodeId"] == "controlled_run"
        assert int(payload["attempt"]) == 4
    finally:
        harness.close()
