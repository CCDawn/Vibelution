from dataclasses import replace

from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime import scientific_semantic_ledger as semantics
from core.web.services.team_workflow.research_runtime.action_registry import ActionRegistry
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import AdapterDispatchWorker
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import HumanActionAdapter
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS
from tests.test_research_workflow_adapter_idempotency import _action, _seed


def _human_worker(harness):
    action = replace(_action(), actor_kind=ActorKind.HUMAN, action_kind="human_task")
    _seed(harness, action)
    ports = FakeDomainPorts()
    registry = ActionRegistry()
    registry.register(HumanActionAdapter(ports))
    worker = AdapterDispatchWorker(
        store=harness.store, registry=registry, ports=ports,
        successor_fn=lambda _: ("source_extraction",),
        now_provider=lambda: FIXED_NOW_MS + 1000,
    )
    return worker, action


def test_human_wait_records_running_not_success_and_does_not_duplicate(tmp_path):
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run()
        worker, action = _human_worker(harness)
        worker.run_once()
        worker.run_once()
        assert harness.store.latest_attempt(action.run_id, action.node_id).status == "waiting_human"
        records = semantics.list_scientific_semantic_records(harness.store, action.run_id)
        assert len(records) == 1
        assert records[0]["subjectRef"] == action.node_run_id
        assert records[0]["semantic"]["execution"] == {
            "status": "running", "waitReason": "human_input",
        }
        assert not {"result", "assessment"}.intersection(records[0]["semantic"])
        assert records[0]["actor"]["agentType"] == "software_agent"
        assert records[0]["actor"]["associatedAgentRef"] == worker._owner
    finally:
        harness.close()


def test_human_wait_semantic_failure_rolls_back_task_anchor_and_attempt(tmp_path, monkeypatch):
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run()
        worker, action = _human_worker(harness)
        original = semantics.append_scientific_semantic_record_in_uow

        def write_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("human wait semantic crash")

        monkeypatch.setattr(semantics, "append_scientific_semantic_record_in_uow", write_then_fail)
        worker.run_once()
        assert semantics.list_scientific_semantic_records(harness.store, action.run_id) == []
        assert harness.store.latest_event_sequence(action.run_id) == 1
        assert harness.store.latest_attempt(action.run_id, action.node_id).status == "dispatching"
        assert harness.store.read(lambda repo: repo.get_anchor_by_node_run(action.node_run_id)) is None
        assert harness.store.read(lambda repo: repo.execute("SELECT COUNT(*) FROM human_tasks").fetchone()[0]) == 0
        assert harness.store.read(lambda repo: repo.get_handoff_by_from_node(action.run_id, action.node_run_id)) is None
    finally:
        harness.close()
