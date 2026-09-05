"""Readiness must consume the same scoped facts as execution admission."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.web.services.team_workflow.research_runtime import (
    artifact_readback_registry as artifacts,
    budget_authority_adapter as budget,
    real_readiness_context as readiness,
    workflow_artifact_store as store,
)


@pytest.mark.parametrize("reverse", [False, True])
def test_stage_budget_is_independent_of_json_key_order(reverse):
    stages = [("knowledge_collection", {"tokens": 100}),
              ("experiment_design", {"tokens": 5000})]
    snapshot = {"budgetPolicy": {"stageBudgets": dict(reversed(stages) if reverse else stages)}}
    context = readiness.RealDomainReadinessContext(SimpleNamespace())
    with patch.object(context, "_input_snapshot", return_value=snapshot), \
         patch.object(context, "_run", return_value=None), \
         patch.object(readiness, "_budget_consumed_from_ledger", return_value={"tokens": 200}) as consumed:
        result = context.budget_limits("team", "run", node_id="protocol_design")
    assert result.stage_tokens_limit == budget._policy_limits(snapshot, "experiment_design")["tokens"]
    assert result.available() == (True, "")
    assert consumed.call_args.kwargs["stage_id"] == "experiment_design"


def test_readiness_does_not_accept_wrong_artifact_authority():
    row = {"kind": "protocol_draft", "workflowRunId": "current",
           "sourceCollectionRunId": "wrong", "payload": {"dataset": "d"}}
    with patch.object(store, "_path", return_value=Path("unused")), \
         patch.object(store, "_read", return_value=[row]):
        assert artifacts.load_scoped_artifact_payload("protocol_draft", team_id="team",
            authority_run_id="expected", workflow_run_id="current") is None
        assert readiness._artifact_payload("protocol_draft", "team", "current",
            authority_run_id="expected") is None


def test_missing_current_question_does_not_borrow_history():
    context = readiness.RealDomainReadinessContext(SimpleNamespace())
    snapshots = {"current": {"questionId": "Q"}, "old": {
        "questionId": "Q", "researchObjectiveContract": {"question": "old question"}}}
    with patch.object(readiness, "_run_ids_for", return_value=["current", "old"]), \
         patch.object(context, "_input_snapshot", side_effect=snapshots.get):
        assert context.question_snapshot("team", "Q", run_id="current") is None
        assert context.question_snapshot("team", "Q")["runId"] == "old"


def test_budget_consumption_and_extension_stay_in_their_stage(tmp_path):
    from tests.test_budget_calibration_contract import (
        CommandHarness, _insert_budget_receipt, _write_snapshot,
    )
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        snapshot = {"budgetPolicy": {"stageBudgets": {
            "knowledge_collection": {"tokens": 100},
            "experiment_design": {"tokens": 5000}}}}
        _write_snapshot(harness, snapshot["budgetPolicy"])
        _insert_budget_receipt(harness, receipt_id="old-stage", node_id="source_finding",
            node_run_id="nr-old", estimate=100, status="settled", usage={"totalTokens": 100})
        _insert_budget_receipt(harness, receipt_id="current-stage", node_id="protocol_design",
            node_run_id="nr-current", estimate=200)
        def update(uow):
            uow.repository.execute("UPDATE budget_receipts SET stage_id = ? WHERE receipt_id = ?",
                ("experiment_design", "current-stage"))
            uow.repository.execute("UPDATE workflow_runs SET safety_limits_json = ? WHERE run_id = ?",
                (json.dumps({"stageTokens": {"knowledge_collection": 9000}, "maxRetries": 7}), "run-test"))
        harness.store.submit(update, force_flush=True).result(timeout=10)
        context = readiness.RealDomainReadinessContext(harness.store)
        result = context.budget_limits("research-team", "run-test", node_id="protocol_design")
        assert result.stage_tokens_consumed == 200
        assert result.stage_tokens_limit == 5000
        assert result.auto_retries == 7
        assert result.available() == (True, "")
    finally:
        harness.close()
