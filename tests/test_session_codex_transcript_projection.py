import queue

from core.web.services import session_service


def test_normalized_assistant_message_exposes_native_codex_transcript():
    messages = session_service._normalize_messages(
        "session-codex",
        [
            {
                "role": "assistant",
                "content": "已经完成检查。",
                "timestamp": "2026-07-07T10:30:00Z",
                "tool_calls": [
                    {
                        "name": "cli_tool",
                        "status": "done",
                        "summary": "npm --prefix web run test",
                        "arguments": {"cmd": "npm --prefix web run test", "cwd": "C:/repo"},
                        "resultPreview": "12 passed",
                        "durationSeconds": 1.25,
                        "exitCode": 0,
                    },
                    {
                        "name": "rg",
                        "status": "failed",
                        "summary": "rg codexTranscript",
                        "error": "No matches",
                        "exitCode": 1,
                        "timedOut": False,
                    },
                ],
                "feedback_events": [
                    {
                        "sequence": 1,
                        "kind": "tool",
                        "status": "done",
                        "name": "cli_tool",
                        "summary": "npm --prefix web run test",
                        "arguments": {"cmd": "npm --prefix web run test", "cwd": "C:/repo"},
                        "resultPreview": "12 passed",
                        "durationSeconds": 1.25,
                        "exitCode": 0,
                    },
                    {
                        "sequence": 2,
                        "kind": "tool",
                        "status": "failed",
                        "name": "rg",
                        "summary": "rg codexTranscript",
                        "error": "No matches",
                        "exitCode": 1,
                    },
                ],
            }
        ],
    )

    assistant = messages[0]

    assert "timelineItems" in assistant
    transcript = assistant["codexTranscript"]
    assert transcript["version"] == 1
    assert transcript["source"] == "native"
    assert transcript["messageId"] == assistant["id"]
    assert [cell["kind"] for cell in transcript["cells"]] == [
        "tool_call",
        "error_notice",
        "assistant_markdown",
    ]
    assert transcript["cells"][0]["tone"] == "neutral"
    assert transcript["cells"][0]["status"] == "completed"
    assert transcript["cells"][1]["tone"] == "error"
    assert transcript["cells"][1]["status"] == "failed"
    assert transcript["cells"][1]["summary"] == "No matches"
    assert transcript["toolCalls"][0]["runtimeKind"] == "terminal"
    assert transcript["terminalOperations"][0]["request"]["displayCommand"] == "npm --prefix web run test"
    assert transcript["terminalOperations"][0]["result"]["exitCode"] == 0
    assert transcript["terminalOperations"][0]["result"]["formattedOutput"] == "12 passed"
    assert transcript["terminalSessions"][0]["operationIds"] == ["terminal_operation:0"]
    assert transcript["modelObservations"][0]["source"] == "DirectToolCall"
    assert [event["kind"] for event in transcript["rolloutEvents"][:4]] == [
        "ToolCallStarted",
        "RuntimeStarted",
        "RuntimeEnded",
        "ToolCallEnded",
    ]


def test_normalized_user_message_does_not_expose_assistant_codex_transcript():
    messages = session_service._normalize_messages(
        "session-codex",
        [
            {
                "role": "user",
                "content": "你好",
                "timestamp": "2026-07-07T10:31:00Z",
                "metadata": {"kind": "journal_user_message", "turnId": "turn-user"},
            }
        ],
    )

    user = messages[0]

    assert user["role"] == "user"
    assert user["content"] == "你好"
    assert "codexTranscript" not in user


def test_native_codex_transcript_preserves_non_terminal_tool_result_preview_details():
    result_preview = """{
  "status": "ok",
  "mode": "inspect",
  "target": {
    "symbol": "agent_conversation_index_classification"
  },
  "count": 1
}"""
    messages = session_service._normalize_messages(
        "session-codex",
        [
            {
                "role": "assistant",
                "content": "已完成。",
                "timestamp": "2026-07-07T10:32:00Z",
                "feedback_events": [
                    {
                        "sequence": 1,
                        "kind": "tool",
                        "status": "done",
                        "name": "code_symbol_tool",
                        "summary": '{\n"status": "ok",',
                        "resultPreview": result_preview,
                        "resultType": "str",
                        "resultLength": len(result_preview),
                        "resultKind": "code_context_graph",
                        "truncated": False,
                        "originalLength": len(result_preview),
                    }
                ],
            }
        ],
    )

    transcript = messages[0]["codexTranscript"]
    tool_call = transcript["toolCalls"][0]

    assert transcript["cells"][0]["summary"] == '{\n"status": "ok",'
    assert tool_call["summary"] == '{\n"status": "ok",'
    assert tool_call["resultPreview"] == result_preview
    assert tool_call["resultLength"] == len(result_preview)
    assert tool_call["resultKind"] == "code_context_graph"
    assert tool_call["truncated"] is False


def test_live_output_checkpoint_includes_native_codex_transcript():
    payload = session_service._live_output_checkpoint_payload(
        session_service.SessionLiveOutputState(
            session_id="session-live",
            turn_id="turn-1",
            stage="tooling",
            content="",
            tool_calls=[
                {
                    "name": "cli_tool",
                    "status": "running",
                    "summary": "pytest tests/test_session_service.py",
                    "arguments": {"sessionId": "terminal-a"},
                }
            ],
            feedback_events=[
                {
                    "sequence": 1,
                    "kind": "tool",
                    "status": "running",
                    "name": "cli_tool",
                    "summary": "pytest tests/test_session_service.py",
                    "arguments": {"sessionId": "terminal-a"},
                }
            ],
            updated_at="2026-07-07T10:35:00Z",
        )
    )

    transcript = payload["codexTranscript"]
    assert transcript["source"] == "native"
    assert transcript["streaming"] is True
    assert transcript["cells"][-1]["kind"] == "stream_tail"
    assert transcript["cells"][0]["status"] == "running"
    assert [event["kind"] for event in transcript["rolloutEvents"]] == [
        "ToolCallStarted",
        "RuntimeStarted",
    ]


def test_assistant_delta_publish_and_coalesce_preserve_native_codex_transcript(monkeypatch):
    monkeypatch.setattr(session_service, "_session_ledger_sequence", lambda _session_id: 11)
    subscriber = queue.Queue(maxsize=4)
    session_service._register_session_stream_subscriber("session-live", subscriber)
    try:
        session_service._publish_session_assistant_delta(
            "session-live",
            session_service.SessionLiveOutputState(
                session_id="session-live",
                turn_id="turn-1",
                stage="tooling",
                content="正在处理",
                content_delta="处理",
                tool_calls=[
                    {
                        "name": "cli_tool",
                        "status": "running",
                        "summary": "npm --prefix web run build",
                    }
                ],
                feedback_events=[
                    {
                        "sequence": 1,
                        "kind": "tool",
                        "status": "running",
                        "name": "cli_tool",
                        "summary": "npm --prefix web run build",
                    }
                ],
            ),
            include_feedback_events=True,
        )
    finally:
        session_service._unregister_session_stream_subscriber("session-live", subscriber)

    event = subscriber.get_nowait()
    transcript = event["codexTranscript"]
    assert transcript["source"] == "native"
    assert transcript["cells"][0]["kind"] == "tool_call"
    assert transcript["rolloutEvents"][0]["kind"] == "ToolCallStarted"

    merged = session_service._merge_session_assistant_delta_events(
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-1",
            "contentDelta": "正",
            "thoughtDelta": "",
            "replaceContent": False,
            "replaceThought": False,
            "codexTranscript": {
                "version": 1,
                "source": "native",
                "messageId": "old",
                "cells": [{"id": "old-cell", "kind": "status", "status": "running", "tone": "running"}],
            },
        },
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-1",
            "contentDelta": "在",
            "thoughtDelta": "",
            "replaceContent": False,
            "replaceThought": False,
            "codexTranscript": {
                "version": 1,
                "source": "native",
                "messageId": "new",
                "cells": [{"id": "new-cell", "kind": "tool_call", "status": "running", "tone": "running"}],
            },
        },
    )

    assert merged["contentDelta"] == "正在"
    assert merged["codexTranscript"]["messageId"] == "new"
    assert merged["codexTranscript"]["cells"][0]["id"] == "new-cell"
