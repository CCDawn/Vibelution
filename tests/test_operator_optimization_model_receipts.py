import pytest

from core.llm.client import LLMClient, model_invocation_receipt_context_scope
from core.llm.errors import LLMError
from tests.test_llm_client import make_config
from tests.test_operator_optimization_discussion_contracts import binding
from core.web.services.team_workflow.research_runtime.model_invocation_receipt_registry import (
    validate_question_model_invocation_receipt,
)


def native_receipt(preflight=None, *, usage=None):
    def backend(_payload):
        return {"id": "test-response", "choices": [{"message": {"role": "assistant", "content": "test"},
            "finish_reason": "stop"}], "usage": usage or {"prompt_tokens": 13, "completion_tokens": 8, "total_tokens": 21}}

    client = LLMClient(config=make_config(), backend=backend)
    context = {"operatorInvocationBinding": binding().model_dump(mode="json"),
        "invocationBudgetPreflight": preflight or (lambda **kwargs: {"maxOutputTokens": 128, "remainingTokens": 1000}),
        "receiptRunAuthority": "workflow_run", "receiptRunId": "run1", "modelPolicySha256": "a" * 64,
        "expectedModelRoute": {"modelRef": "default/qwen-alias", "providerId": "default", "modelId": "qwen-plus"}}
    with model_invocation_receipt_context_scope(context):
        outcome = client.invoke_outcome([{"role": "user", "content": "test"}],
            metadata={"sessionId": "session1", "turnId": "chat-room:round1:participant1", "invocationId": "invocation1"})
    receipt = outcome.model_invocation_receipt
    assert receipt is not None
    return dict(receipt)


def test_operator_receipt_uses_native_llm_boundary_and_scoped_registry_validation():
    receipt = native_receipt()
    assert receipt["scope"]["workflowId"] == "operator-optimization"
    assert receipt["scope"]["researchProjectId"] == "project1"
    assert receipt["nodeRunId"] == "node1"
    assert tuple(receipt["metadata"]["outcomeKinds"]) == ("optimization_hypothesis",)
    assert receipt["tokenUsage"]["totalTokens"] == 21
    validated = validate_question_model_invocation_receipt(receipt, question_id="OPERATOR-SOFTMAX", workflow_run_id="run1")
    assert validated["scope"]["roundId"] == "round1"


@pytest.mark.parametrize("failure", ["missing_budget", "wrong_turn", "wrong_run", "wrong_model"])
def test_operator_invalid_admission_never_calls_provider(failure):
    calls = []
    client = LLMClient(config=make_config(), backend=lambda payload: calls.append(payload))
    context = {"operatorInvocationBinding": binding().model_dump(mode="json"),
        "receiptRunAuthority": "workflow_run", "receiptRunId": "run1", "modelPolicySha256": "a" * 64,
        "expectedModelRoute": {"modelRef": "default/qwen-alias", "providerId": "default", "modelId": "qwen-plus"}}
    if failure != "missing_budget":
        context["invocationBudgetPreflight"] = lambda **kwargs: {"maxOutputTokens": 128}
    if failure == "wrong_run":
        context["receiptRunId"] = "another-run"
    if failure == "wrong_model":
        context["expectedModelRoute"]["modelId"] = "another-model"
    with model_invocation_receipt_context_scope(context), pytest.raises(LLMError) as error:
        client.invoke([{"role": "user", "content": "test"}], metadata={
            "sessionId": "session1", "turnId": "wrong" if failure == "wrong_turn" else "chat-room:round1:participant1"})
    assert error.value.category == "budget_authority_error"
    assert calls == []


@pytest.mark.parametrize("stream", [False, True])
def test_operator_failed_retries_keep_admission_and_receipt_identity_equal(monkeypatch, stream):
    from core.llm.semantic_messages import InvocationScope
    monkeypatch.setattr("core.llm.client._sleep_with_llm_cancel_check", lambda _: None)
    admitted, receipts, calls = [], [], []
    def backend(payload):
        calls.append(payload)
        if len(calls) < 3:
            raise LLMError("server_error", "transient", retryable=True)
        if stream:
            return iter([{"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 13, "completion_tokens": 8, "total_tokens": 21}}])
        return {"id": "response", "choices": [{"message": {"role": "assistant", "content": "done"},
            "finish_reason": "stop"}], "usage": {"prompt_tokens": 13, "completion_tokens": 8, "total_tokens": 21}}
    client = LLMClient(config=make_config(**{"llm.profiles.primary.retry_policy.max_attempts": 3}), backend=backend)
    def preflight(**kwargs):
        admitted.append(kwargs["invocation_id"])
        return {"maxOutputTokens": 128, "remainingTokens": 1000}
    context = {"operatorInvocationBinding": binding().model_dump(mode="json"),
        "invocationBudgetPreflight": preflight, "operatorInvocationReceiptCallback": receipts.append,
        "receiptRunAuthority": "workflow_run", "receiptRunId": "run1", "modelPolicySha256": "a" * 64,
        "expectedModelRoute": {"modelRef": "default/qwen-alias", "providerId": "default", "modelId": "qwen-plus"}}
    with model_invocation_receipt_context_scope(context):
        metadata = {"sessionId": "session1", "turnId": "chat-room:round1:participant1", "invocationId": "invocation1"}
        if stream:
            captured = []
            monkeypatch.setattr(client, "_record_canonical_outcome", lambda outcome, **_: captured.append(outcome))
            list(client.stream_events([{"role": "user", "content": "test"}], metadata=metadata))
            outcome = captured[-1]
        else:
            outcome = client.invoke_outcome([{"role": "user", "content": "test"}], metadata=metadata)
    receipts.append(dict(outcome.model_invocation_receipt))
    assert admitted == ["invocation1", "invocation1:attempt-2", "invocation1:attempt-3"]
    assert [r["evidenceLocator"]["invocationId"] for r in receipts] == admitted
    assert [r["status"] for r in receipts] == ["failed", "failed", "retried"]
    assert not receipts[0]["metadata"]["usageKnown"]
    ordinary = InvocationScope(session_id="s", turn_id="t", invocation_id="i", iteration=0)
    assert client._attempt_invocation_scope(ordinary, 2) is ordinary
