from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
import inspect
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from core.llm.agent_runtime import config_for_agent_llm_model
from core.orchestration.response_processor import ResponseProcessor
from core.llm.client import (
    LLMClient,
    _cancellable_client_cache_key,
    _configure_litellm_import_environment,
    _default_completion_backend,
    _default_responses_backend,
    _llm_provider_proxy_env,
    _ensure_no_proxy_for_local_base_url,
    _new_cancellable_completion_http_handler,
    _new_cancellable_responses_http_handler,
    _resolve_llm_route_concurrency_limit,
    _retry_policy_backoff_seconds,
    _retry_policy_max_attempts,
    _safe_prompt_cache_payload_summary,
    _safe_responses_continuation_summary,
    llm_cancel_context,
    model_invocation_receipt_context_scope,
)
from core.llm.errors import classify_exception
from core.llm.provider_replay_state import OpaqueReplayItem, ProviderReplayState, endpoint_fingerprint
from core.llm.semantic_messages import InvocationScope, SemanticOutputSchema
from core.llm.types import CanonicalItemIdentity, CanonicalToolCall, LLMError, TurnOutcome
from core.llm.wire.responses import ResponsesWireAdapter
from core.llm.recovery import plan_recovery
from core.llm.routing import attach_recovery_fallback, select_recovery_profile
from tests.helpers.isolated_config import isolated_settings_config


def make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.contract", "tool_chat")
    kwargs.setdefault("llm.profiles.primary.streaming", True)
    kwargs.setdefault("llm.profiles.primary.tool_calling_mode", "auto")
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    return isolated_settings_config(**kwargs)


def test_litellm_cost_map_defaults_to_local_without_overriding_operator_env(monkeypatch) -> None:
    monkeypatch.delenv("LITELLM_LOCAL_MODEL_COST_MAP", raising=False)

    _configure_litellm_import_environment()

    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"

    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "False")
    _configure_litellm_import_environment()

    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "False"


def test_strict_output_fails_before_provider_when_capability_is_missing():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "chat-model",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)
    client.capabilities.supports_strict_json_schema = False

    with pytest.raises(LLMError, match="does not support strict JSON Schema") as exc_info:
        client._build_payload(
            [{"role": "user", "content": "review"}],
            output_schema=SemanticOutputSchema(
                name="research_protocol_review_v1",
                schema={"type": "object"},
            ),
        )

    assert exc_info.value.details["payloadValidationResult"] == "blocked_before_provider"


def test_strict_output_reaches_supported_provider_payload():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "chat-model",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)
    client.capabilities.supports_strict_json_schema = True
    schema = {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}},
        "required": ["reasoning"],
        "additionalProperties": False,
    }

    payload = client._build_payload(
        [{"role": "user", "content": "review"}],
        output_schema=SemanticOutputSchema(
            name="research_protocol_review_v1",
            schema=schema,
        ),
    )

    assert payload["response_format"]["json_schema"] == {
        "name": "research_protocol_review_v1",
        "strict": True,
        "schema": schema,
    }
    assert client._last_payload_protocol_summary["structuredOutput"] is True
    assert client._last_payload_protocol_summary["outputSchemaName"] == (
        "research_protocol_review_v1"
    )
    assert len(client._last_payload_protocol_summary["outputSchemaSha256"]) == 64


def test_compression_role_disables_provider_retry_amplification() -> None:
    profile = SimpleNamespace(retry_policy=SimpleNamespace(max_attempts=5))

    assert _retry_policy_max_attempts(profile) == 5
    assert _retry_policy_max_attempts(profile, role="compression") == 1


def test_connection_category_backoff_is_capped_short() -> None:
    profile = SimpleNamespace(retry_policy=SimpleNamespace(backoff_base_seconds=2.0))

    for category in ("network_error", "timeout", "server_error"):
        assert _retry_policy_backoff_seconds(profile, 1, category=category) == 2.0
        assert _retry_policy_backoff_seconds(profile, 2, category=category) == 3.0
        assert _retry_policy_backoff_seconds(profile, 3, category=category) == 3.0
        assert _retry_policy_backoff_seconds(profile, 4, category=category) == 3.0


def test_other_categories_keep_exponential_backoff() -> None:
    profile = SimpleNamespace(retry_policy=SimpleNamespace(backoff_base_seconds=2.0))

    assert _retry_policy_backoff_seconds(profile, 1, category="rate_limit") == 2.0
    assert _retry_policy_backoff_seconds(profile, 2, category="rate_limit") == 4.0
    assert _retry_policy_backoff_seconds(profile, 3, category="rate_limit") == 8.0
    assert _retry_policy_backoff_seconds(profile, 4, category="") == 16.0


def test_responses_continuation_summary_uses_websocket_delta_without_exposing_id() -> None:
    summary = _safe_responses_continuation_summary(
        {
            "model": "openai/gpt-test",
            "input": [
                {"role": "assistant", "content": [{"type": "output_text", "text": "full"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "full"}]},
            ],
            "_vibelution_responses_websocket": {
                "enabled": True,
                "previous_response_id": "resp-secret",
                "input": [
                    {"type": "function_call_output", "call_id": "call-1", "output": "bounded"},
                    {"role": "user", "content": [{"type": "input_text", "text": "delta"}]},
                ],
            },
        }
    )

    assert summary == {
        "previousResponseIdPresent": True,
        "continuationMode": "stateful_previous_response_id",
        "responseInputItemCount": 2,
        "functionCallOutputCount": 1,
    }
    assert "resp-secret" not in str(summary)


def test_responses_continuation_summary_classifies_stateless_replay() -> None:
    summary = _safe_responses_continuation_summary(
        {
            "model": "openai/gpt-test",
            "input": [
                {"role": "assistant", "content": [{"type": "output_text", "text": "prior"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "next"}]},
            ],
        }
    )

    assert summary["previousResponseIdPresent"] is False
    assert summary["continuationMode"] == "stateless_replay"
    assert summary["responseInputItemCount"] == 2
    assert summary["functionCallOutputCount"] == 0


def test_stream_receipt_uses_bounded_canonical_summary_without_provider_capture():
    source = inspect.getsource(LLMClient._stream_attempt)
    assert "provider_response_capture" not in source
    assert "receipt_builder" in source

    receipt_context = {
        "questionStageBinding": {
            "questionStage": "generation",
            "questionId": "SCI-001",
            "questionRunId": "question-run-1",
            "workflowRunId": "workflow-run-1",
            "workflowId": "workflow-1",
            "workflowVersionId": "version-1",
            "formalNodeId": "node-1",
            "formalNodeRunId": "node-run-1",
            "formalNodeAttempt": 1,
            "sessionId": "session-1",
            "taskId": "task-1",
            "turnId": "turn-2",
        },
        "receiptRunAuthority": "question_run",
        "receiptRunId": "question-run-1",
        "modelPolicySha256": "a" * 64,
        "expectedModelRoute": {
            "modelRef": "default/qwen-alias",
            "providerId": "default",
            "modelId": "qwen-plus",
        },
        "outcomeKinds": ["candidate"],
        "outputRef": "artifact://output-1",
    }

    metadata_without_authority = {
        "sessionId": "session-1",
        "turnId": "turn-2",
        "invocationId": "invocation-3",
        "iteration": 0,
    }

    def backend(_payload):
        for index in range(1024):
            yield {
                "id": f"chat-{index}",
                "providerSecret": "provider-secret-must-not-be-captured",
                "choices": [{"delta": {"content": "answer "}}],
            }
        yield {
            "id": "chat-final",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 13,
                "completion_tokens": 8,
                "total_tokens": 21,
                "completion_tokens_details": {"reasoning_tokens": 5},
            },
        }

    client = LLMClient(config=make_config(), backend=backend)
    with model_invocation_receipt_context_scope(receipt_context):
        streamed = list(
            client.stream(
                [{"role": "user", "content": "ping"}],
                metadata=metadata_without_authority,
            )
        )
    outcome = next(
        chunk.additional_kwargs["turn_outcome"]
        for chunk in reversed(streamed)
        if "turn_outcome" in chunk.additional_kwargs
    )

    receipt = outcome.model_invocation_receipt
    assert isinstance(receipt, dict)
    assert "providerEvents" not in receipt["responseExcerpt"]
    assert "provider-secret" not in receipt["responseExcerpt"]
    assert "finalText" in receipt["responseExcerpt"]
    assert len(receipt["responseExcerpt"]) <= 259
    assert receipt["tokenUsage"] == {
        "inputTokens": 13,
        "outputTokens": 8,
        "totalTokens": 21,
        "cachedInputTokens": 0,
        "reasoningTokens": 5,
    }
    assert receipt["receiptId"].endswith("-attempt-1")
    assert receipt["evidenceLocator"]["attempt"] == 1
    assert receipt["evidenceLocator"]["modelPolicySha256"] == "a" * 64


def test_non_stream_receipt_uses_provider_usage_and_server_binding(monkeypatch):
    receipt_context = {
        "receiptRunAuthority": "workflow_run",
        "receiptRunId": "workflow-run-1",
        "modelPolicySha256": "a" * 64,
        "expectedModelRoute": {
            "modelRef": "default/qwen-alias",
            "providerId": "default",
            "modelId": "qwen-plus",
        },
        "questionInvocationBinding": {
            "questionId": "SCI-001",
            "questionRunId": "workflow-run-1",
            "workflowRunId": "workflow-run-1",
            "workflowId": "workflow-1",
            "workflowVersionId": "version-1",
            "formalNodeId": "hypothesis_design",
            "formalNodeRunId": "node-run-1",
            "formalNodeAttempt": 1,
            "sessionId": "session-1",
            "taskId": "task-1",
            "turnId": "turn-1",
            "outcomeKinds": ["candidate"],
        },
    }

    def backend(_payload):
        return {
            "choices": [
                {"message": {"role": "assistant", "content": "candidate"}}
            ],
            "usage": {
                "prompt_tokens": 7,
                "completion_tokens": 3,
                "total_tokens": 10,
            },
        }

    captured = []
    client = LLMClient(config=make_config(), backend=backend)
    monkeypatch.setattr(
        client,
        "_record_canonical_outcome",
        lambda outcome, **_kwargs: captured.append(outcome),
    )
    with model_invocation_receipt_context_scope(receipt_context):
        client.invoke(
            [{"role": "user", "content": "propose"}],
            metadata={
                "sessionId": "session-1",
                "turnId": "turn-1",
                "invocationId": "invocation-1",
            },
        )

    receipt = captured[-1].model_invocation_receipt
    assert receipt["scope"]["workflowRunId"] == "workflow-run-1"
    assert list(receipt["metadata"]["outcomeKinds"]) == ["candidate"]
    assert receipt["tokenUsage"] == {
        "inputTokens": 7,
        "outputTokens": 3,
        "totalTokens": 10,
        "cachedInputTokens": 0,
        "reasoningTokens": 0,
    }
    assert receipt["receiptId"] == "model-receipt-invocation-1-0-attempt-1"
    assert receipt["evidenceLocator"]["attempt"] == 1
    assert receipt["provider"] == "default"
    assert receipt["model"] == "qwen-plus"
    assert receipt["evidenceLocator"]["outputRef"] == (
        "challenge-receipt://SCI-001/workflow-run-1/task-1/turn-1"
    )


def _budgeted_receipt_context(callback):
    return {
        "receiptRunAuthority": "workflow_run",
        "receiptRunId": "workflow-run-1",
        "modelPolicySha256": "a" * 64,
        "expectedModelRoute": {
            "modelRef": "default/qwen-alias",
            "providerId": "default",
            "modelId": "qwen-plus",
        },
        "questionInvocationBinding": {
            "questionId": "SCI-001",
            "questionRunId": "workflow-run-1",
            "workflowRunId": "workflow-run-1",
            "workflowId": "workflow-1",
            "workflowVersionId": "version-1",
            "formalNodeId": "hypothesis_design",
            "formalNodeRunId": "node-run-1",
            "formalNodeAttempt": 1,
            "sessionId": "session-1",
            "taskId": "task-1",
            "turnId": "turn-1",
            "outcomeKinds": ["candidate"],
        },
        "invocationBudgetPreflight": callback,
    }


@pytest.mark.parametrize(
    ("transport", "output_key"),
    [("chat_completions", "max_tokens"), ("responses", "max_output_tokens")],
)
def test_challenge_budget_clamps_each_wire_payload_before_provider(
    transport, output_key
):
    observed = []
    allowed_outputs = [123, 45]

    def preflight(**kwargs):
        observed.append(kwargs)
        return {
            "remainingTokens": 700,
            "maxOutputTokens": allowed_outputs[len(observed) - 1],
        }

    settings = {
        "llm.profiles.primary.transport": transport,
        "llm.profiles.primary.max_output_tokens": 1000,
    }
    if transport == "responses":
        settings.update(
            {
                "llm.providers.default.kind": "relay",
                "llm.providers.default.api_key": "test-key",
                "llm.providers.default.base_url": "https://relay.example.test/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.profiles.primary.provider_id": "default",
                "llm.profiles.primary.model": "qwen-plus",
            }
        )
    config = make_config(**settings)
    client = LLMClient(config=config, backend=lambda payload: payload)
    scope = InvocationScope(
        session_id="session-1",
        turn_id="turn-1",
        invocation_id="invocation-1",
        iteration=0,
    )
    with model_invocation_receipt_context_scope(
        _budgeted_receipt_context(preflight)
    ):
        first_payload = client._build_payload(
            [{"role": "user", "content": "propose"}],
            invocation_scope=scope,
        )
        second_payload = client._build_payload(
            [{"role": "user", "content": "propose"}],
            invocation_scope=scope,
        )

    assert first_payload[output_key] == 123
    assert second_payload[output_key] == 45
    assert len(observed) == 2
    assert observed[0]["max_output_tokens"] == 1000
    assert observed[0]["estimated_input_tokens"] > 0


def test_challenge_budget_exhaustion_blocks_before_provider_call():
    provider_calls = []

    def backend(payload):
        provider_calls.append(payload)
        raise AssertionError("provider must not be called")

    client = LLMClient(config=make_config(), backend=backend)
    with model_invocation_receipt_context_scope(
        _budgeted_receipt_context(
            lambda **_kwargs: {"remainingTokens": 0, "maxOutputTokens": 0}
        )
    ), pytest.raises(LLMError) as exc_info:
        client.invoke(
            [{"role": "user", "content": "propose"}],
            metadata={
                "sessionId": "session-1",
                "turnId": "turn-1",
                "invocationId": "invocation-1",
            },
        )

    assert exc_info.value.category == "budget_exhausted"
    assert exc_info.value.retryable is False
    assert provider_calls == []


def test_ordinary_chat_payload_keeps_profile_output_limit_without_budget_callback():
    config = make_config(
        **{"llm.profiles.primary.max_output_tokens": 777}
    )
    client = LLMClient(config=config, backend=lambda payload: payload)

    payload = client._build_payload([{"role": "user", "content": "hello"}])

    assert payload["max_tokens"] == 777


def test_receipt_identity_changes_for_provider_attempts() -> None:
    receipt_context = {
        "receiptRunAuthority": "workflow_run",
        "receiptRunId": "workflow-run-1",
        "modelPolicySha256": "a" * 64,
        "expectedModelRoute": {
            "modelRef": "default/qwen-alias",
            "providerId": "default",
            "modelId": "qwen-plus",
        },
        "questionInvocationBinding": {
            "questionId": "SCI-001",
            "questionRunId": "workflow-run-1",
            "workflowRunId": "workflow-run-1",
            "workflowId": "workflow-1",
            "workflowVersionId": "version-1",
            "formalNodeId": "hypothesis_design",
            "formalNodeRunId": "node-run-1",
            "formalNodeAttempt": 1,
            "sessionId": "session-1",
            "taskId": "task-1",
            "turnId": "turn-1",
            "outcomeKinds": ["candidate"],
        },
    }
    client = LLMClient(config=make_config(), backend=lambda _payload: {})
    outcome = TurnOutcome.final_answer(
        identity=CanonicalItemIdentity(
            session_id="session-1",
            turn_id="turn-1",
            invocation_id="invocation-1",
            iteration=0,
            item_id="item-1",
        ),
        text="candidate",
    )

    with model_invocation_receipt_context_scope(receipt_context):
        first = client._attach_model_invocation_receipt(
            outcome,
            metadata=None,
            invocation_scope=outcome.identity,
            request_content={"attempt": 1, "model": "qwen-plus"},
            response_content={"attempt": 1},
            started_at_ms=100,
            finished_at_ms=120,
            attempt=1,
            retry_count=0,
        )
        second = client._attach_model_invocation_receipt(
            outcome,
            metadata=None,
            invocation_scope=outcome.identity,
            request_content={"attempt": 2, "model": "qwen-plus"},
            response_content={"attempt": 2},
            started_at_ms=100,
            finished_at_ms=120,
            attempt=2,
            retry_count=1,
        )

    first_receipt = first.model_invocation_receipt
    second_receipt = second.model_invocation_receipt
    assert first_receipt["receiptId"] != second_receipt["receiptId"]
    assert first_receipt["evidenceLocator"]["attempt"] == 1
    assert second_receipt["evidenceLocator"]["attempt"] == 2


def test_client_message_metadata_cannot_mint_model_invocation_receipt() -> None:
    client = LLMClient(config=make_config(), backend=lambda _payload: [])
    scope = SimpleNamespace(session_id="session-1", turn_id="turn-2")
    assert (
        client._receipt_context(
            {"modelInvocationReceiptContext": {"receiptRunAuthority": "question_run"}},
            scope,
        )
        is None
    )


def _receipt_binding_outcome() -> tuple[TurnOutcome, dict]:
    outcome = TurnOutcome.final_answer(
        identity=CanonicalItemIdentity(
            session_id="session-1",
            turn_id="turn-1",
            invocation_id="invocation-1",
            iteration=0,
            item_id="item-1",
        ),
        text="review verdict",
    )
    binding = {
        "questionId": "SCI-001",
        "questionRunId": "workflow-run-1",
        "workflowRunId": "workflow-run-1",
        "workflowId": "workflow-1",
        "workflowVersionId": "version-1",
        "formalNodeId": "hypothesis_design",
        "formalNodeRunId": "node-run-1",
        "formalNodeAttempt": 1,
        "sessionId": "session-1",
        "taskId": "task-1",
        "turnId": "turn-1",
        "outcomeKinds": ["review"],
    }
    return outcome, binding


def test_receipt_attaches_with_redacted_request_summary() -> None:
    # The persisted request summary carries only bounded shape metadata, so
    # the route check must resolve the actual model from the client profile;
    # the redacted summary itself never names the model.
    outcome, binding = _receipt_binding_outcome()
    receipt_context = {
        "receiptRunAuthority": "workflow_run",
        "receiptRunId": "workflow-run-1",
        "modelPolicySha256": "a" * 64,
        "expectedModelRoute": {
            "modelRef": "default/qwen-alias",
            "providerId": "default",
            "modelId": "qwen-plus",
        },
        "questionInvocationBinding": binding,
    }
    client = LLMClient(config=make_config(), backend=lambda _payload: {})

    with model_invocation_receipt_context_scope(receipt_context):
        attached = client._attach_model_invocation_receipt(
            outcome,
            metadata=None,
            invocation_scope=outcome.identity,
            request_content={
                "conversationSha256": "b" * 64,
                "messageCount": 1,
                "payloadShape": {"messageRoles": {"user": 1}},
            },
            response_content={"finalText": "review verdict"},
            started_at_ms=100,
            finished_at_ms=120,
            attempt=1,
            retry_count=0,
        )

    receipt = attached.model_invocation_receipt
    assert isinstance(receipt, dict)
    assert receipt["receiptId"]
    assert receipt["model"] == "qwen-plus"


def test_receipt_still_fails_closed_when_profile_route_differs() -> None:
    outcome, binding = _receipt_binding_outcome()
    receipt_context = {
        "receiptRunAuthority": "workflow_run",
        "receiptRunId": "workflow-run-1",
        "modelPolicySha256": "a" * 64,
        "expectedModelRoute": {
            "modelRef": "default/qwen-alias",
            "providerId": "default",
            "modelId": "qwen-max",
        },
        "questionInvocationBinding": binding,
    }
    client = LLMClient(config=make_config(), backend=lambda _payload: {})

    with model_invocation_receipt_context_scope(receipt_context):
        attached = client._attach_model_invocation_receipt(
            outcome,
            metadata=None,
            invocation_scope=outcome.identity,
            request_content={"conversationSha256": "b" * 64, "messageCount": 1},
            response_content={"finalText": "review verdict"},
            started_at_ms=100,
            finished_at_ms=120,
            attempt=1,
            retry_count=0,
        )

    assert attached.model_invocation_receipt is None


def test_prompt_cache_payload_summary_fingerprints_messages_and_tool_schema_without_content() -> None:
    payload = {
        "messages": [
            {"role": "system", "content": "secret-system"},
            {"role": "user", "content": "secret-user"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "secret-tool-description",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    }

    baseline = _safe_prompt_cache_payload_summary(payload)
    message_changed = _safe_prompt_cache_payload_summary(
        {
            **payload,
            "messages": [
                {"role": "system", "content": "secret-system"},
                {"role": "user", "content": "changed-user"},
            ],
        }
    )
    tool_changed = _safe_prompt_cache_payload_summary(
        {
            **payload,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "changed-description",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        }
    )

    assert baseline["promptCacheMessageHash"]
    assert baseline["promptCacheMessageChunkHashes"]
    assert baseline["promptCacheToolSchemaHash"]
    assert baseline["promptCacheMessageHash"] != message_changed["promptCacheMessageHash"]
    assert baseline["promptCacheToolSchemaHash"] == message_changed["promptCacheToolSchemaHash"]
    assert baseline["promptCacheMessageHash"] == tool_changed["promptCacheMessageHash"]
    assert baseline["promptCacheToolSchemaHash"] != tool_changed["promptCacheToolSchemaHash"]
    serialized = json.dumps(baseline, ensure_ascii=False)
    assert "secret-system" not in serialized
    assert "secret-user" not in serialized
    assert "secret-tool-description" not in serialized


def supported_relay_chat_config():
    return make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
            "llm.profiles.primary.transport": "chat_completions",
            "llm.profiles.primary.prompt_cache.mode": "explicit_cache_control",
        }
    )


def test_litellm_payload_prefixes_minimax_model():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "minimax/MiniMax-M2.7"


def test_minimax_payload_converts_runtime_system_messages_after_first_to_user():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {"role": "system", "content": "system prompt"},
            {"role": "system", "content": "## 外部任务输入\n开始自主进化"},
        ]
    )

    assert [item["role"] for item in payload["messages"]] == ["system", "user"]


def test_litellm_payload_prefixes_openai_compatible_local_model():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.prompt_cache.mode": "disabled",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/qwen-32b-awq"


def test_local_lan_base_url_is_added_to_no_proxy(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost")

    _ensure_no_proxy_for_local_base_url("http://192.168.20.63:8000/v1")

    combined_no_proxy = ",".join(filter(None, [os.environ.get("NO_PROXY", ""), os.environ.get("no_proxy", "")]))
    assert "192.168.20.63" in combined_no_proxy.split(",")


def test_default_completion_backend_passes_service_root_to_litellm(monkeypatch):
    captured = {}

    def fake_completion(**payload):
        captured.update(payload)
        return {"ok": True}

    monkeypatch.setattr("litellm.completion", fake_completion)
    payload = {
        "model": "openai/qwen-local",
        "messages": [{"role": "user", "content": "ping"}],
        "base_url": "http://192.168.20.115:8080/v1/chat/completions",
        "api_key": "test-key",
    }

    assert _default_completion_backend(payload) == {"ok": True}
    assert captured["base_url"] == "http://192.168.20.115:8080/v1"
    assert payload["base_url"] == "http://192.168.20.115:8080/v1/chat/completions"


def test_remote_base_url_does_not_change_no_proxy(monkeypatch):
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("NO_PROXY", "localhost")

    _ensure_no_proxy_for_local_base_url("https://api.openai.com/v1")

    combined_no_proxy = ",".join(filter(None, [os.environ.get("NO_PROXY", ""), os.environ.get("no_proxy", "")]))
    assert set(combined_no_proxy.split(",")) == {"localhost"}


def test_litellm_payload_prefixes_relay_openai_compatible_model():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/gpt-5.5"


def test_openai_responses_gpt_payload_includes_reasoning_effort():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.reasoning_effort": "high",
            "llm.profiles.primary.reasoning_effort_values": ["low", "medium", "high"],
            "llm.profiles.primary.reasoning_effort_adapter": "reasoning_object",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/gpt-5.5"
    assert payload["reasoning"] == {"effort": "high"}


def test_strict_blank_responses_payload_preserves_empty_user_item():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-luna",
            "llm.profiles.primary.transport": "responses",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)

    ordinary_payload = client._build_payload([{"role": "user", "content": ""}])
    strict_blank_payload = client._build_payload(
        [{"role": "user", "content": ""}],
        metadata={"strictPromptPayload": True, "inputMode": "blank"},
    )

    assert ordinary_payload["input"] == []
    assert strict_blank_payload["input"] == [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": ""}],
        }
    ]


def test_strict_blank_chat_completions_payload_preserves_empty_user_message():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "http://192.168.20.66:8080/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
            "llm.profiles.primary.transport": "chat_completions",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)

    ordinary_payload = client._build_payload([{"role": "user", "content": ""}])
    strict_blank_payload = client._build_payload(
        [{"role": "user", "content": ""}],
        metadata={"strictPromptPayload": True, "inputMode": "blank"},
    )
    strict_continuation_payload = client._build_payload(
        [
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": ""},
        ],
        metadata={"strictPromptPayload": True, "inputMode": "blank"},
    )

    assert ordinary_payload["messages"] == []
    assert strict_blank_payload["messages"] == [{"role": "user", "content": ""}]
    assert strict_continuation_payload["messages"] == [
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": ""},
    ]


def test_openai_chat_gpt_payload_omits_reasoning_effort():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "chat_completions",
            "llm.profiles.primary.reasoning_effort": "high",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert "reasoning" not in payload


def test_llm_capabilities_expose_provider_runtime_features():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-4o",
            "llm.profiles.primary.contract": "tool_chat",
            "llm.profiles.primary.streaming": True,
            "llm.profiles.primary.tool_calling_mode": "auto",
            "llm.profiles.primary.supports_image_input": True,
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )
    config.llm.profiles["primary"].transport = "responses"

    client = LLMClient(config=config, backend=lambda payload: payload)

    assert client.capabilities.supports_image_input is True
    assert client.capabilities.supports_prompt_cache is True
    assert client.capabilities.supports_stream_usage is True
    assert client.capabilities.supports_explicit_tool_choice is True
    assert client.capabilities.supports_responses_transport is True


def test_llm_capabilities_apply_model_library_declared_capabilities():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "declared-capability-model",
        }
    )
    profile = config.llm.get_profile("primary")
    config.llm.model_library = {
        "declared-capability-model": {
            "provider_id": profile.provider_id,
            "model": profile.model,
            "capabilities": {
                "imageInput": True,
                "promptCache": True,
                "reasoningRoundtrip": True,
                "streamUsageOptions": False,
            },
        }
    }

    client = LLMClient(config=config, backend=lambda payload: payload)

    assert client.capabilities.supports_image_input is True
    assert client.capabilities.supports_prompt_cache is True
    assert client.capabilities.supports_reasoning_roundtrip is True
    assert client.capabilities.supports_stream_usage is False
    assert client.resolved_spec.provider_details["capability_source"] == "model_library.capabilities"
    assert "imageInput" in client.resolved_spec.provider_details["declared_capability_fields"]


def test_model_library_declared_capabilities_do_not_override_disabled_runtime_gates():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "declared-tool-model",
            "llm.profiles.primary.streaming": False,
            "llm.profiles.primary.tool_calling_mode": "disabled",
        }
    )
    profile = config.llm.get_profile("primary")
    config.llm.model_library = {
        "declared-tool-model": {
            "provider_id": profile.provider_id,
            "model": profile.model,
            "capabilities": {
                "streaming": True,
                "tools": True,
                "parallelTools": True,
                "explicitToolChoice": True,
            },
        }
    }

    client = LLMClient(config=config, backend=lambda payload: payload)

    assert client.capabilities.supports_streaming is False
    assert client.capabilities.supports_tool_calling is False
    assert client.capabilities.supports_parallel_tool_calls is False
    assert client.capabilities.supports_explicit_tool_choice is False


def test_llm_client_resolves_protocol_from_model_library_entry():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "plain-looking-model",
            "llm.profiles.primary.contract": "basic_chat",
        }
    )
    profile = config.llm.get_profile("primary")
    config.llm.model_library = {
        "declared-qwen-route": {
            "provider_id": profile.provider_id,
            "model": "plain-looking-model",
            "protocol": "qwen_openai_compat",
            "compat": {"toolChoiceMode": "omit"},
        }
    }

    client = LLMClient(config=config, backend=lambda payload: payload)

    assert client.protocol_route.protocol.value == "qwen_openai_compat"
    assert client.protocol_route.source == "explicit_model"
    assert client.protocol_route.compat.tool_choice_mode == "omit"


def test_openai_compatible_payload_converts_runtime_system_messages_after_first_to_user():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {"role": "system", "content": "system prompt"},
            {"role": "system", "content": "## 运行时提示\n请输出 state"},
        ]
    )

    assert [item["role"] for item in payload["messages"]] == ["system", "user"]


def test_openai_gpt5_payload_sanitizes_temperature_and_tool_choice():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.temperature": 0.7,
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [{"role": "user", "content": "ping"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read one file",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assert payload["model"] == "openai/gpt-5.5"
    assert payload["temperature"] == 1.0
    assert "tools" in payload
    assert "tool_choice" not in payload


def test_anthropic_thinking_display_requires_type():
    with pytest.raises(ValueError, match="thinking_display requires thinking_type"):
        make_config(
            **{
                "llm.providers.default.kind": "anthropic",
                "llm.providers.default.api_key": "test-key",
                "llm.providers.default.base_url": "https://www.atpify.cn",
                "llm.providers.default.compat_mode": "native",
                "llm.profiles.primary.provider_id": "default",
                "llm.profiles.primary.model": "claude-opus-4-7",
                "llm.profiles.primary.thinking_type": "",
                "llm.profiles.primary.thinking_display": "summarized",
            }
        )


def test_llamacpp_qwen_thinking_blocks_assistant_prefill_before_provider():
    config = make_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://192.168.20.30:8081/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "HiModel_xh2_qwen3.5_9b.gguf",
            "llm.profiles.primary.thinking_type": "adaptive",
        }
    )
    called = False

    def backend(payload):
        nonlocal called
        called = True
        return payload

    client = LLMClient(config=config, backend=backend)

    with pytest.raises(LLMError) as exc_info:
        client.invoke(
            [
                {"role": "user", "content": "今天是星期几"},
                {"role": "assistant", "content": "今天是"},
            ]
        )

    assert called is False
    assert exc_info.value.category == "payload_protocol_error"
    assert exc_info.value.details["protocol"] == "llamacpp_qwen_thinking"
    assert exc_info.value.details["payloadValidationResult"] == "blocked_before_provider"


def test_gu_yunshu_qwen_thinking_replay_blocks_prefill_from_model_library_route():
    config = make_config(
        **{
            "llm.providers.houmo_local.kind": "llamacpp",
            "llm.providers.houmo_local.requires_api_key": False,
            "llm.providers.houmo_local.base_url": "http://192.168.20.30:8081/v1",
            "llm.profiles.primary.provider_id": "houmo_local",
            "llm.profiles.primary.model": "placeholder",
        }
    )
    provider_id = config.llm.get_profile("primary").provider_id
    config.llm.model_library["houmo_qwen35_9b_agent"] = {
        "provider_id": provider_id,
        "model": "HiModel_xh2_qwen3.5_9b_256_256k_b1_1chip_2cores_v1.3.0_20260429.gguf",
        "protocol": "llamacpp_qwen_thinking",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "thinking_type": "adaptive",
        "capabilities": {
            "streaming": True,
            "tools": True,
            "thinking": True,
            "reasoningRoundtrip": False,
        },
        "compat": {
            "requiresStringContent": True,
            "strictMessageKeys": True,
            "allowAssistantPrefill": False,
            "reasoningRoundtrip": False,
            "thinkingFormat": "qwen",
            "toolChoiceMode": "omit",
            "streamUsageOptions": False,
        },
    }
    runtime_config = config_for_agent_llm_model(
        config,
        model_id="houmo_qwen35_9b_agent",
    )
    provider_called = False

    def backend(payload):
        nonlocal provider_called
        provider_called = True
        return payload

    client = LLMClient(config=runtime_config, backend=backend)

    with pytest.raises(LLMError) as exc_info:
        client.invoke(
            [
                {"role": "user", "content": "今天是星期几"},
                {"role": "assistant", "content": "今天是"},
            ]
        )

    assert provider_called is False
    assert exc_info.value.category == "payload_protocol_error"
    assert exc_info.value.details["protocol"] == "llamacpp_qwen_thinking"
    assert exc_info.value.details["protocolSource"] == "explicit_model"
    assert exc_info.value.details["thinkingRequested"] is True
    assert exc_info.value.details["assistantPrefillDetected"] is True
    assert exc_info.value.details["payloadValidationResult"] == "blocked_before_provider"


def test_gu_yunshu_qwen_thinking_replay_sends_user_final_without_prefill():
    config = make_config(
        **{
            "llm.providers.houmo_local.kind": "llamacpp",
            "llm.providers.houmo_local.requires_api_key": False,
            "llm.providers.houmo_local.base_url": "http://192.168.20.30:8081/v1",
            "llm.profiles.primary.provider_id": "houmo_local",
            "llm.profiles.primary.model": "placeholder",
        }
    )
    provider_id = config.llm.get_profile("primary").provider_id
    config.llm.model_library["houmo_qwen35_9b_agent"] = {
        "provider_id": provider_id,
        "model": "HiModel_xh2_qwen3.5_9b_256_256k_b1_1chip_2cores_v1.3.0_20260429.gguf",
        "protocol": "llamacpp_qwen_thinking",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "thinking_type": "adaptive",
        "compat": {"toolChoiceMode": "omit"},
    }

    runtime_config = config_for_agent_llm_model(
        config,
        model_id="houmo_qwen35_9b_agent",
    )
    client = LLMClient(config=runtime_config, backend=lambda payload: payload)

    payload = client._build_payload([{"role": "user", "content": "今天是星期几"}])

    assert payload["enable_thinking"] is True
    assert payload["messages"][-1]["role"] == "user"
    assert all("reasoning_content" not in item for item in payload["messages"])
    assert "tool_choice" not in payload
    assert client.protocol_route.source == "explicit_model"
    assert client._last_payload_protocol_summary["assistantPrefillDetected"] is False


def test_responses_transport_routes_openai_compatible_model_through_responses_bridge():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/gpt-5.5"
    assert "messages" not in payload
    assert "max_tokens" not in payload
    assert payload["max_output_tokens"] == config.llm.get_profile("primary").max_output_tokens
    assert payload["input"] == [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "ping"}],
        }
    ]


def test_responses_discards_unanchored_stateless_replay_for_user_only_request(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-terra",
            "llm.profiles.primary.transport": "responses",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=client.protocol_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(client.protocol_route.runtime_endpoint),
        model_id=client.protocol_route.model_id,
        wire_protocol=client.protocol_route.wire_protocol,
        opaque_items=(
            OpaqueReplayItem(
                item_id="rs-orphaned",
                payload=json.dumps(
                    {
                        "id": "rs-orphaned",
                        "type": "reasoning",
                        "encrypted_content": "opaque-orphaned",
                    }
                ).encode("utf-8"),
            ),
        ),
    )
    recorded = []
    monkeypatch.setattr(
        "core.llm.client._record_llm_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )

    payload = client._build_payload(
        [{"role": "user", "content": "你有什么工具"}],
        replay_state=replay_state,
    )

    assert payload["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "你有什么工具"}]},
    ]
    assert "previous_response_id" not in payload
    replay_event = next(
        (args, kwargs)
        for args, kwargs in recorded
        if len(args) > 1 and args[1] == "llm.replay_state.degraded"
    )
    assert replay_event[1]["fields"] == {
        "profileId": "primary",
        "provider": "relay",
        "model": "gpt-5.6-terra",
        "protocol": "relay_responses",
        "reason": "missing_assistant_anchor",
        "continuationMode": "stateless_replay_dropped",
        "replayItemCount": 1,
        "replayByteSize": replay_state.byte_size,
        "hasResponseId": False,
        "previousResponseIdUsable": False,
        "messageCount": 1,
        "finalMessageRole": "user",
    }


def test_responses_discards_unusable_stateful_bookmark_when_continuation_is_disabled(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-terra",
            "llm.profiles.primary.transport": "responses",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=client.protocol_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(client.protocol_route.runtime_endpoint),
        model_id=client.protocol_route.model_id,
        wire_protocol=client.protocol_route.wire_protocol,
        opaque_items=(
            OpaqueReplayItem(
                item_id="rs-stateful",
                payload=json.dumps(
                    {
                        "id": "rs-stateful",
                        "type": "reasoning",
                        "encrypted_content": "opaque-stateful",
                    }
                ).encode("utf-8"),
            ),
        ),
        response_id="resp-stateful",
    )
    recorded = []
    monkeypatch.setattr(
        "core.llm.client._record_llm_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )

    payload = client._build_payload(
        [{"role": "user", "content": "继续"}],
        replay_state=replay_state,
    )

    assert "previous_response_id" not in payload
    assert payload["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "继续"}]},
    ]
    replay_event = next(
        (args, kwargs)
        for args, kwargs in recorded
        if len(args) > 1 and args[1] == "llm.replay_state.degraded"
    )
    assert replay_event[1]["fields"]["continuationMode"] == (
        "unsupported_previous_response_id_replay_dropped"
    )
    assert replay_event[1]["fields"]["hasResponseId"] is True
    assert replay_event[1]["fields"]["previousResponseIdUsable"] is False
    assert replay_event[1]["fields"]["replayItemCount"] == 1


def test_responses_replays_captured_opaque_items_in_provider_order_without_message_ids():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-terra",
            "llm.profiles.primary.transport": "responses",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)
    replay_items = [
        {
            "id": "rs-first",
            "type": "reasoning",
            "encrypted_content": "opaque-first",
            "summary": [],
        },
        {
            "id": "rs-second",
            "type": "reasoning",
            "encrypted_content": "opaque-second",
            "summary": [],
        },
    ]
    outcome = ResponsesWireAdapter().decode_response(
        {
            "id": "resp-terra-1",
            "status": "completed",
            "output": [
                *replay_items,
                {
                    "id": "msg-terra-1",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "previous answer"}],
                },
            ],
        },
        route=client.protocol_route,
        scope=InvocationScope(
            session_id="session-terra",
            turn_id="turn-terra-1",
            invocation_id="invocation-terra-1",
            iteration=0,
        ),
    )

    assert [item.item_id for item in outcome.replay_state.opaque_items] == ["rs-first", "rs-second"]

    payload = client._build_payload(
        [
            {"role": "user", "content": "first prompt"},
            AIMessage(content="previous answer"),
            {"role": "user", "content": "continue"},
        ],
        replay_state=outcome.replay_state,
    )

    assert payload["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "first prompt"}]},
        *replay_items,
        {"role": "assistant", "content": [{"type": "output_text", "text": "previous answer"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "continue"}]},
    ]
    assert "previous_response_id" not in payload


def test_responses_preserves_explicit_replay_anchor_before_later_assistant():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-terra",
            "llm.profiles.primary.transport": "responses",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)
    replay_item = {
        "id": "rs-anchored",
        "type": "reasoning",
        "encrypted_content": "opaque-anchored",
        "summary": [],
    }
    outcome = ResponsesWireAdapter().decode_response(
        {
            "id": "resp-terra-anchor",
            "status": "completed",
            "output": [replay_item],
        },
        route=client.protocol_route,
        scope=InvocationScope(
            session_id="session-terra",
            turn_id="turn-terra-anchor",
            invocation_id="invocation-terra-anchor",
            iteration=0,
        ),
    )

    payload = client._build_payload(
        [
            {"role": "user", "content": "first prompt"},
            AIMessage(
                content="anchored answer",
                additional_kwargs={"reasoning_replay_item_id": "rs-anchored"},
            ),
            {"role": "user", "content": "middle prompt"},
            AIMessage(content="later answer"),
            {"role": "user", "content": "continue"},
        ],
        replay_state=outcome.replay_state,
    )

    assert payload["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "first prompt"}]},
        replay_item,
        {"role": "assistant", "content": [{"type": "output_text", "text": "anchored answer"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "middle prompt"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "later answer"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "continue"}]},
    ]


def test_responses_rejects_partial_explicit_replay_mapping_instead_of_fallback():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-terra",
            "llm.profiles.primary.transport": "responses",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)
    opaque_items = tuple(
        OpaqueReplayItem(
            item_id=item_id,
            payload=json.dumps(
                {"id": item_id, "type": "reasoning", "encrypted_content": f"opaque-{item_id}"}
            ).encode("utf-8"),
        )
        for item_id in ("rs-first", "rs-second")
    )
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=client.protocol_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(client.protocol_route.runtime_endpoint),
        model_id=client.protocol_route.model_id,
        wire_protocol=client.protocol_route.wire_protocol,
        opaque_items=opaque_items,
    )

    with pytest.raises(LLMError, match="rs-second.*no unique explicit assistant anchor"):
        client._build_payload(
            [
                AIMessage(
                    content="anchored answer",
                    additional_kwargs={"reasoning_replay_item_id": "rs-first"},
                ),
                AIMessage(content="later answer"),
                {"role": "user", "content": "continue"},
            ],
            replay_state=replay_state,
        )


@pytest.mark.parametrize(
    ("provider_item", "error_match"),
    [
        ({"id": "rs-invalid", "type": "message", "content": []}, "type `reasoning`"),
        (
            {"id": "rs-other", "type": "reasoning", "encrypted_content": "opaque"},
            "id does not match replay state",
        ),
    ],
)
def test_responses_rejects_incompatible_opaque_payload_before_adapter(provider_item, error_match):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-terra",
            "llm.profiles.primary.transport": "responses",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=client.protocol_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(client.protocol_route.runtime_endpoint),
        model_id=client.protocol_route.model_id,
        wire_protocol=client.protocol_route.wire_protocol,
        opaque_items=(
            OpaqueReplayItem(
                item_id="rs-invalid",
                payload=json.dumps(provider_item).encode("utf-8"),
            ),
        ),
    )

    with pytest.raises(LLMError, match=error_match):
        client._build_payload(
            [AIMessage(content="previous answer"), {"role": "user", "content": "continue"}],
            replay_state=replay_state,
        )


def test_protocol_switch_reencodes_complete_history_after_private_replay_is_cleared():
    common = {
        "llm.providers.default.kind": "relay",
        "llm.providers.default.api_key": "test-key",
        "llm.providers.default.base_url": "https://relay.example.test/v1",
        "llm.providers.default.compat_mode": "openai",
        "llm.profiles.primary.provider_id": "default",
        "llm.profiles.primary.model": "gpt-5.5",
    }
    messages = [
        {"role": "user", "content": "look up both"},
        AIMessage(
            content="checking",
            tool_calls=[
                {"id": "call-a", "name": "first", "args": {}},
                {"id": "call-b", "name": "second", "args": {}},
            ],
            additional_kwargs={"reasoning_replay_item_id": "reasoning-1"},
        ),
        ToolMessage(content="A", tool_call_id="call-a"),
        ToolMessage(content="B", tool_call_id="call-b"),
        AIMessage(content="both done"),
        {"role": "user", "content": "continue"},
    ]
    responses = LLMClient(
        config=make_config(**{**common, "llm.profiles.primary.transport": "responses"}),
        backend=lambda payload: payload,
    )._build_payload(messages, replay_state=None)
    chat = LLMClient(
        config=make_config(**{**common, "llm.profiles.primary.transport": "chat_completions"}),
        backend=lambda payload: payload,
    )._build_payload(messages, replay_state=None)

    assert "previous_response_id" not in responses
    assert "messages" not in responses
    assert [item.get("type") for item in responses["input"] if "type" in item] == [
        "function_call",
        "function_call",
        "function_call_output",
        "function_call_output",
    ]
    assert "input" not in chat
    assert [message["role"] for message in chat["messages"]] == [
        "user",
        "assistant",
        "tool",
        "tool",
        "assistant",
        "user",
    ]
    assert [call["id"] for call in chat["messages"][1]["tool_calls"]] == ["call-a", "call-b"]
    assert [message["tool_call_id"] for message in chat["messages"][2:4]] == ["call-a", "call-b"]


def test_responses_transport_does_not_add_responses_to_litellm_model_name():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/gpt-5.5"


def test_responses_transport_invokes_responses_backend():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
        }
    )
    calls = []

    def chat_backend(payload):
        calls.append(("chat", payload))
        return {"choices": [{"message": {"role": "assistant", "content": "chat"}}]}

    def responses_backend(payload):
        calls.append(("responses", payload))
        return {"output_text": "responses ok", "usage": {}}

    client = LLMClient(config=config, backend=chat_backend, responses_backend=responses_backend)
    message = client.invoke([{"role": "user", "content": "ping"}])

    assert message.content == "responses ok"
    assert [kind for kind, _payload in calls] == ["responses"]
    assert "input" in calls[0][1]
    assert "messages" not in calls[0][1]


def test_default_responses_backend_maps_internal_base_url_to_litellm_api_base(monkeypatch):
    import litellm

    calls = []

    def responses(**kwargs):
        calls.append(kwargs)
        return {"output_text": "responses ok", "usage": {}}

    monkeypatch.setattr(litellm, "responses", responses, raising=False)
    payload = {
        "model": "openai/gpt-5.5",
        "api_key": "test-key",
        "base_url": "https://ai-pixel.online",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "ping"}]}],
    }

    response = _default_responses_backend(payload)

    assert response["output_text"] == "responses ok"
    assert calls[0]["api_base"] == "https://ai-pixel.online"
    assert "base_url" not in calls[0]
    assert payload["base_url"] == "https://ai-pixel.online"
    assert "api_base" not in payload


def test_default_responses_backend_does_not_duplicate_final_responses_endpoint(monkeypatch):
    import litellm

    calls = []

    def responses(**kwargs):
        calls.append(kwargs)
        return {"output_text": "responses ok", "usage": {}}

    monkeypatch.setattr(litellm, "responses", responses, raising=False)
    payload = {
        "model": "openai/gpt-5.6-luna",
        "api_key": "test-key",
        "base_url": "https://ai-pixel.online/v1/responses",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "ping"}]}],
    }

    response = _default_responses_backend(payload)

    assert response["output_text"] == "responses ok"
    assert calls[0]["api_base"] == "https://ai-pixel.online/v1"
    assert payload["base_url"] == "https://ai-pixel.online/v1/responses"


def test_responses_transport_streams_with_responses_normalizer(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.streaming": True,
        }
    )
    calls = []
    recorded = []

    def default_responses_backend(payload):
        calls.append(payload)
        return iter(
            [
                {"type": "response.output_text.delta", "delta": "res"},
                {"type": "response.output_text.delta", "delta": "ponses"},
                {
                    "type": "response.completed",
                    "response": {"usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}},
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._default_responses_backend", default_responses_backend)
    monkeypatch.setattr(
        "core.llm.client._record_llm_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )
    client = LLMClient(config=config)

    events = list(
        client.stream_events(
            [{"role": "user", "content": "ping"}],
            metadata={
                "turnId": "turn-safe",
                "sessionId": "session-safe",
                "invocationId": "invocation-safe",
            },
        )
    )

    assert [event.type for event in events] == ["text_delta", "text_delta", "done"]
    assert [event.text for event in events[:2]] == ["res", "ponses"]
    assert events[-1].usage.total_tokens == 5
    assert "input" in calls[0]
    assert "messages" not in calls[0]
    started_fields = next(item for item in recorded if item[0][1] == "llm.stream.started")[1]["fields"]
    succeeded_fields = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")[1]["fields"]
    for fields in (started_fields, succeeded_fields):
        assert fields["previousResponseIdPresent"] is False
        assert fields["continuationMode"] == "initial"
        assert fields["responseInputItemCount"] == 1
        assert fields["functionCallOutputCount"] == 0
        field_keys = list(fields)
        for key in (
            "turnId",
            "sessionId",
            "invocationId",
            "previousResponseIdPresent",
            "continuationMode",
            "responseInputItemCount",
            "functionCallOutputCount",
        ):
            assert field_keys.index(key) < 24


def test_responses_transport_streams_completed_output_blocks_when_no_delta(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.streaming": True,
        }
    )

    def default_responses_backend(payload):
        return iter(
            [
                {
                    "type": "response.completed",
                    "response": {
                        "output": [
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "completed fallback",
                                    }
                                ],
                            }
                        ],
                        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                    },
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._default_responses_backend", default_responses_backend)
    client = LLMClient(config=config)

    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[0].text == "completed fallback"
    assert events[-1].usage.total_tokens == 5


def test_responses_incomplete_reason_is_recorded_in_canonical_outcome_log(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.streaming": True,
        }
    )
    recorded = []

    def default_responses_backend(payload):
        return iter(
            [
                {
                    "type": "response.incomplete",
                    "response": {
                        "id": "resp-incomplete",
                        "status": "incomplete",
                        "incomplete_details": {"reason": "max_output_tokens"},
                    },
                }
            ]
        )

    monkeypatch.setattr("core.llm.client._default_responses_backend", default_responses_backend)
    monkeypatch.setattr(
        "core.llm.client._record_llm_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )
    client = LLMClient(config=config)

    list(client.stream([{"role": "user", "content": "ping"}]))

    canonical_event = next(item for item in recorded if item[0][1] == "llm.canonical_outcome.finalized")
    assert canonical_event[1]["fields"]["terminalReason"] == "max_output_tokens"


def test_responses_empty_stream_retries_without_exposing_transient_done(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-luna",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.streaming": True,
            "llm.profiles.primary.retry_policy.max_attempts": 2,
        }
    )
    attempts = {"count": 0}
    recorded = []
    published_statuses = []

    def default_responses_backend(payload):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return iter(())
        return iter(
            [
                {"type": "response.output_text.delta", "delta": "recovered"},
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp-recovered",
                        "status": "completed",
                        "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
                    },
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._default_responses_backend", default_responses_backend)
    monkeypatch.setattr("core.llm.client._sleep_with_llm_cancel_check", lambda _seconds: None)
    monkeypatch.setattr(
        "core.llm.client._record_llm_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "core.llm.client._publish_llm_status_event",
        lambda status, **fields: published_statuses.append((status, fields)),
    )
    client = LLMClient(config=config)

    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert attempts["count"] == 2
    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[0].text == "recovered"
    assert any(item[0][1] == "llm.stream.failed.retrying" for item in recorded)
    assert [
        status
        for status, _fields in published_statuses
        if status in {"retrying", "retry_recovered"}
    ] == [
        "retrying",
        "retry_recovered",
    ]


def test_responses_stream_exhaustion_after_partial_output_does_not_retry(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-luna",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.streaming": True,
            "llm.profiles.primary.retry_policy.max_attempts": 3,
        }
    )
    attempts = {"count": 0}

    def default_responses_backend(payload):
        attempts["count"] += 1
        return iter([{"type": "response.output_text.delta", "delta": "partial"}])

    monkeypatch.setattr("core.llm.client._default_responses_backend", default_responses_backend)
    monkeypatch.setattr("core.llm.client._sleep_with_llm_cancel_check", lambda _seconds: None)
    client = LLMClient(config=config)

    with pytest.raises(LLMError) as raised:
        list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert raised.value.category == "server_error"
    assert attempts["count"] == 1


def test_chat_reasoning_only_exhaustion_retries_without_exposing_transient_reasoning(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-v4-flash",
            "llm.profiles.primary.retry_policy.max_attempts": 2,
        }
    )
    attempts = {"count": 0}

    def backend(_payload):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return iter([{"choices": [{"index": 0, "delta": {"reasoning_content": "transient"}}]}])
        return iter(
            [
                {"choices": [{"index": 0, "delta": {"reasoning_content": "recovered"}}]},
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "answer"},
                            "finish_reason": "stop",
                        }
                    ]
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._sleep_with_llm_cancel_check", lambda _seconds: None)
    client = LLMClient(config=config, backend=backend)

    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert attempts["count"] == 2
    assert [event.type for event in events] == ["reasoning_delta", "text_delta", "done"]
    assert events[0].text == "recovered"
    assert events[1].text == "answer"


def test_responses_transport_streams_output_item_done_message_when_no_delta(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.streaming": True,
        }
    )

    def default_responses_backend(payload):
        return iter(
            [
                {
                    "type": "response.output_item.done",
                    "item": {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "item done fallback",
                            }
                        ],
                    },
                },
                {
                    "type": "response.completed",
                    "response": {
                        "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
                    },
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._default_responses_backend", default_responses_backend)
    client = LLMClient(config=config)

    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[0].text == "item done fallback"
    assert events[-1].usage.total_tokens == 7


def test_responses_transport_streams_function_call_items(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.streaming": True,
        }
    )
    calls = []

    def default_responses_backend(payload):
        calls.append(payload)
        return iter(
            [
                {"type": "response.output_text.delta", "delta": "先看"},
                {
                    "type": "response.output_item.added",
                    "item": {
                        "id": "fc_1",
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "read_file",
                    },
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_1",
                    "delta": "{\"path\"",
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_1",
                    "delta": ": \"agent.py\"}",
                },
                {
                    "type": "response.output_item.done",
                    "item": {
                        "id": "fc_1",
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "read_file",
                        "arguments": "{\"path\": \"agent.py\"}",
                    },
                },
                {"type": "response.completed", "response": {"usage": {"total_tokens": 7}}},
            ]
        )

    monkeypatch.setattr("core.llm.client._default_responses_backend", default_responses_backend)
    client = LLMClient(config=config)

    events = list(client.stream_events([{"role": "user", "content": "read"}]))

    assert [event.type for event in events] == ["text_delta", "tool_call_final", "done"]
    assert events[0].text == "先看"
    assert events[1].tool_calls[0].id == "call_1"
    assert events[1].tool_calls[0].name == "read_file"
    assert events[1].tool_calls[0].arguments == {"path": "agent.py"}
    assert events[1].tool_calls[0].raw_arguments == "{\"path\": \"agent.py\"}"
    assert events[-1].usage.total_tokens == 7
    assert "input" in calls[0]
    assert "messages" not in calls[0]


def test_responses_transport_preserves_existing_provider_prefix():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.openai.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "openai/gpt-5.5",
            "llm.profiles.primary.transport": "responses",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/gpt-5.5"


def test_openai_compatible_payload_prefixes_model_names_that_contain_slash():
    config = make_config(
        **{
            "llm.providers.default.kind": "siliconflow",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.siliconflow.cn/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-ai/DeepSeek-V3",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/deepseek-ai/DeepSeek-V3"


def test_payload_does_not_double_prefix_litellm_qualified_model():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "minimax/MiniMax-M2.7",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "minimax/MiniMax-M2.7"


def test_deepseek_payload_preserves_reasoning_content_for_assistant_history():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "read_file", "args": {"path": "agent.py"}}],
                additional_kwargs={"reasoning_content": "先读文件再决定"},
            ),
            ToolMessage(content="agent.py content", tool_call_id="call_1"),
        ]
    )

    assert payload["messages"][0]["role"] == "assistant"
    assert payload["messages"][0]["reasoning_content"] == "先读文件再决定"
    assert payload["messages"][0]["tool_calls"][0]["id"] == "call_1"
    assert payload["messages"][1]["role"] == "tool"
    assert payload["messages"][1]["tool_call_id"] == "call_1"


def test_deepseek_payload_omits_explicit_tool_choice_in_thinking_mode():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-v4-pro",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [{"role": "user", "content": "ping"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read one file",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assert "tools" in payload
    assert "tool_choice" not in payload


def test_invoke_preserves_reasoning_content_in_ai_message():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
        }
    )

    def backend(_payload):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "已完成",
                        "reasoning_content": "先分析再作答",
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    client = LLMClient(config=config, backend=backend)
    message = client.invoke([{"role": "user", "content": "hi"}])

    assert message.content == "已完成"
    assert message.additional_kwargs["reasoning_content"] == "先分析再作答"


def test_invoke_extracts_reasoning_alias_and_strips_think_tags():
    config = make_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3-local",
        }
    )

    def backend(_payload):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "<think>先看日志</think>结论",
                        "reasoning": "先看日志",
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    client = LLMClient(config=config, backend=backend)
    message = client.invoke([{"role": "user", "content": "hi"}])

    assert message.content == "结论"
    assert message.additional_kwargs["reasoning_content"] == "先看日志"


def test_invoke_extracts_think_tags_when_provider_has_no_reasoning_field():
    config = make_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3-local",
        }
    )

    def backend(_payload):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "<thinking>先判断工具是否可用</thinking>\n可以继续。",
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    client = LLMClient(config=config, backend=backend)
    message = client.invoke([{"role": "user", "content": "hi"}])

    assert message.content == "\n可以继续。"
    assert message.additional_kwargs["reasoning_content"] == "先判断工具是否可用"


def test_invoke_records_cached_input_token_observation(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.prompt_cache.mode": "disabled",
        }
    )
    recorded = []

    def backend(_payload):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 8,
                "total_tokens": 108,
                "prompt_tokens_details": {"cached_tokens": 64},
            },
        }

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    message = client.invoke([{"role": "user", "content": "ping"}])

    assert message.response_metadata["usage_observation"]["cached_input_tokens"] == 64
    assert message.response_metadata["usage_observation"]["cache_hit_rate"] == pytest.approx(0.64)
    assert message.response_metadata["llm_protocol"]["protocol"]
    assert "payloadValidationResult" in message.response_metadata["llm_protocol"]
    assert isinstance(message.response_metadata["llm_capability_source"], dict)
    success_event = next(item for item in recorded if item[0][1] == "llm.invoke.succeeded")
    assert success_event[1]["fields"]["cachedInputTokens"] == 64
    assert success_event[1]["fields"]["cacheHitRate"] == pytest.approx(0.64)


def test_invoke_records_cache_read_token_observation(monkeypatch):
    config = supported_relay_chat_config()
    recorded = []

    def backend(_payload):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {
                "input_tokens": 200,
                "output_tokens": 10,
                "cache_read_input_tokens": 80,
                "cache_creation_input_tokens": 40,
            },
        }

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    message = client.invoke([{"role": "user", "content": "ping"}])

    usage = message.response_metadata["usage_observation"]
    assert usage["input_tokens"] == 200
    assert usage["output_tokens"] == 10
    assert usage["cached_input_tokens"] == 80
    assert usage["cache_read_input_tokens"] == 80
    assert usage["cache_creation_input_tokens"] == 40
    assert usage["uncached_input_tokens"] == 120
    assert usage["cache_hit_rate"] == pytest.approx(0.4)
    success_event = next(item for item in recorded if item[0][1] == "llm.invoke.succeeded")
    assert success_event[1]["fields"]["cachedInputTokens"] == 80
    assert success_event[1]["fields"]["cacheReadInputTokens"] == 80
    assert success_event[1]["fields"]["cacheCreationInputTokens"] == 40
    assert success_event[1]["fields"]["uncachedInputTokens"] == 120
    assert success_event[1]["fields"]["cacheHitRate"] == pytest.approx(0.4)


def test_invoke_records_safe_payload_shape_without_prompt_text(monkeypatch):
    config = supported_relay_chat_config()
    recorded = []

    def backend(_payload):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    client.invoke(
        [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "stable-secret-prefix", "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": "dynamic-current-goal"},
                ],
            },
            {"role": "user", "content": "user-secret-message"},
        ]
    )

    fields = next(item for item in recorded if item[0][1] == "llm.invoke.succeeded")[1]["fields"]
    shape = fields["payloadShape"]
    assert shape["firstSystemBlockCount"] == 2
    assert shape["firstSystemCacheControlBlockCount"] == 1
    assert shape["firstSystemCacheableTextChars"] == len("stable-secret-prefix")
    assert shape["firstSystemDynamicTextChars"] == len("dynamic-current-goal")
    serialized = json.dumps(fields, ensure_ascii=False)
    assert "stable-secret-prefix" not in serialized
    assert "dynamic-current-goal" not in serialized
    assert "user-secret-message" not in serialized


def test_llm_error_stores_error_category():
    error = LLMError("provider_protocol_error", "bad request", retryable=False)

    assert error.category == "provider_protocol_error"


def test_invoke_failure_records_category_without_masking_provider_error(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.prompt_cache.mode": "disabled",
        }
    )
    recorded = []

    def backend(_payload):
        raise Exception('400: One of "input" or "previous_response_id" must be provided.')

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)

    with pytest.raises(LLMError) as raised:
        client.invoke([{"role": "user", "content": "ping"}])

    assert raised.value.category == "provider_protocol_error"
    assert 'One of "input"' in str(raised.value)
    assert recorded[-1][1]["message"] == "LLM invoke failed: provider_protocol_error"
    assert recorded[-1][1]["fields"]["errorType"] == "provider_protocol_error"
    assert recorded[-1][1]["fields"]["protocol"]
    assert recorded[-1][1]["fields"]["selectedProtocol"] == recorded[-1][1]["fields"]["protocol"]
    assert recorded[-1][1]["fields"]["protocolSource"]
    assert recorded[-1][1]["fields"]["payloadValidationResult"] == "passed"
    assert 'One of "input"' in recorded[-1][1]["fields"]["error"]


def test_invoke_failure_records_model_library_capability_source(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "declared-failure-model",
        }
    )
    profile = config.llm.get_profile("primary")
    config.llm.model_library = {
        "declared-failure-model": {
            "provider_id": profile.provider_id,
            "model": profile.model,
            "capabilities": {"imageInput": True},
        }
    }
    recorded = []

    def backend(_payload):
        raise Exception("provider closed connection")

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)

    with pytest.raises(LLMError):
        client.invoke([{"role": "user", "content": "ping"}])

    fields = recorded[-1][1]["fields"]
    assert fields["modelLibraryId"] == "declared-failure-model"
    assert fields["capabilitySource"] == "model_library.capabilities"
    assert fields["declaredCapabilityFields"] == ["imageInput"]


def test_invoke_retries_retryable_timeout_up_to_profile_limit(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.retry_policy.max_attempts": 5,
            "llm.profiles.primary.retry_policy.backoff_base_seconds": 0.1,
        }
    )
    recorded = []
    statuses = []
    attempts = {"count": 0}
    payloads = []

    def backend(payload):
        payloads.append(dict(payload))
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("provider timeout")
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr("core.llm.client.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))
    monkeypatch.setattr("core.llm.client._publish_llm_status_event", lambda status, **fields: statuses.append((status, fields)))

    client = LLMClient(config=config, backend=backend)
    message = client.invoke(
        [{"role": "user", "content": "ping"}],
        metadata={
            "sessionId": "session-retry",
            "turnId": "turn-retry",
            "invocationId": "invoke-retry",
            "llmSlot": "dialogue",
            "promptPurpose": "main_reply",
            "conversationBound": True,
        },
    )

    assert message.content == "ok"
    assert attempts["count"] == 3
    assert payloads[0] == payloads[1] == payloads[2]
    retry_events = [item for item in recorded if item[0][1] == "llm.invoke.failed.retrying"]
    assert [event[1]["fields"]["attempt"] for event in retry_events] == [1, 2]
    assert [event[1]["fields"]["nextAttempt"] for event in retry_events] == [2, 3]
    for _args, kwargs in retry_events:
        fields = kwargs["fields"]
        assert fields["sessionId"] == "session-retry"
        assert fields["turnId"] == "turn-retry"
        assert fields["invocationId"] == "invoke-retry"
        assert fields["llmSlot"] == "dialogue"
        assert fields["promptPurpose"] == "main_reply"
        assert fields["invocationContextPresent"] is True
        assert fields["retryRequestMode"] == "same_wire_payload"
        assert fields["llmPayloadTraceId"]
        assert list(fields).index("invocationId") < 24


def test_stream_retries_retryable_failure_before_first_event(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.retry_policy.max_attempts": 5,
            "llm.profiles.primary.retry_policy.backoff_base_seconds": 0.1,
        }
    )
    recorded = []
    statuses = []
    attempts = {"count": 0}
    payloads = []

    def failing_before_first_chunk():
        raise TimeoutError("stream timeout")
        yield {"choices": [{"delta": {"content": "unreachable"}}]}

    def backend(payload):
        payloads.append(dict(payload))
        attempts["count"] += 1
        if attempts["count"] < 3:
            return failing_before_first_chunk()
        return iter([{"choices": [{"delta": {"content": "ok"}}]}])

    monkeypatch.setattr("core.llm.client.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))
    monkeypatch.setattr("core.llm.client._publish_llm_status_event", lambda status, **fields: statuses.append((status, fields)))

    client = LLMClient(config=config, backend=backend)
    events = list(
        client.stream_events(
            [{"role": "user", "content": "ping"}],
            metadata={
                "sessionId": "session-stream-retry",
                "turnId": "turn-stream-retry",
                "invocationId": "stream-retry",
                "llmSlot": "dialogue",
                "promptPurpose": "main_reply",
                "conversationBound": True,
            },
        )
    )

    assert attempts["count"] == 3
    assert payloads[0] == payloads[1] == payloads[2]
    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[0].text == "ok"
    retry_events = [item for item in recorded if item[0][1] == "llm.stream.failed.retrying"]
    assert [event[1]["fields"]["attempt"] for event in retry_events] == [1, 2]
    assert all(
        event[1]["fields"]["retryRequestMode"] == "same_wire_payload"
        for event in retry_events
    )
    assert all(
        event[1]["fields"]["invocationId"] == "stream-retry"
        for event in retry_events
    )
    retry_statuses = [item for item in statuses if item[0] == "retrying"]
    assert [item[0] for item in retry_statuses] == ["retrying", "retrying"]
    assert [item[1]["attempt"] for item in retry_statuses] == [1, 2]


def test_stream_fails_stream_only_after_retryable_pre_chunk_failures(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.retry_policy.max_attempts": 2,
            "llm.profiles.primary.retry_policy.backoff_base_seconds": 0.1,
        }
    )
    recorded = []
    statuses = []
    payloads = []

    def failing_before_first_chunk():
        raise Exception(
            "litellm.MidStreamFallbackError: peer closed connection without sending complete message body "
            "(incomplete chunked read)"
        )
        yield {"choices": [{"delta": {"content": "unreachable"}}]}

    def backend(payload):
        payloads.append(dict(payload))
        if payload.get("stream"):
            return failing_before_first_chunk()
        return {
            "choices": [
                {"message": {"role": "assistant", "content": "fallback ok"}}
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }

    monkeypatch.setattr("core.llm.client.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))
    monkeypatch.setattr("core.llm.client._publish_llm_status_event", lambda status, **fields: statuses.append((status, fields)))

    client = LLMClient(config=config, backend=backend)
    with pytest.raises(LLMError) as exc_info:
        list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert exc_info.value.category == "network_error"
    assert [payload["stream"] for payload in payloads] == [True, True]
    event_codes = [item[0][1] for item in recorded]
    assert "llm.stream.fallback.invoke_started" not in event_codes
    assert "llm.stream.fallback.invoke_succeeded" not in event_codes
    business_statuses = [
        item for item in statuses
        if item[0] in {"retrying", "failed"}
    ]
    assert [item[0] for item in business_statuses] == ["retrying", "failed"]


def test_stream_records_success_event_with_safe_summary(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []

    def backend(_payload):
        return iter(
            [
                {"choices": [{"delta": {"content": "ok"}}]},
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "function": {"name": "read_file", "arguments": "{}"},
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}], tools=[{"name": "read_file"}]))

    assert [event.type for event in events] == ["text_delta", "tool_call_final", "done"]
    success_events = [item for item in recorded if item[0][1] == "llm.stream.succeeded"]
    assert success_events
    fields = success_events[-1][1]["fields"]
    assert fields["messageCount"] == 1
    assert fields["toolCount"] == 1
    assert fields["chunkCount"] == 3
    assert fields["textDeltaCount"] == 1
    assert fields["toolCallCount"] == 1
    assert "latencyMs" in fields
    assert fields["firstChunkMs"] is not None
    assert fields["firstTextDeltaMs"] is not None
    assert fields["firstReasoningDeltaMs"] is None
    assert fields["maxInterChunkMs"] >= 0
    assert fields["avgInterChunkMs"] >= 0
    assert fields["interChunkCount"] == 2
    first_chunk_event = next(item for item in recorded if item[0][1] == "llm.stream.first_chunk")
    first_chunk_fields = first_chunk_event[1]["fields"]
    assert first_chunk_fields["elapsedMs"] >= 0
    assert first_chunk_fields["chunkType"] == "text_delta"
    first_content_event = next(item for item in recorded if item[0][1] == "llm.stream.first_content_delta")
    first_content_fields = first_content_event[1]["fields"]
    assert first_content_fields["elapsedMs"] >= first_chunk_fields["elapsedMs"]
    assert first_content_fields["contentChars"] == len("ok")
    assert "content" not in first_content_fields


def test_stream_records_usage_and_cache_hit_rate(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []
    payloads = []

    def backend(payload):
        payloads.append(dict(payload))
        return iter(
            [
                {"choices": [{"delta": {"content": "ok"}}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "total_tokens": 120,
                        "prompt_tokens_details": {"cached_tokens": 64},
                    },
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert payloads[0]["stream_options"] == {"include_usage": True}
    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[-1].usage is not None
    assert events[-1].usage.input_tokens == 100
    assert events[-1].usage.cached_input_tokens == 64
    success_event = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")
    fields = success_event[1]["fields"]
    field_keys = list(fields)
    assert field_keys.index("usageObserved") < 24
    assert field_keys.index("cachedInputTokens") < 24
    assert fields["inputTokens"] == 100
    assert fields["outputTokens"] == 20
    assert fields["cachedInputTokens"] == 64
    assert fields["cacheHitRate"] == pytest.approx(0.64)
    assert fields["usageObserved"] is True
    assert fields["usageMissingReason"] == ""
    assert fields["payloadShape"]["messageTextCharsByRole"] == {"user": len("ping")}
    assert fields["payloadShape"]["toolSchemaHash"] == ""


def test_deepseek_stream_records_prompt_cache_hit_and_miss_usage():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
        }
    )
    payloads = []

    def backend(payload):
        payloads.append(dict(payload))
        return iter(
            [
                {"choices": [{"delta": {"content": "ok"}}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 120,
                        "completion_tokens": 10,
                        "total_tokens": 130,
                        "prompt_cache_hit_tokens": 80,
                        "prompt_cache_miss_tokens": 40,
                    },
                },
            ]
        )

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert payloads[0]["stream_options"] == {"include_usage": True}
    assert events[-1].usage is not None
    assert events[-1].usage.input_tokens == 120
    assert events[-1].usage.cached_input_tokens == 80
    assert events[-1].usage.provider_raw_usage["prompt_cache_hit_tokens"] == 80
    assert events[-1].usage.provider_raw_usage["prompt_cache_miss_tokens"] == 40
    outcome = events[-1].provider_payload["turn_outcome"]
    projected = client.project_outcome_message(outcome)
    assert projected.response_metadata["usage_observation"]["input_tokens"] == 120
    assert projected.response_metadata["usage_observation"]["cached_input_tokens"] == 80


def test_stream_records_cache_read_token_observation(monkeypatch):
    config = supported_relay_chat_config()
    recorded = []

    def backend(_payload):
        return iter(
            [
                {"choices": [{"delta": {"content": "ok"}}]},
                {
                    "usage": {
                        "input_tokens": 200,
                        "output_tokens": 20,
                        "cache_read_input_tokens": 75,
                        "cache_creation_input_tokens": 25,
                    },
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[-1].usage is not None
    assert events[-1].usage.input_tokens == 200
    assert events[-1].usage.cached_input_tokens == 75
    assert events[-1].usage.cache_creation_input_tokens == 25
    success_event = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")
    fields = success_event[1]["fields"]
    assert fields["inputTokens"] == 200
    assert fields["outputTokens"] == 20
    assert fields["cachedInputTokens"] == 75
    assert fields["cacheReadInputTokens"] == 75
    assert fields["cacheCreationInputTokens"] == 25
    assert fields["uncachedInputTokens"] == 125
    assert fields["cacheHitRate"] == pytest.approx(0.375)
    assert fields["usageObserved"] is True


def test_stream_marks_cache_creation_only_usage_as_observed(monkeypatch):
    config = supported_relay_chat_config()
    recorded = []

    def backend(_payload):
        return iter(
            [
                {"choices": [{"delta": {"content": "ok"}}]},
                {
                    "usage": {
                        "input_tokens": 200,
                        "output_tokens": 20,
                        "cache_creation_input_tokens": 60,
                    },
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert events[-1].usage is not None
    assert events[-1].usage.cached_input_tokens == 0
    assert events[-1].usage.cache_creation_input_tokens == 60
    fields = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")[1]["fields"]
    assert fields["usageObserved"] is True
    assert fields["cachedInputTokens"] == 0
    assert fields["cacheReadInputTokens"] == 0
    assert fields["cacheCreationInputTokens"] == 60
    assert fields["uncachedInputTokens"] == 200
    assert fields["cacheHitRate"] == 0.0


def test_stream_marks_missing_provider_cache_fields_as_unknown(monkeypatch):
    config = supported_relay_chat_config()
    recorded = []

    def backend(_payload):
        return iter(
            [
                {"choices": [{"delta": {"content": "ok"}}]},
                {"usage": {"input_tokens": 200, "output_tokens": 20}},
            ]
        )

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert events[-1].usage is not None
    fields = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")[1]["fields"]
    assert fields["usageObserved"] is True
    assert fields["cacheUsageObserved"] is False
    assert fields["cacheUsageMissingReason"] == "provider_cache_usage_missing"
    assert fields["cachedInputTokens"] == 0
    assert fields["uncachedInputTokens"] == 0
    assert fields["cacheHitRate"] == 0.0


def test_stream_preserves_explicit_deepseek_zero_cache_hit(monkeypatch):
    config = supported_relay_chat_config()
    recorded = []

    def backend(_payload):
        return iter(
            [
                {"choices": [{"delta": {"content": "ok"}}]},
                {
                    "usage": {
                        "prompt_tokens": 200,
                        "completion_tokens": 20,
                        "prompt_cache_hit_tokens": 0,
                        "prompt_cache_miss_tokens": 200,
                    },
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    list(client.stream_events([{"role": "user", "content": "ping"}]))

    fields = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")[1]["fields"]
    assert fields["cacheUsageObserved"] is True
    assert fields["cacheUsageMissingReason"] == ""
    assert fields["uncachedInputTokens"] == 200
    assert fields["cacheHitRate"] == 0.0


def test_stream_logs_prompt_cache_design_for_automatic_mode(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
            "llm.profiles.primary.prompt_cache.key": "vibelution-primary",
        }
    )
    recorded = []

    def backend(_payload):
        return iter(
            [
                {"type": "response.output_text.delta", "delta": "ok"},
                {
                    "type": "response.completed",
                    "response": {
                        "usage": {
                            "input_tokens": 160,
                            "output_tokens": 12,
                            "prompt_tokens_details": {"cached_tokens": 80},
                        }
                    },
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    content = [
        {"type": "text", "text": "stable-stream-prefix", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "dynamic-stream-suffix"},
    ]
    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "system", "content": content}]))

    assert [event.type for event in events] == ["text_delta", "done"]
    fields = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")[1]["fields"]
    assert fields["payloadShape"]["firstSystemCacheControlBlockCount"] == 0
    assert fields["promptCacheDesign"]["mode"] == "automatic"
    assert fields["promptCacheDesign"]["hasCacheControl"] is True
    assert fields["promptCacheDesign"]["firstSystemCacheControlBlockCount"] == 1
    assert fields["promptCacheDesign"]["firstSystemCacheableTextChars"] == len("stable-stream-prefix")
    assert fields["cachedInputTokens"] == 80


def test_stream_retries_without_usage_options_when_provider_rejects_them(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []
    payloads = []

    def backend(payload):
        payloads.append(dict(payload))
        if payload.get("stream_options"):
            raise Exception("400 bad_request unknown parameter: stream_options.include_usage")
        return iter([{"choices": [{"delta": {"content": "ok"}}]}])

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(
        client.stream_events(
            [{"role": "user", "content": "ping"}],
            metadata={
                "sessionId": "session-usage-downgrade",
                "turnId": "turn-usage-downgrade",
                "invocationId": "usage-downgrade",
                "llmSlot": "dialogue",
                "promptPurpose": "main_reply",
                "conversationBound": True,
            },
        )
    )

    assert [payload.get("stream_options") for payload in payloads] == [
        {"include_usage": True},
        None,
    ]
    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[0].text == "ok"
    event_codes = [item[0][1] for item in recorded]
    assert "llm.stream.usage_options_downgraded" in event_codes
    downgrade_event = next(
        item for item in recorded if item[0][1] == "llm.stream.usage_options_downgraded"
    )
    assert downgrade_event[1]["fields"]["sessionId"] == "session-usage-downgrade"
    assert downgrade_event[1]["fields"]["turnId"] == "turn-usage-downgrade"
    assert downgrade_event[1]["fields"]["invocationId"] == "usage-downgrade"
    assert downgrade_event[1]["fields"]["llmSlot"] == "dialogue"
    assert downgrade_event[1]["fields"]["promptPurpose"] == "main_reply"
    assert (
        downgrade_event[1]["fields"]["retryRequestMode"]
        == "wire_payload_without_stream_usage_options"
    )
    success_event = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")
    assert success_event[1]["fields"]["usageObserved"] is False
    assert success_event[1]["fields"]["usageMissingReason"] == "provider_usage_missing"
    assert success_event[1]["fields"]["protocol"]
    assert success_event[1]["fields"]["selectedProtocol"] == success_event[1]["fields"]["protocol"]
    assert success_event[1]["fields"]["payloadValidationResult"] == "passed"
    assert success_event[1]["fields"]["streamUsageOptionsDowngraded"] is True


def test_deepseek_stream_retries_without_usage_options_when_endpoint_rejects_them():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
        }
    )
    payloads = []

    def backend(payload):
        payloads.append(dict(payload))
        if payload.get("stream_options"):
            raise Exception("400 bad_request unknown parameter: stream_options.include_usage")
        return iter([{"choices": [{"delta": {"content": "ok"}}]}])

    events = list(
        LLMClient(config=config, backend=backend).stream_events(
            [{"role": "user", "content": "ping"}]
        )
    )

    assert [payload.get("stream_options") for payload in payloads] == [
        {"include_usage": True},
        None,
    ]
    assert [event.type for event in events] == ["text_delta", "done"]


def test_stream_final_chunk_exposes_usage_observation_for_ui():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {"choices": [{"delta": {"content": "ok"}}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 80,
                "completion_tokens": 10,
                "total_tokens": 90,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
        },
    ]

    client = LLMClient(config=config, backend=lambda _payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "ping"}]))

    assert [chunk.content for chunk in streamed] == ["ok", ""]
    usage_observation = streamed[-1].response_metadata["usage_observation"]
    assert usage_observation["input_tokens"] == 80
    assert usage_observation["cached_input_tokens"] == 40
    assert usage_observation["cache_read_input_tokens"] == 40
    assert usage_observation["cache_creation_input_tokens"] == 0
    assert usage_observation["uncached_input_tokens"] == 40
    assert usage_observation["cache_hit_rate"] == pytest.approx(0.5)
    assert streamed[0].response_metadata["llm_protocol"]["protocol"]
    assert streamed[-1].response_metadata["llm_protocol"]["payloadValidationResult"] == "passed"


def test_stream_chunk_merge_preserves_single_copy_of_response_metadata():
    first = AIMessageChunk(
        content="你",
        response_metadata={
            "provider": "xiaomi",
            "model": "mimo-v2.5-pro",
            "llm_protocol": {
                "protocol": "chat_completions",
                "payloadValidationResult": "passed",
            },
        },
    )
    second = AIMessageChunk(
        content="好",
        response_metadata={
            "provider": "xiaomi",
            "model": "mimo-v2.5-pro",
            "llm_protocol": {
                "protocol": "chat_completions",
                "payloadValidationResult": "passed",
            },
        },
    )

    merged = ResponseProcessor.merge_stream_chunk(first, second)

    assert merged.content == "你好"
    assert merged.response_metadata["provider"] == "xiaomi"
    assert merged.response_metadata["model"] == "mimo-v2.5-pro"
    assert merged.response_metadata["llm_protocol"]["protocol"] == "chat_completions"
    assert merged.response_metadata["llm_protocol"]["payloadValidationResult"] == "passed"


def test_stream_records_started_event_before_first_provider_chunk(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []

    def backend(_payload):
        def chunks():
            event_codes = [item[0][1] for item in recorded]
            assert "llm.stream.started" in event_codes
            yield {"choices": [{"delta": {"content": "ok"}}]}

        return chunks()

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert [event.type for event in events] == ["text_delta", "done"]
    started_events = [item for item in recorded if item[0][1] == "llm.stream.started"]
    assert len(started_events) == 1
    fields = started_events[0][1]["fields"]
    assert fields["messageCount"] == 1
    assert fields["toolCount"] == 0
    assert fields["runtimeRoute"] == "openai/qwen-32b-awq"
    assert fields["transport"] == "chat_completions"
    assert fields["baseUrlHost"] == "localhost"
    assert fields["stream"] is True
    assert fields["maxTokens"] == config.llm.get_profile("primary").max_output_tokens
    assert fields["payloadBuildMs"] >= 0
    assert fields["payloadSummaryMs"] >= 0
    assert fields["payloadPrepareMs"] >= fields["payloadBuildMs"]
    assert fields["payloadPrepareMs"] >= fields["payloadSummaryMs"]


def test_stream_records_safe_message_role_summary(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []

    def backend(_payload):
        return iter([{"choices": [{"delta": {"content": "ok"}}]}])

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(
        client.stream_events(
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "## 对话用户输入\nping"},
            ]
        )
    )

    assert [event.type for event in events] == ["text_delta", "done"]
    started = next(item for item in recorded if item[0][1] == "llm.stream.started")
    succeeded = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")
    for event in (started, succeeded):
        fields = event[1]["fields"]
        assert fields["messageRoles"] == ["system", "user"]
        assert fields["messageRoleCounts"] == {"system": 1, "user": 1}
        assert fields["promptCacheMessageHash"]
        assert fields["promptCacheMessageChunkHashes"]
        assert fields["promptCacheToolSchemaHash"]
        assert "system prompt" not in str(fields)


@pytest.mark.slow
def test_stream_limits_concurrent_calls_per_route(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    monkeypatch.setattr("core.llm.client._LLM_ROUTE_CONCURRENCY_LIMIT", 2)
    monkeypatch.setattr("core.llm.client._LLM_ROUTE_CONCURRENCY_GATES", {})
    entered = 0
    max_entered = 0
    entered_lock = threading.Lock()
    two_entered = threading.Event()
    release = threading.Event()

    def backend(_payload):
        nonlocal entered, max_entered
        with entered_lock:
            entered += 1
            max_entered = max(max_entered, entered)
            if entered == 2:
                two_entered.set()

        def chunks():
            try:
                assert release.wait(2.0)
                yield {"choices": [{"delta": {"content": "ok"}}]}
            finally:
                nonlocal entered
                with entered_lock:
                    entered -= 1

        return chunks()

    def run_stream():
        client = LLMClient(config=config, backend=backend)
        return [event.type for event in client.stream_events([{"role": "user", "content": "ping"}])]

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(run_stream) for _ in range(3)]
        assert two_entered.wait(1.0)
        assert max_entered == 2
        release.set()
        assert [future.result(timeout=2.0) for future in futures] == [
            ["text_delta", "done"],
            ["text_delta", "done"],
            ["text_delta", "done"],
        ]
    assert max_entered == 2


@pytest.mark.slow
def test_stream_waiting_for_route_slot_can_be_cancelled(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    monkeypatch.setattr("core.llm.client._LLM_ROUTE_CONCURRENCY_LIMIT", 1)
    monkeypatch.setattr("core.llm.client._LLM_ROUTE_CONCURRENCY_GATES", {})
    first_entered = threading.Event()
    release_first = threading.Event()
    backend_calls = 0

    def backend(_payload):
        nonlocal backend_calls
        backend_calls += 1
        first_entered.set()

        def chunks():
            assert release_first.wait(2.0)
            yield {"choices": [{"delta": {"content": "ok"}}]}

        return chunks()

    first_client = LLMClient(config=config, backend=backend)
    first_future_result = []

    def run_first():
        first_future_result.extend(event.type for event in first_client.stream_events([{"role": "user", "content": "first"}]))

    thread = threading.Thread(target=run_first)
    thread.start()
    assert first_entered.wait(1.0)

    cancelled = {"reason": ""}

    def cancel_checker():
        return cancelled["reason"]

    second_client = LLMClient(config=config, backend=backend)
    try:
        cancelled["reason"] = "操作者请求停止当前轮。"
        with llm_cancel_context(cancel_checker), pytest.raises(LLMError) as raised:
            list(second_client.stream_events([{"role": "user", "content": "second"}]))
    finally:
        release_first.set()
        thread.join(timeout=2.0)
    assert raised.value.category == "cancelled"
    assert backend_calls == 1
    assert first_future_result == ["text_delta", "done"]


def test_llm_route_concurrency_defaults_to_four_without_override(monkeypatch):
    monkeypatch.setattr("core.llm.client._LLM_ROUTE_CONCURRENCY_LIMIT", None)
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )

    assert config.llm.route_concurrency == 4
    assert _resolve_llm_route_concurrency_limit(config) == 4


@pytest.mark.parametrize("invalid_value", [0, -3, "abc", None, 2.5, True])
def test_llm_route_concurrency_invalid_values_fall_back_to_default(monkeypatch, invalid_value):
    monkeypatch.setattr("core.llm.client._LLM_ROUTE_CONCURRENCY_LIMIT", None)
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.route_concurrency": invalid_value,
        }
    )

    assert config.llm.route_concurrency == 4
    assert _resolve_llm_route_concurrency_limit(config) == 4


@pytest.mark.slow
def test_stream_route_concurrency_uses_configured_limit(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.route_concurrency": 6,
        }
    )
    monkeypatch.setattr("core.llm.client._LLM_ROUTE_CONCURRENCY_LIMIT", None)
    monkeypatch.setattr("core.llm.client._LLM_ROUTE_CONCURRENCY_GATES", {})
    assert _resolve_llm_route_concurrency_limit(config) == 6
    entered = 0
    max_entered = 0
    entered_lock = threading.Lock()
    six_entered = threading.Event()
    release = threading.Event()

    def backend(_payload):
        nonlocal entered, max_entered
        with entered_lock:
            entered += 1
            max_entered = max(max_entered, entered)
            if entered == 6:
                six_entered.set()

        def chunks():
            try:
                assert release.wait(5.0)
                yield {"choices": [{"delta": {"content": "ok"}}]}
            finally:
                nonlocal entered
                with entered_lock:
                    entered -= 1

        return chunks()

    def run_stream():
        client = LLMClient(config=config, backend=backend)
        return [event.type for event in client.stream_events([{"role": "user", "content": "ping"}])]

    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = [executor.submit(run_stream) for _ in range(7)]
        assert six_entered.wait(5.0)
        assert max_entered == 6
        release.set()
        assert [future.result(timeout=5.0) for future in futures] == [["text_delta", "done"]] * 7
    assert max_entered == 6


def test_stream_cancellation_closes_provider_iterator():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    cancelled = {"reason": "", "closed": False}

    class ClosableIterator:
        def __iter__(self):
            return self

        def __next__(self):
            if not cancelled["reason"]:
                cancelled["reason"] = "操作者请求停止当前轮。"
            return {"choices": [{"delta": {"content": "late-token"}}]}

        def close(self):
            cancelled["closed"] = True

    def cancel_checker():
        return cancelled["reason"]

    client = LLMClient(config=config, backend=lambda _payload: ClosableIterator())
    with llm_cancel_context(cancel_checker), pytest.raises(LLMError) as raised:
        list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert raised.value.category == "cancelled"
    assert cancelled["closed"] is True


def test_chat_completion_non_stream_cancellation_interrupts_blocked_backend_request(monkeypatch):
    import litellm

    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "glm-5.3-flash",
            "llm.profiles.primary.retry_policy.max_attempts": 5,
        }
    )
    entered = threading.Event()
    released = threading.Event()
    cancelled = {"reason": ""}
    observed = {"calls": 0, "error": None, "closed": False}

    class FakeHTTPHandler:
        def close(self):
            observed["closed"] = True
            released.set()

    handler = FakeHTTPHandler()

    def completion(**kwargs):
        observed["calls"] += 1
        assert kwargs["client"] is handler
        entered.set()
        assert released.wait(2.0)
        raise OSError("provider request interrupted")

    monkeypatch.setattr(litellm, "completion", completion, raising=False)
    monkeypatch.setattr(
        "core.llm.client._new_cancellable_completion_http_handler",
        lambda _payload: handler,
    )

    def run_request():
        try:
            client = LLMClient(config=config)
            with llm_cancel_context(
                lambda: cancelled["reason"],
                enable_chat_provider_abort=True,
            ):
                client._invoke_backend_with_retry(
                    {
                        "model": "glm-5.3-flash",
                        "messages": [{"role": "user", "content": "ping"}],
                        "stream": False,
                        "base_url": "https://pixel.try-chatapi.com/v1",
                    },
                    phase="completion",
                    event_code="test.completion",
                    message_count=1,
                    tool_count=0,
                )
        except Exception as exc:
            observed["error"] = exc

    thread = threading.Thread(target=run_request)
    thread.start()
    try:
        assert entered.wait(1.0)
        cancelled["reason"] = "挑战杯逻辑任务已达到截止时间。"
        thread.join(timeout=1.0)
        assert not thread.is_alive()
    finally:
        released.set()
        thread.join(timeout=2.0)

    assert isinstance(observed["error"], LLMError)
    assert observed["error"].category == "cancelled"
    assert observed["calls"] == 1
    assert observed["closed"] is True


def test_chat_completion_without_cancel_checker_does_not_inject_client(monkeypatch):
    import litellm

    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "glm-5.3-flash",
        }
    )
    observed = {}

    def completion(**kwargs):
        observed.update(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    monkeypatch.setattr(litellm, "completion", completion, raising=False)
    client = LLMClient(config=config)
    client._invoke_payload_once(
        {
            "model": "glm-5.3-flash",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
            "base_url": "https://pixel.try-chatapi.com/v1",
        }
    )

    assert "client" not in observed


def test_chat_completion_with_ordinary_empty_checker_does_not_inject_client(monkeypatch):
    """A normal Agent stop checker is cooperative-only unless Challenge opts in."""
    import litellm

    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "glm-5.3-flash",
        }
    )
    observed = {}

    def completion(**kwargs):
        observed.update(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    monkeypatch.setattr(litellm, "completion", completion, raising=False)
    client = LLMClient(config=config)
    with llm_cancel_context(lambda: "", enable_chat_provider_abort=False):
        client._invoke_payload_once(
            {
                "model": "glm-5.3-flash",
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
                "base_url": "https://pixel.try-chatapi.com/v1",
            }
        )

    assert "client" not in observed


def test_native_anthropic_route_does_not_inject_litellm_client(monkeypatch):
    """Native Anthropic Messages payloads must remain free of LiteLLM fields."""
    from types import SimpleNamespace

    client = LLMClient.__new__(LLMClient)
    client._backend = _default_completion_backend
    client.protocol_route = SimpleNamespace(adapter_id="anthropic_messages_native")
    payload = {
        "model": "claude-test",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "ping"}]}],
        "stream": True,
    }

    with llm_cancel_context(lambda: "", enable_chat_provider_abort=True):
        prepared, finish = client._prepare_cancellable_chat_stream(payload)
    try:
        assert prepared is payload
        assert "client" not in prepared
    finally:
        finish()


def _bare_llm_client(backend, adapter_id):
    """Build an unmounted LLMClient for cancellable-prepare unit tests."""

    client = LLMClient.__new__(LLMClient)
    client._backend = backend
    client._responses_backend = _default_responses_backend
    client.protocol_route = SimpleNamespace(adapter_id=adapter_id)
    client.role = "primary"
    client.profile_id = "primary"
    client.provider = SimpleNamespace(provider_id="default")
    client.profile = SimpleNamespace(model="glm-5.3-flash")
    client._cancellable_responses_http_handler_lock = threading.Lock()
    client._cancellable_responses_request_lock = threading.Lock()
    client._cancellable_completion_http_handler_lock = threading.Lock()
    client._cancellable_completion_request_lock = threading.Lock()
    return client


def _capture_llm_scene_events(monkeypatch):
    """Route _record_llm_scene_event into a list and reset the emit dedupe."""
    from core.llm import client as llm_client_module

    events = []
    monkeypatch.setattr(
        llm_client_module,
        "_record_llm_scene_event",
        lambda phase, event_code, **kwargs: events.append((phase, event_code, kwargs)),
    )
    llm_client_module._PROVIDER_ABORT_UNAVAILABLE_EMITTED.clear()
    return events


def test_native_anthropic_chat_stream_records_abort_unavailable_once(monkeypatch):
    """The native Anthropic adapter keeps cooperative cancel and records it."""
    from core.llm import client as llm_client_module

    events = _capture_llm_scene_events(monkeypatch)
    client = _bare_llm_client(_default_completion_backend, "anthropic_messages_native")
    payload = {
        "model": "claude-test",
        "messages": [{"role": "user", "content": "ping"}],
        "stream": True,
    }

    with llm_cancel_context(lambda: "", enable_chat_provider_abort=True):
        prepared, finish = client._prepare_cancellable_chat_stream(payload)
        try:
            assert prepared is payload
            assert "client" not in prepared
            # Repeated skips on the same transport+purpose stay bounded.
            client._prepare_cancellable_chat_stream(payload)
        finally:
            finish()

    assert [event_code for _phase, event_code, _kwargs in events] == [
        "llm.provider_abort_unavailable"
    ]
    _phase, _event_code, kwargs = events[0]
    assert kwargs["outcome"] == "degraded"
    assert kwargs["level"] == "warning"
    fields = kwargs["fields"]
    assert fields["transport"] == "chat_stream"
    assert fields["reason"] == "native_anthropic_adapter"
    assert fields["adapterId"] == "anthropic_messages_native"
    assert fields["purpose"] == "primary"


def test_non_default_chat_backend_records_abort_unavailable(monkeypatch):
    """A non-default Chat backend stays cooperative-only and says so once."""
    import litellm

    events = _capture_llm_scene_events(monkeypatch)
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "glm-5.3-flash",
        }
    )
    observed = {}

    def fake_backend(*args, **kwargs):
        if args:
            observed.update(args[0])
        observed.update(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    monkeypatch.setattr(litellm, "completion", fake_backend, raising=False)
    client = LLMClient(config=config)
    client._backend = fake_backend
    payload = {
        "model": "glm-5.3-flash",
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "base_url": "https://pixel.try-chatapi.com/v1",
    }

    with llm_cancel_context(lambda: "", enable_chat_provider_abort=True):
        response = client._invoke_payload_once(payload)

    # The call result is unchanged: the fake backend answered and no
    # cancellable client was injected.
    assert response["choices"][0]["message"]["content"] == "ok"
    assert "client" not in observed
    abort_events = [
        kwargs for _phase, event_code, kwargs in events
        if event_code == "llm.provider_abort_unavailable"
    ]
    assert len(abort_events) == 1
    fields = abort_events[0]["fields"]
    assert fields["transport"] == "non_stream_chat"
    assert fields["reason"] == "backend_not_default"
    assert fields["backendId"] == "fake_backend"
    assert fields["adapterId"]


def test_non_default_responses_backends_record_abort_unavailable(monkeypatch):
    """Responses stream and non-stream skips each record one bounded event."""
    from core.llm import client as llm_client_module

    events = _capture_llm_scene_events(monkeypatch)
    client = _bare_llm_client(_default_completion_backend, "openai_chat")
    client._responses_backend = object()
    stream_payload = {"model": "glm-5.3-flash", "input": "ping", "stream": True}
    non_stream_payload = {"model": "glm-5.3-flash", "input": "ping", "stream": False}

    with llm_cancel_context(lambda: ""):
        prepared_stream, finish = client._prepare_cancellable_responses_stream(
            stream_payload
        )
        try:
            assert prepared_stream is stream_payload
            assert "client" not in prepared_stream
            prepared_request, finish_request = client._prepare_cancellable_non_stream_request(
                non_stream_payload
            )
            try:
                assert prepared_request is non_stream_payload
                assert "client" not in prepared_request
            finally:
                finish_request()
        finally:
            finish()

    assert [event_code for _phase, event_code, _kwargs in events] == [
        "llm.provider_abort_unavailable",
        "llm.provider_abort_unavailable",
    ]
    transports = [kwargs["fields"]["transport"] for _p, _e, kwargs in events]
    assert transports == ["responses_stream", "non_stream_responses"]
    for _p, _e, kwargs in events:
        assert kwargs["fields"]["reason"] == "backend_not_default"
        assert kwargs["fields"]["backendId"] == "object"


def test_plain_cancel_context_neither_records_nor_injects(monkeypatch):
    """Without provider abort opt-in, cooperative-only stays silent."""
    from core.llm import client as llm_client_module

    events = _capture_llm_scene_events(monkeypatch)
    client = _bare_llm_client(object(), "openai_chat")
    payload = {
        "model": "glm-5.3-flash",
        "messages": [{"role": "user", "content": "ping"}],
        "stream": True,
    }

    with llm_cancel_context(lambda: "", enable_chat_provider_abort=False):
        prepared, finish = client._prepare_cancellable_chat_stream(payload)
        try:
            assert prepared is payload
        finally:
            finish()

    assert events == []
    assert llm_client_module._PROVIDER_ABORT_UNAVAILABLE_EMITTED == set()


def test_slow_cancel_watcher_cannot_reuse_handler_after_finish_timeout(monkeypatch):
    """A slow provider close fences the old handler before the next request."""
    import threading

    client = LLMClient.__new__(LLMClient)
    client._backend = _default_completion_backend
    client.protocol_route = SimpleNamespace(adapter_id="openai_chat")
    client._cancellable_completion_http_handler = None
    client._cancellable_completion_http_handler_lock = threading.Lock()
    client._cancellable_completion_stream_lock = threading.Lock()
    created_handlers = []
    close_entered = threading.Event()
    release_close = threading.Event()
    cancelled = {"reason": ""}

    class SlowHandler:
        def close(self):
            close_entered.set()
            assert release_close.wait(2.0)

    def new_handler(_payload):
        handler = SlowHandler()
        created_handlers.append(handler)
        return handler

    monkeypatch.setattr(
        "core.llm.client._new_cancellable_completion_http_handler",
        new_handler,
    )
    payload = {"messages": [{"role": "user", "content": "ping"}], "stream": True}
    with llm_cancel_context(
        lambda: cancelled["reason"],
        enable_chat_provider_abort=True,
    ):
        _prepared, finish = client._prepare_cancellable_chat_stream(payload)
        cancelled["reason"] = "challenge deadline"
        assert close_entered.wait(1.0)
        finish()
        assert client._cancellable_completion_http_handler is None

        # Release the old watcher only after its ownership has been fenced.
        cancelled["reason"] = ""
        _prepared_next, finish_next = client._prepare_cancellable_chat_stream(payload)
        assert len(created_handlers) == 2
        finish_next()

    release_close.set()
    # The old watcher is daemonized and must be allowed to finish its close;
    # the test's event also prevents it from touching the new handler.
    assert close_entered.is_set()


def test_cancellable_stream_rechecks_stop_after_provider_exhaustion():
    from core.llm import client as client_module

    state = {"reason": ""}

    class ExhaustedIterator:
        def __iter__(self):
            return self

        def __next__(self):
            state["reason"] = "challenge deadline"
            raise StopIteration

    stream = client_module._CancellableProviderStream(
        ExhaustedIterator(),
        lambda: None,
    )
    with llm_cancel_context(lambda: state["reason"]), pytest.raises(
        client_module.LLMCancelledError,
        match="challenge deadline",
    ):
        next(stream)


def test_chat_completion_stream_cancellation_interrupts_blocked_backend_request(monkeypatch):
    import litellm

    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "glm-5.3-flash",
            "llm.profiles.primary.retry_policy.max_attempts": 5,
        }
    )
    entered = threading.Event()
    released = threading.Event()
    cancelled = {"reason": ""}
    observed = {"calls": 0, "error": None, "closed": False}

    class FakeHTTPHandler:
        def close(self):
            observed["closed"] = True
            released.set()

    handler = FakeHTTPHandler()

    def completion(**kwargs):
        observed["calls"] += 1
        assert kwargs["client"] is handler
        entered.set()
        assert released.wait(2.0)
        raise OSError("provider request interrupted")

    monkeypatch.setattr(litellm, "completion", completion, raising=False)
    monkeypatch.setattr(
        "core.llm.client._new_cancellable_completion_http_handler",
        lambda _payload: handler,
    )

    def run_request():
        try:
            client = LLMClient(config=config)
            with llm_cancel_context(
                lambda: cancelled["reason"],
                enable_chat_provider_abort=True,
            ):
                list(client.stream_events([{"role": "user", "content": "ping"}]))
        except Exception as exc:
            observed["error"] = exc

    thread = threading.Thread(target=run_request)
    thread.start()
    try:
        assert entered.wait(1.0)
        cancelled["reason"] = "挑战杯逻辑任务已达到截止时间。"
        thread.join(timeout=1.0)
    finally:
        released.set()
        thread.join(timeout=2.0)

    assert isinstance(observed["error"], LLMError)
    assert observed["error"].category == "cancelled"
    assert observed["calls"] == 1
    assert observed["closed"] is True


def test_responses_stream_cancellation_interrupts_blocked_backend_request(monkeypatch):
    import litellm

    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-terra",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.retry_policy.max_attempts": 5,
        }
    )
    backend_entered = threading.Event()
    backend_released = threading.Event()
    stream_finished = threading.Event()
    cancelled = {"reason": ""}
    observed = {"calls": 0, "error": None}

    class FakeHTTPHandler:
        def close(self):
            backend_released.set()

    handler = FakeHTTPHandler()

    def responses(**kwargs):
        observed["calls"] += 1
        assert kwargs["client"] is handler
        backend_entered.set()
        assert backend_released.wait(2.0)
        raise OSError("provider request interrupted")

    monkeypatch.setattr(litellm, "responses", responses, raising=False)
    monkeypatch.setattr(
        "core.llm.client._new_cancellable_responses_http_handler",
        lambda _payload: handler,
        raising=False,
    )

    def cancel_checker():
        return cancelled["reason"]

    def run_stream():
        try:
            client = LLMClient(config=config)
            with llm_cancel_context(cancel_checker, enable_chat_provider_abort=False):
                list(client.stream_events([{"role": "user", "content": "ping"}]))
        except Exception as exc:
            observed["error"] = exc
        finally:
            stream_finished.set()

    thread = threading.Thread(target=run_stream)
    thread.start()
    try:
        assert backend_entered.wait(1.0), repr(observed["error"])
        cancelled["reason"] = "操作者请求停止当前轮。"
        assert stream_finished.wait(1.0)
    finally:
        backend_released.set()
        thread.join(timeout=2.0)

    assert isinstance(observed["error"], LLMError)
    assert observed["error"].category == "cancelled"
    assert observed["calls"] == 1


def test_responses_stream_reuses_cancellable_http_handler(monkeypatch):
    import litellm

    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-terra",
            "llm.profiles.primary.transport": "responses",
        }
    )
    created_handlers = []
    observed_clients = []

    class FakeHTTPHandler:
        def close(self):
            raise AssertionError("successful streams must not close the reusable client")

    def new_handler(_payload):
        handler = FakeHTTPHandler()
        created_handlers.append(handler)
        return handler

    def responses(**kwargs):
        observed_clients.append(kwargs["client"])
        return iter(
            [
                {"type": "response.output_text.delta", "delta": "ok"},
                {"type": "response.completed", "response": {"usage": {}}},
            ]
        )

    monkeypatch.setattr(litellm, "responses", responses, raising=False)
    monkeypatch.setattr(
        "core.llm.client._new_cancellable_responses_http_handler",
        new_handler,
    )

    client = LLMClient(config=config)
    with llm_cancel_context(lambda: ""):
        first = list(client.stream_events([{"role": "user", "content": "first"}]))
        second = list(client.stream_events([{"role": "user", "content": "second"}]))

    assert [event.type for event in first] == ["text_delta", "done"]
    assert [event.type for event in second] == ["text_delta", "done"]
    assert len(created_handlers) == 1
    assert observed_clients == [created_handlers[0], created_handlers[0]]


def test_new_cancellable_completion_http_handler_builds_credentialed_openai_client():
    """litellm 1.96.0 completion(client=) requires an openai.OpenAI instance."""
    import openai

    payload = {
        "api_key": "sk-cancellable-test",
        "base_url": "https://relay.example/v1/chat/completions",
        "timeout": 12.5,
        "messages": [{"role": "user", "content": "ping"}],
    }

    client = _new_cancellable_completion_http_handler(payload)

    assert isinstance(client, openai.OpenAI)
    assert client.api_key == "sk-cancellable-test"
    # attach happens before _default_completion_backend shifts the endpoint,
    # so the builder must repeat the /chat/completions -> service-root shift.
    assert str(client.base_url).rstrip("/") == "https://relay.example/v1"
    assert client.max_retries == 0
    assert client._client.timeout.read == 12.5
    client.close()


def test_new_cancellable_completion_http_handler_forwards_transport_options(monkeypatch):
    import httpx

    captured = {}
    real_client = httpx.Client

    class RecordingClient(real_client):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "Client", RecordingClient)

    client = _new_cancellable_completion_http_handler(
        {
            "api_key": "k",
            "base_url": "https://relay.example/v1",
            "timeout": 3,
            "ssl_verify": False,
            "messages": [],
        }
    )

    assert captured["timeout"] == 3
    assert captured["verify"] is False
    client.close()


def test_cancellable_client_cache_key_matches_shifted_endpoints():
    chat_full = {"api_key": "k", "base_url": "https://relay.example/v1/chat/completions", "messages": []}
    chat_root = {"api_key": "k", "base_url": "https://relay.example/v1", "messages": []}
    responses_full = {"api_key": "k", "base_url": "https://relay.example/v1/responses", "input": "x"}
    responses_root = {"api_key": "k", "base_url": "https://relay.example/v1", "input": "x"}

    assert _cancellable_client_cache_key(chat_full) == _cancellable_client_cache_key(chat_root)
    assert _cancellable_client_cache_key(responses_full) == _cancellable_client_cache_key(responses_root)
    # Chat and Responses live in separate slots, so an identical effective
    # endpoint may hash the same; only the credential must always diverge.
    assert _cancellable_client_cache_key(chat_full) != _cancellable_client_cache_key(dict(chat_full, api_key="other"))


def test_cancellable_client_slot_keyed_by_credentials_and_transport():
    """Cached cancellable clients must never be reused across credentials."""

    client = LLMClient.__new__(LLMClient)
    created = []
    closed = []

    class FakeClient:
        def close(self):
            closed.append(self)

    def factory(_payload):
        instance = FakeClient()
        created.append(instance)
        return instance

    lock = threading.Lock()
    base_payload = {
        "api_key": "key-a",
        "base_url": "https://relay.example/v1/chat/completions",
        "timeout": 10,
        "messages": [{"role": "user", "content": "ping"}],
    }

    with lock:
        first = client._get_or_create_cancellable_client(
            "_cancellable_completion_http_handler", factory, base_payload
        )
        second = client._get_or_create_cancellable_client(
            "_cancellable_completion_http_handler", factory, dict(base_payload)
        )
    assert first is second
    assert created == [first]
    assert closed == []

    # A rotated api key must rebuild and close the stale credential-bearing client.
    rotated = dict(base_payload, api_key="key-b")
    with lock:
        third = client._get_or_create_cancellable_client(
            "_cancellable_completion_http_handler", factory, rotated
        )
    assert third is not first
    assert created == [first, third]
    assert closed == [first]

    with lock:
        fourth = client._get_or_create_cancellable_client(
            "_cancellable_completion_http_handler", factory, dict(rotated)
        )
    assert fourth is third
    assert created == [first, third]

    # Transport option drift rebuilds too.
    with lock:
        fifth = client._get_or_create_cancellable_client(
            "_cancellable_completion_http_handler", factory, dict(rotated, timeout=99)
        )
    assert fifth is not third
    assert created == [first, third, fifth]
    assert closed == [first, third]


def test_new_cancellable_responses_http_handler_stays_litellm_http_handler():
    """litellm 1.96.0 responses(client=) contract is an HTTPHandler; an openai
    SDK client would fail its isinstance check and be silently ignored."""
    from litellm import HTTPHandler

    handler = _new_cancellable_responses_http_handler(
        {"api_key": "k", "base_url": "https://relay.example/v1/responses", "timeout": 7, "input": "x"}
    )

    assert isinstance(handler, HTTPHandler)
    assert not hasattr(handler, "api_key")
    handler.close()


def test_chat_non_stream_attaches_credentialed_openai_client(monkeypatch):
    """The cancellable chat attach must hand litellm an openai.OpenAI client."""
    import litellm
    import openai

    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "relay-secret",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "glm-5.3-flash",
        }
    )
    observed = {}

    def completion(**kwargs):
        observed.update(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    monkeypatch.setattr(litellm, "completion", completion, raising=False)
    client = LLMClient(config=config)
    with llm_cancel_context(lambda: "", enable_chat_provider_abort=True):
        client._invoke_payload_once(
            {
                "model": "glm-5.3-flash",
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
                "api_key": "relay-secret",
                "base_url": "https://pixel.try-chatapi.com/v1/chat/completions",
            }
        )

    attached = observed.get("client")
    assert isinstance(attached, openai.OpenAI)
    assert attached.api_key == "relay-secret"
    assert str(attached.base_url).rstrip("/") == "https://pixel.try-chatapi.com/v1"
    attached.close()


def test_chat_stream_reuses_keyed_cancellable_client(monkeypatch):
    """Same credentials reuse one openai client; the factory is not re-run."""

    import litellm

    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "glm-5.3-flash",
        }
    )
    observed_clients = []
    created = []

    class FakeClient:
        def close(self):
            raise AssertionError("successful same-key streams must not close the reusable client")

    def new_handler(_payload):
        instance = FakeClient()
        created.append(instance)
        return instance

    def completion(**kwargs):
        observed_clients.append(kwargs["client"])
        return iter(
            [
                {"choices": [{"delta": {"role": "assistant", "content": "ok"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ]
        )

    monkeypatch.setattr(litellm, "completion", completion, raising=False)
    monkeypatch.setattr("core.llm.client._new_cancellable_completion_http_handler", new_handler)

    client = LLMClient(config=config)
    with llm_cancel_context(lambda: "", enable_chat_provider_abort=True):
        first = list(client.stream_events([{"role": "user", "content": "first"}]))
        second = list(client.stream_events([{"role": "user", "content": "second"}]))

    assert any(event.type == "text_delta" for event in first)
    assert any(event.type == "text_delta" for event in second)
    assert len(created) == 1
    assert observed_clients == [created[0], created[0]]


def test_stream_does_not_replay_after_partial_output(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.retry_policy.max_attempts": 5,
        }
    )
    attempts = {"count": 0}

    def partial_then_failure():
        yield {"choices": [{"delta": {"content": "partial"}}]}
        raise TimeoutError("stream timeout")

    def backend(_payload):
        attempts["count"] += 1
        return partial_then_failure()

    monkeypatch.setattr("core.llm.client.time.sleep", lambda _seconds: None)

    client = LLMClient(config=config, backend=backend)
    with pytest.raises(LLMError) as raised:
        list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert raised.value.category == "timeout"
    assert attempts["count"] == 1


def test_invoke_does_not_retry_non_retryable_protocol_error(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.retry_policy.max_attempts": 5,
        }
    )
    attempts = {"count": 0}

    def backend(_payload):
        attempts["count"] += 1
        raise Exception("400 bad_request invalid params")

    monkeypatch.setattr("core.llm.client.time.sleep", lambda _seconds: None)

    client = LLMClient(config=config, backend=backend)
    with pytest.raises(LLMError) as raised:
        client.invoke([{"role": "user", "content": "ping"}])

    assert raised.value.category == "provider_protocol_error"
    assert attempts["count"] == 1


def test_stream_failure_records_category_without_masking_provider_error(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []

    def backend(_payload):
        raise Exception('400: One of "input" or "previous_response_id" must be provided.')

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)

    with pytest.raises(LLMError) as raised:
        list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert raised.value.category == "provider_protocol_error"
    assert 'One of "input"' in str(raised.value)
    assert recorded[-1][1]["message"] == "LLM stream failed before iterator: provider_protocol_error"
    assert recorded[-1][1]["fields"]["errorType"] == "provider_protocol_error"
    assert recorded[-1][1]["fields"]["messageRoles"] == ["user"]
    assert recorded[-1][1]["fields"]["protocol"]
    assert recorded[-1][1]["fields"]["protocolSource"]
    assert recorded[-1][1]["fields"]["payloadValidationResult"] == "passed"
    assert 'One of "input"' in recorded[-1][1]["fields"]["error"]


def test_supported_chat_payload_preserves_structured_content_blocks_by_default():
    config = supported_relay_chat_config()

    content = [{"type": "text", "text": "cached", "cache_control": {"type": "ephemeral"}}]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": content}])

    assert payload["model"] == "openai/deepseek-chat"
    assert payload["messages"][0]["content"] == content


def test_prompt_cache_disabled_strips_cache_control_and_allows_request():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.prompt_cache.mode": "disabled",
        }
    )

    content = [{"type": "text", "text": "plain", "cache_control": {"type": "ephemeral"}}]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": content}])

    assert payload["messages"][0]["content"] == [{"type": "text", "text": "plain"}]


def test_prompt_cache_unsupported_rejects_cache_control_without_backend_call():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.prompt_cache.mode": "unsupported",
        }
    )

    content = [{"type": "text", "text": "plain", "cache_control": {"type": "ephemeral"}}]
    backend_called = False

    def backend(_payload):
        nonlocal backend_called
        backend_called = True
        return {"choices": [{"message": {"role": "assistant", "content": "should-not-run"}}]}

    client = LLMClient(config=config, backend=backend)
    with pytest.raises(LLMError) as raised:
        client.invoke([{"role": "system", "content": content}])

    assert backend_called is False
    assert raised.value.category == "prompt_cache_unsupported"
    assert raised.value.retryable is False
    assert raised.value.details["provider_kind"] == "local"
    assert raised.value.details["prompt_cache_mode"] == "unsupported"


def test_deepseek_automatic_prompt_cache_declares_capability_without_openai_keys():
    """DeepSeek Context Caching is server-side; never inject OpenAI-only fields."""

    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-v4-flash",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
            "llm.profiles.primary.prompt_cache.key": "should-not-be-sent",
            "llm.profiles.primary.prompt_cache.retention": "24h",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": "stable"}, {"role": "user", "content": "hi"}])

    assert client.capabilities.supports_prompt_cache is True
    assert "prompt_cache_key" not in payload
    assert "prompt_cache_retention" not in payload
    assert client._last_payload_protocol_summary["promptCacheProviderStrategy"] == "deepseek_automatic"


def test_openai_compatible_automatic_prompt_cache_strips_cache_control_and_keeps_payload_valid():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
            "llm.profiles.primary.prompt_cache.key": "vibelution-primary",
            "llm.profiles.primary.prompt_cache.retention": "24h",
        }
    )

    content = [
        {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "dynamic"},
    ]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": content}])

    assert payload["model"] == "openai/gpt-5.5"
    assert payload["prompt_cache_key"] == "vibelution-primary"
    assert payload["prompt_cache_retention"] == "24h"
    assert "messages" not in payload
    assert payload["input"][0]["content"] == [
        {"type": "input_text", "text": "stable"},
        {"type": "input_text", "text": "dynamic"},
    ]
    assert client._last_payload_protocol_summary["promptCacheProviderStrategy"] == "openai_automatic_key"


def test_openai_automatic_prompt_cache_defaults_to_in_memory_retention_when_unset():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.openai.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-4o",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": "stable"}])

    assert payload["prompt_cache_key"].startswith("vibelution:openai:primary:")
    assert payload["prompt_cache_retention"] == "in_memory"
    assert client._last_payload_protocol_summary["promptCacheProviderStrategy"] == "openai_automatic_key"


def test_openai_gpt_5_5_automatic_prompt_cache_defaults_to_24h_retention():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": "stable"}])

    assert payload["prompt_cache_key"].startswith("vibelution:relay:primary:")
    assert payload["prompt_cache_retention"] == "24h"
    assert client._last_payload_protocol_summary["promptCacheProviderStrategy"] == "openai_automatic_key"


def test_automatic_prompt_cache_uses_stable_default_cache_key_when_not_configured():
    config = make_config(
        **{
            "llm.providers.default.kind": "xiaomi",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "mimo-v2.5-pro",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload_one = client._build_payload([{"role": "system", "content": "stable"}])
    payload_two = client._build_payload([{"role": "system", "content": "stable"}, {"role": "user", "content": "new"}])

    assert payload_one["prompt_cache_key"].startswith("vibelution:xiaomi:primary:")
    assert payload_two["prompt_cache_key"] == payload_one["prompt_cache_key"]
    assert payload_one["prompt_cache_retention"] == "in_memory"
    assert client._last_payload_protocol_summary["promptCacheProviderStrategy"] == "openai_compatible_automatic_key"


def test_dashscope_qwen_explicit_prompt_cache_preserves_cache_control_without_key():
    config = make_config(
        **{
            "llm.providers.default.kind": "aliyun",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3.6-plus",
            "llm.profiles.primary.prompt_cache.mode": "explicit_cache_control",
        }
    )

    content = [
        {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "dynamic"},
    ]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": content}])

    assert payload["model"] == "openai/qwen3.6-plus"
    assert "prompt_cache_key" not in payload
    assert payload["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert payload["messages"][0]["content"][1] == {"type": "text", "text": "dynamic"}
    assert client._last_payload_protocol_summary["selectedProtocol"] == "qwen_openai_compat"
    assert client._last_payload_protocol_summary["promptCacheProviderStrategy"] == "qwen_explicit_cache_control"


def test_dashscope_qwen_explicit_prompt_cache_adds_history_checkpoint_marker():
    config = make_config(
        **{
            "llm.providers.default.kind": "aliyun",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3.6-plus",
            "llm.profiles.primary.prompt_cache.mode": "explicit_cache_control",
        }
    )

    system_content = [
        {"type": "text", "text": "stable system", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "dynamic system"},
    ]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "history question"},
            {"role": "assistant", "content": "history answer"},
            {"role": "user", "content": "current question"},
        ]
    )

    assert payload["messages"][-2]["role"] == "assistant"
    assert payload["messages"][-2]["content"] == [
        {"type": "text", "text": "history answer", "cache_control": {"type": "ephemeral"}},
    ]
    assert payload["messages"][-1]["role"] == "user"
    assert payload["messages"][-1]["content"] == "current question"
    assert "metadata" not in payload["messages"][-1]
    cache_marker_count = sum(
        1
        for message in payload["messages"]
        for block in (message.get("content") if isinstance(message.get("content"), list) else [])
        if isinstance(block, dict) and block.get("cache_control")
    )
    assert cache_marker_count == 2
    assert client._last_payload_protocol_summary["payloadPolicyQwenPromptCacheMarkersAdded"] == 1


def test_dashscope_qwen_explicit_prompt_cache_respects_four_marker_limit():
    config = make_config(
        **{
            "llm.providers.default.kind": "aliyun",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3.6-plus",
            "llm.profiles.primary.prompt_cache.mode": "explicit_cache_control",
        }
    )
    marker = {"type": "ephemeral"}
    messages = [
        {"role": "system", "content": [{"type": "text", "text": "system", "cache_control": marker}]},
        {"role": "user", "content": [{"type": "text", "text": "turn 1", "cache_control": marker}]},
        {"role": "assistant", "content": [{"type": "text", "text": "turn 1 answer", "cache_control": marker}]},
        {"role": "user", "content": [{"type": "text", "text": "turn 2", "cache_control": marker}]},
        {"role": "user", "content": "current question"},
    ]

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(messages)

    assert payload["messages"][-1]["content"] == "current question"
    cache_marker_count = sum(
        1
        for message in payload["messages"]
        for block in (message.get("content") if isinstance(message.get("content"), list) else [])
        if isinstance(block, dict) and block.get("cache_control")
    )
    assert cache_marker_count == 4
    assert client._last_payload_protocol_summary["payloadPolicyQwenPromptCacheMarkersAdded"] == 0


def test_local_qwen_disabled_cache_does_not_preserve_cache_control():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://127.0.0.1:8081/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3-local",
            "llm.profiles.primary.prompt_cache.mode": "disabled",
        }
    )

    content = [
        {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "dynamic"},
    ]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": content}])

    assert "prompt_cache_key" not in payload
    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "stable"},
        {"type": "text", "text": "dynamic"},
    ]
    assert client._last_payload_protocol_summary["promptCacheProviderStrategy"] == "disabled"


def test_default_prompt_cache_key_partitions_by_agent_and_context():
    """默认 cache key 应按 agent.name 和 ContextVar 分片，避免多 session 共享同一 OpenAI cache shard。"""
    from core.llm.payload_builder import prompt_cache_partition_scope

    def make(agent_name: str = "alpha"):
        return make_config(
            **{
                "agent.name": agent_name,
                "llm.providers.default.kind": "xiaomi",
                "llm.providers.default.api_key": "test-key",
                "llm.providers.default.base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.profiles.primary.provider_id": "default",
                "llm.profiles.primary.model": "mimo-v2.5-pro",
                "llm.profiles.primary.prompt_cache.mode": "automatic",
            }
        )

    client_a = LLMClient(config=make("alpha"), backend=lambda payload: payload)
    client_b = LLMClient(config=make("beta"), backend=lambda payload: payload)
    key_alpha = client_a._build_payload([{"role": "system", "content": "stable"}])["prompt_cache_key"]
    key_beta = client_b._build_payload([{"role": "system", "content": "stable"}])["prompt_cache_key"]
    assert "alpha" in key_alpha and "alpha" not in key_beta
    assert "beta" in key_beta
    assert key_alpha != key_beta

    # ContextVar 分片：相同 agent 不同会话也能分片。
    with prompt_cache_partition_scope("conv-1"):
        key_conv1 = client_a._build_payload([{"role": "system", "content": "stable"}])["prompt_cache_key"]
    with prompt_cache_partition_scope("conv-2"):
        key_conv2 = client_a._build_payload([{"role": "system", "content": "stable"}])["prompt_cache_key"]
    assert "conv-1" in key_conv1
    assert "conv-2" in key_conv2
    assert key_conv1 != key_conv2 != key_alpha


def test_automatic_prompt_cache_logs_design_even_when_payload_strips_cache_control(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
            "llm.profiles.primary.prompt_cache.key": "vibelution-primary",
        }
    )
    recorded = []
    captured_payload = {}

    def backend(payload):
        captured_payload.update(payload)
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
        }

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    content = [
        {"type": "text", "text": "stable-prefix", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "dynamic-suffix"},
    ]
    client = LLMClient(config=config, backend=backend)
    client.invoke([{"role": "system", "content": content}])

    assert "messages" not in captured_payload
    assert captured_payload["input"][0]["content"] == [
        {"type": "input_text", "text": "stable-prefix"},
        {"type": "input_text", "text": "dynamic-suffix"},
    ]
    fields = next(item for item in recorded if item[0][1] == "llm.invoke.succeeded")[1]["fields"]
    assert fields["payloadShape"]["firstSystemCacheControlBlockCount"] == 0
    assert fields["promptCacheDesign"]["mode"] == "automatic"
    assert fields["promptCacheDesign"]["hasCacheControl"] is True
    assert fields["promptCacheDesign"]["firstSystemCacheControlBlockCount"] == 1
    assert fields["promptCacheDesign"]["firstSystemCacheableTextChars"] == len("stable-prefix")
    assert fields["cachedInputTokens"] == 40


def test_invoke_logs_prompt_cache_opportunity_when_cacheable_prefix_is_disabled(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "xiaomi",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "mimo-v2.5-pro",
            "llm.profiles.primary.prompt_cache.mode": "disabled",
        }
    )
    recorded = []

    def backend(_payload):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"input_tokens": 100, "output_tokens": 5},
        }

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    cacheable_text = "stable-prefix " * 400
    client = LLMClient(config=config, backend=backend)
    client.invoke(
        [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": cacheable_text, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": "dynamic-suffix"},
                ],
            }
        ]
    )

    fields = next(item for item in recorded if item[0][1] == "llm.invoke.succeeded")[1]["fields"]
    design = fields["promptCacheDesign"]
    assert design["mode"] == "disabled"
    assert design["cacheablePrefixWithoutEnabledMode"] is True
    assert design["cacheablePrefixOpportunityReason"] == "prompt_cache_mode_disabled"


def test_invoke_logs_prompt_cache_break_when_dynamic_system_suffix_precedes_history(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )
    recorded = []

    def backend(_payload):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"input_tokens": 100, "output_tokens": 5},
        }

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    client.invoke(
        [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "stable-prefix", "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": "dynamic-suffix"},
                ],
            },
            {"role": "user", "content": "history-user"},
            {"role": "assistant", "content": "history-assistant"},
            {"role": "user", "content": "current-user"},
        ]
    )

    fields = next(item for item in recorded if item[0][1] == "llm.invoke.succeeded")[1]["fields"]
    design = fields["promptCacheDesign"]
    assert design["cacheablePrefixBreakReason"] == "dynamic_system_suffix_before_history"
    assert design["cacheablePrefixEndsAt"] == "first_system_cache_control_block"
    assert design["dynamicSystemSuffixOutsideCachePrefix"] is True


def test_invoke_logs_prompt_cache_order_with_history_before_volatile_context(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )
    recorded = []

    def backend(_payload):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"input_tokens": 100, "output_tokens": 5},
        }

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    client.invoke(
        [
            {"role": "system", "content": "stable-system"},
            {"role": "user", "content": "history-user"},
            {"role": "assistant", "content": "history-assistant"},
            {"role": "system", "content": "## Agent Runtime Context\nvolatile"},
            {"role": "user", "content": "current-user"},
        ]
    )

    fields = next(item for item in recorded if item[0][1] == "llm.invoke.succeeded")[1]["fields"]
    diagnostics = fields["promptCacheOrderDiagnostics"]
    assert diagnostics["firstVolatileContextIndex"] == 3
    assert diagnostics["lastUserIndex"] == 4
    assert diagnostics["stableHistoryBeforeVolatileChars"] == len("history-user") + len("history-assistant")
    assert diagnostics["volatileContextBeforeHistory"] is False
    assert diagnostics["stableCachePrefixMessageCount"] == 3
    assert diagnostics["stableCachePrefixChars"] == len("stable-system") + len("history-user") + len("history-assistant")
    assert diagnostics["stableCachePrefixEndReason"] == "before_volatile_context"
    assert diagnostics["stableCachePrefixHash"]
    assert fields["messageOrderProfile"][3]["role"] == "system"
    assert fields["messageOrderProfile"][3]["volatileContext"] is True


def test_invoke_logs_prompt_cache_order_regression_when_volatile_precedes_history(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )
    recorded = []

    def backend(_payload):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"input_tokens": 100, "output_tokens": 5},
        }

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    client.invoke(
        [
            {"role": "system", "content": "stable-system"},
            {"role": "system", "content": "## Agent Runtime Context\nvolatile"},
            {"role": "user", "content": "history-user"},
            {"role": "assistant", "content": "history-assistant"},
            {"role": "user", "content": "current-user"},
        ]
    )

    fields = next(item for item in recorded if item[0][1] == "llm.invoke.succeeded")[1]["fields"]
    diagnostics = fields["promptCacheOrderDiagnostics"]
    assert diagnostics["firstVolatileContextIndex"] == 1
    assert diagnostics["lastUserIndex"] == 4
    assert diagnostics["volatileContextBeforeHistoryChars"] == len("## Agent Runtime Context\nvolatile")
    assert diagnostics["volatileContextBeforeHistory"] is True


def test_openai_compatible_payload_preserves_image_blocks_for_chat_completions():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "chat_completions",
            "llm.profiles.primary.supports_image_input": True,
        }
    )

    content = [
        {"type": "text", "text": "看看这张图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": content}])

    assert payload["messages"][0]["content"] == content


def test_responses_transport_converts_image_blocks_to_input_image():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.supports_image_input": True,
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看看这张图"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            }
        ]
    )

    assert payload["model"] == "openai/gpt-5.5"
    assert "messages" not in payload
    assert payload["input"][0]["content"] == [
        {"type": "input_text", "text": "看看这张图"},
        {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
    ]


def test_responses_transport_forwards_images_when_capability_is_unknown():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "custom-multimodal-model",
            "llm.profiles.primary.transport": "responses",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            }
        ]
    )

    assert client.capabilities.supports_image_input is None
    assert payload["input"][0]["content"] == [
        {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
    ]


def test_openai_codex_model_uses_explicit_provider_context_window():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.openai.com/v1",
            "llm.providers.default.context_window": 123456,
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.3-codex",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)

    assert client.resolved_spec.context_window == 123456
    assert client.resolved_spec.provider_details["context_window_source"] == "provider_config"


def test_openai_gpt_5_5_uses_explicit_provider_context_window():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.openai.com/v1",
            "llm.providers.default.context_window": 123456,
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)

    assert client.resolved_spec.context_window == 123456
    assert client.resolved_spec.provider_details["context_window_source"] == "provider_config"


def test_tool_schema_is_sanitized_before_payload():
    class ArgsSchema:
        @staticmethod
        def model_json_schema():
            return {
                "title": "Args",
                "type": "object",
                "$defs": {"Ignored": {"type": "string"}},
                "properties": {
                    "file path": {
                        "title": "Path",
                        "type": "string",
                        "description": "target",
                        "examples": ["a.py"],
                    }
                },
                "required": ["file path"],
            }

    class Tool:
        name = "read file!*"
        description = "x" * 2000
        args_schema = ArgsSchema

    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "read"}], tools=[Tool()])
    function = payload["tools"][0]["function"]

    assert function["name"] == "read_file"
    assert len(function["description"]) == 1024
    assert "title" not in function["parameters"]
    assert "$defs" not in function["parameters"]
    assert "examples" not in function["parameters"]["properties"]["file path"]


def test_stream_merges_tool_call_argument_deltas():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": "{\"path\""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ": \"agent.py\"}"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "read"}]))

    tool_chunks = [chunk for chunk in streamed if chunk.tool_calls]
    assert len(tool_chunks) == 1
    assert tool_chunks[0].tool_calls[0]["id"] == "call_1"
    assert tool_chunks[0].tool_calls[0]["name"] == "read_file"
    assert tool_chunks[0].tool_calls[0]["args"] == {"path": "agent.py"}
    assert streamed[-1].additional_kwargs["turn_outcome"].kind == "tool_calls"


def test_stream_chunks_merge_without_duplicate_tool_calls():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": "{\"path\""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ": \"agent.py\"}"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    full_chunk = None
    for chunk in client.stream([{"role": "user", "content": "read"}]):
        full_chunk = ResponseProcessor.merge_stream_chunk(full_chunk, chunk)

    assert len(full_chunk.tool_calls) == 1
    assert full_chunk.tool_calls[0]["id"] == "call_1"
    assert full_chunk.tool_calls[0]["name"] == "read_file"


def test_stream_events_expose_tool_calls_only_after_finalization():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {"choices": [{"delta": {"content": "读"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": "{\"path\""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ": \"agent.py\"}"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    events = list(client.stream_events([{"role": "user", "content": "read"}]))

    assert [event.type for event in events] == ["text_delta", "tool_call_final", "done"]
    assert events[0].text == "读"
    assert events[1].tool_calls[0].id == "call_1"
    assert events[1].tool_calls[0].arguments == {"path": "agent.py"}


def test_stream_exposes_reasoning_deltas_without_polluting_content():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
        }
    )
    chunks = [
        {"choices": [{"delta": {"reasoning_content": "先看"}}]},
        {"choices": [{"delta": {"reasoning_content": "日志"}}]},
        {"choices": [{"delta": {"content": "结论"}}]},
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "read"}]))

    assert streamed[0].content == ""
    assert streamed[0].additional_kwargs["reasoning_content_delta"] == "先看"
    assert streamed[1].additional_kwargs["reasoning_content_delta"] == "日志"
    assert streamed[2].content == "结论"


def test_stream_converts_cumulative_reasoning_prefixes_to_deltas():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-reasoner",
        }
    )
    chunks = [
        {"choices": [{"delta": {"reasoning": "先看"}}]},
        {"choices": [{"delta": {"reasoning": "先看日志"}}]},
        {"choices": [{"delta": {"reasoning": "先看日志"}}]},
        {"choices": [{"delta": {"content": "结论"}}]},
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "read"}]))

    reasoning_deltas = [
        chunk.additional_kwargs.get("reasoning_content_delta")
        for chunk in streamed
        if chunk.additional_kwargs.get("reasoning_content_delta")
    ]
    assert reasoning_deltas == ["先看", "日志"]
    assert "".join(str(chunk.content) for chunk in streamed if chunk.content) == "结论"


def test_stream_exposes_reasoning_aliases_and_strips_think_tags_from_content():
    config = make_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3-local",
        }
    )
    chunks = [
        {"choices": [{"delta": {"reasoning": "先看"}}]},
        {"choices": [{"delta": {"thinking": "日志"}}]},
        {"choices": [{"delta": {"content": "<think>不要进回答</think>结论"}}]},
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "read"}]))

    assert streamed[0].additional_kwargs["reasoning_content_delta"] == "先看"
    assert streamed[1].additional_kwargs["reasoning_content_delta"] == "日志"
    assert streamed[2].additional_kwargs["reasoning_content_delta"] == "不要进回答"
    assert streamed[3].content == "结论"


def test_stream_splits_reasoning_when_think_tags_span_chunks():
    config = make_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3-local",
        }
    )
    chunks = [
        {"choices": [{"delta": {"content": "<think>"}}]},
        {"choices": [{"delta": {"content": "先看"}}]},
        {"choices": [{"delta": {"content": "日志"}}]},
        {"choices": [{"delta": {"content": "</think>"}}]},
        {"choices": [{"delta": {"content": "结论"}}]},
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "read"}]))

    assert [chunk.additional_kwargs.get("reasoning_content_delta") for chunk in streamed[:2]] == ["先看", "日志"]
    assert streamed[2].content == "结论"


def test_stream_events_record_reasoning_source_summary(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-reasoner",
        }
    )
    chunks = [
        {"choices": [{"delta": {"reasoning": "先看"}}]},
        {"choices": [{"delta": {"content": "结论"}}]},
    ]
    recorded = []
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    events = list(client.stream_events([{"role": "user", "content": "read"}]))

    assert [event.type for event in events] == ["reasoning_delta", "text_delta", "done"]
    assert events[0].provider_payload == {"reasoning_source": "reasoning"}
    success_event = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")
    assert success_event[1]["fields"]["reasoningDeltaCount"] == 1
    assert success_event[1]["fields"]["reasoningChars"] == 2
    assert success_event[1]["fields"]["reasoningSources"] == ["reasoning"]
    assert success_event[1]["fields"]["reasoningObserved"] is True


def test_stream_events_drop_incomplete_tool_calls_with_empty_name():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_empty",
                                "function": {"arguments": "{\"limit\": 10}"},
                            }
                        ]
                    }
                }
            ]
        }
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    events = list(client.stream_events([{"role": "user", "content": "read"}]))

    assert [event.type for event in events] == ["done"]
    streamed = list(client.stream([{"role": "user", "content": "read"}]))
    assert len(streamed) == 1
    assert streamed[0].content == ""
    assert streamed[0].tool_calls == []
    assert streamed[0].additional_kwargs["turn_outcome"].kind == "incomplete"


def test_transcript_replay_duplicate_tool_call_id_regression():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
        }
    )
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_function_8euvktt1r7y4_1",
                                "function": {"name": "get_git_status_summary_tool", "arguments": "{}"},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 1,
                                "id": "call_function_8euvktt1r7y4_2",
                                "function": {"arguments": "{\"limit\": 10}"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    full_chunk = None
    for chunk in client.stream([{"role": "user", "content": "开始自主进化"}]):
        full_chunk = ResponseProcessor.merge_stream_chunk(full_chunk, chunk)

    assert len(full_chunk.tool_calls) == 1
    assert full_chunk.tool_calls[0]["id"] == "call_function_8euvktt1r7y4_1"
    assert full_chunk.tool_calls[0]["name"] == "get_git_status_summary_tool"


def test_bad_request_wrapped_as_connection_error_is_protocol_error():
    error = Exception("APIConnectionError: MinimaxException - bad_request_error invalid params, chat content is empty (2013)")

    normalized = classify_exception(error)

    assert normalized.category == "empty_content_error"
    assert normalized.retryable is False


def test_connection_refused_wrapped_as_internal_server_error_is_network_error():
    error = Exception(
        "litellm.InternalServerError: InternalServerError: OpenAIException - Connection error. "
        "httpx.ConnectError: [WinError 10061] 由于目标计算机积极拒绝，无法连接。"
    )

    normalized = classify_exception(error)

    assert normalized.category == "network_error"
    assert normalized.retryable is True


def test_bad_gateway_html_with_css_400_percent_is_retryable_server_error():
    error = Exception(
        "provider_protocol_error: litellm.BadGatewayError: BadGatewayError: "
        "OpenAIException - <html><head><title>网站请求超时</title>"
        "<style>body{background-size:400% 400%}</style></head>"
        "<body><p>502</p><h1>回源请求被中断</h1></body></html>"
    )

    normalized = classify_exception(error)

    assert normalized.category == "server_error"
    assert normalized.retryable is True


def test_llm_provider_proxy_env_disables_environment_proxy_when_project_proxy_off(monkeypatch):
    config = make_config(
        **{
            "network.proxy_enabled": False,
            "llm.providers.default.kind": "xiaomi",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "mimo-v2.5-pro",
        }
    )
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7890")

    with _llm_provider_proxy_env(config, "https://token-plan-cn.xiaomimimo.com/v1"):
        assert os.environ.get("HTTP_PROXY") is None
        assert os.environ.get("HTTPS_PROXY") is None
        assert os.environ.get("ALL_PROXY") is None

    assert os.environ.get("HTTP_PROXY") == "http://127.0.0.1:7890"
    assert os.environ.get("HTTPS_PROXY") == "http://127.0.0.1:7890"
    assert os.environ.get("ALL_PROXY") == "socks5://127.0.0.1:7890"


def test_llm_provider_proxy_env_uses_configured_project_proxy(monkeypatch):
    config = make_config(
        **{
            "network.proxy_enabled": True,
            "network.proxy_url": "http://127.0.0.1:7897",
            "llm.providers.default.kind": "xiaomi",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "mimo-v2.5-pro",
        }
    )
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)

    with _llm_provider_proxy_env(config, "https://token-plan-cn.xiaomimimo.com/v1"):
        assert os.environ.get("HTTP_PROXY") == "http://127.0.0.1:7897"
        assert os.environ.get("HTTPS_PROXY") == "http://127.0.0.1:7897"
        assert os.environ.get("ALL_PROXY") == "http://127.0.0.1:7897"

    assert os.environ.get("HTTP_PROXY") == "http://127.0.0.1:7890"
    assert os.environ.get("HTTPS_PROXY") is None
    assert os.environ.get("ALL_PROXY") is None


def test_duplicate_tool_call_error_classified_as_tool_protocol_error():
    error = Exception("invalid params, duplicate tool_call id: call_function_8euvktt1r7y4_1")

    normalized = classify_exception(error)

    assert normalized.category == "tool_protocol_error"
    assert normalized.retryable is False


def test_recovery_policy_disables_tools_for_tool_protocol_error():
    error = Exception("invalid params, duplicate tool_call id: call_function_8euvktt1r7y4_1")

    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert decision.category == "tool_protocol_error"
    assert decision.action == "disable_tools_and_retry_without_streaming"
    assert decision.disable_tools is True
    assert decision.disable_streaming is True
    assert decision.stop_current_turn is False


def test_recovery_policy_fail_fast_for_tool_calling_capability_error():
    error = LLMError("capability_error", "profile `primary` 不支持 tool calling", retryable=False)

    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert decision.category == "capability_error"
    assert decision.action == "fail_fast"
    assert decision.disable_tools is False
    assert decision.disable_streaming is False
    assert decision.stop_current_turn is True
    assert decision.user_message == "profile `primary` 不支持 tool calling"


def test_recovery_policy_uses_longer_backoff_for_rate_limit():
    error = Exception("429 rate limit exceeded")

    decision = plan_recovery(error, attempt=2, max_attempts=5)

    assert decision.category == "rate_limit"
    assert decision.action == "retry_after_backoff"
    assert decision.wait_seconds == 20
    assert decision.stop_current_turn is False


def test_recovery_policy_requests_context_compression():
    error = Exception("maximum context length exceeded")

    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert decision.category == "context_length_error"
    assert decision.action == "compress_context"
    assert decision.request_context_compression is True
    assert decision.stop_current_turn is False


def test_recovery_routing_prefers_no_tool_non_streaming_profile():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.providers.plain.kind": "local",
            "llm.providers.plain.requires_api_key": False,
            "llm.providers.plain.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
            "llm.profiles.fallback_plain.provider_id": "plain",
            "llm.profiles.fallback_plain.model": "qwen-32b-awq",
            "llm.profiles.fallback_plain.streaming": False,
            "llm.profiles.fallback_plain.tool_calling_mode": "disabled",
        }
    )

    fallback = select_recovery_profile(
        config,
        current_profile_id="primary",
        action="disable_tools_and_retry_without_streaming",
    )

    assert fallback == "fallback_plain"


def test_effective_route_identity_distinguishes_profiles_without_secrets():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "primary-secret",
            "llm.providers.default.base_url": "https://relay.example.test/v1/",
            "llm.providers.backup.kind": "local",
            "llm.providers.backup.requires_api_key": False,
            "llm.providers.backup.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-luna",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.fallback_backup.provider_id": "backup",
            "llm.profiles.fallback_backup.model": "qwen-32b-awq",
            "llm.profiles.fallback_backup.transport": "chat_completions",
        }
    )
    primary = LLMClient(config=config, profile_id="primary", backend=lambda payload: payload)
    fallback = LLMClient(config=config, profile_id="fallback_backup", backend=lambda payload: payload)

    assert primary.effective_route_identity() == primary.effective_route_identity()
    assert primary.effective_route_identity() != fallback.effective_route_identity()
    assert primary.effective_route_id() != fallback.effective_route_id()
    assert "primary-secret" not in repr(primary.effective_route_identity())
    assert "primary-secret" not in primary.effective_route_id()


def test_recovery_decision_attaches_fallback_profile():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.providers.backup.kind": "local",
            "llm.providers.backup.requires_api_key": False,
            "llm.providers.backup.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
            "llm.profiles.fallback_backup.provider_id": "backup",
            "llm.profiles.fallback_backup.model": "qwen-32b-awq",
            "llm.profiles.fallback_backup.streaming": False,
            "llm.profiles.fallback_backup.tool_calling_mode": "disabled",
        }
    )
    decision = plan_recovery(
        Exception("invalid params, duplicate tool_call id: call_1"),
        attempt=1,
        max_attempts=5,
    )

    enriched = attach_recovery_fallback(
        decision,
        config=config,
        current_profile_id="primary",
    )

    assert enriched.fallback_profile_id == "fallback_backup"


def test_capability_error_recovery_does_not_attach_fallback_profile():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.providers.backup.kind": "local",
            "llm.providers.backup.requires_api_key": False,
            "llm.providers.backup.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
            "llm.profiles.fallback_backup.provider_id": "backup",
            "llm.profiles.fallback_backup.model": "qwen-32b-awq",
            "llm.profiles.fallback_backup.streaming": False,
            "llm.profiles.fallback_backup.tool_calling_mode": "disabled",
        }
    )
    decision = plan_recovery(
        LLMError("capability_error", "profile `primary` 不支持 tool calling", retryable=False),
        attempt=1,
        max_attempts=5,
    )

    enriched = attach_recovery_fallback(
        decision,
        config=config,
        current_profile_id="primary",
    )

    assert enriched.action == "fail_fast"
    assert enriched.fallback_profile_id is None


def test_provider_retry_does_not_use_compression_profile_as_fallback():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.remote_main.kind": "relay",
            "llm.providers.remote_main.api_key": "test-key",
            "llm.providers.remote_main.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.compression.provider_id": "remote_main",
            "llm.profiles.compression.model": "gpt-5.5",
            "llm.profiles.compression.streaming": False,
        }
    )

    fallback = select_recovery_profile(
        config,
        current_profile_id="primary",
        action="retry_with_backoff",
    )

    assert fallback is None


def test_responses_websocket_states_publish_turn_visible_transport_statuses(monkeypatch):
    recorded_statuses: list[tuple[str, dict]] = []
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "core.llm.client._publish_llm_status_event",
        lambda status, **fields: recorded_statuses.append((status, fields)),
    )
    client = object.__new__(LLMClient)
    client.provider = SimpleNamespace(provider_id="ai-pixel", kind="ai-pixel")
    client.profile = SimpleNamespace(model="gpt-5.6-terra")
    client.profile_id = "primary"

    client._record_responses_websocket_state(
        "fallback",
        {
            "reasonType": "ConnectionClosedError",
            "closeCode": 1013,
            "closeReason": "no available account",
            "fallbackTransport": "http",
        },
    )
    client._record_responses_websocket_state(
        "recovered",
        {"fallbackTransport": "http"},
    )

    assert [status for status, _fields in recorded_statuses] == [
        "transport_fallback",
        "transport_recovered",
    ]
    assert recorded_statuses[0][1]["category"] == "provider_transport_unavailable"
    assert recorded_statuses[0][1]["closeCode"] == 1013
    assert recorded_statuses[0][1]["closeReason"] == "no available account"
    assert recorded_statuses[1][1]["fallbackTransport"] == "http"


def test_usage_observation_accepts_provider_usage_objects():
    class UsageObject:
        prompt_tokens = 100
        completion_tokens = 20
        total_tokens = 120
        prompt_tokens_details = {"cached_tokens": 32}

    response = SimpleNamespace(usage=UsageObject())
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
        }
    )
    client = LLMClient(config=config, backend=lambda _payload: response)

    usage = client._usage_from_response(response, latency_ms=7)

    assert usage.input_tokens == 100
    assert usage.output_tokens == 20
    assert usage.cached_input_tokens == 32
    assert usage.provider_raw_usage["prompt_tokens_details"] == {"cached_tokens": 32}


def test_deepseek_usage_object_preserves_prompt_cache_hit_and_miss_tokens():
    usage_object = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        prompt_cache_hit_tokens=64,
        prompt_cache_miss_tokens=36,
    )
    response = SimpleNamespace(usage=usage_object)
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
        }
    )

    usage = LLMClient(config=config, backend=lambda _payload: response)._usage_from_response(
        response,
        latency_ms=7,
    )

    assert usage.input_tokens == 100
    assert usage.cached_input_tokens == 64
    assert usage.provider_raw_usage["prompt_cache_hit_tokens"] == 64
    assert usage.provider_raw_usage["prompt_cache_miss_tokens"] == 36


def test_context_recovery_uses_larger_context_profile_only():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.context_window": 32768,
            "llm.providers.large.kind": "local",
            "llm.providers.large.requires_api_key": False,
            "llm.providers.large.context_window": 131072,
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.long_context.provider_id": "large",
            "llm.profiles.long_context.model": "qwen-plus",
        }
    )

    fallback = select_recovery_profile(
        config,
        current_profile_id="primary",
        action="compress_context",
    )

    current_window = config.llm.get_provider(config.llm.get_profile("primary").provider_id).context_window
    selected_window = config.llm.get_provider(config.llm.get_profile(fallback).provider_id).context_window
    assert fallback is not None
    assert selected_window > current_window


def _chain_history_with_call_id(call_id: str) -> list:
    return [
        {"role": "user", "content": "读取资料"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "ctx_tool", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "content": "first page"},
    ]


def _tool_call_outcome(call_id: str, *, item_id: str = "item-1") -> TurnOutcome:
    identity = CanonicalItemIdentity(
        session_id="session-dedupe",
        turn_id="turn-dedupe",
        invocation_id="invocation-dedupe",
        iteration=1,
        item_id=item_id,
    )
    call = CanonicalToolCall(identity=identity, call_id=call_id, name="ctx_tool")
    return TurnOutcome(
        kind="tool_calls",
        identity=identity,
        tool_calls=(call,),
        pending_tool_call_ids=(call_id,),
    )


def test_response_tool_call_replaying_chain_id_is_renamed_before_journal():
    from core.llm.client import _dedupe_outcome_tool_calls_against_chain

    history = _chain_history_with_call_id("call_dup")
    outcome = _tool_call_outcome("call_dup")

    renamed = _dedupe_outcome_tool_calls_against_chain(outcome, history)

    assert renamed.tool_calls[0].call_id == "call_dup-resp-1"
    assert renamed.pending_tool_call_ids == ("call_dup-resp-1",)
    # The provider item identity stays traceable; the raw outcome is untouched.
    assert renamed.tool_calls[0].identity.item_id == "item-1"
    assert outcome.tool_calls[0].call_id == "call_dup"
    assert outcome.pending_tool_call_ids == ("call_dup",)


def test_response_tool_call_renames_are_unique_across_repeated_collisions():
    from dataclasses import replace

    from core.llm.client import _dedupe_outcome_tool_calls_against_chain

    history = _chain_history_with_call_id("call_dup")
    identity = CanonicalItemIdentity(
        session_id="session-dedupe",
        turn_id="turn-dedupe",
        invocation_id="invocation-dedupe",
        iteration=1,
        item_id="item-1",
    )
    second_identity = replace(identity, item_id="item-2")
    outcome = TurnOutcome(
        kind="tool_calls",
        identity=identity,
        tool_calls=(
            CanonicalToolCall(identity=identity, call_id="call_dup", name="ctx_tool"),
            CanonicalToolCall(identity=second_identity, call_id="call_dup", name="ctx_tool"),
        ),
        pending_tool_call_ids=("call_dup", "call_dup"),
    )

    renamed = _dedupe_outcome_tool_calls_against_chain(outcome, history)

    assert [call.call_id for call in renamed.tool_calls] == [
        "call_dup-resp-1",
        "call_dup-resp-2",
    ]
    assert renamed.pending_tool_call_ids == ("call_dup-resp-1", "call_dup-resp-2")


def test_response_tool_call_replays_of_renamed_id_do_not_stack_suffixes():
    from core.llm.client import (
        _dedupe_outcome_tool_calls_against_chain,
        _next_response_tool_call_id,
    )

    # History already contains the previous response rename "-resp-1".
    history = _chain_history_with_call_id("call_dup") + [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_dup-resp-1",
                    "type": "function",
                    "function": {"name": "ctx_tool", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_dup-resp-1", "content": "second page"},
    ]

    replayed_original = _dedupe_outcome_tool_calls_against_chain(
        _tool_call_outcome("call_dup"), history
    )
    assert replayed_original.tool_calls[0].call_id == "call_dup-resp-2"

    # The model replaying the renamed id gets a fresh suffix, never a stack.
    replayed_rename = _dedupe_outcome_tool_calls_against_chain(
        _tool_call_outcome("call_dup-resp-1"), history
    )
    assert replayed_rename.tool_calls[0].call_id == "call_dup-resp-2"
    assert _next_response_tool_call_id("call_dup-resp-1", set()) == "call_dup-resp-1"


def test_response_tool_call_rename_follows_results_and_skips_clean_outcomes():
    from dataclasses import replace

    from core.llm.client import _dedupe_outcome_tool_calls_against_chain
    from core.llm.types import CanonicalToolResult

    history = _chain_history_with_call_id("call_dup")
    identity = CanonicalItemIdentity(
        session_id="session-dedupe",
        turn_id="turn-dedupe",
        invocation_id="invocation-dedupe",
        iteration=1,
        item_id="item-1",
    )
    clean = TurnOutcome(
        kind="tool_calls",
        identity=identity,
        tool_calls=(CanonicalToolCall(identity=identity, call_id="call_fresh", name="ctx_tool"),),
    )
    assert _dedupe_outcome_tool_calls_against_chain(clean, history) is clean

    outcome = TurnOutcome(
        kind="tool_calls",
        identity=identity,
        tool_calls=(CanonicalToolCall(identity=identity, call_id="call_dup", name="ctx_tool"),),
        tool_results=(
            CanonicalToolResult(
                identity=identity,
                call_id="call_dup",
                tool_name="ctx_tool",
                output={"page": 1},
            ),
        ),
        pending_tool_call_ids=("call_dup",),
    )

    renamed = _dedupe_outcome_tool_calls_against_chain(outcome, history)

    assert renamed.tool_results[0].call_id == "call_dup-resp-1"
    assert renamed.tool_results[0].output == {"page": 1}


def test_invoke_outcome_renames_replayed_tool_call_id_against_request_chain():
    sent_payloads = []

    def backend(payload):
        sent_payloads.append(payload)
        if len(sent_payloads) == 1:
            return {
                "id": "resp_replay_dup",
                "status": "completed",
                "output": [
                    {
                        "id": "function_replay_dup",
                        "type": "function_call",
                        "call_id": "call_dup",
                        "name": "ctx_tool",
                        "arguments": "{}",
                    }
                ],
            }
        return {
            "id": "resp_final",
            "status": "completed",
            "output": [
                {
                    "id": "message_final",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "done"}],
                }
            ],
        }

    from tests.test_llm_responses_replay_continuation import _config as replay_config

    client = LLMClient(config=replay_config(), backend=backend)
    history = _chain_history_with_call_id("call_dup")
    outcome = client.invoke_outcome(history, metadata=_invocation_metadata())

    # The replayed "call_dup" never escapes the client: journal and next
    # request see "call_dup-resp-1" with consistent pairing.
    assert [call.call_id for call in outcome.tool_calls] == ["call_dup-resp-1"]

    assistant = client.project_outcome_message(outcome)
    assert assistant.tool_calls[0]["id"] == "call_dup-resp-1"

    tool_message = {"role": "tool", "tool_call_id": "call_dup-resp-1", "content": "next page"}
    followup = client.invoke_outcome(
        [*history, assistant, tool_message],
        metadata=_invocation_metadata(),
    )
    assert followup.kind == "final_answer"
    # The second request passed the projector with unique ids and a paired chain.
    assert len(sent_payloads) == 2


def _invocation_metadata() -> dict:
    return {
        "sessionId": "session-dedupe",
        "turnId": "turn-dedupe",
        "invocationId": "invocation-dedupe",
        "iteration": 0,
    }


def test_chat_truncated_tool_arguments_resend_same_request_and_recover(monkeypatch):
    """端到端：首次流式 tool arguments 截断 → 同请求重发 → 第二次完整下发。"""

    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "glm-4.6",
            "llm.profiles.primary.transport": "chat_completions",
            "llm.profiles.primary.streaming": True,
            "llm.profiles.primary.retry_policy.max_attempts": 2,
        }
    )
    attempts = {"count": 0}
    published_statuses = []

    def chat_backend(payload):
        attempts["count"] += 1
        if attempts["count"] == 1:
            # Relay 流尾截断：arguments 只到一半就收到 finish_reason。
            return iter(
                [
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call-1",
                                            "function": {
                                                "name": "source_collection_stage_writeback_tool",
                                                "arguments": '{"teamId": "research-team", "result_json": "{\"sum',
                                            },
                                        }
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ]
                    },
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
                ]
            )
        return iter(
            [
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-1",
                                        "function": {
                                            "name": "source_collection_stage_writeback_tool",
                                            "arguments": '{"teamId": "research-team", "result_json": "{}"}',
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                },
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ]
        )

    monkeypatch.setattr("core.llm.client._sleep_with_llm_cancel_check", lambda _seconds: None)
    monkeypatch.setattr(
        "core.llm.client._publish_llm_status_event",
        lambda status, **fields: published_statuses.append((status, fields)),
    )
    client = LLMClient(config=config, backend=chat_backend)

    events = list(client.stream_events([{"role": "user", "content": "写回阶段结果"}]))

    # 第一次尝试零下发（无 text/tool_call_final/done），第二次完整成功。
    assert attempts["count"] == 2
    tool_finals = [event for event in events if event.type == "tool_call_final"]
    assert len(tool_finals) == 1
    call = tool_finals[0].tool_calls[0]
    assert call.name == "source_collection_stage_writeback_tool"
    assert call.arguments == {"teamId": "research-team", "result_json": "{}"}
    done_events = [event for event in events if event.type == "done"]
    assert len(done_events) == 1
    outcome = done_events[0].provider_payload["turn_outcome"]
    assert outcome.kind == "tool_calls"
    assert outcome.pending_tool_call_ids == ("call-1",)
    assert [status for status, _fields in published_statuses if status in {"retrying", "retry_recovered"}] == [
        "retrying",
        "retry_recovered",
    ]


def test_chat_truncated_tool_arguments_with_partial_output_does_not_retry(monkeypatch):
    """已有可见输出下发时不重发（避免重复输出），以 incomplete 终态收尾。"""

    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "glm-4.6",
            "llm.profiles.primary.transport": "chat_completions",
            "llm.profiles.primary.streaming": True,
            "llm.profiles.primary.retry_policy.max_attempts": 2,
        }
    )
    attempts = {"count": 0}

    def chat_backend(payload):
        attempts["count"] += 1
        return iter(
            [
                {"choices": [{"index": 0, "delta": {"content": "部分输出"}, "finish_reason": None}]},
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-1",
                                        "function": {"name": "lookup", "arguments": '{"query": "trunc'},
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                },
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ]
        )

    monkeypatch.setattr("core.llm.client._sleep_with_llm_cancel_check", lambda _seconds: None)
    client = LLMClient(config=config, backend=chat_backend)

    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert attempts["count"] == 1
    assert [event.type for event in events] == ["text_delta", "done"]
    outcome = events[-1].provider_payload["turn_outcome"]
    assert outcome.kind == "incomplete"
    assert outcome.error == "chat.finish.tool_arguments_unparsable"
