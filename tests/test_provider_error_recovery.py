from __future__ import annotations

from pathlib import Path

import pytest

from config import Settings
from core.llm.client import LLMClient
from core.llm.errors import classify_exception
from core.llm.recovery import plan_recovery
from core.ui.chat_state import CHAT_STATE_VERSION, save_chat_state
from core.web.services import session_service

pytestmark = pytest.mark.serial


def _make_config(**kwargs):
    return Settings(None, **kwargs).config


def _seed_session(root: Path) -> None:
    save_chat_state(
        root,
        {
            "version": CHAT_STATE_VERSION,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-21T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "Agent 会话",
                    "updated_at": "2026-05-21T12:00:00",
                    "last_turn_status": "ready",
                    "messages": [],
                    "active_task": None,
                }
            ],
        },
    )


def test_upstream_bad_gateway_is_retryable_server_error():
    class BadGatewayError(Exception):
        pass

    error = BadGatewayError(
        'litellm.BadGatewayError: BadGatewayError: OpenAIException - {"error":{"message":"Upstream request failed","type":"upstream_error"}}'
    )

    normalized = classify_exception(error)
    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert normalized.category == "server_error"
    assert normalized.retryable is True
    assert decision.category == "server_error"
    assert decision.action == "retry_with_backoff"
    assert decision.wait_seconds > 0
    assert decision.stop_current_turn is False


def test_ssl_eof_is_retryable_network_error():
    error = Exception(
        "litellm.InternalServerError: InternalServerError: OpenAIException - "
        "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)"
    )

    normalized = classify_exception(error)
    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert normalized.category == "network_error"
    assert normalized.retryable is True
    assert decision.category == "network_error"
    assert decision.action == "retry_with_backoff"


def test_incomplete_chunked_read_is_retryable_network_error():
    error = Exception(
        "litellm.MidStreamFallbackError: litellm.APIConnectionError: "
        "OpenAIException - peer closed connection without sending complete message body "
        "(incomplete chunked read)"
    )

    normalized = classify_exception(error)
    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert normalized.category == "network_error"
    assert normalized.retryable is True
    assert decision.category == "network_error"
    assert decision.action == "retry_with_backoff"


def test_service_temporarily_unavailable_is_retryable_server_error():
    error = Exception(
        'litellm.ServiceUnavailableError: ServiceUnavailableError: OpenAIException - '
        '{"error":{"message":"Service temporarily unavailable","type":"api_error"}}'
    )

    normalized = classify_exception(error)
    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert normalized.category == "server_error"
    assert normalized.retryable is True
    assert decision.category == "server_error"
    assert decision.action == "retry_with_backoff"


def test_stream_upstream_failure_records_retryable_server_error(monkeypatch):
    config = _make_config(
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
        raise Exception(
            'litellm.BadGatewayError: BadGatewayError: OpenAIException - {"error":{"message":"Upstream request failed","type":"upstream_error"}}'
        )

    monkeypatch.setattr("core.llm.client.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)

    try:
        list(client.stream_events([{"role": "user", "content": "ping"}]))
    except Exception as exc:
        raised = exc
    else:  # pragma: no cover - defensive assertion path
        raise AssertionError("expected upstream stream failure")

    assert raised.category == "server_error"
    assert raised.retryable is True
    messages = [item[1]["message"] for item in recorded]
    assert "LLM stream failed before iterator: server_error" in messages
    assert recorded[-1][1]["message"] == "LLM stream fallback invoke failed: server_error"
    assert recorded[-1][1]["fields"]["errorType"] == "server_error"
    assert recorded[-1][1]["fields"]["retryable"] is True


def test_session_failed_result_sanitizes_provider_upstream_error(tmp_path, monkeypatch):
    _seed_session(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )

    provider_error = (
        'provider_protocol_error: litellm.BadGatewayError: BadGatewayError: OpenAIException - '
        '{"error":{"message":"Upstream request failed","type":"upstream_error"}}'
    )

    class FailingResultAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": provider_error,
                "raw_output": provider_error,
                "error": provider_error,
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: FailingResultAgent())
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: session_service._run_session_turn(context))

    payload = session_service.submit_session_message("session-live", "继续当前对话")

    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "继续当前对话"
    assert payload["messages"][-1]["role"] == "assistant"
    assert "模型服务上游暂时失败" in payload["messages"][-1]["content"]
    assert payload["messages"][-1]["metadata"]["kind"] == "turn_error"
    assert payload["messages"][-1]["metadata"]["providerFailure"] is True
    assert payload["lastTurnError"] is not None
    assert payload["lastTurnError"]["errorType"] == "provider_upstream_error"
    assert payload["lastTurnError"]["recoverable"] is True
    assert "模型服务上游暂时失败" in payload["lastTurnError"]["message"]
    assert "litellm.BadGatewayError" not in payload["lastTurnError"]["message"]
    assert "provider_protocol_error" not in payload["lastTurnError"]["message"]
    assert "litellm.BadGatewayError" not in payload["messages"][-1]["content"]
    assert "provider_protocol_error" not in payload["messages"][-1]["content"]
    assert payload["currentPhase"] == "failed"


def test_session_llm_runtime_diagnostics_fill_provider_failure_metadata():
    result = {
        "status": "failed",
        "llm_failure": {
            "category": "server_error",
            "provider": "",
            "model": "",
        },
    }

    session_service._attach_session_llm_runtime_diagnostics(
        result,
        {
            "llmModelId": "gpt_5_5_gpt_5_5",
            "runtimeProfileId": "primary",
            "providerId": "inline_model_gpt_5_5_gpt_5_5",
            "providerKind": "openai_compatible",
            "model": "gpt-5.5",
            "llmWarnings": ["ignored"],
        },
    )

    assert result["metadata"]["llmModelId"] == "gpt_5_5_gpt_5_5"
    assert result["metadata"]["providerId"] == "inline_model_gpt_5_5_gpt_5_5"
    assert "llmWarnings" not in result["metadata"]
    assert result["llm_failure"]["provider"] == "inline_model_gpt_5_5_gpt_5_5"
    assert result["llm_failure"]["providerId"] == "inline_model_gpt_5_5_gpt_5_5"
    assert result["llm_failure"]["providerKind"] == "openai_compatible"
    assert result["llm_failure"]["model"] == "gpt-5.5"
    assert result["llm_failure"]["llmModelId"] == "gpt_5_5_gpt_5_5"
    assert result["llm_failure"]["runtimeProfileId"] == "primary"


def test_session_detail_dedupes_same_turn_error_messages(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": CHAT_STATE_VERSION,
            "active_conversation_id": "session-live",
            "updated_at": "2026-06-08T14:19:02",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "Agent 会话",
                    "updated_at": "2026-06-08T14:19:02",
                    "last_turn_status": "failed",
                    "messages": [
                        {
                            "role": "user",
                            "content": "审查主对话和子对话",
                            "timestamp": "2026-06-08T14:14:10",
                        },
                        {
                            "role": "assistant",
                            "content": "模型服务上游暂时失败，本轮没有完成。",
                            "timestamp": "2026-06-08T14:19:02",
                            "metadata": {
                                "kind": "turn_error",
                                "turnId": "turn-1",
                                "providerFailure": True,
                            },
                        },
                        {
                            "role": "assistant",
                            "content": "模型服务上游暂时失败，本轮没有完成。",
                            "timestamp": "2026-06-08T14:19:02",
                            "metadata": {
                                "kind": "turn_error",
                                "turnId": "turn-1",
                                "providerFailure": True,
                            },
                        },
                    ],
                    "active_task": None,
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    payload = session_service.get_session_detail("session-live")

    turn_error_messages = [
        message
        for message in payload["messages"]
        if message.get("metadata", {}).get("kind") == "turn_error"
    ]
    assert len(turn_error_messages) == 1
    assert payload["messages"][-1]["content"] == "模型服务上游暂时失败，本轮没有完成。"


def test_session_provider_failure_circuit_breaker_stops_continuation_and_logs_event(tmp_path, monkeypatch):
    _seed_session(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: type("Cfg", (), {"max_continuation_turns": 4})(),
    )
    recorded_events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    provider_error = (
        'server_error: litellm.ServiceUnavailableError: ServiceUnavailableError: OpenAIException - '
        '{"error":{"message":"Service temporarily unavailable","type":"api_error"}}'
    )
    calls = []

    class ProviderFailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            return {
                "status": "failed",
                "summary": provider_error,
                "raw_output": provider_error,
                "error": provider_error,
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
                "llm_failure": {
                    "category": "server_error",
                    "retryable": True,
                    "recovery_action": "retry_with_backoff",
                    "attempts": 5,
                    "max_attempts": 5,
                    "consecutive_failures": 1,
                    "stop_reason": "provider unavailable",
                },
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailingAgent())
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: session_service._run_session_turn(context))

    payload = session_service.submit_session_message("session-live", "请用一句话回复 ping")

    assert calls == ["请用一句话回复 ping"]
    assert payload["currentPhase"] == "failed"
    assert payload["lastTurnError"]["errorType"] == "provider_upstream_error"
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run is not None
    assert latest_run["status"] == "failed"
    assert latest_run["errorType"] == "provider_upstream_error"

    circuit_events = [
        kwargs
        for args, kwargs in recorded_events
        if len(args) >= 3 and args[2] == "conversation.turn_circuit_breaker"
    ]
    assert circuit_events
    fields = circuit_events[-1]["fields"]
    assert fields["llmFailureCategory"] == "server_error"
    assert fields["attempts"] == 5
    assert fields["maxAttempts"] == 5
    assert fields["continuationTurn"] == 1


def test_session_provider_failure_uses_llm_failure_metadata_when_summary_is_sanitized(tmp_path, monkeypatch):
    _seed_session(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: type("Cfg", (), {"max_continuation_turns": 4})(),
    )
    recorded_events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    calls = []

    class ProviderFailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            return {
                "status": "failed",
                "summary": "当前轮执行失败，请检查模型槽位或日志。",
                "raw_output": "当前轮执行失败，请检查模型槽位或日志。",
                "error": "server_error: litellm.ServiceUnavailableError",
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
                "llm_failure": {
                    "category": "server_error",
                    "retryable": True,
                    "recovery_action": "retry_with_backoff",
                    "message": "server_error: provider 服务异常",
                    "attempts": 5,
                    "max_attempts": 5,
                    "consecutive_failures": 1,
                    "stop_reason": "provider unavailable",
                },
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailingAgent())
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: session_service._run_session_turn(context))

    payload = session_service.submit_session_message("session-live", "请用一句话回复 ping")

    assert calls == ["请用一句话回复 ping"]
    assert payload["currentPhase"] == "failed"
    assert payload["lastTurnError"]["errorType"] == "provider_upstream_error"
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run is not None
    assert latest_run["status"] == "failed"
    assert latest_run["errorType"] == "provider_upstream_error"
    assert "litellm.ServiceUnavailableError" in latest_run["error"]
    assert sum(1 for args, _kwargs in recorded_events if len(args) >= 3 and args[2] == "conversation.turn_circuit_breaker") == 1


def test_session_exception_failure_sanitizes_provider_error_and_logs_raw(tmp_path, monkeypatch):
    _seed_session(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )

    provider_error = (
        'provider_protocol_error: litellm.BadGatewayError: BadGatewayError: OpenAIException - '
        '{"error":{"message":"Upstream request failed","type":"upstream_error"}}'
    )

    class RaisingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            raise RuntimeError(provider_error)

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: RaisingAgent())
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: session_service._run_session_turn(context))

    payload = session_service.submit_session_message("session-live", "继续当前对话")

    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-1]["role"] == "assistant"
    assert "模型服务上游暂时失败" in payload["messages"][-1]["content"]
    assert payload["messages"][-1]["metadata"]["kind"] == "turn_error"
    assert payload["lastTurnError"] is not None
    assert payload["lastTurnError"]["errorType"] == "provider_upstream_error"
    assert "模型服务上游暂时失败" in payload["lastTurnError"]["message"]
    assert "litellm.BadGatewayError" not in payload["lastTurnError"]["message"]
    assert "litellm.BadGatewayError" not in payload["messages"][-1]["content"]

    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run is not None
    assert latest_run["status"] == "failed"
    assert latest_run["errorType"] == "provider_upstream_error"
    assert "litellm.BadGatewayError" in latest_run["error"]


def test_session_provider_failure_preserves_partial_visible_reply(tmp_path, monkeypatch):
    _seed_session(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )

    provider_error = (
        'provider_protocol_error: litellm.BadGatewayError: BadGatewayError: OpenAIException - '
        '{"error":{"message":"Upstream request failed","type":"upstream_error"}}'
    )

    class PartialThenFailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": "我已经完成了前半段审查，发现会话入口需要保留错误消息。",
                "raw_output": "我已经完成了前半段审查，发现会话入口需要保留错误消息。",
                "error": provider_error,
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: PartialThenFailingAgent())
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: session_service._run_session_turn(context))

    payload = session_service.submit_session_message("session-live", "继续当前对话")

    assert payload["messages"][-3]["role"] == "user"
    assert payload["messages"][-2]["role"] == "assistant"
    assert payload["messages"][-2]["content"] == "我已经完成了前半段审查，发现会话入口需要保留错误消息。"
    assert payload["messages"][-1]["role"] == "assistant"
    assert "模型服务上游暂时失败" in payload["messages"][-1]["content"]
    assert payload["messages"][-1]["metadata"]["kind"] == "turn_error"


def test_session_completed_result_with_provider_error_is_persisted_as_assistant_message(tmp_path, monkeypatch):
    _seed_session(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )

    provider_error = (
        'provider_protocol_error: litellm.BadRequestError: DeepseekException - '
        '{"error":{"message":"The `reasoning_content` in the thinking mode must be passed back to the API.",'
        '"type":"invalid_request_error"}}'
    )

    class CompletedButErroredAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。",
                "raw_output": "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。",
                "error": provider_error,
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: CompletedButErroredAgent())
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: session_service._run_session_turn(context))

    payload = session_service.submit_session_message("session-live", "继续当前对话")

    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-1]["role"] == "assistant"
    assert "模型服务上游暂时失败" in payload["messages"][-1]["content"]
    assert payload["messages"][-1]["metadata"]["kind"] == "turn_error"
    assert payload["lastTurnError"] is not None
    assert payload["lastTurnError"]["errorType"] == "provider_protocol_error"
    assert "模型服务上游暂时失败" in payload["lastTurnError"]["message"]
    assert "reasoning_content" not in payload["messages"][-1]["content"]

    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run is not None
    assert latest_run["status"] == "failed"
    assert latest_run["errorType"] == "provider_protocol_error"
    assert "reasoning_content" in latest_run["error"]


def test_session_history_seed_keeps_provider_error_but_filters_recovery_notices(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": CHAT_STATE_VERSION,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-23T00:10:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "Agent 会话",
                    "updated_at": "2026-05-23T00:10:00",
                    "last_turn_status": "ready",
                    "messages": [
                        {
                            "role": "user",
                            "content": "现在审查一下整个项目,然后向我汇报结果",
                            "timestamp": "2026-05-23T00:00:00",
                        },
                        {
                            "role": "assistant",
                            "content": "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。",
                            "timestamp": "2026-05-23T00:01:00",
                        },
                        {
                            "role": "assistant",
                            "content": "上一轮运行已被中断，当前会话已恢复为可继续状态。",
                            "timestamp": "2026-05-23T00:02:00",
                        },
                        {
                            "role": "assistant",
                            "content": "结果已经审查完了，结论是：项目结构健康。",
                            "timestamp": "2026-05-23T00:03:00",
                        },
                    ],
                    "active_task": None,
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )
    captured = {}

    class CapturingAgent:
        def seed_chat_history(self, messages):
            captured["history"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续汇报。",
                "raw_output": "继续汇报。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: CapturingAgent())
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: session_service._run_session_turn(context))

    payload = session_service.submit_session_message("session-live", "继续")

    assert payload["messages"][-1]["role"] == "assistant"
    assert captured["history"] == [
        {
            "role": "user",
            "content": "现在审查一下整个项目,然后向我汇报结果",
            "metadata": {"schemaVersion": 1, "sourceIndex": 0},
        },
        {
            "role": "assistant",
            "content": "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。",
            "metadata": {"schemaVersion": 1, "sourceIndex": 1},
        },
        {
            "role": "assistant",
            "content": "结果已经审查完了，结论是：项目结构健康。",
            "metadata": {"schemaVersion": 1, "sourceIndex": 2},
        },
    ]
