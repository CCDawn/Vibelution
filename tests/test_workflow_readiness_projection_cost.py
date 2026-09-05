"""Read projections must not repeat domain scans or enter the writer queue."""

from unittest.mock import Mock

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.web.services.team_workflow.research_runtime.command_offers import build_command_offers
from core.web.services.team_workflow.research_runtime import readiness_providers
from tests._support.command_helpers import CommandHarness


def test_offer_batch_reads_revision_once_and_next_batch_observes_changes(tmp_path, monkeypatch):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        run = harness.store.get_run("run-test")
        revision = Mock(return_value={"source_collection": "first"})
        monkeypatch.setattr(harness.context, "domain_revision_vector", revision)
        results = []
        original = harness.readiness.evaluate

        def evaluate(**kwargs):
            result = original(**kwargs)
            results.append(result)
            return result

        monkeypatch.setattr(harness.readiness, "evaluate", evaluate)
        options = dict(readiness_service=harness.readiness, context=harness.context,
                       team_id=run.team_id, run=run,
                       definition=build_challenge_cup_workflow_definition())
        build_command_offers(**options)
        assert len(results) > 1
        assert revision.call_count == 1
        assert all(item.domain_revision_vector == revision.return_value for item in results)
        results.clear()
        revision.return_value = {"source_collection": "second"}
        build_command_offers(**options)
        assert revision.call_count == 2
        assert all(item.domain_revision_vector == revision.return_value for item in results)
        # Executing a command still uses the original, fresh authority context.
        assert harness.context.domain_revision_vector(run.team_id, run.run_id) == revision.return_value
        assert revision.call_count == 3
    finally:
        harness.close()


def test_revision_receipt_queries_do_not_use_writer_queue(tmp_path, monkeypatch):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        writer = Mock(side_effect=AssertionError("read entered writer queue"))
        monkeypatch.setattr(harness.store, "submit", writer)
        vector = readiness_providers.build_domain_revision_vector(
            "research-team", "run-test", ledger_store=harness.store,
        )
        assert "budget_receipts" in vector
        writer.assert_not_called()
    finally:
        harness.close()
