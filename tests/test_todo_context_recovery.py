"""Todo recovery must use active journal facts without becoming conversation."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from core.chat.conversation_invariant import conversation_layer_fingerprint
from core.chat.conversation_ledger import (
    append_conversation_event, load_conversation_events,
    EVENT_USER_MESSAGE, EVENT_TOOL_RESULT,
)
from core.chat.todo_checklist import TODO_CONTEXT_HEADER, restore_todo_context_from_journal
from tools.todo_tools import todo_write


def write_todo(root, todos, *, session="s", turn="t", call="todo", status="done", result=None):
    return append_conversation_event(
        root, session, turn, EVENT_TOOL_RESULT, status=status, tool_call_id=call,
        payload={"toolCall": {"id": call, "name": "todo_write", "arguments": {"todos": todos},
                              "result": todo_write(todos) if result is None else result}},
    )


def todo(content="current", status="in_progress"):
    return [{"content": content, "activeForm": f"doing {content}", "status": status}]


def restore(root, messages=None, *, session="s", turn="t", prompt=None):
    return restore_todo_context_from_journal(
        messages or [SystemMessage("stable"), HumanMessage("request")],
        project_root=root, session_id=session, turn_id=turn, user_prompt=prompt,
    )


def blocks(messages):
    return [m for m in messages if isinstance(m, SystemMessage) and m.content.startswith(TODO_CONTEXT_HEADER)]


def test_recovers_missing_todo_before_user_without_changing_conversation(tmp_path):
    event = write_todo(tmp_path, todo())
    source = [SystemMessage("stable"), HumanMessage("request"), AIMessage("compressed history")]
    before = conversation_layer_fingerprint(source)
    recovered = restore(tmp_path, source)
    assert len(blocks(recovered)) == 1
    assert event.event_id in blocks(recovered)[0].content
    assert "current" in blocks(recovered)[0].content
    assert recovered[0] is source[0]
    assert recovered.index(blocks(recovered)[0]) < recovered.index(source[1])
    assert conversation_layer_fingerprint(recovered) == before
    assert len(load_conversation_events(tmp_path, "s")) == 1
    assert len(blocks(restore(tmp_path, recovered))) == 1


def test_keeps_tool_history_without_duplicate_recovery(tmp_path):
    items = todo()
    write_todo(tmp_path, items)
    source = [SystemMessage("stable"), HumanMessage("request"),
              AIMessage("", tool_calls=[{"id": "todo", "name": "todo_write", "args": {"todos": items}}]),
              ToolMessage(todo_write(items), tool_call_id="todo")]
    assert restore(tmp_path, source) == source


@pytest.mark.parametrize("items", [[], todo(status="completed")])
def test_latest_clear_or_completion_removes_old_recovery(tmp_path, items):
    write_todo(tmp_path, todo("old"))
    recovered = restore(tmp_path)
    write_todo(tmp_path, items, call="next")
    assert not blocks(restore(tmp_path, recovered))


@pytest.mark.parametrize("status,result,items", [
    ("failed", "failure", todo("bad")),
    ("done", json.dumps({"status": "error"}), todo("bad")),
    ("done", "ok", [{"content": "bad", "status": "bogus"}]),
])
def test_failed_or_malformed_updates_do_not_replace_valid_snapshot(tmp_path, status, result, items):
    write_todo(tmp_path, todo("valid"))
    write_todo(tmp_path, items, call="bad", status=status, result=result)
    text = blocks(restore(tmp_path))[0].content
    assert '"content": "valid"' in text
    assert '"content": "bad"' not in text


def test_session_isolation_and_new_question_do_not_revive_old_plan(tmp_path):
    write_todo(tmp_path, todo("old"), turn="old")
    assert not blocks(restore(tmp_path, session="other"))
    assert not blocks(restore(tmp_path, turn="new", prompt="another question"))
    assert blocks(restore(tmp_path, turn="new", prompt="继续"))
    append_conversation_event(tmp_path, "s", "new", EVENT_USER_MESSAGE, payload={"content": "another question"})
    assert not blocks(restore(tmp_path, turn="new", prompt="继续"))


def test_recovery_is_bounded_and_task_text_is_labeled_as_data(tmp_path):
    write_todo(tmp_path, todo("x" * 100_000))
    text = blocks(restore(tmp_path))[0].content
    assert len(text) < 16_000
    assert "data" in text.lower()


def test_no_todo_is_no_change(tmp_path):
    source = [SystemMessage("stable"), HumanMessage("request")]
    assert restore(tmp_path, source) == source


def test_inactive_branch_cannot_restore_a_superseded_todo(tmp_path):
    from core.chat.conversation_ledger import EVENT_BRANCH_REBASE

    first = write_todo(tmp_path, todo("active"))
    write_todo(tmp_path, todo("discarded"), call="discarded")
    append_conversation_event(
        tmp_path, "s", "replacement", EVENT_BRANCH_REBASE,
        parent_event_id=first.event_id,
        payload={"operation": "edit", "fromEventId": first.event_id, "branchId": "replacement"},
    )
    text = blocks(restore(tmp_path))[0].content
    assert '"content": "active"' in text
    assert "discarded" not in text


def test_late_result_from_old_task_cannot_cross_a_new_request(tmp_path):
    append_conversation_event(tmp_path, "s", "old", EVENT_USER_MESSAGE, payload={"content": "old task"})
    append_conversation_event(tmp_path, "s", "new", EVENT_USER_MESSAGE, payload={"content": "new task"})
    write_todo(tmp_path, todo("old task result"), turn="old")
    append_conversation_event(tmp_path, "s", "continue", EVENT_USER_MESSAGE, payload={"content": "继续"})
    assert not blocks(restore(tmp_path, turn="continue", prompt="继续"))


@pytest.mark.parametrize("kind", ["user_guidance", "user_interrupt_guidance", "control_notice"])
def test_guidance_and_invisible_control_notice_preserve_task_scope(tmp_path, kind):
    append_conversation_event(tmp_path, "s", "t", EVENT_USER_MESSAGE, payload={"content": "original task"})
    write_todo(tmp_path, todo())
    append_conversation_event(
        tmp_path, "s", "t" if kind != "control_notice" else "notice", EVENT_USER_MESSAGE,
        payload={"content": "注意用中文", "metadata": {"kind": kind}},
        visible_in_model=kind != "control_notice",
    )
    assert len(blocks(restore(tmp_path))) == 1


def test_model_invisible_todo_cannot_supply_recovery(tmp_path):
    append_conversation_event(
        tmp_path, "s", "t", EVENT_TOOL_RESULT, status="done", visible_in_model=False,
        payload={"toolCall": {"name": "todo_write", "arguments": {"todos": todo()}}},
    )
    assert not blocks(restore(tmp_path))


@pytest.mark.parametrize("hard_limit,expected_blocked", [(20_000, False), (100, True)])
def test_compression_recovers_before_hard_budget_gate(tmp_path, monkeypatch, hard_limit, expected_blocked):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import core.orchestration.turn_compression as compression
    from tools.compression_strategy import CompressionLevel

    write_todo(tmp_path, todo())
    source = [SystemMessage("stable"), HumanMessage("request"), AIMessage("old history " * 1000)]
    kept = source[:2]
    scenes = []
    monkeypatch.setattr(compression, "resolve_feature_decision", lambda *a, **k: SimpleNamespace(effective_enabled=True))
    result, blocked, applied, *_ = compression.compress_turn_messages(
        messages=source, iteration=1,
        token_compressor=SimpleNamespace(compress=lambda *a, **k: (kept, "")),
        config=SimpleNamespace(context_compression=SimpleNamespace(max_compressions_per_session=3)),
        effective_max_token_limit=30_000, threshold_tokens=20_000,
        project_root=str(tmp_path), mode=compression.AgentMode.CHAT,
        turn_runtime_fn=lambda: {"sessionId": "s", "runId": "t"},
        compression_strategy=SimpleNamespace(
            determine_level_with_iteration=lambda *a: CompressionLevel.STANDARD,
            get_config=lambda *a: SimpleNamespace(summary_max_chars=1000, keep_ai_messages=1, preserve_errors=True),
        ),
        estimate_tokens_fn=lambda messages: sum(len(str(getattr(m, "content", ""))) for m in messages),
        get_ui_fn=lambda: Mock(), get_state_manager_fn=lambda: Mock(),
        scene_recorder_fn=lambda *a, **k: scenes.append((a, k)),
        context_input_hard_limit=hard_limit,
    )
    assert blocked is expected_blocked
    if blocked:
        assert result == source
        assert not applied
        assert any(args[1] == "agent.context_budget_exhausted" for args, _ in scenes)
    else:
        assert applied
        assert len(blocks(result)) == 1


def test_checkpoint_seed_and_continue_restore_original_journal_todo(tmp_path):
    from core.chat.context_assembler import assemble_conversation_context
    from core.chat.conversation_ledger import append_context_compression_checkpoint
    from core.orchestration.turn_message_assembly import langchain_messages_from_conversation_layer

    append_conversation_event(tmp_path, "s", "old", EVENT_USER_MESSAGE, payload={"content": "original task"})
    write_todo(tmp_path, todo("unfinished"), turn="old")
    append_context_compression_checkpoint(
        tmp_path, "s", turn_id="checkpoint", current_turn_id="new", summary="summary without checklist",
        level="standard", reason="test", before_tokens=20_000, after_tokens=100,
    )
    append_conversation_event(tmp_path, "s", "new", EVENT_USER_MESSAGE, payload={"content": "继续"})
    seed = assemble_conversation_context(
        [], session_id="s", current_turn_id="new", recent_message_limit=None,
        ledger_events=load_conversation_events(tmp_path, "s"),
    )
    assert not any(m.get("tool_calls") for m in seed.history_messages)
    messages = langchain_messages_from_conversation_layer(seed.history_messages) + [HumanMessage("继续")]
    recovered = restore(tmp_path, messages, turn="new", prompt="继续")
    assert "unfinished" in blocks(recovered)[0].content
    assert conversation_layer_fingerprint(recovered) == conversation_layer_fingerprint(messages)
