from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import queue
import threading

import pytest

from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    load_conversation_events,
)
from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.services import session_service
from core.web.services import agent_directory_service
from tests.helpers.web_chat_state import _seed_chat_state
from tests.session_catalog_fixtures import QUERY_SEARCH_FIELDS, build_session_query_summaries


def test_prompt_snapshot_hint_skips_chat_state_reload(monkeypatch):
    agent = {
        "agentId": "agent-primary",
        "primaryMode": "chat",
        "promptTemplateId": "prompt-chat-default",
    }
    snapshot = {
        "agentId": "agent-primary",
        "promptTemplateId": "prompt-chat-default",
        "builtinContentVersion": 4,
        "chatBasePromptVersion": 3,
        "corePromptSchemaVersion": 1,
        "corePrompts": [
            {"name": "COMMON"},
            {"name": "SOUL"},
            {"name": "AGENTS"},
        ],
        "content": "stable prompt",
        "contentHash": "prompt-v4",
    }
    recorded = []

    monkeypatch.setattr(
        session_service.prompt_template_service,
        "get_agent_prompt_snapshot_versions",
        lambda *_args, **_kwargs: {
            "builtinContentVersion": 4,
            "chatBasePromptVersion": 3,
            "corePromptSchemaVersion": 1,
        },
    )
    monkeypatch.setattr(
        session_service,
        "chat_state_transaction",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("chat state must not be reloaded")),
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_prompt_snapshot_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )

    result = session_service._ensure_session_agent_prompt_snapshot(
        "session-live",
        agent,
        snapshot_hint=snapshot,
    )

    assert result == snapshot
    assert result is not snapshot
    assert recorded[0][1]["outcome"] == "reused"


def test_session_agent_runtime_cache_reuses_transport_and_invalidates_on_prompt_change(tmp_path, monkeypatch):
    session_service._invalidate_session_agent_runtime_cache()
    created = []

    class RuntimeAgent:
        def __init__(self):
            self.reuse_preparations = 0

        def prepare_for_session_turn_reuse(self):
            self.reuse_preparations += 1

    def create_runtime(*_args, **_kwargs):
        runtime = RuntimeAgent()
        created.append(runtime)
        return runtime

    monkeypatch.setattr(session_service, "_create_chat_agent_for_session", create_runtime)
    resolved = SimpleNamespace(config={"provider": "local-test"}, model_id="model-primary")
    agent = {
        "agentId": "agent-primary",
        "updatedAt": "2026-07-16T10:00:00Z",
        "primaryMode": "chat",
        "promptTemplateId": "prompt-chat-default",
        "llmBindings": {"dialogue": {"modelId": "model-primary"}},
    }

    first, first_cache = session_service._acquire_chat_agent_for_session(
        "session-live",
        tmp_path,
        agent,
        resolved_llm=resolved,
        prompt_snapshot_hash="prompt-v1",
    )
    second, second_cache = session_service._acquire_chat_agent_for_session(
        "session-live",
        tmp_path,
        agent,
        resolved_llm=resolved,
        prompt_snapshot_hash="prompt-v1",
    )
    third, third_cache = session_service._acquire_chat_agent_for_session(
        "session-live",
        tmp_path,
        agent,
        resolved_llm=resolved,
        prompt_snapshot_hash="prompt-v2",
    )

    assert first_cache["status"] == "miss"
    assert second_cache["status"] == "hit"
    assert second is first
    assert first.reuse_preparations == 1
    assert third_cache["status"] == "miss"
    assert third is not first
    assert len(created) == 2
    session_service._invalidate_session_agent_runtime_cache()


def test_session_agent_runtime_cache_ignores_unrelated_app_config_domains(tmp_path, monkeypatch):
    session_service._invalidate_session_agent_runtime_cache()
    created = []

    def create_runtime(*_args, **_kwargs):
        runtime = object()
        created.append(runtime)
        return runtime

    monkeypatch.setattr(session_service, "_create_chat_agent_for_session", create_runtime)
    agent = {
        "agentId": "agent-primary",
        "updatedAt": "2026-07-16T10:00:00Z",
        "primaryMode": "chat",
        "promptTemplateId": "prompt-chat-default",
    }
    base_config = {
        "llm": {"profiles": {"primary": {"model": "model-primary"}}},
        "agent": {"name": "Agent"},
        "context_compression": {"enabled": True},
        "pet": {"mood": "calm"},
    }
    first, first_cache = session_service._acquire_chat_agent_for_session(
        "session-live",
        tmp_path,
        agent,
        resolved_llm=SimpleNamespace(config=base_config, model_id="model-primary"),
        prompt_snapshot_hash="prompt-v1",
    )
    unrelated_change, unrelated_cache = session_service._acquire_chat_agent_for_session(
        "session-live",
        tmp_path,
        agent,
        resolved_llm=SimpleNamespace(
            config={**base_config, "pet": {"mood": "excited"}},
            model_id="model-primary",
        ),
        prompt_snapshot_hash="prompt-v1",
    )
    llm_change, llm_cache = session_service._acquire_chat_agent_for_session(
        "session-live",
        tmp_path,
        agent,
        resolved_llm=SimpleNamespace(
            config={**base_config, "llm": {"profiles": {"primary": {"model": "model-next"}}}},
            model_id="model-primary",
        ),
        prompt_snapshot_hash="prompt-v1",
    )

    assert first_cache["status"] == "miss"
    assert unrelated_cache["status"] == "hit"
    assert unrelated_change is first
    assert llm_cache["status"] == "miss"
    assert llm_change is not first
    compression_change, compression_cache = session_service._acquire_chat_agent_for_session(
        "session-live",
        tmp_path,
        agent,
        resolved_llm=SimpleNamespace(
            config={**base_config, "context_compression": {"enabled": False}},
            model_id="model-primary",
        ),
        prompt_snapshot_hash="prompt-v1",
    )
    assert compression_cache["status"] == "miss"
    assert compression_change is not llm_change
    assert len(created) == 3
    session_service._invalidate_session_agent_runtime_cache()


def test_session_event_cache_coalesces_concurrent_misses(monkeypatch):
    session_id = "session-singleflight"
    loader_started = threading.Event()
    second_signature_computed = threading.Event()
    release_loader = threading.Event()
    signature_calls = 0
    load_calls = 0
    call_lock = threading.Lock()

    def signature(_session_id):
        nonlocal signature_calls
        with call_lock:
            signature_calls += 1
            if signature_calls >= 2:
                second_signature_computed.set()
        return ("ledger.jsonl", 1, 1, 1)

    def load_events(_project_root, _session_id):
        nonlocal load_calls
        with call_lock:
            load_calls += 1
        loader_started.set()
        assert release_loader.wait(timeout=5)
        return ["event-1"]

    monkeypatch.setattr(session_service, "_session_conversation_events_signature", signature)
    monkeypatch.setattr(session_service, "load_conversation_events", load_events)
    session_service._invalidate_session_conversation_events_cache(session_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(session_service._load_session_conversation_events_cached, session_id)
        assert loader_started.wait(timeout=5)
        second = executor.submit(session_service._load_session_conversation_events_cached, session_id)
        assert second_signature_computed.wait(timeout=5)
        release_loader.set()

        assert first.result(timeout=5) == ["event-1"]
        assert second.result(timeout=5) == ["event-1"]

    assert load_calls == 1
    session_service._invalidate_session_conversation_events_cache(session_id)


def test_active_session_summary_normalizes_only_the_active_conversation(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-active",
            "updated_at": "2026-07-14T15:40:00",
            "conversations": [
                {"conversation_id": "session-inactive", "title": "旧会话"},
                {"conversation_id": "session-active", "title": "当前会话"},
            ],
        },
    )
    normalized_ids: list[str] = []

    def normalize_target(raw, **_kwargs):
        conversation_id = str(raw.get("conversation_id") or "")
        normalized_ids.append(conversation_id)
        return {"id": conversation_id, "messages": []}

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_agent_lookup_for_conversations", lambda: {})
    monkeypatch.setattr(session_service, "_agent_directory_stub_hidden_team_member_ids", lambda: set())
    monkeypatch.setattr(session_service, "_normalize_conversation", normalize_target)
    monkeypatch.setattr(
        session_service,
        "_with_direct_session_agent_for_summary",
        lambda conversation, *, agent_by_id: conversation,
    )
    monkeypatch.setattr(
        session_service,
        "_build_session_summary",
        lambda conversation, *, hydrate_agent: {"id": conversation["id"]},
    )

    summary = session_service.get_active_session_summary()

    assert summary == {"id": "session-active"}
    assert normalized_ids == ["session-active"]


def test_delete_session_restores_direct_agent_binding_when_chat_save_fails(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="删除回滚 Agent",
        primary_mode="chat",
        role_key="chat-default",
        prompt_template_id="prompt-chat-default",
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_id"] = agent["agentId"]
    state["conversations"][0]["agentId"] = agent["agentId"]
    save_chat_state(tmp_path, state)

    def fail_chat_save(*_args, **_kwargs):
        raise OSError("simulated chat persistence failure")

    monkeypatch.setattr(session_service, "save_chat_state", fail_chat_save)

    try:
        session_service.delete_chat_session_lightweight("session-live")
    except OSError as exc:
        assert "simulated chat persistence failure" in str(exc)
    else:
        raise AssertionError("delete must surface the chat persistence failure")

    restored_agent = agent_directory_service.get_agent(agent["agentId"], include_archived=True)
    assert restored_agent is not None
    assert restored_agent["directSessionId"] == "session-live"
    persisted_state = load_chat_state(tmp_path)
    assert {item["conversation_id"] for item in persisted_state["conversations"]} == {"session-live"}


def test_session_stream_coalescing_preserves_assistant_delta_events():
    subscriber = queue.Queue()
    subscriber.put_nowait({"type": "assistant_delta", "contentDelta": "你"})
    subscriber.put_nowait({"type": "assistant_delta", "contentDelta": "好"})

    dropped = session_service._coalesce_session_stream_queue(subscriber, event_type="assistant_delta")

    assert dropped == 0
    assert subscriber.get_nowait()["contentDelta"] == "你"
    assert subscriber.get_nowait()["contentDelta"] == "好"
    assert session_service._SESSION_STREAM_COALESCED_EVENT_TYPES == {"session_detail"}


def test_session_assistant_delta_queue_coalesces_pending_same_turn_deltas():
    subscriber = queue.Queue(maxsize=4)
    subscriber.put_nowait(
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-1",
            "contentDelta": "你",
            "thoughtDelta": "",
            "replaceContent": False,
            "replaceThought": False,
        },
    )
    subscriber.put_nowait({"type": "session_detail", "ledgerSeq": 1})

    merged, dropped = session_service._coalesce_session_assistant_delta_queue(
        subscriber,
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-1",
            "contentDelta": "好",
            "thoughtDelta": "思考",
            "replaceContent": False,
            "replaceThought": False,
        },
    )

    assert dropped == 1
    assert merged["contentDelta"] == "你好"
    assert merged["thoughtDelta"] == "思考"
    assert merged["replaceContent"] is False
    assert merged["replaceThought"] is False
    assert "feedbackEvents" not in merged
    assert subscriber.get_nowait()["type"] == "session_detail"


def test_session_assistant_delta_queue_merges_feedback_events_for_same_turn_deltas():
    subscriber = queue.Queue(maxsize=4)
    subscriber.put_nowait(
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-1",
            "contentDelta": "准备",
            "thoughtDelta": "",
            "replaceContent": False,
            "replaceThought": False,
            "feedbackEvents": [
                {
                    "sequence": 1,
                    "kind": "status",
                    "status": "running",
                    "name": "context_prepare",
                    "summary": "正在准备上下文",
                }
            ],
        },
    )

    merged, dropped = session_service._coalesce_session_assistant_delta_queue(
        subscriber,
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-1",
            "contentDelta": "请求模型",
            "thoughtDelta": "",
            "replaceContent": False,
            "replaceThought": False,
            "feedbackEvents": [
                {
                    "sequence": 2,
                    "kind": "status",
                    "status": "running",
                    "name": "model_request",
                    "summary": "正在请求模型",
                }
            ],
        },
    )

    assert dropped == 1
    assert merged["contentDelta"] == "准备请求模型"
    assert [event["name"] for event in merged["feedbackEvents"]] == [
        "context_prepare",
        "model_request",
    ]


def test_session_assistant_delta_queue_updates_unsequenced_feedback_event():
    subscriber = queue.Queue(maxsize=4)
    subscriber.put_nowait(
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-1",
            "contentDelta": "",
            "thoughtDelta": "",
            "replaceContent": False,
            "replaceThought": False,
            "feedbackEvents": [
                {
                    "sequence": 0,
                    "kind": "tool",
                    "status": "running",
                    "name": "source_collection_context_tool",
                    "summary": "正在读取受控资料上下文",
                }
            ],
        },
    )

    merged, dropped = session_service._coalesce_session_assistant_delta_queue(
        subscriber,
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-1",
            "contentDelta": "",
            "thoughtDelta": "",
            "replaceContent": False,
            "replaceThought": False,
            "feedbackEvents": [
                {
                    "sequence": 0,
                    "kind": "tool",
                    "status": "done",
                    "name": "source_collection_context_tool",
                    "summary": "上下文已读取",
                    "resultPreview": "candidatePage.returned=19",
                }
            ],
        },
    )

    assert dropped == 1
    assert merged["feedbackEvents"] == [
        {
            "sequence": 0,
            "kind": "tool",
            "status": "done",
            "name": "source_collection_context_tool",
            "summary": "上下文已读取",
            "resultPreview": "candidatePage.returned=19",
        }
    ]


def test_session_assistant_delta_feedback_merge_keeps_parallel_same_name_tool_calls():
    merged = session_service._merge_session_assistant_delta_feedback_events(
        [
            {
                "sequence": 0,
                "kind": "tool",
                "status": "running",
                "name": "read_file_tool",
                "callId": "call-a",
            }
        ],
        [
            {
                "sequence": 0,
                "kind": "tool",
                "status": "running",
                "name": "read_file_tool",
                "callId": "call-b",
            }
        ],
    )

    assert [event["callId"] for event in merged] == ["call-a", "call-b"]


def test_session_turn_capture_correlates_parallel_same_name_tools_by_call_id():
    capture = session_service.SessionTurnCapture(session_id="session-parallel", turn_id="turn-parallel")

    capture.note_tool_event("read_file_tool", "running", "读取 A", call_id="call-a")
    capture.note_tool_event("read_file_tool", "running", "读取 B", call_id="call-b")
    capture.note_tool_event("read_file_tool", "done", "A 完成", call_id="call-a", result="A")

    tool_calls = {item["callId"]: item for item in capture.tool_calls}
    feedback_events = {item["callId"]: item for item in capture.feedback_events if item.get("kind") == "tool"}
    assert tool_calls["call-a"]["status"] == "done"
    assert tool_calls["call-b"]["status"] == "running"
    assert feedback_events["call-a"]["status"] == "done"
    assert feedback_events["call-b"]["status"] == "running"


def test_committed_assistant_segment_is_published_in_live_feedback_order(monkeypatch):
    capture = session_service.SessionTurnCapture(session_id="session-timeline", turn_id="turn-timeline")
    capture.content = "我先检查工作区。"
    ledger_events = []
    live_updates = []
    monkeypatch.setattr(
        session_service,
        "_append_session_conversation_event",
        lambda *args, **kwargs: ledger_events.append((args, kwargs)),
    )
    monkeypatch.setattr(
        session_service,
        "_set_session_live_output",
        lambda *args, **kwargs: live_updates.append((args, kwargs)),
    )

    session_service._commit_session_capture_assistant_segment(
        "session-timeline",
        capture,
        boundary="tool_event",
    )
    capture.note_tool_event("get_git_status_summary_tool", "running", "检查 Git 状态", call_id="call-git")

    assert [(event["kind"], event["sequence"]) for event in capture.feedback_events] == [
        ("assistant_text", 1),
        ("tool", 2),
    ]
    assert capture.feedback_events[0]["content"] == "我先检查工作区。"
    assert ledger_events[0][1]["payload"]["feedbackSequence"] == 1
    assert live_updates[0][1]["feedback_events"][0]["kind"] == "assistant_text"
    checkpoint = session_service._live_output_checkpoint_payload(
        session_service.SessionLiveOutputState(
            session_id="session-timeline",
            turn_id="turn-timeline",
            content=capture.content,
            tool_calls=capture.tool_calls,
            feedback_events=capture.feedback_events,
        )
    )
    assert [item["kind"] for item in checkpoint["timelineItems"]] == ["assistant_text", "operation"]
    assert [item.get("text") for item in checkpoint["timelineItems"] if item["kind"] == "assistant_text"] == [
        "我先检查工作区。"
    ]


def test_session_turn_capture_records_parallel_same_name_tools_with_unique_sequences():
    capture = session_service.SessionTurnCapture(session_id="session-parallel", turn_id="turn-parallel")
    worker_barrier = threading.Barrier(2)

    def record_tool(call_id: str) -> None:
        worker_barrier.wait(timeout=5)
        capture.note_tool_event("read_file_tool", "running", f"读取 {call_id}", call_id=call_id)
        capture.note_tool_event(
            "read_file_tool",
            "done",
            f"{call_id} 完成",
            call_id=call_id,
            result=call_id,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(record_tool, call_id) for call_id in ("call-a", "call-b")]
        for future in futures:
            future.result(timeout=5)

    tool_calls = {item["callId"]: item for item in capture.tool_calls}
    feedback_events = [item for item in capture.feedback_events if item.get("kind") == "tool"]
    assert set(tool_calls) == {"call-a", "call-b"}
    assert {item["status"] for item in tool_calls.values()} == {"done"}
    assert {item["callId"] for item in feedback_events} == {"call-a", "call-b"}
    assert {item["status"] for item in feedback_events} == {"done"}
    assert len({item["sequence"] for item in feedback_events}) == 2


def test_session_turn_capture_summarizes_repeated_tool_loop_progress():
    capture = session_service.SessionTurnCapture(session_id="session-loop", turn_id="turn-loop")

    for index in range(3):
        capture.note_tool_event(
            "web_fetch_tool",
            "running",
            f"正在抓取第 {index + 1} 个来源",
            arguments={"url": f"https://example.test/paper-{index}"},
        )
        capture.note_tool_event(
            "web_fetch_tool",
            "failed",
            f"[错误] HTTP 403: https://example.test/paper-{index}",
            error=f"[错误] HTTP 403: https://example.test/paper-{index}",
        )

    progress_events = [
        event
        for event in capture.feedback_events
        if event.get("kind") == "status" and event.get("name") == "long_loop_progress"
    ]

    assert len(progress_events) == 1
    assert progress_events[0]["status"] == "running"
    assert "第 3 次工具调用" in progress_events[0]["summary"]
    assert "web_fetch_tool" in progress_events[0]["summary"]
    assert "HTTP 403" in progress_events[0]["summary"]
    assert "尚未形成最终回答" in progress_events[0]["resultPreview"]


def test_session_live_output_publishes_long_loop_progress_as_status_only_delta(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    monkeypatch.setattr(session_service, "_write_session_live_output_checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_delete_session_live_output_checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_session_ledger_sequence", lambda _session_id: 7)
    subscriber = queue.Queue()
    capture = session_service.SessionTurnCapture(session_id="session-loop", turn_id="turn-loop")
    for index in range(3):
        capture.note_tool_event("web_fetch_tool", "running", f"抓取来源 {index + 1}")
        capture.note_tool_event(
            "web_fetch_tool",
            "failed",
            f"[错误] HTTP 403: https://example.test/paper-{index}",
            error=f"[错误] HTTP 403: https://example.test/paper-{index}",
        )

    session_service._register_session_stream_subscriber("session-loop", subscriber)
    try:
        session_service._set_session_live_output(
            "session-loop",
            turn_id="turn-loop",
            tool_calls=capture.tool_calls,
            feedback_events=capture.feedback_events,
        )
    finally:
        session_service._unregister_session_stream_subscriber("session-loop", subscriber)
        with session_service._SESSION_LIVE_OUTPUTS_LOCK:
            session_service._SESSION_LIVE_OUTPUTS.pop("session-loop", None)

    event = subscriber.get_nowait()
    progress = [
        item
        for item in event["feedbackEvents"]
        if item.get("kind") == "status" and item.get("name") == "long_loop_progress"
    ]

    assert event["type"] == "assistant_delta"
    assert event["sessionId"] == "session-loop"
    assert event["turnId"] == "turn-loop"
    assert event["ledgerSeq"] == 7
    assert event["content"] == ""
    assert event["contentDelta"] == ""
    assert progress
    assert "第 3 次工具调用" in progress[0]["summary"]


def test_completed_visible_reply_with_tool_trace_is_terminal():
    result = {
        "status": "completed",
        "summary": "你好！我是 Vibelution agent，目前工作区状态正常。有什么可以帮你的吗？",
        "raw_output": "你好！我是 Vibelution agent，目前工作区状态正常。有什么可以帮你的吗？",
        "tool_call_count": 1,
        "tool_trace": [
            {
                "name": "get_git_status_summary_tool",
                "status": "done",
                "summary": "工作区干净",
            }
        ],
    }

    assert session_service._chat_turn_result_status("completed", result, stop_requested=False) == "completed"


def test_needs_continue_feedback_finalization_does_not_mark_thought_failed():
    result = {
        "feedback_events": [
            {"sequence": 1, "kind": "status", "status": "running", "name": "context_prepare", "summary": "准备上下文。"},
            {"sequence": 2, "kind": "tool", "status": "done", "name": "get_git_status_summary_tool", "summary": "工作区干净。"},
            {"sequence": 3, "kind": "thought", "status": "running", "summary": "现在可以回应用户。"},
        ],
    }

    feedback_events = session_service._extract_chat_feedback_events(result, final_status="needs_continue")

    assert [item["status"] for item in feedback_events] == ["done", "done", "done"]


def test_session_turn_progress_live_output_closes_previous_statuses(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)

    session_service._set_session_running("session-live", True, turn_id="turn-progress")
    try:
        session_service._set_session_turn_progress_live_output("session-live", "context_prepare", turn_id="turn-progress")
        session_service._set_session_turn_progress_live_output("session-live", "agent_prepare", turn_id="turn-progress")
        session_service._set_session_turn_progress_live_output("session-live", "model_request", turn_id="turn-progress")

        live_state = session_service._snapshot_session_live_output("session-live")
    finally:
        session_service._clear_session_live_output("session-live", turn_id="turn-progress")
        session_service._set_session_running("session-live", False, turn_id="turn-progress")

    assert live_state is not None
    progress_events = [event for event in live_state.feedback_events if event["kind"] == "status"]
    assert [event["name"] for event in progress_events] == [
        "context_prepare",
        "agent_prepare",
        "model_request",
    ]
    assert [event["status"] for event in progress_events] == ["done", "done", "running"]


def test_session_turn_progress_live_output_does_not_block_on_durable_work_run(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)

    durable_updates = []
    monkeypatch.setattr(
        session_service,
        "_touch_chat_turn_work_run",
        lambda **kwargs: durable_updates.append(kwargs),
    )

    session_service._set_session_running("session-live", True, turn_id="turn-progress")
    try:
        session_service._set_session_turn_progress_live_output(
            "session-live",
            "context_prepare",
            turn_id="turn-progress",
        )
        live_state = session_service._snapshot_session_live_output("session-live")
    finally:
        session_service._clear_session_live_output("session-live", turn_id="turn-progress")
        session_service._set_session_running("session-live", False, turn_id="turn-progress")

    assert live_state is not None
    assert live_state.stage == "context_prepare"
    assert durable_updates == []


def test_session_llm_retry_status_still_updates_durable_work_run(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)

    durable_updates = []
    monkeypatch.setattr(
        session_service,
        "_touch_chat_turn_work_run",
        lambda **kwargs: durable_updates.append(kwargs),
    )

    session_service._set_session_running("session-live", True, turn_id="turn-retry")
    try:
        session_service._set_session_llm_status_live_output(
            "session-live",
            "retrying",
            turn_id="turn-retry",
            fields={"attempt": 1, "max_attempts": 2, "category": "timeout"},
        )
    finally:
        session_service._clear_session_live_output("session-live", turn_id="turn-retry")
        session_service._set_session_running("session-live", False, turn_id="turn-retry")

    assert len(durable_updates) == 1
    assert durable_updates[0]["stage"] == "model_retry"
    assert durable_updates[0]["turn_id"] == "turn-retry"


def test_session_llm_retry_recovery_replaces_running_retry_status(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    monkeypatch.setattr(session_service, "_touch_chat_turn_work_run", lambda **_kwargs: None)

    session_service._set_session_running("session-live", True, turn_id="turn-retry")
    try:
        session_service._set_session_llm_status_live_output(
            "session-live",
            "retrying",
            turn_id="turn-retry",
            fields={"attempt": 1, "max_attempts": 2, "category": "server_error"},
        )
        session_service._set_session_live_output(
            "session-live",
            turn_id="turn-retry",
            stage="assistant_response",
            content="recovered answer",
        )
        session_service._set_session_llm_status_live_output(
            "session-live",
            "retry_recovered",
            turn_id="turn-retry",
            fields={"attempt": 2, "max_attempts": 2, "category": "server_error"},
        )
        recovered = session_service._snapshot_session_live_output("session-live")
    finally:
        session_service._clear_session_live_output("session-live", turn_id="turn-retry")
        session_service._set_session_running("session-live", False, turn_id="turn-retry")

    assert recovered is not None
    assert len(recovered.feedback_events) == 1
    assert recovered.feedback_events[0]["name"] == "model_retry"
    assert recovered.feedback_events[0]["status"] == "recovered"
    assert "error" not in recovered.feedback_events[0]
    assert recovered.content == "recovered answer"


def test_session_llm_transport_status_updates_one_visible_recovery_event(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    monkeypatch.setattr(session_service, "_touch_chat_turn_work_run", lambda **_kwargs: None)

    session_service._set_session_running("session-live", True, turn_id="turn-transport")
    try:
        session_service._set_session_llm_status_live_output(
            "session-live",
            "transport_fallback",
            turn_id="turn-transport",
            fields={
                "category": "provider_transport_unavailable",
                "closeCode": 1013,
                "closeReason": "no available account",
                "fallbackTransport": "http",
            },
        )
        degraded = session_service._snapshot_session_live_output("session-live")
        assert degraded is not None
        degraded_event = dict(degraded.feedback_events[0])
        session_service._set_session_llm_status_live_output(
            "session-live",
            "transport_recovered",
            turn_id="turn-transport",
            fields={"fallbackTransport": "http"},
        )
        recovered = session_service._snapshot_session_live_output("session-live")
    finally:
        session_service._clear_session_live_output("session-live", turn_id="turn-transport")
        session_service._set_session_running("session-live", False, turn_id="turn-transport")

    assert degraded_event["name"] == "model_transport"
    assert degraded_event["status"] == "degraded"
    assert degraded_event["error"] == "no available account"
    assert "no available account" not in degraded_event["summary"]
    assert "no available account" not in degraded_event["resultPreview"]
    assert recovered is not None
    assert len(recovered.feedback_events) == 1
    assert recovered.feedback_events[0]["status"] == "recovered"
    assert "error" not in recovered.feedback_events[0]
    assert "连接已恢复" in recovered.feedback_events[0]["summary"]


def test_session_turn_prepare_timing_log_fields_are_bounded_and_non_sensitive():
    fields = session_service._session_turn_prepare_timing_log_fields(
        {
            "totalPrepareMs": 9123,
            "sessionWorkspaceMs": 17,
            "agentDirectorySyncMs": 23,
            "agentLookupMs": 31,
            "promptSnapshotMs": 47,
            "lightweightChatDecisionMs": 53,
            "agentContextBuildMs": 61,
            "workspacePolicyMs": 71,
            "llmKeyEnvSyncMs": 83,
            "agentLlmResolveMs": 97,
            "llmKeyEnvSyncedCount": 1,
            "llmKeyEnvAlreadyPresentCount": 2,
            "llmKeyEnvMissingCount": 3,
            "syncedEnvNames": ["DO_NOT_LOG"],
            "unrelated": "not part of the bounded timing event",
        }
    )

    assert fields == {
        "totalPrepareMs": 9123,
        "sessionWorkspaceMs": 17,
        "agentDirectorySyncMs": 23,
        "agentLookupMs": 31,
        "promptSnapshotMs": 47,
        "lightweightChatDecisionMs": 53,
        "agentContextBuildMs": 61,
        "workspacePolicyMs": 71,
        "llmKeyEnvSyncMs": 83,
        "agentLlmResolveMs": 97,
        "llmKeyEnvSyncedCount": 1,
        "llmKeyEnvAlreadyPresentCount": 2,
        "llmKeyEnvMissingCount": 3,
    }


def test_running_snapshot_throttle_skips_detail_hydration(monkeypatch):
    subscriber = queue.Queue()
    session_id = "session-throttled"

    def unexpected_detail_hydration(*_args, **_kwargs):
        raise AssertionError("throttled snapshot must not hydrate session detail")

    session_service._register_session_stream_subscriber(session_id, subscriber)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)
    monkeypatch.setattr(session_service, "get_session_detail", unexpected_detail_hydration)
    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        session_service._SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = session_service._perf_counter()
    try:
        session_service._publish_session_detail_snapshot(session_id)
    finally:
        session_service._unregister_session_stream_subscriber(session_id, subscriber)
        with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            session_service._SESSION_STREAM_LAST_SNAPSHOT_AT.pop(session_id, None)
            session_service._SESSION_STREAM_THROTTLED_COUNTS.pop(session_id, None)

    assert subscriber.empty()


def test_session_live_progress_and_tool_updates_do_not_publish_full_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    snapshot_calls = []
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda session_id: snapshot_calls.append(session_id),
    )
    monkeypatch.setattr(session_service, "_write_session_live_output_checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_delete_session_live_output_checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_session_ledger_sequence", lambda _session_id: 11)
    subscriber = queue.Queue()
    session_id = "session-delta-only"
    turn_id = "turn-delta-only"
    session_service._set_session_running(session_id, True, turn_id=turn_id)
    session_service._register_session_stream_subscriber(session_id, subscriber)
    try:
        session_service._set_session_turn_progress_live_output(session_id, "model_request", turn_id=turn_id)
        session_service._set_session_live_output(
            session_id,
            turn_id=turn_id,
            tool_calls=[{"id": "tool-1", "name": "git_status", "status": "running"}],
        )
    finally:
        session_service._unregister_session_stream_subscriber(session_id, subscriber)
        session_service._clear_session_live_output(session_id, turn_id=turn_id)
        session_service._set_session_running(session_id, False, turn_id=turn_id)

    events = []
    while not subscriber.empty():
        events.append(subscriber.get_nowait())
    assert snapshot_calls == []
    assert len(events) == 1
    assert all(event["type"] == "assistant_delta" for event in events)
    assert events[-1]["turnId"] == turn_id
    assert events[-1]["ledgerSeq"] == 11


def test_session_diagnostics_do_not_block_on_full_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    snapshot_calls = []
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda session_id: snapshot_calls.append(session_id),
    )
    monkeypatch.setattr(session_service, "_write_session_live_output_checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_delete_session_live_output_checkpoint", lambda *_args, **_kwargs: None)
    session_id = "session-payload-trace-fastpath"
    turn_id = "turn-payload-trace-fastpath"
    session_service._set_session_running(session_id, True, turn_id=turn_id)
    try:
        session_service._set_session_live_context_composition(
            session_id,
            {
                "turnId": turn_id,
                "recordedAt": "2026-07-17T09:27:03",
                "source": "runtime_assembly",
                "segments": [
                    {
                        "key": "current_user",
                        "label": "current user",
                        "chars": 10,
                        "tokens": 5,
                        "itemCount": 1,
                    }
                ],
            },
            turn_id=turn_id,
        )
        session_service._set_session_llm_payload_trace_live_output(
            session_id,
            {
                "schemaVersion": 1,
                "traceId": "trace-fastpath",
                "sessionId": session_id,
                "turnId": turn_id,
                "provider": "test-provider",
                "model": "test-model",
            },
            turn_id=turn_id,
        )

        composition = session_service._current_session_live_context_composition(session_id)
        trace = session_service._current_session_live_llm_payload_trace(session_id)
    finally:
        session_service._clear_session_live_output(session_id, turn_id=turn_id)
        session_service._set_session_running(session_id, False, turn_id=turn_id)

    assert snapshot_calls == []
    assert composition is not None
    assert composition["turnId"] == turn_id
    assert trace is not None
    assert trace["traceId"] == "trace-fastpath"
    assert trace["turnId"] == turn_id


def test_interrupted_snapshot_finalizes_running_feedback_events(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-07-08T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "last_turn_status": "running",
                    "updated_at": "2026-07-08T12:00:00",
                }
            ],
        },
    )
    append_conversation_event(tmp_path, "session-live", "turn-stop", EVENT_TURN_STARTED, status="running")
    session_service._set_session_running("session-live", True, turn_id="turn-stop")
    try:
        session_service._set_session_live_output(
            "session-live",
            turn_id="turn-stop",
            content="模型连接正在重试...\n第 3/5 次；原因：server_error。",
            feedback_events=[
                {"sequence": 1, "kind": "status", "status": "running", "name": "context_prepare", "summary": "准备上下文"},
                {"sequence": 2, "kind": "status", "status": "running", "name": "agent_prepare", "summary": "唤起 agent"},
                {"sequence": 3, "kind": "status", "status": "running", "name": "retrying", "summary": "正在重试"},
            ],
        )

        session_service._persist_session_interrupted_snapshot(
            "session-live",
            {
                "turnId": "turn-stop",
                "stopReason": "操作者请求停止当前轮。",
                "stopRequestedAt": "2026-07-08T12:06:49",
            },
            lang="zh",
        )
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-stop")
        session_service._clear_session_live_output("session-live", turn_id="turn-stop")

    events = load_conversation_events(tmp_path, "session-live")
    assistant_event = next(event for event in events if event.event_type == EVENT_ASSISTANT_MESSAGE)
    assert assistant_event.status == "stopped"
    assert [event["status"] for event in assistant_event.payload["feedbackEvents"]] == [
        "done",
        "done",
        "done",
    ]


def test_reconcile_discards_live_checkpoint_for_already_interrupted_turn(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-07-08T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "last_turn_status": "ready",
                    "updated_at": "2026-07-08T12:00:00",
                }
            ],
        },
    )
    session_service._set_session_running("session-live", True, turn_id="turn-terminal")
    try:
        session_service._set_session_live_output(
            "session-live",
            turn_id="turn-terminal",
            content="模型连接正在重试...",
            feedback_events=[
                {"sequence": 1, "kind": "status", "status": "running", "name": "context_prepare", "summary": "准备上下文"},
                {"sequence": 2, "kind": "status", "status": "running", "name": "retrying", "summary": "正在重试"},
            ],
        )
    finally:
        with session_service._SESSION_LIVE_OUTPUTS_LOCK:
            session_service._SESSION_LIVE_OUTPUTS.pop("session-live", None)
        session_service._set_session_running("session-live", False, turn_id="turn-terminal")

    append_conversation_event(tmp_path, "session-live", "turn-terminal", EVENT_TURN_STARTED, status="running")
    append_conversation_event(tmp_path, "session-live", "turn-terminal", EVENT_TURN_INTERRUPTED, status="stopped")
    checkpoint_path = session_service._session_live_output_checkpoint_path("session-live")
    assert checkpoint_path.exists()

    session_service._reconcile_stale_session_ledger("session-live", reason="detail_loaded_after_restart")

    assert not checkpoint_path.exists()
    assert [event.event_type for event in load_conversation_events(tmp_path, "session-live")] == [
        EVENT_TURN_STARTED,
        EVENT_TURN_INTERRUPTED,
    ]


def test_reconcile_preserves_open_ledger_for_durable_active_work_run(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_active_chat_turn_work_run_for_session",
        lambda session_id: {
            "runId": "turn-active",
            "sessionId": session_id,
            "status": "running",
        },
    )
    append_conversation_event(tmp_path, "session-live", "turn-active", EVENT_TURN_STARTED, status="running")

    session_service._reconcile_stale_session_ledger(
        "session-live",
        reason="detail_loaded_after_restart",
    )

    assert [event.event_type for event in load_conversation_events(tmp_path, "session-live")] == [
        EVENT_TURN_STARTED,
    ]


def test_reconcile_does_not_interrupt_turn_activated_during_ledger_read(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_active_chat_turn_work_run_for_session", lambda _session_id: None)
    append_conversation_event(tmp_path, "session-live", "turn-new", EVENT_TURN_STARTED, status="running")

    ledger_read = threading.Event()
    allow_reconcile = threading.Event()
    original_latest_open_turn_id = session_service.latest_open_turn_id

    def delayed_latest_open_turn_id(events):
        ledger_read.set()
        assert allow_reconcile.wait(2.0)
        return original_latest_open_turn_id(events)

    monkeypatch.setattr(session_service, "latest_open_turn_id", delayed_latest_open_turn_id)
    reconcile = threading.Thread(
        target=session_service._reconcile_stale_session_ledger,
        args=("session-live",),
        kwargs={"reason": "detail_loaded_after_restart"},
    )
    reconcile.start()
    assert ledger_read.wait(2.0)
    session_service._set_session_running("session-live", True, turn_id="turn-new")
    allow_reconcile.set()
    reconcile.join(timeout=2.0)

    try:
        assert not reconcile.is_alive()
        assert [event.event_type for event in load_conversation_events(tmp_path, "session-live")] == [
            EVENT_TURN_STARTED,
        ]
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-new")


def test_terminal_fallback_closes_running_turn_when_result_persistence_raises(monkeypatch, tmp_path):
    class FakeWorkRunStore:
        def __init__(self):
            self.snapshots = {}

        def load_snapshot(self, run_kind, run_id):
            return self.snapshots.get((run_kind, run_id))

        def persist_snapshot(self, run_kind, payload, *, active_run_id=None):
            self.snapshots[(run_kind, payload["runId"])] = dict(payload)

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    work_runs = FakeWorkRunStore()
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", work_runs)
    monkeypatch.setattr(
        session_service,
        "_persist_session_turn_result",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("result persistence failed")),
    )
    append_conversation_event(tmp_path, "session-live", "turn-fallback", EVENT_TURN_STARTED, status="running")
    session_service._set_session_running("session-live", True, turn_id="turn-fallback")
    session_service._set_session_live_output("session-live", turn_id="turn-fallback", content="partial")

    try:
        session_service._persist_session_turn_result("session-live", {}, turn_id="turn-fallback")
    except RuntimeError:
        session_service._ensure_session_turn_terminal_fallback("session-live", "turn-fallback")
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-fallback")

    session_service._ensure_session_turn_terminal_fallback("session-live", "turn-fallback")

    events = load_conversation_events(tmp_path, "session-live")
    terminal_events = [event for event in events if event.event_type == EVENT_TURN_FAILED]
    assert len(terminal_events) == 1
    assert "session-live" not in session_service._RUNNING_SESSION_IDS
    assert session_service._snapshot_session_live_output("session-live") is None
    work_run = work_runs.load_snapshot("chat_turn", "turn-fallback")
    assert work_run["status"] == "failed"
    assert work_run["finishedAt"]


def test_terminal_fallback_preserves_completed_turn_work_run(monkeypatch, tmp_path):
    class FakeWorkRunStore:
        def __init__(self):
            self.snapshots = {}

        def load_snapshot(self, run_kind, run_id):
            return self.snapshots.get((run_kind, run_id))

        def persist_snapshot(self, run_kind, payload, *, active_run_id=None):
            self.snapshots[(run_kind, payload["runId"])] = dict(payload)

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    work_runs = FakeWorkRunStore()
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", work_runs)
    append_conversation_event(tmp_path, "session-live", "turn-completed", EVENT_TURN_STARTED, status="running")
    append_conversation_event(tmp_path, "session-live", "turn-completed", EVENT_TURN_COMPLETED, status="completed")
    work_runs.persist_snapshot(
        "chat_turn",
        {
            "runId": "turn-completed",
            "sessionId": "session-live",
            "status": "completed",
            "summary": "正常完成摘要",
            "finishedAt": "2026-07-15T16:00:55",
        },
    )
    session_service._set_session_live_output("session-live", turn_id="turn-completed", content="final")

    session_service._ensure_session_turn_terminal_fallback("session-live", "turn-completed")

    events = load_conversation_events(tmp_path, "session-live")
    assert [event.event_type for event in events] == [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED]
    work_run = work_runs.load_snapshot("chat_turn", "turn-completed")
    assert work_run["status"] == "completed"
    assert work_run["summary"] == "正常完成摘要"
    assert session_service._snapshot_session_live_output("session-live") is None


def test_terminal_fallback_does_not_block_running_cleanup_when_fallback_persistence_raises(monkeypatch):
    monkeypatch.setattr(
        session_service,
        "load_conversation_events",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("journal unavailable")),
    )
    monkeypatch.setattr(
        session_service,
        "_persist_chat_turn_work_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("work run unavailable")),
    )
    session_service._set_session_running("session-live", True, turn_id="turn-fallback-errors")
    session_service._set_session_live_output("session-live", turn_id="turn-fallback-errors", content="partial")

    try:
        session_service._ensure_session_turn_terminal_fallback("session-live", "turn-fallback-errors")
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-fallback-errors")

    assert "session-live" not in session_service._RUNNING_SESSION_IDS
    assert session_service._snapshot_session_live_output("session-live") is None


def test_session_stream_full_queue_prefers_dropping_snapshots_before_assistant_delta():
    subscriber = queue.Queue(maxsize=2)
    subscriber.put_nowait({"type": "assistant_delta", "contentDelta": "你"})
    subscriber.put_nowait({"type": "session_detail", "ledgerSeq": 1})

    delivered, dropped = session_service._put_session_stream_event(
        subscriber,
        {"type": "assistant_delta", "content": "你好", "contentDelta": "好", "replaceContent": False},
        recover_assistant_delta_on_drop=True,
    )

    assert delivered is True
    assert dropped == 1
    first = subscriber.get_nowait()
    second = subscriber.get_nowait()
    assert first["type"] == "assistant_delta"
    assert first["contentDelta"] == "你"
    assert second["type"] == "assistant_delta"
    assert second["contentDelta"] == "好"
    assert second["replaceContent"] is False


def test_session_stream_full_queue_recovers_when_old_assistant_delta_must_drop():
    subscriber = queue.Queue(maxsize=1)
    subscriber.put_nowait({"type": "assistant_delta", "contentDelta": "你"})

    delivered, dropped = session_service._put_session_stream_event(
        subscriber,
        {
            "type": "assistant_delta",
            "content": "你好",
            "thought": "思考",
            "contentDelta": "好",
            "thoughtDelta": "考",
            "replaceContent": False,
            "replaceThought": False,
        },
        recover_assistant_delta_on_drop=True,
    )

    assert delivered is True
    assert dropped == 1
    recovered = subscriber.get_nowait()
    assert recovered["contentDelta"] == "你好"
    assert recovered["thoughtDelta"] == "思考"
    assert recovered["replaceContent"] is True
    assert recovered["replaceThought"] is True


def test_session_stream_full_queue_recovers_from_explicit_snapshot_when_public_delta_is_lightweight():
    subscriber = queue.Queue(maxsize=1)
    subscriber.put_nowait({"type": "assistant_delta", "contentDelta": "你"})

    delivered, dropped = session_service._put_session_stream_event(
        subscriber,
        {
            "type": "assistant_delta",
            "content": "",
            "thought": "",
            "contentDelta": "好",
            "thoughtDelta": "考",
            "replaceContent": False,
            "replaceThought": False,
        },
        recover_assistant_delta_on_drop=True,
        assistant_delta_recovery_event={
            "type": "assistant_delta",
            "content": "",
            "thought": "",
            "contentDelta": "你好",
            "thoughtDelta": "思考",
            "replaceContent": True,
            "replaceThought": True,
        },
    )

    assert delivered is True
    assert dropped == 1
    recovered = subscriber.get_nowait()
    assert recovered["content"] == ""
    assert recovered["thought"] == ""
    assert recovered["contentDelta"] == "你好"
    assert recovered["thoughtDelta"] == "思考"
    assert recovered["replaceContent"] is True
    assert recovered["replaceThought"] is True


def test_session_assistant_delta_publish_recovers_full_snapshot_with_lightweight_public_event(monkeypatch):
    subscriber = queue.Queue(maxsize=1)
    subscriber.put_nowait(
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-old",
            "contentDelta": "旧",
        }
    )
    monkeypatch.setattr(session_service, "_session_ledger_sequence", lambda session_id: 42)
    session_service._register_session_stream_subscriber("session-live", subscriber)
    try:
        session_service._publish_session_assistant_delta(
            "session-live",
            session_service.SessionLiveOutputState(
                session_id="session-live",
                turn_id="turn-1",
                content="你好",
                thought="思考",
                content_delta="好",
                thought_delta="考",
            ),
        )
    finally:
        session_service._unregister_session_stream_subscriber("session-live", subscriber)

    recovered = subscriber.get_nowait()
    assert recovered["sessionId"] == "session-live"
    assert recovered["turnId"] == "turn-1"
    assert recovered["ledgerSeq"] == 42
    assert recovered["content"] == ""
    assert recovered["thought"] == ""
    assert recovered["contentDelta"] == "你好"
    assert recovered["thoughtDelta"] == "思考"
    assert recovered["replaceContent"] is True
    assert recovered["replaceThought"] is True


def test_session_stream_initial_state_prefers_live_overlay_summary(tmp_path, monkeypatch):
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
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-seeded-user",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "继续前端开发"},
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-seeded-assistant",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "已经接到真实状态了。"},
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="turn-live")
    try:
        session_service._set_session_live_output(
            "session-live",
            turn_id="turn-live",
            content="实时内容",
            thought="实时思考",
            feedback_events=[{"kind": "status", "name": "model_response"}],
        )

        payload = session_service.get_session_stream_initial_state("session-live")
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-live")
        session_service._clear_session_live_output("session-live", turn_id="turn-live")

    assert payload is not None
    assert payload["running"] is True
    assert payload["activeTurnId"] == "turn-live"
    latest = payload["latestMessage"]
    assert latest["id"] == session_service._live_assistant_message_id("session-live", "turn-live")
    assert latest["role"] == "assistant"
    assert latest["streaming"] is True
    assert latest["contentLength"] == len("实时内容")
    assert latest["thoughtLength"] == len("实时思考")
    assert latest["feedbackEventCount"] == 1


def test_get_session_detail_materializes_agent_directory_stub_without_switching_active(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-active",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-active",
                    "title": "唐望舒",
                    "agent_id": "agent-active",
                    "agentId": "agent-active",
                    "updated_at": "2026-05-18T12:00:00",
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent_directory_service.save_state(
        {
            "agents": [
                {
                    "agentId": "agent-active",
                    "displayName": "唐望舒",
                    "directSessionId": "session-active",
                    "status": "active",
                    "workspacePath": "workspace/agents/agent-active",
                },
                {
                    "agentId": "agent-knowledge-steward",
                    "displayName": "资料入库",
                    "directSessionId": "agent-knowledge-steward-direct",
                    "status": "active",
                    "workspacePath": "workspace/agents/agent-knowledge-steward",
                },
            ]
        }
    )

    detail = session_service.get_session_detail("agent-knowledge-steward-direct")

    assert detail is not None
    assert detail["id"] == "agent-knowledge-steward-direct"
    assert detail["agentId"] == "agent-knowledge-steward"
    assert load_chat_state(tmp_path)["active_conversation_id"] == "session-active"


def test_get_session_detail_materializes_legacy_workspace_less_session(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-active",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-active",
                    "title": "唐望舒",
                    "agent_id": "agent-active",
                    "agentId": "agent-active",
                    "workspace_path": "workspace/sessions/session-active",
                    "updated_at": "2026-05-18T12:00:00",
                },
                {
                    "conversation_id": "session-legacy",
                    "title": "旧会话",
                    "updated_at": "2026-05-18T12:01:00",
                },
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent_directory_service.save_state(
        {
            "agents": [
                {
                    "agentId": "agent-active",
                    "displayName": "唐望舒",
                    "directSessionId": "session-active",
                    "status": "active",
                    "workspacePath": "workspace/agents/agent-active",
                }
            ]
        }
    )

    detail = session_service.get_session_detail("session-legacy")

    state = load_chat_state(tmp_path)
    legacy = next(item for item in state["conversations"] if item["conversation_id"] == "session-legacy")
    assert detail is not None
    assert detail["id"] == "session-legacy"
    assert detail["agentId"]
    assert legacy["agentId"] == detail["agentId"]
    assert legacy["workspace_path"] == "workspace/sessions/session-legacy"
    assert state["active_conversation_id"] == "session-active"


def test_image_attachment_capability_uses_dialogue_llm(monkeypatch):
    monkeypatch.setattr(
        session_service,
        "_session_agent_supports_image_input",
        lambda agent_instance, *, slot: True,
    )
    monkeypatch.setattr(
        session_service,
        "_session_agent_llm_slot_model_id",
        lambda agent_instance, slot: "mimo-vision",
    )
    monkeypatch.setattr(
        session_service,
        "_session_agent_llm_model_name",
        lambda agent_instance, *, slot: "mimo-v2.5-pro",
    )

    capability = session_service._resolve_image_attachment_capability(
        agent_instance={"agentId": "agent-vision"},
    )

    assert capability["llm_slot"] == session_service.SESSION_LLM_SLOT_DIALOGUE
    assert capability["supports_image_input"] is True
    assert "route" not in capability
    assert "intent" not in capability


def test_image_attachment_capability_remains_dialogue_without_model_binding(monkeypatch):
    monkeypatch.setattr(
        session_service,
        "_session_agent_supports_image_input",
        lambda agent_instance, *, slot: True,
    )

    capability = session_service._resolve_image_attachment_capability(agent_instance={})

    assert capability["llm_slot"] == session_service.SESSION_LLM_SLOT_DIALOGUE
    assert capability["supports_image_input"] is True


def test_image_attachment_unknown_capability_is_preserved_for_fail_open(monkeypatch):
    monkeypatch.setattr(
        session_service,
        "_session_agent_supports_image_input",
        lambda agent_instance, *, slot: None,
    )
    monkeypatch.setattr(
        session_service,
        "_session_agent_llm_slot_model_id",
        lambda agent_instance, slot: "ai-pixel/gpt-5.6-terra",
    )
    monkeypatch.setattr(
        session_service,
        "_session_agent_llm_model_name",
        lambda agent_instance, *, slot: "gpt-5.6-terra",
    )

    capability = session_service._resolve_image_attachment_capability(
        agent_instance={"agentId": "agent-terra"},
    )

    assert capability["llm_slot"] == session_service.SESSION_LLM_SLOT_DIALOGUE
    assert capability["supports_image_input"] is None


def test_session_image_support_uses_resolved_runtime_probe_tristate(monkeypatch):
    def resolved(value):
        return SimpleNamespace(
            resolved_spec=SimpleNamespace(
                provider_details={
                    "capabilities": {
                        "image_input": {
                            "value": value,
                            "source": "runtime_probe",
                        }
                    }
                }
            ),
            capabilities=SimpleNamespace(supports_image_input=False),
        )

    monkeypatch.setattr(
        session_service,
        "get_config",
        lambda: SimpleNamespace(llm=SimpleNamespace()),
    )
    monkeypatch.setattr(session_service, "resolve_agent_llm", lambda *args, **kwargs: resolved("supported"))
    agent = {"llmBindings": {"vision": {"modelId": "ai-pixel/gpt-5.6-terra"}}}

    assert (
        session_service._session_agent_supports_image_input(
            agent,
            slot=session_service.SESSION_LLM_SLOT_VISION,
        )
        is True
    )

    monkeypatch.setattr(session_service, "resolve_agent_llm", lambda *args, **kwargs: resolved("unknown"))
    assert (
        session_service._session_agent_supports_image_input(
            agent,
            slot=session_service.SESSION_LLM_SLOT_VISION,
        )
        is None
    )


def test_session_image_support_preserves_unknown_resolved_capability(monkeypatch):
    resolved = SimpleNamespace(
        resolved_spec=SimpleNamespace(provider_details={"capabilities": {}}),
        capabilities=SimpleNamespace(supports_image_input=None),
    )
    monkeypatch.setattr(session_service, "get_config", lambda: SimpleNamespace(llm=SimpleNamespace()))
    monkeypatch.setattr(session_service, "resolve_agent_llm", lambda *args, **kwargs: resolved)
    agent = {"llmBindings": {"dialogue": {"modelId": "ai-pixel/gpt-5.6-terra"}}}

    assert session_service._session_agent_supports_image_input(agent) is None


def test_contextual_image_retry_still_requires_explicit_image_intent():
    assert session_service._is_retriable_image_request_prompt("继续") is False
    assert session_service._is_retriable_image_request_prompt("再看一下刚才那张图") is True
    assert session_service._is_retriable_image_request_prompt("我刚才点击了测试，还是显示不支持图像为什么") is False


def test_session_image_support_uses_shared_model_capability_rules(monkeypatch):
    class DummyLlm:
        model_library = {
            "mimo_model": {
                "provider_id": "xiaomi_provider",
                "model": "mimo-v2.5",
            },
            "blocked_hint_model": {
                "provider_id": "relay_provider",
                "model": "gpt-5.5-vision-like",
                "capability_status": "unsupported",
            },
        }

        def get_provider(self, provider_id):
            if provider_id == "xiaomi_provider":
                return SimpleNamespace(kind="xiaomi")
            return SimpleNamespace(kind="relay")

    monkeypatch.setattr(session_service, "get_config", lambda: SimpleNamespace(llm=DummyLlm()))

    assert (
        session_service._session_agent_supports_image_input(
            {"llmBindings": {"vision": {"modelId": "mimo_model"}}},
            slot=session_service.SESSION_LLM_SLOT_VISION,
        )
        is True
    )
    assert (
        session_service._session_agent_supports_image_input(
            {"llmBindings": {"vision": {"modelId": "blocked_hint_model"}}},
            slot=session_service.SESSION_LLM_SLOT_VISION,
        )
        is False
    )
def test_session_detail_agent_snapshot_reuses_normalized_agent(monkeypatch):
    from core.web.services import session_service

    cached_agent = {
        "agentId": "agent-reuse",
        "displayName": "Reuse Agent",
    }

    def fail_directory_lookup(_agent_id):
        raise AssertionError("normalized Agent snapshot must not reload the directory")

    monkeypatch.setattr(session_service, "get_agent", fail_directory_lookup)

    assert session_service._session_detail_agent_snapshot(
        {"_agent": cached_agent},
        "agent-reuse",
        hydrate_agent=True,
    ) is cached_agent


def test_messages_with_live_output_reuses_normalized_projection(monkeypatch):
    from core.web.services import session_service

    normalized_messages = [
        {
            "id": "session-reuse-message-1",
            "role": "user",
            "content": "hello",
            "timestamp": "2026-07-14T00:00:00Z",
        }
    ]

    def fail_ledger_reload(_session_id):
        raise AssertionError("normalized session messages must not reload the ledger")

    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", fail_ledger_reload)
    monkeypatch.setattr(session_service, "_build_live_output_message", lambda _session_id: None)

    assert session_service._messages_with_live_output(
        "session-reuse",
        normalized_messages=normalized_messages,
    ) == normalized_messages


def _stub_session_query_source(monkeypatch, summaries):
    monkeypatch.setattr(
        session_service,
        "_get_cached_session_query_sessions",
        lambda **_kwargs: [dict(item) for item in summaries],
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_list_query_event",
        lambda **_kwargs: None,
    )


def test_session_catalog_fixture_is_deterministic_and_default_sorted():
    summaries = build_session_query_summaries(12)

    assert len(summaries) == 12
    assert summaries[0]["id"] == "session-00011"
    assert summaries[-1]["id"] == "session-00000"
    assert set(QUERY_SEARCH_FIELDS).issubset(summaries[0])
    assert [item["id"] for item in summaries if "needle" in item["title"]] == [
        "session-00010",
        "session-00000",
    ]


def test_session_query_contract_searches_all_declared_metadata_fields(monkeypatch):
    base = build_session_query_summaries(1)[0]

    for field in QUERY_SEARCH_FIELDS:
        item = dict(base)
        marker = f"unique-{field.lower()}-marker"
        item[field] = marker
        _stub_session_query_source(monkeypatch, [item])

        payload = session_service.query_sessions(q=f"  {marker.upper()}  ")

        assert payload["items"] == [item], field
        assert payload["filters"]["q"] == marker.upper(), field


def test_session_query_contract_normalizes_filters_sort_and_numeric_cursor(monkeypatch):
    summaries = build_session_query_summaries(24)
    _stub_session_query_source(monkeypatch, summaries)

    page = session_service.query_sessions(limit=3, cursor="2")
    assert [item["id"] for item in page["items"]] == [
        item["id"] for item in summaries[2:5]
    ]
    assert page["nextCursor"] == "5"
    assert page["totalEstimate"] == 24
    assert page["filters"]["cursor"] == "2"

    invalid = session_service.query_sessions(limit=0, cursor="-9", sort="unsupported")
    assert invalid["filters"]["limit"] == session_service._SESSION_QUERY_DEFAULT_LIMIT
    assert invalid["filters"]["cursor"] == ""
    assert invalid["filters"]["sort"] == "updatedAt_desc"

    agent_filtered = session_service.query_sessions(agent_id="agent-03")
    assert agent_filtered["items"]
    assert {item["agentId"] for item in agent_filtered["items"]} == {"agent-03"}

    kind_filtered = session_service.query_sessions(session_kind=" CHILD ")
    assert kind_filtered["items"]
    assert {item["sessionKind"] for item in kind_filtered["items"]} == {"child"}

    state_filtered = session_service.query_sessions(state=" MODEL_REQUEST ")
    assert state_filtered["items"]
    assert {item["currentPhase"] for item in state_filtered["items"]} == {
        "model_request"
    }

    title_sorted = session_service.query_sessions(sort="title_asc")
    assert [item["title"] for item in title_sorted["items"]] == sorted(
        (item["title"] for item in summaries),
        key=str.lower,
    )


def test_session_query_benchmark_reports_bounded_synthetic_metrics(
    monkeypatch,
    tmp_path,
):
    from scripts.benchmark_session_query import (
        SCENARIOS,
        initialize_benchmark_data_root,
        run_benchmark,
    )

    data_root = tmp_path / "benchmark-data"
    data_root.mkdir()
    monkeypatch.setattr(
        session_service,
        "_SESSION_LIST_CACHE_TTL_SECONDS",
        0.0,
    )
    initialize_benchmark_data_root(data_root)
    dry_run = run_benchmark(
        data_root=data_root,
        sizes=[8],
        warmups=1,
        samples=2,
        dry_run=True,
    )
    payload = run_benchmark(
        data_root=data_root,
        sizes=[8],
        warmups=1,
        samples=2,
        approved_manifest_hash=dry_run["manifest"]["manifestHash"],
    )

    assert payload["schemaVersion"] == 1
    assert payload["implementation"] == "legacy_python_session_query"
    assert payload["workload"] == "temporary_chat_state_with_counted_empty_ledger_reads"
    assert payload["dryRun"] is False
    assert payload["isolation"]["dataRootKind"] == "explicit_system_temp_child"
    assert payload["isolation"]["operatorStateUnchanged"] is True
    assert payload["isolation"]["lifecycleMode"] == "offline_in_process_no_launcher"
    assert session_service._SESSION_LIST_CACHE_TTL_SECONDS == 0.0
    assert len(payload["results"]) == len(SCENARIOS)
    for result in payload["results"]:
        assert result["sessionCount"] == 8
        assert result["p50Ms"] >= 0
        assert result["p95Ms"] >= result["p50Ms"]
        assert result["peakAllocatedBytes"] >= 0
        assert result["allocationProbe"] == "measured"
        assert result["ledgerPreviewCallsPerSample"] >= 0
    warm_default = next(
        item for item in payload["results"] if item["scenario"] == "warm_default_page"
    )
    assert warm_default["ledgerPreviewCallsPerSample"] == 0


def test_session_query_benchmark_rejects_operator_workspace_as_data_root(
    monkeypatch,
    tmp_path,
):
    from scripts import benchmark_session_query

    operator_workspace = tmp_path / "operator" / "data" / "workspace"
    (operator_workspace / "chat").mkdir(parents=True)
    (operator_workspace / "chat" / "chat_state.json").write_text(
        '{"version": 1, "conversations": []}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        benchmark_session_query.isolation,
        "formal_operator_workspace",
        lambda: operator_workspace,
        raising=False,
    )

    with pytest.raises(
        benchmark_session_query.BenchmarkIsolationError,
        match="operator",
    ):
        benchmark_session_query.run_benchmark(
            data_root=operator_workspace,
            sizes=[8],
            warmups=1,
            samples=1,
        )

    assert not (operator_workspace / "sessions").exists()


def test_session_query_benchmark_dry_run_preserves_operator_hashes(
    monkeypatch,
    tmp_path,
):
    from scripts import benchmark_session_query

    operator_workspace = tmp_path / "operator" / "data" / "workspace"
    data_root = tmp_path / "benchmark-data"
    (operator_workspace / "chat").mkdir(parents=True)
    (operator_workspace / "agents").mkdir()
    (operator_workspace / "agent_config").mkdir()
    data_root.mkdir()
    protected_payloads = {
        operator_workspace / "chat" / "chat_state.json": '{"chat": true}',
        operator_workspace / "agents" / "agents.json": '{"agents": []}',
        operator_workspace
        / "agent_config"
        / "mode_bindings.json": '{"bindings": []}',
    }
    for path, content in protected_payloads.items():
        path.write_text(content, encoding="utf-8")
    benchmark_session_query.initialize_benchmark_data_root(data_root)
    monkeypatch.setattr(
        benchmark_session_query.isolation,
        "formal_operator_workspace",
        lambda: operator_workspace,
        raising=False,
    )

    payload = benchmark_session_query.run_benchmark(
        data_root=data_root,
        sizes=[8],
        warmups=1,
        samples=1,
        dry_run=True,
    )

    assert payload["dryRun"] is True
    assert payload["results"] == []
    assert payload["isolation"]["operatorStateUnchanged"] is True
    assert payload["isolation"]["protectedBefore"] == payload["isolation"][
        "protectedAfter"
    ]
    assert {item.name for item in data_root.iterdir()} == {
        benchmark_session_query.DATA_ROOT_SENTINEL
    }
    for path, content in protected_payloads.items():
        assert path.read_text(encoding="utf-8") == content


def test_session_query_benchmark_normal_run_cannot_pollute_operator_state(
    monkeypatch,
    tmp_path,
):
    from scripts import benchmark_session_query

    operator_workspace = tmp_path / "operator" / "data" / "workspace"
    data_root = tmp_path / "benchmark-data"
    (operator_workspace / "chat").mkdir(parents=True)
    (operator_workspace / "agents" / "agent-real").mkdir(parents=True)
    (operator_workspace / "sessions" / "session-real").mkdir(parents=True)
    (operator_workspace / "agent_config").mkdir()
    data_root.mkdir()
    protected_payloads = {
        operator_workspace / "chat" / "chat_state.json": '{"chat": "sentinel"}',
        operator_workspace / "agents" / "agents.json": '{"agents": ["real"]}',
        operator_workspace
        / "agent_config"
        / "mode_bindings.json": '{"bindings": ["real"]}',
    }
    for path, content in protected_payloads.items():
        path.write_text(content, encoding="utf-8")
    benchmark_session_query.initialize_benchmark_data_root(data_root)
    monkeypatch.setattr(
        benchmark_session_query.isolation,
        "formal_operator_workspace",
        lambda: operator_workspace,
        raising=False,
    )

    dry_run = benchmark_session_query.run_benchmark(
        data_root=data_root,
        sizes=[8],
        warmups=1,
        samples=1,
        dry_run=True,
    )
    payload = benchmark_session_query.run_benchmark(
        data_root=data_root,
        sizes=[8],
        warmups=1,
        samples=1,
        approved_manifest_hash=dry_run["manifest"]["manifestHash"],
    )

    assert payload["results"]
    assert payload["isolation"]["operatorStateUnchanged"] is True
    assert {item.name for item in data_root.iterdir()} == {
        benchmark_session_query.DATA_ROOT_SENTINEL
    }
    assert {item.name for item in (operator_workspace / "sessions").iterdir()} == {
        "session-real"
    }
    assert {item.name for item in (operator_workspace / "agents").iterdir()} == {
        "agent-real",
        "agents.json",
    }
    for path, content in protected_payloads.items():
        assert path.read_text(encoding="utf-8") == content


def test_session_query_benchmark_output_must_stay_under_data_root(
    monkeypatch,
    tmp_path,
):
    from scripts import benchmark_session_query

    operator_workspace = tmp_path / "operator" / "data" / "workspace"
    data_root = tmp_path / "benchmark-data"
    operator_workspace.mkdir(parents=True)
    data_root.mkdir()
    benchmark_session_query.initialize_benchmark_data_root(data_root)
    monkeypatch.setattr(
        benchmark_session_query.isolation,
        "formal_operator_workspace",
        lambda: operator_workspace,
        raising=False,
    )

    with pytest.raises(
        benchmark_session_query.BenchmarkIsolationError,
        match="output path",
    ):
        benchmark_session_query.isolation.validate_output_path(
            tmp_path / "outside.json",
            data_root=data_root,
        )

    assert (
        benchmark_session_query.isolation.validate_output_path(
            data_root / "result.json",
            data_root=data_root,
        )
        == data_root / "result.json"
    )


def test_session_query_benchmark_requires_sentinel_and_matching_manifest(
    monkeypatch,
    tmp_path,
):
    from scripts import benchmark_session_query

    operator_workspace = tmp_path / "operator" / "data" / "workspace"
    data_root = tmp_path / "benchmark-data"
    operator_workspace.mkdir(parents=True)
    data_root.mkdir()
    monkeypatch.setattr(
        benchmark_session_query.isolation,
        "formal_operator_workspace",
        lambda: operator_workspace,
        raising=False,
    )

    with pytest.raises(
        benchmark_session_query.BenchmarkIsolationError,
        match="sentinel",
    ):
        benchmark_session_query.run_benchmark(
            data_root=data_root,
            sizes=[8],
            warmups=1,
            samples=1,
            dry_run=True,
        )

    benchmark_session_query.initialize_benchmark_data_root(data_root)
    with pytest.raises(
        benchmark_session_query.BenchmarkIsolationError,
        match="manifest hash",
    ):
        benchmark_session_query.run_benchmark(
            data_root=data_root,
            sizes=[8],
            warmups=1,
            samples=1,
        )


def test_session_query_benchmark_rejects_launcher_mounted_root(
    monkeypatch,
    tmp_path,
):
    from scripts import benchmark_session_query

    operator_workspace = tmp_path / "operator" / "data" / "workspace"
    mounted_root = tmp_path / "launcher-mounted"
    data_root = mounted_root / "benchmark-data"
    operator_workspace.mkdir(parents=True)
    data_root.mkdir(parents=True)
    monkeypatch.setattr(
        benchmark_session_query.isolation,
        "formal_operator_workspace",
        lambda: operator_workspace,
        raising=False,
    )
    monkeypatch.setattr(
        benchmark_session_query.isolation,
        "launcher_mount_roots",
        lambda: {mounted_root},
        raising=False,
    )

    with pytest.raises(
        benchmark_session_query.BenchmarkIsolationError,
        match="Launcher",
    ):
        benchmark_session_query.initialize_benchmark_data_root(data_root)


def test_session_query_benchmark_skips_allocation_probe_above_limit(
    monkeypatch,
    tmp_path,
):
    from scripts import benchmark_session_query

    operator_workspace = tmp_path / "operator" / "data" / "workspace"
    data_root = tmp_path / "benchmark-data"
    operator_workspace.mkdir(parents=True)
    data_root.mkdir()
    monkeypatch.setattr(
        benchmark_session_query.isolation,
        "formal_operator_workspace",
        lambda: operator_workspace,
        raising=False,
    )
    benchmark_session_query.initialize_benchmark_data_root(data_root)
    dry_run = benchmark_session_query.run_benchmark(
        data_root=data_root,
        sizes=[8],
        warmups=1,
        samples=1,
        dry_run=True,
        allocation_max_sessions=4,
    )

    payload = benchmark_session_query.run_benchmark(
        data_root=data_root,
        sizes=[8],
        warmups=1,
        samples=1,
        allocation_max_sessions=4,
        approved_manifest_hash=dry_run["manifest"]["manifestHash"],
    )

    assert payload["results"]
    assert {
        (item["allocationProbe"], item["peakAllocatedBytes"])
        for item in payload["results"]
    } == {("skipped_above_limit", None)}


def test_session_query_benchmark_isolates_large_cold_samples_by_process(
    monkeypatch,
    tmp_path,
):
    from scripts import benchmark_session_query

    invocations: list[list[str]] = []
    payloads = iter(
        (
            '{"durationMs": 10, "ledgerPreviewCalls": 8, '
            '"resultCount": 6, "matchedCount": 6}',
            '{"durationMs": 20, "ledgerPreviewCalls": 8, '
            '"resultCount": 6, "matchedCount": 6}',
            '{"durationMs": 40, "ledgerPreviewCalls": 8, '
            '"resultCount": 6, "matchedCount": 6}',
        )
    )

    def fake_run(command, **kwargs):
        invocations.append(command)
        assert kwargs["check"] is True
        assert kwargs["capture_output"] is True
        return SimpleNamespace(stdout=next(payloads))

    monkeypatch.setattr(benchmark_session_query.subprocess, "run", fake_run)

    result = benchmark_session_query._measure_cold_in_subprocesses(
        data_root=tmp_path,
        session_count=10_000,
        warmups=1,
        samples=2,
    )

    assert len(invocations) == 3
    assert all("--worker-single-cold" in command for command in invocations)
    assert result["p50Ms"] == 30.0
    assert result["p95Ms"] == 40.0
    assert result["processIsolation"] == "one_process_per_cold_sample"
    assert result["allocationProbe"] == "skipped_process_isolated_cold"
