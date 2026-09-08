import json

from core.web.services.team_workflow.research_runtime.event_publish_worker import EventPublishWorker
from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import absorb_knowledge_result
from core.web.services.team_workflow.research_runtime.readiness.knowledge_recheck import build_knowledge_readiness_recheck
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS
from tests.test_knowledge_readiness_gate import _harness
from tests.test_knowledge_sideflow_run import _invoke, _walk_child_to_handoff, _accept_handoff, _outbox_rows


def test_redelivery_resumes_parent_after_absorb_before_recheck_crash(tmp_path):
    harness = _harness(tmp_path)
    try:
        store = harness.commands.store
        child_id = _invoke(harness)["childRunId"]
        pending = _walk_child_to_handoff(harness, child_id)
        _accept_handoff(harness, child_id, pending)
        payload = json.loads(_outbox_rows(harness, child_id, "event_publish")[0][2])
        now = FIXED_NOW_MS + 5000
        # Durable parent absorption survives the worker dying before recheck/ACK.
        assert absorb_knowledge_result(store, payload, now_provider=lambda: now)["status"] == "absorbed"
        assert store.latest_attempt("run-parent", "hypothesis_design") is None
        worker = EventPublishWorker(
            store=store, now_provider=lambda: now + 1,
            readiness_recheck=build_knowledge_readiness_recheck(
                store=store, command_service=harness.commands.command_service,
                readiness_invalidate=harness.commands.readiness.invalidate,
                now_provider=lambda: now + 1,
            ),
        )
        assert worker.run_once() == 1
        attempt = store.latest_attempt("run-parent", "hypothesis_design")
        assert attempt is not None
        assert attempt.status == "starting"
        assert len(_outbox_rows(harness, "run-parent", "graph_dispatch")) == 1
        assert worker.run_once() == 0
        assert len([e for e in store.list_events("run-parent") if e.event_type == "knowledge_result_absorbed"]) == 1
    finally:
        harness.close()
