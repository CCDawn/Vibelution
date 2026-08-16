from core.orchestration.round_state import RoundStateController


def test_note_response_tools_coerces_string_and_invalid_counts():
    state = RoundStateController(max_iterations=5)
    state.note_response_tools("2", "", tool_names=["read_file_tool", "grep_search_tool"])
    assert state.last_response_tool_call_count == 2
    assert state.consecutive_tool_only_steps == 1
    assert state.substantive_tool_calls == 2

    state.note_response_tools("bad", "")
    assert state.last_response_tool_call_count == 0
    assert state.consecutive_tool_only_steps == 0
    assert state.no_new_evidence_steps == 1


def test_unnamed_tool_batch_is_substantive_not_bookkeeping():
    state = RoundStateController(max_iterations=5)
    state.note_response_tools(2, "", tool_names=[])
    assert state.consecutive_bookkeeping_tool_only_steps == 0
    assert state.consecutive_tool_only_steps == 1
    assert state.no_new_evidence_steps == 0
    assert state.substantive_tool_calls == 2

    state.note_response_tools(1, "", tool_names=["task_list_tool"])
    assert state.consecutive_bookkeeping_tool_only_steps == 1
    assert state.consecutive_tool_only_steps == 0
    assert state.substantive_tool_calls == 2


def test_counters_and_acting_status_coerce_invalid_ints():
    state = RoundStateController(max_iterations=3)
    state.add_tool_calls("3")
    state.add_xml_tool_calls("nope")
    state.add_token_usage("12", "not-a-number")
    assert state.total_tool_calls == 3
    assert state.total_input_tokens == 12
    assert state.total_output_tokens == 0
    assert state.acting_status("4")["tool_count"] == 7
    assert state.acting_status("bad")["tool_count"] == 3


def test_note_response_tools_rejects_character_split_and_decodes_bytes_names():
    state = RoundStateController(max_iterations=5)
    state.note_response_tools(1, "", tool_names="read_file_tool")
    assert state.substantive_tool_calls == 1
    assert state.consecutive_tool_only_steps == 1

    state.note_response_tools(
        2,
        b"",
        tool_names='[{"name":"read_file_tool"},{"toolName":"grep_search_tool"}]',
    )
    assert state.substantive_tool_calls == 3
    assert state.consecutive_tool_only_steps == 2

    state.note_response_tools(1, "", tool_names=[b"task_list_tool"])
    assert state.consecutive_bookkeeping_tool_only_steps == 1
    assert state.consecutive_tool_only_steps == 0


def test_round_state_coerces_false_flags_bytes_outcome_and_string_max_iterations():
    state = RoundStateController(max_iterations="2")
    assert state.max_iterations == 2
    state.note_delegation("false")
    assert state.delegation_failures == 1
    assert state.no_new_evidence_steps == 1

    state.note_progress()
    state.next_iteration()
    state.next_iteration()
    state.note_response_tools(0, visible_text=b"final")
    state.note_turn_outcome(b"final_answer")
    assert state.last_turn_outcome_kind == "final_answer"
    assert state.finish_success("false") is True
    assert state.exhausted_without_final_answer() is False
    assert state.thinking_status(b"goal-1")["goal"] == "goal-1"

    stalled = RoundStateController(max_iterations=1)
    stalled.note_response_tools(True, "")
    assert stalled.last_response_tool_call_count == 0

    flagged = RoundStateController(max_iterations=b"5")
    flagged.note_response_tools(
        2,
        "",
        tool_names={"read_file_tool": True, "task_list_tool": bytearray(b"false")},
    )
    assert flagged.substantive_tool_calls == 1
    assert flagged.consecutive_tool_only_steps == 1
    json_map = RoundStateController(max_iterations=5)
    json_map.note_response_tools(
        1,
        "",
        tool_names='{"task_list_tool":"true","read_file_tool":"false"}',
    )
    assert json_map.substantive_tool_calls == 0
    assert json_map.consecutive_bookkeeping_tool_only_steps == 1
