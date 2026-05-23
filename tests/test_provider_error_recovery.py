from __future__ import annotations

from pathlib import Path

from config import Settings
from core.llm.client import LLMClient
from core.llm.errors import classify_exception
from core.llm.recovery import plan_recovery
from core.ui.chat_state import CHAT_STATE_VERSION, save_chat_state
from core.web.services import session_service


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
    assert recorded[-1][1]["message"] == "LLM stream failed before iterator: server_error"
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

    assert payload["messages"][-1]["role"] == "user"
    assert payload["messages"][-1]["content"] == "继续当前对话"
    assert payload["lastTurnError"] is not None
    assert payload["lastTurnError"]["errorType"] == "provider_upstream_error"
    assert payload["lastTurnError"]["recoverable"] is True
    assert "模型服务上游暂时失败" in payload["lastTurnError"]["message"]
    assert "litellm.BadGatewayError" not in payload["lastTurnError"]["message"]
    assert "provider_protocol_error" not in payload["lastTurnError"]["message"]
    assert all("模型服务上游暂时失败" not in message["content"] for message in payload["messages"])
    assert payload["currentPhase"] == "failed"


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

    assert payload["messages"][-1]["role"] == "user"
    assert payload["lastTurnError"] is not None
    assert payload["lastTurnError"]["errorType"] == "provider_upstream_error"
    assert "模型服务上游暂时失败" in payload["lastTurnError"]["message"]
    assert "litellm.BadGatewayError" not in payload["lastTurnError"]["message"]
    assert all("模型服务上游暂时失败" not in message["content"] for message in payload["messages"])

    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run is not None
    assert latest_run["status"] == "failed"
    assert latest_run["errorType"] == "provider_upstream_error"
    assert "litellm.BadGatewayError" in latest_run["error"]


def test_session_completed_result_with_provider_error_is_not_persisted_as_assistant_message(tmp_path, monkeypatch):
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

    assert payload["messages"][-1]["role"] == "user"
    assert payload["lastTurnError"] is not None
    assert payload["lastTurnError"]["errorType"] == "provider_protocol_error"
    assert "模型服务上游暂时失败" in payload["lastTurnError"]["message"]
    assert all("模型服务上游暂时失败" not in message["content"] for message in payload["messages"])

    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run is not None
    assert latest_run["status"] == "failed"
    assert latest_run["errorType"] == "provider_protocol_error"
    assert "reasoning_content" in latest_run["error"]


def test_session_history_seed_filters_provider_error_and_recovery_notices(tmp_path, monkeypatch):
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
            "timestamp": "2026-05-23T00:00:00",
        },
        {
            "role": "assistant",
            "content": "结果已经审查完了，结论是：项目结构健康。",
            "timestamp": "2026-05-23T00:03:00",
        },
    ]
