import json
from types import SimpleNamespace

from core.web.services.team_workflow.research_runtime.command_service import NodeNotReadyError
from core.web.services.team_workflow.research_runtime.readiness.knowledge_recheck import _refresh_knowledge_block
from tests.test_knowledge_readiness_gate import _harness, _isolated_registry
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, build_attempt_record, build_command_record


def test_absorbed_knowledge_refreshes_stale_block_without_dispatch(tmp_path):
    harness = _harness(tmp_path)
    store = harness.commands.store
    old = {"code": "auto_advance_not_ready", "detail": "knowledge_package_not_materialized; hypothesis_round_unconverged"}
    try:
        def seed(uow):
            uow.repository.insert_command(build_command_record(command_id="cmd-blocked", run_id="run-parent",
                node_id="hypothesis_design", idempotency_key="blocked"))
            uow.repository.insert_attempt(build_attempt_record(node_run_id="nr-blocked", run_id="run-parent",
                node_id="hypothesis_design", command_id="cmd-blocked", status="blocked", problem_json=json.dumps(old)))
            uow.repository.update_run_status("run-parent", "research-team", "blocked", FIXED_NOW_MS,
                active_node_id="hypothesis_design", blocked_problem_json=json.dumps(old))
        store.submit(seed, force_flush=True).result(timeout=10)
        parent = store.get_run("run-parent")
        exc = NodeNotReadyError(SimpleNamespace(blockers=[SimpleNamespace(code="hypothesis_round_unconverged")]), parent.run_version)
        before = store.read(lambda repo: (len(repo.list_attempts("run-parent")), repo.latest_event_sequence("run-parent")))
        _refresh_knowledge_block(store, parent, "hypothesis_design", "kinv-1", exc, FIXED_NOW_MS + 1)
        updated = store.get_run("run-parent")
        assert updated.status == "blocked"
        assert json.loads(updated.blocked_problem_json)["detail"] == "hypothesis_round_unconverged"
        assert json.loads(store.latest_attempt("run-parent", "hypothesis_design").problem_json)["detail"] == "hypothesis_round_unconverged"
        assert len(store.read(lambda repo: repo.list_attempts("run-parent"))) == before[0]
        _refresh_knowledge_block(store, parent, "hypothesis_design", "kinv-1", exc, FIXED_NOW_MS + 2)
        assert store.read(lambda repo: repo.latest_event_sequence("run-parent")) == before[1] + 1
    finally:
        harness.close()
