import json

from core.research.workflow.knowledge_sideflow_definition import build_knowledge_sideflow_workflow_definition
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def test_source_repair_moves_real_checkpoint_then_reenters_extraction(tmp_path):
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(workflow_definition=build_knowledge_sideflow_workflow_definition())
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        harness.worker.run_once()
        first = harness.latest_adapter_pending()
        assert first is not None
        harness.resume(run_id="run-test", node_id="source_finding", attempt=1,
                       action_id=json.loads(first.payload_json)["actionId"])
        harness.consume_adapter(first.action_id)
        harness.worker.run_once()
        extraction = harness.commands.store.latest_attempt("run-test", "source_extraction")
        assert extraction is not None
        pending_extraction = harness.latest_adapter_pending()
        assert pending_extraction is not None

        def block(uow):
            uow.repository.update_attempt_status(extraction.node_run_id, "blocked", FIXED_NOW_MS + 10)

        harness.commands.store.submit(block, force_flush=True).result(timeout=10)
        harness.enqueue_graph_dispatch("run-test", "source_finding", 2)
        harness.worker.run_once()
        snapshot = harness.coordinator.snapshot(
            "run-test", harness.commands.store.get_run("run-test").workflow_version_id,
        )
        assert snapshot["pendingAction"]["nodeId"] == "source_finding"
        assert snapshot["pendingAction"]["attempt"] == 2
        assert harness.commands.store.latest_attempt("run-test", "source_extraction").status == "stale"
        repair = harness.latest_adapter_pending()
        assert repair is not None
        assert json.loads(repair.payload_json)["nodeId"] == "source_finding"
        harness.resume(run_id="run-test", node_id="source_finding", attempt=2,
                       action_id=json.loads(repair.payload_json)["actionId"])
        harness.consume_adapter(repair.action_id)
        harness.worker.run_once()
        next_extraction = harness.commands.store.latest_attempt("run-test", "source_extraction")
        assert next_extraction.attempt == 2
        assert next_extraction.status == "dispatching"
        snapshot = harness.coordinator.snapshot(
            "run-test", harness.commands.store.get_run("run-test").workflow_version_id,
        )
        assert snapshot["pendingAction"]["nodeId"] == "source_extraction"
        assert snapshot["pendingAction"]["attempt"] == 2
    finally:
        harness.close()
