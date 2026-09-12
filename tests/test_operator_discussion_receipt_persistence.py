from dataclasses import replace
import json
import pytest

from core.research.operator_optimization.model_budget_contracts import OperatorDiscussionBudget
from core.web.services.team_workflow.operator_optimization.model_budget import reserve_model_budget
from core.web.services.team_workflow.research_runtime.receipt_persistence import enqueue_question_model_invocation_receipt
from tests._support.workflow_ledger_helpers import (
    open_ledger_store, build_run_record, build_command_record, build_attempt_record,
)
from tests.test_operator_optimization_model_receipts import native_receipt


@pytest.mark.parametrize("usage", [{"prompt_tokens": 13, "completion_tokens": 8, "total_tokens": 21},
    {"prompt_tokens": 1300, "completion_tokens": 800, "total_tokens": 2100}])
def test_native_receipt_cost_and_delivery_commit_once_in_same_ledger(tmp_path, monkeypatch, usage):
    store = open_ledger_store(tmp_path / "ledger.sqlite")
    try:
        def seed(u):
            u.repository.insert_run(replace(build_run_record(run_id="run1"), team_id="team1",
                project_id="project1", question_id="OPERATOR-SOFTMAX", workflow_id="operator-optimization"))
            u.repository.insert_command(build_command_record(command_id="cmd1", run_id="run1"))
            u.repository.insert_attempt(build_attempt_record("node1", run_id="run1",
                node_id="optimization_discussion", command_id="cmd1", status="running"))
        store.submit(seed, force_flush=True).result()
        budget = OperatorDiscussionBudget(tokenLimit=1000, maxOutputTokensPerCall=100, maxCalls=2,
            prices=[dict(modelRef="default/qwen-alias", priceVersion="v1", currency="CNY",
                inputPerMillion=1, outputPerMillion=2)])
        reserve_model_budget(store, run_id="run1", node_run_id="node1", optimization_campaign_id="campaign1",
            round_id="round1", discussion_budget=budget, model_cost_limit=1, campaign_currency="CNY",
            policy_hash="a" * 64)
        from core.web.services.team_workflow.operator_optimization import discussion_authority
        from core.web.services.team_workflow.operator_optimization.discussion_budget_runtime import speaker_budget_preflight
        from core.web.services.team_workflow.research_runtime import formal_write_runtime
        monkeypatch.setattr(formal_write_runtime, "get_write_store", lambda: store)
        monkeypatch.setattr(discussion_authority, "validate_operator_authority", lambda value: value)
        authority = {"workflowRunId": "run1", "nodeRunId": "node1", "budget": {"discussion": budget.model_dump(mode="json")}}
        receipt = native_receipt(speaker_budget_preflight(authority, "default/qwen-alias"), usage=usage)
        args = dict(team_id="team1", question_id="OPERATOR-SOFTMAX", workflow_run_id="run1", receipt=receipt)
        first = enqueue_question_model_invocation_receipt(store, **args)
        second = enqueue_question_model_invocation_receipt(store, **args)
        assert first["created"] and not second["created"]
        row = store.submit(lambda u: u.repository.execute(
            "SELECT settled_json FROM budget_receipts WHERE reservation_id='reservation-node1'").fetchone()).result()
        projection = json.loads(row[0])["operatorModelBudget"]
        assert projection["callsUsed"] == 1
        assert projection["tokensUsed"] == usage["total_tokens"]
        assert float(projection["actualAmount"]) == (usage["prompt_tokens"] + 2 * usage["completion_tokens"]) / 1000000
        if usage["total_tokens"] > budget.tokenLimit:
            from core.web.services.team_workflow.operator_optimization.model_budget import ModelBudgetError
            with pytest.raises(ModelBudgetError, match="token limit"):
                speaker_budget_preflight(authority, "default/qwen-alias")(
                    invocation_id="next-call", estimated_input_tokens=10, max_output_tokens=20)
        from core.web.services.team_workflow.operator_optimization.model_budget import settle_model_budget
        settled = settle_model_budget(store, reservation={"reservationId": "reservation-node1"})
        assert settled["status"] == "settled"
        assert not enqueue_question_model_invocation_receipt(store, **args)["created"]
    finally:
        store.close()
