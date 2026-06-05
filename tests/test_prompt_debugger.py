from tests import prompt_debugger as pd


def test_extract_tool_calls_parses_bracket_tool_call_block():
    text = """
    [TOOL_CALL]
    {tool => "cli_tool", args => {
      --command "dir"
      --cwd "."
      --hint "列出目录"
    }}
    [/TOOL_CALL]
    """

    calls = pd._extract_tool_calls(text)

    assert calls
    assert calls[0]["name"] == "cli_tool"
    assert calls[0]["args"]["command"] == "dir"
    assert calls[0]["args"]["cwd"] == "."
    assert calls[0]["args"]["hint"] == "列出目录"


def test_extract_tool_calls_parses_simple_tool_call_block():
    text = """
    <tool_call>
    search_memory_tool
    query="test"
    </tool_call>
    """

    calls = pd._extract_tool_calls(text)

    assert calls
    assert calls[0]["name"] == "search_memory_tool"
    assert calls[0]["args"]["query"] == "test"


def test_prompt_debugger_suites_track_current_tool_names():
    shell = pd.TOOL_TEST_SUITES["shell_tools"]["scenarios"][0]
    memory_write = pd.TOOL_TEST_SUITES["memory_tools"]["scenarios"][0]
    memory_read = pd.TOOL_TEST_SUITES["memory_tools"]["scenarios"][1]
    search = pd.TOOL_TEST_SUITES["search_tools"]["scenarios"][0]
    child_create = pd.TOOL_TEST_SUITES["create_child_session_tool"]["scenarios"][0]
    child_list = pd.TOOL_TEST_SUITES["list_child_sessions_tool"]["scenarios"][0]

    assert shell["expected_tool"] == "cli_tool"
    assert memory_write["expected_tool"] == "record_learning_tool"
    assert memory_read["expected_tool"] == "search_memory_tool"
    assert search["expected_tool"] == "web_search_tool"
    assert child_create["expected_tool"] == "create_child_session_tool"
    assert child_list["expected_tool"] == "list_child_sessions_tool"


def test_prompt_debugger_quick_verify_child_session_tools_registered():
    create_result = pd._quick_verify_tool("create_child_session_tool")
    list_result = pd._quick_verify_tool("list_child_sessions_tool")

    assert create_result["registered"] is True
    assert create_result["source"] == "Key_Tools"
    assert "user_request" in create_result["params"]
    assert "auto_start" in create_result["params"]
    assert list_result["registered"] is True
    assert list_result["source"] == "Key_Tools"
    assert "parent_session_id" in list_result["params"]
