import asyncio
import base64
import json
import queue
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.evaluation.chat_next_state_signals import append_chat_next_state_signal
from core.infrastructure.tool_execution_scope import register_current_tool_future
from core.prompt_manager.prompt_manager import PromptManager
from core.chat.slash_commands import parse_skill_slash_command
from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_DELTA_COMMITTED,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ASSISTANT_PARTIAL,
    EVENT_TOOL_RESULT,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    load_conversation_events,
)
from core.ui.chat_state import load_chat_state, save_chat_state
from core.runtime_manager import constants as runtime_manager_constants
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import cli_agents as cli_agent_routes
from core.web.services import (
    agent_directory_service,
    chat_review_service,
    runtime_service,
    session_service,
    skill_service,
    self_evolution_control_service,
    self_evolution_service,
    supervised_control_service,
    supervised_worktree_evolution_service,
)
from core.web.services.session import stream_capture
from core.web.services.session import worker as session_worker
from tests.helpers.chat_turn_harness import wait_for_matching_event
from tests.helpers.web_chat_state import (
    _bind_seeded_session_agent,
    _bind_seeded_submittable_agent,
    _read_next_state_signals,
    _resolve_seeded_assistant_tool_calls,
    _seed_chat_state,
)

pytestmark = pytest.mark.serial


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


CONTEXT_PREPARE_LIVE_MESSAGE = "正在准备对话上下文...\n正在读取当前会话、绑定 Agent、工具权限和可恢复的上轮现场。"


_RETIRED_ASSISTANT_ENVELOPE_FIELDS = (
    "content",
    "thought",
    "streaming",
    "streamStage",
    "toolCalls",
    "feedbackEvents",
    "timelineItems",
    "codexTranscript",
)


def _assistant_turn_items(message: dict, item_type: str = "") -> list[dict]:
    assert message["role"] == "assistant"
    items = list(message.get("turnItems") or [])
    if not item_type:
        return items
    return [item for item in items if str(item.get("type") or "") == item_type]


def _assistant_visible_text(message: dict) -> str:
    return "\n".join(
        str(item.get("text") or "").strip()
        for item in _assistant_turn_items(message)
        if str(item.get("type") or "") in {"agent_message", "error"}
        if str(item.get("text") or "").strip()
    )


def _conversation_message_text(message: dict) -> str:
    if str(message.get("role") or "").strip().lower() == "assistant":
        return _assistant_visible_text(message)
    return str(message.get("content") or "")


def _assistant_status_metadata(message: dict, code: str) -> dict:
    for item in _assistant_turn_items(message, "status"):
        if str(item.get("code") or "").strip() != code:
            continue
        metadata = item.get("metadata")
        return dict(metadata) if isinstance(metadata, dict) else {}
    return {}


def _assistant_tool_summaries(message: dict) -> list[dict[str, str]]:
    return [
        {
            "name": str(item.get("toolName") or ""),
            "status": str(item.get("status") or ""),
        }
        for item in _assistant_turn_items(message, "tool_call")
    ]


def _assert_v3_assistant_message(message: dict) -> None:
    assert message["role"] == "assistant"
    assert isinstance(message.get("turnItems"), list)
    assert all(field not in message for field in _RETIRED_ASSISTANT_ENVELOPE_FIELDS)


def _assert_context_prepare_overlay(message: dict) -> None:
    _assert_v3_assistant_message(message)
    assert message["status"] == "running"
    assert any(
        item.get("type") == "status"
        and item.get("code") == "context_prepare"
        and item.get("text") == CONTEXT_PREPARE_LIVE_MESSAGE
        for item in message["turnItems"]
    )


def _append_test_ledger_messages(project_root: Path, session_id: str, messages: list[dict], *, prefix: str = "test") -> None:
    for index, message in enumerate(messages, start=1):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        turn_id = f"{prefix}-{index:03d}"
        timestamp = str(message.get("timestamp") or "").strip()
        metadata = dict(message.get("metadata") or {}) if isinstance(message.get("metadata"), dict) else {}
        if role == "user":
            append_conversation_event(
                project_root,
                session_id,
                turn_id,
                EVENT_USER_MESSAGE,
                status="recorded",
                payload={
                    "content": message.get("content") or "",
                    "attachments": list(message.get("attachments") or []),
                    "metadata": metadata,
                },
                timestamp=timestamp,
            )
            continue
        if role == "assistant":
            mental_snapshot = message.get("mentalSnapshot") or message.get("mental_snapshot")
            # Seeded calls must form a resolvable provider chain (explicit ids
            # plus matching tool-result events) or the conversation-seed
            # invariant fail-closes every later turn in this history.
            tool_calls, seeded_tool_results = _resolve_seeded_assistant_tool_calls(turn_id, message)
            append_conversation_event(
                project_root,
                session_id,
                turn_id,
                EVENT_ASSISTANT_MESSAGE,
                status=str(message.get("status") or "completed").strip() or "completed",
                payload={
                    "content": message.get("content") or "",
                    "thought": message.get("thought") or "",
                    "toolCalls": tool_calls,
                    "feedbackEvents": list(message.get("feedbackEvents") or message.get("feedback_events") or []),
                    "mentalSnapshot": dict(mental_snapshot) if isinstance(mental_snapshot, dict) else None,
                    "metadata": metadata,
                },
                timestamp=timestamp,
            )
            for tool_call_id, name, result_content in seeded_tool_results:
                append_conversation_event(
                    project_root,
                    session_id,
                    turn_id,
                    EVENT_TOOL_RESULT,
                    status="done",
                    payload={"toolCall": {"id": tool_call_id, "name": name, "result": result_content}},
                    timestamp=timestamp,
                    tool_call_id=tool_call_id,
                )
            continue
        if role == "tool":
            tool_call_id = str(
                message.get("tool_call_id")
                or message.get("toolCallId")
                or metadata.get("toolCallId")
                or ""
            ).strip()
            append_conversation_event(
                project_root,
                session_id,
                turn_id,
                EVENT_TOOL_RESULT,
                status=str(metadata.get("status") or metadata.get("toolStatus") or "done").strip() or "done",
                payload={
                    "toolCall": {
                        "id": tool_call_id,
                        "name": str(metadata.get("toolName") or metadata.get("tool_name") or "tool").strip() or "tool",
                        "result": message.get("content") or "",
                    }
                },
                timestamp=timestamp,
                tool_call_id=tool_call_id,
            )




def _bind_live_session_agent(project_root: Path, *, display_name: str = "真实会话", **kwargs) -> dict:
    agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name=display_name,
        **kwargs,
    )
    _bind_seeded_session_agent(project_root, agent)
    return agent


def test_session_agent_factory_explicitly_disables_auto_delegation(tmp_path, monkeypatch):
    runtime_agent = SimpleNamespace()
    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: runtime_agent)

    created = session_service._create_chat_agent_for_session(
        tmp_path,
        agent_instance=None,
        resolved_llm=SimpleNamespace(config=object()),
    )

    assert created is runtime_agent
    assert created._allow_session_subagent_auto_delegation is False


def _capture_session_lifecycle_events(monkeypatch):
    events = []
    condition = threading.Condition()

    def record_session_turn_lifecycle_event(session_id, phase, **kwargs):
        event = {
            "session_id": session_id,
            "phase": phase,
            "turn_id": kwargs.get("turn_id", ""),
            "outcome": kwargs.get("outcome", ""),
            "fields": dict(kwargs.get("fields") or {}),
        }
        with condition:
            events.append(event)
            condition.notify_all()

    def wait_for_phase(phase, *, timeout=2.0, fields=None):
        expected_fields = fields or {}
        return wait_for_matching_event(
            events,
            timeout_s=timeout,
            predicate=lambda event: (
                event["phase"] == phase
                and all(
                    event["fields"].get(key) == value
                    for key, value in expected_fields.items()
                )
            ),
            condition=condition,
        )

    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", record_session_turn_lifecycle_event)
    return wait_for_phase, events


def _install_session_turn_scheduler(monkeypatch, *, max_active_per_agent: int):
    scheduler = session_service.SessionTurnScheduler(
        agent_key_for_context=session_service._session_scheduler_agent_key,
        session_key_for_context=session_service._session_scheduler_session_key,
        max_active_per_agent=max_active_per_agent,
        now=session_service._perf_counter,
        record_event=session_service._record_scheduler_event_adapter,
        mark_queued=lambda context, position: session_service._mark_session_turn_queued(
            context,
            queue_position=position,
        ),
        mark_dequeued=lambda context: session_service._mark_session_turn_dequeued(context),
        is_session_running=lambda session_id: session_service._is_session_running(session_id),
        is_session_turn_current=lambda session_id, turn_id: session_service._is_session_turn_current(
            session_id,
            turn_id,
        ),
    )
    monkeypatch.setattr(session_service, "_SESSION_TURN_SCHEDULER", scheduler)
    return scheduler


@pytest.fixture(autouse=True)
def disable_runtime_manager_live_control(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)


@pytest.fixture(autouse=True)
def isolate_evolution_live_state():
    self_evolution_service.invalidate_self_evolution_overview_cache()
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_SUBSCRIBERS_LOCK:
        self_evolution_control_service._RUN_SUBSCRIBERS.clear()
    yield
    self_evolution_service.invalidate_self_evolution_overview_cache()
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_SUBSCRIBERS_LOCK:
        self_evolution_control_service._RUN_SUBSCRIBERS.clear()


def _read_first_sse_event(response):
    event_name = ""
    data_lines = []
    for line in response.iter_lines():
        if line.startswith("event: "):
            event_name = line[len("event: ") :]
            continue
        if line.startswith("data: "):
            data_lines.append(line[len("data: ") :])
            continue
        if line == "":
            if event_name or data_lines:
                return {
                    "event": event_name,
                    "data": "\n".join(data_lines),
                }
    raise AssertionError("Expected at least one SSE event")


def _real_runtime_manager_evolution_paths(kind: str, run_id: str) -> tuple[Path, Path]:
    root = runtime_manager_constants.PROJECT_ROOT / ".runtime" / "runtime-manager" / "evolution" / kind
    return root / "runs" / f"{run_id}.json", root / "index.json"


def _read_optional_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _restore_real_runtime_index_if_touched(kind: str, run_id: str, original_index_text: str | None) -> None:
    run_path, index_path = _real_runtime_manager_evolution_paths(kind, run_id)
    if run_path.exists():
        run_path.unlink()
    if index_path.exists() and run_id in index_path.read_text(encoding="utf-8"):
        if original_index_text is None:
            index_path.unlink()
        else:
            index_path.write_text(original_index_text, encoding="utf-8")


def test_skills_api_lists_read_only_skill_library(tmp_path, monkeypatch):
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nStop before implementation.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_service, "default_skill_roots", lambda: [skill_root])

    response = client.get("/api/skills")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "read_only"
    assert payload["counts"]["total"] == 1
    assert payload["skills"][0]["command"] == "/brt"
    assert "content" not in payload["skills"][0]


def test_skills_api_returns_skill_detail(tmp_path, monkeypatch):
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nAsk one question at a time.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_service, "default_skill_roots", lambda: [skill_root])

    response = client.get("/api/skills/brt")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "brt"
    assert payload["command"] == "/brt"
    assert "Ask one question at a time." in payload["content"]


def test_history_seed_omits_state_only_assistant_messages():
    history = session_service._history_messages_for_agent_seed(
        [
            {"role": "user", "content": "审查对话日志并汇报"},
            {"role": "assistant", "content": "<state>{\"mood\":\"open\"}</state>"},
            {"role": "assistant", "content": "<state"},
            {"role": "assistant", "content": "已完成审查。"},
        ]
    )

    assert [
        {"role": item["role"], "content": item["content"]}
        for item in history
    ] == [
        {"role": "user", "content": "审查对话日志并汇报"},
        {"role": "assistant", "content": "已完成审查。"},
    ]


def test_history_seed_excludes_current_turn_by_identity_without_text_dedupe():
    history = session_service._history_messages_for_agent_seed(
        [
            {"role": "user", "content": "你好", "metadata": {"turnId": "turn-1"}},
            {"role": "assistant", "content": "第一轮", "metadata": {"turnId": "turn-1"}},
            {"role": "user", "content": "你好", "metadata": {"turnId": "turn-2"}},
            {"role": "assistant", "content": "第二轮", "metadata": {"turnId": "turn-2"}},
            {"role": "user", "content": "你好", "metadata": {"turnId": "turn-current"}},
        ],
        exclude_turn_id="turn-current",
    )

    assert [item["content"] for item in history if item["role"] == "user"] == ["你好", "你好"]


def test_history_seed_keeps_empty_assistant_message_with_tool_calls():
    history = session_service._history_messages_for_agent_seed(
        [
            {"role": "user", "content": "继续验证"},
            {
                "role": "assistant",
                "content": "",
                "toolCalls": [
                    {
                        "toolName": "cli_tool",
                        "toolCallId": "call_test",
                        "status": "failed",
                        "resultPreview": "Windows detected Unix shell fragment.",
                    }
                ],
            },
        ]
    )

    assert len(history) == 2
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == ""
    assert history[1]["tool_calls"][0]["name"] == "cli_tool"
    assert history[1]["tool_calls"][0]["resultPreview"] == "Windows detected Unix shell fragment."


def test_history_seed_omits_turn_error_messages():
    history = session_service._history_messages_for_agent_seed(
        [
            {"role": "user", "content": "继续检查模型调用"},
            {
                "role": "assistant",
                "content": "模型服务上游暂时失败，本轮没有完成。",
                "metadata": {
                    "kind": "turn_error",
                    "errorType": "provider_protocol_error",
                },
            },
            {"role": "user", "content": "继续检查最新模型调用状态"},
            {"role": "assistant", "content": "现在可以继续处理。"},
        ]
    )

    assert [
        {"role": item["role"], "content": item["content"]}
        for item in history
    ] == [
        {"role": "user", "content": "继续检查模型调用"},
        {"role": "user", "content": "继续检查最新模型调用状态"},
        {"role": "assistant", "content": "现在可以继续处理。"},
    ]


def test_history_seed_omits_raw_payload_protocol_error_assistant_text():
    """Raw provider error text must never enter seeded model history, even bare."""

    poisoned = "payload_protocol_error: duplicate tool call id"
    assert session_service._should_omit_message_from_agent_history(
        {"role": "assistant", "content": poisoned}
    ) is True
    history = session_service._history_messages_for_agent_seed(
        [
            {"role": "user", "content": "执行资料搜集任务"},
            {"role": "assistant", "content": poisoned},
            {"role": "user", "content": "继续下一步"},
        ]
    )

    assert [
        {"role": item["role"], "content": item["content"]}
        for item in history
    ] == [
        {"role": "user", "content": "执行资料搜集任务"},
        {"role": "user", "content": "继续下一步"},
    ]


def test_provider_failure_classification_includes_payload_protocol_error():
    """Local payload protocol failures route through the provider-failure path."""

    error_text = "payload_protocol_error: duplicate tool call id"
    assert session_service._looks_like_provider_error_text(error_text) is True
    assert session_service._failure_error_type(error_text) == "provider_protocol_error"
    assert (
        session_service._is_provider_failed_result(
            {
                "status": "failed",
                "summary": error_text,
                "raw_output": error_text,
                "error": error_text,
            }
        )
        is True
    )
    reason = session_service._provider_error_user_reason(error_text, lang="zh")
    assert reason.get("code") == "provider_protocol_error"
    summary = session_service._user_visible_failure_summary(error_text, lang="zh")
    assert error_text not in summary
    assert "协议" in summary


def test_build_followup_prompt_unwraps_nested_continue_goal():
    prompt = session_service._build_followup_prompt(
        original_prompt="审查对话日志并汇报",
        effective_prompt=(
            "继续完成同一个用户目标：继续完成同一个用户目标：审查对话日志并汇报\n"
            "上一内部回合仍未完成用户目标（第 1 轮）。"
        ),
        latest_result={
            "status": "completed",
            "outcome": "progress",
            "recommended_next_action": "基于已读证据输出结论。",
        },
        history_messages=[{"role": "user", "content": "审查对话日志并汇报"}],
        turn_index=2,
    )

    assert prompt == "审查对话日志并汇报"
    assert "继续完成同一个用户目标：" not in prompt
    assert "上一内部回合" not in prompt


def test_build_followup_prompt_includes_running_turn_guidance():
    prompt = session_service._build_followup_prompt(
        original_prompt="审查对话日志并汇报",
        effective_prompt="审查对话日志并汇报",
        latest_result={
            "status": "completed",
            "outcome": "progress",
            "recommended_next_action": "基于已读证据输出结论。",
        },
        history_messages=[{"role": "user", "content": "审查对话日志并汇报"}],
        turn_index=2,
        guidance_summaries=["先不要继续实现，先汇报链路风险。"],
    )

    assert "用户在当前运行轮补充了以下引导" not in prompt
    assert prompt.startswith("审查对话日志并汇报")
    assert "先不要继续实现，先汇报链路风险。" in prompt


def test_normalize_persisted_tool_calls_preserves_timeout_as_timeout():
    tool_calls = session_service._normalize_persisted_tool_calls(
        [
            {
                "name": "grep_search_tool",
                "status": "done",
                "summary": "[超时] grep_search_tool 执行超时 (30秒)",
            },
            {
                "name": "read_file_tool",
                "summary": "read ok",
            },
        ]
    )

    assert tool_calls[0]["status"] == "timeout"
    assert tool_calls[1]["status"] == "done"


def test_normalize_persisted_tool_calls_preserves_safe_details():
    tool_calls = session_service._normalize_persisted_tool_calls(
        [
            {
                "name": "image2_generate_tool",
                "status": "failed",
                "summary": "Read timed out.",
                "args": {
                    "prompt": "生成美女图片",
                    "size": "1024x1024",
                    "_cancel_checker": "internal",
                    "api_key": "secret",
                },
                "error": "HTTPSConnectionPool read timed out",
                "durationMs": 180452,
                "timeoutSeconds": 180,
                "resultType": "str",
                "resultLength": 755,
                "tracePath": "conversations/session/tool_calls.jsonl",
            },
        ]
    )

    assert tool_calls == [
        {
            "name": "image2_generate_tool",
            "status": "timeout",
            "summary": "Read timed out.",
            "arguments": {
                "prompt": "生成美女图片",
                "size": "1024x1024",
            },
            "error": "HTTPSConnectionPool read timed out",
            "durationMs": 180452,
            "timeoutSeconds": 180,
            "resultType": "str",
            "resultLength": 755,
            "tracePath": "conversations/session/tool_calls.jsonl",
        }
    ]


def test_normalize_persisted_tool_calls_preserves_error_like_statuses():
    tool_calls = session_service._normalize_persisted_tool_calls(
        [
            {"name": "grep_search_tool", "status": "no_result", "summary": "No match found."},
            {"name": "read_file_tool", "status": "cancelled", "summary": "User cancelled read."},
            {"name": "python_lint_tool", "status": "submitted", "summary": "lint submission accepted."},
            {"name": "task_update_tool", "status": "in_progress", "summary": "task update job running."},
        ]
    )

    assert tool_calls[0]["status"] == "no_result"
    assert tool_calls[1]["status"] == "cancelled"
    assert tool_calls[2]["status"] == "submitted"
    assert tool_calls[3]["status"] == "in_progress"


def test_chat_turn_records_keep_tool_names_when_persisted_calls_have_details():
    records = session_service._build_chat_turn_records_from_messages(
        [
            {"role": "user", "content": "生成图片"},
            {
                "role": "assistant",
                "content": "已调用工具。",
                "tool_calls": [
                    {
                        "name": "image2_generate_tool",
                        "status": "failed",
                        "args": {"prompt": "生成美女图片"},
                        "error": "timeout",
                    }
                ],
            },
        ]
    )

    assert records[0].tool_calls == ["image2_generate_tool"]
    assert records[0].tool_call_count == 1


def test_session_detail_exposes_recent_next_state_signal_summaries(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-seeded",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "继续前端开发"},
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-seeded",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "已经接到真实状态了。"},
    )
    append_chat_next_state_signal(
        project_root=tmp_path,
        session_id="session-live",
        turn_id="turn-signal",
        source="runtime",
        kind="provider_failure",
        polarity="negative",
        mode="evaluative",
        related_event_code="conversation.turn_circuit_breaker",
        summary="Provider failed after a partial tool pass.",
        metadata={"rawError": "full provider payload should stay out of session detail"},
        created_at="2026-05-18T11:58:00Z",
        record_scene=False,
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["nextStateSignals"] == [
        {
            "signalId": payload["nextStateSignals"][0]["signalId"],
            "sessionId": "session-live",
            "turnId": "turn-signal",
            "source": "runtime",
            "kind": "provider_failure",
            "polarity": "negative",
            "mode": "evaluative",
            "relatedEventCode": "conversation.turn_circuit_breaker",
            "createdAt": "2026-05-18T11:58:00Z",
            "summary": "Provider failed after a partial tool pass.",
        }
    ]
    assert "metadata" not in payload["nextStateSignals"][0]
    assert payload["messages"][0]["content"] == "继续前端开发"
    assert all(message["role"] in {"user", "assistant"} for message in payload["messages"])


def test_create_session_persists_new_active_empty_conversation(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.post("/api/sessions")

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"].startswith("session-")
    assert payload["title"] == payload["agentDisplayName"]
    assert payload["taskTitle"] == "新会话"
    assert payload["title"] != "新会话"
    assert payload["messages"] == []
    assert payload["currentPhase"] == "ready"
    assert payload["sourceRef"]["owner"] == "ConversationLedger"
    assert payload["sourceRef"]["canonicalEditRoute"] == f"/chat?session={payload['id']}"
    assert payload["projectionEdit"]["canWrite"] is False
    assert payload["agentSourceRef"]["owner"] == "AgentDirectory"
    assert payload["agentSourceRef"]["canonicalEditRoute"] == f"/agents?agent={payload['agentId']}&pane=config"

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == payload["id"]
    assert [item["conversation_id"] for item in state["conversations"]] == [
        "session-live",
        payload["id"],
    ]
    created = state["conversations"][-1]
    assert created["title"] == "新会话"
    assert created["agent_id"] == payload["agentId"]
    assert created["agentId"] == payload["agentId"]
    assert agent_directory_service.get_agent(payload["agentId"])["directSessionId"] == payload["id"]
    assert "agent_profile_id" not in created
    assert "agentProfileId" not in created


def test_create_session_invalidates_agent_index_cache_after_project_root_switch(tmp_path, monkeypatch):
    old_root = tmp_path / "old-project"
    new_root = tmp_path / "new-project"
    _seed_chat_state(old_root)
    _seed_chat_state(new_root)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", old_root)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", old_root)
    agent = agent_directory_service.create_agent_instance(
        display_name="旧项目 Agent",
        direct_session_id="session-live",
        primary_mode="chat",
    )
    old_state = load_chat_state(old_root)
    old_state["conversations"][0]["agent_id"] = agent["agentId"]
    old_state["conversations"][0]["agentId"] = agent["agentId"]
    save_chat_state(old_root, old_state)
    old_cached_title = client.get("/api/sessions").json()[0]["title"]
    assert old_cached_title

    monkeypatch.setattr(session_service, "PROJECT_ROOT", new_root)

    response = client.post("/api/sessions")

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] != old_cached_title
    assert payload["title"] == payload["agentDisplayName"]
    assert payload["taskTitle"] == "新会话"
    assert payload["agentId"]
    assert agent_directory_service.PROJECT_ROOT == new_root


def test_update_session_title_persists_to_list_and_detail(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.patch(
        "/api/sessions/session-live",
        json={"title": "重命名后的会话"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["title"] == "重命名后的会话"

    sessions_response = client.get("/api/sessions")
    assert sessions_response.status_code == 200
    assert sessions_response.json()[0]["title"] == "重命名后的会话"

    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["title"] == "重命名后的会话"


def test_update_root_agent_session_title_keeps_agent_responsibility_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="旧 Agent 名",
        direct_session_id="session-live",
        primary_mode="chat",
    )
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-live",
                "title": "旧任务名",
                "agent_id": agent["agentId"],
                "agentId": agent["agentId"],
                "updated_at": "2026-05-18T12:00:00",
                "last_turn_status": "ready",
                "messages": [],
            }
        ],
    )

    agent_display_name = agent["displayName"]

    response = client.patch("/api/sessions/session-live", json={"title": "新任务名"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["title"] == "新任务名"
    assert payload["agentDisplayName"] == agent_display_name
    assert agent_directory_service.get_agent(agent["agentId"])["displayName"] == agent_display_name
    title_event = next(item for item in events if item[0][2] == "conversation.title.updated")
    assert title_event[1]["fields"] == {
        "sessionId": "session-live",
        "agentId": agent["agentId"],
        "sessionKind": "main",
        "agentIdentityChanged": False,
        "source": "session_record",
    }


def test_update_agent_responsibility_keeps_root_session_title_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    session = session_service.create_chat_session(title="需求分析")

    response = client.patch(
        f"/api/agents/{session['agentId']}",
        json={"displayName": "代码开发"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["displayName"] == "代码开发"
    detail = session_service.get_session_detail(session["id"])
    assert detail["title"] == "需求分析"
    assert detail["agentDisplayName"] == "代码开发"


def test_update_child_session_title_keeps_agent_display_name_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(
        display_name="根 Agent 名",
        direct_session_id="session-test-root",
        primary_mode="chat",
    )
    agent_display_name = agent["displayName"]
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-child",
                "title": "旧子任务",
                "task_title": "旧子任务",
                "taskTitle": "旧子任务",
                "session_kind": "child",
                "sessionKind": "child",
                "parent_session_id": "session-test-root",
                "parentSessionId": "session-test-root",
                "root_session_id": "session-test-root",
                "rootSessionId": "session-test-root",
                "agent_id": agent["agentId"],
                "agentId": agent["agentId"],
                "updated_at": "2026-05-18T12:00:00",
                "last_turn_status": "ready",
                "messages": [],
            }
        ],
    )

    response = client.patch("/api/sessions/session-child", json={"title": "新子任务"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["title"] == "新子任务"
    assert payload["taskTitle"] == "新子任务"
    assert payload["agentDisplayName"] == agent_display_name
    assert agent_directory_service.get_agent(agent["agentId"])["displayName"] == agent_display_name


def test_update_session_agent_profile_payload_is_rejected(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)

    response = client.patch(
        "/api/sessions/session-live",
        json={"agentProfileId": "subagent_explorer"},
    )

    assert response.status_code == 422

    state = load_chat_state(tmp_path)
    assert "agent_profile_id" not in state["conversations"][0]
    assert "agentProfileId" not in state["conversations"][0]


def test_update_session_agent_id_persists_as_primary_binding(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(
        display_name="备用会话 Agent",
        llm_bindings={"dialogue": {"modelId": "model-backup"}},
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )

    response = client.patch(
        "/api/sessions/session-live",
        json={"agentId": agent["agentId"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["agentId"] == agent["agentId"]
    assert "agentProfileId" not in payload

    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["agent_id"] == agent["agentId"]
    assert state["conversations"][0]["agentId"] == agent["agentId"]
    assert "agent_profile_id" not in state["conversations"][0]
    assert "agentProfileId" not in state["conversations"][0]
    rebound_agent = agent_directory_service.get_agent(agent["agentId"])
    assert rebound_agent is not None
    assert rebound_agent["directSessionId"] == "session-live"
    assert rebound_agent["llmBindings"]["dialogue"]["modelId"] == "model-backup"
    directory_state = agent_directory_service.load_state()
    assert [
        item["agentId"]
        for item in directory_state.get("agents", [])
        if item.get("status") == "active" and item.get("directSessionId") == "session-live"
    ] == [agent["agentId"]]


def test_session_agent_templates_endpoint_removed():
    response = client.get("/api/sessions/agent-templates")

    assert response.status_code == 404


def test_update_session_title_rejects_empty_title(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.patch(
        "/api/sessions/session-live",
        json={"title": "   "},
    )

    assert response.status_code == 422
    assert "名称" in response.json()["detail"]
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["title"] == "真实会话"


def test_delete_session_switches_to_latest_remaining_session(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "当前会话",
                    "updated_at": "2026-05-18T12:00:00",
                    "last_turn_status": "ready",
                    "messages": [{"role": "user", "content": "删除我", "timestamp": "2026-05-18T12:00:00"}],
                },
                {
                    "conversation_id": "session-older",
                    "title": "旧会话",
                    "updated_at": "2026-05-18T10:00:00",
                    "last_turn_status": "ready",
                    "messages": [{"role": "user", "content": "旧", "timestamp": "2026-05-18T10:00:00"}],
                },
                {
                    "conversation_id": "session-newer",
                    "title": "新会话",
                    "updated_at": "2026-05-18T11:00:00",
                    "last_turn_status": "ready",
                    "messages": [{"role": "user", "content": "新", "timestamp": "2026-05-18T11:00:00"}],
                },
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    events = []

    def capture_session_delete_event(component, phase, event_code, **kwargs):
        if str(event_code).startswith("session.delete."):
            events.append(
                {
                    "component": component,
                    "phase": phase,
                    "eventCode": event_code,
                    **kwargs,
                }
            )

    monkeypatch.setattr(session_service, "record_runtime_scene_event", capture_session_delete_event)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "deleted": True,
        "deletedSessionId": "session-live",
        "nextActiveSessionId": "session-newer",
        "replacementDirectSessionId": "",
    }

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == "session-newer"
    assert [item["conversation_id"] for item in state["conversations"]] == [
        "session-older",
        "session-newer",
    ]
    assert [event["eventCode"] for event in events] == [
        "session.delete.requested",
        "session.delete.directory_archived",
        "session.delete.deleted",
    ]
    assert events[0]["fields"]["phase"] == "ready"
    assert events[2]["fields"]["nextActiveSessionId"] == "session-newer"
    assert {
        "load_state",
        "repair_state",
        "resolve_target",
        "unbind_agent",
        "save_state_and_archive",
        "runtime_cleanup",
    }.issubset(events[2]["fields"]["timingsMs"])
    assert events[2]["fields"]["durationMs"] >= events[2]["fields"]["timingsMs"]["save_state_and_archive"]


def test_delete_session_keeps_bound_agent_active(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="科研复核 Agent",
        primary_mode="research",
        role_key="research_review",
        prompt_template_id="prompt-research-review",
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_id"] = agent["agentId"]
    state["conversations"][0]["agentId"] = agent["agentId"]
    save_chat_state(tmp_path, state)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    kept_agent = agent_directory_service.get_agent(agent["agentId"], include_archived=True)
    assert kept_agent is not None
    assert kept_agent["status"] == "active"


def test_delete_bound_direct_session_rebinds_agent_without_reviving_old_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    events = []
    agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="科研复核 Agent",
        primary_mode="research",
        role_key="research_review",
        prompt_template_id="prompt-research-review",
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_id"] = agent["agentId"]
    state["conversations"][0]["agentId"] = agent["agentId"]
    save_chat_state(tmp_path, state)

    def capture_session_delete_event(component, phase, event_code, **kwargs):
        if str(event_code).startswith("session.delete."):
            events.append(
                {
                    "component": component,
                    "phase": phase,
                    "eventCode": event_code,
                    **kwargs,
                }
            )

    monkeypatch.setattr(session_service, "record_runtime_scene_event", capture_session_delete_event)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    rebound_agent = agent_directory_service.get_agent(agent["agentId"], include_archived=True)
    assert rebound_agent is not None
    assert rebound_agent["status"] == "active"
    assert rebound_agent["directSessionId"] == ""
    assert session_service.get_session_detail("session-live") is None
    sessions = session_service.list_sessions()
    assert "session-live" not in {item["id"] for item in sessions}
    assert agent["agentId"] not in {item["agentId"] for item in sessions}
    unbound_events = [event for event in events if event["eventCode"] == "session.delete.agent_unbound"]
    assert len(unbound_events) == 1
    assert unbound_events[0]["fields"]["agentId"] == agent["agentId"]
    assert unbound_events[0]["fields"]["previousDirectSessionId"] == "session-live"


def test_delete_last_session_creates_replacement(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] is True
    assert payload["deletedSessionId"] == "session-live"
    next_active_session_id = str(payload["nextActiveSessionId"] or "").strip()
    assert next_active_session_id.startswith("session-")
    assert next_active_session_id != "session-live"

    replacement = session_service.get_session_detail(next_active_session_id)
    assert replacement is not None
    assert replacement["title"] == "新会话"
    assert replacement["agentId"] == ""
    assert replacement["messages"] == []

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == next_active_session_id
    assert [item["conversation_id"] for item in state["conversations"]] == [next_active_session_id]


def test_delete_session_prefer_async_returns_lightweight_handoff(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-live",
                "title": "当前会话",
                "updated_at": "2026-05-18T09:00:00",
                "last_turn_status": "ready",
                "messages": [{"role": "user", "content": "当前", "timestamp": "2026-05-18T09:00:00"}],
            },
            {
                "conversation_id": "session-next",
                "title": "下一个会话",
                "updated_at": "2026-05-18T10:00:00",
                "last_turn_status": "ready",
                "messages": [{"role": "user", "content": "下一个", "timestamp": "2026-05-18T10:00:00"}],
            },
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.delete("/api/sessions/session-live", headers={"Prefer": "respond-async"})

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "deleted": True,
        "deletedSessionId": "session-live",
        "nextActiveSessionId": "session-next",
        "replacementDirectSessionId": "",
    }
    assert session_service.get_session_detail("session-live") is None


def test_delete_session_rejects_running_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    events = []

    def capture_session_delete_event(component, phase, event_code, **kwargs):
        if str(event_code).startswith("session.delete."):
            events.append(
                {
                    "component": component,
                    "phase": phase,
                    "eventCode": event_code,
                    **kwargs,
                }
            )

    monkeypatch.setattr(session_service, "record_runtime_scene_event", capture_session_delete_event)

    session_service._set_session_running("session-live", True)
    try:
        response = client.delete("/api/sessions/session-live")
    finally:
        session_service._set_session_running("session-live", False)

    assert response.status_code == 409
    assert "运行" in response.json()["detail"]
    state = load_chat_state(tmp_path)
    assert [item["conversation_id"] for item in state["conversations"]] == ["session-live"]
    assert [event["eventCode"] for event in events] == [
        "session.delete.requested",
        "session.delete.blocked",
    ]
    assert events[0]["fields"]["phase"] == "running"
    assert events[1]["fields"]["reason"] == "busy"


def test_session_detail_uses_live_phase_while_turn_is_running(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "running"


def test_session_detail_exposes_pre_model_progress_stage(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="turn-progress")
    try:
        session_service._set_session_waiting_live_output("session-live", turn_id="turn-progress")
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False, turn_id="turn-progress")

    assert response.status_code == 200
    payload = response.json()
    live_message = payload["messages"][-1]
    assert live_message["id"] == "session-live-message-live-turn-progress"
    assert live_message["status"] == "running"
    assert any(
        item.get("type") == "status"
        and item.get("code") == "context_prepare"
        and item.get("text") == CONTEXT_PREPARE_LIVE_MESSAGE
        for item in live_message["turnItems"]
    )
    assert all(field not in live_message for field in ("content", "thought", "streaming", "streamStage", "toolCalls", "feedbackEvents", "timelineItems", "codexTranscript"))
    assert live_message["metadata"]["kind"] == "session_live_overlay"
    assert live_message["metadata"]["turnId"] == "turn-progress"
    assert live_message["metadata"]["ledgerSeq"] >= 0


def test_session_detail_live_overlay_identity_matches_assistant_delta_turn_id(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="turn-live-identity")
    try:
        session_service._set_session_live_output(
            "session-live",
            turn_id="turn-live-identity",
            content="正在输出。",
            thought="正在思考。",
            feedback_events=[{"kind": "status", "name": "model_response"}],
        )
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live", turn_id="turn-live-identity")
        session_service._set_session_running("session-live", False, turn_id="turn-live-identity")

    assert response.status_code == 200
    live_message = response.json()["messages"][-1]
    assert live_message["id"] == "session-live-message-live-turn-live-identity"
    assert live_message["metadata"] == {
        "kind": "session_live_overlay",
        "turnId": "turn-live-identity",
        "ledgerSeq": live_message["metadata"]["ledgerSeq"],
    }
    _assert_v3_assistant_message(live_message)
    assert _assistant_visible_text(live_message) == "正在输出。"
    reasoning_items = _assistant_turn_items(live_message, "reasoning")
    assert [item["text"] for item in reasoning_items] == ["正在思考。"]
    assert any(
        item.get("type") == "status" and item.get("code") == "model_response"
        for item in live_message["turnItems"]
    )
    # C3: live overlay must carry turnItems package so reconnect paints on package_cells track.
    turn_items = live_message.get("turnItems") or []
    assert turn_items
    final_items = [
        item
        for item in turn_items
        if str(item.get("phase") or "") == "final_answer"
        or (
            str(item.get("kind") or item.get("type") or "") in {"assistant_message", "agent_message"}
            and str(item.get("channel") or "") in {"", "answer"}
        )
    ]
    assert final_items
    assert final_items[0]["text"] == "正在输出。"
    assert final_items[0]["status"] == "running"
    assert final_items[0]["terminal"] is False


def test_session_detail_exposes_pre_model_progress_as_ordered_feedback_events(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="turn-progress-events")
    try:
        session_service._persist_chat_turn_work_run(
            session_id="session-live",
            turn_id="turn-progress-events",
            status="running",
            user_message="继续",
            updated_at="2026-06-05T00:00:00",
        )
        session_service._set_session_turn_progress_live_output("session-live", "context_prepare", turn_id="turn-progress-events")
        session_service._set_session_turn_progress_live_output("session-live", "agent_prepare", turn_id="turn-progress-events")
        session_service._set_session_turn_progress_live_output("session-live", "model_request", turn_id="turn-progress-events")
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live", turn_id="turn-progress-events")
        session_service._set_session_running("session-live", False, turn_id="turn-progress-events")
        session_service._persist_chat_turn_work_run(
            session_id="session-live",
            turn_id="turn-progress-events",
            status="completed",
            finished_at="2026-06-05T00:00:10",
            updated_at="2026-06-05T00:00:10",
        )

    assert response.status_code == 200
    payload = response.json()
    live_message = payload["messages"][-1]
    _assert_v3_assistant_message(live_message)
    status_items = _assistant_turn_items(live_message, "status")
    assert [item["code"] for item in status_items] == [
        "context_prepare",
        "agent_prepare",
        "model_request",
    ]
    assert status_items[-1]["status"] == "running"
    work_run = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", "turn-progress-events")
    assert work_run is not None
    assert work_run["updatedAt"] != "2026-06-05T00:00:00"


def test_session_detail_prefers_running_turn_context_composition(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        conversations=[
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "updated_at": "2026-05-18T12:00:00",
                "last_turn_status": "ready",
                "last_context_composition": {
                    "turnId": "old-turn",
                    "recordedAt": "2026-06-04T00:00:00",
                    "totalTokens": 10,
                    "segments": [{"key": "history", "label": "history", "tokens": 10, "chars": 100}],
                },
                "messages": [
                    {"role": "user", "content": "上一轮", "timestamp": "2026-05-18T11:55:00"},
                    {"role": "assistant", "content": "完成", "timestamp": "2026-05-18T11:56:00"},
                ],
            }
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="new-turn")
    try:
        session_service._set_session_live_context_composition(
            "session-live",
            {
                "turnId": "new-turn",
                "recordedAt": "2026-06-05T00:00:00",
                "source": "runtime_assembly",
                "totalTokens": 42,
                "segments": [{"key": "current_user", "label": "current user", "tokens": 42, "chars": 420}],
            },
            turn_id="new-turn",
        )
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live", turn_id="new-turn")
        session_service._set_session_running("session-live", False, turn_id="new-turn")

    assert response.status_code == 200
    payload = response.json()
    assert payload["lastContextComposition"]["turnId"] == "new-turn"
    assert payload["lastContextComposition"]["totalTokens"] == 42
    assert payload["lastContextComposition"]["segments"][0]["key"] == "current_user"


def test_session_detail_overrides_active_task_status_from_running_work_run(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "previous-task",
            "kind": "coding",
            "status": "done",
            "title": "上一轮任务",
            "latest_summary": "上一轮已结束。",
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="turn-active-task")
    try:
        session_service._persist_chat_turn_work_run(
            session_id="session-live",
            turn_id="turn-active-task",
            status="running",
            user_message="继续",
            summary="正在请求模型，等待首个响应片段...",
        )
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-active-task")
        session_service._persist_chat_turn_work_run(
            session_id="session-live",
            turn_id="turn-active-task",
            status="completed",
            finished_at="2026-06-05T00:00:10",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "running"
    assert payload["activeTask"] is None


def test_session_detail_hydrates_file_context_from_saved_active_task(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "done",
            "title": "修复会话页面文件上下文",
            "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
            "changed_files": ["core/web/services/session_service.py"],
            "verification_status": "passed",
            "verification_summary": "2 passed in 0.31s",
            "default_file_context": "core/web/services/session_service.py",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["readFiles"] == ["web/src/routes/ChatCodingRoute.tsx"]
    assert payload["changedFiles"] == ["core/web/services/session_service.py"]
    assert payload["defaultFileContext"] == "core/web/services/session_service.py"
    assert payload["previewTabs"] == [
        "core/web/services/session_service.py",
        "web/src/routes/ChatCodingRoute.tsx",
    ]
    assert payload["activePreviewPath"] == "core/web/services/session_service.py"
    assert payload["activeTask"]["title"] == "修复会话页面文件上下文"
    assert payload["activeTask"]["changedFiles"] == ["core/web/services/session_service.py"]
    assert payload["activeTask"]["readFiles"] == ["web/src/routes/ChatCodingRoute.tsx"]


def test_session_events_stream_initial_detail(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-stream-seeded-user",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "继续前端开发"},
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-stream-seeded-assistant",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": "<think>internal</think>\n\n已经接到真实状态了。",
            "toolCalls": [
                {"name": "read_file_tool", "status": "done", "summary": "读取文件"},
                {"name": "search_code_tool", "status": "done", "summary": "搜索代码"},
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    detail = session_service.get_session_detail("session-live")
    assert detail is not None

    stream = session_service.stream_session_events("session-live", initial_detail=detail)
    raw_event = next(stream)
    stream.close()

    class _SingleEventResponse:
        def iter_lines(self):
            for line in str(raw_event).splitlines():
                yield line
            yield ""

    event = _read_first_sse_event(_SingleEventResponse())

    assert event["event"] == "session_detail"
    payload = json.loads(event["data"])
    assert payload["type"] == "session_detail"
    assert payload["sessionId"] == "session-live"
    assert payload["detail"]["id"] == "session-live"
    assistant_message = payload["detail"]["messages"][1]
    _assert_v3_assistant_message(assistant_message)
    assert _assistant_visible_text(assistant_message) == "已经接到真实状态了。"


def test_session_events_stream_initial_lightweight_payload_avoids_full_detail(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="running")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    def unexpected_full_detail(session_id: str):
        raise AssertionError(f"unexpected full detail load for {session_id}")

    monkeypatch.setattr(session_service, "get_session_detail", unexpected_full_detail)

    stream = session_service.stream_session_events("session-live", initial="light")
    raw_event = next(stream)
    stream.close()

    class _SingleEventResponse:
        def iter_lines(self):
            for line in str(raw_event).splitlines():
                yield line
            yield ""

    event = _read_first_sse_event(_SingleEventResponse())

    assert event["event"] == "session_initial"
    payload = json.loads(event["data"])
    assert payload["type"] == "session_initial"
    assert payload["sessionId"] == "session-live"
    assert "detail" not in payload
    assert payload["summary"]["id"] == "session-live"
    assert payload["latestMessage"]["role"] == "assistant"
    assert payload["latestMessage"]["contentLength"] >= 0


def test_session_stream_initial_payload_helper_normalizes_route_default(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="running")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    mode, detail, initial_state = session_service.resolve_session_stream_initial_payload(
        "session-live",
        "invalid-mode",
    )

    assert mode == "light"
    assert detail is None
    assert initial_state is not None
    assert initial_state["type"] == "session_initial"
    assert initial_state["sessionId"] == "session-live"


def test_session_stream_initial_payload_helper_keeps_none_as_no_initial_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="running")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_session_stream_initial_state",
        lambda session_id: (_ for _ in ()).throw(
            AssertionError(f"unexpected initial state load for {session_id}")
        ),
    )

    mode, detail, initial_state = session_service.resolve_session_stream_initial_payload("session-live", "none")

    assert mode == "none"
    assert detail is None
    assert initial_state is None


def test_session_events_stream_none_yields_only_incremental_events(monkeypatch):
    def fail_initial_projection(*_args, **_kwargs):
        raise AssertionError("initial=none must not rebuild the session bootstrap projection")

    def register_incremental_event(_session_id, subscriber):
        subscriber.put({"type": "session_probe", "sessionId": "session-bootstrap-owned"})

    monkeypatch.setattr(session_service, "get_session_stream_initial_state", fail_initial_projection)
    monkeypatch.setattr(session_service, "get_session_detail", fail_initial_projection)
    monkeypatch.setattr(session_service, "_register_session_stream_subscriber", register_incremental_event)
    monkeypatch.setattr(session_service, "_unregister_session_stream_subscriber", lambda *_args: None)

    stream = session_service.stream_session_events("session-bootstrap-owned", initial="none")
    first_event = next(stream)
    stream.close()

    assert "event: session_probe" in first_event
    assert '"sessionId": "session-bootstrap-owned"' in first_event


def test_async_session_stream_delivers_with_more_idle_streams_than_executor_capacity():
    async def exercise() -> str:
        streams = [
            session_service.stream_session_events_async(f"session-idle-{index}", initial="none")
            for index in range(12)
        ]
        pending = [asyncio.create_task(anext(stream)) for stream in streams]
        try:
            for _ in range(50):
                with session_service._SESSION_STREAM_SUBSCRIBERS_LOCK:
                    registered = sum(
                        len(session_service._SESSION_STREAM_SUBSCRIBERS.get(f"session-idle-{index}") or ())
                        for index in range(12)
                    )
                if registered == 12:
                    break
                await asyncio.sleep(0.005)
            assert registered == 12

            with session_service._SESSION_STREAM_SUBSCRIBERS_LOCK:
                target = next(iter(session_service._SESSION_STREAM_SUBSCRIBERS["session-idle-11"]))
            delivered, dropped = session_service._put_session_stream_event(
                target,
                {"type": "session_probe", "sessionId": "session-idle-11"},
            )
            assert delivered is True
            assert dropped == 0
            return await asyncio.wait_for(pending[11], timeout=0.3)
        finally:
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for stream in streams:
                await stream.aclose()

    raw_event = asyncio.run(exercise())

    assert "event: session_probe" in raw_event
    assert '"sessionId": "session-idle-11"' in raw_event
    with session_service._SESSION_STREAM_SUBSCRIBERS_LOCK:
        assert all(
            not session_service._SESSION_STREAM_SUBSCRIBERS.get(f"session-idle-{index}")
            for index in range(12)
        )


def test_web_app_entrypoint_uses_extracted_app_chain_helpers():
    from core.web import app as web_app
    from core.web.lifecycle import web_workbench_lifespan
    from core.web.middleware.runtime_scene_api import RuntimeSceneApiEventMiddleware
    from core.web.router_registry import register_web_routers
    from core.web.static_spa import web_index_response

    app = create_app()
    middleware_classes = [item.cls for item in app.user_middleware]

    assert RuntimeSceneApiEventMiddleware in middleware_classes
    assert web_app.web_workbench_lifespan is web_workbench_lifespan
    assert web_app.register_web_routers is register_web_routers
    assert web_app.web_index_response is web_index_response
    assert web_app.app.title == "Vibelution Web Workbench"


def test_session_detail_snapshot_publish_records_perf_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    detail = session_service.get_session_detail("session-live")
    assert detail is not None
    stream = session_service.stream_session_events("session-live", initial_detail=detail)
    next(stream)
    try:
        session_service._publish_session_detail_snapshot("session-live")
    finally:
        stream.close()

    published_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.published"]
    assert len(published_events) == 1
    fields = published_events[0][1]["fields"]
    assert fields["sessionId"] == "session-live"
    assert fields["subscriberCount"] == 1
    assert fields["deliveredCount"] == 1
    assert fields["droppedCount"] == 0
    assert fields["messageCount"] == len(detail["messages"])
    assert fields["elapsedMs"] >= 0


def test_session_detail_snapshot_publish_coalesces_stale_detail_events(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=8)
    session_service._register_session_stream_subscriber("session-live", subscriber)
    try:
        for index in range(3):
            subscriber.put_nowait({"type": "session_detail", "detail": {"stale": index}})
        session_service._publish_session_detail_snapshot("session-live")
    finally:
        session_service._unregister_session_stream_subscriber("session-live", subscriber)

    assert subscriber.qsize() == 1
    latest = subscriber.get_nowait()
    assert latest["type"] == "session_detail"
    assert latest["detail"]["id"] == "session-live"
    published_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.published"]
    assert published_events[-1][1]["fields"]["deliveredCount"] == 1
    assert published_events[-1][1]["fields"]["droppedCount"] == 3


def test_session_live_output_publishes_lightweight_assistant_delta_without_detail_snapshot(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    detail_calls = 0
    original_get_session_detail = session_service.get_session_detail

    def counted_get_session_detail(*args, **kwargs):
        nonlocal detail_calls
        detail_calls += 1
        return original_get_session_detail(*args, **kwargs)

    monkeypatch.setattr(session_service, "get_session_detail", counted_get_session_detail)

    subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=8)
    session_service._register_session_stream_subscriber("session-live", subscriber)
    session_service._set_session_running("session-live", True, turn_id="turn-running")
    content_delta_event: dict[str, object] | None = None
    try:
        session_service._set_session_live_output("session-live", turn_id="turn-running", content="hello")
        content_delta_event = subscriber.get_nowait()
        session_service._set_session_live_output(
            "session-live",
            turn_id="turn-running",
            thought="thinking",
            feedback_events=[
                {
                    "kind": "thought",
                    "status": "running",
                    "summary": "thinking",
                    "resultPreview": "thinking",
                }
            ],
        )
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-running")
        session_service._unregister_session_stream_subscriber("session-live", subscriber)
        with session_service._SESSION_LIVE_OUTPUTS_LOCK:
            session_service._SESSION_LIVE_OUTPUTS.pop("session-live", None)

    assert detail_calls == 0
    assert subscriber.qsize() >= 1
    events = [content_delta_event]
    while not subscriber.empty():
        events.append(subscriber.get_nowait())
    assert content_delta_event is not None
    assert all(item["type"] == "assistant_delta" for item in events)
    assert all("timelineItems" not in item for item in events)
    event = events[-1]
    assert event["type"] == "assistant_delta"
    assert event["sessionId"] == "session-live"
    assert event["turnId"] == "turn-running"
    assert event["ledgerSeq"] >= 0
    assert all("content" not in item and "thought" not in item for item in events)
    assert all(isinstance(item.get("turnItems"), list) for item in events)
    assert any(
        any(turn_item.get("type") == "agent_message" and turn_item.get("text") == "hello" for turn_item in item["turnItems"])
        for item in events
    )
    assert any(
        any(turn_item.get("type") == "reasoning" and turn_item.get("text") == "thinking" for turn_item in item["turnItems"])
        for item in events
    )
    assert all("feedbackEvents" not in item and "timelineItems" not in item for item in events)
    assert event["done"] is False
    delta_events = [item for item in recorded_events if item[0][2] == "session.assistant_delta.published"]
    snapshot_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.published"]
    assert len(delta_events) == 2
    assert not snapshot_events
    assert all(item[1]["fields"]["contentChars"] == 0 for item in delta_events)
    assert all(item[1]["fields"]["thoughtChars"] == 0 for item in delta_events)
    assert any(item[1]["fields"]["turnItemCount"] >= 1 for item in delta_events)
    fields = delta_events[-1][1]["fields"]
    assert fields["subscriberCount"] == 1


def test_session_live_output_does_not_append_token_level_partials_to_ledger(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=8)
    session_service._register_session_stream_subscriber("session-live", subscriber)
    session_service._set_session_running("session-live", True, turn_id="turn-streaming")
    try:
        for index in range(100):
            session_service._set_session_live_output(
                "session-live",
                turn_id="turn-streaming",
                content=f"chunk {index}",
                thought=f"thought {index}",
                feedback_events=[{"kind": "status", "name": "model_response"}],
            )
        events = load_conversation_events(tmp_path, "session-live")
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-streaming")
        session_service._unregister_session_stream_subscriber("session-live", subscriber)
        session_service._clear_session_live_output("session-live", turn_id="turn-streaming")

    partial_events = [
        event
        for event in events
        if event.event_type == EVENT_ASSISTANT_PARTIAL and event.source == "session_live_output"
    ]
    assert partial_events == []
    assert subscriber.qsize() == 1
    event = subscriber.get_nowait()
    assert event["type"] == "assistant_delta"
    assert any(item.get("type") == "agent_message" and item.get("text") == "chunk 99" for item in event["turnItems"])
    assert any(item.get("type") == "reasoning" and item.get("text") == "thought 99" for item in event["turnItems"])


def test_session_detail_recovers_interrupted_live_output_from_checkpoint(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    append_conversation_event(tmp_path, "session-live", "turn-open", EVENT_TURN_STARTED, status="running")

    session_service._set_session_running("session-live", True, turn_id="turn-open")
    session_service._set_session_live_output(
        "session-live",
        turn_id="turn-open",
        content="已生成但尚未完成的内容。",
        thought="临时思考。",
        feedback_events=[{"kind": "status", "name": "model_response"}],
    )
    with session_service._SESSION_LIVE_OUTPUTS_LOCK:
        session_service._SESSION_LIVE_OUTPUTS.pop("session-live", None)
    session_service._set_session_running("session-live", False, turn_id="turn-open")

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    events = load_conversation_events(tmp_path, "session-live")
    event_types = [event.event_type for event in events]
    assert EVENT_TURN_STARTED in event_types
    assert event_types[-3:] == [session_service.EVENT_ASSISTANT_ITEM_COMMITTED, EVENT_ASSISTANT_MESSAGE, EVENT_TURN_INTERRUPTED]
    reasoning_event = events[-3]
    assert reasoning_event.payload["kind"] == "reasoning"
    assert reasoning_event.payload["text"] == "临时思考。"
    assistant_event = events[-2]
    assert assistant_event.payload["content"] == "已生成但尚未完成的内容。"
    assert assistant_event.payload["thought"] == "临时思考。"
    assert assistant_event.payload["feedbackEvents"][0]["name"] == "model_response"
    assert any(
        message["role"] == "assistant" and _assistant_visible_text(message) == "已生成但尚未完成的内容。"
        for message in response.json()["messages"]
    )


def test_session_detail_recovers_live_checkpoint_without_open_turn_started_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="turn-checkpoint-only")
    session_service._set_session_live_output(
        "session-live",
        turn_id="turn-checkpoint-only",
        content="全部候选已读完，尚未执行阶段回写。",
        thought="正在整理最终回写。",
        feedback_events=[{"kind": "status", "name": "model_response"}],
    )
    session_service._set_session_running("session-live", False, turn_id="turn-checkpoint-only")

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    events = load_conversation_events(tmp_path, "session-live")
    event_types = [event.event_type for event in events]
    assert event_types[-2:] == [EVENT_ASSISTANT_MESSAGE, EVENT_TURN_INTERRUPTED]
    assert events[-1].turn_id == "turn-checkpoint-only"
    assert events[-1].payload["reason"] == "detail_loaded_after_restart"
    assert not session_service._session_live_output_checkpoint_path("session-live").exists()
    messages = response.json()["messages"]
    assert any(
        message["role"] == "assistant"
        and _assistant_visible_text(message) == "全部候选已读完，尚未执行阶段回写。"
        and message.get("metadata", {}).get("interrupted") is True
        for message in messages
    )
    assert not any(
        message.get("metadata", {}).get("kind") == "session_live_overlay"
        or message.get("status") == "running"
        for message in messages
    )


def test_session_detail_snapshot_publish_throttles_busy_snapshots(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(session_service, "_SESSION_STREAM_MIN_BUSY_SNAPSHOT_INTERVAL_SECONDS", 10.0)
    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        session_service._SESSION_STREAM_LAST_SNAPSHOT_AT.pop("session-live", None)
        session_service._SESSION_STREAM_THROTTLED_COUNTS.pop("session-live", None)

    subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=8)
    session_service._register_session_stream_subscriber("session-live", subscriber)
    session_service._set_session_running("session-live", True, turn_id="turn-running")
    try:
        session_service._publish_session_detail_snapshot("session-live")
        session_service._publish_session_detail_snapshot("session-live")
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-running")
        session_service._unregister_session_stream_subscriber("session-live", subscriber)
        with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            session_service._SESSION_STREAM_LAST_SNAPSHOT_AT.pop("session-live", None)
            session_service._SESSION_STREAM_THROTTLED_COUNTS.pop("session-live", None)

    assert subscriber.qsize() == 1
    published_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.published"]
    throttled_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.throttled"]
    assert len(published_events) == 1
    assert len(throttled_events) == 1
    assert throttled_events[0][1]["fields"]["skippedCount"] == 1


def test_session_detail_snapshot_publish_does_not_throttle_terminal_snapshots(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="failed")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(session_service, "_SESSION_STREAM_MIN_BUSY_SNAPSHOT_INTERVAL_SECONDS", 10.0)
    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        session_service._SESSION_STREAM_LAST_SNAPSHOT_AT.pop("session-live", None)
        session_service._SESSION_STREAM_THROTTLED_COUNTS.pop("session-live", None)

    subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=8)
    session_service._register_session_stream_subscriber("session-live", subscriber)
    try:
        session_service._publish_session_detail_snapshot("session-live")
        session_service._publish_session_detail_snapshot("session-live")
    finally:
        session_service._unregister_session_stream_subscriber("session-live", subscriber)
        with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            session_service._SESSION_STREAM_LAST_SNAPSHOT_AT.pop("session-live", None)
            session_service._SESSION_STREAM_THROTTLED_COUNTS.pop("session-live", None)

    assert subscriber.qsize() == 1
    published_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.published"]
    throttled_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.throttled"]
    assert len(published_events) == 2
    assert not throttled_events


def test_session_events_stream_rejects_missing_session():
    response = client.get("/api/sessions/missing-session/events")
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_cli_agent_terminal_stop_route_records_lifecycle_event(monkeypatch):
    recorded = []

    terminal_session = {
        "terminalSessionId": "term-1",
        "sourceSessionId": "session-live",
        "cliRunId": "cli-run-1",
        "adapterId": "mimo_code",
        "label": "MiMo Code",
    }

    def fake_append(session_id, *, event, terminal_session):
        recorded.append((session_id, event, dict(terminal_session)))
        return {
            "id": "session-live-message-2",
            "role": "assistant",
            "content": "MiMo Code 已关闭。",
            "timestamp": "2026-06-14T10:00:00",
            "metadata": {
                "kind": "cli_agent_lifecycle",
                "event": "closed",
                "cliRunId": "cli-run-1",
            },
        }

    monkeypatch.setattr(
        cli_agent_routes,
        "stop_cli_agent_terminal_session",
        lambda terminal_session_id: {**terminal_session, "terminalSessionId": terminal_session_id},
    )
    monkeypatch.setattr(cli_agent_routes, "append_cli_agent_lifecycle_event", fake_append)

    response = client.post("/api/cli-agents/terminal-sessions/term-1/stop")

    assert response.status_code == 200
    payload = response.json()
    assert payload["terminalSessionId"] == "term-1"
    assert payload["lifecycleEvent"]["metadata"]["kind"] == "cli_agent_lifecycle"
    assert payload["lifecycleEvent"]["metadata"]["cliRunId"] == "cli-run-1"
    assert recorded == [("session-live", "closed", {**terminal_session, "terminalSessionId": "term-1"})]


def test_cli_agent_terminal_detail_route_returns_404_for_missing_session(monkeypatch):
    def raise_not_found(*_args, **_kwargs):
        raise cli_agent_routes.CliAgentTerminalError(
            "TERMINAL_SESSION_NOT_FOUND",
            "Terminal session not found.",
        )

    monkeypatch.setattr(cli_agent_routes, "get_cli_agent_terminal_session", raise_not_found)

    response = client.get("/api/cli-agents/terminal-sessions/missing-term")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "TERMINAL_SESSION_NOT_FOUND"


def test_cli_agent_terminal_events_route_returns_409_when_session_not_running(monkeypatch):
    def raise_not_running(*_args, **_kwargs):
        raise cli_agent_routes.CliAgentTerminalError(
            "TERMINAL_SESSION_NOT_RUNNING",
            "Terminal session is not running.",
        )

    monkeypatch.setattr(cli_agent_routes, "get_cli_agent_terminal_session", raise_not_running)

    response = client.get("/api/cli-agents/terminal-sessions/term-1/events")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TERMINAL_SESSION_NOT_RUNNING"


def test_cli_agent_terminal_input_route_returns_409_when_session_not_running(monkeypatch):
    def raise_not_running(_terminal_session_id, _data):
        raise cli_agent_routes.CliAgentTerminalError(
            "TERMINAL_SESSION_NOT_RUNNING",
            "Terminal session is not running.",
        )

    monkeypatch.setattr(cli_agent_routes, "write_cli_agent_terminal_input", raise_not_running)

    response = client.post(
        "/api/cli-agents/terminal-sessions/term-1/input",
        json={"data": "pwd"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TERMINAL_SESSION_NOT_RUNNING"


def test_cli_agent_terminal_resize_route_returns_404_for_missing_session(monkeypatch):
    def raise_not_found(_terminal_session_id, _rows, _cols):
        raise cli_agent_routes.CliAgentTerminalError(
            "TERMINAL_SESSION_NOT_FOUND",
            "Terminal session not found.",
        )

    monkeypatch.setattr(cli_agent_routes, "resize_cli_agent_terminal_session", raise_not_found)

    response = client.post(
        "/api/cli-agents/terminal-sessions/term-1/resize",
        json={"rows": 24, "cols": 80},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "TERMINAL_SESSION_NOT_FOUND"


def test_submit_session_message_rejects_archived_agent_without_mutating_session(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    detail = session_service.create_chat_session(title="归档 Agent")
    agent_directory_service.archive_agent_instance(detail["agentId"])
    events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: pytest.fail("archived Agent sessions must not schedule turns"),
    )

    with pytest.raises(session_service.SessionValidationError, match="已归档|archived"):
        session_service.submit_session_message(detail["id"], "这条消息不应该进入运行队列")

    state = load_chat_state(tmp_path)
    conversation = state["conversations"][0]
    assert "messages" not in conversation
    assert load_conversation_events(tmp_path, detail["id"]) == []
    blocked_events = [item for item in events if item[0][2] == "conversation.turn.blocked_archived_agent"]
    assert len(blocked_events) == 1
    assert blocked_events[0][1]["fields"]["agentId"] == detail["agentId"]


def test_edit_resubmit_session_message_rejects_archived_agent_without_mutating_session(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    detail = session_service.create_chat_session(title="归档重发 Agent")
    append_conversation_event(
        tmp_path,
        detail["id"],
        "turn-original",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "原始消息"},
        timestamp="2026-05-29T08:40:00+00:00",
    )
    agent_directory_service.archive_agent_instance(detail["agentId"])
    events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: pytest.fail("archived Agent edit-resubmit must not schedule turns"),
    )

    with pytest.raises(session_service.SessionValidationError, match="已归档|archived"):
        session_service.edit_and_resubmit_session_message(
            detail["id"],
            f"{detail['id']}-message-1",
            "编辑后的消息不应进入运行队列",
        )

    next_state = load_chat_state(tmp_path)
    next_conversation = next_state["conversations"][0]
    assert "messages" not in next_conversation
    assert session_service.get_session_detail(detail["id"])["messages"][0]["content"] == "原始消息"
    assert next_conversation.get("last_turn_status") != "running"
    blocked_events = [item for item in events if item[0][2] == "conversation.turn.blocked_archived_agent"]
    assert len(blocked_events) == 1
    assert blocked_events[0][1]["fields"]["agentId"] == detail["agentId"]


def test_run_session_turn_blocks_if_agent_archived_after_scheduling(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _dialogue_cfg = session_service.get_config()
    _dialogue_profile = _dialogue_cfg.llm.get_profile(role="primary")
    _dialogue_model_id, _ = _dialogue_cfg.llm.get_model_library_entry_for_profile(_dialogue_profile)
    detail = session_service.create_chat_session(
        title="排队后归档 Agent",
        llm_bindings={"dialogue": {"modelId": str(_dialogue_model_id or "").strip()}},
    )
    scheduled_contexts = []
    events = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(context))
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "create_chat_agent",
        lambda **_kwargs: pytest.fail("archived Agent worker must not create runtime"),
    )

    session_service.submit_session_message(detail["id"], "这条消息排队后 Agent 会被归档")
    assert len(scheduled_contexts) == 1

    agent_directory_service.archive_agent_instance(detail["agentId"])
    session_service._run_session_turn(scheduled_contexts[0])

    next_detail = session_service.get_session_detail(detail["id"])
    assert next_detail["currentPhase"] == "failed"
    assert "已归档" in next_detail["lastTurnError"]["message"]
    blocked_events = [item for item in events if item[0][2] == "conversation.turn.blocked_archived_agent"]
    assert len(blocked_events) == 1
    assert blocked_events[0][1]["fields"]["agentId"] == detail["agentId"]


def test_submit_session_message_runs_turn_and_persists_reply(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="done")
    _bind_seeded_submittable_agent(tmp_path)
    _bind_seeded_submittable_agent(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    base_config.llm.get_provider(primary_profile.provider_id)
    dialogue_model_id = primary_profile.model_ref
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    session_agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="真实会话",
        llm_bindings={"dialogue": {"modelId": dialogue_model_id}},
        prompt_template_id="prompt-chat-default",
    )
    _bind_seeded_session_agent(tmp_path, session_agent)
    session_service._invalidate_session_list_cache()
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            assert "ChatCodingRoute.tsx" in initial_prompt
            return {
                "status": "completed",
                "summary": "已完成网页对话提交接线。",
                "raw_output": "已完成网页对话提交接线。",
                "reasoning_content": "先确认消息模型，再把思考与心智快照一起落盘。",
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "主链路已经清楚了。",
                    "whisper": "把思考和回答放在同一张卡片里。",
                    "summary": "主链路已经清楚了。",
                    "cognitiveState": "productive",
                    "confidence": 0.86,
                    "sampleSize": 4,
                    "interventionCount": 1,
                    "updatedAt": "2026-05-18T12:01:00",
                    "source": "state",
                },
                "outcome": "done",
                "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
                "changed_files": ["core/web/services/session_service.py"],
                "verification_status": "passed",
                "verification_summary": "2 passed in 0.31s",
                "tool_call_count": 2,
                "tool_trace": [
                    {"name": "read_file_tool"},
                    {"function": {"name": "apply_patch_tool"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={
            "clientSubmissionId": "submission-web-app-1",
            "content": "请继续修复 web/src/routes/ChatCodingRoute.tsx 并验证",
            "mentalModelEnabled": True,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "assistant"
    _assert_v3_assistant_message(payload["messages"][-1])
    assert _assistant_visible_text(payload["messages"][-1]) == "已完成网页对话提交接线。"
    assert [item["text"] for item in _assistant_turn_items(payload["messages"][-1], "reasoning")] == [
        "先确认消息模型，再把思考与心智快照一起落盘。"
    ]
    mental_snapshot = _assistant_status_metadata(payload["messages"][-1], "mental_snapshot").get("mentalSnapshot") or {}
    assert mental_snapshot["mood"] == "专注"
    assert mental_snapshot["cognitiveState"] == "productive"
    assert _assistant_tool_summaries(payload["messages"][-1]) == [
        {"name": "read_file_tool", "status": "completed"},
        {"name": "apply_patch_tool", "status": "completed"},
    ]
    assert payload["taskSummary"] == "已完成网页对话提交接线。"
    assert payload["currentPhase"] == "ready"
    assert payload["readFiles"] == []
    assert payload["changedFiles"] == []
    assert payload["defaultFileContext"] == ""
    assert payload["previewTabs"] == []
    assert payload["activePreviewPath"] == "agent"
    assert payload["activeTask"] is None
    assert "active_task" not in load_chat_state(tmp_path)["conversations"][0]
    turn_events = [
        (args[2], kwargs)
        for args, kwargs in recorded_scene_events
        if len(args) >= 3 and str(args[2]).startswith("conversation.turn.")
    ]
    event_codes = [event_code for event_code, _kwargs in turn_events]
    for expected in [
        "conversation.turn.started",
        "conversation.turn.scheduled",
        "conversation.turn.worker_started",
        "conversation.turn.ui_capture_started",
        "conversation.turn.agent_created",
        "conversation.turn.history_assembled",
        "conversation.turn.agent_turn_started",
        "conversation.turn.agent_turn_returned",
        "conversation.turn.terminal_result",
        "conversation.turn.capture_attached",
        "conversation.turn.result_persisted",
        "conversation.turn.user_visible_finished",
        "conversation.turn.worker_finished",
    ]:
        assert expected in event_codes
    persisted_event = next(kwargs for event_code, kwargs in turn_events if event_code == "conversation.turn.result_persisted")
    assert persisted_event["outcome"] == "completed"
    assert persisted_event["fields"]["sessionId"] == "session-live"
    assert persisted_event["fields"]["assistantTextLength"] == len("已完成网页对话提交接线。")
    assert persisted_event["child_log_path"] == "conversations/session-live-turns.jsonl"
    capture_event = next(kwargs for event_code, kwargs in turn_events if event_code == "conversation.turn.capture_attached")
    assert capture_event["outcome"] == "recorded"
    assert event_codes.index("conversation.turn.result_persisted") < event_codes.index("conversation.turn.user_visible_finished")
    assert event_codes.index("conversation.turn.user_visible_finished") < event_codes.index("conversation.turn.worker_finished")


def test_session_worker_uses_unbounded_history_seed_for_direct_chat(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    session_agent = agent_directory_service.create_agent_instance(
        display_name="Full History Seed Agent",
        primary_mode="chat",
    )
    _bind_seeded_session_agent(tmp_path, session_agent)
    captured_limits: list[object] = []
    original_assembler = session_service.assemble_conversation_context

    class DummyAgent:
        def seed_chat_history(self, _messages):
            return None

        def run_single_turn(self, initial_prompt=None, attachments=None):
            return {"status": "completed", "summary": "ok", "raw_output": "ok", "outcome": "done"}

    def capture_assembler(*args, **kwargs):
        captured_limits.append(kwargs.get("recent_message_limit", "missing"))
        return original_assembler(*args, **kwargs)

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(session_service, "assemble_conversation_context", capture_assembler)
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请完整保留此前未压缩的对话上下文"},
    )

    assert response.status_code == 202
    assert captured_limits == [None]


def test_session_submit_message_routes_slash_skill_into_scheduled_context(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    session_agent = agent_directory_service.create_agent_instance(
        display_name="Slash Skill Agent",
        primary_mode="chat",
    )
    _bind_seeded_session_agent(tmp_path, session_agent)
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nStop before implementation.\n",
        encoding="utf-8",
    )
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        session_service,
        "parse_skill_slash_command",
        lambda content: parse_skill_slash_command(content, skill_roots=[skill_root]),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "/brt 设计斜杠 skill 调用"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "/brt 设计斜杠 skill 调用"
    persisted_skill = payload["messages"][-2]["metadata"]["slashSkillCommand"]
    assert persisted_skill["command"] == "brt"
    assert persisted_skill["skillName"] == "brt"
    assert persisted_skill["skillHash"]
    assert "content" not in persisted_skill
    assert payload["activeSkillContract"]["command"] == "brt"
    assert payload["activeSkillContract"]["skillName"] == "brt"
    assert payload["activeSkillContract"]["skillHash"]
    assert "content" not in payload["activeSkillContract"]
    assert "Stop before implementation." not in json.dumps(payload["activeSkillContract"], ensure_ascii=False)
    assert len(scheduled_contexts) == 1
    invocation = scheduled_contexts[0]["skill_invocation"]
    assert invocation["command"] == "brt"
    assert invocation["args"] == "设计斜杠 skill 调用"
    assert invocation["skillName"] == "brt"
    assert invocation["skillHash"]
    assert scheduled_contexts[0]["active_skill_contract"]["command"] == "brt"


def test_session_worker_seeds_slash_skill_runtime_context(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    _bind_seeded_submittable_agent(tmp_path)
    session_agent = agent_directory_service.create_agent_instance(
        display_name="Slash Skill Runtime Agent",
        primary_mode="chat",
    )
    _bind_seeded_session_agent(tmp_path, session_agent)
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nAsk one question at a time.\n",
        encoding="utf-8",
    )
    seen_contexts: list[str] = []
    marker_calls: list[str] = []
    seen_prompt: dict[str, str] = {}
    scene_events: list[dict] = []
    lifecycle_events: list[dict] = []

    class DummyAgent:
        def set_mental_model_enabled_override(self, _enabled):
            pass

        def seed_chat_history(self, _messages):
            pass

        def seed_static_runtime_context(self, content):
            seen_contexts.append(f"static:{content}")

        def seed_runtime_context(self, content):
            seen_contexts.append(f"dynamic:{content}")

        def seed_volatile_runtime_context(self, content):
            seen_contexts.append(f"volatile:{content}")

        def mark_runtime_context_seeded_by_host(self):
            marker_calls.append("marked")

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen_prompt["value"] = initial_prompt
            return {"status": "completed", "summary": "ok", "raw_output": "ok", "outcome": "done"}

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_resolve_session_agent_llm",
        lambda *_args, **_kwargs: SimpleNamespace(
            model_id="test-dialogue-model",
            config=SimpleNamespace(),
            log_fields=lambda: {"llmModelId": "test-dialogue-model"},
        ),
    )
    _install_session_turn_scheduler(monkeypatch, max_active_per_agent=1)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda *_args, **_kwargs: SimpleNamespace(
            memory_policy={},
            static_context_block="## Agent Static Context\nstable",
            dynamic_context_block="## Agent Runtime Context\nvolatile",
            context_block="## Agent Static Context\nstable\n\n## Agent Runtime Context\nvolatile",
            context_segments=[
                {
                    "key": "agent_static",
                    "block": "## Agent Static Context\nstable",
                    "placement": "cache_prefix",
                },
                {
                    "key": "agent_runtime",
                    "block": "## Agent Runtime Context\nvolatile",
                    "placement": "volatile_turn",
                },
            ],
            timings={},
        ),
    )
    monkeypatch.setattr(
        session_service,
        "parse_skill_slash_command",
        lambda content: parse_skill_slash_command(content, skill_roots=[skill_root]),
    )
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: scene_events.append(
            {"component": component, "phase": phase, "eventCode": event_code, **kwargs}
        ),
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: lifecycle_events.append(
            {"sessionId": session_id, "phase": phase, **kwargs}
        ),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "/brt 设计斜杠 skill 调用"},
    )

    assert response.status_code == 202
    assert seen_prompt["value"] == "/brt 设计斜杠 skill 调用"
    assert len(seen_contexts) == 3
    assert "## Agent Static Context\nstable" in seen_contexts[0]
    assert seen_contexts[1] == "volatile:## Agent Runtime Context\nvolatile"
    assert seen_contexts[2].startswith("volatile:## Slash Skill Context")
    assert "Command: /brt" in seen_contexts[2]
    assert "Ask one question at a time." in seen_contexts[2]
    assert marker_calls
    history_assembled_events = [event for event in lifecycle_events if event["phase"] == "history_assembled"]
    assert history_assembled_events
    history_fields = history_assembled_events[-1]["fields"]
    assert history_fields["assembledHistoryMessageCount"] >= 1
    assert history_fields["historyAssemblyMs"] >= 0
    assert history_fields["staticRuntimeContextIncluded"] is True
    assert history_fields["dynamicRuntimeContextIncluded"] is True
    assert history_fields["dynamicRuntimeContextAvailable"] is True
    assert history_fields["dynamicRuntimeContextOmittedFromModelInput"] is False
    assert history_fields["skillRuntimeContextIncluded"] is True
    assert history_fields["skillRuntimeContextAvailable"] is True
    assert history_fields["skillRuntimeContextOmittedFromModelInput"] is False
    assert history_fields["skillRuntimeContextPlacement"] == "before_current_user"
    assert history_fields["runtimeContextSegmentCount"] == 3
    assert history_fields["staticRuntimeContextSeedAvailable"] is True
    assert history_fields["runtimeContextSeedAvailable"] is True
    assert history_fields["volatileRuntimeContextSeedAvailable"] is True
    assert any(event["eventCode"] == "conversation.skill_command.routed" for event in scene_events)


def test_session_worker_seeds_active_skill_contract_on_later_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    session_agent = agent_directory_service.create_agent_instance(
        display_name="Active Skill Runtime Agent",
        primary_mode="chat",
    )
    _bind_seeded_session_agent(tmp_path, session_agent)
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\n- Ask one question at a time.\n",
        encoding="utf-8",
    )
    command = parse_skill_slash_command("/brt 设计斜杠 skill 调用", skill_roots=[skill_root])
    invocation = session_service._skill_invocation_payload(command)
    contract = session_service._active_skill_contract_from_invocation(invocation, turn_id="previous-turn")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["active_skill_contract"] = contract
    save_chat_state(tmp_path, state)

    seen_contexts: list[str] = []
    seen_prompt: dict[str, str] = {}
    lifecycle_events: list[dict] = []

    class DummyAgent:
        def set_mental_model_enabled_override(self, _enabled):
            pass

        def seed_chat_history(self, _messages):
            pass

        def seed_static_runtime_context(self, content):
            seen_contexts.append(f"static:{content}")

        def seed_volatile_runtime_context(self, content):
            seen_contexts.append(f"volatile:{content}")

        def mark_runtime_context_seeded_by_host(self):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen_prompt["value"] = initial_prompt
            return {"status": "completed", "summary": "ok", "raw_output": "ok", "outcome": "done"}

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_resolve_session_agent_llm",
        lambda *_args, **_kwargs: SimpleNamespace(
            model_id="test-dialogue-model",
            config=SimpleNamespace(),
            log_fields=lambda: {"llmModelId": "test-dialogue-model"},
        ),
    )
    _install_session_turn_scheduler(monkeypatch, max_active_per_agent=1)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda *_args, **_kwargs: SimpleNamespace(
            memory_policy={},
            static_context_block="## Agent Static Context\nstable",
            dynamic_context_block="",
            context_block="## Agent Static Context\nstable",
            context_segments=[
                {
                    "key": "agent_static",
                    "block": "## Agent Static Context\nstable",
                    "placement": "cache_prefix",
                },
            ],
            timings={},
        ),
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: lifecycle_events.append(
            {"sessionId": session_id, "phase": phase, **kwargs}
        ),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    assert seen_prompt["value"]
    volatile_contexts = [item for item in seen_contexts if item.startswith("volatile:")]
    assert len(volatile_contexts) == 1
    assert volatile_contexts[0].startswith("volatile:## Active Skill Context")
    assert "Command: /brt" in volatile_contexts[0]
    assert "Ask one question at a time." in volatile_contexts[0]
    assert "## Slash Skill Context" not in volatile_contexts[0]
    assert "SKILL.md:" not in volatile_contexts[0]
    history_assembled_events = [event for event in lifecycle_events if event["phase"] == "history_assembled"]
    assert history_assembled_events
    history_fields = history_assembled_events[-1]["fields"]
    assert history_fields["assembledHistoryMessageCount"] >= 1
    assert history_fields["historyAssemblyMs"] >= 0
    assert history_fields["activeSkillContractAvailable"] is True
    assert history_fields["activeSkillContextIncluded"] is True
    assert history_fields["activeSkillContextPlacement"] == "before_current_user"
    detail = response.json()
    assert detail["lastContextComposition"]["cache"]["volatileSegmentCount"] >= 1
    assert any(
        item["key"] == "active_skill"
        and item["includedInModelInput"] is True
        and item["placement"] == "before_current_user"
        for item in detail["lastContextComposition"]["segments"]
    )


def test_edit_resubmit_session_message_routes_slash_skill_into_scheduled_context(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:03:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-18T12:03:00",
                    "last_turn_status": "ready",
                }
            ],
        },
    )
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    session_agent = agent_directory_service.create_agent_instance(
        display_name="Edit Resubmit Slash Agent",
        primary_mode="chat",
    )
    _bind_seeded_session_agent(tmp_path, session_agent)
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-original",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "原始需求"},
        timestamp="2026-05-18T12:00:00",
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-original",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "原始回答"},
        timestamp="2026-05-18T12:01:00",
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-followup",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "后续追问"},
        timestamp="2026-05-18T12:02:00",
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-followup",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "后续回答"},
        timestamp="2026-05-18T12:03:00",
    )
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nStop before implementation.\n",
        encoding="utf-8",
    )
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        session_service,
        "parse_skill_slash_command",
        lambda content: parse_skill_slash_command(content, skill_roots=[skill_root]),
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": "session-live-message-3",
            "content": "/brt 重新设计斜杠入口",
            "mentalModelEnabled": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "/brt 重新设计斜杠入口"
    persisted_skill = payload["messages"][-2]["metadata"]["slashSkillCommand"]
    assert persisted_skill["command"] == "brt"
    assert persisted_skill["skillName"] == "brt"
    assert persisted_skill["skillHash"]
    assert "content" not in persisted_skill
    assert payload["activeSkillContract"]["command"] == "brt"
    assert payload["activeSkillContract"]["skillName"] == "brt"
    assert len(scheduled_contexts) == 1
    invocation = scheduled_contexts[0]["skill_invocation"]
    assert invocation["command"] == "brt"
    assert invocation["args"] == "重新设计斜杠入口"
    assert invocation["skillName"] == "brt"
    assert scheduled_contexts[0]["active_skill_contract"]["command"] == "brt"

    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")
    session_service._clear_session_live_output("session-live")


def test_session_user_image_attachment_upload_and_submit_reaches_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].supports_image_input = True
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    vision_model_id = primary_model_id or "vision-upload-test-model"
    base_config.llm.model_library[vision_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "vision-upload-test"),
        "label": str((primary_model_entry or {}).get("label") or "vision-upload-test"),
        "supports_image_input": True,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": vision_model_id},
                "vision": {"modelId": vision_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {
                "status": "completed",
                "summary": "我已经看到了图片。",
                "raw_output": "我已经看到了图片。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201
    attachment = upload_response.json()

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析这张图", "attachmentIds": [attachment["artifactId"]], "mentalModelEnabled": False},
    )

    assert response.status_code == 202
    payload = response.json()
    user_message = payload["messages"][-2]
    assert user_message["attachments"][0]["artifactId"] == attachment["artifactId"]
    assert user_message["attachments"][0]["filename"] == "sketch.png"
    assert seen["initial_prompt"] == "分析这张图"
    seen_attachment = seen["attachments"][0]
    assert seen_attachment["artifactId"] == attachment["artifactId"]
    assert seen_attachment["dataUrl"].startswith("data:image/png;base64,")

    state = load_chat_state(tmp_path)
    assert "messages" not in state["conversations"][0]
    stored_user = session_service.get_session_detail("session-live")["messages"][-2]
    assert stored_user["attachments"][0]["artifactId"] == attachment["artifactId"]
    assert "dataUrl" not in stored_user["attachments"][0]


def test_session_user_image_attachment_vision_intent_blocks_unsupported_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].supports_image_input = False
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    if primary_model_id and isinstance(primary_model_entry, dict):
        base_config.llm.model_library[primary_model_id]["supports_image_input"] = False
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={"dialogue": {"modelId": primary_model_id or "model-primary"}},
            prompt_template_id="prompt-chat-default",
        ),
    )
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析这张图里有什么", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "failed"
    assert "明确不支持图像输入" in str((payload.get("lastTurnError") or {}).get("message") or "")
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["last_turn_status"] == "failed"


def test_session_user_image_attachment_picture_content_phrase_stays_vision_intent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].supports_image_input = False
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    if primary_model_id and isinstance(primary_model_entry, dict):
        base_config.llm.model_library[primary_model_id]["supports_image_input"] = False
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={"dialogue": {"modelId": primary_model_id or "model-primary"}},
            prompt_template_id="prompt-chat-default",
        ),
    )
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "画面里有什么", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    _img_payload = response.json()
    assert _img_payload["currentPhase"] == "failed"
    assert "明确不支持图像输入" in _img_payload["lastTurnError"]["message"]


def test_session_user_image_attachment_vision_intent_reaches_supported_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].supports_image_input = True
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    vision_model_id = primary_model_id or "vision-intent-test-model"
    base_config.llm.model_library[vision_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "vision-intent-test"),
        "label": str((primary_model_entry or {}).get("label") or "vision-intent-test"),
        "supports_image_input": True,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": vision_model_id},
                "vision": {"modelId": vision_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {"status": "completed", "summary": "看到了图片。", "raw_output": "看到了图片。", "outcome": "done"}

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析这张图", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    assert seen["initial_prompt"] == "分析这张图"
    assert seen["attachments"][0]["dataUrl"].startswith("data:image/png;base64,")


def test_session_recent_image_reference_reuses_last_user_attachment_for_vision(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].supports_image_input = True
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    vision_model_id = primary_model_id or "vision-recent-reference-test-model"
    base_config.llm.model_library[vision_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "vision-recent-reference-test"),
        "label": str((primary_model_entry or {}).get("label") or "vision-recent-reference-test"),
        "supports_image_input": True,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": vision_model_id},
                "vision": {"modelId": vision_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen_turns: list[dict[str, object]] = []

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen_turns.append({"initial_prompt": initial_prompt, "attachments": list(attachments or [])})
            return {"status": "completed", "summary": "看到了图片。", "raw_output": "看到了图片。", "outcome": "done"}

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201
    artifact_id = upload_response.json()["artifactId"]

    first = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析这张图", "attachmentIds": [artifact_id]},
    )
    assert first.status_code == 202

    second = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "再看一下刚才那张图"},
    )

    assert second.status_code == 202
    assert seen_turns[-1]["initial_prompt"] == "再看一下刚才那张图"
    assert seen_turns[-1]["attachments"][0]["artifactId"] == artifact_id
    assert seen_turns[-1]["attachments"][0]["dataUrl"].startswith("data:image/png;base64,")
    latest_user = [message for message in second.json()["messages"] if message["role"] == "user"][-1]
    assert latest_user["attachments"][0]["artifactId"] == artifact_id
    assert latest_user["metadata"]["resolvedRecentImageReference"]["status"] == "resolved"


def test_session_user_image_attachment_vision_support_inherits_model_library(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    profile = base_config.llm.profiles["primary"]
    profile.supports_image_input = None
    mimo_model_id = ""
    for item in base_config.llm.model_library.values():
        if isinstance(item, dict) and item.get("model") == "mimo-v2.5":
            item["supports_image_input"] = True
    for model_id, item in base_config.llm.model_library.items():
        if isinstance(item, dict) and item.get("model") == "mimo-v2.5":
            mimo_model_id = str(model_id)
            break
    if not mimo_model_id:
        primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(profile)
        provider_id = str((primary_model_entry or {}).get("provider_id") or profile.provider_id)
        mimo_model_id = "xiaomi-mimo-v25-test"
        base_config.llm.model_library[mimo_model_id] = {
            "provider_id": provider_id,
            "model": "mimo-v2.5",
            "label": "mimo-v2.5",
            "supports_image_input": True,
        }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": mimo_model_id},
                "vision": {"modelId": mimo_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen: dict[str, object] = {}
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {"status": "completed", "summary": "看到了图片。", "raw_output": "看到了图片。", "outcome": "done"}

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "向我描述一下这个图片", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    assert seen["initial_prompt"] == "向我描述一下这个图片"
    assert seen["attachments"][0]["dataUrl"].startswith("data:image/png;base64,")
    router_events = [
        kwargs for args, kwargs in recorded_scene_events
        if args[:3] == ("conversation", "image_attachment_capability", "conversation.image_attachment.capability_checked")
    ]
    assert router_events
    assert router_events[-1]["fields"]["decision"] == "forwarded"
    assert router_events[-1]["fields"]["reason"] == "supported"
    assert router_events[-1]["fields"]["supportsImageInput"] is True
    assert router_events[-1]["fields"]["modelName"] == "mimo-v2.5"


def test_session_user_image_attachment_uses_dialogue_slot_not_vision_slot(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    dialogue_model_id, dialogue_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    if not dialogue_model_id:
        dialogue_model_id = "dialogue-no-vision-test"
    provider_id = str((dialogue_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    base_config.llm.model_library[dialogue_model_id] = {
        **dict(dialogue_model_entry or {}),
        "provider_id": provider_id,
        "model": "dialogue-multimodal",
        "label": "dialogue-multimodal",
        "supports_image_input": True,
    }
    vision_model_id = "vision-slot-model-test"
    base_config.llm.model_library[vision_model_id] = {
        "provider_id": provider_id,
        "model": "vision-slot-unused",
        "label": "vision-slot-unused",
        "supports_image_input": False,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": dialogue_model_id},
                "vision": {"modelId": vision_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen: dict[str, object] = {}
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {"status": "completed", "summary": "看到了图片。", "raw_output": "看到了图片。", "outcome": "done"}

    def fake_create_chat_agent(**kwargs):
        seen["runtime_model"] = kwargs["config"].llm.profiles["primary"].model
        return DummyAgent()

    monkeypatch.setattr(session_service, "create_chat_agent", fake_create_chat_agent)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析这张图里有什么", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    assert seen["runtime_model"] == "dialogue-multimodal"
    assert seen["attachments"][0]["dataUrl"].startswith("data:image/png;base64,")
    router_events = [
        kwargs for args, kwargs in recorded_scene_events
        if args[:3] == ("conversation", "image_attachment_capability", "conversation.image_attachment.capability_checked")
    ]
    assert router_events
    assert router_events[-1]["fields"]["decision"] == "forwarded"
    assert router_events[-1]["fields"]["reason"] == "supported"
    assert router_events[-1]["fields"]["llmSlot"] == "dialogue"
    assert router_events[-1]["fields"]["llmModelId"] == dialogue_model_id
    assert router_events[-1]["fields"]["dialogueModelId"] == dialogue_model_id
    assert router_events[-1]["fields"]["visionModelId"] == vision_model_id


def test_session_user_image_attachment_edit_intent_reaches_supported_multimodal_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(
        "tools.image2_tools.image2_generate_tool",
        lambda **kwargs: pytest.fail("supported multimodal models must receive image input before image2"),
    )
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    vision_model_id = primary_model_id or "mimo-edit-intent-test-model"
    base_config.llm.model_library[vision_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "mimo-v2.5-pro"),
        "label": str((primary_model_entry or {}).get("label") or "mimo-edit-intent-test-model"),
        "supports_image_input": True,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": vision_model_id},
                "vision": {"modelId": vision_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen: dict[str, object] = {}
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {
                "status": "completed",
                "summary": "我已先查看图片并准备调整方案。",
                "raw_output": "我已先查看图片并准备调整方案。",
                "outcome": "done",
            }

    def fake_create_chat_agent(**kwargs):
        seen["runtime_model"] = kwargs["config"].llm.profiles["primary"].model
        return DummyAgent()

    monkeypatch.setattr(session_service, "create_chat_agent", fake_create_chat_agent)

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201
    artifact_id = upload_response.json()["artifactId"]

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "把这张图改成 2D 卡通头像", "attachmentIds": [artifact_id]},
    )

    assert response.status_code == 202
    assert seen["initial_prompt"] == "把这张图改成 2D 卡通头像"
    assert seen["runtime_model"] == base_config.llm.model_library[vision_model_id]["model"]
    assert seen["attachments"][0]["artifactId"] == artifact_id
    assert seen["attachments"][0]["dataUrl"].startswith("data:image/png;base64,")
    router_events = [
        kwargs for args, kwargs in recorded_scene_events
        if args[:3] == ("conversation", "image_attachment_capability", "conversation.image_attachment.capability_checked")
    ]
    assert router_events
    assert router_events[-1]["fields"]["decision"] == "forwarded"
    assert router_events[-1]["fields"]["reason"] == "supported"
    assert router_events[-1]["fields"]["llmSlot"] == "dialogue"
    assert router_events[-1]["fields"]["supportsImageInput"] is True


def test_session_user_image_attachment_edit_intent_blocks_when_agent_cannot_read_images(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    dialogue_model_id = primary_model_id or "image2-fallback-no-vision-model"
    base_config.llm.model_library[dialogue_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "image2-fallback-no-vision"),
        "label": str((primary_model_entry or {}).get("label") or "image2-fallback-no-vision"),
        "supports_image_input": False,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": dialogue_model_id},
                "vision": {"modelId": dialogue_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    monkeypatch.setattr(
        "tools.image2_tools.image2_generate_tool",
        lambda **kwargs: pytest.fail("image2 must be called by the model tool protocol, not the session entry"),
    )
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201
    artifact_id = upload_response.json()["artifactId"]

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "把这张图改成 2D 卡通头像", "attachmentIds": [artifact_id]},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "failed"
    assert "明确不支持图像输入" in str((payload.get("lastTurnError") or {}).get("message") or "")
    router_events = [
        kwargs for args, kwargs in recorded_scene_events
        if args[:3] == ("conversation", "image_attachment_capability", "conversation.image_attachment.capability_checked")
    ]
    assert router_events
    assert router_events[-1]["fields"]["decision"] == "blocked"
    assert router_events[-1]["fields"]["reason"] == "unsupported_image_input"
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["last_turn_status"] == "failed"


def test_session_recent_image_reference_blocks_when_agent_cannot_read_images(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    dialogue_model_id = primary_model_id or "recent-image2-fallback-no-vision-model"
    base_config.llm.model_library[dialogue_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "recent-image2-fallback-no-vision"),
        "label": str((primary_model_entry or {}).get("label") or "recent-image2-fallback-no-vision"),
        "supports_image_input": False,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": dialogue_model_id},
                "vision": {"modelId": dialogue_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    monkeypatch.setattr(
        "tools.image2_tools.image2_generate_tool",
        lambda **kwargs: pytest.fail("image2 must be called by the model tool protocol, not the session entry"),
    )
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201
    artifact_id = upload_response.json()["artifactId"]

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "把刚才那张图改成 2D 卡通头像"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "failed"
    assert "明确不支持图像输入" in str((payload.get("lastTurnError") or {}).get("message") or "")
    router_events = [
        kwargs for args, kwargs in recorded_scene_events
        if args[:3] == ("conversation", "image_attachment_capability", "conversation.image_attachment.capability_checked")
    ]
    assert router_events
    assert router_events[-1]["fields"]["decision"] == "blocked"
    assert router_events[-1]["fields"]["reason"] == "unsupported_image_input"
    latest_user = [message for message in response.json()["messages"] if message["role"] == "user"][-1]
    assert latest_user["metadata"]["resolvedRecentImageReference"]["status"] == "resolved"
    assert latest_user["metadata"]["resolvedRecentImageReference"]["artifactIds"] == [artifact_id]


def test_session_contextual_retry_restores_recent_image_attachment_for_supported_multimodal_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(
        "tools.image2_tools.image2_generate_tool",
        lambda **kwargs: pytest.fail("contextual retry must return to the dialogue model, not image2"),
    )
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    vision_model_id = primary_model_id or "contextual-retry-vision-model"
    base_config.llm.model_library[vision_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "contextual-retry-vision"),
        "label": str((primary_model_entry or {}).get("label") or "contextual-retry-vision"),
        "supports_image_input": True,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": vision_model_id},
                "vision": {"modelId": vision_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen_turns: list[dict[str, object]] = []

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen_turns.append(
                {
                    "initial_prompt": initial_prompt,
                    "attachments": list(attachments or []),
                }
            )
            return {
                "status": "completed",
                "summary": "已读取图片并继续处理。",
                "raw_output": "已读取图片并继续处理。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: DummyAgent())

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "generated.png"},
    )
    assert upload_response.status_code == 201
    artifact_id = upload_response.json()["artifactId"]

    first = client.post(
        "/api/sessions/session-live/messages",
        json={
            "content": "这是你生成的图片,跟原来的图片完全不一样,你需要继续调整提示词,来逼近原来的图片",
            "attachmentIds": [artifact_id],
        },
    )
    assert first.status_code == 202

    second = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你再试试,应该可以了"},
    )

    assert second.status_code == 202
    assert len(seen_turns) == 2
    assert seen_turns[-1]["attachments"][0]["artifactId"] == artifact_id
    assert seen_turns[-1]["initial_prompt"] == "这是你生成的图片,跟原来的图片完全不一样,你需要继续调整提示词,来逼近原来的图片"
    latest_user = [message for message in second.json()["messages"] if message["role"] == "user"][-1]
    assert latest_user["metadata"]["resolvedRecentImageReference"]["status"] == "resolved"
    assert latest_user["metadata"]["resolvedRecentImageReference"]["source"] == "contextual_retry"


def test_session_contextual_retry_ignores_active_task_image_clarification(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="done",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "editing",
            "title": "打开 mimo_cli",
            "goal": "打开 mimo_cli",
            "latest_summary": "我看到你发送了图片。你想让我分析这张图片，还是基于它生成/调整图片？请补一句你的目标。",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_seeded_submittable_agent(tmp_path)
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        "tools.image2_tools.image2_generate_tool",
        lambda **kwargs: pytest.fail("plain continue must not be routed to image2"),
    )

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "state.png"},
    )
    assert upload_response.status_code == 201
    artifact = upload_response.json()
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-image-history",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={
            "content": "我刚才点击了测试,还是显示不支持图像为什么",
            "attachments": [artifact],
        },
        timestamp="2026-05-18T11:58:00",
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-image-history",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "我看到你发送了图片。你想让我分析这张图片，还是基于它生成/调整图片？请补一句你的目标。"},
        timestamp="2026-05-18T11:59:00",
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-image-retry",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={
            "content": "继续",
            "metadata": {
                "resolvedRecentImageReference": {
                    "status": "resolved",
                    "source": "contextual_retry",
                    "prompt": "我看到你发送了图片。你想让我分析这张图片，还是基于它生成/调整图片？请补一句你的目标。",
                    "artifactIds": [artifact["artifactId"]],
                }
            },
        },
        timestamp="2026-05-18T12:00:00",
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-image-retry",
        EVENT_ASSISTANT_MESSAGE,
        status="failed",
        payload={
            "content": "图片生成失败：image2 provider returned 401",
            "metadata": {
                "kind": "turn_error",
                "reasonCode": "auth_failed",
            },
        },
        timestamp="2026-05-18T12:01:00",
    )

    response = client.post("/api/sessions/session-live/messages", json={"content": "继续"})
    print("CTX-RETRY 422 detail:", response.status_code, response.text[:300])

    assert response.status_code == 202
    assert len(scheduled_contexts) == 1
    assert scheduled_contexts[0]["user_message"] == "继续"
    assert scheduled_contexts[0].get("attachments") in (None, [])
    latest_user = [message for message in response.json()["messages"] if message["role"] == "user"][-1]
    assert "resolvedRecentImageReference" not in (latest_user.get("metadata") or {})


def test_session_recent_image_reference_without_history_asks_for_image(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session("session-live", display_name="真实会话"),
    )
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "再看一下刚才那张图"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["metadata"]["resolvedRecentImageReference"]["status"] == "missing"
    assert "没有在当前会话里找到" in _assistant_visible_text(payload["messages"][-1])


def test_session_user_image_attachment_empty_text_with_unknown_capability_reaches_dialogue_llm(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session("session-live", display_name="真实会话"),
    )
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        session_service,
        "_session_agent_supports_image_input",
        lambda agent_instance, *, slot: None,
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {
                "status": "completed",
                "summary": "LLM 已查看图片。",
                "raw_output": "LLM 已查看图片。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "ready"
    assert seen["initial_prompt"] == ""
    assert seen["attachments"][0]["dataUrl"].startswith("data:image/png;base64,")
    assert _assistant_visible_text(payload["messages"][-1]) == "LLM 已查看图片。"
    assert all(
        "你想让我分析这张图片" not in str(message.get("content") or "")
        for message in payload["messages"]
    )


def test_session_user_image_attachment_rejects_unsupported_type(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/sessions/session-live/attachments",
        content=b"not an image",
        headers={"Content-Type": "text/plain", "X-Vibelution-Filename": "note.txt"},
    )

    assert response.status_code == 422


def test_session_user_image_attachment_rejects_spoofed_image_payload(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/sessions/session-live/attachments",
        content=b"not really a png",
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "spoof.png"},
    )

    assert response.status_code == 422


def test_session_user_image_attachment_rejects_oversized_content_length_before_storage(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.routes.sessions.record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        "core.web.routes.sessions.store_session_user_image_attachment",
        lambda *_args, **_kwargs: pytest.fail("oversized upload should be rejected before storage"),
    )

    response = client.post(
        "/api/sessions/session-live/attachments",
        content=b"",
        headers={
            "Content-Type": "image/png",
            "X-Vibelution-Filename": "huge.png",
            "Content-Length": str(session_service.SESSION_USER_IMAGE_MAX_BYTES + 1),
        },
    )

    assert response.status_code == 413
    assert recorded_events
    args, kwargs = recorded_events[-1]
    assert args[:3] == ("conversation", "attachment_upload", "conversation.attachment_upload.rejected")
    assert kwargs["fields"]["reason"] == "content_length_exceeded"
    assert kwargs["fields"]["limitBytes"] == session_service.SESSION_USER_IMAGE_MAX_BYTES


def test_session_user_image_attachment_rejects_stream_that_exceeds_limit(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.routes.sessions.record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        "core.web.routes.sessions.SESSION_USER_IMAGE_MAX_BYTES",
        16,
    )
    monkeypatch.setattr(
        "core.web.routes.sessions.store_session_user_image_attachment",
        lambda *_args, **_kwargs: pytest.fail("oversized stream should be rejected before storage"),
    )

    response = client.post(
        "/api/sessions/session-live/attachments",
        content=iter([b"\x89PNG\r\n\x1a\n", b"0123456789"]),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "stream.png"},
    )

    assert response.status_code == 413
    assert recorded_events[-1][1]["fields"]["reason"] == "stream_limit_exceeded"
    assert recorded_events[-1][1]["fields"]["receivedBytes"] > 16


def test_submit_session_message_preserves_chinese_content_round_trip(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session("session-live", display_name="真实会话"),
    )
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    content = "修复中文编码：runtime circuit breaker validation ping"

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": content},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == content
    assert payload["messages"][-1]["role"] == "assistant"
    _assert_context_prepare_overlay(payload["messages"][-1])

    state = load_chat_state(tmp_path)
    assert "messages" not in state["conversations"][0]
    persisted = session_service.get_session_detail("session-live")["messages"][-2]
    assert persisted["role"] == "user"
    assert persisted["content"] == content

    workspace_log = session_service._ensure_session_workspace("session-live") / "logs" / "conversation.jsonl"
    log_records = [json.loads(line) for line in workspace_log.read_text(encoding="utf-8").splitlines()]
    assert log_records[-1]["content"] == content


def test_submit_session_message_preserves_full_multiline_prompt_for_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session("session-live", display_name="真实会话"),
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: captured.update({"context": dict(context)}))

    content = "\n".join(
        [
            "第一行：这是完整需求的开头",
            "第二行：保留背景",
            "第三行：保留约束",
            "第四行：保留测试要求",
            "第五行：不能被本地 trim_lines 截断",
            "第六行：仍然应该交给 LLM 判断",
        ]
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": content},
    )

    assert response.status_code == 202
    assert captured["context"]["user_message"] == content
    assert captured["context"]["raw_user_message"] == content
    assert captured["context"]["user_message_source"] == "raw_meaningful"


def test_submit_session_message_shows_waiting_live_message_while_turn_runs(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "检查为什么对话看起来卡住"},
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["currentPhase"] == "running"
        live_message = payload["messages"][-1]
        assert live_message["role"] == "assistant"
        _assert_context_prepare_overlay(live_message)
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_submit_session_message_recovers_content_from_utf8_base64_fallback(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    content = "请继续检查中文输入链路"
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "???????:runtime circuit breaker validation ping", "contentUtf8Base64": encoded},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["content"] == content
    _assert_context_prepare_overlay(payload["messages"][-1])
    state = load_chat_state(tmp_path)
    assert "messages" not in state["conversations"][0]
    assert session_service.get_session_detail("session-live")["messages"][-2]["content"] == content
    assert _read_next_state_signals(tmp_path, session_id="session-live") == []


def test_submit_session_message_rejects_encoding_replacement_pollution(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "???????:runtime circuit breaker validation ping"},
    )

    assert response.status_code == 422
    assert "编码损坏" in response.json()["detail"]
    state = load_chat_state(tmp_path)
    assert "messages" not in state["conversations"][0]
    assert [
        _conversation_message_text(item)
        for item in session_service.get_session_detail("session-live")["messages"]
    ] == [
        "继续前端开发",
        "已经接到真实状态了。",
    ]


def test_submit_session_message_preserves_short_dialogue_prompt_without_task_fallback(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "继续前端开发",
            "goal": "继续前端开发",
            "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
            "default_file_context": "web/src/routes/ChatCodingRoute.tsx",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "继续前端开发",
                "raw_output": "继续前端开发",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你好"},
    )

    assert response.status_code == 202
    assert captured["prompt"] == "你好"
    assert all(item["content"] != "你好" for item in captured["seeded"])
    payload = response.json()
    assert payload["activeTask"]["goal"] == "继续前端开发"
    assert payload["activeTask"]["title"] == "继续前端开发"
    event_codes = [args[2] for args, _kwargs in recorded_events]
    assert "conversation.user_message_filtered" not in event_codes


def test_lightweight_chat_does_not_classify_user_text_or_disable_tools():
    enabled, reason = session_service._lightweight_chat_payload_decision(
        {"raw_user_message": "Capital ok?", "user_message": "Capital ok?"}
    )
    assert (enabled, reason) == (False, "unified_conversation_chain")

    enabled, reason = session_service._lightweight_chat_payload_decision(
        {"raw_user_message": "API ok?", "user_message": "API ok?"}
    )
    assert (enabled, reason) == (False, "unified_conversation_chain")


def test_lightweight_chat_keeps_active_skill_contract_in_full_payload():
    enabled, reason = session_service._lightweight_chat_payload_decision(
        {
            "raw_user_message": "收到",
            "user_message": "收到",
            "active_skill_contract": {
                "command": "brt",
                "skillName": "brt",
                "skillHash": "hash-a",
                "keyRules": ["Ask one question at a time."],
            },
        }
    )

    assert (enabled, reason) == (False, "active_skill_contract")


def test_submit_session_message_continue_preserves_raw_prompt_and_dialogue_history(tmp_path, monkeypatch):
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "修复对话消息流程",
            "goal": "修复对话消息流程",
            "read_files": ["core/web/services/session_service.py"],
            "default_file_context": "core/web/services/session_service.py",
            "metadata": {"source": "task_tool"},
        },
    )
    _append_test_ledger_messages(
        tmp_path,
        "session-live",
        [{"role": "user", "content": "?", "timestamp": "2026-05-18T11:57:00"}],
        prefix="continue-history",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)

    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "修复对话消息流程",
                "raw_output": "修复对话消息流程",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    assert captured["prompt"] == "继续"
    assert any(item["content"] == "?" for item in captured["seeded"])


def test_web_session_prepares_agent_from_assembled_history_once(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "updated_at": "2026-07-14T10:00:00",
                "last_turn_status": "ready",
                "messages": [],
            }
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)

    previous_turn_id = "turn-previous"
    previous_call_id = "call-previous"
    append_conversation_event(
        tmp_path,
        "session-live",
        previous_turn_id,
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "读取 README 并汇报"},
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        previous_turn_id,
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": "",
            "toolCalls": [
                {
                    "id": previous_call_id,
                    "name": "read_file_tool",
                    "arguments": {"file_path": "README.md"},
                }
            ],
        },
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        previous_turn_id,
        EVENT_TOOL_RESULT,
        status="completed",
        payload={
            "toolCall": {
                "id": previous_call_id,
                "name": "read_file_tool",
                "result": "# Vibelution",
            }
        },
        tool_call_id=previous_call_id,
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        previous_turn_id,
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "README 显示这是 Vibelution 项目。"},
    )

    class DummyAgent:
        def __init__(self):
            self.out_of_band_history_seeds = []

        def seed_chat_history(self, messages):
            self.out_of_band_history_seeds.append(list(messages))

    runtime_agent = DummyAgent()
    runner_calls: list[dict] = []

    def fake_run_existing_agent_single_turn(agent, **kwargs):
        assert agent is runtime_agent
        runner_calls.append(dict(kwargs))
        return {
            "status": "completed",
            "summary": "已接住上一轮上下文。",
            "raw_output": "已接住上一轮上下文。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
        }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: runtime_agent)
    monkeypatch.setattr(session_service, "run_existing_agent_single_turn", fake_run_existing_agent_single_turn)
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202, response.json()
    assert runtime_agent.out_of_band_history_seeds == []
    assert len(runner_calls) == 1
    call = runner_calls[0]
    assert call["initial_prompt"] == "继续"
    assert call["turn_identity"]
    history = call["chat_history"]
    assert [item["role"] for item in history] == ["user", "assistant", "tool", "assistant"]
    assert history[1]["tool_calls"][0]["id"] == previous_call_id
    assert history[2]["tool_call_id"] == previous_call_id
    assert history[3]["content"] == "README 显示这是 Vibelution 项目。"
    assert all(item.get("content") != "继续" for item in history)


def test_web_session_preflight_stop_reports_history_assembled_not_seeded(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    _wait_for_phase, lifecycle_events = _capture_session_lifecycle_events(monkeypatch)

    class StopBeforeRunnerAgent:
        def run_single_turn(self, initial_prompt=None):
            pytest.fail("preflight stop must happen before the public runner")

    # The turn must honor a stop request as early as the prepare stage
    # (9bbc671d0), so drive the stub off the history_assembled event instead
    # of a call counter: before assembly no stop is pending, after it arrives.
    def stop_after_history_assembly(_turn_control):
        if any(event.get("phase") == "history_assembled" for event in lifecycle_events):
            return "test preflight stop"
        return ""

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: StopBeforeRunnerAgent())
    monkeypatch.setattr(session_service, "_get_turn_control_stop_reason", stop_after_history_assembly)
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "在 preparation 前停止"},
    )

    assert response.status_code == 202, response.json()
    phases = [event["phase"] for event in lifecycle_events]
    assert phases.count("history_assembled") == 1
    assembled_event = next(event for event in lifecycle_events if event["phase"] == "history_assembled")
    assert assembled_event["fields"]["assembledHistoryMessageCount"] >= 1
    assert assembled_event["fields"]["historyAssemblyMs"] >= 0


def test_submit_session_message_does_not_promote_contextual_confirmation_to_task_goal(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "优化日志摘要入口",
            "goal": "优化日志摘要入口",
            "latest_summary": "已经形成日志摘要优化计划。",
            "metadata": {"source": "task_tool"},
        },
    )
    _bind_seeded_submittable_agent(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已开始按计划修改日志摘要入口。",
                "raw_output": "已开始按计划修改日志摘要入口。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "好的开始修改"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["activeTask"]["goal"] == "优化日志摘要入口"
    assert payload["activeTask"]["title"] != "好的开始修改"
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["active_task"]["goal"] == "优化日志摘要入口"


def test_submit_session_contextual_confirmation_preserves_raw_prompt(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "agent-avatar-task",
            "kind": "coding",
            "status": "editing",
            "title": "现在agent可以设置默认头像吗",
            "goal": "现在agent可以设置默认头像吗",
            "changed_files": ["workspace/avatars/avatars.json"],
            "latest_summary": "Agent 目前不能设置默认图片头像。要我现在开始实现吗？",
            "next_action": "",
            "metadata": {"source": "task_tool", "outcome": "no_change"},
        },
    )
    _bind_seeded_submittable_agent(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "已开始实现 Agent 默认头像支持。",
                "raw_output": "已开始实现 Agent 默认头像支持。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "开始实现"},
    )

    assert response.status_code == 202
    assert captured["prompt"] == "开始实现"
    payload = response.json()
    assert payload["activeTask"]["goal"] == "现在agent可以设置默认头像吗"
    assert payload["activeTask"]["title"] == "现在agent可以设置默认头像吗"


def test_submit_session_plain_confirmation_preserves_raw_prompt_without_agent_inbox_task_pollution(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "[Agent 私信回复]\n来源 Agent: A013 · 白予安",
            "goal": "[Agent 私信回复]\n来源 Agent: A013 · 白予安",
            "latest_summary": "白予安回复说需要 CEO 确认后继续推进记忆系统开发。",
            "read_files": ["core/web/services/session_service.py"],
            "metadata": {"source": "task_tool", "last_user_message_filtered": True},
        },
    )
    _bind_seeded_submittable_agent(tmp_path)
    _append_test_ledger_messages(
        tmp_path,
        "session-live",
        [
            {
                "role": "user",
                "content": "我现在需要对项目的记忆系统进行开发,需要你的团队,请你把这个作为目前的任务,分析一下如何进展",
                "timestamp": "2026-05-31T17:03:58",
            },
            {
                "role": "user",
                "content": "[Agent 私信回复]\n来源 Agent: A013 · 白予安\n\n消息内容:\n需要 CEO 确认。",
                "timestamp": "2026-05-31T17:08:50",
                "metadata": {
                    "kind": "agent_inbox_message",
                    "inboxKind": "agent_inbox_reply",
                    "sourceAgentId": "agent-a013",
                    "targetAgentId": "agent-ceo",
                },
            },
            {
                "role": "assistant",
                "content": "团队已完成前期组织诊断和能力评估，现在需要您的决策来推进下一阶段工作。请确认上述决策点。",
                "timestamp": "2026-05-31T17:09:00",
            },
        ],
        prefix="agent-inbox-history",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "已收到确认，继续推进记忆系统开发组织任务。",
                "raw_output": "已收到确认，继续推进记忆系统开发组织任务。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "确认"},
    )

    assert response.status_code == 202
    prompt = str(captured["prompt"])
    assert prompt == "确认"
    assert "[Agent 私信回复]" not in prompt
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["goal"].startswith("我现在需要对项目的记忆系统进行开发")
    assert "[Agent 私信回复]" not in active_task["goal"]


def test_submit_session_agent_inbox_turn_preserves_inbox_prompt_without_history_fallback(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "只需要创建记忆库管理员",
            "goal": "只需要创建记忆库管理员",
            "latest_summary": "等待团队私信回复。",
            "metadata": {"source": "task_tool"},
        },
    )
    _bind_seeded_submittable_agent(tmp_path)
    _append_test_ledger_messages(
        tmp_path,
        "session-live",
        [
            {
                "role": "user",
                "content": "只需要创建记忆库管理员",
                "timestamp": "2026-05-31T17:03:58",
            },
            {
                "role": "tool",
                "tool_call_id": "call_old_fetch_timeout",
                "content": "[错误] 请求超时 (30s): https://example.test/old-timeout",
                "timestamp": "2026-05-31T17:04:10",
                "metadata": {"toolName": "web_fetch_tool", "toolStatus": "failed"},
            },
            {
                "role": "tool",
                "tool_call_id": "call_old_fetch_large",
                "content": "[网页内容] https://example.test/old-paper\n\n" + ("old fetched page body\n" * 700),
                "timestamp": "2026-05-31T17:04:20",
                "metadata": {"toolName": "web_fetch_tool", "toolStatus": "done"},
            },
        ],
        prefix="agent-inbox-base",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured: dict[str, object] = {}
    lifecycle_events: list[tuple[str, dict]] = []

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None, attachments=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "已收到白予安的私信回复，并将其作为团队反馈处理。",
                "raw_output": "已收到白予安的私信回复，并将其作为团队反馈处理。",
                "outcome": "no_change",
            }

    def record_lifecycle_event(session_id, phase, **kwargs):
        lifecycle_events.append((phase, dict(kwargs.get("fields") or {})))

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )
    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", record_lifecycle_event)

    inbox_prompt = (
        "[Agent 私信回复]\n"
        "来源 Agent: A013 · 白予安\n"
        "消息ID: agentmsg-20260601-000153-481642\n\n"
        "消息内容:\n"
        "记忆库管理员只需要配置 memory_tools 和 agent_message_tool。"
    )
    detail = session_service.submit_session_message(
        "session-live",
        inbox_prompt,
        turn_mode="agent_inbox",
        write_intent=False,
        message_metadata={
            "kind": "agent_inbox_message",
            "inboxKind": "agent_inbox_reply",
            "sourceAgentCode": "A013",
            "sourceAgentName": "白予安",
        },
        message_source="agent_inbox",
    )

    assert detail["id"] == "session-live"
    prompt = str(captured["prompt"])
    assert prompt.startswith("[Agent 私信回复]")
    assert "记忆库管理员只需要配置 memory_tools" in prompt
    assert prompt != "只需要创建记忆库管理员"
    seeded_text = "\n".join(str(item.get("content") or "") for item in captured["seeded"])
    assert "只需要创建记忆库管理员" in seeded_text
    assert "请求超时" in seeded_text
    assert "详情位置: 会话历史和工具日志仍保留原始结果" in seeded_text
    assert "old fetched page body\n" * 40 not in seeded_text
    assert not any(
        phase == "user_message_filtered" and fields.get("fallbackSource") == "history"
        for phase, fields in lifecycle_events
    )
    assert any(phase == "agent_inbox_prompt_preserved" for phase, _fields in lifecycle_events)
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["last_user_message"] == "只需要创建记忆库管理员"
    assert active_task["metadata"]["last_user_message_reason"] == "agent_inbox_message"


def test_submit_session_continue_preserves_raw_prompt_when_active_task_goal_is_confirmation(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "好的开始修改",
            "goal": "好的开始修改",
            "read_files": ["core/web/services/runtime_scene_service.py"],
            "metadata": {"source": "task_tool"},
        },
    )
    _bind_seeded_submittable_agent(tmp_path)
    _append_test_ledger_messages(
        tmp_path,
        "session-live",
        [
            {
                "role": "user",
                "content": "检查日志系统摘要一致性并给出优化方案",
                "timestamp": "2026-05-18T11:57:00",
            },
            {
                "role": "assistant",
                "content": "建议先定位 summary 与 package_index 的生成链路，再补测试。",
                "timestamp": "2026-05-18T11:58:00",
            },
            {"role": "user", "content": "好的开始修改", "timestamp": "2026-05-18T11:59:00"},
            {
                "role": "assistant",
                "content": "已达到 Web Chat 任务级持续上限（4 轮），本次先暂停，避免后台无限运行。",
                "timestamp": "2026-05-18T12:00:00",
            },
        ],
        prefix="confirmation-history",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "已恢复到日志摘要一致性任务并完成收束。",
                "raw_output": "已恢复到日志摘要一致性任务并完成收束。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    prompt = str(captured["prompt"])
    assert prompt == "继续"
    assert any(item["content"] == "检查日志系统摘要一致性并给出优化方案" for item in captured["seeded"])
    assert any(item["content"] == "好的开始修改" for item in captured["seeded"])


def test_submit_session_continue_keeps_raw_prompt_while_task_state_prefers_newer_user_goal(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "diagnostics-refinement-task",
            "kind": "coding",
            "status": "reading",
            "title": "你可以继续按刚才的方向整理诊断报告",
            "goal": "你可以继续按刚才的方向整理诊断报告",
            "read_files": ["config.toml", "config.example.toml"],
            "latest_summary": "很抱歉，我现在无法执行任何工具操作，所有工具不可用。",
            "last_user_message": "继续",
            "metadata": {
                "source": "task_tool",
                "outcome": "no_change",
                "last_user_message_filtered": True,
                "last_user_message_reason": "non_meaningful_user_message",
            },
        },
    )
    _bind_seeded_submittable_agent(tmp_path)
    _append_test_ledger_messages(
        tmp_path,
        "session-live",
        [
            {
                "role": "user",
                "content": "你可以继续按刚才的方向整理诊断报告",
                "timestamp": "2026-05-30T00:53:10",
            },
            {
                "role": "assistant",
                "content": "初版诊断报告已经整理完成。",
                "timestamp": "2026-05-30T00:57:55",
                "tool_calls": [{"name": "read_file", "status": "done"}],
            },
            {
                "role": "user",
                "content": "这个报告没有解释为什么日志会重复记录,你需要继续分析 runtime scene 的重复事件来源",
                "timestamp": "2026-05-30T00:58:24",
            },
            {"role": "user", "content": "继续", "timestamp": "2026-05-30T01:03:15"},
            {
                "role": "assistant",
                "content": "很抱歉，我现在无法执行任何工具操作，所有工具当前都显示为不可用状态。",
                "timestamp": "2026-05-30T01:04:19",
                "toolCalls": [],
            },
        ],
        prefix="resume-report-history",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    prompts = []

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            prompts.append(initial_prompt)
            return {
                "status": "completed",
                "summary": "已恢复到 runtime scene 重复事件诊断任务。",
                "raw_output": "已恢复到 runtime scene 重复事件诊断任务。",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    prompt = str(prompts[0])
    assert prompt == "继续"
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["goal"] == "这个报告没有解释为什么日志会重复记录,你需要继续分析 runtime scene 的重复事件来源"
    assert active_task["title"] == "这个报告没有解释为什么日志会重复记录,你需要继续分析 runtime scene 的重复事件来源"


def test_submit_session_continue_keeps_raw_prompt_while_task_state_ignores_retry_control_goal(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "diagnostics-retry-task",
            "kind": "coding",
            "status": "reading",
            "title": "好了应该恢复了你再试试",
            "goal": "好了应该恢复了你再试试",
            "latest_summary": "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。",
            "last_user_message": "好了应该恢复了你再试试",
            "metadata": {"source": "task_tool", "outcome": "failed_runtime"},
        },
    )
    _bind_seeded_submittable_agent(tmp_path)
    _append_test_ledger_messages(
        tmp_path,
        "session-live",
        [
            {
                "role": "user",
                "content": "这次报告和原始日志完全对不上,你需要继续调整诊断方向,来逼近真实原因",
                "timestamp": "2026-05-30T00:58:24",
            },
            {
                "role": "user",
                "content": "好了应该恢复了你再试试",
                "timestamp": "2026-05-30T10:35:27",
            },
            {
                "role": "assistant",
                "content": "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。",
                "timestamp": "2026-05-30T10:39:52",
                "tool_calls": [{"name": "read_file", "status": "done"}],
            },
        ],
        prefix="retry-goal-history",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    prompts = []

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            prompts.append(initial_prompt)
            return {
                "status": "completed",
                "summary": "已继续处理日志诊断逼近任务。",
                "raw_output": "已继续处理日志诊断逼近任务。",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    prompt = str(prompts[0])
    assert prompt == "继续"
    active_task = load_chat_state(tmp_path)["conversations"][0]["active_task"]
    assert active_task["goal"] == "这次报告和原始日志完全对不上,你需要继续调整诊断方向,来逼近真实原因"


def test_edit_resubmit_session_message_recovers_content_from_utf8_base64_fallback(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    content = "编辑后保留中文"
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": "session-live-message-1",
            "content": "???????:runtime circuit breaker validation ping",
            "contentUtf8Base64": encoded,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["content"] == content
    _assert_context_prepare_overlay(payload["messages"][-1])
    state = load_chat_state(tmp_path)
    assert "messages" not in state["conversations"][0]
    assert session_service.get_session_detail("session-live")["messages"][-2]["content"] == content


def test_edit_resubmit_session_message_truncates_following_history_and_starts_turn(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:03:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-18T12:03:00",
                    "last_turn_status": "ready",
                }
            ],
        },
    )
    _append_test_ledger_messages(
        tmp_path,
        "session-live",
        [
            {"role": "user", "content": "原始需求", "timestamp": "2026-05-18T12:00:00"},
            {"role": "assistant", "content": "原始回答", "timestamp": "2026-05-18T12:01:00"},
            {"role": "user", "content": "后续追问", "timestamp": "2026-05-18T12:02:00"},
            {"role": "assistant", "content": "后续回答", "timestamp": "2026-05-18T12:03:00"},
        ],
        prefix="edit-history",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    scheduled_contexts: list[dict] = []
    events: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: events.append(
            {"component": component, "phase": phase, "eventCode": event_code, **kwargs}
        ),
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": "session-live-message-3",
            "content": "编辑后的需求",
            "mentalModelEnabled": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "running"
    assert [_conversation_message_text(item) for item in payload["messages"][:-1]] == ["原始需求", "原始回答", "编辑后的需求"]
    _assert_context_prepare_overlay(payload["messages"][-1])
    assert len(scheduled_contexts) == 1
    assert scheduled_contexts[0]["user_message"] == "编辑后的需求"
    assert [_conversation_message_text(item) for item in scheduled_contexts[0]["history_messages"]] == [
        "原始需求",
        "原始回答",
    ]
    assert scheduled_contexts[0]["mental_model_enabled"] is False
    state = load_chat_state(tmp_path)
    assert "messages" not in state["conversations"][0]
    stored_messages = session_service.get_session_detail("session-live")["messages"][:-1]
    assert [_conversation_message_text(item) for item in stored_messages] == ["原始需求", "原始回答", "编辑后的需求"]
    assert stored_messages[0]["role"] == "user"
    assert stored_messages[0]["timestamp"] == "2026-05-18T12:00:00"
    assert stored_messages[1]["role"] == "assistant"
    assert stored_messages[1]["timestamp"] == "2026-05-18T12:01:00"
    assert any(event["eventCode"] == "conversation.message_edited_resubmitted" for event in events)
    signals = _read_next_state_signals(tmp_path, session_id="session-live")
    assert any(item["kind"] == "assistant_output_edited" and item["turnId"] for item in signals)

    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")
    session_service._clear_session_live_output("session-live")


def test_edit_resubmit_session_message_allows_latest_user_message(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:03:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-18T12:03:00",
                    "last_turn_status": "ready",
                }
            ],
        },
    )
    _append_test_ledger_messages(
        tmp_path,
        "session-live",
        [
            {"role": "user", "content": "原始需求", "timestamp": "2026-05-18T12:00:00"},
            {"role": "assistant", "content": "原始回答", "timestamp": "2026-05-18T12:01:00"},
            {"role": "user", "content": "后续追问", "timestamp": "2026-05-18T12:02:00"},
            {"role": "assistant", "content": "后续回答", "timestamp": "2026-05-18T12:03:00"},
        ],
        prefix="edit-latest-history",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    scheduled_contexts: list[dict] = []
    events: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: events.append(
            {"component": component, "phase": phase, "eventCode": event_code, **kwargs}
        ),
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": "session-live-message-3",
            "content": "编辑最新的需求",
            "mentalModelEnabled": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert [_conversation_message_text(item) for item in payload["messages"][:-1]] == ["原始需求", "原始回答", "编辑最新的需求"]
    _assert_context_prepare_overlay(payload["messages"][-1])
    assert len(scheduled_contexts) == 1
    assert scheduled_contexts[0]["user_message"] == "编辑最新的需求"
    assert [_conversation_message_text(item) for item in scheduled_contexts[0]["history_messages"]] == [
        "原始需求",
        "原始回答",
    ]
    assert any(event["eventCode"] == "conversation.message_edited_resubmitted" for event in events)

    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")
    session_service._clear_session_live_output("session-live")


def test_edit_resubmit_session_message_supersedes_running_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))

    first_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "先执行旧任务"},
    )
    assert first_response.status_code == 202
    assert len(scheduled_contexts) == 1
    old_context = scheduled_contexts[0]
    old_turn_id = old_context["turn_id"]
    old_user_message_id = first_response.json()["messages"][-2]["id"]

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": old_user_message_id,
            "content": "改成执行新任务",
            "mentalModelEnabled": False,
        },
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assert len(scheduled_contexts) == 2
    new_turn_id = scheduled_contexts[1]["turn_id"]
    assert new_turn_id != old_turn_id
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "改成执行新任务"
    _assert_context_prepare_overlay(payload["messages"][-1])
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["runId"] == new_turn_id
    old_run = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", old_turn_id)
    assert old_run["status"] == "superseded"
    assert old_run["finishedAt"]

    class OldAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "旧任务迟到结果不应写入。",
                "raw_output": "旧任务迟到结果不应写入。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: OldAgent())
    session_service._run_session_turn(old_context)

    detail = client.get("/api/sessions/session-live").json()
    assert detail["currentPhase"] == "running"
    assert "旧任务迟到结果不应写入" not in json.dumps(detail, ensure_ascii=False)
    assert detail["messages"][-2]["content"] == "改成执行新任务"

    session_service._set_session_running("session-live", False, turn_id=new_turn_id)
    session_service._clear_session_turn_control("session-live", turn_id=new_turn_id)
    session_service._clear_session_live_output("session-live")


def test_edit_resubmit_session_message_rejects_assistant_message(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    before_state = load_chat_state(tmp_path)

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={"messageId": "session-live-message-2", "content": "不能编辑助手消息"},
    )

    assert response.status_code == 422
    assert load_chat_state(tmp_path) == before_state


def test_edit_resubmit_session_message_rejects_non_latest_user_message(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    _append_test_ledger_messages(
        tmp_path,
        "session-live",
        [
            {"role": "user", "content": "后续追问", "timestamp": "2026-05-18T12:02:00"},
            {"role": "assistant", "content": "后续回答", "timestamp": "2026-05-18T12:03:00"},
        ],
        prefix="non-latest-edit-history",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    before_state = load_chat_state(tmp_path)
    rejected_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: rejected_events.append({"args": args, "kwargs": kwargs}) or {"accepted": True},
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={"messageId": "session-live-message-1", "content": "不能改旧消息"},
    )

    assert response.status_code == 422
    assert load_chat_state(tmp_path) == before_state
    assert any(
        event["args"][:3] == ("conversation", "message_edit_resubmit_rejected", "conversation.message_edit_resubmit_rejected")
        for event in rejected_events
    )


def test_chat_turn_registers_as_work_run_until_finished(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "解释当前状态"},
    )

    assert response.status_code == 202
    running_summary = runtime_service.get_runtime_summary()
    active_chat = running_summary["workRuns"]["active"]["chat_turn"]
    assert active_chat["runKind"] == "chat_turn"
    assert active_chat["status"] == "running"
    assert active_chat["sessionId"] == "session-live"
    assert active_chat["leases"] == ["readonly_chat"]

    turn_id = active_chat["runId"]
    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "已解释当前状态。",
            "raw_output": "已解释当前状态。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
        },
        turn_id=turn_id,
    )
    session_service._set_session_running("session-live", False, turn_id=turn_id)

    finished_summary = runtime_service.get_runtime_summary()
    assert finished_summary["workRuns"]["active"]["chat_turn"] is None
    latest_chat = finished_summary["workRuns"]["latest"]["chat_turn"]
    assert latest_chat["runId"] == turn_id
    assert latest_chat["status"] == "completed"


def test_persist_turn_result_projects_sanitized_runtime_prompt_assembly(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    turn_id = "turn-runtime-prompt-assembly"
    session_service._set_session_running("session-live", True, turn_id=turn_id)

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "OK",
            "raw_output": "OK",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
            "prompt_assembly": {
                "schemaVersion": 1,
                "assemblyMode": "turn_runtime_v2",
                "modelProtocol": "basic_chat_no_tools",
                "totalEstimatedTokens": 2922,
                "segments": [
                    {
                        "key": "core_common",
                        "source": "COMMON.md",
                        "decision": "full",
                        "contentHash": "safe-hash",
                        "content": "must never reach the public DTO",
                    }
                ],
            },
        },
        turn_id=turn_id,
    )
    session_service._set_session_running("session-live", False, turn_id=turn_id)

    detail = session_service.get_session_detail("session-live")
    assert detail["lastPromptAssembly"]["modelProtocol"] == "basic_chat_no_tools"
    assert detail["lastPromptAssembly"]["totalEstimatedTokens"] == 2922
    assert detail["lastPromptAssembly"]["segments"] == [
        {
            "key": "core_common",
            "source": "COMMON.md",
            "contentHash": "safe-hash",
            "decision": "full",
        }
    ]
    assert "content" not in detail["lastPromptAssembly"]["segments"][0]


def test_attach_runtime_prompt_assembly_manifest_uses_agent_prompt_manager():
    manifest = {
        "schemaVersion": 1,
        "assemblyMode": "turn_runtime_v2",
        "modelProtocol": "basic_chat_no_tools",
    }
    runtime_agent = SimpleNamespace(
        prompt_manager=SimpleNamespace(get_last_assembly_manifest=lambda: manifest)
    )
    result = {"status": "completed"}

    attached = session_worker._attach_runtime_prompt_assembly_manifest(result, runtime_agent)

    assert attached is result
    assert attached["prompt_assembly"] == manifest


def test_prompt_assembly_manifest_is_bound_to_the_building_worker_thread():
    manager = PromptManager.__new__(PromptManager)
    manager._last_assembly_manifest = {"modelProtocol": "global"}
    manager._assembly_manifest_local = threading.local()
    manager._assembly_manifest_local.value = {"modelProtocol": "main-thread"}
    worker_manifest: list[dict] = []

    def read_from_other_worker() -> None:
        manager._last_assembly_manifest = {"modelProtocol": "other-worker"}
        manager._assembly_manifest_local.value = {"modelProtocol": "other-worker"}
        worker_manifest.append(manager.get_last_assembly_manifest())

    worker = threading.Thread(target=read_from_other_worker)
    worker.start()
    worker.join()

    assert worker_manifest == [{"modelProtocol": "other-worker"}]
    assert manager.get_last_assembly_manifest() == {"modelProtocol": "main-thread"}


def test_persist_turn_result_blocks_phantom_image_generation_success(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    turn_id = "turn-image2"
    session_service._set_session_running("session-live", True, turn_id=turn_id)
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append({"args": args, "kwargs": kwargs}) or {"accepted": True},
    )

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "已生成图片。",
            "raw_output": "已生成图片。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
        },
        turn_id=turn_id,
    )
    session_service._set_session_running("session-live", False, turn_id=turn_id)

    conversation = load_chat_state(tmp_path)["conversations"][0]
    detail = session_service.get_session_detail("session-live")
    assert sum(message.get("turnId") == "turn-segments" for message in detail["messages"]) == 0
    assert detail["currentPhase"] == "failed"
    assert "没有实际生成新的图片" in detail["lastTurnError"]["message"]
    assert "messages" not in conversation
    assert conversation["last_turn_status"] == "failed"
    assert any(
        event["args"][:3]
        == ("conversation", "turn_phantom_image_success_blocked", "conversation.turn.phantom_image_success_blocked")
        for event in events
    )


@pytest.mark.slow
def test_different_agent_sessions_run_chat_turns_concurrently(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "core.orchestration.context_engine.record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-concurrent")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)

    started_sessions: set[str] = set()
    started_lock = threading.Lock()
    both_started = threading.Event()
    release = threading.Event()

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            session_id = alpha["id"] if "alpha" in prompt else beta["id"]
            with started_lock:
                started_sessions.add(session_id)
                if started_sessions == {alpha["id"], beta["id"]}:
                    both_started.set()
            assert release.wait(2.0)
            return {
                "status": "completed",
                "summary": f"{session_id} done",
                "raw_output": f"{session_id} done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        first = session_service.submit_session_message(alpha["id"], "alpha 并行任务")
        second = session_service.submit_session_message(beta["id"], "beta 并行任务")

        assert first["currentPhase"] == "running"
        assert second["currentPhase"] == "running"
        assert both_started.wait(1.0), "expected different agents to overlap"
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert _assistant_visible_text(session_service.get_session_detail(alpha["id"])["messages"][-1]) == f"{alpha['id']} done"
    assert _assistant_visible_text(session_service.get_session_detail(beta["id"])["messages"][-1]) == f"{beta['id']} done"


@pytest.mark.slow
def test_same_agent_different_sessions_run_chat_turns_concurrently(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "core.orchestration.context_engine.record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-queue")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    started_sessions: set[str] = set()
    started_lock = threading.Lock()
    both_started = threading.Event()
    release = threading.Event()
    prompts: list[str] = []

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            prompts.append(prompt)
            session_id = alpha["id"] if "alpha" in prompt else beta["id"]
            with started_lock:
                started_sessions.add(session_id)
                if started_sessions == {alpha["id"], beta["id"]}:
                    both_started.set()
            assert release.wait(2.0)
            return {
                "status": "completed",
                "summary": f"{session_id} done",
                "raw_output": f"{session_id} done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        first = session_service.submit_session_message(alpha["id"], "alpha 并行任务")
        assert first["currentPhase"] == "running"
        second = session_service.submit_session_message(beta["id"], "beta 并行任务")
        assert second["currentPhase"] == "running"

        assert both_started.wait(1.0), "expected same-agent different sessions to overlap"
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert len(prompts) == 2
    assert set(prompts) == {"alpha 并行任务", "beta 并行任务"}
    assert _assistant_visible_text(session_service.get_session_detail(alpha["id"])["messages"][-1]) == f"{alpha['id']} done"
    assert _assistant_visible_text(session_service.get_session_detail(beta["id"])["messages"][-1]) == f"{beta['id']} done"


@pytest.mark.slow
def test_same_agent_sessions_queue_when_agent_concurrency_limit_is_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *args, **kwargs: {"accepted": True})
    wait_for_lifecycle_phase, _events = _capture_session_lifecycle_events(monkeypatch)
    monkeypatch.setattr(
        "core.orchestration.context_engine.record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )
    _install_session_turn_scheduler(monkeypatch, max_active_per_agent=1)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-queue")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()
    prompts: list[str] = []

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            prompts.append(prompt)
            if "alpha" in prompt:
                first_started.set()
                assert release_first.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "alpha done",
                    "raw_output": "alpha done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            second_started.set()
            assert release_second.wait(2.0)
            return {
                "status": "completed",
                "summary": "beta done",
                "raw_output": "beta done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        first = session_service.submit_session_message(alpha["id"], "alpha 串行任务")
        assert first["currentPhase"] == "running"
        assert first_started.wait(1.0)

        second = session_service.submit_session_message(beta["id"], "beta 串行任务")
        assert second["currentPhase"] == "queued"
        queued_event = wait_for_lifecycle_phase("scheduler_queued", fields={"agentId": alpha["agentId"]})
        assert queued_event is not None
        assert queued_event["fields"]["queueReason"] == "agent_concurrency_limit"
        assert queued_event["fields"]["agentMaxActive"] == 1
        assert queued_event["fields"]["schedulerSessionKey"] == f"session:{beta['id']}"
        assert not second_started.is_set()

        release_first.set()
        assert second_started.wait(3.0), "expected queued turn to start after first turn"
    finally:
        release_first.set()
        release_second.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert prompts == ["alpha 串行任务", "beta 串行任务"]
    assert _assistant_visible_text(session_service.get_session_detail(alpha["id"])["messages"][-1]) == "alpha done"
    assert _assistant_visible_text(session_service.get_session_detail(beta["id"])["messages"][-1]) == "beta done"


@pytest.mark.slow
def test_stopping_queued_same_agent_turn_prevents_later_start(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "_ensure_agent_default_avatar", lambda agent, **kwargs: None, raising=False)
    wait_for_lifecycle_phase, _events = _capture_session_lifecycle_events(monkeypatch)
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )
    _install_session_turn_scheduler(monkeypatch, max_active_per_agent=1)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-stop-queued")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()
    prompts: list[str] = []

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            prompts.append(prompt)
            if "alpha" in prompt:
                first_started.set()
                assert release_first.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "alpha done",
                    "raw_output": "alpha done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            second_started.set()
            assert release_second.wait(2.0)
            return {
                "status": "completed",
                "summary": "beta done",
                "raw_output": "beta done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        first = session_service.submit_session_message(alpha["id"], "alpha 串行任务")
        assert first["currentPhase"] == "running"
        assert first_started.wait(1.0)

        second = session_service.submit_session_message(beta["id"], "beta 串行任务")
        assert second["currentPhase"] == "queued"
        queued_event = wait_for_lifecycle_phase("scheduler_queued", fields={"agentId": alpha["agentId"]})
        assert queued_event is not None
        assert not second_started.is_set()

        stopped = session_service.request_stop_session_turn(beta["id"])
        assert stopped["currentPhase"] == "ready"
        assert stopped["messages"][-1]["role"] == "user"
        assert "beta 串行任务" in str(stopped["messages"][-1].get("content") or "")
        assert stopped["runtimeNotices"][-1]["kind"] == "turn_stopped"
        assert "尚未开始执行" in stopped["runtimeNotices"][-1]["message"]

        release_first.set()
    finally:
        release_first.set()
        release_second.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert not second_started.is_set(), "stopped queued turn must not be started after the active turn releases"
    assert prompts == ["alpha 串行任务"]
    beta_detail = session_service.get_session_detail(beta["id"])
    assert beta_detail["messages"][-1]["role"] == "user"
    assert "beta 串行任务" in str(beta_detail["messages"][-1].get("content") or "")
    assert all("本轮已按请求停止" not in _conversation_message_text(message) for message in beta_detail["messages"])
    assert beta_detail["runtimeNotices"][-1]["kind"] == "turn_stopped"


@pytest.mark.slow
def test_shutdown_stops_queued_same_agent_turn_before_it_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    wait_for_lifecycle_phase, _events = _capture_session_lifecycle_events(monkeypatch)
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )
    _install_session_turn_scheduler(monkeypatch, max_active_per_agent=1)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-shutdown-queued")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()
    prompts: list[str] = []

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            prompts.append(prompt)
            if "alpha" in prompt:
                first_started.set()
                assert release_first.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "alpha done",
                    "raw_output": "alpha done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            second_started.set()
            assert release_second.wait(2.0)
            return {
                "status": "completed",
                "summary": "beta done",
                "raw_output": "beta done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha 关闭前任务")
        assert first_started.wait(1.0)
        queued = session_service.submit_session_message(beta["id"], "beta 关闭前任务")
        assert queued["currentPhase"] == "queued"
        queued_event = wait_for_lifecycle_phase("scheduler_queued", fields={"agentId": alpha["agentId"]})
        assert queued_event is not None
        assert not second_started.is_set()

        stopped = runtime_service._stop_active_chat_turns_before_shutdown()
        assert {item["sessionId"] for item in stopped} == {alpha["id"], beta["id"]}
        assert {item["status"] for item in stopped} == {"stopped"}

        release_first.set()
    finally:
        release_first.set()
        release_second.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert not second_started.is_set(), "shutdown-stopped queued turn must not start after active turn releases"
    assert prompts == ["alpha 关闭前任务"]
    assert session_service.get_session_detail(alpha["id"])["currentPhase"] == "ready"
    assert session_service.get_session_detail(beta["id"])["currentPhase"] == "ready"


@pytest.mark.slow
def test_runtime_summary_exposes_parallel_chat_turn_active_items(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_manager_snapshot", lambda: {})
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-active-items")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)

    started_sessions: set[str] = set()
    started_lock = threading.Lock()
    both_started = threading.Event()
    release = threading.Event()

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            session_id = alpha["id"] if "alpha" in prompt else beta["id"]
            with started_lock:
                started_sessions.add(session_id)
                if started_sessions == {alpha["id"], beta["id"]}:
                    both_started.set()
            assert release.wait(2.0)
            return {
                "status": "completed",
                "summary": f"{session_id} done",
                "raw_output": f"{session_id} done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha 并行任务")
        session_service.submit_session_message(beta["id"], "beta 并行任务")
        expected_session_ids = {alpha["id"], beta["id"]}
        deadline = time.perf_counter() + 5.0
        payload = runtime_service.get_runtime_summary()
        chat_items = payload["workRuns"]["activeItems"]["chat_turn"]
        while time.perf_counter() < deadline:
            payload = runtime_service.get_runtime_summary()
            chat_items = payload["workRuns"]["activeItems"]["chat_turn"]
            if {item["sessionId"] for item in chat_items} == expected_session_ids and {item["status"] for item in chat_items} == {"running"}:
                break
            time.sleep(0.05)
        assert {item["sessionId"] for item in chat_items} == {alpha["id"], beta["id"]}
        assert {item["status"] for item in chat_items} == {"running"}
        assert payload["lifecycleProof"]["activeWorkRuns"]["count"] == 2
        assert payload["lifecycleProof"]["activeWorkRuns"]["kinds"] == ["chat_turn", "chat_turn"]
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.slow
def test_runtime_summary_exposes_queued_chat_turn_active_item(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    wait_for_lifecycle_phase, _events = _capture_session_lifecycle_events(monkeypatch)
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_manager_snapshot", lambda: {})
    _install_session_turn_scheduler(monkeypatch, max_active_per_agent=1)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-queued-items")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            if "alpha" in prompt:
                first_started.set()
                assert release_first.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "alpha done",
                    "raw_output": "alpha done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            second_started.set()
            assert release_second.wait(2.0)
            return {
                "status": "completed",
                "summary": "beta done",
                "raw_output": "beta done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha 串行任务")
        assert first_started.wait(1.0)
        session_service.submit_session_message(beta["id"], "beta 串行任务")
        queued_event = wait_for_lifecycle_phase("scheduler_queued", fields={"agentId": alpha["agentId"]})
        assert queued_event is not None

        payload = runtime_service.get_runtime_summary()
        chat_items = sorted(
            payload["workRuns"]["activeItems"]["chat_turn"],
            key=lambda item: item["sessionId"],
        )
        assert {item["sessionId"] for item in chat_items} == {alpha["id"], beta["id"]}
        assert {item["status"] for item in chat_items} == {"queued", "running"}
        assert not second_started.is_set()
    finally:
        release_first.set()
        release_second.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_submit_session_message_records_chat_turn_started_scene_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={
            "content": "解释当前状态",
            "clientSubmissionId": "submission-timing-1",
        },
    )

    assert response.status_code == 202
    started_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn", "conversation.turn.started")
    ]
    assert started_events
    fields = started_events[-1][1]["fields"]
    active_chat = session_service.load_chat_turn_work_run_summary()["active"]
    assert fields["sessionId"] == "session-live"
    assert fields["turnId"] == active_chat["runId"]
    assert fields["leaseCount"] == 1
    scheduled_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn_scheduled", "conversation.turn.scheduled")
    ]
    assert scheduled_events
    scheduled_fields = scheduled_events[-1][1]["fields"]
    assert scheduled_fields["sessionId"] == "session-live"
    assert scheduled_fields["turnId"] == active_chat["runId"]
    assert scheduled_fields["chatStateLockedMs"] >= 0
    assert scheduled_fields["submitElapsedBeforeScheduleLogMs"] >= 0
    accepted_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn_accepted", "conversation.turn.accepted")
    ]
    assert accepted_events
    accepted_fields = accepted_events[-1][1]["fields"]
    assert accepted_fields["sessionId"] == "session-live"
    assert accepted_fields["turnId"] == active_chat["runId"]
    assert accepted_fields["clientSubmissionId"] == "submission-timing-1"
    assert accepted_fields["scheduleSubmitMs"] >= 0
    assert accepted_fields["submitTotalMs"] >= accepted_fields["scheduleSubmitMs"]
    for timing_field in (
        "kernelTraceMs",
        "initialJournalMarkersMs",
        "initialLiveDeltaPublishMs",
        "cycleMessageDispatchMs",
        "turnStartedSceneLogMs",
        "userPromptResolveMs",
        "scheduledSceneLogMs",
    ):
        assert accepted_fields[timing_field] >= 0
    assert accepted_fields["cycleMessageProjectionMode"] == "background_ordered"


def test_session_cycle_message_projection_is_dispatched_without_inline_logging(monkeypatch):
    submitted: list[tuple] = []
    recorded: list[tuple] = []

    monkeypatch.setattr(
        session_service,
        "_SESSION_CYCLE_PROJECTION_EXECUTOR",
        SimpleNamespace(submit=lambda *args, **kwargs: submitted.append((args, kwargs))),
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_cycle_message",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )

    session_service._submit_session_cycle_message_projection(
        "session-live",
        {"role": "user", "content": "not inspected by the dispatcher"},
        event="user_message",
        status="running",
        turn_id="turn-1",
    )

    assert len(submitted) == 1
    assert recorded == []
    submitted_args, submitted_kwargs = submitted[0]
    assert submitted_args[0] is session_service._run_session_cycle_message_projection
    assert submitted_args[1] == "session-live"
    assert submitted_kwargs["turn_id"] == "turn-1"


def test_submit_session_message_prefer_async_returns_lightweight_acceptance(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    response = client.post(
        "/api/sessions/session-live/messages",
        headers={"Prefer": "respond-async"},
        json={"content": "解释当前状态"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["sessionId"] == "session-live"
    assert payload["turnId"]
    assert payload["status"] == "running"
    assert "messages" not in payload


def test_submit_session_message_uses_live_delta_without_pre_schedule_detail_snapshot(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    scheduled_contexts = []
    live_updates = []
    published_details = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", scheduled_contexts.append)
    monkeypatch.setattr(
        session_service,
        "_set_session_waiting_live_output",
        lambda session_id, *, turn_id="": live_updates.append((session_id, turn_id)),
    )
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        published_details.append,
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        headers={"Prefer": "respond-async"},
        json={"content": "统一链路性能回归"},
    )

    assert response.status_code == 202
    assert len(scheduled_contexts) == 1
    assert live_updates == [("session-live", response.json()["turnId"])]
    assert published_details == []


def test_edit_resubmit_records_chat_turn_started_scene_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={"messageId": "session-live-message-1", "content": "编辑后的需求"},
    )

    assert response.status_code == 202
    started_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn", "conversation.turn.started")
    ]
    assert started_events
    fields = started_events[-1][1]["fields"]
    active_chat = session_service.load_chat_turn_work_run_summary()["active"]
    assert fields["sessionId"] == "session-live"
    assert fields["turnId"] == active_chat["runId"]
    assert fields["userMessageChars"] == len("编辑后的需求")


def test_run_session_turn_records_agent_started_scene_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    seeded_agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="真实会话",
        prompt_template_id="prompt-chat-default",
    )
    _bind_seeded_session_agent(
        tmp_path,
        seeded_agent,
    )
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class DummyAgent:
        def set_turn_interrupt_checker(self, checker):
            self.checker = checker

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已解释当前状态。",
                "raw_output": "已解释当前状态。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda workspace_path=None: DummyAgent())
    turn_control = session_service._create_session_turn_control("session-live")
    session_service._set_session_running("session-live", True, turn_id=turn_control.turn_id, leases=["readonly_chat"])
    try:
        session_service._run_session_turn(
            {
                "session_id": "session-live",
                "turn_id": turn_control.turn_id,
                "turn_control": turn_control,
                "user_message": "解释当前状态",
                "history_messages": [],
                "mental_model_enabled": False,
                "agent_id": seeded_agent["agentId"],
            }
        )
    finally:
        session_service._set_session_running("session-live", False, turn_id=turn_control.turn_id)
        session_service._clear_session_turn_control("session-live", turn_id=turn_control.turn_id)

    agent_created_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn_agent_created", "conversation.turn.agent_created")
    ]
    assert agent_created_events
    fields = agent_created_events[-1][1]["fields"]
    assert fields["sessionId"] == "session-live"
    assert fields["turnId"] == turn_control.turn_id
    assert fields["agentType"] == "DummyAgent"
    assert fields["agentCreateMs"] >= 0
    assembled_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn_history_assembled", "conversation.turn.history_assembled")
    ]
    assert assembled_events
    assembled_fields = assembled_events[-1][1]["fields"]
    assert assembled_fields["assembledHistoryMessageCount"] >= 1
    assert assembled_fields["historyAssemblyMs"] >= 0
    assert assembled_fields["runtimeContextSeedMs"] >= 0
    assert assembled_fields["totalSeedMs"] >= 0
    returned_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn_agent_turn_returned", "conversation.turn.agent_turn_returned")
    ]
    assert returned_events
    assert returned_events[-1][1]["fields"]["llmElapsedMs"] >= 0
    worker_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn_worker_started", "conversation.turn.worker_started")
    ]
    assert worker_events
    worker_fields = worker_events[-1][1]["fields"]
    assert worker_fields["totalPrepareMs"] >= 0
    assert "agentContextBuildMs" in worker_fields
    assert "executorWaitMs" in worker_fields


def test_runtime_summary_exposes_work_run_kinds(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    self_evolution_control_service.persist_manager_run_snapshot(
        "self",
        {
            "runId": "self-work-run",
            "status": "running",
            "startedAt": "2026-05-21T00:00:00",
            "updatedAt": "2026-05-21T00:00:00",
        },
        active_run_id="self-work-run",
    )
    supervised_control_service.persist_manager_run_snapshot(
        "supervised",
        {
            "runId": "supervised-work-run",
            "status": "done",
            "startedAt": "2026-05-21T00:00:00",
            "updatedAt": "2026-05-21T00:01:00",
        },
        active_run_id="",
    )
    supervised_worktree_evolution_service._persist_snapshot(
        {
            "runId": "swte-work-run",
            "runKind": "supervised_worktree_evolution_run",
            "status": "running",
            "startedAt": "2026-05-21T00:00:00",
            "updatedAt": "2026-05-21T00:02:00",
        },
        active_run_id="swte-work-run",
    )

    payload = runtime_service.get_runtime_summary()

    assert set(payload["workRuns"]["active"]) == {
        "chat_turn",
        "chat_room_round",
        "self_evolution_run",
        "self_evolution_autonomous_loop",
        "source_collection_run",
        "supervised_evolution_run",
        "supervised_worktree_evolution_run",
    }
    assert payload["workRuns"]["active"]["chat_room_round"] is None
    assert payload["workRuns"]["active"]["source_collection_run"] is None
    assert payload["workRuns"]["active"]["self_evolution_run"]["runKind"] == "self_evolution_run"
    assert payload["workRuns"]["active"]["self_evolution_run"]["leases"] == [
        "evolution_transaction",
        "worktree_write",
        "memory_write",
    ]
    assert payload["workRuns"]["latest"]["supervised_evolution_run"]["runKind"] == "supervised_evolution_run"
    assert payload["workRuns"]["latest"]["supervised_evolution_run"]["leases"] == ["evaluation"]
    assert payload["workRuns"]["active"]["supervised_worktree_evolution_run"]["runKind"] == "supervised_worktree_evolution_run"
    assert payload["workRuns"]["active"]["supervised_worktree_evolution_run"]["leases"] == [
        "evaluation",
        "worktree_write",
    ]


def test_submit_session_message_captures_chat_review_candidate(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    _bind_seeded_submittable_agent(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "结论：已经定位到网页聊天提交流程。下一步我会把采样和审核接上。",
                "raw_output": "结论：已经定位到网页聊天提交流程。下一步我会把采样和审核接上。",
                "tool_call_count": 2,
                "tool_trace": [
                    {"name": "read_file_tool"},
                    {"function": {"name": "apply_patch_tool"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续把网页聊天里的 case 抽出来给监督进化用"},
    )

    assert response.status_code == 202
    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.status_code == 200
    payload = queue_response.json()
    assert payload["pendingCount"] == 1
    assert payload["items"][0]["sessionId"] == "session-live"
    assert payload["items"][0]["qualitySignals"]


def test_session_adds_current_conversation_to_chat_review_queue(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.post("/api/sessions/session-live/chat-review-candidate")

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["sessionId"] == "session-live"
    assert payload["turnCount"] == 1
    assert payload["candidateId"] == "session-live_t0001_0001"
    assert "监督" in payload["summary"] or "supervised" in payload["summary"].lower()

    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["pendingCount"] == 1
    assert queue_payload["items"][0]["candidateId"] == "session-live_t0001_0001"
    assert queue_payload["items"][0]["status"] == "pending"
    assert recorded_scene_events
    assert recorded_scene_events[-1][0][:3] == (
        "chat_review",
        "session_candidate_created",
        "chat_review.session_candidate.created",
    )


def test_session_add_to_chat_review_rejects_empty_conversation(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-18T12:00:00",
                    "last_turn_status": "ready",
                }
            ],
        },
    )
    _append_test_ledger_messages(
        tmp_path,
        "session-live",
        [
            {
                "role": "user",
                "content": "只有用户消息",
                "timestamp": "2026-05-18T11:55:00",
            }
        ],
        prefix="chat-review-empty",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)

    response = client.post("/api/sessions/session-live/chat-review-candidate")

    assert response.status_code == 422
    assert "完整" in response.json()["detail"] or "complete" in response.json()["detail"].lower()
    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.json()["pendingCount"] == 0


def test_session_add_to_chat_review_rejects_duplicate_snapshot(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)

    first_response = client.post("/api/sessions/session-live/chat-review-candidate")
    second_response = client.post("/api/sessions/session-live/chat-review-candidate")

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert "已经" in second_response.json()["detail"] or "already" in second_response.json()["detail"].lower()
    queue_response = client.get("/api/evolution/chat-review")
    queue_payload = queue_response.json()
    assert queue_payload["pendingCount"] == 1
    assert [item["candidateId"] for item in queue_payload["items"]] == ["session-live_t0001_0001"]


def test_submit_session_message_rejects_busy_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    _bind_seeded_submittable_agent(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    before_events = [event.to_dict() for event in load_conversation_events(tmp_path, "session-live")]

    session_service._set_session_running("session-live", True)
    session_service._WORK_RUN_STORE.persist_snapshot(
        "chat_turn",
        {
            "runId": "existing-chat-turn",
            "runKind": "chat_turn",
            "track": "dialogue",
            "sessionId": "session-live",
            "status": "running",
            "currentPhase": "running",
            "leases": ["readonly_chat"],
            "userMessage": "上一轮仍在运行",
            "startedAt": "2026-05-18T11:59:00",
            "updatedAt": "2026-05-18T12:00:00",
            "finishedAt": "",
        },
        active_run_id="existing-chat-turn",
    )

    try:
        response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "继续修复 web/src/routes/ChatCodingRoute.tsx"},
        )
    finally:
        session_service._set_session_running("session-live", False)

    assert response.status_code == 409
    assert "运行" in response.json()["detail"] or "running" in response.json()["detail"].lower()
    assert [event.to_dict() for event in load_conversation_events(tmp_path, "session-live")] == before_events
    active_run = session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn")
    assert active_run["runId"] == "existing-chat-turn"
    assert active_run["userMessage"] == "上一轮仍在运行"


def test_submit_session_message_rejects_blank_message_without_mutating_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    _bind_seeded_submittable_agent(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    before_state = load_chat_state(tmp_path)
    before_events = [event.to_dict() for event in load_conversation_events(tmp_path, "session-live")]
    before_status = before_state["conversations"][0]["last_turn_status"]

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": " \n\t "},
    )

    assert response.status_code == 422
    assert "请输入" in response.json()["detail"] or "enter a message" in response.json()["detail"].lower()
    after_state = load_chat_state(tmp_path)
    assert [event.to_dict() for event in load_conversation_events(tmp_path, "session-live")] == before_events
    assert after_state["conversations"][0]["last_turn_status"] == before_status
    assert session_service._is_session_running("session-live") is False
    assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None


def test_submit_session_message_records_provider_failure_next_state_signal(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)

    class ProviderFailureAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": "litellm.BadGatewayError: BadGatewayError: OpenAIException - {\"error\":{\"message\":\"Upstream request failed\"}}",
                "raw_output": "litellm.BadGatewayError: BadGatewayError: OpenAIException - {\"error\":{\"message\":\"Upstream request failed\"}}",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailureAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续检查上游失败"},
    )

    assert response.status_code == 202
    signals = _read_next_state_signals(tmp_path, session_id="session-live")
    assert any(item["kind"] == "provider_failure" for item in signals)
    assert any(item["relatedEventCode"] == "conversation.turn_error" for item in signals)


def test_capture_session_ui_stream_records_tool_error_next_state_signal(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live", turn_id="turn-tool")
    with session_service._capture_session_ui_stream("session-live", capture):
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_ERROR,
            {"name": "read_file_tool", "error": "permission denied", "callId": "call-read_file_tool-1"},
        )

    signals = _read_next_state_signals(tmp_path, session_id="session-live", turn_id="turn-tool")
    assert any(item["kind"] == "tool_error" for item in signals)
    assert any(item["relatedEventCode"] == "conversation.tool_error" for item in signals)
    assert any(item["metadata"]["toolName"] == "read_file_tool" for item in signals)


def test_capture_session_ui_stream_promotes_tool_error_to_active_work_run(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    session_service._persist_chat_turn_work_run(
        session_id="session-live",
        turn_id="turn-source-writeback",
        status="running",
        user_message="## 资料搜集阶段任务：资料提炼任务\n请完成 source_collection_stage_writeback_tool 回写。",
        summary="正在思考，已收到思考片段...",
    )

    capture = session_service.SessionTurnCapture(session_id="session-live", turn_id="turn-source-writeback")
    with session_service._capture_session_ui_stream("session-live", capture):
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_ERROR,
            {
                "name": "source_collection_stage_writeback_tool",
                "error": "[超时] source_collection_stage_writeback_tool 执行超时 (30秒)", "callId": "call-source_collection_stage_writeback_tool-1"},
        )

    active = session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn")
    assert active["runId"] == "turn-source-writeback"
    assert active["status"] == "running"
    assert "source_collection_stage_writeback_tool" in active["summary"]
    assert "超时" in active["summary"]
    assert active["lastToolError"]["toolName"] == "source_collection_stage_writeback_tool"
    assert "超时" in active["lastToolError"]["summary"]


def test_capture_session_ui_stream_surfaces_llm_retry_status(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    lifecycle_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: lifecycle_events.append(
            {"session_id": session_id, "phase": phase, **kwargs}
        ),
    )
    published: list[str] = []
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda session_id: published.append(session_id))
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live", turn_id="turn-llm")
    with session_service._capture_session_ui_stream("session-live", capture):
        session_service.get_event_bus().publish(
            session_service.EventNames.LLM_STATUS,
            {
                "status": "retrying",
                "attempt": 2,
                "max_attempts": 5,
                "category": "network_error",
            },
        )

    live_state = session_service._snapshot_session_live_output("session-live")
    assert live_state is not None
    assert live_state.stage == "model_retry"
    assert "模型连接正在重试" in live_state.content
    assert "2/5" in live_state.content
    # Retry progress is delivered through the lightweight assistant_delta
    # turnItems stream; it must not force a full session-detail snapshot.
    assert published == []
    assert any(item["phase"] == "llm_status_retrying" for item in lifecycle_events)


def test_capture_session_ui_stream_surfaces_network_failure_without_fallback_text(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    lifecycle_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: lifecycle_events.append(
            {"session_id": session_id, "phase": phase, **kwargs}
        ),
    )
    published: list[str] = []
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda session_id: published.append(session_id))
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live", turn_id="turn-llm")
    with session_service._capture_session_ui_stream("session-live", capture):
        session_service.get_event_bus().publish(
            session_service.EventNames.LLM_STATUS,
            {
                "status": "failed",
                "attempt": 2,
                "max_attempts": 2,
                "category": "network_error",
            },
        )

    live_state = session_service._snapshot_session_live_output("session-live")
    assert live_state is not None
    assert live_state.stage == "model_failed"
    assert "模型请求失败" in live_state.content
    assert "network_error" in live_state.content
    assert "代理端口" in live_state.content
    assert "非流式" not in live_state.content
    assert "切换" not in live_state.content
    assert any(item["phase"] == "llm_status_failed" for item in lifecycle_events)


def test_capture_session_ui_stream_surfaces_live_thought_as_model_thinking(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    lifecycle_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: lifecycle_events.append(
            {"session_id": session_id, "phase": phase, **kwargs}
        ),
    )
    published: list[str] = []
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda session_id: published.append(session_id))
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live-thought", turn_id="turn-thinking")
    with session_service._capture_session_ui_stream("session-live-thought", capture):
        stub_ui.stream_thought("先看最新日志，再判断是否真的卡住。", done=False)

    live_state = session_service._snapshot_session_live_output("session-live-thought")
    assert live_state is not None
    assert live_state.stage == "model_thinking"
    assert live_state.content == ""
    assert any(
        item.get("kind") == "status"
        and item.get("name") == "model_thinking"
        and "正在思考" in str(item.get("resultPreview") or "")
        for item in live_state.feedback_events
    )
    assert live_state.thought == "先看最新日志，再判断是否真的卡住。"
    assert capture.thought == "先看最新日志，再判断是否真的卡住。"
    assert any(item["phase"] == "ui_progress_model_thinking" for item in lifecycle_events)
    assert any(item["phase"] == "llm_status_reasoning" for item in lifecycle_events)


def test_session_continuation_marks_server_side_model_wait_as_thinking(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)

    observed_stages: list[str] = []

    def fake_run_existing_agent_single_turn(agent, **kwargs):
        live_state = session_service._snapshot_session_live_output("session-server-thinking")
        observed_stages.append(str(live_state.stage if live_state is not None else ""))
        return {
            "status": "completed",
            "summary": "完成",
            "raw_output": "完成",
            "tool_call_count": 0,
            "tool_trace": [],
        }

    monkeypatch.setattr(session_service, "run_existing_agent_single_turn", fake_run_existing_agent_single_turn)

    turn_control = session_service._create_session_turn_control("session-server-thinking")
    try:
        result = session_service._run_session_continuation_loop(
            object(),
            context={},
            session_id="session-server-thinking",
            turn_control=turn_control,
            initial_prompt="你好",
            history_messages=[],
        )
    finally:
        session_service._clear_session_turn_control("session-server-thinking", turn_id=turn_control.turn_id)

    assert isinstance(result, dict)
    assert result["status"] == "completed"
    assert observed_stages == ["model_thinking"]
    live_state = session_service._snapshot_session_live_output("session-server-thinking")
    assert live_state is not None
    assert live_state.stage == "model_thinking"
    assert live_state.content == ""
    assert live_state.thought == ""
    assert any(
        item.get("kind") == "status"
        and item.get("name") == "model_thinking"
        and "正在思考" in str(item.get("resultPreview") or "")
        for item in live_state.feedback_events
    )


def test_session_same_turn_continuation_passes_durable_history_only_once(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    calls: list[dict] = []

    def fake_run_existing_agent_single_turn(agent, **kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            return {
                "status": "completed",
                "summary": "已读取文件，继续形成结论。",
                "raw_output": "已读取文件，继续形成结论。",
                "outcome": "progress",
                "tool_call_count": 1,
                "tool_trace": [{"name": "read_file_tool", "status": "done"}],
            }
        return {
            "status": "completed",
            "summary": "结论已形成。",
            "raw_output": "结论已形成。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
        }

    monkeypatch.setattr(session_service, "run_existing_agent_single_turn", fake_run_existing_agent_single_turn)
    durable_history = [
        {"role": "user", "content": "读取文件"},
        {"role": "assistant", "content": "上一轮结论"},
    ]
    turn_control = session_service._create_session_turn_control("session-history-once")
    try:
        result = session_service._run_session_continuation_loop(
            object(),
            context={},
            session_id="session-history-once",
            turn_control=turn_control,
            initial_prompt="继续",
            history_messages=durable_history,
            allow_internal_auto_continue=True,
            max_internal_auto_continue_turns=2,
        )
    finally:
        session_service._clear_session_turn_control("session-history-once", turn_id=turn_control.turn_id)

    assert isinstance(result, dict)
    assert result["status"] == "completed"
    assert len(calls) == 2
    assert calls[0]["chat_history"] == durable_history
    assert calls[1]["chat_history"] is None
    assert calls[0]["turn_identity"] == turn_control.turn_id
    assert calls[1]["turn_identity"] == turn_control.turn_id


def test_source_collection_stage_task_enables_bounded_internal_auto_continue(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    _bind_seeded_submittable_agent(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )
    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: object())
    captured: dict[str, object] = {}

    def fake_run_session_continuation_loop(agent, **kwargs):
        captured.update(kwargs)
        return {
            "status": "completed",
            "summary": "阶段任务完成。",
            "raw_output": "阶段任务完成。",
            "outcome": "done",
        }

    monkeypatch.setattr(session_worker, "_run_session_continuation_loop", fake_run_session_continuation_loop)

    detail = session_service.submit_session_message(
        "session-live",
        "资料搜集阶段任务",
        turn_mode="task",
        write_intent=False,
        message_source="agent_inbox",
        message_metadata={
            "kind": "source_collection_stage_session_task",
            "teamId": "research-team",
            "runId": "dprun-1",
            "stageId": "finding",
            "agentId": "agent-source-finder",
            "agentRole": "source_finder",
            "sourceCollectionStageTaskId": "stagetask-1",
        },
    )

    assert detail["id"] == "session-live"
    assert captured["allow_internal_auto_continue"] is True
    assert captured["max_internal_auto_continue_turns"] == session_service.SOURCE_COLLECTION_STAGE_TASK_AUTO_CONTINUE_MAX_TURNS


def test_source_collection_stage_task_continue_inherits_contract_and_tool_gate(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    _bind_seeded_submittable_agent(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )
    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: object())
    captured: list[dict[str, object]] = []

    def fake_run_session_continuation_loop(agent, **kwargs):
        captured.append(dict(kwargs))
        return {
            "status": "completed",
            "summary": "阶段任务仍在推进。",
            "raw_output": "阶段任务仍在推进。",
            "outcome": "progress",
        }

    monkeypatch.setattr(session_worker, "_run_session_continuation_loop", fake_run_session_continuation_loop)
    checklist = [
        {"id": "read_candidates", "requiredTool": "source_collection_context_tool"},
        {"id": "write_extractions", "requiredTool": "source_collection_stage_writeback_tool"},
    ]
    metadata = {
        "kind": "source_collection_stage_session_task",
        "teamId": "research-team",
        "runId": "dprun-1",
        "stageId": "extraction",
        "agentId": "agent-source-extractor",
        "agentRole": "source_extractor",
        "sourceCollectionStageTaskId": "stagetask-1",
        "sourceContextMode": "retry_evidence",
        "writebackContract": {"taskChecklist": checklist},
        "taskChecklist": checklist,
    }

    session_service.submit_session_message(
        "session-live",
        "资料提炼阶段任务",
        turn_mode="task",
        write_intent=False,
        message_source="agent_inbox",
        message_metadata=metadata,
    )
    detail = session_service.submit_session_message(
        "session-live",
        "继续",
        turn_mode="task",
        write_intent=False,
    )

    assert len(captured) == 2
    assert captured[1]["allow_internal_auto_continue"] is True
    assert captured[1]["require_tool_progress"] is True
    assert captured[1]["required_tool_names"] == [
        "source_collection_context_tool",
        "source_collection_stage_writeback_tool",
    ]
    assert "team_id: research-team" in captured[1]["initial_prompt"]
    assert "run_id: dprun-1" in captured[1]["initial_prompt"]
    assert "stage_id: extraction" in captured[1]["initial_prompt"]
    assert "task_id: stagetask-1" in captured[1]["initial_prompt"]
    assert "source_collection_stage_writeback_tool" in captured[1]["initial_prompt"]
    assert "checklist 已由后端绑定" in captured[1]["initial_prompt"]
    assert "先调用 task_list_tool" not in captured[1]["initial_prompt"]
    assert "不要调用通用 task_list_tool" in captured[1]["initial_prompt"]
    assert "仅抓取上下文已给出的 sourceUrl 或 DOI" in captured[1]["initial_prompt"]
    assert "不要扩展检索方向" in captured[1]["initial_prompt"]
    assert "当前批读取完毕后一次性补证" in captured[1]["initial_prompt"]
    assert "不要调用 web_fetch_tool" not in captured[1]["initial_prompt"]
    continued_user_message = [item for item in detail["messages"] if item.get("role") == "user"][-1]
    assert continued_user_message["metadata"]["kind"] == "source_collection_stage_session_task"
    assert continued_user_message["metadata"]["sourceCollectionStageTaskId"] == "stagetask-1"
    assert continued_user_message["metadata"]["sourceContextMode"] == "retry_evidence"
    assert continued_user_message["metadata"]["sourceCollectionStageContinuation"] is True


def test_source_collection_finding_continuation_keeps_external_fetch_disabled():
    prompt = session_service._source_collection_stage_task_continuation_prompt(
        {
            "kind": "source_collection_stage_session_task",
            "sourceCollectionStageContinuation": True,
            "teamId": "research-team",
            "runId": "dprun-1",
            "stageId": "finding",
            "agentRole": "source_finder",
            "sourceCollectionStageTaskId": "stagetask-finding",
            "sourceContextMode": "compact",
        }
    )

    assert "不要调用 web_fetch_tool" in prompt


def test_source_collection_stage_task_ack_only_result_does_not_finish_before_required_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    prompts: list[str] = []

    def fake_run_existing_agent_single_turn(agent, **kwargs):
        prompts.append(str(kwargs.get("initial_prompt") or ""))
        if len(prompts) == 1:
            return {
                "status": "completed",
                "summary": "已接收资料提炼任务，我将先绑定检查清单并分页读取候选上下文。",
                "raw_output": "已接收资料提炼任务，我将先绑定检查清单并分页读取候选上下文。",
                "tool_call_count": 0,
                "tool_trace": [],
            }
        return {
            "status": "completed",
            "summary": "已读取候选上下文并完成阶段回写。",
            "raw_output": "已读取候选上下文并完成阶段回写。",
            "outcome": "done",
            "tool_call_count": 2,
            "tool_trace": [
                {"name": "source_collection_context_tool", "status": "done"},
                {"name": "source_collection_stage_writeback_tool", "status": "done"},
            ],
        }

    monkeypatch.setattr(session_service, "run_existing_agent_single_turn", fake_run_existing_agent_single_turn)

    turn_control = session_service._create_session_turn_control("session-stage-ack-only")
    try:
        result = session_service._run_session_continuation_loop(
            object(),
            context={},
            session_id="session-stage-ack-only",
            turn_control=turn_control,
            initial_prompt="资料搜集阶段任务",
            history_messages=[],
            user_message_source="agent_inbox",
            allow_internal_auto_continue=True,
            max_internal_auto_continue_turns=2,
            require_tool_progress=True,
            required_tool_names=["source_collection_context_tool", "source_collection_stage_writeback_tool"],
        )
    finally:
        session_service._clear_session_turn_control("session-stage-ack-only", turn_id=turn_control.turn_id)

    assert len(prompts) == 2
    assert isinstance(result, dict)
    assert result["status"] == "completed"
    assert result["raw_output"] == "已读取候选上下文并完成阶段回写。"
    assert "上一轮只输出了接收或计划" in prompts[1]
    assert "source_collection_context_tool" in prompts[1]


def test_source_collection_stage_task_waits_for_all_required_tools_across_continuations(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    prompts: list[str] = []

    def fake_run_existing_agent_single_turn(agent, **kwargs):
        prompts.append(str(kwargs.get("initial_prompt") or ""))
        if len(prompts) == 1:
            return {
                "status": "completed",
                "summary": "已读取候选并抓取证据，随后立即回写。",
                "raw_output": "已读取候选并抓取证据，随后立即回写。",
                "outcome": "done",
                "tool_call_count": 2,
                "tool_trace": [
                    {"name": "source_collection_context_tool", "status": "done"},
                    {"name": "web_fetch_tool", "status": "done"},
                ],
            }
        return {
            "status": "completed",
            "summary": "已完成阶段回写。",
            "raw_output": "已完成阶段回写。",
            "outcome": "done",
            "tool_call_count": 1,
            "tool_trace": [
                {"name": "source_collection_stage_writeback_tool", "status": "done"},
            ],
        }

    monkeypatch.setattr(session_service, "run_existing_agent_single_turn", fake_run_existing_agent_single_turn)

    turn_control = session_service._create_session_turn_control("session-stage-partial-tools")
    try:
        result = session_service._run_session_continuation_loop(
            object(),
            context={},
            session_id="session-stage-partial-tools",
            turn_control=turn_control,
            initial_prompt="继续资料提炼阶段任务",
            history_messages=[],
            allow_internal_auto_continue=True,
            max_internal_auto_continue_turns=2,
            require_tool_progress=True,
            required_tool_names=["source_collection_context_tool", "source_collection_stage_writeback_tool"],
        )
    finally:
        session_service._clear_session_turn_control("session-stage-partial-tools", turn_id=turn_control.turn_id)

    assert len(prompts) == 2
    assert isinstance(result, dict)
    assert result["status"] == "completed"
    assert result["raw_output"] == "已完成阶段回写。"
    assert "source_collection_stage_writeback_tool" in prompts[1]


def test_session_continuation_pauses_after_bounded_no_progress_streak(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    prompts: list[str] = []

    def fake_run_existing_agent_single_turn(agent, **kwargs):
        prompts.append(str(kwargs.get("initial_prompt") or ""))
        return {
            "status": "completed",
            "summary": "",
            "raw_output": "",
            "outcome": "progress",
            "tool_call_count": 1,
            "tool_trace": [{"name": "task_update_tool", "status": "done", "summary": "progress"}],
        }

    monkeypatch.setattr(session_service, "run_existing_agent_single_turn", fake_run_existing_agent_single_turn)

    turn_control = session_service._create_session_turn_control("session-auto-limit")
    try:
        result = session_service._run_session_continuation_loop(
            object(),
            context={},
            session_id="session-auto-limit",
            turn_control=turn_control,
            initial_prompt="继续阶段任务",
            history_messages=[],
            allow_internal_auto_continue=True,
            max_internal_auto_continue_turns=2,
        )
    finally:
        session_service._clear_session_turn_control("session-auto-limit", turn_id=turn_control.turn_id)

    # The first successful tool observation is progress. Only the next two
    # identical observations consume the consecutive no-progress allowance.
    assert len(prompts) == 3
    assert isinstance(result, dict)
    assert result["status"] == "paused_limit"
    assert result["metadata"]["continuation_limit_reached"] is True
    assert result["metadata"]["continuation_pause_reason"] == "runaway_no_progress"
    assert result["metadata"]["continuation_no_progress_count"] == 2
    assert "没有产生新的任务进展" in result["raw_output"]


def test_capture_session_ui_stream_merges_incremental_thought_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live-thought", turn_id="turn-thinking")
    with session_service._capture_session_ui_stream("session-live-thought", capture):
        stub_ui.stream_thought("先看", done=False)
        stub_ui.stream_thought("日志", done=False)
        stub_ui.stream_thought("先看日志和代码", done=False)

    live_state = session_service._snapshot_session_live_output("session-live-thought")
    assert live_state is not None
    thought_events = [item for item in live_state.feedback_events if item["kind"] == "thought"]
    assert len(thought_events) == 1
    assert thought_events[0]["resultPreview"] == "先看日志和代码"
    assert capture.thought == "先看日志和代码"


def test_capture_session_ui_stream_batches_tiny_response_deltas(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    live_updates: list[dict[str, object]] = []

    def fake_set_live_output(session_id: str, **kwargs):
        live_updates.append({"session_id": session_id, **kwargs})

    monkeypatch.setattr(session_service, "_set_session_live_output", fake_set_live_output)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live-response", turn_id="turn-response")
    with session_service._capture_session_ui_stream("session-live-response", capture):
        for token in ["这", "是", "一", "段", "非", "常", "细", "碎", "的", "回", "答"]:
            stub_ui.stream_response(token, done=False)

    content_updates = [item for item in live_updates if "content" in item]
    assert capture.content == "这是一段非常细碎的回答"
    assert len(content_updates) >= 1
    assert content_updates[-1]["content"] == capture.content
    assert any(item.get("stage") == "assistant_response" for item in content_updates)


def test_capture_session_ui_stream_flushes_slow_tiny_response_deltas(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    live_updates: list[dict[str, object]] = []
    clock = {"now": 1.0}

    def fake_set_live_output(session_id: str, **kwargs):
        live_updates.append({"session_id": session_id, **kwargs})

    monkeypatch.setattr(session_service, "_set_session_live_output", fake_set_live_output)
    monkeypatch.setattr(session_service, "_perf_counter", lambda: clock["now"])
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live-response", turn_id="turn-response")
    with session_service._capture_session_ui_stream("session-live-response", capture):
        for token in ["慢", "速", "回", "答"]:
            stub_ui.stream_response(token, done=False)
            clock["now"] += 0.2

    content_updates = [item for item in live_updates if "content" in item]
    assert capture.content == "慢速回答"
    assert [item["content"] for item in content_updates] == [
        "慢速",
        "慢速回答",
        "慢速回答",
    ]

def test_capture_session_ui_stream_batches_tiny_thought_deltas(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        stream_capture._SessionUiCaptureTextBatcher,
        "_should_flush_thought",
        lambda _self, _thought: False,
    )
    live_updates: list[dict[str, object]] = []

    def fake_set_live_output(session_id: str, **kwargs):
        live_updates.append({"session_id": session_id, **kwargs})

    monkeypatch.setattr(session_service, "_set_session_live_output", fake_set_live_output)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live-thought", turn_id="turn-thinking")
    with session_service._capture_session_ui_stream("session-live-thought", capture):
        for token in ["先", "看", "日", "志", "，", "再", "看", "代", "码", "。"]:
            stub_ui.stream_thought(token, done=False)

    thought_updates = [item for item in live_updates if "thought" in item]
    assert capture.thought == "先看日志，再看代码。"
    assert len(thought_updates) == 1
    assert thought_updates[0]["thought"] == "先看日志，再看代码。"


def test_capture_session_ui_stream_flushes_response_batches_by_size(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    live_updates: list[dict[str, object]] = []

    def fake_set_live_output(session_id: str, **kwargs):
        live_updates.append({"session_id": session_id, **kwargs})

    monkeypatch.setattr(session_service, "_set_session_live_output", fake_set_live_output)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    response = "这是一段足够长的回答内容，用来证明后端会按批次刷新，而不是每个字符都刷新。"
    capture = session_service.SessionTurnCapture(session_id="session-live-response", turn_id="turn-response")
    with session_service._capture_session_ui_stream("session-live-response", capture):
        for token in response:
            stub_ui.stream_response(token, done=False)

    content_updates = [item for item in live_updates if "content" in item]
    assert capture.content == response
    assert len(content_updates) >= 2
    assert len(content_updates) < len(response)
    assert content_updates[-1]["content"] == response


def test_capture_session_ui_stream_preserves_reasoning_delta_spaces(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live-thought", turn_id="turn-thinking")
    with session_service._capture_session_ui_stream("session-live-thought", capture):
        stub_ui.stream_thought("Let", done=False)
        stub_ui.stream_thought(" me", done=False)
        stub_ui.stream_thought(" check the config", done=False)

    live_state = session_service._snapshot_session_live_output("session-live-thought")
    assert live_state is not None
    thought_events = [item for item in live_state.feedback_events if item["kind"] == "thought"]
    assert len(thought_events) == 1
    assert thought_events[0]["resultPreview"] == "Let me check the config"
    assert live_state.thought == "Let me check the config"
    assert capture.thought == "Let me check the config"


def test_capture_session_ui_stream_splits_cumulative_thought_after_tool_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live-thought", turn_id="turn-thinking")
    with session_service._capture_session_ui_stream("session-live-thought", capture):
        stub_ui.stream_thought("先读日志。", done=False)
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_START,
            {"name": "read_log", "args": {"path": "logs/runtime_scenes/latest"}, "callId": "call-read-log-1"},
        )
        stub_ui.stream_thought("先读日志。再检查前端状态。", done=False)

    live_state = session_service._snapshot_session_live_output("session-live-thought")
    assert live_state is not None
    thought_events = [item for item in live_state.feedback_events if item["kind"] == "thought"]
    assert [item["resultPreview"] for item in thought_events] == ["先读日志。", "再检查前端状态。"]
    assert thought_events[1]["sequence"] > thought_events[0]["sequence"]
    assert live_state.thought == "先读日志。再检查前端状态。"


def test_capture_session_ui_stream_dedupes_repeated_thought_after_tool_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-repeated-thought", turn_id="turn-thinking")
    with session_service._capture_session_ui_stream("session-repeated-thought", capture):
        stub_ui.stream_thought("我已经有了 sections.py 的完整内容。现在分析三个问题。", done=False)
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_START,
            {"name": "read_file", "args": {"path": "core/prompt_manager/sections.py"}, "callId": "call-read_file-1"},
        )
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_SUCCESS,
            {"name": "read_file", "result": "section content", "durationMs": 12, "callId": "call-read_file-1"},
        )
        stub_ui.stream_thought("我已经有了 sections.py 的完整内容。现在分析三个问题。", done=False)
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_START,
            {"name": "grep", "args": {"pattern": "cache_prefix=True"}, "callId": "call-grep-1"},
        )

    live_state = session_service._snapshot_session_live_output("session-repeated-thought")
    assert live_state is not None
    thought_events = [item for item in live_state.feedback_events if item["kind"] == "thought"]
    tool_events = [item for item in live_state.feedback_events if item["kind"] == "tool"]
    assert [item["resultPreview"] for item in thought_events] == [
        "我已经有了 sections.py 的完整内容。现在分析三个问题。"
    ]
    assert [item["name"] for item in tool_events] == ["read_file", "grep"]
    assert tool_events[0]["relatedThoughtSequence"] == thought_events[0]["sequence"]
    assert tool_events[1]["relatedThoughtSequence"] == thought_events[0]["sequence"]
    assert live_state.thought == "我已经有了 sections.py 的完整内容。现在分析三个问题。"


def test_capture_session_ui_stream_preserves_ordered_feedback_events(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-feedback", turn_id="turn-feedback")
    with session_service._capture_session_ui_stream("session-feedback", capture):
        stub_ui.stream_thought("先读日志。", done=False)
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_START,
            {"name": "read_log", "args": {"path": "logs/runtime_scenes/latest"}, "callId": "call-read-log-1"},
        )
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_SUCCESS,
            {"name": "read_log", "result": "opened latest package", "durationMs": 12, "callId": "call-read-log-1"},
        )
        stub_ui.stream_thought("再检查前端链路。", done=False)
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_START,
            {"name": "rg", "args": {"pattern": "feedbackEvents"}, "callId": "call-rg-1"},
        )

    live_state = session_service._snapshot_session_live_output("session-feedback")
    assert live_state is not None
    kinds = [item["kind"] for item in live_state.feedback_events]
    assert kinds == ["thought", "status", "tool", "thought", "tool"]
    assert live_state.feedback_events[1]["name"] == "model_thinking"
    assert live_state.feedback_events[2]["name"] == "read_log"
    assert live_state.feedback_events[2]["status"] == "done"
    assert live_state.feedback_events[2]["relatedThoughtSequence"] == live_state.feedback_events[0]["sequence"]
    assert live_state.feedback_events[4]["relatedThoughtSequence"] == live_state.feedback_events[3]["sequence"]


def test_capture_session_ui_stream_commits_response_segments_at_tool_boundaries(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live", turn_id="turn-segments")
    with session_service._capture_session_ui_stream("session-live", capture):
        stub_ui.stream_response("先给出初步判断。", done=False)
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_SUCCESS,
            {"name": "read_log", "result": "opened latest package", "durationMs": 12, "callId": "call-read-log-1"},
        )
        stub_ui.stream_response("再根据日志给出结论。", done=False)

    events = load_conversation_events(tmp_path, "session-live")
    segments = [event for event in events if event.event_type == EVENT_ASSISTANT_DELTA_COMMITTED]

    assert [event.payload.get("content") for event in segments] == [
        "先给出初步判断。",
        "再根据日志给出结论。",
    ]

    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-segments",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": "先给出初步判断。再根据日志给出结论。",
            "feedbackEvents": capture.feedback_events,
        },
        source="persist_session_turn_result",
    )
    detail = session_service.get_session_detail("session-live")
    assert sum(message.get("turnId") == "turn-segments" for message in detail["messages"]) == 1
    message = detail["messages"][-1]
    _assert_v3_assistant_message(message)
    assert [item["type"] for item in message["turnItems"]] == ["tool_call", "agent_message"]
    assert message["turnItems"][0]["toolName"] == "read_log"
    assert _assistant_visible_text(message) == "先给出初步判断。再根据日志给出结论。"


def test_session_detail_interleaves_committed_assistant_segments_with_tool_events(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-interleaved",
        EVENT_ASSISTANT_DELTA_COMMITTED,
        status="completed",
        payload={"content": "先给出初步判断。"},
        source="session_ui_capture",
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-interleaved",
        EVENT_TOOL_RESULT,
        status="done",
        payload={
            "toolCall": {
                "id": "tool-read-log",
                "name": "read_log",
                "status": "done",
                "summary": "读取最新日志",
                "resultPreview": "found rendering bottleneck",
            }
        },
        source="session_ui_capture",
        tool_call_id="tool-read-log",
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-interleaved",
        EVENT_ASSISTANT_DELTA_COMMITTED,
        status="completed",
        payload={"content": "再根据日志给出结论。"},
        source="session_ui_capture",
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-interleaved",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": "先给出初步判断。\n\n再根据日志给出结论。",
            "feedbackEvents": [
                {
                    "sequence": 2,
                    "kind": "tool",
                    "status": "done",
                    "name": "read_log",
                    "summary": "读取最新日志",
                    "resultPreview": "found rendering bottleneck",
                }
            ],
        },
        source="persist_session_turn_result",
    )

    detail = session_service.get_session_detail("session-live")
    message = detail["messages"][-1]
    _assert_v3_assistant_message(message)
    assert [item["type"] for item in message["turnItems"]] == ["tool_call", "agent_message"]
    assert message["turnItems"][0]["toolName"] == "read_log"
    assert _assistant_visible_text(message) == "先给出初步判断。\n\n再根据日志给出结论。"


def test_capture_session_ui_stream_does_not_mark_returned_degraded_tool_running(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-feedback", turn_id="turn-degraded")
    with session_service._capture_session_ui_stream("session-feedback", capture):
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_START,
            {
                "name": "cli_tool",
                "args": {"command": "cd C:\\Users\\17533\\Desktop\\Vibelution && pytest | head -50"},
"callId": "call-cli_tool-1"},
        )
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_SUCCESS,
            {
                "name": "cli_tool",
                "args": {"command": "cd C:\\Users\\17533\\Desktop\\Vibelution && pytest | head -50"},
                "summary": "[跨平台警告] 在 Windows 上检测到 Unix shell 片段",
                "result": "[跨平台警告] 在 Windows 上检测到 Unix shell 片段",
                "transportStatus": "returned",
                "semanticStatus": "degraded",
                "durationMs": 546,
"callId": "call-cli_tool-1"},
        )

    live_state = session_service._snapshot_session_live_output("session-feedback")
    assert live_state is not None
    tool_events = [item for item in live_state.feedback_events if item["kind"] == "tool"]
    assert [item["status"] for item in tool_events] == ["degraded"]
    assert tool_events[0]["semanticStatus"] == "degraded"

    events = load_conversation_events(tmp_path, "session-feedback")
    tool_result = next(item for item in events if item.event_type == EVENT_TOOL_RESULT)
    assert tool_result.status == "degraded"
    assert tool_result.payload["toolCall"]["status"] == "degraded"
    assert tool_result.payload["toolCall"]["semanticStatus"] == "degraded"


def test_capture_session_ui_stream_filters_llm_status_by_event_context(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    published: list[str] = []
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda session_id: published.append(session_id))
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live", turn_id="turn-llm")
    with session_service._capture_session_ui_stream("session-live", capture):
        session_service.get_event_bus().publish(
            session_service.EventNames.LLM_STATUS,
            {
                "status": "retrying",
                "session_id": "other-session",
                "turn_id": "turn-llm",
                "attempt": 1,
                "max_attempts": 5,
                "category": "network_error",
            },
        )
        session_service.get_event_bus().publish(
            session_service.EventNames.LLM_STATUS,
            {
                "status": "retrying",
                "session_id": "session-live",
                "turn_id": "turn-llm",
                "attempt": 2,
                "max_attempts": 5,
                "category": "network_error",
            },
        )

    live_state = session_service._snapshot_session_live_output("session-live")
    assert live_state is not None
    assert live_state.stage == "model_retry"
    assert "2/5" in live_state.content


def test_turn_circuit_breaker_records_next_state_signal_with_turn_id(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )

    session_service._record_session_turn_circuit_breaker_event(
        "session-live",
        {
            "error": "litellm.BadGatewayError: BadGatewayError: OpenAIException - {\"error\":{\"message\":\"Upstream request failed\"}}",
            "llm_failure": {
                "category": "server_error",
                "retryable": True,
                "attempts": 5,
                "max_attempts": 5,
                "consecutive_failures": 5,
                "stop_reason": "retry budget exhausted",
            },
        },
        turn_id="turn-42",
        turn_index=2,
    )

    signals = _read_next_state_signals(tmp_path, session_id="session-live", turn_id="turn-42")
    assert any(item["kind"] == "provider_failure" for item in signals)
    assert any(item["relatedEventCode"] == "conversation.turn_circuit_breaker" for item in signals)
    assert any(item["metadata"]["continuationTurn"] == 2 for item in signals)


def test_submit_session_message_recovers_when_scheduler_fails(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    _bind_seeded_submittable_agent(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    def fail_schedule(context):
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr(session_service, "_schedule_session_turn", fail_schedule)

    with pytest.raises(RuntimeError, match="scheduler unavailable"):
        session_service.submit_session_message("session-live", "继续检查调度失败恢复")

    payload = session_service.get_session_detail("session-live")
    assert payload["currentPhase"] == "failed"
    assert payload["messages"][-1]["role"] == "user"
    assert payload["messages"][-1]["content"] == "继续检查调度失败恢复"
    assert "scheduler unavailable" in payload["lastTurnError"]["message"]
    assert session_service._is_session_running("session-live") is False
    assert session_service._get_session_turn_control("session-live") is None
    assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["status"] == "failed"
    assert latest_run["errorType"] == "RuntimeError"
    assert latest_run["userMessage"] == "继续检查调度失败恢复"
    assert "scheduler unavailable" in latest_run["error"]
    event_codes = [args[2] for args, _kwargs in recorded_scene_events if len(args) >= 3]
    assert "conversation.turn.started" in event_codes
    assert "conversation.turn.scheduled" in event_codes
    assert "conversation.turn.failure_persisted" in event_codes


def test_submit_session_message_write_intent_rejects_self_evolution_lease(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    self_snapshot = {
        "runId": "web-self-active-for-chat",
        "runKind": "self_evolution_run",
        "status": "running",
        "leases": ["evolution_transaction", "worktree_write", "memory_write"],
        "startedAt": "2026-05-21T00:00:00",
        "updatedAt": "2026-05-21T00:00:00",
    }
    self_evolution_control_service.persist_manager_run_snapshot("self", self_snapshot, active_run_id=self_snapshot["runId"])

    readonly = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "解释当前状态"},
    )

    assert readonly.status_code == 202
    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")

    write_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复这个 bug", "writeIntent": True},
    )

    assert write_response.status_code == 409
    assert "resource" in write_response.json()["detail"].lower() or "资源" in write_response.json()["detail"]


def test_request_stop_session_turn_persists_stop_snapshot_and_releases_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    monkeypatch.setattr(session_service, "_cancel_queued_session_turn", lambda session_id, turn_id: True)

    try:
        submit_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "先继续分析当前对话提交流程"},
        )

        assert submit_response.status_code == 202
        running_payload = submit_response.json()
        assert running_payload["currentPhase"] == "running"
        assert running_payload["stopRequested"] is False
        active_control = session_service._get_session_turn_control("session-live")
        assert active_control is not None

        stop_response = client.post(
            "/api/sessions/session-live/stop",
            json={"turnId": active_control.turn_id},
        )

        assert stop_response.status_code == 202
        payload = stop_response.json()
        assert payload["currentPhase"] == "ready"
        assert payload["stopRequested"] is False
        assert payload["messages"][-1]["role"] == "assistant"
        assert "本轮已按请求停止" in _assistant_visible_text(payload["messages"][-1])
        stop_signals = _read_next_state_signals(tmp_path, session_id="session-live")
        assert any(item["kind"] == "user_stops" and item["turnId"] for item in stop_signals)

        continue_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "继续"},
        )
        assert continue_response.status_code == 202
        assert continue_response.json()["currentPhase"] == "running"
        continue_signals = _read_next_state_signals(tmp_path, session_id="session-live")
        assert any(item["kind"] == "user_continues" for item in continue_signals)
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")


def test_submit_session_safe_guidance_records_signal_without_stopping(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        submit_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "先继续分析当前对话提交流程"},
        )
        assert submit_response.status_code == 202

        guidance_text = "这一轮先不要改代码，只汇报安全引导链路。\n第二行必须进入模型。\n第三行也不能省略。"
        guidance_response = client.post(
            "/api/sessions/session-live/guidance",
            json={"mode": "safe", "content": guidance_text},
        )

        assert guidance_response.status_code == 202
        payload = guidance_response.json()
        assert payload["currentPhase"] == "running"
        assert payload["stopRequested"] is False
        guidance_messages = [
            item
            for item in payload["messages"]
            if isinstance(item, dict)
            and str(((item.get("metadata") or {}).get("kind") or "")).strip() == "user_guidance"
        ]
        assert guidance_messages
        assert guidance_messages[-1]["content"] == guidance_text
        latest_index = session_service._latest_user_message_index(payload["messages"])
        assert latest_index >= 0
        latest_metadata = payload["messages"][latest_index].get("metadata") or {}
        assert str(latest_metadata.get("kind") or "") != "user_guidance"
        summaries = session_service._recent_session_guidance_summaries("session-live")
        assert guidance_text in summaries
        signals = _read_next_state_signals(tmp_path, session_id="session-live")
        assert any(
            item["kind"] == "user_guidance"
            and "这一轮先不要改代码，只汇报安全引导链路。" in str(item.get("summary") or "")
            and item["turnId"]
            for item in signals
        )
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")


def test_submit_session_interrupt_guidance_records_signal_and_stops(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    monkeypatch.setattr(session_service, "_cancel_queued_session_turn", lambda session_id, turn_id: True)

    try:
        submit_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "先继续分析当前对话提交流程"},
        )
        assert submit_response.status_code == 202

        guidance_response = client.post(
            "/api/sessions/session-live/guidance",
            json={"mode": "interrupt", "content": "停止当前思路，改为先审计数据流。"},
        )

        assert guidance_response.status_code == 202
        payload = guidance_response.json()
        assert payload["currentPhase"] == "ready"
        assert payload["stopRequested"] is False
        assert "本轮已按请求停止" in _assistant_visible_text(payload["messages"][-1])
        signals = _read_next_state_signals(tmp_path, session_id="session-live")
        assert any(
            item["kind"] == "user_interrupt_guidance"
            and item["summary"] == "停止当前思路，改为先审计数据流。"
            and item["turnId"]
            for item in signals
        )
        assert any(item["kind"] == "user_stops" for item in signals)
        interrupt_messages = [
            item
            for item in payload["messages"]
            if isinstance(item, dict)
            and str(((item.get("metadata") or {}).get("kind") or "")).strip() == "user_interrupt_guidance"
        ]
        assert interrupt_messages
        assert interrupt_messages[-1]["content"] == "停止当前思路，改为先审计数据流。"
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")


def test_request_stop_session_turn_reuses_active_work_run_when_controller_is_missing(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    _bind_seeded_submittable_agent(tmp_path)
    scene_events = []

    def record_scene_event(component, phase, event_code, **kwargs):
        scene_events.append((component, phase, event_code, kwargs))
        return {"accepted": True}

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", record_scene_event)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )
    session_service._set_session_running("session-live", True, turn_id="existing-chat-turn")
    session_service._clear_session_turn_control("session-live")
    session_service._WORK_RUN_STORE.persist_snapshot(
        "chat_turn",
        {
            "runId": "existing-chat-turn",
            "runKind": "chat_turn",
            "track": "dialogue",
            "sessionId": "session-live",
            "status": "running",
            "currentPhase": "running",
            "leases": ["readonly_chat"],
            "userMessage": "上一轮控制器丢失但 WorkRun 仍活跃",
            "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "finishedAt": "",
        },
        active_run_id="existing-chat-turn",
    )

    try:
        stop_response = client.post(
            "/api/sessions/session-live/stop",
            json={"turnId": "existing-chat-turn"},
        )

        assert stop_response.status_code == 202
        payload = stop_response.json()
        assert payload["currentPhase"] == "ready"
        assert payload["stopRequested"] is False
        assert "本轮已按请求停止" in _assistant_visible_text(payload["messages"][-1])
        assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None
        latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
        assert latest_run["runId"] == "existing-chat-turn"
        assert latest_run["status"] == "stopped"
        assert latest_run["finishedAt"]
        assert any(
            event[2] == "conversation.turn_control_recovered"
            and event[3]["fields"]["turnId"] == "existing-chat-turn"
            and event[3]["fields"]["reusedActiveRun"] is True
            for event in scene_events
        )
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


@pytest.mark.slow
def test_stop_requested_turn_persists_visible_stop_message(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )

    started = threading.Event()
    finished = threading.Event()
    worker_threads = []

    class StoppableAgent:
        def __init__(self):
            self.stop_checker = None

        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def set_turn_interrupt_checker(self, checker):
            self.stop_checker = checker

        def run_single_turn(self, initial_prompt=None):
            started.set()
            for _ in range(200):
                reason = self.stop_checker() if callable(self.stop_checker) else ""
                if reason:
                    return {
                        "status": "stopped",
                        "summary": "",
                        "raw_output": "",
                        "stop_requested": True,
                        "stop_reason": reason,
                        "tool_call_count": 0,
                        "tool_trace": [],
                    }
                time.sleep(0.01)
            return {
                "status": "completed",
                "summary": "不该走到这里。",
                "raw_output": "不该走到这里。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: StoppableAgent())

    def run_async(context):
        def _worker():
            try:
                session_service._run_session_turn(context)
            finally:
                finished.set()

        thread = threading.Thread(target=_worker, daemon=True)
        worker_threads.append(thread)
        thread.start()

    monkeypatch.setattr(session_service, "_schedule_session_turn", run_async)

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续推进当前网页会话的终止能力"},
    )

    assert response.status_code == 202
    assert started.wait(1.0), "expected the background turn to start"

    active_control = session_service._get_session_turn_control("session-live")
    assert active_control is not None
    stop_response = client.post(
        "/api/sessions/session-live/stop",
        json={"turnId": active_control.turn_id},
    )

    assert stop_response.status_code == 202
    assert stop_response.json()["currentPhase"] in {"stopping", "ready"}
    assert stop_response.json().get("activeTurnId") in {"", active_control.turn_id}
    assert finished.wait(2.0), "expected the stopped turn to finish"

    for thread in worker_threads:
        thread.join(timeout=0.2)

    detail_response = client.get("/api/sessions/session-live")
    assert detail_response.status_code == 200
    payload = detail_response.json()
    assert payload["currentPhase"] == "ready"
    assert payload["stopRequested"] is False
    assert payload["messages"][-1]["role"] == "assistant"
    assert "本轮已按请求停止" in _assistant_visible_text(payload["messages"][-1])


@pytest.mark.slow
def test_stop_turn_stays_stopping_until_registered_tool_is_physically_quiescent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )

    started = threading.Event()
    worker_finished = threading.Event()
    pending_tool: Future[str] = Future()
    worker_threads: list[threading.Thread] = []
    registration_results: list[bool] = []

    class ToolStoppingAgent:
        def __init__(self):
            self.stop_checker = None

        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def set_turn_interrupt_checker(self, checker):
            self.stop_checker = checker

        def run_single_turn(self, initial_prompt=None):
            registration_results.append(
                register_current_tool_future(pending_tool, tool_name="blocking_test_tool")
            )
            started.set()
            for _ in range(200):
                reason = self.stop_checker() if callable(self.stop_checker) else ""
                if reason:
                    return {
                        "status": "stopped",
                        "summary": "",
                        "raw_output": "",
                        "stop_requested": True,
                        "stop_reason": reason,
                        "tool_call_count": 1,
                        "tool_trace": [{"name": "blocking_test_tool", "status": "cancelled"}],
                    }
                time.sleep(0.01)
            raise AssertionError("expected the test turn to observe the stop request")

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ToolStoppingAgent())

    def run_async(context):
        def _worker():
            try:
                session_service._run_session_turn(context)
            finally:
                worker_finished.set()

        thread = threading.Thread(target=_worker, daemon=True)
        worker_threads.append(thread)
        thread.start()

    monkeypatch.setattr(session_service, "_schedule_session_turn", run_async)

    try:
        response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "执行一个需要停止的阻塞工具"},
        )
        assert response.status_code == 202
        assert started.wait(1.0)
        active_control = session_service._get_session_turn_control("session-live")
        assert active_control is not None

        stop_response = client.post(
            "/api/sessions/session-live/stop",
            json={"turnId": active_control.turn_id},
        )

        assert stop_response.status_code == 202
        assert registration_results == [True]
        assert stop_response.json()["currentPhase"] == "stopping"
        assert stop_response.json()["activeTurnId"] == active_control.turn_id
        assert stop_response.json()["stopRequested"] is True
        assert worker_finished.wait(0.05) is False

        pending_tool.set_result("physically complete")
        assert worker_finished.wait(2.0)

        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["currentPhase"] == "ready"
        assert payload["activeTurnId"] == ""
        assert payload["stopRequested"] is False
        assert payload["messages"][-1]["role"] == "assistant"
    finally:
        if not pending_tool.done():
            pending_tool.set_result("test cleanup")
        for thread in worker_threads:
            thread.join(timeout=1)
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_stop_queued_session_turn_persists_partial_snapshot_and_allows_immediate_continue(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "chat-stop-resume",
            "kind": "coding",
            "status": "reading",
            "title": "修复 Web Chat 停止恢复",
            "goal": "修复 Web Chat 停止恢复",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "已定位停止按钮问题。",
            "updated_at": "2026-05-20T16:24:53",
            "metadata": {"source": "task_tool"},
        },
    )
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    monkeypatch.setattr(session_service, "_cancel_queued_session_turn", lambda session_id, turn_id: True)

    submit_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复停止恢复"},
    )
    assert submit_response.status_code == 202
    old_control = session_service._get_session_turn_control("session-live")
    assert old_control is not None

    session_service._set_session_live_output(
        "session-live",
        thought="我已经定位到 stop checker。",
        content="已完成一部分：停止请求进入后会设置 stop flag。",
        tool_calls=[{"name": "read_file_tool", "status": "done", "summary": "session_service.py"}],
    )

    stop_response = client.post(
        "/api/sessions/session-live/stop",
        json={"turnId": old_control.turn_id},
    )
    assert stop_response.status_code == 202
    stopped_payload = stop_response.json()
    assert stopped_payload["currentPhase"] == "ready"
    assert stopped_payload["stopRequested"] is False
    stopped_message = stopped_payload["messages"][-1]
    assert "已完成一部分" in _assistant_visible_text(stopped_message)
    assert "本轮已按请求停止" in _assistant_visible_text(stopped_message)
    assert [item["text"] for item in _assistant_turn_items(stopped_message, "reasoning")] == [
        "我已经定位到 stop checker。"
    ]
    assert _assistant_tool_summaries(stopped_message)[0]["name"] == "read_file_tool"
    assert stopped_payload["messages"][-1]["metadata"]["turnId"] == old_control.turn_id
    ledger_events = load_conversation_events(tmp_path, "session-live")
    assert any(event.event_type == EVENT_TURN_INTERRUPTED and event.turn_id == old_control.turn_id for event in ledger_events)

    continue_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )
    assert continue_response.status_code == 202
    new_control = session_service._get_session_turn_control("session-live")
    assert new_control is not None
    assert new_control.turn_id != old_control.turn_id

    session_service._clear_session_turn_control("session-live", turn_id=old_control.turn_id)
    assert session_service._get_session_turn_control("session-live").turn_id == new_control.turn_id

    session_service._set_session_running("session-live", False, turn_id=old_control.turn_id)
    assert session_service._is_session_running("session-live") is True

    session_service._set_session_running("session-live", False, turn_id=new_control.turn_id)
    session_service._clear_session_turn_control("session-live", turn_id=new_control.turn_id)


def test_stop_active_session_turn_blocks_continue_until_worker_observes_cancel_token(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    submit_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "第一轮会被停止"},
    )
    assert submit_response.status_code == 202
    old_control = session_service._get_session_turn_control("session-live")
    assert old_control is not None
    old_turn_id = old_control.turn_id

    stop_response = client.post(
        "/api/sessions/session-live/stop",
        json={"turnId": old_turn_id},
    )
    assert stop_response.status_code == 202
    assert old_control.snapshot()["stopRequested"] is True
    assert "操作者请求停止当前轮" in old_control.snapshot()["stopReason"]

    continue_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续新一轮"},
    )
    assert continue_response.status_code == 409
    assert session_service._get_session_turn_control("session-live") is old_control

    session_service._set_session_running("session-live", False, turn_id=old_turn_id)
    session_service._clear_session_turn_control("session-live", turn_id=old_turn_id)

    continue_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续新一轮"},
    )
    assert continue_response.status_code == 202
    new_control = session_service._get_session_turn_control("session-live")
    assert new_control is not None
    assert new_control.turn_id != old_turn_id
    assert old_control.snapshot()["stopRequested"] is True

    session_service._set_session_running("session-live", False, turn_id=new_control.turn_id)
    session_service._clear_session_turn_control("session-live", turn_id=new_control.turn_id)


def test_session_detail_reconciles_open_conversation_ledger_after_restart(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    append_conversation_event(tmp_path, "session-live", "turn-open", EVENT_TURN_STARTED, status="running")

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    events = load_conversation_events(tmp_path, "session-live")
    assert any(
        event.event_type == EVENT_TURN_INTERRUPTED
        and event.turn_id == "turn-open"
        and event.payload.get("reason") == "detail_loaded_after_restart"
        for event in events
    )


def test_stale_stopped_turn_does_not_run_after_immediate_continue(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    scheduled_contexts = []
    stale_agent_called = False

    class StaleAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def set_turn_interrupt_checker(self, checker):
            self.stop_checker = checker

        def run_single_turn(self, initial_prompt=None):
            nonlocal stale_agent_called
            stale_agent_called = True
            return {
                "status": "completed",
                "summary": "旧轮结果不应该写入当前会话。",
                "raw_output": "旧轮结果不应该写入当前会话。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(session_service, "_cancel_queued_session_turn", lambda session_id, turn_id: True)
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: StaleAgent())

    try:
        first_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第一轮需要停止"},
        )
        assert first_response.status_code == 202
        assert len(scheduled_contexts) == 1

        stop_response = client.post(
            "/api/sessions/session-live/stop",
            json={"turnId": scheduled_contexts[0]["turn_id"]},
        )
        assert stop_response.status_code == 202

        continue_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第二轮已经开始"},
        )
        assert continue_response.status_code == 202
        assert continue_response.json()["currentPhase"] == "running"
        assert len(scheduled_contexts) == 2

        session_service._run_session_turn(scheduled_contexts[0])

        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert stale_agent_called is False
        assert payload["currentPhase"] == "running"
        assert payload["messages"][-2]["role"] == "user"
        assert payload["messages"][-2]["content"] == "第二轮已经开始"
        assert payload["messages"][-1]["role"] == "assistant"
        _assert_context_prepare_overlay(payload["messages"][-1])
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_stop_during_agent_call_does_not_record_late_completed_result(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    lifecycle_events = []

    def record_lifecycle_event(session_id, phase, **kwargs):
        lifecycle_events.append(
            {
                "session_id": session_id,
                "phase": phase,
                "turn_id": kwargs.get("turn_id", ""),
                "outcome": kwargs.get("outcome", ""),
                "fields": dict(kwargs.get("fields") or {}),
            }
        )

    class LateCompletedAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def set_turn_interrupt_checker(self, checker):
            self.stop_checker = checker

        def run_single_turn(self, initial_prompt=None):
            control = session_service._get_session_turn_control("session-live")
            assert control is not None
            control.request_stop("操作者请求停止当前轮。")
            return {
                "status": "completed",
                "summary": "停止后的迟到完成结果不应该落盘。",
                "raw_output": "停止后的迟到完成结果不应该落盘。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        record_lifecycle_event,
    )
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: LateCompletedAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    try:
        response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "这轮会在模型调用期间被停止"},
        )

        assert response.status_code == 202
        latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert latest_run["status"] == "stopped_by_user"
        assert payload["currentPhase"] == "ready"
        assert "本轮已按请求停止" in _assistant_visible_text(payload["messages"][-1])
        assert "迟到完成结果" not in _assistant_visible_text(payload["messages"][-1])
        assert not any(
            event["phase"] in {"agent_turn_returned", "terminal_result"} and event["outcome"] == "completed"
            for event in lifecycle_events
        )
        assert any(
            event["phase"] == "stop_observed"
            and event["outcome"] == "stopped"
            and event["fields"].get("stage") == "agent_return"
            for event in lifecycle_events
        )
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_stale_turn_live_output_does_not_overwrite_new_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    monkeypatch.setattr(session_service, "_cancel_queued_session_turn", lambda session_id, turn_id: True)

    try:
        first_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第一轮需要停止"},
        )
        assert first_response.status_code == 202
        old_control = session_service._get_session_turn_control("session-live")
        assert old_control is not None

        stop_response = client.post(
            "/api/sessions/session-live/stop",
            json={"turnId": old_control.turn_id},
        )
        assert stop_response.status_code == 202

        continue_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第二轮已经开始"},
        )
        assert continue_response.status_code == 202
        new_control = session_service._get_session_turn_control("session-live")
        assert new_control is not None

        session_service._set_session_live_output(
            "session-live",
            turn_id=new_control.turn_id,
            content="新轮正在输出。",
        )
        session_service._set_session_live_output(
            "session-live",
            turn_id=old_control.turn_id,
            content="旧轮迟到输出，不应该可见。",
        )

        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["messages"][-1]["status"] == "running"
        assert _assistant_visible_text(payload["messages"][-1]) == "新轮正在输出。"
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_stale_turn_live_output_clear_does_not_remove_new_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-done",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "已完成上一轮。"},
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="turn-new")
    session_service._set_session_live_output(
        "session-live",
        turn_id="turn-new",
        content="新轮正在输出。",
    )

    session_service._clear_session_live_output("session-live", turn_id="turn-old")
    response = client.get("/api/sessions/session-live")
    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["status"] == "running"
    assert _assistant_visible_text(payload["messages"][-1]) == "新轮正在输出。"

    session_service._clear_session_live_output("session-live", turn_id="turn-new")
    session_service._set_session_running("session-live", False, turn_id="turn-new")
    response_after_clear = client.get("/api/sessions/session-live")
    assert response_after_clear.status_code == 200
    assert response_after_clear.json()["messages"][-1]["status"] == "completed"


def test_session_detail_includes_live_thought_draft(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        thought="先把这轮的思考过程挂进消息卡片。",
        feedback_events=[
            {
                "sequence": 1,
                "kind": "thought",
                "status": "running",
                "summary": "先把这轮的思考过程挂进消息卡片。",
                "resultPreview": "先把这轮的思考过程挂进消息卡片。",
            }
        ],
        mental_snapshot={
            "mood": "专注",
            "feeling": "链路已经接近打通。",
            "whisper": "再把默认折叠状态接上。",
            "cognitiveState": "productive",
        },
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    live_message = payload["messages"][-1]
    _assert_v3_assistant_message(live_message)
    assert live_message["status"] == "running"
    assert [item["text"] for item in _assistant_turn_items(live_message, "reasoning")] == [
        "先把这轮的思考过程挂进消息卡片。"
    ]
    assert any(
        item.get("type") == "status"
        and item.get("code") == "mental_snapshot"
        and (item.get("metadata") or {}).get("mentalSnapshot", {}).get("mood") == "专注"
        for item in live_message["turnItems"]
    )


def test_session_detail_hides_partial_state_live_answer(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        content="<state",
        tool_calls=[{"name": "read_file_tool", "status": "running"}],
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["status"] == "running"
    assert _assistant_visible_text(payload["messages"][-1]) == ""
    assert _assistant_tool_summaries(payload["messages"][-1]) == [
        {"name": "read_file_tool", "status": "running"}
    ]


def test_session_detail_hides_dsml_and_lone_angle_live_answer(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        content="<state>\n{}\n</｜｜DSML｜｜parameter>\n</invoke>\n</｜｜DSML｜｜tool_calls>\n<",
        thought="</invoke>\n<",
        tool_calls=[{"name": "spawn_agent_tool", "status": "running"}],
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["status"] == "running"
    assert _assistant_visible_text(payload["messages"][-1]) == ""
    assert "thought" not in payload["messages"][-1]
    assert _assistant_tool_summaries(payload["messages"][-1]) == [
        {"name": "spawn_agent_tool", "status": "running"}
    ]


def test_session_detail_hides_parameter_live_answer(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        content="连续被拦截。让我尝试拆分写入。\n</parameter>",
        thought="</parameter>\n<parameter",
        tool_calls=[{"name": "cli_tool", "status": "running"}],
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["status"] == "running"
    assert _assistant_visible_text(payload["messages"][-1]) == "连续被拦截。让我尝试拆分写入。"
    assert "thought" not in payload["messages"][-1]
    assert _assistant_tool_summaries(payload["messages"][-1]) == [
        {"name": "cli_tool", "status": "running"}
    ]


def test_session_detail_sanitizes_persisted_protocol_messages_and_active_task(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "polluted-protocol",
            "kind": "coding",
            "status": "reading",
            "title": "<invoke name=\"read_file_tool\"><parameter name=\"file_path\">secret.py</parameter></invoke>",
            "goal": "<state",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "继续检查。\n</parameter>",
            "next_action": "<parameter name=\"file_path\">secret.py</parameter>",
            "updated_at": "2026-05-20T17:54:06",
            "metadata": {"source": "task_tool"},
        },
    )
    state = load_chat_state(tmp_path)
    save_chat_state(tmp_path, state)
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-protocol",
        EVENT_ASSISTANT_MESSAGE,
        status="running",
        payload={
            "content": (
                "继续检查。\n"
                '<invoke name="read_file_tool">'
                '<parameter name="file_path">tests/prompt_debugger.py</parameter>'
                "</invoke>\n"
                "<state"
            ),
            "thought": "</parameter>\n<parameter",
            "toolCalls": [{"name": "read_file_tool"}],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200, response.json()
    payload = response.json()
    normalized_task = session_service._normalize_session_active_task(
        load_chat_state(tmp_path)["conversations"][0]["active_task"]
    )
    assistant = payload["messages"][-1]
    assert _assistant_visible_text(assistant) == "继续检查。"
    assert "thought" not in assistant
    assert payload["taskSummary"] == "继续检查。"
    assert payload["activeTask"]["latestSummary"] == "继续检查。"
    assert payload["activeTask"]["title"] == ""
    assert payload["activeTask"]["goal"] == ""
    assert payload["activeTask"]["nextAction"] == ""
    assert normalized_task["latest_summary"] == "继续检查。"
    assert normalized_task["title"] == ""
    assert normalized_task["goal"] == ""
    assert normalized_task["next_action"] == ""
    assert "<invoke" not in json.dumps(payload, ensure_ascii=False)
    assert "<parameter" not in json.dumps(payload, ensure_ascii=False)
    assert "<state" not in json.dumps(payload, ensure_ascii=False)


def test_session_detail_ignores_old_chat_state_runtime_notice_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="idle")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"] = [
        {
            "role": "assistant",
            "content": "上一轮运行已被中断，当前会话已恢复为可继续状态。",
            "timestamp": "2026-05-29T18:16:31",
        },
        {
            "role": "assistant",
            "content": "继续分析日志。",
            "timestamp": "2026-05-29T18:16:32",
        },
    ]
    save_chat_state(tmp_path, state)
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-real-message",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "继续分析日志。"},
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert [_conversation_message_text(message) for message in payload["messages"]][-1:] == ["继续分析日志。"]
    assert all("已被中断" not in _conversation_message_text(message) for message in payload["messages"])
    assert payload["runtimeNotices"] == []


def test_session_detail_keeps_runtime_notice_outside_ledger_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="idle")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["runtime_notices"] = [
        {
            "kind": "runtime_notice",
            "level": "info",
            "message": "当前 Agent 正在处理上一项任务，本轮已进入队列...",
            "timestamp": "2026-05-29T21:36:20",
            "source": "conversation.queued",
        }
    ]
    save_chat_state(tmp_path, state)
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-user",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "按照这个提示词来生成图片"},
        timestamp="2026-05-29T21:36:19",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "_ensure_agent_default_avatar", lambda agent, **kwargs: None, raising=False)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["messages"][-1]["role"] == "user"
    assert all("本轮已进入队列" not in _conversation_message_text(message) for message in payload["messages"])
    assert len(payload["runtimeNotices"]) == 1
    assert payload["runtimeNotices"][0]["kind"] == "runtime_notice"
    assert "本轮已进入队列" in payload["runtimeNotices"][0]["message"]


def test_session_detail_shows_current_runtime_notice_until_real_message_arrives(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="idle")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["runtime_notices"] = [
        {
            "kind": "turn_recovered",
            "level": "warning",
            "message": "上一轮运行已被中断，当前会话已恢复为可继续状态。",
            "timestamp": "2026-05-29T18:16:31",
            "source": "conversation.turn_recovered",
        },
        {
            "kind": "turn_recovered",
            "level": "warning",
            "message": "上一轮运行已被中断，当前会话已恢复为可继续状态。",
            "timestamp": "2026-05-29T18:16:32",
            "source": "conversation.turn_recovered",
        },
    ]
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    fresh_notice = client.get("/api/sessions/session-live").json()
    assert len(fresh_notice["runtimeNotices"]) == 1
    assert fresh_notice["runtimeNotices"][0]["source"] == "conversation.turn_recovered"

    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-after-notice",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "已恢复并继续完成任务。"},
        timestamp="2026-05-29T18:16:33",
    )

    settled = client.get("/api/sessions/session-live").json()
    assert settled["runtimeNotices"] == []


def test_session_detail_recovers_stale_running_legacy_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="idle")
    state = load_chat_state(tmp_path)
    conversation = state["conversations"][0]
    conversation["last_turn_status"] = "running"
    conversation["messages"] = [
        {
            "role": "user",
            "content": "旧会话里只有 legacy 消息",
            "timestamp": "2026-05-29T18:16:30",
        },
        {
            "role": "assistant",
            "content": "legacy 历史回复应继续显示",
            "timestamp": "2026-05-29T18:16:31",
        },
    ]
    event_path = tmp_path / "workspace" / "sessions" / "session-live" / "turn_journal.jsonl"
    if event_path.exists():
        event_path.unlink()
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert [_conversation_message_text(message) for message in payload["messages"]] == [
        "旧会话里只有 legacy 消息",
        "legacy 历史回复应继续显示",
    ]
    assert payload["runtimeNotices"][-1]["kind"] == "turn_recovered"
    persisted = load_chat_state(tmp_path)["conversations"][0]
    assert persisted["last_turn_status"] == "ready"
    assert "messages" not in persisted


def test_submit_session_message_persists_lease_conflict_notice_without_llm_call(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="idle")
    _bind_seeded_submittable_agent(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append({"args": args, "kwargs": kwargs}) or {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "load_evolution_active_run_snapshot",
        lambda kind: {
            "runId": "web-supervised-busy",
            "runKind": "supervised_worktree_evolution_run",
            "status": "running",
            "leases": ["evaluation", "worktree_write"],
        } if kind == "supervised" else None,
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "修复这个前端显示问题"},
    )

    assert response.status_code == 409
    assert "worktree_write" in response.json()["detail"]
    detail = client.get("/api/sessions/session-live").json()
    assert _assistant_visible_text(detail["messages"][-1]) != "修复这个前端显示问题"
    assert detail["runtimeNotices"][-1]["kind"] == "turn_rejected"
    assert "HTTP 409" in detail["runtimeNotices"][-1]["message"]
    assert "web-supervised-busy" in detail["runtimeNotices"][-1]["message"]
    assert detail["llmUsage"]["source"] == "not_called"
    assert detail["cacheUsage"]["source"] == "not_called"
    assert detail["lastCacheComposition"]["source"] == "not_called"
    assert detail["lastTurnError"]["httpStatus"] == 409
    assert any(
        event["args"][:3] == ("conversation", "turn_rejected", "conversation.turn.rejected_before_llm")
        and event["kwargs"]["fields"]["llmCalled"] is False
        and event["kwargs"]["fields"]["conflictRunId"] == "web-supervised-busy"
        for event in events
    )


def test_session_detail_recovers_stale_running_state(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["last_turn_status"] = "running"
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_service._WORK_RUN_STORE.persist_snapshot(
        "chat_turn",
        {
            "runId": "stale-turn-1",
            "runKind": "chat_turn",
            "track": "dialogue",
            "sessionId": "session-live",
            "status": "running",
            "currentPhase": "running",
            "leases": ["readonly_chat"],
            "userMessage": "继续前端开发",
            "startedAt": "2026-05-18T11:59:00",
            "updatedAt": "2026-05-18T12:00:00",
            "finishedAt": "",
        },
        active_run_id="stale-turn-1",
    )
    session_service._set_session_running("session-live", False)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "ready"
    assert all("已被中断" not in _conversation_message_text(message) for message in payload["messages"])
    assert payload["runtimeNotices"][-1]["kind"] == "turn_recovered"
    assert payload["runtimeNotices"][-1]["source"] == "conversation.turn_recovered"
    assert "已被中断" in payload["runtimeNotices"][-1]["message"]
    persisted = load_chat_state(tmp_path)
    assert persisted["conversations"][0]["last_turn_status"] == "ready"
    assert "messages" not in persisted["conversations"][0]
    assert persisted["conversations"][0]["runtime_notices"][-1]["kind"] == "turn_recovered"
    assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["runId"] == "stale-turn-1"
    assert latest_run["status"] == "stopped"
    assert latest_run["finishedAt"]


def test_submit_session_message_allows_follow_up_when_previous_turn_finished(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续推进并给出下一步建议。",
                "raw_output": "继续推进并给出下一步建议。",
                "outcome": "done",
                "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
                "tool_call_count": 1,
                "tool_trace": [
                    {"name": "read_file_tool"},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复 web/src/routes/ChatCodingRoute.tsx"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "assistant"
    assert _assistant_visible_text(payload["messages"][-1]) == "继续推进并给出下一步建议。"
    assert payload["currentPhase"] == "ready"
    assert payload["activeTask"] is None


def test_submit_session_message_keeps_streamed_reply_when_final_result_is_control_marker(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ControlMarkerAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            from core.ui import get_ui

            get_ui().stream_response("项目审查完成：核心问题集中在会话持久化和前端状态冗余。", done=False)
            get_ui().stream_response("[outcome=done]", done=True)
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "read_files": ["README.md"],
                "tool_call_count": 1,
                "tool_trace": [{"name": "read_file_tool", "args": {"file_path": "README.md"}}],
            }

    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ControlMarkerAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "审查整个项目并汇报"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert _assistant_visible_text(assistant) == "项目审查完成：核心问题集中在会话持久化和前端状态冗余。"
    assert "[outcome=done]" not in json.dumps(payload, ensure_ascii=False)
    assert payload["activeTask"] is None


def test_submit_session_message_keeps_fallback_streamed_reply_when_final_result_is_control_marker(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class FallbackReplyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            from core.ui import get_ui

            get_ui().stream_response("非流式回答已返回：这是最终可见正文。", done=True)
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: FallbackReplyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续并给出最终回答"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert _assistant_visible_text(assistant) == "非流式回答已返回：这是最终可见正文。"
    assert payload["activeTask"] is None


def test_submit_session_message_marks_completed_file_artifact_task_done(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    output_path = tmp_path / "workspace" / "agents" / "agent-a" / "outputs" / "presentation_structure.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("<html>slides</html>\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ArtifactDoneAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "文件已成功创建：workspace/agents/agent-a/outputs/presentation_structure.html\n任务完成：10页HTML演示文稿已生成。",
                "raw_output": "文件已成功创建：workspace/agents/agent-a/outputs/presentation_structure.html\n任务完成：10页HTML演示文稿已生成。",
                "outcome": "done",
                "tool_call_count": 2,
                "tool_trace": [
                    {
                        "name": "write_file_tool",
                        "args": {"file_path": "workspace/agents/agent-a/outputs/presentation_structure.html"},
                        "result_preview": "[创建文件] [OK] 成功",
                    },
                    {"name": "task_complete_tool", "args": {"status": "done"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ArtifactDoneAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "给我一个10页的ppt,html也可以"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assert payload["currentPhase"] == "ready"
    assert payload["activeTask"]["status"] == "done"
    assert payload["activeTask"]["changedFiles"] == ["workspace/agents/agent-a/outputs/presentation_structure.html"]
    assert payload["activeTask"]["nextAction"] == ""
    assert _assistant_visible_text(payload["messages"][-1]).startswith("文件已成功创建")
    persisted_events = [
        kwargs
        for args, kwargs in recorded_scene_events
        if len(args) >= 3 and args[2] == "conversation.turn.result_persisted"
    ]
    assert persisted_events
    assert persisted_events[-1]["fields"]["activeTaskStatus"] == "done"
    assert persisted_events[-1]["fields"]["activeTaskOutcome"] == "done"
    assert persisted_events[-1]["fields"]["activeTaskChangedFileCount"] == 1


def test_submit_session_message_continues_progress_until_done(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    calls = []

    class ContinuingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "completed",
                    "summary": "<state>",
                    "raw_output": "<state>",
                    "outcome": "progress",
                    "next_action": "继续读取测试工具结构并形成规划。",
                    "read_files": ["tests/prompt_debugger.py"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "规划完成：先复用 prompt_debugger，再包装 BDD 调试入口。",
                "raw_output": "规划完成：先复用 prompt_debugger，再包装 BDD 调试入口。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ContinuingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert len(calls) == 1
    assert "继续完成同一个用户目标" not in str(calls)
    assert _assistant_visible_text(payload["messages"][-1]) == "已查看：tests/prompt_debugger.py\n下一步：继续读取测试工具结构并形成规划。"
    assert payload["currentPhase"] == "needs_continue"


def test_submit_session_message_continues_after_bookkeeping_progress(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    calls = []

    class BookkeepingProgressAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "partial",
                    "summary": "",
                    "raw_output": "",
                    "outcome": "progress",
                    "recommended_next_action": "继续读取证据或直接给出结论。",
                    "tool_call_count": 3,
                    "tool_trace": [
                        {"name": "get_git_status_summary_tool"},
                        {"name": "task_create_tool"},
                        {"name": "task_update_tool"},
                    ],
                }
            return {
                "status": "completed",
                "summary": "已找到优化点：任务管理工具不应算作有效证据推进。",
                "raw_output": "已找到优化点：任务管理工具不应算作有效证据推进。",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: BookkeepingProgressAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "寻找可以优化的地方并汇报"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assert len(calls) == 1
    assert "继续完成同一个用户目标" not in str(calls)
    assert _assistant_visible_text(payload["messages"][-1]) == "下一步：继续读取证据或直接给出结论。"
    assert payload["currentPhase"] == "needs_continue"


def test_submit_session_message_keeps_tools_available_after_tool_progress(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=3),
    )
    calls = []

    class ToolProgressAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None, disable_tools=False):
            calls.append({"prompt": initial_prompt, "disable_tools": disable_tools})
            if len(calls) == 1:
                return {
                    "status": "partial",
                    "summary": "已读取 core/web/services/runtime_scene_service.py，下一步继续校准 runtime scene 摘要。",
                    "raw_output": "已读取 core/web/services/runtime_scene_service.py，下一步继续校准 runtime scene 摘要。",
                    "outcome": "progress",
                    "recommended_next_action": "基于已读证据给出可见结论。",
                    "tool_call_count": 3,
                    "tool_trace": [
                        {"name": "code_symbol_tool"},
                        {"name": "read_file_tool"},
                        {"name": "grep_search_tool"},
                    ],
                }
            assert disable_tools is False
            assert "工具循环保护" not in str(initial_prompt)
            return {
                "status": "completed",
                "summary": "已修正工具路径并收束：runtime scene 摘要需要基于返回内容继续推进。",
                "raw_output": "已修正工具路径并收束：runtime scene 摘要需要基于返回内容继续推进。",
                "outcome": "done",
                "tool_call_count": 1,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ToolProgressAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "好的开始修改"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assert len(calls) == 1
    assert calls[0]["disable_tools"] is False
    assert "继续完成同一个用户目标" not in str(calls)
    assert _assistant_visible_text(payload["messages"][-1]) == "已读取 core/web/services/runtime_scene_service.py，下一步继续校准 runtime scene 摘要。"
    assert payload["currentPhase"] == "needs_continue"


def test_submit_session_message_keeps_previous_continuation_reply_when_done_marker_follows(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    calls = []

    class MarkerAfterReplyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "completed",
                    "summary": "已审查当前项目。以下是汇报结果。\n\n核心问题是回答持久化和 UI 区分度。",
                    "raw_output": "已审查当前项目。以下是汇报结果。\n\n核心问题是回答持久化和 UI 区分度。",
                    "outcome": "progress",
                    "read_files": ["README.md"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "README.md"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: MarkerAfterReplyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你现在审查一下整个项目,并向我汇报结果"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert len(calls) == 1
    assert _assistant_visible_text(assistant) == "已审查当前项目。以下是汇报结果。\n\n核心问题是回答持久化和 UI 区分度。"
    assert "[outcome=done]" not in json.dumps(payload, ensure_ascii=False)
    assert payload["activeTask"] is None


def test_submit_session_message_never_persists_empty_assistant_reply(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class EmptyVisibleAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "<state>{}</state>",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: EmptyVisibleAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请审查项目并汇报"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["role"] == "assistant"
    assert _assistant_visible_text(assistant).strip()
    assert _assistant_visible_text(assistant) == "本轮没有产生可见回复。"

    state = load_chat_state(tmp_path)
    detail = session_service.get_session_detail("session-live")
    persisted_assistant = detail["messages"][-1]
    assert persisted_assistant["role"] == "assistant"
    assert _assistant_visible_text(persisted_assistant) == "本轮没有产生可见回复。"
    assert "messages" not in state["conversations"][0]


def test_session_visible_reply_treats_litellm_empty_placeholder_as_no_visible_reply():
    placeholder = "[System: Empty message content sanitised to satisfy protocol]"
    result = {
        "status": "completed",
        "summary": placeholder,
        "raw_output": placeholder,
        "outcome": "progress",
        "tool_call_count": 1,
        "tool_trace": [
            {"name": "read_file_tool", "args": {"file_path": "README.md"}},
        ],
    }

    visible = session_service._format_visible_reply(result)
    ensured = session_service._ensure_assistant_visible_text(
        visible,
        result=result,
        lang="zh",
    )

    assert visible == "已查看：README.md"
    assert ensured == "已查看：README.md"
    assert session_service._visible_reply_summary_candidate(result) == "已查看：README.md"
    assert placeholder not in ensured


def test_submit_session_message_does_not_persist_xml_protocol_as_reply_or_task(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ProtocolOnlyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": (
                    "继续检查文件。\n"
                    '<invoke name="read_file_tool">'
                    '<parameter name="file_path">tests/prompt_debugger.py</parameter>'
                    "</invoke>\n"
                    "</parameter>"
                ),
                "raw_output": (
                    "继续检查文件。\n"
                    '<invoke name="read_file_tool">'
                    '<parameter name="file_path">tests/prompt_debugger.py</parameter>'
                    "</invoke>\n"
                    "<state"
                ),
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 1,
                "tool_trace": [
                    {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProtocolOnlyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请继续检查 BDD 调试工具规划"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert _assistant_visible_text(assistant) == "继续检查文件。"
    state = load_chat_state(tmp_path)
    persisted_json = json.dumps(state, ensure_ascii=False)
    assert "<invoke" not in persisted_json
    assert "<parameter" not in persisted_json
    assert "</parameter>" not in persisted_json
    assert "<state" not in persisted_json
    assert "active_task" not in state["conversations"][0]


def test_submit_session_message_pauses_progress_without_internal_auto_continue(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    calls = []

    class ProgressThenDoneAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) < 3:
                return {
                    "status": "completed",
                    "summary": "",
                    "raw_output": "",
                    "outcome": "progress",
                    "next_action": "继续读取测试工具结构并形成规划。",
                    "read_files": ["tests/prompt_debugger.py"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "规划完成：包装 prompt_debugger 的 BDD 场景过滤能力。",
                "raw_output": "规划完成：包装 prompt_debugger 的 BDD 场景过滤能力。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProgressThenDoneAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert len(calls) == 1
    assert "任务级持续上限" not in _assistant_visible_text(payload["messages"][-1])
    assert _assistant_visible_text(payload["messages"][-1]) == "已查看：tests/prompt_debugger.py\n下一步：继续读取测试工具结构并形成规划。"
    assert payload["currentPhase"] == "needs_continue"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "needs_continue"
    assert latest_run["finishedAt"]


def test_submit_session_message_preserves_visible_progress_without_limit_prompt(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    calls = []

    class VisibleProgressAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "completed",
                    "summary": "我已经完成第一项优化，并通过基础验证。下一步继续收口剩余日志路径。",
                    "raw_output": "我已经完成第一项优化，并通过基础验证。下一步继续收口剩余日志路径。",
                    "outcome": "progress",
                    "next_action": "继续收口剩余日志路径。",
                    "tool_call_count": 1,
                    "tool_trace": [{"name": "cli_tool", "args": {"command": "python -m py_compile core/logging/__init__.py"}}],
                }
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: VisibleProgressAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续优化日志系统"},
    )

    assert response.status_code == 202
    payload = response.json()
    assistant = payload["messages"][-1]
    assert len(calls) == 1
    assert _assistant_visible_text(assistant) == "我已经完成第一项优化，并通过基础验证。下一步继续收口剩余日志路径。"
    assert "任务级持续上限" not in _assistant_visible_text(assistant)
    assert payload["currentPhase"] == "needs_continue"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "needs_continue"
    state = load_chat_state(tmp_path)
    assert "active_task" not in state["conversations"][0]


def test_submit_session_message_preserves_repeated_visible_progress_once_without_auto_continue(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=4),
    )
    calls = []
    repeated_reply = "已完成日志审查：问题集中在 continuation loop 反复发送同一段可见进展。"

    class RepeatingVisibleProgressAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) < 3:
                return {
                    "status": "completed",
                    "summary": repeated_reply,
                    "raw_output": repeated_reply,
                    "outcome": "progress",
                    "next_action": "继续收束同一问题。",
                    "tool_call_count": 1,
                    "tool_trace": [{"name": "read_file_tool", "args": {"file_path": "core/web/services/session_service.py"}}],
                }
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: RepeatingVisibleProgressAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析对话重复输出问题"},
    )

    assert response.status_code == 202
    payload = response.json()
    assistant = payload["messages"][-1]
    assert len(calls) == 1
    assert _assistant_visible_text(assistant) == repeated_reply
    assert _assistant_visible_text(assistant).count(repeated_reply) == 1
    assert "任务级持续上限" not in _assistant_visible_text(assistant)
    assert payload["currentPhase"] == "needs_continue"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "needs_continue"


def test_submit_session_message_stops_on_inferred_progress_visible_conclusion(tmp_path, monkeypatch):
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    calls = []
    conclusion = "根因已经确认：推断出来的 progress 不应该让已完成的可见结论再次进入 continuation。"

    class InferredProgressConclusionAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            return {
                "status": "completed",
                "summary": conclusion,
                "raw_output": conclusion,
                "outcome": "progress",
                "metadata": {"chat_contract_outcome_source": "inferred"},
                "read_files": ["core/web/services/session_service.py"],
                "tool_call_count": 1,
                "tool_trace": [
                    {
                        "name": "read_file_tool",
                        "args": {"file_path": "core/web/services/session_service.py"},
                    }
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: InferredProgressConclusionAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析对话重复输出问题"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert len(calls) == 1
    assert _assistant_visible_text(payload["messages"][-1]) == conclusion
    assert payload["currentPhase"] == "ready"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "completed"


def test_submit_session_message_completed_turn_ignores_low_configured_limit(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class DoneAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已经完成优化并验证通过。",
                "raw_output": "已经完成优化并验证通过。",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DoneAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "完成这个优化"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert _assistant_visible_text(payload["messages"][-1]) == "已经完成优化并验证通过。"
    assert "任务级持续上限" not in _assistant_visible_text(payload["messages"][-1])
    assert payload["currentPhase"] == "ready"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "completed"


def test_submit_session_continue_preserves_raw_prompt_and_unfinished_task_state(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "bdd-tool-plan",
            "kind": "coding",
            "status": "reading",
            "title": "做一个 BDD 调试测试工具规划并汇报",
            "goal": "做一个 BDD 调试测试工具规划并汇报",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "已读取测试工具结构。",
            "updated_at": "2026-05-20T16:24:53",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    prompts = []

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            prompts.append(initial_prompt)
            return {
                "status": "completed",
                "summary": "继续完成规划：建议包装 prompt_debugger 的 BDD 场景过滤能力。",
                "raw_output": "继续完成规划：建议包装 prompt_debugger 的 BDD 场景过滤能力。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert prompts[0] == "继续"
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["goal"] == "做一个 BDD 调试测试工具规划并汇报"
    assert active_task["title"] == "做一个 BDD 调试测试工具规划并汇报"
    assert active_task["last_user_message"] == "继续"


def test_submit_session_continue_clears_stale_next_action_after_visible_reply(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "stale-next-action",
            "kind": "coding",
            "status": "reading",
            "title": "查看系统提示词",
            "goal": "查看系统提示词",
            "latest_summary": "已完成前半段汇报。",
            "next_action": "发送“继续”以恢复停止前的现场。",
            "updated_at": "2026-05-24T20:10:41",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续上次未完成的汇报，系统提示词已汇总完成。",
                "raw_output": "继续上次未完成的汇报，系统提示词已汇总完成。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["activeTask"]["goal"] == "查看系统提示词"
    assert payload["activeTask"]["latestSummary"] == "继续上次未完成的汇报，系统提示词已汇总完成。"
    assert payload["activeTask"]["nextAction"] == ""

    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["next_action"] == ""


def test_submit_session_continue_keeps_raw_prompt_when_active_task_is_continue(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "polluted-continue",
            "kind": "coding",
            "status": "reading",
            "title": "继续",
            "goal": "继续",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "<state",
            "updated_at": "2026-05-20T17:54:06",
            "metadata": {"source": "task_tool"},
        },
    )
    _bind_seeded_submittable_agent(tmp_path)
    _append_test_ledger_messages(
        tmp_path,
        "session-live",
        [
            {
                "role": "user",
                "content": "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报",
                "timestamp": "2026-05-20T17:50:00",
            },
            {
                "role": "assistant",
                "content": "已达到 Web Chat 任务级持续上限（1 轮），本次先暂停，避免后台无限运行。",
                "timestamp": "2026-05-20T17:51:00",
            },
            {
                "role": "user",
                "content": "继续",
                "timestamp": "2026-05-20T17:53:05",
            },
        ],
        prefix="continue-active",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    prompts = []

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            prompts.append(initial_prompt)
            if len(prompts) == 1:
                return {
                    "status": "completed",
                    "summary": "<state",
                    "raw_output": "<state",
                    "outcome": "progress",
                    "next_action": "继续读取测试工具结构并形成规划。",
                    "read_files": ["tests/prompt_debugger.py"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "规划已恢复：先包装 prompt_debugger 的 BDD 场景过滤能力。",
                "raw_output": "规划已恢复：先包装 prompt_debugger 的 BDD 场景过滤能力。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    assert prompts[0] == "继续"
    payload = response.json()
    assert len(prompts) == 1
    assert "继续完成同一个用户目标" not in str(prompts)
    assert _assistant_visible_text(payload["messages"][-1]) == "已查看：tests/prompt_debugger.py\n下一步：继续读取测试工具结构并形成规划。"
    assert "任务级持续上限" not in _assistant_visible_text(payload["messages"][-1])
    assert "<state" not in _assistant_visible_text(payload["messages"][-1])
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["goal"] == "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"
    assert active_task["title"] == "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"
    assert active_task["latest_summary"] == "已查看：tests/prompt_debugger.py\n下一步：继续读取测试工具结构并形成规划。"


def test_persist_turn_result_cleans_parameter_and_requires_real_stop(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "bdd-tool-plan",
            "kind": "coding",
            "status": "reading",
            "title": "做一个 BDD 调试测试工具规划并汇报",
            "goal": "做一个 BDD 调试测试工具规划并汇报",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "已读取测试工具结构。",
            "updated_at": "2026-05-20T16:24:53",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_service._clear_session_turn_control("session-live")

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "stopped",
            "summary": "连续被拦截。让我尝试拆分写入。\n</parameter>",
            "raw_output": "连续被拦截。让我尝试拆分写入。\n</parameter>",
            "stop_requested": True,
            "outcome": "progress",
            "read_files": ["tests/prompt_debugger.py"],
            "tool_call_count": 0,
            "tool_trace": [],
        },
    )

    state = load_chat_state(tmp_path)
    detail = session_service.get_session_detail("session-live")
    message = detail["messages"][-1]
    assert message["role"] == "assistant"
    assert _assistant_visible_text(message) == "连续被拦截。让我尝试拆分写入。"
    assert _assistant_visible_text(message) != "本轮已按请求停止。"
    assert "messages" not in state["conversations"][0]
    active_task = state["conversations"][0]["active_task"]
    assert active_task["latest_summary"] == "连续被拦截。让我尝试拆分写入。"
    assert "</parameter>" not in json.dumps(active_task, ensure_ascii=False)


def test_session_detail_uses_ready_phase_for_resting_sessions(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_persists_visible_failure(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)

    class FailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: FailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请修复 web/src/routes/ChatCodingRoute.tsx 的提交流程"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert not any(
        message.get("metadata", {}).get("kind") == "turn_error"
        for message in payload["messages"]
    )
    assert payload["lastTurnError"] is not None
    error_text = payload["lastTurnError"]["message"]
    assert "失败" in error_text or "failed" in error_text.lower()
    assert "LLM unavailable" in error_text
    assert payload["currentPhase"] == "failed"


def test_submit_session_message_surfaces_failed_result_error(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)

    class FailingResultAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": "",
                "raw_output": "",
                "error": "configuration_error: LiteLLM 未安装，无法执行模型调用；请安装 litellm",
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: FailingResultAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你现在是这个项目的agent，请告诉我目前的感受"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert not any(
        message.get("metadata", {}).get("kind") == "turn_error"
        for message in payload["messages"]
    )
    assert "LiteLLM 未安装" in payload["lastTurnError"]["message"]
    assert payload["currentPhase"] == "failed"


def test_submit_session_message_surfaces_provider_error_inside_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )

    provider_error = (
        'provider_protocol_error: litellm.BadGatewayError: BadGatewayError: OpenAIException - '
        '{"error":{"message":"Upstream request failed","type":"upstream_error"}}'
    )

    class ProviderFailingAgent:
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

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续当前对话"},
    )

    assert response.status_code == 202
    payload = response.json()
    # Non-tool failures are no longer persisted as journal messages (model context
    # stays clean); the visible error is carried by lastTurnError only.
    assert not any(
        message.get("metadata", {}).get("kind") == "turn_error"
        for message in payload["messages"]
    )
    assert any(message.get("content") == "继续当前对话" for message in payload["messages"])
    assert payload["lastTurnError"]["errorType"] == "provider_upstream_error"
    assert payload["lastTurnError"]["reasonCode"] == "upstream_unavailable"
    assert "provider 上游服务不可用或网关失败" in payload["lastTurnError"]["reasonSummary"]
    assert payload["lastTurnError"]["reasonDetail"] == "Upstream request failed"
    assert "模型服务上游暂时失败" in payload["lastTurnError"]["message"]
    assert "litellm.BadGatewayError" not in payload["lastTurnError"]["message"]
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["errorType"] == "provider_upstream_error"
    assert "litellm.BadGatewayError" in latest_run["error"]


def test_submit_session_message_surfaces_local_runtime_exception_as_turn_error(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )

    def raise_missing_key(*_args, **_kwargs):
        raise ValueError("未设置 API Key: VIBELUTION_LLM_MODEL_RELAY_GPT_5_6_LUNA_API_KEY")

    monkeypatch.setattr(session_service, "create_chat_agent", raise_missing_key)
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续当前对话"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert not any(
        message.get("metadata", {}).get("kind") == "turn_error"
        for message in payload["messages"]
    )
    assert payload["messages"][-1]["role"] == "user"
    assert payload["lastTurnError"]["errorType"] == "ValueError"
    assert payload["lastTurnError"]["recoverable"] is False
    assert "未设置 API Key" in payload["lastTurnError"]["message"]
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["errorType"] == "ValueError"
    assert "VIBELUTION_LLM_MODEL_RELAY_GPT_5_6_LUNA_API_KEY" in latest_run["error"]


def test_failed_runtime_turn_result_is_persisted_as_turn_error_with_trace(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    failed_result = {
        "status": "failed_runtime",
        "summary": "图像路由失败：当前模型不支持图片输入。",
        "raw_output": "图像路由失败：当前模型不支持图片输入。",
        "error": "图像路由失败：当前模型不支持图片输入。",
        "outcome": "blocked",
        "thought": "Need a vision-capable model before continuing.",
        "tool_trace": [{"name": "image2_generate_tool", "status": "failed", "summary": "unsupported"}],
        "feedback_events": [{"kind": "status", "name": "model_request", "status": "failed", "summary": "模型请求失败"}],
        "llm_failure": {
            "category": "protocol_error",
            "message": "模型响应未完成规范化：模型已返回，但响应适配器没有生成 canonical TurnOutcome。",
            "reason_code": "canonical_turn_outcome_missing",
            "reason_summary": "模型响应未完成规范化",
            "reason_detail": "模型已返回，但响应适配器没有生成 canonical TurnOutcome。",
            "chain_stage": "llm_response_normalization",
            "event_code": "llm.turn_outcome.missing",
            "retryable": False,
        },
    }

    scene_events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda area, category, event_code, **kwargs: scene_events.append(
            {"area": area, "category": category, "eventCode": event_code, **kwargs}
        ),
    )
    session_service._set_session_running("session-live", True, turn_id="turn-runtime-failure")
    session_service._set_session_live_output(
        "session-live",
        turn_id="turn-runtime-failure",
        llm_payload_trace={
            "traceId": "trace-runtime-1",
            "provider": "ai-pixel",
            "model": "gpt-5.6-terra",
            "selectedProtocol": "responses",
        },
    )
    try:
        session_service._persist_session_turn_result(
            "session-live",
            failed_result,
            turn_id="turn-runtime-failure",
        )
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-runtime-failure")
    payload = session_service.get_session_detail("session-live")

    assert not any(
        message.get("metadata", {}).get("kind") == "turn_error"
        for message in payload["messages"]
    )
    assert payload["lastTurnError"]["errorType"] == "runtime_error"
    assert payload["lastTurnError"]["reasonCode"] == "canonical_turn_outcome_missing"
    assert payload["lastTurnError"]["chainStage"] == "llm_response_normalization"
    assert payload["lastTurnError"]["eventCode"] == "llm.turn_outcome.missing"
    assert payload["lastTurnError"]["traceId"] == "trace-runtime-1"
    assert payload["lastTurnError"]["protocol"] == "responses"
    assert "模型响应未完成规范化" in payload["lastTurnError"]["reasonSummary"]
    assert "当前模型不支持图片输入" in payload["lastTurnError"]["message"]
    assert payload["currentPhase"] == "failed"
    turn_error_scene = next(item for item in scene_events if item["eventCode"] == "conversation.turn_error")
    assert turn_error_scene["fields"]["chainStage"] == "llm_response_normalization"
    assert turn_error_scene["fields"]["traceId"] == "trace-runtime-1"


def test_submit_session_message_surfaces_provider_http_diagnostics(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)

    provider_error = (
        "server_error: litellm.ServiceUnavailableError: AnthropicException - "
        "b'{\"error\":{\"message\":\"No available accounts: no available accounts\","
        "\"type\":\"api_error\"},\"type\":\"error\"}'."
    )

    class ProviderFailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": "server_error",
                "raw_output": "server_error",
                "error": "server_error",
                "llm_failure": {
                    "category": "server_error",
                    "message": provider_error,
                    "provider": "anthropic",
                    "model": "claude-opus-4-7",
                    "api_base": "https://www.atpify.cn",
                    "retryable": True,
                },
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续当前对话"},
    )

    assert response.status_code == 202
    payload = response.json()
    # Provider diagnostics now live on lastTurnError only (no error journal message).
    assert not any(
        message.get("metadata", {}).get("kind") == "turn_error"
        for message in payload["messages"]
    )
    assert payload["lastTurnError"]["httpStatus"] == 503
    assert payload["lastTurnError"]["provider"] == "anthropic"
    assert payload["lastTurnError"]["providerHost"] == "www.atpify.cn"
    assert payload["lastTurnError"]["providerErrorType"] == "api_error"
    assert payload["lastTurnError"]["providerErrorMessage"] == "No available accounts: no available accounts"
    assert payload["lastTurnError"]["model"] == "claude-opus-4-7"
    assert "No available accounts" in payload["lastTurnError"]["message"]


def test_submit_session_message_surfaces_prompt_cache_unsupported_inside_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)

    cache_error = (
        "prompt_cache_unsupported: 当前模型配置声明不支持 prompt cache；"
        "profile `primary` provider `relay` transport `responses` model `gpt-5.5`。"
    )

    class CacheUnsupportedAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": cache_error,
                "raw_output": cache_error,
                "error": cache_error,
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: CacheUnsupportedAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续当前对话"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert not any(
        message.get("metadata", {}).get("kind") == "turn_error"
        for message in payload["messages"]
    )
    assert "模型服务上游暂时失败" not in payload["lastTurnError"]["message"]
    assert payload["lastTurnError"]["errorType"] == "prompt_cache_unsupported"
    assert payload["lastTurnError"]["reasonCode"] == "prompt_cache_unsupported"
    assert "当前模型配置声明不支持 prompt cache" in payload["lastTurnError"]["message"]


def test_submit_session_message_surfaces_provider_quota_reason_inside_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)

    provider_error = (
        'provider_protocol_error: litellm.RateLimitError: AnthropicException - '
        'b\'{"error":{"message":"api key 7天限额已用完","type":"rate_limit_exceeded"},"type":"error"}\''
    )

    class ProviderFailingAgent:
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

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你好"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert not any(
        message.get("metadata", {}).get("kind") == "turn_error"
        for message in payload["messages"]
    )
    assert "API Key 额度或当日限额已用完" in payload["lastTurnError"]["message"]
    assert "api key 7天限额已用完" in payload["lastTurnError"]["message"]
    assert payload["lastTurnError"]["reasonCode"] == "quota_exhausted"
    assert payload["lastTurnError"]["reasonSummary"] == "API Key 额度或当日限额已用完"
    assert payload["lastTurnError"]["reasonDetail"] == "api key 7天限额已用完"


def test_submit_session_message_prefers_llm_failure_message_for_provider_detail(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)

    generic_error = "provider_protocol_error"
    detailed_error = (
        'provider_protocol_error: litellm.RateLimitError: AnthropicException - '
        'b\'{"error":{"message":"group requests-per-minute limit exceeded","type":"rate_limit_exceeded"},"type":"error"}\''
    )

    class CircuitBreakerFailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": generic_error,
                "raw_output": generic_error,
                "error": generic_error,
                "llm_failure": {
                    "category": "provider_protocol_error",
                    "message": detailed_error,
                    "retryable": False,
                },
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: CircuitBreakerFailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你好"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert not any(
        message.get("metadata", {}).get("kind") == "turn_error"
        for message in payload["messages"]
    )
    assert "provider 正在限流" in payload["lastTurnError"]["message"]
    assert "group requests-per-minute limit exceeded" in payload["lastTurnError"]["message"]
    assert payload["lastTurnError"]["reasonCode"] == "rate_limited"
    assert payload["lastTurnError"]["reasonDetail"] == "group requests-per-minute limit exceeded"


def test_submit_session_message_surfaces_deprecated_parameter_reason_inside_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)

    provider_error = "provider_protocol_error: invalid_request_error: `temperature` is deprecated for this model."

    class ProviderFailingAgent:
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

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你好"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert not any(
        message.get("metadata", {}).get("kind") == "turn_error"
        for message in payload["messages"]
    )
    assert "模型不接受当前采样参数，例如 temperature" in payload["lastTurnError"]["message"]
    assert "`temperature` is deprecated" in payload["lastTurnError"]["message"]
    assert payload["lastTurnError"]["reasonCode"] == "deprecated_sampling_parameter"
    assert payload["lastTurnError"]["reasonDetail"] == "`temperature` is deprecated for this model."


def test_submit_session_message_omits_mental_snapshot_when_disabled(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "is_mental_model_enabled", lambda: False)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续推进并给出下一步建议。",
                "raw_output": "继续推进并给出下一步建议。",
                "reasoning_content": "先保留思考，再让心智快照按开关退场。",
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "这部分应该被开关挡住。",
                    "whisper": "不要落盘。",
                    "cognitiveState": "productive",
                },
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复 web/src/routes/ChatCodingRoute.tsx"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert [item["text"] for item in _assistant_turn_items(payload["messages"][-1], "reasoning")] == [
        "先保留思考，再让心智快照按开关退场。"
    ]
    assert not _assistant_status_metadata(payload["messages"][-1], "mental_snapshot")


def test_submit_session_message_uses_per_turn_mental_model_override(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    monkeypatch.setattr(session_service, "is_mental_model_enabled", lambda: True)

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.override = None
            self.seeded_history = None
            created_agents.append(self)

        def set_mental_model_enabled_override(self, enabled):
            self.override = enabled

        def seed_chat_history(self, messages):
            self.seeded_history = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已按本轮开关处理。",
                "raw_output": "已按本轮开关处理。",
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "如果开关关闭，这里不应该落盘。",
                    "whisper": "per-turn",
                    "cognitiveState": "productive",
                },
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", DummyAgent)
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    disabled_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "这一轮不要打开心智模型", "mentalModelEnabled": False},
    )

    assert disabled_response.status_code == 202, disabled_response.json()
    disabled_payload = disabled_response.json()
    assert created_agents[-1].override is False
    assert not _assistant_status_metadata(disabled_payload["messages"][-1], "mental_snapshot")

    enabled_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "这一轮打开心智模型", "mentalModelEnabled": True},
    )

    assert enabled_response.status_code == 202, enabled_response.json()
    enabled_payload = enabled_response.json()
    assert created_agents[-1].override is True
    assert _assistant_status_metadata(enabled_payload["messages"][-1], "mental_snapshot")["mentalSnapshot"]["mood"] == "专注"


def test_turn_mental_snapshot_prefers_current_state_info_over_runtime_summary(monkeypatch):
    monkeypatch.setattr(session_service, "is_mental_model_enabled", lambda: True)
    monkeypatch.setattr(
        runtime_service,
        "_mental_state_summary",
        lambda lang: {
            "mood": "焦虑",
            "feeling": "旧的图片生成失败状态。",
            "whisper": "先检查 API 密钥。",
            "summary": "旧状态不应覆盖本轮。",
            "source": "state",
        },
    )
    monkeypatch.setattr(
        session_service,
        "_diagnosis_mental_snapshot",
        lambda lang, *, session_workspace=None: {
            "mood": "",
            "feeling": "",
            "whisper": "",
            "summary": "当前以规则诊断为主，认知态：稳定。",
            "cognitiveState": "normal",
            "confidence": 0.5,
            "sampleSize": 2,
            "interventionCount": 0,
            "source": "diagnosis",
        },
    )
    recorded_events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)),
    )

    snapshot = session_service._build_turn_mental_snapshot(
        {
            "state_info": {
                "mood": "专注",
                "feeling": "正在按用户最新要求配置默认头像。",
                "whisper": "使用 workspace/avatars 里的现有图片。",
            }
        },
        "zh",
        mental_model_enabled=True,
        session_id="session-live",
        turn_id="turn-current",
    )

    assert snapshot["mood"] == "专注"
    assert snapshot["feeling"] == "正在按用户最新要求配置默认头像。"
    assert snapshot["whisper"] == "使用 workspace/avatars 里的现有图片。"
    assert snapshot["source"] == "state"
    assert snapshot["cognitiveState"] == "normal"
    assert recorded_events
    assert recorded_events[-1][0] == (
        "conversation",
        "mental_snapshot",
        "conversation.mental_snapshot.selected",
    )
    assert recorded_events[-1][1]["fields"]["chosenSource"] == "state"
    assert recorded_events[-1][1]["fields"]["hasRuntimeSnapshot"] is True


def test_submit_session_message_includes_stream_friendly_tool_and_mental_payloads(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已完成三段式输出。",
                "raw_output": "最终回答内容。",
                "thought": "这是一段可见思考。",
                "reasoning_content": "这是一段可见思考。",
                "state_info": {
                    "mood": "专注",
                    "feeling": "心智模型已展开。",
                    "whisper": "工具调用继续保持单块。",
                },
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "心智模型已展开。",
                    "whisper": "工具调用继续保持单块。",
                    "cognitiveState": "productive",
                    "confidence": 0.91,
                    "sampleSize": 3,
                    "interventionCount": 1,
                    "updatedAt": "2026-05-18T12:01:00",
                    "source": "diagnosis",
                    "intervention": "继续保持当前路径。",
                    "metrics": {"sample_size": 3, "intervention_count": 1},
                    "historyTail": [
                        {"cognitiveState": "productive", "confidence": 0.91, "timestamp": "2026-05-18T12:01:00"},
                    ],
                },
                "tool_trace": [
                    {"name": "read_file_tool", "result_preview": "read ok", "status": "success"},
                    {"name": "run_test_for_tool", "result_preview": "tests passed", "status": "success"},
                ],
                "tool_call_count": 2,
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续把对话展示改成四段式", "mentalModelEnabled": True},
    )

    assert response.status_code == 202
    payload = response.json()
    assistant = payload["messages"][-1]
    assert _assistant_visible_text(assistant) == "最终回答内容。"
    assert [item["text"] for item in _assistant_turn_items(assistant, "reasoning")] == ["这是一段可见思考。"]
    mental_snapshot = _assistant_status_metadata(assistant, "mental_snapshot")["mentalSnapshot"]
    assert mental_snapshot["cognitiveState"] == "productive"
    assert mental_snapshot["intervention"] == "继续保持当前路径。"
    assert mental_snapshot["metrics"]["sample_size"] == 3
    assert _assistant_tool_summaries(assistant) == [
        {"name": "read_file_tool", "status": "completed"},
        {"name": "run_test_for_tool", "status": "completed"},
    ]
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_restores_prior_mental_snapshot_for_agent(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "updated_at": "2026-05-20T14:00:00",
                "last_turn_status": "ready",
                "messages": [
                    {
                        "role": "user",
                        "content": "你能感知到你的心智模型吗",
                        "timestamp": "2026-05-20T13:58:00",
                    },
                    {
                        "role": "assistant",
                        "content": "我对自己的心智模型能感知多少？",
                        "timestamp": "2026-05-20T13:59:00",
                        "mental_snapshot": {
                            "mood": "沉思",
                            "feeling": "正在延续心智模型话题。",
                            "whisper": "接住上一段回答。",
                            "sampleSize": 4,
                        },
                    },
                ],
            }
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _bind_live_session_agent(tmp_path)
    captured = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["history"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续补完心智模型回答。",
                "raw_output": "继续补完心智模型回答。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你话还没说完"},
    )

    assert response.status_code == 202
    assert captured["history"][1]["mental_snapshot"]["mood"] == "沉思"
    assert captured["history"][0]["content"] == "你能感知到你的心智模型吗"
