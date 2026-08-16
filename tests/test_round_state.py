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
